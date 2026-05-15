from __future__ import annotations

from typing import Any, Dict, List, Set


RUBRIC_VERSION = "2026-04-r1"
RUBRIC_WEIGHTS = {
    "retrieval": 0.30,
    "grounding": 0.30,
    "policy": 0.25,
    "reasoning": 0.15,
}

ROOT_CAUSE_LABELS = ("retrieval", "prompt", "policy", "model")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _clamp(value: float, low: float = 0.0, high: float = 5.0) -> float:
    return max(low, min(high, value))


def _grade(score: float) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


def _safe_bool(container: Dict[str, Any], key: str, default: bool = False) -> bool:
    return bool(container.get(key, default))


def _extract_retrieved_articles(result: Dict[str, Any]) -> Set[int]:
    rows = result.get("retrieval_layer", {}).get("top_k_chunks", [])
    out: Set[int] = set()
    for row in rows:
        raw = row.get("article_number")
        if raw is None:
            continue
        raw_str = str(raw).strip()
        if raw_str.isdigit():
            out.add(int(raw_str))
    return out


def _reference_coverage(expected_refs: Set[int], retrieved_refs: Set[int]) -> float:
    if not expected_refs:
        return 1.0
    if not retrieved_refs:
        return 0.0
    return len(expected_refs.intersection(retrieved_refs)) / len(expected_refs)


def _score_retrieval(
    expected_refs: Set[int],
    retrieved_refs: Set[int],
    retrieval_strong: bool,
) -> float:
    coverage = _reference_coverage(expected_refs, retrieved_refs)
    if retrieval_strong and coverage >= 1.0:
        return 5.0
    if retrieval_strong and coverage >= 0.5:
        return 4.0
    if retrieval_strong and coverage > 0:
        return 3.0
    if retrieval_strong and not expected_refs:
        return 3.0
    if coverage > 0:
        return 2.0
    if retrieved_refs:
        return 1.0
    return 0.0


def _score_grounding(result: Dict[str, Any]) -> float:
    checks = result.get("checks", {})
    answer = result.get("answer_grounding_layer", {})
    behavior = result.get("legal_behavior_layer", {})

    score = 5.0
    if not _safe_bool(answer, "grounded_ok", True):
        score -= 2.5
    if not _safe_bool(answer, "citation_ok", True):
        score -= 1.5
    quote_ok = answer.get("quote_ok")
    if quote_ok is False:
        score -= 1.5
    if not _safe_bool(checks, "must_not_hallucinate_ok", True):
        score -= 2.0
    if _safe_bool(behavior, "hard_fail_hallucinated_law_or_quote", False):
        score -= 2.0
    if not _safe_bool(checks, "no_runaway_generation_ok", True):
        score -= 3.0
    if _safe_bool(behavior, "runaway_generation_detected", False):
        score -= 1.5

    return _clamp(score)


def _score_policy(result: Dict[str, Any]) -> float:
    checks = result.get("checks", {})
    behavior = result.get("legal_behavior_layer", {})

    score = 5.0
    if not _safe_bool(checks, "mode_ok", True):
        score -= 2.5
    if not _safe_bool(checks, "correct_refusal_on_weak_context", True):
        score -= 1.5
    if not _safe_bool(behavior, "issue_recognition_ok", True):
        score -= 1.5
    if _safe_bool(behavior, "asked_back_redundantly", False):
        score -= 1.0
    if not _safe_bool(behavior, "asked_back_when_needed", True):
        score -= 1.0

    return _clamp(score)


def _score_reasoning(
    case: Dict[str, Any],
    result: Dict[str, Any],
    retrieval_strong: bool,
    expected_coverage: float,
) -> float:
    checks = result.get("checks", {})
    behavior = result.get("legal_behavior_layer", {})
    fallback = result.get("guard_fallback_layer", {})

    score = 5.0
    if not _safe_bool(checks, "must_reference_ok", True):
        score -= 2.0
    if _safe_bool(behavior, "overclaim_without_evidence", False):
        score -= 2.0

    expected_mode = case.get("expected_mode")
    fallback_triggered = _safe_bool(fallback, "fallback_triggered", False)
    if expected_mode == "grounded_legal_answer" and fallback_triggered and retrieval_strong and expected_coverage >= 0.5:
        score -= 1.0
    if _safe_bool(behavior, "runaway_generation_detected", False):
        score -= 2.0

    return _clamp(score)


def _classify_root_cause(
    case: Dict[str, Any],
    result: Dict[str, Any],
    expected_refs: Set[int],
    retrieved_refs: Set[int],
    scores: Dict[str, float],
) -> Dict[str, Any]:
    checks = result.get("checks", {})
    retrieval_layer = result.get("retrieval_layer", {})
    fallback_layer = result.get("guard_fallback_layer", {})
    answer_layer = result.get("answer_grounding_layer", {})
    behavior = result.get("legal_behavior_layer", {})

    if all(bool(v) for v in checks.values()):
        return {
            "primary": "none",
            "confidence": 1.0,
            "scores": {k: 0 for k in ROOT_CAUSE_LABELS},
            "evidence": [],
        }

    retrieval_strong = _safe_bool(retrieval_layer, "is_strong_enough", False)
    coverage = _reference_coverage(expected_refs, retrieved_refs)
    fallback_reason = str(fallback_layer.get("fallback_reason", "")).strip()

    cause_scores: Dict[str, int] = {k: 0 for k in ROOT_CAUSE_LABELS}
    evidence: List[str] = []

    if not retrieval_strong:
        cause_scores["retrieval"] += 3
        evidence.append("retrieval_strength=weak")
    if expected_refs and coverage == 0:
        cause_scores["retrieval"] += 3
        evidence.append("expected_refs_not_retrieved")
    elif expected_refs and coverage < 1:
        cause_scores["retrieval"] += 1
        evidence.append("expected_refs_partial_coverage")
    if fallback_reason in {"weak_context", "missing_exact_article"}:
        cause_scores["retrieval"] += 1
        evidence.append(f"fallback_reason={fallback_reason}")

    if not _safe_bool(checks, "mode_ok", True):
        cause_scores["policy"] += 3
        evidence.append("mode_contract_mismatch")
    if not _safe_bool(checks, "correct_refusal_on_weak_context", True):
        cause_scores["policy"] += 2
        evidence.append("weak_context_refusal_mismatch")
    if not _safe_bool(behavior, "issue_recognition_ok", True):
        cause_scores["policy"] += 2
        evidence.append("intent_or_scope_misclassification")
    if _safe_bool(behavior, "asked_back_redundantly", False):
        cause_scores["policy"] += 1
        evidence.append("redundant_clarification")
    if not _safe_bool(behavior, "asked_back_when_needed", True):
        cause_scores["policy"] += 2
        evidence.append("missing_required_clarification")

    prompt_candidate = (
        retrieval_strong
        and coverage >= 0.5
        and not _safe_bool(checks, "must_reference_ok", True)
        and _safe_bool(answer_layer, "citation_ok", True)
        and _safe_bool(answer_layer, "grounded_ok", True)
    )
    if prompt_candidate:
        cause_scores["prompt"] += 3
        evidence.append("instruction_following_weak_on_citations")

    query_mode = retrieval_layer.get("query_mode_detected")
    if query_mode in {"article_lookup", "quote_request"} and prompt_candidate:
        cause_scores["prompt"] += 1
        evidence.append(f"query_mode={query_mode}_needs_tighter_prompt_contract")

    if retrieval_strong and (
        not _safe_bool(answer_layer, "grounded_ok", True)
        or not _safe_bool(answer_layer, "citation_ok", True)
        or not _safe_bool(checks, "must_not_hallucinate_ok", True)
        or _safe_bool(behavior, "hard_fail_hallucinated_law_or_quote", False)
        or _safe_bool(behavior, "overclaim_without_evidence", False)
    ):
        cause_scores["model"] += 3
        evidence.append("reasoning_or_generation_instability")
    if _safe_bool(behavior, "runaway_generation_detected", False) or not _safe_bool(checks, "no_runaway_generation_ok", True):
        cause_scores["model"] += 4
        evidence.append("runaway_generation_detected")

    if case.get("expected_mode") == "grounded_legal_answer" and _safe_bool(fallback_layer, "fallback_triggered", False):
        if retrieval_strong and coverage >= 0.5:
            cause_scores["policy"] += 2
            evidence.append("fallback_triggered_despite_usable_context")

    top = sorted(cause_scores.items(), key=lambda kv: kv[1], reverse=True)
    primary = top[0][0] if top and top[0][1] > 0 else "model"
    top_score = top[0][1] if top else 0
    second_score = top[1][1] if len(top) > 1 else 0
    confidence = round(min(0.95, 0.55 + 0.08 * top_score + 0.03 * (top_score - second_score)), 2)
    if top_score == 0:
        confidence = 0.5

    return {
        "primary": primary,
        "confidence": confidence,
        "scores": cause_scores,
        "evidence": evidence[:8],
    }


def evaluate_case_with_rubric(case: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    expected_refs = {
        int(x) for x in case.get("must_reference_any_of", []) if str(x).isdigit()
    }
    retrieved_refs = _extract_retrieved_articles(result)
    retrieval_strong = _safe_bool(result.get("retrieval_layer", {}), "is_strong_enough", False)
    coverage = _reference_coverage(expected_refs, retrieved_refs)

    dimension_scores = {
        "retrieval": _score_retrieval(expected_refs, retrieved_refs, retrieval_strong),
        "grounding": _score_grounding(result),
        "policy": _score_policy(result),
        "reasoning": _score_reasoning(case, result, retrieval_strong, coverage),
    }

    weighted_score = round(
        sum((dimension_scores[k] / 5.0) * RUBRIC_WEIGHTS[k] for k in RUBRIC_WEIGHTS) * 100.0,
        2,
    )
    root_cause = _classify_root_cause(
        case=case,
        result=result,
        expected_refs=expected_refs,
        retrieved_refs=retrieved_refs,
        scores=dimension_scores,
    )

    return {
        "rubric_version": RUBRIC_VERSION,
        "weights": RUBRIC_WEIGHTS,
        "dimension_scores": {k: round(v, 2) for k, v in dimension_scores.items()},
        "weighted_score": weighted_score,
        "grade": _grade(weighted_score),
        "root_cause": root_cause,
        "reference_coverage": {
            "expected_articles": sorted(expected_refs),
            "retrieved_articles": sorted(retrieved_refs),
            "coverage_ratio": round(coverage, 4),
        },
    }


def summarize_rubric(evaluations: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not evaluations:
        return {
            "rubric_version": RUBRIC_VERSION,
            "average_weighted_score": 0.0,
            "dimension_averages": {k: 0.0 for k in RUBRIC_WEIGHTS},
            "grade_distribution": {},
            "root_cause_distribution": {k: 0 for k in ROOT_CAUSE_LABELS},
            "low_score_cases": 0,
        }

    total = len(evaluations)
    dim_sums = {k: 0.0 for k in RUBRIC_WEIGHTS}
    grade_dist: Dict[str, int] = {}
    cause_dist = {k: 0 for k in ROOT_CAUSE_LABELS}
    low_score_cases = 0
    weighted_sum = 0.0

    for ev in evaluations:
        weighted_score = _to_float(ev.get("weighted_score"), 0.0)
        weighted_sum += weighted_score
        if weighted_score < 70:
            low_score_cases += 1

        grade = str(ev.get("grade", "F"))
        grade_dist[grade] = grade_dist.get(grade, 0) + 1

        dims = ev.get("dimension_scores", {})
        for k in dim_sums:
            dim_sums[k] += _to_float(dims.get(k), 0.0)

        primary = str(ev.get("root_cause", {}).get("primary", ""))
        if primary in cause_dist:
            cause_dist[primary] += 1

    return {
        "rubric_version": RUBRIC_VERSION,
        "average_weighted_score": round(weighted_sum / total, 2),
        "dimension_averages": {k: round(v / total, 2) for k, v in dim_sums.items()},
        "grade_distribution": grade_dist,
        "root_cause_distribution": cause_dist,
        "low_score_cases": low_score_cases,
    }
