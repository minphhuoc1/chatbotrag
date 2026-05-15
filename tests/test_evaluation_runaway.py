from src.legal_chatbot.evaluation import evaluate_case_with_rubric


def _base_case_result():
    return {
        "checks": {
            "mode_ok": True,
            "must_reference_ok": True,
            "must_not_hallucinate_ok": True,
            "grounded_ok": True,
            "correct_refusal_on_weak_context": True,
            "no_runaway_generation_ok": True,
        },
        "retrieval_layer": {
            "is_strong_enough": True,
            "query_mode_detected": "open_ended",
            "top_k_chunks": [{"article_number": "46"}],
        },
        "guard_fallback_layer": {"fallback_triggered": False, "fallback_reason": ""},
        "answer_grounding_layer": {"grounded_ok": True, "citation_ok": True},
        "legal_behavior_layer": {
            "issue_recognition_ok": True,
            "asked_back_redundantly": False,
            "asked_back_when_needed": True,
            "overclaim_without_evidence": False,
            "hard_fail_hallucinated_law_or_quote": False,
            "runaway_generation_detected": False,
        },
    }


def test_runaway_generation_is_scored_as_failure_signal():
    case = {
        "id": 30,
        "expected_mode": "grounded_legal_answer",
        "must_reference_any_of": [46],
    }
    result = _base_case_result()
    result["checks"]["no_runaway_generation_ok"] = False
    result["checks"]["must_not_hallucinate_ok"] = False
    result["checks"]["grounded_ok"] = False
    result["answer_grounding_layer"]["grounded_ok"] = False
    result["legal_behavior_layer"]["runaway_generation_detected"] = True

    scored = evaluate_case_with_rubric(case, result)

    assert scored["weighted_score"] < 70.0
    assert scored["root_cause"]["primary"] == "model"
    assert "runaway_generation_detected" in scored["root_cause"]["evidence"]

