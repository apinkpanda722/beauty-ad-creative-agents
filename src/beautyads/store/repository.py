"""Parameterized persistence for public creatives and their analysis jobs."""

import json
from collections.abc import Collection, Mapping, Sequence
from typing import Any

from beautyads.domain import (
    AnalysisRepository,
    CollectionStat,
    Creative,
    CreativeKey,
    CreativeRepository,
    JobResult,
    JobStatus,
    Metrics,
    Source,
    is_analyzable,
)
from beautyads.store.connection import SqlConnection
from beautyads.store.schema import INSERT_COLUMNS, build_upsert_sql

CREATIVE_COLUMNS: tuple[str, ...] = (
    "source",
    "source_id",
    "url",
    "title",
    "caption",
    "published_at",
    "duration_s",
    "language",
    "analyzable",
    "brand",
    "account",
    "latest_view_count",
    "latest_like_count",
    "latest_comment_count",
    "collected_at",
    "attributes",
)


def _creative_values(creative: Creative) -> dict[str, Any]:
    values = creative.model_dump(exclude={"metrics"})
    values["source"] = creative.source.value
    values["attributes"] = json.dumps(creative.attributes, sort_keys=True)
    values.update(
        {
            f"latest_{name}": value
            for name, value in creative.metrics.model_dump().items()
        }
    )
    return values


def _restore_creative(row: Sequence[Any]) -> Creative:
    values = dict(zip(CREATIVE_COLUMNS, row, strict=True))
    attributes = values["attributes"]
    values["attributes"] = {} if attributes is None else dict(attributes)
    values["metrics"] = Metrics(
        view_count=values.pop("latest_view_count"),
        like_count=values.pop("latest_like_count"),
        comment_count=values.pop("latest_comment_count"),
    )
    return Creative.model_validate(values)


class PostgresCreativeStore(CreativeRepository, AnalysisRepository):
    def __init__(self, conn: SqlConnection):
        self.conn = conn

    def _read(self, query: str, params: Sequence[Any], *, one: bool = False):
        """읽기 메서드는 이 헬퍼로 트랜잭션을 닫는다.

        연결을 여러 스레드가 공유하면 호출자가 모든 저장소 호출(읽기 포함)을
        직렬화해야 한다. 읽기의 rollback()은 연결 단위라 다른 스레드가 쓰기
        도중에 열어 둔 트랜잭션을 끝낸다.
        """
        try:
            cursor = self.conn.execute(query, params)
            rows = cursor.fetchone() if one else cursor.fetchall()
        except Exception:
            self.conn.rollback()
            raise
        self.conn.rollback()
        return rows

    def requeue_jobs(self, kind: str, error_codes: Collection[str]) -> int:
        if not error_codes:
            return 0
        try:
            cursor = self.conn.execute(
                """UPDATE analysis_jobs SET status='pending', updated_at=now()
                   WHERE kind=%s AND status='failed' AND error_code = ANY(%s)""",
                (kind, list(error_codes)),
            )
            count = cursor.rowcount
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return count

    def job_counts(self, kind: str) -> dict[str, int]:
        rows = self._read(
            """SELECT status, count(*) FROM analysis_jobs
               WHERE kind = %s GROUP BY status""",
            (kind,),
        )
        counts = {status.value: 0 for status in JobStatus}
        counts.update(rows)
        return counts

    def get_job_results(
        self, kind: str, keys: Sequence[CreativeKey]
    ) -> list[JobResult]:
        # Keep each statement well below PostgreSQL's bind-parameter limit.
        batch_size = 500
        results = []
        columns = (
            "source",
            "source_id",
            "kind",
            "status",
            "labels",
            "error_code",
            "model",
            "thinking_level",
            "prompt_version",
            "raw_output",
            "attempts",
            "updated_at",
        )
        for offset in range(0, len(keys), batch_size):
            batch = keys[offset : offset + batch_size]
            placeholders = ", ".join("(%s, %s)" for _ in batch)
            params = (
                kind,
                *(
                    value
                    for key in batch
                    for value in (key.source.value, key.source_id)
                ),
            )
            rows = self._read(
                f"""SELECT j.source, j.source_id, j.kind, j.status, j.labels,
                           j.error_code, m.model, m.thinking_level, m.prompt_version,
                           m.raw_output, j.attempts, j.updated_at
                    FROM analysis_jobs AS j
                    LEFT JOIN model_outputs AS m
                      ON m.source = j.source AND m.source_id = j.source_id
                         AND m.kind = j.kind
                         AND m.id = (SELECT max(o.id) FROM model_outputs AS o
                                     WHERE o.source = j.source AND o.source_id = j.source_id
                                       AND o.kind = j.kind)
                    WHERE j.kind = %s AND (j.source, j.source_id) IN ({placeholders})""",
                params,
            )
            for row in rows:
                values = dict(zip(columns, row, strict=True))
                key = CreativeKey(
                    source=values.pop("source"), source_id=values.pop("source_id")
                )
                labels = values["labels"]
                if labels is not None:
                    values["labels"] = (
                        json.loads(labels) if isinstance(labels, str) else dict(labels)
                    )
                results.append(JobResult(key=key, **values))
        return results

    def list_creatives(
        self,
        *,
        brands: Collection[str] | None = None,
        sources: Collection[Source] | None = None,
        analyzable_only: bool = False,
        limit: int | None = None,
    ) -> list[Creative]:
        if (brands is not None and not brands) or (sources is not None and not sources):
            return []
        conditions = []
        params: list[Any] = []
        if brands is not None:
            conditions.append("brand = ANY(%s)")
            params.append(list(brands))
        if sources is not None:
            conditions.append("source = ANY(%s)")
            params.append([source.value for source in sources])
        if analyzable_only:
            conditions.append("analyzable IS TRUE")
        columns = ", ".join(CREATIVE_COLUMNS)
        query = f"SELECT {columns} FROM creatives"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY published_at DESC NULLS LAST, source, source_id"
        if limit is not None:
            query += " LIMIT %s"
            params.append(limit)
        rows = self._read(query, tuple(params))
        return [_restore_creative(row) for row in rows]

    def upsert_creatives(self, creatives: Sequence[Creative]) -> int:
        try:
            unique = {creative.key: creative for creative in creatives}
            sql = build_upsert_sql()
            for creative in unique.values():
                values = _creative_values(creative)
                values["metrics_collected_at"] = creative.collected_at
                self.conn.execute(
                    sql, tuple(values[column] for column in INSERT_COLUMNS)
                )
                # Matching values must still advance the metrics watermark, or
                # an older intermediate snapshot could later replace them.
                self.conn.execute(
                    """UPDATE creatives SET metrics_collected_at = %s,
                           collected_at = GREATEST(collected_at, %s)
                       WHERE source = %s AND source_id = %s
                         AND (metrics_collected_at IS NULL OR metrics_collected_at <= %s)""",
                    (
                        creative.collected_at,
                        creative.collected_at,
                        creative.source.value,
                        creative.source_id,
                        creative.collected_at,
                    ),
                )
                self.conn.execute(
                    """INSERT INTO metrics_history
                           (source, source_id, collected_at, view_count, like_count, comment_count)
                       VALUES (%s, %s, %s, %s, %s, %s)
                       ON CONFLICT (source, source_id, collected_at) DO NOTHING""",
                    (
                        creative.source.value,
                        creative.source_id,
                        creative.collected_at,
                        creative.metrics.view_count,
                        creative.metrics.like_count,
                        creative.metrics.comment_count,
                    ),
                )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return len(unique)

    def get_creative(self, key: CreativeKey) -> Creative | None:
        columns = ", ".join(CREATIVE_COLUMNS)
        row = self._read(
            f"SELECT {columns} FROM creatives WHERE source = %s AND source_id = %s",
            (key.source.value, key.source_id),
            one=True,
        )
        return None if row is None else _restore_creative(row)

    def collection_stats(self) -> list[CollectionStat]:
        rows = self._read(
            """SELECT source, brand, account, count(*) AS total,
                      count(*) FILTER (WHERE analyzable = %s) AS analyzable_true,
                      count(*) FILTER (WHERE analyzable = %s) AS analyzable_false,
                      count(*) FILTER (WHERE analyzable IS NULL) AS analyzable_null,
                      max(collected_at) AS last_collected_at
               FROM creatives
               GROUP BY source, brand, account
               ORDER BY source, brand, account""",
            (True, False),
        )
        return [
            CollectionStat.model_validate(
                dict(zip(CollectionStat.model_fields, row, strict=True))
            )
            for row in rows
        ]

    def enqueue_analysis(self, kind: str, creatives: Sequence[Creative]) -> int:
        inserted = 0
        try:
            for creative in creatives:
                if not is_analyzable(creative):
                    continue
                cursor = self.conn.execute(
                    """INSERT INTO analysis_jobs (source, source_id, kind, status)
                       VALUES (%s, %s, %s, %s)
                       ON CONFLICT (source, source_id, kind) DO NOTHING""",
                    (
                        creative.source.value,
                        creative.source_id,
                        kind,
                        JobStatus.pending.value,
                    ),
                )
                inserted += cursor.rowcount
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return inserted

    def next_pending(self, kind: str, limit: int) -> list[Creative]:
        columns = ", ".join(f"c.{column}" for column in CREATIVE_COLUMNS)
        rows = self._read(
            f"""SELECT {columns} FROM creatives AS c
                JOIN analysis_jobs AS j ON c.source = j.source AND c.source_id = j.source_id
                WHERE j.kind = %s AND j.status = %s
                ORDER BY c.published_at DESC NULLS LAST
                LIMIT %s""",
            (kind, JobStatus.pending.value, limit),
        )
        return [_restore_creative(row) for row in rows]

    def record_analysis(
        self,
        kind: str,
        key: CreativeKey,
        *,
        status: JobStatus,
        model: str | None,
        thinking_level: str | None,
        prompt_version: str | None,
        raw_output: str | None,
        labels: Mapping[str, str] | None,
        error_code: str | None,
    ) -> None:
        try:
            if raw_output is not None:
                self.conn.execute(
                    """INSERT INTO model_outputs
                           (source, source_id, kind, model, thinking_level, prompt_version, raw_output)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (
                        key.source.value,
                        key.source_id,
                        kind,
                        model,
                        thinking_level,
                        prompt_version,
                        raw_output,
                    ),
                )
            self.conn.execute(
                """UPDATE analysis_jobs SET status = %s, error_code = %s, labels = %s::jsonb,
                       attempts = attempts + 1, updated_at = now()
                   WHERE source = %s AND source_id = %s AND kind = %s""",
                (
                    status.value,
                    error_code,
                    None if labels is None else json.dumps(dict(labels)),
                    key.source.value,
                    key.source_id,
                    kind,
                ),
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
