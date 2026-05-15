# -*- coding: utf-8 -*-
"""
Evaluate candidate hints against test_cases.yaml before enabling in runtime.

Outputs:
- reports/qa/hints_eval_<timestamp>.json
- artifacts/hints/approved_hints_suggested_<timestamp>.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import yaml

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from src.legal_chatbot import policy
from src.legal_chatbot.config import TEST_CASES_PATH


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _dedup(items: list[int]) -> list[int]:
    seen = set()
    out = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _load_candidates(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = payload.get("hints", []) if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        return []

    cleaned = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        keywords = item.get("keywords", item.get("terms", []))
        if isinstance(keywords, str):
            keywords = [keywords]
        if not isinstance(keywords, list):
            continue
        keywords = [_norm(k) for k in keywords if isinstance(k, str) and _norm(k)]
        if not keywords:
            continue

        articles = item.get("articles", item.get("article_numbers", []))
        if isinstance(articles, int):
            articles = [articles]
        if isinstance(articles, str) and articles.isdigit():
            articles = [int(articles)]
        if not isinstance(articles, list):
            continue
        parsed_articles = []
        for article in articles:
            if isinstance(article, str) and article.isdigit():
                article = int(article)
            if isinstance(article, int) and article > 0:
                parsed_articles.append(article)
        parsed_articles = _dedup(parsed_articles)
        if not parsed_articles:
            continue

        cleaned.append(
            {
                "keywords": keywords,
                "articles": parsed_articles,
                "confidence": float(item.get("confidence", 0.5)),
                "source": item.get("source", "candidate"),
            }
        )
    return cleaned


def _load_cases(path: Path) -> list[dict]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    cases = payload.get("cases", []) if isinstance(payload, dict) else []
    return cases if isinstance(cases, list) else []


def _matches_hint(user_query: str, hint: dict) -> bool:
    text = _norm(user_query)
    keywords = hint.get("keywords", [])
    return bool(keywords) and all(kw in text for kw in keywords)


def _suggest_with_candidates(user_query: str, candidates: list[dict]) -> list[int]:
    base = list(policy.suggest_target_articles(user_query))
    for hint in candidates:
        if _matches_hint(user_query, hint):
            base.extend(hint.get("articles", []))
    return _dedup(base)


def _latest_candidate_file(candidates_dir: Path) -> Path | None:
    files = sorted(candidates_dir.glob("candidate_hints_*.json"), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def evaluate(cases: list[dict], candidates: list[dict]) -> dict:
    rows = []
    baseline_hits = 0
    expanded_hits = 0
    legal_cases = 0
    fallback_cases = 0
    baseline_fallback_positive = 0
    expanded_fallback_positive = 0

    for case in cases:
        query = str(case.get("query", "") or "").strip()
        expected = [int(a) for a in case.get("must_reference_any_of", []) if isinstance(a, int)]
        expected_mode = str(case.get("expected_mode", "") or "").strip()

        baseline = policy.suggest_target_articles(query)
        expanded = _suggest_with_candidates(query, candidates)

        if expected:
            legal_cases += 1
            baseline_hit = any(a in baseline for a in expected)
            expanded_hit = any(a in expanded for a in expected)
            baseline_hits += int(baseline_hit)
            expanded_hits += int(expanded_hit)
        else:
            fallback_cases += 1
            baseline_hit = False
            expanded_hit = False
            baseline_fallback_positive += int(bool(baseline))
            expanded_fallback_positive += int(bool(expanded))

        rows.append(
            {
                "id": case.get("id"),
                "query": query,
                "expected_mode": expected_mode,
                "expected_articles": expected,
                "baseline_hints": baseline,
                "expanded_hints": expanded,
                "baseline_hit": baseline_hit,
                "expanded_hit": expanded_hit,
                "improved": (not baseline_hit and expanded_hit) if expected else False,
            }
        )

    coverage_baseline = (baseline_hits / legal_cases) if legal_cases else 0.0
    coverage_expanded = (expanded_hits / legal_cases) if legal_cases else 0.0
    fallback_positive_baseline = (
        baseline_fallback_positive / fallback_cases if fallback_cases else 0.0
    )
    fallback_positive_expanded = (
        expanded_fallback_positive / fallback_cases if fallback_cases else 0.0
    )

    return {
        "summary": {
            "total_cases": len(cases),
            "legal_cases": legal_cases,
            "fallback_cases": fallback_cases,
            "baseline_coverage": round(coverage_baseline, 4),
            "expanded_coverage": round(coverage_expanded, 4),
            "coverage_gain": round(coverage_expanded - coverage_baseline, 4),
            "baseline_fallback_positive_rate": round(fallback_positive_baseline, 4),
            "expanded_fallback_positive_rate": round(fallback_positive_expanded, 4),
        },
        "cases": rows,
    }


def score_candidates(cases: list[dict], candidates: list[dict]) -> list[dict]:
    scored = []
    for idx, cand in enumerate(candidates):
        triggered = 0
        helpful = 0
        noisy = 0
        for case in cases:
            query = str(case.get("query", "") or "")
            expected = [int(a) for a in case.get("must_reference_any_of", []) if isinstance(a, int)]
            if not _matches_hint(query, cand):
                continue
            triggered += 1
            cand_articles = cand.get("articles", [])
            if expected:
                if any(a in cand_articles for a in expected):
                    helpful += 1
                else:
                    noisy += 1
            else:
                noisy += 1

        precision = helpful / triggered if triggered else 0.0
        score = helpful - noisy
        scored.append(
            {
                "candidate_index": idx,
                "keywords": cand.get("keywords", []),
                "articles": cand.get("articles", []),
                "confidence": float(cand.get("confidence", 0.5)),
                "triggered_cases": triggered,
                "helpful_cases": helpful,
                "noisy_cases": noisy,
                "precision": round(precision, 4),
                "score": score,
            }
        )
    scored.sort(
        key=lambda x: (
            -x["score"],
            -x["helpful_cases"],
            x["noisy_cases"],
            -x["confidence"],
        )
    )
    return scored


def select_approved(scored: list[dict], min_confidence: float = 0.55) -> list[dict]:
    approved = []
    for item in scored:
        if item["helpful_cases"] < 1:
            continue
        if item["noisy_cases"] != 0:
            continue
        if item["precision"] < 0.5:
            continue
        if item["confidence"] < min_confidence:
            continue
        approved.append(
            {
                "keywords": item["keywords"],
                "articles": item["articles"],
                "enabled": True,
                "source": "candidate_eval_auto_v1",
                "confidence": item["confidence"],
                "score": item["score"],
            }
        )
    return approved


def main():
    parser = argparse.ArgumentParser(description="Evaluate synthetic hint candidates.")
    parser.add_argument(
        "--candidate-path",
        default="",
        help="Path tới candidate_hints_*.json (để trống -> lấy file mới nhất trong artifacts/hints).",
    )
    parser.add_argument(
        "--test-cases",
        default=str(TEST_CASES_PATH),
        help="Path test_cases.yaml",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.55,
        help="Ngưỡng confidence cho approved hints suggested.",
    )
    args = parser.parse_args()

    candidates_dir = ROOT_DIR / "artifacts" / "hints"
    if args.candidate_path:
        candidate_path = Path(args.candidate_path)
    else:
        candidate_path = _latest_candidate_file(candidates_dir)
        if candidate_path is None:
            raise SystemExit(
                "Không tìm thấy candidate_hints_*.json. Hãy chạy scripts/generate_synthetic_hints.py trước."
            )

    test_cases_path = Path(args.test_cases)
    if not test_cases_path.exists():
        raise SystemExit(f"Không tìm thấy test cases: {test_cases_path}")
    if not candidate_path.exists():
        raise SystemExit(f"Không tìm thấy candidate hints: {candidate_path}")

    cases = _load_cases(test_cases_path)
    candidates = _load_candidates(candidate_path)

    evaluation = evaluate(cases, candidates)
    scored = score_candidates(cases, candidates)
    approved = select_approved(scored, min_confidence=args.min_confidence)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_dir = ROOT_DIR / "reports" / "qa"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"hints_eval_{stamp}.json"

    approved_dir = ROOT_DIR / "artifacts" / "hints"
    approved_dir.mkdir(parents=True, exist_ok=True)
    approved_path = approved_dir / f"approved_hints_suggested_{stamp}.json"

    report_payload = {
        "schema_version": 1,
        "generated_at": datetime.now().isoformat(),
        "candidate_path": str(candidate_path),
        "test_cases_path": str(test_cases_path),
        "summary": evaluation["summary"],
        "top_candidates": scored[:60],
        "cases": evaluation["cases"],
    }
    report_path.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    approved_payload = {
        "schema_version": 1,
        "generated_at": datetime.now().isoformat(),
        "source_candidate_path": str(candidate_path),
        "selection_rule": {
            "min_confidence": args.min_confidence,
            "must_helpful_cases_at_least": 1,
            "max_noisy_cases": 0,
        },
        "hints": approved,
    }
    approved_path.write_text(json.dumps(approved_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("✅ Candidate hint evaluation completed.")
    print(f"   Evaluation report: {report_path}")
    print(f"   Suggested approved hints: {approved_path}")
    print(f"   Approved count (suggested): {len(approved)}")


if __name__ == "__main__":
    main()
