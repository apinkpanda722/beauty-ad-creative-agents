"""Identify only stored candidates using the existing bounded video call pattern."""

from collections.abc import Callable, Mapping
from math import isfinite
from pathlib import Path

from pydantic import BaseModel, ValidationError

from beautyads.domain import Creative, CreativeKey, JobStatus, Source
from beautyads.domain.product_id import ProductIdResult
from beautyads.domain.products import Product
from beautyads.llm import (
    DailyLimitReached,
    InteractionResult,
    LlmCallError,
    LlmResponseError,
    ThinkingLevel,
    gemini_interact,
    json_schema_format,
    parse_json_output,
    text_part,
    video_part,
)
from beautyads.llm.gemini import check_cap

from .models import ANALYSIS_MODEL_ID, VideoInput
from .prompts import PRODUCT_ID_PROMPT_VERSION, build_product_id_prompt


class ProductIdOutcome(BaseModel):
    key: CreativeKey
    status: JobStatus = JobStatus.failed
    labels: dict | None = None
    raw_output: str | None = None
    model: str | None = None
    error_code: str | None = None
    attempts: int = 0
    prompt_version: str = PRODUCT_ID_PROMPT_VERSION


def identify_product(
    creative: Creative,
    *,
    candidates: Mapping[str, Product],
    thinking_level: ThinkingLevel,
    ledger_path: Path,
    caps: Mapping[str, float],
    window_max_s: float = 60,
    interact: Callable[..., InteractionResult] = gemini_interact,
    video: VideoInput | None = None,
    on_attempt: Callable[[ProductIdOutcome], None] | None = None,
) -> ProductIdOutcome:
    if not isfinite(window_max_s) or window_max_s <= 0:
        raise ValueError("window_max_s must be finite and positive")
    outcome = ProductIdOutcome(key=creative.key)
    if creative.source not in {Source.youtube, Source.instagram}:
        outcome.error_code = "UNSUPPORTED_SOURCE"
        return outcome
    if not candidates or any(p.brand != creative.brand for p in candidates.values()):
        outcome.error_code = "NO_VALID_CANDIDATES"
        return outcome
    if video is None and (creative.source != Source.youtube or not creative.url):
        outcome.error_code = "NO_VIDEO"
        return outcome
    end = (
        min(window_max_s, creative.duration_s)
        if creative.duration_s is not None
        else window_max_s
    )
    if not isfinite(end) or end <= 0:
        outcome.error_code = "INVALID_DURATION"
        return outcome
    parts = [
        text_part(build_product_id_prompt(candidates)),
        video_part(
            video.uri if video is not None else creative.url,
            start_s=0,
            end_s=end,
            fps=1,
            mime_type=video.mime_type if video is not None else None,
        ),
    ]
    schema = ProductIdResult.model_json_schema()
    schema["properties"]["candidates"]["items"]["enum"] = list(candidates)
    for attempt in range(2):
        outcome.attempts = attempt + 1
        outcome.raw_output = None
        check_cap(ledger_path, "gemini", caps)
        try:
            result = interact(
                model=ANALYSIS_MODEL_ID,
                input_parts=parts,
                thinking_level=thinking_level,
                purpose="product-identify",
                ledger_path=ledger_path,
                caps=caps,
                response_format=json_schema_format(schema),
            )
        except DailyLimitReached:
            raise
        except LlmCallError:
            # The batch distinguishes account stops from per-creative failures.
            raise
        except LlmResponseError as exc:
            outcome.status = JobStatus.failed
            outcome.error_code = exc.code
        else:
            outcome.raw_output = result.text
            outcome.model = result.usage.model
            try:
                selection = ProductIdResult.model_validate(
                    parse_json_output(result.text), context={"candidates": candidates}
                )
            except (ValidationError, LlmResponseError):
                outcome.status = JobStatus.held if attempt else JobStatus.pending
                outcome.error_code = "INVALID_OUTPUT"
            else:
                outcome.status = JobStatus.done
                outcome.error_code = None
                outcome.labels = {
                    "products": [
                        key.model_dump() for key in selection.products(candidates)
                    ]
                }
        if on_attempt is not None:
            on_attempt(outcome.model_copy(deep=True))
        if outcome.status != JobStatus.pending:
            return outcome
    return outcome
