"""Model calls use the SDK's bundled prices, selected before any imports."""

os = __import__("os")
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

from beautyads.obs import CostCapExceeded
from beautyads.settings import ThinkingLevel

from .errors import (
    DailyLimitReached,
    ErrorKind,
    LlmCallError,
    LlmResponseError,
    classify_error,
    retry_after_seconds,
)
from .gemini import (
    GeminiInteractionsFn,
    InteractionResult,
    UsageInfo,
    extract_output_text,
    gemini_interact,
    json_schema_format,
    parse_json_output,
    text_part,
    usage_from_response,
    video_part,
)

__all__ = [
    "CostCapExceeded",
    "DailyLimitReached",
    "ErrorKind",
    "GeminiInteractionsFn",
    "InteractionResult",
    "LlmCallError",
    "LlmResponseError",
    "ThinkingLevel",
    "UsageInfo",
    "classify_error",
    "extract_output_text",
    "gemini_interact",
    "json_schema_format",
    "parse_json_output",
    "retry_after_seconds",
    "text_part",
    "usage_from_response",
    "video_part",
]
