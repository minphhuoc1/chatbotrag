from types import SimpleNamespace

from src.legal_chatbot.policy import (
    assess_retrieval_strength,
    build_insufficient_context_response,
    detect_unilateral_termination_role,
    suggest_target_articles,
)


def _doc(article_number: int):
    return SimpleNamespace(
        metadata={"article_number": article_number},
        page_content=f"Điều {article_number}. Nội dung mô phỏng.",
    )


def test_detect_unilateral_termination_role():
    assert (
        detect_unilateral_termination_role(
            "Nếu người lao động đơn phương chấm dứt trái luật thì phải bồi thường gì?"
        )
        == "employee"
    )
    assert (
        detect_unilateral_termination_role(
            "Nếu công ty đơn phương chấm dứt hợp đồng trái pháp luật thì bồi thường sao?"
        )
        == "employer"
    )
    assert (
        detect_unilateral_termination_role(
            "Đơn phương chấm dứt trái luật thì phải bồi thường gì?"
        )
        == "ambiguous"
    )
    assert (
        detect_unilateral_termination_role(
            "Điều 113 quy định nghỉ hằng năm ra sao?"
        )
        == "none"
    )


def test_suggest_target_articles_prioritizes_unlawful_unilateral_compensation():
    employee_hints = suggest_target_articles(
        "Nếu người lao động đơn phương chấm dứt trái luật thì bồi thường gì?"
    )
    employer_hints = suggest_target_articles(
        "Nếu công ty đơn phương chấm dứt trái pháp luật thì phải bồi thường gì?"
    )
    ambiguous_hints = suggest_target_articles(
        "Đơn phương chấm dứt trái pháp luật thì bồi thường ra sao?"
    )

    assert 40 in employee_hints
    assert 41 in employer_hints
    assert 40 in ambiguous_hints and 41 in ambiguous_hints


def test_assess_retrieval_strength_requires_core_articles_for_role_specific_query():
    query = "Nếu người lao động đơn phương chấm dứt trái luật thì phải bồi thường gì?"
    docs_missing_40 = [_doc(35), _doc(36), _doc(34)]
    result = assess_retrieval_strength(query, docs_missing_40)

    assert result["is_strong_enough"] is False
    assert result["reason"] == "required compensation article not retrieved"
    assert result["required_articles"] == [40]


def test_assess_retrieval_strength_asks_for_clarification_when_role_ambiguous():
    query = "Đơn phương chấm dứt trái pháp luật thì phải bồi thường gì?"
    docs_with_both = [_doc(40), _doc(41), _doc(35)]
    result = assess_retrieval_strength(query, docs_with_both)

    assert result["is_strong_enough"] is False
    assert result["reason"] == "ambiguous legal subject for compensation"
    answer = build_insufficient_context_response(
        user_input=query,
        query_mode="open_ended",
        retrieval_check=result,
    )
    assert "Điều 40" in answer
    assert "Điều 41" in answer
    assert "Bạn đang hỏi trường hợp nào" in answer

