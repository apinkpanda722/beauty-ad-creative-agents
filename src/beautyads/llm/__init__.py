"""Model calls use the SDK's bundled prices, selected before any imports."""

os = __import__("os")
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

from beautyads.obs import CostCapExceeded
from beautyads.settings import ThinkingLevel

from .chat import (
    ChatResult,
    ToolCall,
    cache_system_block,
    chat_complete,
    chat_stream,
    precheck_call,
    record_usage,
)
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
from .prices import (
    PRICE_TABLE_CHECKED_ON,
    ModelPrice,
    PriceUnknown,
    compute_cost,
    price_for,
    resolve_cost,
)

__all__ = [
    "PRICE_TABLE_CHECKED_ON",
    "ChatResult",
    "CostCapExceeded",
    "DailyLimitReached",
    "ErrorKind",
    "FileError",
    "GeminiInteractionsFn",
    "InteractionResult",
    "LlmCallError",
    "LlmResponseError",
    "ModelPrice",
    "PriceUnknown",
    "ThinkingLevel",
    "ToolCall",
    "UploadedFile",
    "UsageInfo",
    "cache_system_block",
    "chat_complete",
    "chat_stream",
    "classify_error",
    "compute_cost",
    "delete_file",
    "extract_output_text",
    "file_error_code",
    "gemini_interact",
    "json_schema_format",
    "parse_json_output",
    "precheck_call",
    "price_for",
    "record_usage",
    "resolve_cost",
    "retry_after_seconds",
    "text_part",
    "upload_video",
    "usage_from_response",
    "video_part",
    "wait_processed",
]
