"""Public domain types and repository contracts shared across layers."""

from beautyads.domain.creative import (
    CollectionStat,
    Creative,
    CreativeKey,
    JobStatus,
    Metrics,
    Source,
    is_analyzable,
)
from beautyads.domain.jobs import JobResult
from beautyads.domain.labels import HookResult, HookType
from beautyads.domain.protocols import AnalysisRepository, CreativeRepository

__all__ = [
    "AnalysisRepository",
    "CollectionStat",
    "Creative",
    "CreativeKey",
    "CreativeRepository",
    "HookResult",
    "HookType",
    "JobResult",
    "JobStatus",
    "Metrics",
    "Source",
    "is_analyzable",
]
