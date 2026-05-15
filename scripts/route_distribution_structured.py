#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Route distribution runner for 30 legal QA cases via engine.run_structured.

Modes:
- default: use real configured LLM chains.
- --mock-llm: keep real retrieval/vector DB, mock analyzer/reasoner/intent
  to isolate routing behavior from provider throttling (429).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.legal_chatbot.config import TEST_CASES_PATH
from test_legal_qa import init_runtime


REPORT_DIR = Path("reports") / "route_distribution"
REPORT_DIR.mkdir(parents=True, exist_ok=True)


class _MockResponse:
    def __init__(self, content: str):
        self.content = content


class _MockIntentLLM:
    def invoke(self, prompt):
        # Let rule-based layer in classify_intent decide first.
        # For uncertain queries, bias to LEGAL to keep routing coverage.
        return _MockResponse("LEGAL")


class _MockChain:
    def __init__(self, fn):
        self._fn = fn

    def invoke(self, payload):
        return self._fn(payload)


LEGAL_KEYWORDS = [
    "hợp đồng",
    "lao động",
    "lương",
    "sa thải",
    "đơn phương",
    "trợ cấp",
    "kỷ luật",
    "thử việc",
    "nghỉ phép",
    "bảo hiểm",
]


def _extract_keywords_for_mock(text: str) -> list[str]:
    text_lower = (text or "").lower()
    keywords = []
    for m in re.findall(r"[đd]iều\s*(\d+)", text_lower):
        keywords.append(f"Điều {m}")
    for kw in LEGAL_KEYWORDS:
        if kw in text_lower:
            keywords.append(kw)
    if not keywords:
        keywords = ["lao động"]
    # de-dup preserve order
    seen = set()
    out = []
    for k in keywords:
        k_norm = k.strip().lower()
        if k_norm in seen:
            continue
        seen.add(k_norm)
        out.append(k.strip())
    return out[:6]


def _attach_mock_llm(runtime):
    engine = runtime.engine

    def _mock_analyzer_invoke(payload):
        raw_input = ""
        if isinstance(payload, dict):
            raw_input = str(payload.get("input", "") or "")
        else:
            raw_input = str(payload or "")
        keywords = _extract_keywords_for_mock(raw_input)
        output = {
            "issue": "legal query",
            "keywords": keywords,
            "law_type": "luật lao động",
        }
        return json.dumps(output, ensure_ascii=False)

    def _mock_reasoner_invoke(payload):
        # Keep concise, grounded tone. Citation contract will post-process if needed.
        _ = payload
        return "Theo ngữ cảnh đã truy xuất, cần đối chiếu điều luật liên quan để kết luận."

    engine.analyzer_chain = _MockChain(_mock_analyzer_invoke)
    engine.reasoner_chain = _MockChain(_mock_reasoner_invoke)
    engine.llm_intent = _MockIntentLLM()


def _format_percent(value: float) -> str:
    return f"{value:.1f}%"


def _print_table(summary: list[dict]):
    print("route            | count | %")
    print("-----------------|-------|------")
    for item in summary:
        route = item["route"]
        print(f"{route:<16} | {item['count']:>5} | {_format_percent(item['pct'])}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mock-llm", action="store_true", help="Mock analyzer/reasoner/intent to avoid provider throttling")
    parser.add_argument("--sleep-ms", type=int, default=120, help="Sleep between cases (real LLM mode)")
    args = parser.parse_args()

    with open(TEST_CASES_PATH, "r", encoding="utf-8") as f:
        cases = yaml.safe_load(f)["cases"]

    runtime = init_runtime()
    if args.mock_llm:
        _attach_mock_llm(runtime)

    counter = Counter()
    rows = []
    total = len(cases)

    for case in cases:
        q = str(case.get("query", "") or "").strip()
        route = "error"
        err = ""
        for attempt in range(1, 5):
            try:
                result = runtime.engine.run_structured(user_input=q, chat_history=[])
                route = (result.route or "unknown").strip() or "unknown"
                err = ""
                break
            except Exception as exc:
                err = str(exc)
                if "429" in err or "rate limit" in err.lower():
                    time.sleep(min(10, 2 * attempt))
                    continue
                time.sleep(0.8)
        counter[route] += 1
        rows.append(
            {
                "id": int(case.get("id", -1)),
                "query": q,
                "route": route,
                "error": err[:200],
            }
        )
        time.sleep(max(0.0, args.sleep_ms / 1000.0))

    summary = []
    for route, count in counter.most_common():
        summary.append(
            {
                "route": route,
                "count": count,
                "pct": (count / total * 100.0) if total else 0.0,
            }
        )

    payload = {
        "generated_at": datetime.now().isoformat(),
        "mode": "mock_llm" if args.mock_llm else "real_llm",
        "total_cases": total,
        "summary": summary,
        "rows": rows,
    }

    out_path = REPORT_DIR / f"route_distribution_{payload['mode']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    _print_table(summary)
    print(f"\nreport: {out_path}")


if __name__ == "__main__":
    main()
