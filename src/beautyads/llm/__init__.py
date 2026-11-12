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
from .files import (
    FileError,
    UploadedFile,
    delete_file,
    file_error_code,
    upload_video,
    wait_processed,
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
    "FileError",
    "GeminiInteractionsFn",
    "InteractionResult",
    "LlmCallError",
    "LlmResponseError",
    "ThinkingLevel",
    "UploadedFile",
    "UsageInfo",
    "classify_error",
    "delete_file",
    "extract_output_text",
    "file_error_code",
    "gemini_interact",
    "json_schema_format",
    "parse_json_output",
    "retry_after_seconds",
    "text_part",
    "upload_video",
    "usage_from_response",
    "video_part",
    "wait_processed",
]
