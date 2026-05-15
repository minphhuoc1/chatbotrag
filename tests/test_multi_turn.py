# -*- coding: utf-8 -*-
"""
Multi-turn test runner.
Chạy từng case theo chuỗi turn, tích lũy chat_history giữa các turn.
"""
import json
import sys
from pathlib import Path
from datetime import datetime

import yaml
from langchain_core.messages import HumanMessage, AIMessage

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from test_legal_qa import init_runtime  # dùng lại init đã có

CASES_PATH = Path("tests/cases/multi_turn_cases.yaml")
REPORT_DIR = Path("reports/multi_turn")
REPORT_DIR.mkdir(parents=True, exist_ok=True)


def _check_turn(result, turn_spec: dict) -> dict:
    """Kiểm tra một turn theo spec, trả về dict kết quả."""
    checks = {}
    route = result.route or "unknown"

    # Check route
    if "expected_route" in turn_spec:
        checks["route_ok"] = (route == turn_spec["expected_route"])
    elif "expected_route_any_of" in turn_spec:
        checks["route_ok"] = (route in turn_spec["expected_route_any_of"])
    else:
        checks["route_ok"] = True  # không check

    if "must_not_route" in turn_spec:
        checks["must_not_route_ok"] = (route not in turn_spec["must_not_route"])

    # Check articles
    if "expected_articles" in turn_spec:
        answer = result.answer or ""
        cited = []
        import re
        cited = [m for m in re.findall(r"[Đđ]iều\s*(\d+)", answer)]
        expected = [str(a) for a in turn_spec["expected_articles"]]
        hits = [e for e in expected if e in cited]
        checks["article_coverage"] = len(hits) / len(expected) if expected else 1.0
        checks["article_coverage_ok"] = checks["article_coverage"] >= 0.5

    # Check ask_back
    if turn_spec.get("must_not_ask_back"):
        answer_lower = (result.answer or "").lower()
        ask_back_signals = ["bạn có thể cho biết", "bạn vui lòng", "cho biết thêm", "bạn đang hỏi"]
        checks["no_ask_back_ok"] = not any(s in answer_lower for s in ask_back_signals)

    # Check forbidden phrases
    if "must_not_contain" in turn_spec:
        answer_lower = (result.answer or "").lower()
        checks["no_forbidden_phrase_ok"] = not any(
            phrase.lower() in answer_lower
            for phrase in turn_spec["must_not_contain"]
        )

    checks["passed"] = all(v for v in checks.values() if isinstance(v, bool))
    return checks


def run_multi_turn_tests(mock_llm: bool = True):
    with open(CASES_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    runtime = init_runtime()
    if mock_llm:
        from route_distribution_structured import _attach_mock_llm
        _attach_mock_llm(runtime)

    results = []
    passed_cases = 0
    total_cases = 0

    for case in data["cases"]:
        case_id = case["id"]
        chat_history = []
        turn_results = []
        case_passed = True

        for i, turn in enumerate(case["turns"]):
            if turn["role"] != "user":
                continue

            result = runtime.engine.run_structured(
                user_input=turn["content"],
                chat_history=chat_history,
            )

            turn_checks = _check_turn(result, turn)
            if not turn_checks["passed"]:
                case_passed = False

            turn_results.append({
                "turn": i + 1,
                "input": turn["content"],
                "route": result.route,
                "answer_snippet": (result.answer or "")[:200],
                "checks": turn_checks,
                "note": turn.get("note", ""),
            })

            # Tích lũy chat_history cho turn tiếp theo
            chat_history.append(HumanMessage(content=turn["content"]))
            chat_history.append(AIMessage(content=result.answer or ""))

        total_cases += 1
        if case_passed:
            passed_cases += 1

        results.append({
            "case_id": case_id,
            "description": case.get("description", ""),
            "passed": case_passed,
            "turns": turn_results,
        })

    report = {
        "generated_at": datetime.now().isoformat(),
        "mode": "mock_llm" if mock_llm else "real_llm",
        "summary": {
            "total_cases": total_cases,
            "passed_cases": passed_cases,
            "failed_cases": total_cases - passed_cases,
            "pass_rate": passed_cases / total_cases if total_cases else 0,
        },
        "results": results,
    }

    out_path = REPORT_DIR / f"multi_turn_{report['mode']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # Print summary
    print(f"\n{'='*50}")
    print(f"Multi-Turn Test: {passed_cases}/{total_cases} cases passed")
    print(f"{'='*50}")
    for r in results:
        status = "✅" if r["passed"] else "❌"
        print(f"{status} {r['case_id']}: {r['description']}")
        for t in r["turns"]:
            route_ok = t["checks"].get("route_ok", True)
            print(f"   Turn {t['turn']}: route={t['route']} {'✅' if route_ok else '❌'}")
            if not t["checks"]["passed"]:
                failed = [k for k, v in t["checks"].items() if isinstance(v, bool) and not v]
                print(f"   Failed checks: {failed}")

    print(f"\nReport: {out_path}")
    return report


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--real-llm", action="store_true")
    args = parser.parse_args()
    run_multi_turn_tests(mock_llm=not args.real_llm)
