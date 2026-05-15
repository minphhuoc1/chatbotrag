import atexit
import logging
import os
from typing import List

from .config import (
    OBS_LANGFUSE_ENABLED,
    OBS_PHOENIX_AUTO_INSTRUMENT,
    OBS_PHOENIX_ENABLED,
    OBS_PHOENIX_PROJECT,
    OBS_TRACE_TAG,
)

_LOGGER = logging.getLogger(__name__)
_PHOENIX_READY = False
_LANGFUSE_FLUSH_REGISTERED = False


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "1" if default else "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def ensure_phoenix_instrumentation() -> bool:
    """
    Bật OpenInference -> Phoenix auto instrumentation (nếu cấu hình cho phép).
    Hàm này an toàn khi gọi nhiều lần.
    """
    global _PHOENIX_READY

    if _PHOENIX_READY:
        return True
    if not OBS_PHOENIX_ENABLED:
        return False

    try:
        from phoenix.otel import register

        register(
            project_name=OBS_PHOENIX_PROJECT,
            auto_instrument=OBS_PHOENIX_AUTO_INSTRUMENT,
        )
        _PHOENIX_READY = True
        _LOGGER.info(
            "Phoenix tracing enabled (project=%s, auto_instrument=%s)",
            OBS_PHOENIX_PROJECT,
            OBS_PHOENIX_AUTO_INSTRUMENT,
        )
        return True
    except Exception as exc:
        _LOGGER.warning("Phoenix instrumentation is disabled: %s", exc)
        return False


def _register_langfuse_flush() -> None:
    global _LANGFUSE_FLUSH_REGISTERED
    if _LANGFUSE_FLUSH_REGISTERED:
        return

    def _flush():
        try:
            from langfuse import get_client

            get_client().flush()
        except Exception:
            return

    atexit.register(_flush)
    _LANGFUSE_FLUSH_REGISTERED = True


def build_langchain_callbacks() -> List[object]:
    """
    Trả về danh sách callback handlers cho LangChain runtime.
    - LangSmith: hoạt động chủ yếu qua ENV (`LANGSMITH_TRACING=true`), không cần handler riêng.
    - Langfuse: cần callback handler để gửi traces.
    """
    callbacks: List[object] = []

    if OBS_LANGFUSE_ENABLED:
        try:
            from langfuse.langchain import CallbackHandler

            callbacks.append(CallbackHandler())
            _register_langfuse_flush()
        except Exception as exc:
            _LOGGER.warning("Langfuse callback is disabled: %s", exc)

    return callbacks


def build_invoke_config_metadata(session_id: str = "", user_id: str = "") -> dict:
    """
    Metadata chuẩn hoá cho invoke config, dùng được cho cả Langfuse/LangSmith.
    """
    metadata = {}
    if OBS_TRACE_TAG:
        metadata["trace_tag"] = OBS_TRACE_TAG

    # Langfuse-specific metadata fields (optional).
    if session_id:
        metadata["langfuse_session_id"] = session_id
    if user_id:
        metadata["langfuse_user_id"] = user_id

    return metadata


def describe_observability_state() -> dict:
    return {
        "langsmith_tracing": _env_flag("LANGSMITH_TRACING", False),
        "langfuse_enabled": OBS_LANGFUSE_ENABLED,
        "phoenix_enabled": OBS_PHOENIX_ENABLED,
        "phoenix_ready": _PHOENIX_READY,
        "trace_tag": OBS_TRACE_TAG,
    }
