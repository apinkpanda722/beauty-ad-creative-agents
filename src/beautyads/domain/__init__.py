"""Public domain types and repository contracts shared across layers."""

from beautyads.domain.creative import (
    Creative,
    CreativeKey,
    JobStatus,
    Metrics,
    Source,
    is_analyzable,
)
from beautyads.domain.labels import HookResult, HookType
from beautyads.domain.protocols import AnalysisRepository, CreativeRepository

__all__ = [
    "AnalysisRepository",
    "Creative",
    "CreativeKey",
    "CreativeRepository",
    "HookResult",
    "HookType",
    "JobStatus",
    "Metrics",
    "Source",
    "is_analyzable",
]
