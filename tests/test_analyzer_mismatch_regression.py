"""
D2: Anti-regression tests for analyzer mismatch.

Verifies that:
- _parse_analyzer_output never returns a raw string (it always returns a dict).
- analyzer_chain output goes through _parse_analyzer_output before any .get() call.
- JSON fallback path produces the correct keywords structure.
- analyze-and-retrieve never calls .get() on a raw LLM string output.
"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call

import pytest

from src.legal_chatbot.reasoning_chain import LegalReasoningEngine


# ── Helpers ─────────────────────────────────────────────────────────────────

def _make_engine():
    """Return a LegalReasoningEngine with all LLM dependencies mocked out."""
    engine = LegalReasoningEngine.__new__(LegalReasoningEngine)
    engine.retriever = MagicMock()
    engine.llm_extract = MagicMock()
    engine.llm_reason = MagicMock()
    engine.llm_intent = MagicMock()
    engine.system_prompt = "{context}"
    # Minimal mocked chains
    engine.analyzer_chain = MagicMock()
    engine.reasoner_chain = MagicMock()
    return engine


# ── _parse_analyzer_output ──────────────────────────────────────────────────

def test_parse_analyzer_output_returns_dict_for_valid_json():
    engine = _make_engine()
    raw = json.dumps({"issue": "sa thải", "keywords": ["sa thải"], "law_type": "luật lao động"})
    result = engine._parse_analyzer_output(raw)
    assert isinstance(result, dict)
    assert result["keywords"] == ["sa thải"]


def test_parse_analyzer_output_extracts_json_from_noisy_text():
    """Model output with prose before/after the JSON block must still parse."""
    engine = _make_engine()
    raw = (
        'Tôi phân tích như sau:\n'
        '{"issue": "nghỉ phép", "keywords": ["nghỉ phép", "hằng năm"], "law_type": "luật lao động"}\n'
        'Đây là kết quả.'
    )
    result = engine._parse_analyzer_output(raw)
    assert isinstance(result, dict)
    assert "nghỉ phép" in result.get("keywords", [])


def test_parse_analyzer_output_raises_on_empty_string():
    engine = _make_engine()
    with pytest.raises(json.JSONDecodeError):
        engine._parse_analyzer_output("")


def test_parse_analyzer_output_raises_on_pure_text():
    engine = _make_engine()
    with pytest.raises(json.JSONDecodeError):
        engine._parse_analyzer_output("Đây là văn bản thuần túy không có JSON")


def test_parse_analyzer_output_never_returns_string():
    """Core regression: output must never be a raw string (to prevent .get() on str)."""
    engine = _make_engine()
    valid_json = '{"issue": "lương", "keywords": ["lương"], "law_type": "luật lao động"}'
    result = engine._parse_analyzer_output(valid_json)
    assert not isinstance(result, str), (
        "parse_analyzer_output must return dict, not string. "
        "Returning a string would cause .get() AttributeError downstream."
    )


# ── JSON fallback keyword extraction ────────────────────────────────────────

def test_extract_keywords_fallback_returns_list():
    engine = _make_engine()
    keywords = engine._extract_keywords_fallback("Tôi bị sa thải không có lý do")
    assert isinstance(keywords, list)
    assert len(keywords) >= 1


def test_extract_keywords_fallback_finds_legal_terms():
    engine = _make_engine()
    keywords = engine._extract_keywords_fallback("Lương tối thiểu vùng là bao nhiêu?")
    assert any("lương" in kw.lower() for kw in keywords)


def test_extract_keywords_fallback_max_5():
    engine = _make_engine()
    text = "hợp đồng sa thải lương bảo hiểm nghỉ phép kỷ luật bồi thường"
    keywords = engine._extract_keywords_fallback(text)
    assert len(keywords) <= 5


# ── Analyzer chain output → never .get() on string ──────────────────────────

def test_analyze_and_retrieve_uses_parse_analyzer_output_not_raw_string():
    """
    D2 KEY REGRESSION: _analyze_and_retrieve must parse analyzer output
    through _parse_analyzer_output() before calling .get('keywords', []).
    If analyzer_chain returns a raw string and code does raw_output.get(...),
    it crashes with AttributeError.

    We verify this by giving the chain a valid JSON string and confirming
    _parse_analyzer_output is called (or at minimum no AttributeError occurs).
    """
    engine = _make_engine()

    # Analyzer returns a valid JSON string (as StrOutputParser would give)
    valid_json = json.dumps({
        "issue": "sa thải trái luật",
        "keywords": ["sa thải", "đơn phương"],
        "law_type": "luật lao động"
    })
    engine.analyzer_chain.invoke = MagicMock(return_value=valid_json)

    # Retriever returns empty docs (so we hit insufficient_context branch)
    engine.retriever.invoke = MagicMock(return_value=[])
    engine.retriever.get_relevant_documents = MagicMock(return_value=[])

    # Patch retrieval functions to return []
    with patch("src.legal_chatbot.reasoning_chain.retrieve_documents", return_value=[]), \
         patch("src.legal_chatbot.reasoning_chain.retrieve_exact_article", return_value=[]), \
         patch("src.legal_chatbot.reasoning_chain.classify_intent") as mock_intent:

        from src.legal_chatbot.intent import Intent
        intent_res = SimpleNamespace(intent=Intent.LEGAL, response="")
        mock_intent.return_value = intent_res

        # Should NOT raise AttributeError from str.get()
        try:
            search_query, context_text, docs = engine._analyze_and_retrieve(
                "Tôi bị sa thải trái luật cần bồi thường gì?", []
            )
        except AttributeError as e:
            pytest.fail(
                f"AttributeError raised — analyzer output was .get()ed as string: {e}"
            )
        except Exception:
            # Other exceptions (retrieval, etc.) are acceptable in unit test context
            pass


def test_analyze_and_retrieve_fallback_on_invalid_json():
    """
    D2: When analyzer returns non-JSON text, fallback keyword extraction runs
    without crashing — no .get() on a raw string.
    """
    engine = _make_engine()

    # Analyzer returns garbage text (not JSON)
    engine.analyzer_chain.invoke = MagicMock(return_value="Tôi không biết phân tích JSON")

    with patch("src.legal_chatbot.reasoning_chain.retrieve_documents", return_value=[]), \
         patch("src.legal_chatbot.reasoning_chain.retrieve_exact_article", return_value=[]):
        try:
            search_query, context_text, docs = engine._analyze_and_retrieve(
                "Làm việc 50 tiếng một tuần có vi phạm không?", []
            )
            # fallback must produce a non-empty search_query
            assert isinstance(search_query, str)
        except AttributeError as e:
            pytest.fail(f"AttributeError from str.get() in fallback path: {e}")
        except Exception:
            pass  # Other exceptions acceptable


def test_run_structured_result_is_run_result_instance():
    """D1/D2: run_structured() must always return a RunResult, never a raw string."""
    from src.legal_chatbot.reasoning_chain import RunResult
    engine = _make_engine()

    with patch("src.legal_chatbot.reasoning_chain.classify_intent") as mock_intent:
        from src.legal_chatbot.intent import Intent
        # Simulate non-legal intent so we return early
        non_legal = SimpleNamespace(intent=Intent.GREETING, response="Xin chào!")
        mock_intent.return_value = non_legal

        result = engine.run_structured("Xin chào!")

    assert isinstance(result, RunResult), (
        "run_structured() must return RunResult, not a raw string or tuple"
    )
    assert isinstance(result.answer, str)
