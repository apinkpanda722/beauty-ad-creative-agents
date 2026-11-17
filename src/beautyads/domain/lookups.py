"""Injected lookup contracts; missing graph links are unknown, not absence."""

from collections.abc import Collection
from enum import StrEnum
from typing import Protocol

from beautyads.domain.labels import Claim


class SupportStatus(StrEnum):
    supported = "supported"
    unsupported = "unsupported"
    unknown = "unknown"


class CertStatus(StrEnum):
    certified = "certified"
    not_certified = "not_certified"
    unknown = "unknown"


class EvidenceIndex(Protocol):
    def existing(self, ids: Collection[str]) -> set[str]: ...


class EfficacySupportLookup(Protocol):
    def efficacy_support(self, product_url: str, efficacy: Claim) -> SupportStatus: ...


class CertLookup(Protocol):
    def cert_status(self, product_url: str, efficacy: Claim) -> CertStatus: ...
