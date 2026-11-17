"""Stable high-level registry over the frozen CQ-v1 queries."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from beautyads.domain.labels import Category, Claim
from beautyads.domain.skin import SkinConcern, SkinType
from beautyads.domain.tools import (
    EVIDENCE_ID_PATTERN,
    GraphReader,
    ToolContext,
    ToolErrorCode,
    ToolFailure,
    ToolKind,
    ToolResult,
    UiCommand,
)
from beautyads.graph.connection import GraphError
from beautyads.graph.queries import QUESTIONS, question_parameters

PROMOTES_QUESTION_IDS = frozenset(
    {"CQ-04", "CQ-05", "CQ-06", "CQ-08", "CQ-13", "CQ-14", "CQ-15", "CQ-16"}
)

ProductCategory = Literal[Category.mask_pack, Category.serum_ampoule, Category.sun_care]
EvidenceId = Annotated[str, StringConstraints(pattern=EVIDENCE_ID_PATTERN)]


class EmptyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EfficacyInput(EmptyInput):
    category: ProductCategory = Field(description="조회할 제품 카테고리")
    claim: Claim = Field(description="제품 성분 근거와 연결할 효능 분류")


class ConcernInput(EmptyInput):
    category: ProductCategory = Field(description="조회할 제품 카테고리")
    concern: SkinConcern = Field(description="제품 성분 근거와 연결할 피부 고민")


class SkinTypeInput(EmptyInput):
    skin_type: SkinType = Field(description="광고 앵글과 포맷을 집계할 피부 타입")


class EvidenceInput(EmptyInput):
    evidence_ids: list[EvidenceId] = Field(
        max_length=20, description="화면에 표시할 근거 소재 식별자 목록"
    )


class DistributionInput(EvidenceInput):
    axis: Literal["hook_type", "angle", "format", "claim", "category"] = Field(
        description="근거 소재의 분포를 표시할 분류 축"
    )


class PlanInput(EmptyInput):
    plan_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] = (
        Field(description="화면에 표시할 기획안 식별자")
    )


@dataclass(frozen=True)
class ToolSpec:
    name: str
    kind: ToolKind
    description: str
    input_model: type[BaseModel]
    question_id: str | None


TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        "ad_angles_formats_by_skin_type",
        ToolKind.aggregate,
        "쓰는 때: 피부 타입에 맞는 제품의 연결 광고 앵글과 포맷을 집계할 때.\n"
        "쓰지 않는 때: 개별 제품의 효능 근거가 필요할 때.",
        SkinTypeInput,
        "CQ-08",
    ),
    ToolSpec(
        "compare_competitor_claims",
        ToolKind.compare,
        "쓰는 때: 공개 기준 제품과 핵심 성분을 공유하는 경쟁 제품의 광고 효능을 비교할 때.\n"
        "쓰지 않는 때: 작업 공간의 자사 제품을 지정한 비교가 필요할 때.",
        EmptyInput,
        "CQ-13",
    ),
    ToolSpec(
        "compare_hooks_by_category",
        ToolKind.compare,
        "쓰는 때: 카테고리별 연결 광고의 훅과 조회수 자료를 비교할 때.\n"
        "쓰지 않는 때: 출처가 다른 조회수를 직접 비교하거나 광고 성과의 인과를 판단할 때.",
        EmptyInput,
        "CQ-06",
    ),
    ToolSpec(
        "compare_price_band_competitors",
        ToolKind.compare,
        "쓰는 때: 서버에 가격대가 정해져 있고 같은 단위당 정가의 경쟁 광고를 비교할 때.\n"
        "쓰지 않는 때: 가격대가 없거나 할인 판매가 비교가 필요할 때.",
        EmptyInput,
        "CQ-16",
    ),
    ToolSpec(
        "count_claim_supported_ads",
        ToolKind.aggregate,
        "쓰는 때: 효능 주장과 제품 성분 근거가 함께 연결된 광고 건수가 필요할 때.\n"
        "쓰지 않는 때: 전체 광고의 효능이나 제품의 임상 효과를 판단할 때.",
        EfficacyInput,
        "CQ-04",
    ),
    ToolSpec(
        "ingredient_ad_trend",
        ToolKind.aggregate,
        "쓰는 때: 병풀 별칭을 경유한 연결 광고의 게시 자료로 최근 변화를 살필 때.\n"
        "쓰지 않는 때: 표본이 적은 결과로 시장 전체 추세를 확정할 때.",
        EmptyInput,
        "CQ-15",
    ),
    ToolSpec(
        "lookup_certified_products",
        ToolKind.lookup,
        "쓰는 때: 미백 기능성 인증이 연결된 제품을 찾을 때.\n"
        "쓰지 않는 때: 연결되지 않은 제품의 인증 유무를 확정할 때.",
        EmptyInput,
        "CQ-03",
    ),
    ToolSpec(
        "lookup_products_by_concern",
        ToolKind.lookup,
        "쓰는 때: 카테고리와 피부 고민에 성분 근거로 연결된 제품을 찾을 때.\n"
        "쓰지 않는 때: 근거 연결이 없는 제품의 효능을 추정할 때.",
        ConcernInput,
        "CQ-02",
    ),
    ToolSpec(
        "lookup_products_by_efficacy",
        ToolKind.lookup,
        "쓰는 때: 카테고리와 효능에 성분 근거로 연결된 제품을 찾을 때.\n"
        "쓰지 않는 때: 성분 포함만으로 제품의 효능을 인정하거나 인증을 확정할 때.",
        EfficacyInput,
        "CQ-01",
    ),
    ToolSpec(
        "show_distribution",
        ToolKind.display,
        "쓰는 때: 선택한 근거 소재의 분류 분포를 화면에 표시할 때.\n"
        "쓰지 않는 때: 새 그래프 조회나 집계 결과가 필요할 때.",
        DistributionInput,
        None,
    ),
    ToolSpec(
        "show_evidence_cards",
        ToolKind.display,
        "쓰는 때: 선택한 근거 소재를 카드로 화면에 표시할 때.\n"
        "쓰지 않는 때: 새로운 근거 소재를 검색할 때.",
        EvidenceInput,
        None,
    ),
    ToolSpec(
        "show_graph_fragment",
        ToolKind.display,
        "쓰는 때: 선택한 근거 소재의 관계를 화면에 표시할 때.\n"
        "쓰지 않는 때: 새로운 그래프 경로를 조회할 때.",
        EvidenceInput,
        None,
    ),
    ToolSpec(
        "show_plan",
        ToolKind.display,
        "쓰는 때: 이미 있는 기획안을 화면에 표시할 때.\n"
        "쓰지 않는 때: 기획안을 새로 작성하거나 평가할 때.",
        PlanInput,
        None,
    ),
    ToolSpec(
        "top_claims_of_ingredient_ads",
        ToolKind.aggregate,
        "쓰는 때: 병풀 별칭으로 연결된 제품 광고의 효능 주장 분포를 볼 때.\n"
        "쓰지 않는 때: 모든 성분이나 전체 광고 시장의 순위가 필요할 때.",
        EmptyInput,
        "CQ-05",
    ),
    ToolSpec(
        "unclaimed_efficacy_gaps",
        ToolKind.compare,
        "쓰는 때: 공개 제품의 성분·인증 근거와 연결된 경쟁 광고 효능의 차집합을 볼 때.\n"
        "쓰지 않는 때: 미연결 경쟁 광고까지 포함한 시장 독점성을 확정할 때.",
        EmptyInput,
        "CQ-14",
    ),
)


def tool_definitions() -> list[dict]:
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.input_model.model_json_schema(),
        }
        for tool in TOOLS
    ]


def get_tool(name: str) -> ToolSpec | None:
    return next((tool for tool in TOOLS if tool.name == name), None)


def _failure(code: ToolErrorCode, message: str, *, retryable=False) -> ToolFailure:
    return ToolFailure(code=code, retryable=retryable, message=message)


def _evidence_ids(rows: list[dict]) -> list[str]:
    found: set[str] = set()
    for row in rows:
        multiple = row.get("creative_ids")
        if isinstance(multiple, list):
            found.update(value for value in multiple if isinstance(value, str))
        single = row.get("creative_id")
        if isinstance(single, str):
            found.add(single)
    return sorted(found)[:50]


def run_tool(
    name: str,
    arguments: Mapping | str,
    ctx: ToolContext | None,
    graph: GraphReader,
) -> ToolResult | ToolFailure:
    if ctx is None or not ctx.tenant_id.strip():
        return _failure(
            ToolErrorCode.TENANT_CONTEXT_MISSING, "실행 테넌트가 필요합니다."
        )
    try:
        tool = get_tool(name)
        if tool is None:
            return _failure(ToolErrorCode.TOOL_UNKNOWN, "등록되지 않은 도구입니다.")
        try:
            parsed = json.loads(arguments) if isinstance(arguments, str) else arguments
            if not isinstance(parsed, Mapping):
                return _failure(ToolErrorCode.INPUT_INVALID, "입력은 객체여야 합니다.")
            inputs = tool.input_model.model_validate(dict(parsed)).model_dump(
                mode="json"
            )
        except (ValueError, TypeError):
            return _failure(
                ToolErrorCode.INPUT_INVALID, "도구 입력이 올바르지 않습니다."
            )

        if tool.kind == ToolKind.display:
            return ToolResult(
                tool=name,
                kind=tool.kind,
                summary="표시 명령을 보냈다.",
                top_rows=[],
                row_count=0,
                evidence_ids=[],
                no_evidence=False,
                ui_command=UiCommand(kind=name, data=inputs),
            )

        context = {"tenant_id": ctx.tenant_id}
        if tool.question_id == "CQ-16":
            if ctx.price_band is None:
                return _failure(
                    ToolErrorCode.PRICE_BAND_MISSING, "가격대 컨텍스트가 필요합니다."
                )
            context.update(ctx.price_band.model_dump())
        question = QUESTIONS[tool.question_id]
        params = question_parameters(
            question, as_of=ctx.as_of, inputs=inputs, context=context
        )
        rows = graph.run(question.cypher, params).records
        evidence_ids = _evidence_ids(rows)
        linked = tool.question_id in PROMOTES_QUESTION_IDS
        summary = f"조회 결과 {len(rows)}행." if rows else "근거 없음."
        if linked:
            summary += " 연결된 소재 기준."
        return ToolResult(
            tool=name,
            kind=tool.kind,
            summary=summary,
            top_rows=rows[:5],
            row_count=len(rows),
            evidence_ids=evidence_ids,
            no_evidence=not rows,
            linked_creative_count=len(evidence_ids) if linked else None,
        )
    except GraphError as exc:
        return _failure(
            ToolErrorCode.GRAPH_UNAVAILABLE,
            "그래프 조회를 완료하지 못했습니다.",
            retryable=exc.code == "NEO4J_UNREACHABLE",
        )
    except Exception as exc:  # noqa: BLE001 -- tool boundary returns sanitized failures
        return _failure(ToolErrorCode.TOOL_INTERNAL_ERROR, type(exc).__name__)
