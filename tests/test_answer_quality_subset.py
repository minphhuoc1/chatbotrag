
# -*- coding: utf-8 -*-
"""
Answer quality test — chạy 5 cases đại diện với real LLM.
Mục đích: đo faithfulness và grounding thực tế, không phải chỉ routing.

Chọn cases đại diện đa dạng route:
  case 5  — rag, open-ended
  case 6  — rag, kỷ luật sa thải
  case 26 — rag, fact pattern mơ hồ
  case 2  — quote_direct
  case 22 — insufficient_context (Điều 250)
"""
import time, json, re
from pathlib import Path
from datetime import datetime
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from test_legal_qa import init_runtime
import yaml

TARGET_IDS = {2, 5, 6, 22, 26}
SLEEP_BETWEEN = 8  # giây — tránh 429

CASES_PATH = Path("tests/cases")
# dùng lại file cases gốc
with open(next(CASES_PATH.glob("*.yaml")), encoding="utf-8") as f:
    ALL_CASES = {c["id"]: c for c in yaml.safe_load(f)["cases"]}

REPORT_DIR = Path("reports/answer_quality")
REPORT_DIR.mkdir(parents=True, exist_ok=True)


RUBRIC = {
    "citation_present":     "Câu trả lời có trích dẫn số Điều cụ thể không?",
    "no_runaway":           "Câu trả lời không bị lặp vòng (runaway generation)?",
    "grounded":             "Nội dung dựa trên văn bản pháp luật, không bịa?",
    "answers_question":     "Câu hỏi được trả lời đúng trọng tâm không?",
}


def _auto_check(answer: str, case: dict) -> dict:
    """Các check tự động không cần human."""
    checks = {}

    # Runaway check
    chunks = answer.split()
    ngram_counts = {}
    for i in range(len(chunks) - 4):
        ng = tuple(chunks[i:i+5])
        ngram_counts[ng] = ngram_counts.get(ng, 0) + 1
    max_repeat = max(ngram_counts.values()) if ngram_counts else 0
    checks["no_runaway"] = max_repeat < 5

    # Citation check
    cited = re.findall(r"[Đđ]iều\s*(\d+)", answer)
    checks["has_citation"] = len(cited) > 0

    # Expected articles check
    if "expected_articles" in case:
        expected = [str(a) for a in case["expected_articles"]]
        checks["article_coverage"] = len([e for e in expected if e in cited]) / len(expected)

    return checks


def run():
    runtime = init_runtime()
    rows = []

    for case_id in sorted(TARGET_IDS):
        case = ALL_CASES.get(case_id)
        if not case:
            print(f"[SKIP] case {case_id} not found")
            continue

        print(f"\n[{case_id}] {case['query'][:60]}...")
        try:
            result = runtime.engine.run_structured(user_input=case["query"], chat_history=[])
            auto = _auto_check(result.answer or "", case)
            rows.append({
                "case_id": case_id,
                "query": case["query"],
                "route": result.route,
                "answer": result.answer,
                "auto_checks": auto,
                "human_rubric": {k: None for k in RUBRIC},  # fill tay
                "error": "",
            })
            print(f"  route={result.route} | citation={auto.get('has_citation')} | runaway_ok={auto.get('no_runaway')}")
        except Exception as e:
            rows.append({"case_id": case_id, "query": case["query"], "error": str(e)[:200]})
            print(f"  ERROR: {e}")

        time.sleep(SLEEP_BETWEEN)

    report = {
        "generated_at": datetime.now().isoformat(),
        "target_cases": sorted(TARGET_IDS),
        "results": rows,
        "human_rubric_guide": RUBRIC,
        "note": "human_rubric fields must be filled manually: true/false/null"
    }
    out = REPORT_DIR / f"answer_quality_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nReport saved: {out}")
    print("Điền human_rubric trong file JSON trước khi dùng kết quả.")


if __name__ == "__main__":
    run()
