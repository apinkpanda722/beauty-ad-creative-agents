"""MFDS facts and conservative, per-kind functional certification decisions."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict


class IngredientStandard(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name_ko: str | None = None
    name_en: str | None = None
    cas_no: str | None = None


class CertStatus(StrEnum):
    # Neither API supplies evidence of absence; null and missing mean unknown.
    certified = "certified"
    unknown = "unknown"


class FunctionalKind(StrEnum):
    brightening = "brightening"
    anti_aging = "anti_aging"
    sun_protection = "sun_protection"


class FunctionalReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    item_name: str | None = None
    entp_name: str | None = None
    report_date: str | None = None
    effect_text: str | None = None
    spf: str | None = None
    pa: str | None = None
    cancelled: bool | None = None
    cancelled_raw: str | None = None
    source: Literal["report", "screening"]


def functional_kinds(report: FunctionalReport) -> dict[FunctionalKind, CertStatus]:
    """Return every kind's status, retaining unknowns rather than an empty set.

    Only efficacy text supports brightening/wrinkle improvement. Sun protection
    requires populated SPF/PA fields from the report API; names and screening
    XML, even when they mention SPF, cannot establish that status.
    """
    statuses = dict.fromkeys(FunctionalKind, CertStatus.unknown)
    if report.cancelled is True:
        return statuses
    effect = "".join((report.effect_text or "").split())
    if "미백" in effect:
        statuses[FunctionalKind.brightening] = CertStatus.certified
    if "주름개선" in effect:
        statuses[FunctionalKind.anti_aging] = CertStatus.certified
    if report.source == "report" and any(
        value is not None and value.strip() for value in (report.spf, report.pa)
    ):
        statuses[FunctionalKind.sun_protection] = CertStatus.certified
    return statuses
