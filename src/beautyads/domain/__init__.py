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
from beautyads.domain.labels import (
    Angle,
    Category,
    Claim,
    ContentType,
    ContentTypeResult,
    CtaType,
    Format,
    FullResult,
    HookResult,
    HookType,
    PlatformFitFlags,
    StructureFlags,
    Talent,
)
from beautyads.domain.protocols import AnalysisRepository, CreativeRepository

__all__ = [
    "AnalysisRepository",
    "Angle",
    "Category",
    "Claim",
    "CollectionStat",
    "ContentType",
    "ContentTypeResult",
    "Creative",
    "CreativeKey",
    "CreativeRepository",
    "CtaType",
    "Format",
    "FullResult",
    "HookResult",
    "HookType",
    "JobResult",
    "JobStatus",
    "Metrics",
    "PlatformFitFlags",
    "Source",
    "StructureFlags",
    "Talent",
    "is_analyzable",
]
