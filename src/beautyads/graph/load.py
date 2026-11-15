"""Batched, parameterized MERGE of creatives and validated final label axes."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from beautyads.domain.labels import (
    Angle,
    Category,
    ContentType,
    CtaType,
    Format,
    HookType,
    Talent,
)
from beautyads.domain.sync import SyncCreative, SyncLabel
from beautyads.graph.connection import GraphConnection, GraphError

# All interpolated Cypher identifiers come exclusively from these constants.
AXES = (
    ("hook_type", "Hook", "USES_HOOK", HookType),
    ("angle", "Angle", "HAS_ANGLE", Angle),
    ("format", "Format", "HAS_FORMAT", Format),
    ("talent", "Talent", "FEATURES", Talent),
    ("cta_type", "CtaType", "HAS_CTA", CtaType),
)
CREATIVE_PROPERTIES = (
    "source",
    "source_id",
    "url",
    "published_at",
    "duration_s",
    "language",
    "brand",
    "latest_view_count",
    "latest_like_count",
    "latest_comment_count",
    "metrics_collected_at",
)
MERGE_CREATIVE = """
    UNWIND $rows AS row
    MERGE (c:Creative {source: row.source, source_id: row.source_id})
    SET c += row.properties
"""
CLEAN_AXES = {
    field: f"""
        UNWIND $rows AS row
        MATCH (c:Creative {{source: row.source, source_id: row.source_id}})
              -[r:{relationship}]->(n:{label})
        WHERE row.value IS NULL OR n.value IS NULL OR n.value <> row.value
        DELETE r
    """
    for field, label, relationship, _ in AXES
}
MERGE_AXES = {
    field: f"""
        UNWIND $rows AS row
        MERGE (c:Creative {{source: row.source, source_id: row.source_id}})
        MERGE (n:{label} {{value: row.value}})
        MERGE (c)-[r:{relationship}]->(n)
    """
    + (" SET r.description = row.description" if field == "hook_type" else "")
    for field, label, relationship, _ in AXES
}


@dataclass
class LoadReport:
    nodes_created: int = 0
    relationships_created: int = 0
    skipped_invalid: int = 0


def _prepare(creative, jobs, run_tag, report):
    labels = {
        axis: next(
            (
                job.labels
                for job in jobs
                if job.kind == f"{axis}@{run_tag}" and job.status == "done"
            ),
            None,
        )
        or {}
        for axis in ("content_type", "hook", "full")
    }

    def valid(value, enum):
        if value is None:
            return None
        if isinstance(value, str) and value in {item.value for item in enum}:
            return value
        report.skipped_invalid += 1
        return None

    properties = {name: creative.properties.get(name) for name in CREATIVE_PROPERTIES}
    for name in ("latest_view_count", "latest_like_count", "latest_comment_count"):
        value = properties.get(name)
        properties[name] = int(value) if value is not None else None
    properties["content_type"] = valid(
        labels["content_type"].get("content_type"), ContentType
    )
    product = properties["content_type"] == ContentType.product_creative
    properties["category"] = (
        valid(labels["content_type"].get("category"), Category) if product else None
    )
    row = {
        "source": creative.key.source.value,
        "source_id": creative.key.source_id,
        "properties": properties,
    }
    axes = {}
    for field, _, _, enum in AXES:
        job = labels["hook" if field == "hook_type" else "full"]
        value = valid(job.get(field), enum) if product else None
        axes[field] = {
            "source": row["source"],
            "source_id": row["source_id"],
            "value": value,
        }
        if field == "hook_type":
            description = job.get("hook_description")
            axes[field]["description"] = (
                description if isinstance(description, str) else None
            )
    return row, axes


def load_creatives(
    graph: GraphConnection,
    entries: Sequence[tuple[SyncCreative, Sequence[SyncLabel]]],
    *,
    run_tag: str,
    batch_size: int = 500,
) -> LoadReport:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    report = LoadReport()

    def execute(query: str, rows: list[dict[str, Any]]) -> None:
        result = graph.run(query, {"rows": rows})
        report.nodes_created += result.nodes_created
        report.relationships_created += result.relationships_created

    for offset in range(0, len(entries), batch_size):
        prepared = [
            _prepare(creative, jobs, run_tag, report)
            for creative, jobs in entries[offset : offset + batch_size]
        ]
        execute(MERGE_CREATIVE, [row for row, _ in prepared])
        for field, _, _, _ in AXES:
            rows = [axes[field] for _, axes in prepared]
            # Remove obsolete assignments only. Replaying unchanged labels creates
            # no relationships, while a reclassification reflects the PG source.
            execute(CLEAN_AXES[field], rows)
            valid_rows = [row for row in rows if row["value"] is not None]
            if valid_rows:
                execute(MERGE_AXES[field], valid_rows)
    return report


def verify_counts(graph: GraphConnection) -> dict[str, int]:
    def count(query, params=None):
        result = graph.run(query, params)
        if len(result.records) != 1:
            raise GraphError("GRAPH_VERIFY_FAILED")
        value = result.records[0].get("count")
        if not isinstance(value, int):
            raise GraphError("GRAPH_VERIFY_FAILED")
        return value

    creative_count = count("MATCH (c:Creative) RETURN count(c) AS count")
    invalid = sum(
        count(
            f"MATCH (n:{label}) WHERE n.value IS NULL OR NOT n.value IN $values "
            "RETURN count(n) AS count",
            {"values": [value.value for value in enum]},
        )
        for _, label, _, enum in AXES
    )
    return {"creative_count": creative_count, "invalid_values": invalid}


def count_axis_relationships(graph: GraphConnection) -> int:
    """Count the classification-axis relationships that hang off creatives."""
    total = 0
    for _, label, relationship, _ in AXES:
        result = graph.run(
            f"MATCH (:Creative)-[r:{relationship}]->(:{label}) RETURN count(r) AS count"
        )
        if len(result.records) != 1:
            raise GraphError("GRAPH_VERIFY_FAILED")
        value = result.records[0].get("count")
        if not isinstance(value, int):
            raise GraphError("GRAPH_VERIFY_FAILED")
        total += value
    return total
