"""Tenant-scoped PostgreSQL memory with injectable connections and bound SQL."""

import json
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from beautyads.domain.tenant import (
    Feedback,
    FeedbackDecision,
    PlanRecord,
    TenantMismatch,
    TenantRepository,
    WorkspaceProfile,
    thread_tenant,
    validate_tenant_id,
)
from beautyads.store.connection import SqlConnection

_PROFILE_COLUMNS = (
    "tenant_id",
    "display_name",
    "brand",
    "own_product_url",
    "tone",
    "forbidden_terms",
    "price_band_pct",
)
_PLAN_COLUMNS = ("tenant_id", "plan_id", "thread_id", "payload", "created_at")
_FEEDBACK_COLUMNS = (
    "tenant_id",
    "plan_id",
    "decision",
    "reason",
    "hook_type",
    "claims",
    "created_at",
)
_JSON_COLUMNS = frozenset({"forbidden_terms", "payload", "claims"})


def _values(record: BaseModel, columns: tuple[str, ...]) -> tuple[Any, ...]:
    data = record.model_dump()
    for column in _JSON_COLUMNS.intersection(data):
        data[column] = json.dumps(data[column], ensure_ascii=False)
    return tuple(data[column] for column in columns)


def _restore[Record: BaseModel](
    model: type[Record], columns: tuple[str, ...], row: Sequence[Any]
) -> Record:
    data = dict(zip(columns, row, strict=True))
    for column in _JSON_COLUMNS.intersection(data):
        if isinstance(data[column], str):
            data[column] = json.loads(data[column])
    return model.model_validate(data)


class PostgresTenantRepository(TenantRepository):
    def __init__(self, conn: SqlConnection):
        self.conn = conn

    def _write(self, query: str, params: Sequence[Any]) -> None:
        try:
            self.conn.execute(query, params)
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def _read(self, query: str, params: Sequence[Any]) -> list[Sequence[Any]]:
        # As in other stores, callers serialize all use of a shared connection.
        try:
            rows = self.conn.execute(query, params).fetchall()
        except Exception:
            self.conn.rollback()
            raise
        self.conn.rollback()
        return rows

    def save_profile(self, tenant_id: str, profile: WorkspaceProfile) -> None:
        tenant_id = validate_tenant_id(tenant_id)
        if profile.tenant_id != tenant_id:
            raise TenantMismatch()
        self._write(
            """INSERT INTO tenant_profiles
               (tenant_id, display_name, brand, own_product_url, tone,
                forbidden_terms, price_band_pct)
               VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)
               ON CONFLICT (tenant_id) DO UPDATE SET
                   display_name = EXCLUDED.display_name, brand = EXCLUDED.brand,
                   own_product_url = EXCLUDED.own_product_url, tone = EXCLUDED.tone,
                   forbidden_terms = EXCLUDED.forbidden_terms,
                   price_band_pct = EXCLUDED.price_band_pct
               WHERE tenant_profiles.tenant_id = %s""",
            (*_values(profile, _PROFILE_COLUMNS), tenant_id),
        )

    def get_profile(self, tenant_id: str) -> WorkspaceProfile | None:
        tenant_id = validate_tenant_id(tenant_id)
        rows = self._read(
            """SELECT tenant_id, display_name, brand, own_product_url, tone,
                      forbidden_terms, price_band_pct
               FROM tenant_profiles WHERE tenant_id = %s""",
            (tenant_id,),
        )
        return _restore(WorkspaceProfile, _PROFILE_COLUMNS, rows[0]) if rows else None

    def save_plan(self, tenant_id: str, plan: PlanRecord) -> None:
        tenant_id = validate_tenant_id(tenant_id)
        if plan.tenant_id != tenant_id or thread_tenant(plan.thread_id) != tenant_id:
            raise TenantMismatch()
        self._write(
            """INSERT INTO tenant_plans
               (tenant_id, plan_id, thread_id, payload, created_at)
               VALUES (%s, %s, %s, %s::jsonb, %s)
               ON CONFLICT (tenant_id, plan_id) DO UPDATE SET
                   thread_id = EXCLUDED.thread_id, payload = EXCLUDED.payload,
                   created_at = EXCLUDED.created_at
               WHERE tenant_plans.tenant_id = %s""",
            (*_values(plan, _PLAN_COLUMNS), tenant_id),
        )

    def get_plan(self, tenant_id: str, plan_id: str) -> PlanRecord | None:
        tenant_id = validate_tenant_id(tenant_id)
        rows = self._read(
            """SELECT tenant_id, plan_id, thread_id, payload, created_at
               FROM tenant_plans WHERE tenant_id = %s AND plan_id = %s""",
            (tenant_id, plan_id),
        )
        return _restore(PlanRecord, _PLAN_COLUMNS, rows[0]) if rows else None

    def add_feedback(self, tenant_id: str, feedback: Feedback) -> None:
        tenant_id = validate_tenant_id(tenant_id)
        if feedback.tenant_id != tenant_id:
            raise TenantMismatch()
        self._write(
            """INSERT INTO tenant_feedback
               (tenant_id, plan_id, decision, reason, hook_type, claims, created_at)
               VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)""",
            _values(feedback, _FEEDBACK_COLUMNS),
        )

    def list_feedback(
        self,
        tenant_id: str,
        *,
        decision: FeedbackDecision | None = None,
        since: datetime | None = None,
        limit: int,
    ) -> list[Feedback]:
        tenant_id = validate_tenant_id(tenant_id)
        if type(limit) is not int or limit <= 0:
            raise ValueError("limit must be a positive integer")
        decision = FeedbackDecision(decision) if decision is not None else None
        rows = self._read(
            """SELECT tenant_id, plan_id, decision, reason, hook_type, claims, created_at
               FROM tenant_feedback WHERE tenant_id = %s
                   AND (%s::text IS NULL OR decision = %s)
                   AND (%s::timestamptz IS NULL OR created_at >= %s)
               ORDER BY created_at DESC, id DESC LIMIT %s""",
            (tenant_id, decision, decision, since, since, limit),
        )
        return [_restore(Feedback, _FEEDBACK_COLUMNS, row) for row in rows]

    def register_thread(self, tenant_id: str, thread_id: str) -> None:
        tenant_id = validate_tenant_id(tenant_id)
        if thread_tenant(thread_id) != tenant_id:
            raise TenantMismatch()
        try:
            # Never overwrite an owner, including concurrent registrations.
            self.conn.execute(
                """INSERT INTO tenant_threads (tenant_id, thread_id)
                   VALUES (%s, %s) ON CONFLICT (thread_id) DO NOTHING""",
                (tenant_id, thread_id),
            )
            rows = self.conn.execute(
                """SELECT tenant_id FROM tenant_threads
                   WHERE tenant_id = %s AND thread_id = %s""",
                (tenant_id, thread_id),
            ).fetchall()
            if not rows or rows[0][0] != tenant_id:
                raise TenantMismatch()
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def assert_thread_access(self, tenant_id: str, thread_id: str) -> None:
        tenant_id = validate_tenant_id(tenant_id)
        if thread_tenant(thread_id) != tenant_id:
            raise TenantMismatch()
        rows = self._read(
            """SELECT tenant_id FROM tenant_threads
               WHERE tenant_id = %s AND thread_id = %s""",
            (tenant_id, thread_id),
        )
        if not rows or rows[0][0] != tenant_id:
            raise TenantMismatch()
