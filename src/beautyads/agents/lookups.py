"""Injected public graph readers for deterministic checks, without negative inference."""

import re
from collections.abc import Collection

from beautyads.domain.creative import Source
from beautyads.domain.labels import Claim
from beautyads.domain.lookups import CertStatus, SupportStatus
from beautyads.domain.tools import EVIDENCE_ID_PATTERN, GraphReader
from beautyads.graph.evidence_queries import (
    existing_creatives_query,
    product_support_parameters,
    product_support_query,
)


class GraphEvidenceIndex:
    def __init__(self, graph: GraphReader):
        self.graph = graph
        self.last_error: str | None = None

    def existing(self, ids: Collection[str]) -> set[str]:
        self.last_error = None
        valid = list(
            dict.fromkeys(
                value
                for value in ids
                if isinstance(value, str)
                and re.fullmatch(EVIDENCE_ID_PATTERN, value)
                and value.split(":", 1)[0] in Source
            )
        )
        if not valid:
            return set()
        try:
            rows = self.graph.run(existing_creatives_query(), {"ids": valid}).records
            return {
                row.get("creative_id")
                for row in rows
                if row.get("creative_id") in valid
            }
        except Exception:  # noqa: BLE001 -- graph failures must not escape the lookup boundary
            self.last_error = "GRAPH_UNAVAILABLE"
            return set()


class _ProductLookup:
    def __init__(self, graph: GraphReader):
        self.graph = graph
        self.last_error: str | None = None

    def _rows(self, product_url: str, efficacy: Claim) -> list[dict]:
        self.last_error = None
        params = product_support_parameters(product_url=product_url, claim=efficacy)
        try:
            return self.graph.run(product_support_query(), params).records
        except Exception:  # noqa: BLE001 -- keep graph failure distinct from absent links
            self.last_error = "GRAPH_UNAVAILABLE"
            return []


class GraphEfficacySupport(_ProductLookup):
    def efficacy_support(self, product_url: str, efficacy: Claim) -> SupportStatus:
        rows = self._rows(product_url, efficacy)
        if any(
            (row.get("ingredient_count") or 0) > 0
            and (row.get("supporting_count") or 0) > 0
            for row in rows
        ):
            return SupportStatus.supported
        return SupportStatus.unknown


class GraphCertLookup(_ProductLookup):
    def cert_status(self, product_url: str, efficacy: Claim) -> CertStatus:
        self.last_error = None
        claim = Claim(efficacy)
        if claim not in {Claim.brightening, Claim.anti_aging, Claim.sun_protection}:
            return CertStatus.unknown
        if any(
            claim.value in (row.get("certifications") or [])
            for row in self._rows(product_url, claim)
        ):
            return CertStatus.certified
        return CertStatus.unknown
