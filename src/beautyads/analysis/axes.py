"""Classify content first and validate full labels within caller-owned windows."""

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from beautyads.domain import (
    Category,
    ContentType,
    ContentTypeResult,
    Creative,
    FullResult,
    JobStatus,
)
from beautyads.llm import (
    DailyLimitReached,
    ErrorKind,
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

from .models import (
    ANALYSIS_MODEL_ID,
    PROMPT_VERSIONS,
    AxisOutcome,
    VideoInput,
    log_llm_failure,
    models_match,
)
from .prompts import build_content_type_prompt, build_full_prompt


def _response_schema(model: type[BaseModel]) -> dict:
    """Inline domain definitions as in the existing hook response schema."""
    schema = model.model_json_schema()
    definitions = schema.pop("$defs", {})

    def inline(value: Any) -> Any:
        if isinstance(value, dict):
            if "$ref" in value:
                name = value["$ref"].rsplit("/", 1)[-1]
                return inline(definitions[name])
            return {name: inline(child) for name, child in value.items()}
        if isinstance(value, list):
            return [inline(child) for child in value]
        return value

    return inline(schema)


def content_type_schema() -> dict:
    return _response_schema(ContentTypeResult)


def full_schema() -> dict:
    return _response_schema(FullResult)


def is_product_target(result: ContentTypeResult) -> bool:
    return (
        result.content_type == ContentType.product_creative
        and result.category != Category.other
    )


def full_window(
    duration_s: float | None, *, window_max_s: float
) -> tuple[float, float]:
    end = window_max_s
    if duration_s is not None:
        end = min(end, duration_s)
    return 0.0, end


def _analyze_axis(
    creative: Creative,
    video: VideoInput,
    *,
    axis: str,
    result_model: type[ContentTypeResult] | type[FullResult],
    prompt: str,
    thinking_level: ThinkingLevel,
    purpose: str,
    ledger_path: Path,
    caps: Mapping[str, float],
    window_max_s: float,
    interact: Callable[..., InteractionResult],
    max_validation_retries: int,
) -> AxisOutcome:
    outcome = AxisOutcome(
        key=creative.key,
        axis=axis,
        status=JobStatus.failed,
        labels=None,
        raw_output=None,
        model=None,
        model_matches_request=None,
        error_code=None,
        attempts=0,
        prompt_version=PROMPT_VERSIONS[axis],
    )
    start, end = full_window(creative.duration_s, window_max_s=window_max_s)
    input_parts = [
        text_part(prompt),
        video_part(
            video.uri, start_s=start, end_s=end, fps=1, mime_type=video.mime_type
        ),
    ]
    response_format = json_schema_format(_response_schema(result_model))
    for attempt in range(max_validation_retries + 1):
        outcome.attempts = attempt + 1
        try:
            result = interact(
                model=ANALYSIS_MODEL_ID,
                input_parts=input_parts,
                thinking_level=thinking_level,
                purpose=purpose,
                ledger_path=ledger_path,
                caps=caps,
                response_format=response_format,
            )
        except DailyLimitReached:
            raise
        except LlmCallError as exc:
            if exc.kind == ErrorKind.RATE_LIMIT:
                raise
            log_llm_failure(axis, exc)
            outcome.error_code = f"LLM_{exc.kind}"
            return outcome
        except LlmResponseError as exc:
            outcome.error_code = exc.code
            return outcome

        outcome.raw_output = result.text
        outcome.model = result.usage.model
        outcome.model_matches_request = models_match(ANALYSIS_MODEL_ID, outcome.model)
        try:
            labels = result_model.model_validate(parse_json_output(result.text))
        except (LlmResponseError, ValidationError):
            continue
        outcome.status = JobStatus.done
        outcome.labels = labels.model_dump(mode="json")
        return outcome

    outcome.status = JobStatus.held
    outcome.error_code = "INVALID_OUTPUT"
    return outcome


def analyze_content_type(
    creative: Creative,
    video: VideoInput,
    *,
    thinking_level: ThinkingLevel,
    purpose: str,
    ledger_path: Path,
    caps: Mapping[str, float],
    window_max_s: float,
    interact: Callable[..., InteractionResult] = gemini_interact,
    max_validation_retries: int = 1,
) -> AxisOutcome:
    return _analyze_axis(
        creative,
        video,
        axis="content_type",
        result_model=ContentTypeResult,
        prompt=build_content_type_prompt(creative),
        thinking_level=thinking_level,
        purpose=purpose,
        ledger_path=ledger_path,
        caps=caps,
        window_max_s=window_max_s,
        interact=interact,
        max_validation_retries=max_validation_retries,
    )


def analyze_full(
    creative: Creative,
    video: VideoInput,
    *,
    thinking_level: ThinkingLevel,
    purpose: str,
    ledger_path: Path,
    caps: Mapping[str, float],
    window_max_s: float,
    interact: Callable[..., InteractionResult] = gemini_interact,
    max_validation_retries: int = 1,
) -> AxisOutcome:
    return _analyze_axis(
        creative,
        video,
        axis="full",
        result_model=FullResult,
        prompt=build_full_prompt(creative),
        thinking_level=thinking_level,
        purpose=purpose,
        ledger_path=ledger_path,
        caps=caps,
        window_max_s=window_max_s,
        interact=interact,
        max_validation_retries=max_validation_retries,
    )
