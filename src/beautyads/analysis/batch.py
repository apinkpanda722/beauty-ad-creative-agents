"""Sequential batches retain pending work when quota or budget is exhausted."""

from typing import Any

from pydantic import BaseModel

from beautyads.domain import AnalysisRepository, JobStatus
from beautyads.llm import CostCapExceeded, DailyLimitReached, ErrorKind, LlmCallError

from .hook import analyze_hook
from .prompts import HOOK_PROMPT_VERSION


class BatchSummary(BaseModel):
    counts: dict[str, int]
    stopped: str | None


def analyze_pending(
    repo: AnalysisRepository, *, limit: int, **call_kwargs: Any
) -> BatchSummary:
    summary = BatchSummary(
        counts={status.value: 0 for status in JobStatus}, stopped=None
    )
    for creative in repo.next_pending("hook", limit):
        try:
            outcome = analyze_hook(creative, **call_kwargs)
        except DailyLimitReached:
            summary.stopped = "DAILY_LIMIT"
            break
        except CostCapExceeded as exc:
            summary.stopped = f"COST_CAP:{exc.provider}"
            break
        except LlmCallError as exc:
            if exc.kind != ErrorKind.RATE_LIMIT:
                raise
            summary.stopped = "RATE_LIMITED"
            break

        repo.record_analysis(
            "hook",
            outcome.key,
            status=outcome.status,
            model=outcome.model,
            thinking_level=call_kwargs["thinking_level"],
            prompt_version=HOOK_PROMPT_VERSION,
            raw_output=outcome.raw_output,
            labels={"hook_type": outcome.hook.hook_type.value}
            if outcome.hook is not None
            else None,
            error_code=outcome.error_code,
        )
        summary.counts[outcome.status.value] += 1
    return summary
