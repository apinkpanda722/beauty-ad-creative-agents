"""Select creatives and validate Gemini classifications of their opening window."""

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import NamedTuple

from pydantic import BaseModel, ValidationError

from beautyads.domain import (
    Creative,
    CreativeKey,
    HookResult,
    HookType,
    JobStatus,
    Source,
    is_analyzable,
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

from .prompts import HOOK_PROMPT_VERSION, build_hook_prompt

HOOK_WINDOW_S = 3.0


def hook_response_schema() -> dict:
    """Inline the domain enum for the measured Gemini schema format."""
    schema = HookResult.model_json_schema()
    definitions = schema.pop("$defs")
    schema["properties"]["hook_type"] = definitions[HookType.__name__]
    return schema


class Skip(NamedTuple):
    key: CreativeKey
    reason: str


class Selection(NamedTuple):
    eligible: list[Creative]
    skipped: list[Skip]


def select_for_analysis(
    creatives: Sequence[Creative], *, video_length_cut_s: float
) -> Selection:
    """Defensively recheck the eligibility decision made during collection."""
    eligible = []
    skipped = []
    for creative in creatives:
        if not is_analyzable(creative):
            skipped.append(Skip(creative.key, "NOT_ANALYZABLE"))
        elif (
            creative.duration_s is not None and creative.duration_s > video_length_cut_s
        ):
            skipped.append(Skip(creative.key, "TOO_LONG"))
        else:
            eligible.append(creative)
    return Selection(eligible, skipped)


def hook_window(
    duration_s: float | None,
    *,
    window_max_s: float,
    hook_window_s: float = HOOK_WINDOW_S,
) -> tuple[float, float]:
    end = min(hook_window_s, window_max_s)
    if duration_s is not None:
        end = min(end, duration_s)
    return 0.0, end


class AnalysisOutcome(BaseModel):
    key: CreativeKey
    status: JobStatus
    hook: HookResult | None
    raw_output: str | None
    model: str | None
    error_code: str | None
    attempts: int
    prompt_version: str


def analyze_hook(
    creative: Creative,
    *,
    thinking_level: ThinkingLevel,
    purpose: str,
    ledger_path: Path,
    caps: Mapping[str, float],
    window_max_s: float,
    interact: Callable[..., InteractionResult] = gemini_interact,
    max_validation_retries: int = 1,
) -> AnalysisOutcome:
    """Retry invalid labels only; quota and cost exceptions reach the batch."""
    outcome = AnalysisOutcome(
        key=creative.key,
        status=JobStatus.failed,
        hook=None,
        raw_output=None,
        model=None,
        error_code=None,
        attempts=0,
        prompt_version=HOOK_PROMPT_VERSION,
    )
    if creative.source != Source.youtube:
        outcome.error_code = "UNSUPPORTED_SOURCE"
        return outcome
    if not creative.url:
        outcome.error_code = "NO_URL"
        return outcome

    start, end = hook_window(creative.duration_s, window_max_s=window_max_s)
    input_parts = [
        text_part(build_hook_prompt(creative)),
        video_part(creative.url, start_s=start, end_s=end, fps=1),
    ]
    response_format = json_schema_format(hook_response_schema())
    for attempt in range(max_validation_retries + 1):
        outcome.attempts = attempt + 1
        try:
            result = interact(
                model="gemini-3.6-flash",
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
            outcome.error_code = f"LLM_{exc.kind}"
            return outcome
        except LlmResponseError as exc:
            outcome.error_code = exc.code
            return outcome

        outcome.raw_output = result.text
        outcome.model = result.usage.model
        try:
            hook = HookResult.model_validate(parse_json_output(result.text))
        except (LlmResponseError, ValidationError):
            continue
        outcome.status = JobStatus.done
        outcome.hook = hook
        return outcome

    outcome.status = JobStatus.held
    outcome.error_code = "INVALID_OUTPUT"
    return outcome
