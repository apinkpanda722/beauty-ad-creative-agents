"""Tenant-keyed feedback MERGE with atomic replacement of its ABOUT set."""

import json
from collections.abc import Sequence
from datetime import UTC

from beautyads.domain.feedback_sync import TENANT_PATTERN, SyncFeedback
from beautyads.domain.labels import Claim, HookType
from beautyads.graph.connection import GraphConnection

_HOOK_VALUES = frozenset(value.value for value in HookType)
_CLAIM_VALUES = frozenset(value.value for value in Claim)

# GraphConnection.run is one transaction, including deletion and replacement.
REPLACE_FEEDBACK = """
    MERGE (f:Feedback {tenant_id: $tenant_id, feedback_id: $feedback_id})
    SET f.plan_id = $plan_id, f.decision = $decision, f.created_at = $created_at
    CALL {
        WITH f
        MATCH (f)-[old:ABOUT]->()
        DELETE old
        RETURN count(*) AS removed_about
    }
    FOREACH (value IN $hooks |
        MERGE (h:Hook {value: value})
        MERGE (f)-[:ABOUT]->(h)
    )
    FOREACH (value IN $claims |
        MERGE (e:Efficacy {value: value})
        MERGE (f)-[:ABOUT]->(e)
    )
"""

FEEDBACK_STATE = """
    MATCH (f:Feedback {tenant_id: $tenant_id, feedback_id: $feedback_id})
    OPTIONAL MATCH (f)-[:ABOUT]->(pattern)
    RETURN properties(f) AS feedback, labels(pattern) AS pattern_type,
           pattern.value AS pattern
"""


def _valid(item: SyncFeedback) -> bool:
    return (
        isinstance(item.tenant_id, str)
        and TENANT_PATTERN.fullmatch(item.tenant_id) is not None
        and item.decision in ("approved", "rejected")
        and (
            item.hook_type is None
            or isinstance(item.hook_type, str)
            and item.hook_type in _HOOK_VALUES
        )
        and all(
            isinstance(value, str) and value in _CLAIM_VALUES for value in item.claims
        )
    )


def load_feedback(graph: GraphConnection, items: Sequence[SyncFeedback]) -> dict:
    report = {
        "loaded": 0,
        "rejected": 0,
        "errors": [],
        "nodes_created": 0,
        "relationships_created": 0,
    }
    for item in items:
        if not _valid(item):
            report["rejected"] += 1
            report["errors"].append(
                {"code": "FEEDBACK_VALUE_INVALID", "feedback_id": item.feedback_id}
            )
            continue
        created_at = (
            item.created_at.replace(tzinfo=UTC)
            if item.created_at.tzinfo is None
            else item.created_at.astimezone(UTC)
        )
        result = graph.run(
            REPLACE_FEEDBACK,
            {
                "tenant_id": item.tenant_id,
                "feedback_id": item.feedback_id,
                "plan_id": item.plan_id,
                "decision": item.decision,
                "created_at": created_at.isoformat(),
                "hooks": [item.hook_type] if item.hook_type is not None else [],
                "claims": sorted(set(item.claims)),
            },
        )
        report["loaded"] += 1
        report["nodes_created"] += result.nodes_created
        report["relationships_created"] += result.relationships_created
    return report


def read_feedback_state(
    graph: GraphConnection, items: Sequence[SyncFeedback]
) -> list[str]:
    """Compare semantic sets on replay, since ABOUT edges are replaced."""
    records = []
    for item in items:
        if _valid(item):
            result = graph.run(
                FEEDBACK_STATE,
                {
                    "tenant_id": item.tenant_id,
                    "feedback_id": item.feedback_id,
                },
            )
            records.extend(
                json.dumps(row, sort_keys=True, ensure_ascii=False, default=str)
                for row in result.records
            )
    return sorted(records)
