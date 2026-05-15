"""
D1: Engine contract tests for run_structured().

Tests cover:
- RunResult dataclass field presence and types.
- run() backward-compat wrapper returns (str, str).
- build_validation_fallback explicit signature.
- classify_query_mode C1 fix (no "bị" false-positive).
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage

from src.legal_chatbot.reasoning_chain import RunResult
from src.legal_chatbot.policy import (
    build_validation_fallback,
    classify_query_mode,
)


# ── RunResult dataclass contract ────────────────────────────────────────────

def test_run_result_has_required_fields():
    """A1: RunResult must expose all contract fields."""
    r = RunResult(answer="ok")
    assert hasattr(r, "answer")
    assert hasattr(r, "context_text")
    assert hasattr(r, "docs")
    assert hasattr(r, "intent_result")
    assert hasattr(r, "query_mode")
    assert hasattr(r, "search_query")
    assert hasattr(r, "retrieval_check")
    assert hasattr(r, "validation")
    assert hasattr(r, "is_clarifying")
    assert hasattr(r, "route")
    assert hasattr(r, "debug_flags")


def test_run_result_defaults():
    """A1: Default values must be stable and not shared between instances."""
    r1 = RunResult(answer="a")
    r2 = RunResult(answer="b")
    r1.docs.append("x")
    assert r2.docs == [], "mutable default must not be shared"


def test_run_result_answer_is_str():
    r = RunResult(answer="hello")
    assert isinstance(r.answer, str)


# ── run() backward-compat wrapper ───────────────────────────────────────────

def _make_engine_stub(structured_result: RunResult):
    """Build a minimal LegalReasoningEngine where run_structured() is stubbed."""
    from src.legal_chatbot.reasoning_chain import LegalReasoningEngine

    engine = LegalReasoningEngine.__new__(LegalReasoningEngine)
    engine.run_structured = MagicMock(return_value=structured_result)
    return engine


def test_run_returns_tuple_of_two_strings():
    """A3: run() must return (answer_str, context_str) for all callers."""
    stub = RunResult(answer="câu trả lời", context_text="văn bản ngữ cảnh")
    engine = _make_engine_stub(stub)

    result = engine.run("câu hỏi", [])

    assert isinstance(result, tuple)
    assert len(result) == 2
    assert result[0] == "câu trả lời"
    assert result[1] == "văn bản ngữ cảnh"


def test_run_delegates_to_run_structured():
    """A3: run() must call run_structured() exactly once with the same args."""
    stub = RunResult(answer="x")
    engine = _make_engine_stub(stub)

    engine.run("q", ["history"])

    engine.run_structured.assert_called_once_with("q", ["history"])


def test_run_works_without_chat_history():
    """A3: run() must not crash when chat_history is omitted."""
    stub = RunResult(answer="y")
    engine = _make_engine_stub(stub)

    result = engine.run("q")
    assert result[0] == "y"


# ── build_validation_fallback explicit signature (C2) ───────────────────────

def test_build_validation_fallback_positional_args():
    """C2: Explicit 3-arg signature must work positionally."""
    val = {"ok": False, "invalid_articles": [250], "reason": "out of range"}
    msg = build_validation_fallback(val, "open_ended", "model")
    assert isinstance(msg, str)
    assert len(msg) > 0


def test_build_validation_fallback_default_failure_cause():
    """C2: failure_cause defaults to '' → generic fallback."""
    val = {"ok": False, "invalid_articles": [], "reason": "weak"}
    msg = build_validation_fallback(val, "open_ended")
    assert "căn cứ" in msg.lower() or "kết luận" in msg.lower()


def test_build_validation_fallback_invalid_articles_branch():
    """A4: When invalid_articles present, fallback must warn about bad citations."""
    val = {"ok": False, "invalid_articles": [999], "reason": "hallucinated"}
    msg = build_validation_fallback(val, "article_lookup", "model")
    assert "Điều" in msg or "viện dẫn" in msg.lower()


def test_build_validation_fallback_quote_mode():
    val = {"ok": False, "invalid_articles": [], "reason": "quote not grounded"}
    msg = build_validation_fallback(val, "quote_request", "")
    assert "trích nguyên văn" in msg.lower() or "nguyên văn" in msg.lower()


def test_build_validation_fallback_prompt_cause():
    val = {"ok": False, "invalid_articles": [], "reason": "vague query"}
    msg = build_validation_fallback(val, "open_ended", "prompt")
    assert "phạm vi" in msg.lower() or "câu hỏi" in msg.lower()


# ── classify_query_mode C1 fix ───────────────────────────────────────────────

def test_classify_query_mode_bi_no_longer_triggers_fact_pattern():
    """C1: Queries containing only 'bị' should NOT classify as fact_pattern."""
    # Typical complaint sentence that wrongly triggered fact_pattern before the fix.
    assert classify_query_mode("Tôi bị sếp chửi rủa phải làm sao?") != "fact_pattern"


def test_classify_query_mode_bi_sa_thai_is_open_ended():
    """C1: 'bị sa thải' alone (no article, no specific markers) → open_ended."""
    result = classify_query_mode("Tôi bị sa thải cần biết quyền lợi gì?")
    # Must not be fact_pattern due to stray "bị"
    assert result in {"open_ended", "article_lookup", "quote_request"}
    assert result != "fact_pattern"


def test_classify_query_mode_article_lookup_still_works():
    assert classify_query_mode("Điều 35 quy định gì?") == "article_lookup"


def test_classify_query_mode_quote_request():
    assert classify_query_mode("Trích nguyên văn Điều 40") == "quote_request"


def test_classify_query_mode_fact_pattern_explicit_markers():
    """C1: Explicit fact markers must still classify as fact_pattern."""
    assert classify_query_mode("Làm như vậy có hợp pháp không?") == "fact_pattern"
    assert classify_query_mode("Công ty làm đúng hay sai?") == "fact_pattern"


def test_run_structured_quote_request_returns_direct_context():
    """Quote request with valid retrieved context should bypass generic reasoner flow."""
    from src.legal_chatbot.reasoning_chain import LegalReasoningEngine
    from src.legal_chatbot.intent import Intent

    engine = LegalReasoningEngine.__new__(LegalReasoningEngine)
    engine.llm_intent = MagicMock()
    engine.reasoner_chain = MagicMock()
    engine._build_reasoner_context = MagicMock(return_value="ctx")
    engine._remove_chinese_characters = MagicMock(side_effect=lambda x, **_: x)
    engine._analyze_and_retrieve = MagicMock(
        return_value=(
            "Điều 113",
            "Điều 113. Nghỉ hằng năm 1. Người lao động làm việc đủ 12 tháng ...",
            [SimpleNamespace(page_content="Điều 113. Nghỉ hằng năm ...", metadata={"article_number": 113})],
        )
    )

    with patch("src.legal_chatbot.reasoning_chain.classify_intent") as mock_intent, \
         patch("src.legal_chatbot.reasoning_chain.classify_query_mode", return_value="quote_request"), \
         patch("src.legal_chatbot.reasoning_chain.resolve_article_query", return_value=""), \
         patch("src.legal_chatbot.reasoning_chain.assess_retrieval_strength", return_value={"is_strong_enough": True}), \
         patch("src.legal_chatbot.reasoning_chain.validate_answer_against_context", return_value={"ok": True, "reason": "grounded", "invalid_articles": []}):
        mock_intent.return_value = SimpleNamespace(intent=Intent.LEGAL, response="", source="rule")
        result = engine.run_structured("Trích nguyên văn Điều 113", [])

    assert result.route == "quote_direct"
    assert "Điều 113" in result.answer
    engine.reasoner_chain.invoke.assert_not_called()


def test_run_structured_empty_reasoner_answer_falls_back():
    """If reasoner emits an empty answer, engine must return a safe fallback instead of blank output."""
    from src.legal_chatbot.reasoning_chain import LegalReasoningEngine
    from src.legal_chatbot.intent import Intent

    engine = LegalReasoningEngine.__new__(LegalReasoningEngine)
    engine.llm_intent = MagicMock()
    engine.reasoner_chain = MagicMock()
    engine.reasoner_chain.invoke = MagicMock(return_value="   ")
    engine._build_reasoner_context = MagicMock(return_value="ctx")
    engine._remove_chinese_characters = MagicMock(return_value="")
    engine._analyze_and_retrieve = MagicMock(
        return_value=(
            "hợp đồng lương",
            "Điều 35 ... Điều 47 ...",
            [SimpleNamespace(page_content="Điều 35 ...", metadata={"article_number": 35})],
        )
    )

    with patch("src.legal_chatbot.reasoning_chain.classify_intent") as mock_intent, \
         patch("src.legal_chatbot.reasoning_chain.classify_query_mode", return_value="open_ended"), \
         patch("src.legal_chatbot.reasoning_chain.resolve_article_query", return_value=""), \
         patch("src.legal_chatbot.reasoning_chain.assess_retrieval_strength", return_value={"is_strong_enough": True}):
        mock_intent.return_value = SimpleNamespace(intent=Intent.LEGAL, response="", source="rule")
        result = engine.run_structured("Nếu tôi nghỉ ngay thì công ty còn phải thanh toán gì?", [])

    assert result.route == "rag_empty_fallback"
    assert isinstance(result.answer, str) and result.answer.strip()


def test_run_structured_followup_unpaid_wage_uses_deterministic_rule():
    from src.legal_chatbot.reasoning_chain import LegalReasoningEngine
    from src.legal_chatbot.intent import Intent

    engine = LegalReasoningEngine.__new__(LegalReasoningEngine)
    engine.llm_intent = MagicMock()
    engine._analyze_and_retrieve = MagicMock(side_effect=AssertionError("should not retrieve"))

    history = [HumanMessage(content="Tôi là người lao động, công ty đang nợ lương tôi 2 tháng.")]

    with patch("src.legal_chatbot.reasoning_chain.classify_intent") as mock_intent:
        mock_intent.return_value = SimpleNamespace(intent=Intent.LEGAL, response="", source="rule")
        result = engine.run_structured("Vậy tôi nghỉ ngay không báo trước có được không?", history)

    assert result.route == "rule_followup"
    assert "Điều 35" in result.answer
    assert "không cần báo trước" in result.answer


def test_run_structured_followup_unpaid_wage_settlement_question_prefers_settlement_answer():
    from src.legal_chatbot.reasoning_chain import LegalReasoningEngine
    from src.legal_chatbot.intent import Intent

    engine = LegalReasoningEngine.__new__(LegalReasoningEngine)
    engine.llm_intent = MagicMock()
    engine._analyze_and_retrieve = MagicMock(side_effect=AssertionError("should not retrieve"))

    history = [HumanMessage(content="Tôi là người lao động, công ty đang nợ lương tôi 2 tháng.")]

    with patch("src.legal_chatbot.reasoning_chain.classify_intent") as mock_intent:
        mock_intent.return_value = SimpleNamespace(intent=Intent.LEGAL, response="", source="rule")
        result = engine.run_structured(
            "Nếu tôi nghỉ ngay thì công ty còn phải thanh toán cho tôi những khoản nào?",
            history,
        )

    assert result.route == "rule_followup"
    assert "thanh toán" in result.answer.lower()
    assert "tiền lương" in result.answer.lower()


def test_run_structured_reasoner_429_returns_error_fallback():
    from src.legal_chatbot.reasoning_chain import LegalReasoningEngine
    from src.legal_chatbot.intent import Intent

    engine = LegalReasoningEngine.__new__(LegalReasoningEngine)
    engine.llm_intent = MagicMock()
    engine.reasoner_chain = MagicMock()
    engine.reasoner_chain.invoke = MagicMock(side_effect=RuntimeError("429 Too Many Requests"))
    engine._build_reasoner_context = MagicMock(return_value="ctx")
    engine._analyze_and_retrieve = MagicMock(
        return_value=(
            "hợp đồng lương",
            "Điều 35 ... Điều 47 ...",
            [SimpleNamespace(page_content="Điều 35 ...", metadata={"article_number": 35})],
        )
    )

    with patch("src.legal_chatbot.reasoning_chain.classify_intent") as mock_intent, \
         patch("src.legal_chatbot.reasoning_chain.classify_query_mode", return_value="open_ended"), \
         patch("src.legal_chatbot.reasoning_chain.resolve_article_query", return_value=""), \
         patch("src.legal_chatbot.reasoning_chain.assess_retrieval_strength", return_value={"is_strong_enough": True}):
        mock_intent.return_value = SimpleNamespace(intent=Intent.LEGAL, response="", source="rule")
        result = engine.run_structured("Cho tôi biết quyền lợi khi chấm dứt hợp đồng", [])

    assert result.route == "rag_error_fallback"
    assert "rate limit" in result.answer.lower() or "quá tải" in result.answer.lower()


def test_run_structured_clarifying_payload_uses_tag_not_literal_prefix():
    from src.legal_chatbot.reasoning_chain import LegalReasoningEngine
    from src.legal_chatbot.intent import Intent

    engine = LegalReasoningEngine.__new__(LegalReasoningEngine)
    engine.llm_intent = MagicMock()
    engine.CLARIFY_TAG = "[CLARIFY]"
    engine._is_clarifying_payload = LegalReasoningEngine._is_clarifying_payload.__get__(engine, LegalReasoningEngine)
    engine._strip_clarifying_payload = LegalReasoningEngine._strip_clarifying_payload.__get__(engine, LegalReasoningEngine)
    engine._analyze_and_retrieve = MagicMock(
        return_value=(
            "Điều 35",
            "[CLARIFY] Hãy nêu rõ bạn đang hỏi Điều 35 của văn bản nào.",
            [],
        )
    )

    with patch("src.legal_chatbot.reasoning_chain.classify_intent") as mock_intent, \
         patch("src.legal_chatbot.reasoning_chain.classify_query_mode", return_value="article_lookup"):
        mock_intent.return_value = SimpleNamespace(intent=Intent.LEGAL, response="", source="rule")
        result = engine.run_structured("Điều 35", [])

    assert result.route == "clarifying"
    assert result.answer.startswith("Hãy nêu rõ")
    assert "[CLARIFY]" not in result.answer
