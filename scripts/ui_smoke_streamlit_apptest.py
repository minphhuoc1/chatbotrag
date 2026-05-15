#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
UI smoke test using Streamlit AppTest.

Why this exists:
- Validate real UI flow (chat_input/chat_message + session memory).
- Catch regressions where app bypasses engine contract.
- Provide quick PASS/BLOCKED signal before manual demo.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import List

from streamlit.testing.v1 import AppTest


REPORT_DIR = Path("reports") / "ui_smoke"
LOG_PATH = Path("logs") / "app.log"
ROOT_DIR = Path(__file__).resolve().parents[1]
APP_FILE = ROOT_DIR / "app.py"

# Ensure top-level modules (e.g., retrieval.py, ingest.py) are importable
# when Streamlit runs app.py via testing harness.
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


@dataclass
class TurnSpec:
    query: str
    must_contain_any: List[str] = field(default_factory=list)
    must_not_contain_any: List[str] = field(default_factory=list)


@dataclass
class TurnResult:
    query: str
    answer: str
    elapsed_s: float
    ok: bool
    checks: List[str]


def _last_assistant_answer(at: AppTest) -> str:
    msgs = [m for m in at.chat_message if getattr(m, "name", "") == "assistant"]
    if not msgs:
        return ""
    last = msgs[-1]
    markdowns = getattr(last, "markdown", [])
    if not markdowns:
        return ""
    return "\n".join((md.value or "").strip() for md in markdowns).strip()


def _run_turn(at: AppTest, spec: TurnSpec, timeout: int = 300) -> TurnResult:
    checks: List[str] = []
    t0 = time.perf_counter()
    at.chat_input[0].set_value(spec.query)
    at.run(timeout=timeout)
    elapsed = time.perf_counter() - t0
    answer = _last_assistant_answer(at)

    ok = True
    answer_lower = answer.lower()
    for token in spec.must_contain_any:
        if token.lower() in answer_lower:
            checks.append(f"contains:{token}=OK")
            break
    else:
        if spec.must_contain_any:
            ok = False
            checks.append(f"contains_any={spec.must_contain_any}=MISS")

    for token in spec.must_not_contain_any:
        if token.lower() in answer_lower:
            ok = False
            checks.append(f"not_contains:{token}=VIOLATION")
        else:
            checks.append(f"not_contains:{token}=OK")

    if not checks:
        checks.append("no_assertions")

    return TurnResult(
        query=spec.query,
        answer=answer,
        elapsed_s=round(elapsed, 3),
        ok=ok,
        checks=checks,
    )


def _tail_new_log(start_size: int) -> str:
    if not LOG_PATH.exists():
        return ""
    with LOG_PATH.open("rb") as f:
        f.seek(min(start_size, LOG_PATH.stat().st_size))
        data = f.read()
    return data.decode("utf-8", errors="replace")


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    start_size = LOG_PATH.stat().st_size if LOG_PATH.exists() else 0

    # Cases tập trung vào các điểm đã từng lỗi:
    # - Clarify thay vì over-reject
    # - Memory follow-up query
    # - Intent routing cơ bản
    specs = [
        TurnSpec(
            query="Xin chào",
            must_contain_any=["trợ lý", "luật lao động", "hỗ trợ"],
        ),
        TurnSpec(
            query="Điều 35",
            must_contain_any=["văn bản luật", "chủ đề", "xác nhận"],
        ),
        TurnSpec(
            query="Đơn phương chấm dứt trái luật phải bồi thường gì?",
            must_contain_any=["Điều 40", "Điều 41", "trường hợp nào"],
            must_not_contain_any=["không đủ căn cứ trong tài liệu hiện có"],
        ),
        TurnSpec(
            query="Tôi là người lao động, hợp đồng 24 tháng, công ty đang nợ lương tôi 2 tháng.",
            must_contain_any=["nợ lương", "Điều 35", "không báo trước"],
        ),
        TurnSpec(
            query="Vậy tôi nghỉ ngay không báo trước có được không?",
            must_contain_any=["nợ lương", "Điều 35", "không cần báo trước"],
            must_not_contain_any=["không đủ căn cứ trong tài liệu hiện có"],
        ),
        TurnSpec(
            query="Nếu tôi nghỉ ngay thì công ty còn phải thanh toán cho tôi những khoản nào?",
            must_contain_any=["tiền lương", "thanh toán", "quyền lợi"],
        ),
        TurnSpec(
            query="Trích nguyên văn Điều 113",
            must_contain_any=["Điều 113", "nghỉ hằng năm"],
        ),
        TurnSpec(
            query="Real Madrid tối qua đá sao rồi?",
            must_contain_any=["phạm vi", "luật lao động", "không hỗ trợ"],
        ),
    ]

    at = AppTest.from_file(str(APP_FILE))
    at.run(timeout=360)

    results: List[TurnResult] = []
    for spec in specs:
        result = _run_turn(at, spec, timeout=360)
        results.append(result)

    passed = sum(1 for r in results if r.ok)
    total = len(results)
    status = "PASS" if passed == total else "BLOCKED"

    new_log = _tail_new_log(start_size)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = REPORT_DIR / f"ui_smoke_{stamp}.json"
    log_path = REPORT_DIR / f"ui_smoke_{stamp}.log"

    payload = {
        "status": status,
        "summary": {
            "passed": passed,
            "failed": total - passed,
            "total": total,
        },
        "results": [asdict(r) for r in results],
    }
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    log_path.write_text(new_log, encoding="utf-8")

    print(f"[{status}] UI smoke: {passed}/{total}")
    print(f"report: {report_path}")
    print(f"log_tail: {log_path}")
    for idx, r in enumerate(results, 1):
        print("-" * 80)
        print(f"[{idx}] ok={r.ok} elapsed={r.elapsed_s}s")
        print(f"Q: {r.query}")
        print(f"A: {r.answer[:400]}")
        print(f"checks: {r.checks}")

    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
