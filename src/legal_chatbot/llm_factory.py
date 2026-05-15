import os
from dataclasses import dataclass
from dotenv import load_dotenv

from .config import (
    LLM_ANALYZER_MODEL,
    LLM_ANALYZER_FALLBACK_MODEL,
    LLM_FAST_MAX_RETRIES,
    LLM_INTENT_FALLBACK_MODEL,
    LLM_INTENT_MODEL,
    LLM_INTENT_MAX_TOKENS,
    LLM_PROVIDER,
    LLM_REASONER_FALLBACK_MODEL,
    LLM_REASONER_MAX_TOKENS,
    LLM_REASONER_MAX_RETRIES,
    LLM_REASONER_MODEL,
    LLM_ANALYZER_MAX_TOKENS,
    LLM_TEMPERATURE,
    LLM_TIMEOUT,
)
from .observability import build_langchain_callbacks, ensure_phoenix_instrumentation

load_dotenv()

try:
    from langchain_community.chat_models import ChatOpenAI
except ImportError:
    ChatOpenAI = None

try:
    from langchain_ollama import ChatOllama
except ImportError:
    ChatOllama = None


@dataclass
class LLMClients:
    llm_reason: object
    llm_json: object
    llm_intent: object
    provider: str
    reasoner_model: str
    analyzer_model: str
    intent_model: str
    reasoner_fallback_model: str
    analyzer_fallback_model: str
    intent_fallback_model: str


def _looks_like_blocked_local_proxy(value: str) -> bool:
    normalized = (value or "").strip().lower()
    if not normalized:
        return False
    return (
        "127.0.0.1:9" in normalized
        or "localhost:9" in normalized
        or "0.0.0.0:9" in normalized
    )


def _sanitize_proxy_env_for_groq() -> None:
    """
    Gỡ proxy local chặn outbound để Groq có thể kết nối.
    Chỉ remove khi proxy match pattern blocked local (:9).
    """
    proxy_keys = [
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ]
    for key in proxy_keys:
        val = os.getenv(key, "")
        if _looks_like_blocked_local_proxy(val):
            os.environ.pop(key, None)


def _create_groq_clients() -> LLMClients:
    if ChatOpenAI is None:
        raise RuntimeError(
            "Thiếu ChatOpenAI (langchain_community). Không thể tạo Groq client."
        )
    groq_api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not groq_api_key:
        raise RuntimeError("Thiếu GROQ_API_KEY trong environment (.env).")

    _sanitize_proxy_env_for_groq()
    ensure_phoenix_instrumentation()
    callbacks = build_langchain_callbacks()

    common_kwargs = {
        "openai_api_base": "https://api.groq.com/openai/v1",
        "openai_api_key": groq_api_key,
        "request_timeout": LLM_TIMEOUT,
    }

    def _create_chat_model(
        model_name: str,
        temperature: float,
        max_retries: int | None = None,
        max_tokens: int | None = None,
    ):
        kwargs = dict(common_kwargs)
        if max_retries is not None:
            kwargs["max_retries"] = max_retries
        if max_tokens is not None and max_tokens > 0:
            kwargs["max_tokens"] = max_tokens
        if callbacks:
            kwargs["callbacks"] = callbacks
        return ChatOpenAI(
            model_name=model_name,
            temperature=temperature,
            **kwargs,
        )

    def _with_optional_fallback(primary, fallback):
        if fallback is None:
            return primary
        return primary.with_fallbacks([fallback])

    analyzer_fallback_model = LLM_ANALYZER_FALLBACK_MODEL
    intent_fallback_model = LLM_INTENT_FALLBACK_MODEL
    reasoner_fallback_model = LLM_REASONER_FALLBACK_MODEL

    llm_reason_primary = _create_chat_model(
        model_name=LLM_REASONER_MODEL,
        temperature=LLM_TEMPERATURE,
        max_retries=LLM_REASONER_MAX_RETRIES,
        max_tokens=LLM_REASONER_MAX_TOKENS,
    )
    llm_reason_fallback = None
    if reasoner_fallback_model and reasoner_fallback_model != LLM_REASONER_MODEL:
        llm_reason_fallback = _create_chat_model(
            model_name=reasoner_fallback_model,
            temperature=LLM_TEMPERATURE,
            max_retries=LLM_FAST_MAX_RETRIES,
            max_tokens=LLM_REASONER_MAX_TOKENS,
        )
    llm_reason = _with_optional_fallback(llm_reason_primary, llm_reason_fallback)

    llm_json_primary = _create_chat_model(
        model_name=LLM_ANALYZER_MODEL,
        temperature=0.0,
        max_retries=LLM_FAST_MAX_RETRIES,
        max_tokens=LLM_ANALYZER_MAX_TOKENS,
    )
    llm_json_fallback = None
    if analyzer_fallback_model and analyzer_fallback_model != LLM_ANALYZER_MODEL:
        llm_json_fallback = _create_chat_model(
            model_name=analyzer_fallback_model,
            temperature=0.0,
            max_retries=LLM_FAST_MAX_RETRIES,
            max_tokens=LLM_ANALYZER_MAX_TOKENS,
        )
    llm_json = _with_optional_fallback(llm_json_primary, llm_json_fallback)

    llm_intent_primary = _create_chat_model(
        model_name=LLM_INTENT_MODEL,
        temperature=0.0,
        max_retries=LLM_FAST_MAX_RETRIES,
        max_tokens=LLM_INTENT_MAX_TOKENS,
    )
    llm_intent_fallback = None
    if intent_fallback_model and intent_fallback_model != LLM_INTENT_MODEL:
        llm_intent_fallback = _create_chat_model(
            model_name=intent_fallback_model,
            temperature=0.0,
            max_retries=LLM_FAST_MAX_RETRIES,
            max_tokens=LLM_INTENT_MAX_TOKENS,
        )
    llm_intent = _with_optional_fallback(llm_intent_primary, llm_intent_fallback)
    return LLMClients(
        llm_reason=llm_reason,
        llm_json=llm_json,
        llm_intent=llm_intent,
        provider="groq",
        reasoner_model=LLM_REASONER_MODEL,
        analyzer_model=LLM_ANALYZER_MODEL,
        intent_model=LLM_INTENT_MODEL,
        reasoner_fallback_model=reasoner_fallback_model,
        analyzer_fallback_model=analyzer_fallback_model,
        intent_fallback_model=intent_fallback_model,
    )


def _create_ollama_clients() -> LLMClients:
    if ChatOllama is None:
        raise RuntimeError(
            "Thiếu package 'langchain-ollama'. Hãy cài dependency trước khi dùng provider=ollama."
        )

    ensure_phoenix_instrumentation()
    callbacks = build_langchain_callbacks()

    llm_reason = ChatOllama(
        model=LLM_REASONER_MODEL,
        temperature=LLM_TEMPERATURE,
        timeout=LLM_TIMEOUT,
        callbacks=callbacks or None,
    )
    llm_json = ChatOllama(
        model=LLM_ANALYZER_MODEL,
        temperature=LLM_TEMPERATURE,
        format="json",
        timeout=LLM_TIMEOUT,
        callbacks=callbacks or None,
    )
    llm_intent = ChatOllama(
        model=LLM_INTENT_MODEL,
        temperature=0.0,
        timeout=LLM_TIMEOUT,
        callbacks=callbacks or None,
    )
    return LLMClients(
        llm_reason=llm_reason,
        llm_json=llm_json,
        llm_intent=llm_intent,
        provider="ollama",
        reasoner_model=LLM_REASONER_MODEL,
        analyzer_model=LLM_ANALYZER_MODEL,
        intent_model=LLM_INTENT_MODEL,
        reasoner_fallback_model="",
        analyzer_fallback_model="",
        intent_fallback_model="",
    )


def create_llm_clients() -> LLMClients:
    provider = LLM_PROVIDER
    if provider == "groq":
        return _create_groq_clients()
    if provider == "ollama":
        return _create_ollama_clients()
    raise RuntimeError(
        f"LEGAL_CHATBOT_LLM_PROVIDER='{provider}' không hợp lệ. Dùng 'groq' hoặc 'ollama'."
    )
