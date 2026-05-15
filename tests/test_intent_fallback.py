from unittest.mock import MagicMock

from langchain_core.messages import AIMessage

from src.legal_chatbot.intent import Intent, classify_intent


def test_llm_fallback_returns_offtopic_when_offtopic_signal_present():
    llm = MagicMock()
    llm.invoke.side_effect = RuntimeError("429")
    result = classify_intent("Real Madrid tối qua đá sao rồi?", llm=llm)
    assert result.intent == Intent.OFF_TOPIC
    assert result.source in {"rule", "rule_offtopic_guard", "llm_fallback_rule_offtopic"}
    assert result.response


def test_llm_fallback_keeps_legal_when_no_offtopic_signal():
    llm = MagicMock()
    llm.invoke.side_effect = RuntimeError("429")
    result = classify_intent("Tôi cần tư vấn thêm", llm=llm)
    assert result.intent == Intent.LEGAL
    assert result.source == "llm_fallback"


def test_context_carry_does_not_override_explicit_offtopic():
    llm = MagicMock()
    llm.invoke.side_effect = RuntimeError("429")
    history = [
        AIMessage(
            content=(
                "Điều 113 có nội dung về nghỉ hằng năm và có đoạn người sử dụng lao động "
                "phải thông báo trước cho người lao động."
            )
        )
    ]
    result = classify_intent(
        "Real Madrid tối qua đá sao rồi?",
        llm=llm,
        chat_history=history,
    )
    assert result.intent == Intent.OFF_TOPIC
    assert result.source in {"rule", "rule_offtopic_guard", "llm_fallback_rule_offtopic"}


def test_context_carry_still_keeps_legal_for_real_clarifying_followup():
    history = [AIMessage(content="Bạn đang hỏi theo trường hợp nào để tôi trả lời chính xác?")]
    result = classify_intent("Mình là người lao động", llm=None, chat_history=history)
    assert result.intent == Intent.LEGAL
    assert result.source == "context_carry"
