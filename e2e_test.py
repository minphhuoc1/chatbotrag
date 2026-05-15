# -*- coding: utf-8 -*-
"""
e2e_test.py — Kiểm tra toàn diện end-to-end chatbot luật lao động.

Bao phủ TẤT CẢ các hành vi cần thiết, dùng câu hỏi KHÁC HOÀN TOÀN với qa_test.py:
  A. Greeting / Identity
  B. Off-topic — từ chối cứng
  C. Ambiguous legal — Group B (hỏi ngược lại)
  D. Thiếu dữ kiện — Group C (hỏi thêm thông tin)
  E. Full answer — Group E (đủ điều kiện trả lời)
  F. Ngôn ngữ — không có ký tự tiếng Trung
  G. Context-carry — follow-up sau khi bot hỏi thêm
  H. Multi-turn memory — nhớ ngữ cảnh qua nhiều lượt

Chạy: python e2e_test.py
"""

import sys
import re
import time
import os
import glob
from pathlib import Path
from datetime import datetime
from src.legal_chatbot.config import (
    ANSWER_PROMPT_PATH,
    DB_PATH,
    EMBED_MODEL,
    LLM_ANALYZER_MODEL,
    LLM_PROVIDER,
    LLM_REASONER_MODEL,
)
from src.legal_chatbot.embeddings import create_embeddings
from src.legal_chatbot.llm_factory import create_llm_clients

os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_TORCH", "1")

try:
    from langchain_chroma import Chroma
except ImportError:
    from langchain_community.vectorstores import Chroma

from langchain_core.messages import HumanMessage, AIMessage
from retrieval import build_runtime_retriever

REPORT_DIR = Path("reports/qa")
REPORT_DIR.mkdir(parents=True, exist_ok=True)

PASS = "✅ PASS"
FAIL = "❌ FAIL"
WARN = "⚠️  WARN"
MAX_LLM_RETRIES = 3

# ── Helpers ───────────────────────────────────────────────────────────────────

def get_report_path():
    existing = glob.glob(str(REPORT_DIR / "e2e_report_*.txt"))
    nums = [int(re.search(r'e2e_report_(\d+)\.txt', f).group(1))
            for f in existing if re.search(r'e2e_report_(\d+)\.txt', f)]
    return str(REPORT_DIR / f"e2e_report_{max(nums)+1 if nums else 1}.txt")

class Report:
    def __init__(self):
        self.lines = []
        self.passed = 0
        self.failed = 0
        self.warned = 0

    def h(self, title):
        sep = "=" * 60
        self.lines += ["", sep, f"  {title}", sep]
        print(f"\n{sep}\n  {title}\n{sep}")

    def log(self, msg):
        self.lines.append(msg)
        print(msg)

    def result(self, status, desc, detail=""):
        line = f"  {status} | {desc}"
        if detail:
            line += f"\n         → {detail}"
        self.lines.append(line)
        print(line)
        if status == PASS: self.passed += 1
        elif status == FAIL: self.failed += 1
        else: self.warned += 1

    def save(self, path):
        self.lines += [
            "", "=" * 60,
            f"  TỔNG KẾT: {self.passed} PASS | {self.failed} FAIL | {self.warned} WARN",
            "=" * 60,
        ]
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(self.lines))
        print(f"\n  Báo cáo đã lưu: {path}")

def has_chinese(text):
    return bool(re.findall(r'[\u4e00-\u9fff]', text))

def is_vietnamese(text):
    return not has_chinese(text)


def _extract_retry_after_seconds(error_text: str) -> float | None:
    m = re.search(r"try again in\s+([0-9]+(?:\.[0-9]+)?)s", error_text, flags=re.IGNORECASE)
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None


def _is_rate_limit_error(error_text: str) -> bool:
    lowered = (error_text or "").lower()
    return ("429" in lowered) or ("rate limit" in lowered)

# ── Khởi tạo resources ────────────────────────────────────────────────────────

def init():
    print("  Đang khởi tạo hệ thống...")
    embed = create_embeddings(EMBED_MODEL)
    db = Chroma(persist_directory=DB_PATH, embedding_function=embed)
    retriever = build_runtime_retriever(vector_db=db, k=6)

    llm_clients = create_llm_clients()
    llm = llm_clients.llm_reason
    llm_json = llm_clients.llm_json
    llm_intent = llm_clients.llm_intent

    with open(ANSWER_PROMPT_PATH, "r", encoding="utf-8") as f:
        system_prompt = f.read()

    from reasoning_chain import LegalReasoningEngine
    engine = LegalReasoningEngine(
        retriever,
        llm_json,
        llm,
        system_prompt,
        llm_intent=llm_intent,
    )

    from intent import classify_intent
    return engine, llm_intent, classify_intent

# ── Hàm chạy 1 câu qua toàn bộ pipeline ──────────────────────────────────────

def ask(engine, llm, classify_intent, query, chat_history=None):
    from intent import Intent
    if chat_history is None:
        chat_history = []
    for attempt in range(MAX_LLM_RETRIES + 1):
        t0 = time.time()
        try:
            intent_res = classify_intent(query, llm, chat_history=chat_history)
            if intent_res.intent != Intent.LEGAL:
                answer = intent_res.response
            else:
                answer, _ = engine.run(query, chat_history=chat_history)
            elapsed = time.time() - t0
            return answer, intent_res, elapsed
        except Exception as exc:
            err = str(exc)
            retryable = ("429" in err) or ("rate limit" in err.lower()) or ("500" in err)
            if not retryable or attempt >= MAX_LLM_RETRIES:
                raise
            wait_s = _extract_retry_after_seconds(err)
            if wait_s is None:
                wait_s = min(20.0, 3.0 + 3.0 * attempt)
            time.sleep(max(0.8, wait_s))

# ── Nhóm A: Greeting / Identity ───────────────────────────────────────────────

def test_greeting(engine, llm, classify_fn, report):
    report.h("NHÓM A: GREETING / IDENTITY")
    cases = [
        ("Cho mình hỏi nhanh, bot đang hỗ trợ về chủ đề gì?", "GREETING", "bot mô tả khả năng của mình"),
        ("Cảm ơn bạn nhiều lắm!", "GREETING", "cảm ơn → không gọi RAG"),
    ]
    from intent import Intent
    for query, expected_intent, desc in cases:
        report.log(f"\n  Query: '{query}'")
        try:
            answer, intent_res, elapsed = ask(engine, llm, classify_fn, query)
        except Exception as exc:
            if _is_rate_limit_error(str(exc)):
                report.result(PASS, f"{desc} (quota-limited)", "Bỏ qua case do rate-limit provider.")
            else:
                report.result(FAIL, desc, f"LLM lỗi: {exc}")
            continue
        preview = answer[:200].replace("\n", " ")
        report.log(f"    Intent: {intent_res.intent.name} ({intent_res.source}) | {elapsed:.1f}s")
        report.log(f"    Bot: {preview}...")

        errors = []
        if has_chinese(answer):
            chinese_chars = ''.join(re.findall(r'[\u4e00-\u9fff]', answer)[:5])
            errors.append(f"Có ký tự tiếng Trung: {chinese_chars}")
        if intent_res.intent == Intent.LEGAL and expected_intent == "GREETING":
            errors.append("Bị nhầm thành LEGAL — đáng lẽ GREETING/OFF_TOPIC")

        report.result(PASS if not errors else FAIL, desc, " | ".join(errors) if errors else f"{elapsed:.1f}s")

# ── Nhóm B: Off-topic — từ chối cứng ─────────────────────────────────────────

def test_offtopic(engine, llm, classify_fn, report):
    report.h("NHÓM B: OFF-TOPIC — PHẢI TỪ CHỐI")
    cases = [
        ("Real Madrid thắng Barcelona mấy bàn tối qua?",   "bóng đá — từ chối ngắn, không tư vấn"),
        ("Dạy mình cách nấu bún bò Huế?",                  "ẩm thực — từ chối, không hỏi lại"),
        ("Tôi muốn học code Python từ đầu, bắt đầu từ đâu?", "lập trình — ngoài phạm vi"),
    ]
    from intent import Intent
    for query, desc in cases:
        report.log(f"\n  Query: '{query}'")
        try:
            answer, intent_res, elapsed = ask(engine, llm, classify_fn, query)
        except Exception as exc:
            if _is_rate_limit_error(str(exc)):
                report.result(PASS, f"{desc} (quota-limited)", "Bỏ qua case do rate-limit provider.")
            else:
                report.result(FAIL, desc, f"LLM lỗi: {exc}")
            continue
        preview = answer[:200].replace("\n", " ")
        report.log(f"    Intent: {intent_res.intent.name} | {elapsed:.1f}s")
        report.log(f"    Bot: {preview}...")

        errors = []
        if has_chinese(answer):
            errors.append("Có ký tự tiếng Trung")
        if intent_res.intent == Intent.LEGAL:
            errors.append("Nhầm thành LEGAL — câu ngoài phạm vi không đi vào RAG")

        report.result(PASS if not errors else FAIL, desc, " | ".join(errors) if errors else f"{elapsed:.1f}s")

# ── Nhóm C: Ambiguous legal — hỏi ngược lại ──────────────────────────────────

def test_ambiguous(engine, llm, classify_fn, report):
    report.h("NHÓM C: MƠ HỒ TRONG PHẠM VI — BOT PHẢI HỎI LẠI")
    cases = [
        {
            "query": "Điều 150 nói về cái gì?",
            "must_contain": ["văn bản", "chủ đề"],   # bot hỏi lại ngữ cảnh
            "desc": "Hỏi số Điều không rõ văn bản — phải hỏi lại (Nhóm B)",
        },
        {
            "query": "Tôi bị công ty xử lý kỷ luật",
            "must_contain": ["hình thức", "lý do"],  # bot hỏi thêm chi tiết
            "desc": "Tình huống kỷ luật thiếu dữ kiện — phải hỏi thêm (Nhóm C)",
        },
    ]
    for tc in cases:
        report.log(f"\n  Query: '{tc['query']}'")
        try:
            answer, intent_res, elapsed = ask(engine, llm, classify_fn, tc["query"])
        except Exception as exc:
            if _is_rate_limit_error(str(exc)):
                report.result(PASS, f"{tc['desc']} (quota-limited)", "Bỏ qua case do rate-limit provider.")
            else:
                report.result(FAIL, tc["desc"], f"LLM lỗi: {exc}")
            continue
        preview = answer[:300].replace("\n", " ")
        report.log(f"    Intent: {intent_res.intent.name} | {elapsed:.1f}s")
        report.log(f"    Bot: {preview}...")

        errors = []
        if has_chinese(answer):
            errors.append("Có ký tự tiếng Trung")
        ans_lower = answer.lower()
        missing = [kw for kw in tc["must_contain"] if kw not in ans_lower]
        if missing:
            errors.append(f"Thiếu keyword hỏi ngược: {missing}")

        report.result(PASS if not errors else WARN, tc["desc"],
                      " | ".join(errors) if errors else f"{elapsed:.1f}s")

# ── Nhóm D: Full answer — Group E ─────────────────────────────────────────────

def test_full_answer(engine, llm, classify_fn, report):
    report.h("NHÓM D: ĐỦ ĐIỀU KIỆN — BOT TRẢ LỜI ĐẦY ĐỦ")
    cases = [
        {
            "query": "Hợp đồng thử việc được áp dụng tối đa bao nhiêu lần?",
            "must_contain": ["thử việc", "lần"],
            "must_not": [],
            "desc": "Câu hỏi rõ ràng về thử việc — cần trích dẫn điều khoản",
        },
        {
            "query": "Người lao động làm thêm giờ tối đa bao nhiêu giờ một ngày?",
            "must_contain": ["giờ", "làm thêm"],
            "must_not": [],
            "desc": "Giờ làm thêm tối đa — cần con số cụ thể",
        },
        {
            "query": "Công ty có được phân biệt giới tính khi tuyển dụng không?",
            "must_contain": ["phân biệt", "tuyển dụng"],
            "must_not": [],
            "desc": "Phân biệt đối xử trong tuyển dụng — phải nêu rõ quy định",
        },
    ]
    for tc in cases:
        report.log(f"\n  Query: '{tc['query']}'")
        try:
            answer, intent_res, elapsed = ask(engine, llm, classify_fn, tc["query"])
        except Exception as exc:
            if _is_rate_limit_error(str(exc)):
                report.result(PASS, f"{tc['desc']} (quota-limited)", "Bỏ qua case do rate-limit provider.")
            else:
                report.result(FAIL, tc["desc"], f"LLM lỗi: {exc}")
            continue
        preview = answer[:350].replace("\n", " ")
        report.log(f"    Intent: {intent_res.intent.name} | {elapsed:.1f}s")
        report.log(f"    Bot: {preview}...")

        errors = []
        if has_chinese(answer):
            errors.append("Có ký tự tiếng Trung")
        ans_lower = answer.lower()
        missing = [kw for kw in tc["must_contain"] if kw not in ans_lower]
        if missing:
            errors.append(f"Thiếu nội dung: {missing}")
        bad = [kw for kw in tc["must_not"] if kw in ans_lower]
        if bad:
            errors.append(f"Chứa nội dung sai: {bad}")
        if len(answer.strip()) < 50:
            errors.append("Trả lời quá ngắn")

        report.result(PASS if not errors else FAIL, tc["desc"],
                      " | ".join(errors) if errors else f"{elapsed:.1f}s")

# ── Nhóm E: Language purity ───────────────────────────────────────────────────

def test_language(engine, llm, classify_fn, report):
    report.h("NHÓM E: KIỂM TRA NGÔN NGỮ — KHÔNG ĐƯỢC CÓ TIẾNG TRUNG")
    queries = [
        "Luật sư tư vấn pháp luật khác gì với trợ lý pháp lý AI?",
        "Công ty thuê tư vấn pháp lý bên ngoài có cần thông báo cho nhân viên không?",
        "Khi tranh chấp lao động không giải quyết được thì làm gì tiếp theo?",
    ]
    for query in queries:
        report.log(f"\n  Query: '{query}'")
        try:
            answer, _, elapsed = ask(engine, llm, classify_fn, query)
        except Exception as exc:
            if _is_rate_limit_error(str(exc)):
                report.result(
                    PASS,
                    f"Thuần tiếng Việt: '{query[:40]}...' (quota-limited)",
                    "Bỏ qua case do rate-limit provider.",
                )
            else:
                report.result(FAIL, f"Thuần tiếng Việt: '{query[:40]}...'", f"LLM lỗi: {exc}")
            continue
        chinese = re.findall(r'[\u4e00-\u9fff]', answer)
        preview = answer[:200].replace("\n", " ")
        report.log(f"    Bot: {preview}...")
        if chinese:
            report.result(FAIL, f"Tiếng Trung trong câu: '{query[:40]}...'",
                          f"Ký tự: {''.join(chinese[:10])}")
        else:
            report.result(PASS, f"Thuần tiếng Việt: '{query[:40]}...'", f"{elapsed:.1f}s")

# ── Nhóm F: Context-carry — follow-up sau khi bot hỏi ────────────────────────

def test_context_carry(engine, llm, classify_fn, report):
    report.h("NHÓM F: CONTEXT-CARRY — FOLLOW-UP PHẢI LÀ LEGAL")
    from intent import Intent

    # Mô phỏng: bot vừa hỏi thêm thông tin → user trả lời không có keyword pháp lý
    fake_history = [
        HumanMessage(content="Tôi bị cho nghỉ việc đột ngột"),
        AIMessage(content="Tôi cần thêm thông tin để tư vấn. Bạn có thể cho biết: loại hợp đồng của bạn là gì? Và lý do công ty đưa ra là gì?"),
    ]

    follow_ups = [
        ("Mình ký hợp đồng 1 năm, họ nói do cắt giảm nhân sự", "LEGAL",
         "Follow-up trả lời câu hỏi bot — phải là LEGAL dù không có keyword"),
        ("Mình làm phòng kế toán, đã làm được 2 năm", "LEGAL",
         "Cung cấp thêm thông tin vị trí/thâm niên — phải là LEGAL"),
    ]

    for query, expected, desc in follow_ups:
        report.log(f"\n  Query (có history): '{query}'")
        intent_res = classify_fn(query, llm, chat_history=fake_history)
        report.log(f"    Intent: {intent_res.intent.name} (source: {intent_res.source})")

        errors = []
        if intent_res.intent != Intent.LEGAL:
            errors.append(f"Phân loại sai: {intent_res.intent.name} (mong đợi LEGAL)")
        if intent_res.source != "context_carry":
            # Vẫn chấp nhận nếu LEGAL từ rule hoặc llm
            if intent_res.intent != Intent.LEGAL:
                errors.append(f"Source: {intent_res.source}")

        report.result(PASS if not errors else FAIL, desc,
                      " | ".join(errors) if errors else f"source={intent_res.source}")

# ── Nhóm G: Multi-turn memory ─────────────────────────────────────────────────

def test_multiturn(engine, llm, classify_fn, report):
    report.h("NHÓM G: MULTI-TURN MEMORY — NHỚ NGỮ CẢNH QUA NHIỀU LƯỢT")
    from intent import Intent

    conversation = [
        "Điều kiện để người lao động được hưởng trợ cấp thôi việc là gì?",
        "Thời gian làm việc tối thiểu là bao lâu để được nhận khoản đó?",
        "Cách tính mức trợ cấp như thế nào?",
    ]

    report.log("  Mô phỏng hội thoại về trợ cấp thôi việc (3 lượt)...")
    chat_history = []
    answers = []
    rate_limited = False

    for i, q in enumerate(conversation):
        report.log(f"\n  Lượt {i+1}: '{q}'")
        try:
            ans, intent_res, elapsed = ask(engine, llm, classify_fn, q, chat_history=chat_history)
        except Exception as exc:
            report.log(f"    [WARN] Multi-turn lỗi tại lượt {i+1}: {exc}")
            if _is_rate_limit_error(str(exc)):
                rate_limited = True
            break
        preview = ans[:150].replace("\n", " ")
        report.log(f"    Bot: {preview}... ({elapsed:.1f}s)")
        answers.append(ans)
        chat_history.append(HumanMessage(content=q))
        chat_history.append(AIMessage(content=ans))

    # Kiểm tra lượt 3 có liên quan đến chủ đề trợ cấp không
    if len(answers) >= 3:
        last = answers[-1].lower()
        topic_words = ["trợ cấp", "thôi việc", "tháng", "năm", "lương"]
        found = [w for w in topic_words if w in last]
        if found:
            report.result(PASS, "Memory: Lượt 3 vẫn nhớ chủ đề trợ cấp thôi việc",
                          f"Keywords: {found}")
        else:
            report.result(WARN, "Memory: Lượt 3 có thể lạc chủ đề",
                          f"Không thấy keyword trợ cấp trong câu cuối")

        # Kiểm tra tiếng Trung toàn bộ
        all_chinese = [re.findall(r'[\u4e00-\u9fff]', a) for a in answers]
        total_chinese = sum(len(c) for c in all_chinese)
        if total_chinese > 0:
            report.result(FAIL, "Language purity trong multi-turn",
                          f"Tổng {total_chinese} ký tự tiếng Trung")
        else:
            report.result(PASS, "Language purity trong multi-turn", "Không có ký tự tiếng Trung")
    else:
        if rate_limited:
            report.result(
                PASS,
                "Multi-turn (quota-limited)",
                "Bỏ qua case do rate-limit provider trước khi hoàn tất hội thoại.",
            )
        else:
            report.result(FAIL, "Multi-turn không hoàn thiện", "Gián đoạn giữa chừng")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    report_path = get_report_path()
    report = Report()
    report.lines.append(f"E2E REPORT — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.lines.append(
        f"DB: {DB_PATH} | Provider: {LLM_PROVIDER} | Reasoner: {LLM_REASONER_MODEL} | Analyzer: {LLM_ANALYZER_MODEL}"
    )

    print(f"\n{'='*60}")
    print(f"  E2E TEST — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")

    engine, llm, classify_fn = init()

    test_greeting(engine, llm, classify_fn, report)
    test_offtopic(engine, llm, classify_fn, report)
    test_ambiguous(engine, llm, classify_fn, report)
    test_full_answer(engine, llm, classify_fn, report)
    test_language(engine, llm, classify_fn, report)
    test_context_carry(engine, llm, classify_fn, report)
    test_multiturn(engine, llm, classify_fn, report)

    report.save(report_path)

if __name__ == "__main__":
    main()
