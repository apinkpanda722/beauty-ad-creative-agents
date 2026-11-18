"""Service-independent tool inputs, results, and graph reader contract."""

from collections.abc import Mapping
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

EVIDENCE_ID_PATTERN = r"^[a-z]+:[A-Za-z0-9_-]{1,64}$"


class ToolKind(StrEnum):
    lookup = "lookup"
    aggregate = "aggregate"
    compare = "compare"
    display = "display"


class PriceBand(BaseModel):
    price_min: float
    price_max: float


class ToolContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: str
    as_of: date
    last_collected_at: datetime | None = None
    price_band: PriceBand | None = None


class ToolErrorCode(StrEnum):
    TENANT_CONTEXT_MISSING = "TENANT_CONTEXT_MISSING"
    TOOL_UNKNOWN = "TOOL_UNKNOWN"
    INPUT_INVALID = "INPUT_INVALID"
    GRAPH_UNAVAILABLE = "GRAPH_UNAVAILABLE"
    PRICE_BAND_MISSING = "PRICE_BAND_MISSING"
    TOOL_INTERNAL_ERROR = "TOOL_INTERNAL_ERROR"


class ToolFailure(BaseModel):
    code: ToolErrorCode
    retryable: bool
    message: str


class UiCommand(BaseModel):
    kind: Literal[
        "show_evidence_cards", "show_graph_fragment", "show_distribution", "show_plan"
    ]
    data: dict


class ToolResult(BaseModel):
    tool: str
    kind: ToolKind
    summary: str
    top_rows: list[dict] = Field(max_length=5)
    row_count: int
    evidence_ids: list[str]
    no_evidence: bool
    linked_creative_count: int | None = None
    ui_command: UiCommand | None = None


class GraphRecords(Protocol):
    @property
    def records(self) -> list[dict[str, Any]]: ...


class GraphReader(Protocol):
    def run(
        self, query: str, params: Mapping[str, Any] | None = None
    ) -> GraphRecords: ...


# Shared closed inputs for evidence expansion (the frozen CQ inputs stay intact).
EvidenceCategory = Literal["mask_pack", "serum_ampoule", "sun_care"]
RankedEvidenceSource = Literal["youtube", "instagram"]
