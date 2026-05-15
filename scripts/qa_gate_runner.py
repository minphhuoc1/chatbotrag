import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT / "reports"
QA_DIR = REPORTS_DIR / "qa"
LEGAL_QA_DIR = REPORTS_DIR / "legal_qa"
DIAG_DIR = REPORTS_DIR / "diagnostics"
QA_DB_DIR = Path(
    os.getenv(
        "LEGAL_CHATBOT_QA_DB_PATH",
        str((Path(os.getenv("TEMP", str(ROOT / "tmp"))).resolve() / "chatbotrag_vector_db_qa")),
    )
)


def _cleanup_qa_db(db_dir: Path):
    """
    Dọn DB QA trước khi ingest để giữ đúng path cố định.
    Chỉ dọn trong temp-dir và prefix chatbotrag_vector_db_qa để an toàn.
    """
    db_dir = db_dir.resolve()
    temp_root = Path(os.getenv("TEMP", str(ROOT / "tmp"))).resolve()
    name_ok = db_dir.name.startswith("chatbotrag_vector_db_qa")
    within_temp = str(db_dir).lower().startswith(str(temp_root).lower())
    if not (name_ok and within_temp):
        return

    candidates = [
        db_dir,
        Path(str(db_dir) + "_parent_store"),
        Path(str(db_dir) + "_parent_index.json"),
    ]
    for path in candidates:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.exists():
            try:
                path.unlink()
            except Exception:
                pass


def newest_file(pattern: str, folder: Path, since: float) -> Path:
    matches = [p for p in folder.glob(pattern) if p.is_file() and p.stat().st_mtime >= since - 1]
    if not matches:
        return None
    return sorted(matches, key=lambda p: p.stat().st_mtime)[-1]


def run_step(name: str, cmd: list[str], env_overrides: dict | None = None):
    print(f"\n=== {name} ===")
    print("CMD:", " ".join(cmd))
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    rc = subprocess.run(cmd, cwd=str(ROOT), env=env).returncode
    if rc != 0:
        raise RuntimeError(f"{name} failed with exit code {rc}")


def run_step_capture(name: str, cmd: list[str], env_overrides: dict | None = None):
    print(f"\n=== {name} ===")
    print("CMD:", " ".join(cmd))
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        errors="ignore",
    )
    if proc.stdout:
        print(proc.stdout, end="" if proc.stdout.endswith("\n") else "\n")
    if proc.stderr:
        print(proc.stderr, end="" if proc.stderr.endswith("\n") else "\n")
    return proc.returncode, f"{proc.stdout}\n{proc.stderr}"


def is_quota_limited_text(text: str) -> bool:
    lowered = (text or "").lower()
    return (
        "rate_limit_exceeded" in lowered
        or "tokens per minute" in lowered
        or "tokens per day" in lowered
        or "429" in lowered
    )


def cooldown(seconds: int, reason: str):
    if seconds <= 0:
        return
    print(f"\n--- Cooldown {seconds}s ({reason}) ---")
    time.sleep(seconds)


def parse_txt_summary(path: Path) -> tuple[int, int, int]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"TỔNG KẾT:\s*(\d+)\s*PASS\s*\|\s*(\d+)\s*FAIL\s*\|\s*(\d+)\s*WARN", text)
    if not m:
        raise ValueError(f"Cannot parse summary from {path}")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def parse_legal_qa_summary(path: Path) -> tuple[int, int]:
    data = json.loads(path.read_text(encoding="utf-8"))
    summary = data.get("summary", {})
    return int(summary.get("passed_cases", 0)), int(summary.get("failed_cases", 0))


def parse_diagnostic_summary(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("summary", {})


def main():
    start = time.time()
    allowed_diag_fails = int(os.getenv("QA_GATE_ALLOWED_DIAG_FAILS", "1"))
    allow_quota_skip = os.getenv("QA_GATE_ALLOW_QUOTA_SKIP", "1").strip().lower() in {"1", "true", "yes", "on"}
    env = {
        "PYTHONIOENCODING": "utf-8",
        "QA_NONINTERACTIVE": "1",
        "HF_LOCAL_FILES_ONLY": "1",
        "HF_HUB_OFFLINE": "1",
        "LANGSMITH_TRACING": "false",
        "LEGAL_CHATBOT_EMBED_DEVICE": os.getenv("LEGAL_CHATBOT_EMBED_DEVICE", "cuda"),
        "LEGAL_CHATBOT_RETRIEVAL_ENABLE_STRATEGY_ROUTER": "1",
        "LEGAL_CHATBOT_RETRIEVAL_ENABLE_LEXICAL": "1",
        "LEGAL_CHATBOT_RETRIEVAL_ENABLE_DETERMINISTIC_ARTICLE_BRANCH": "1",
        "LEGAL_CHATBOT_RETRIEVAL_ENABLE_RERANKER": "1",
        "LEGAL_CHATBOT_RETRIEVAL_ENABLE_METADATA_BOOST": "1",
        "LEGAL_CHATBOT_TOP_K": os.getenv("LEGAL_CHATBOT_TOP_K", "4"),
        "LEGAL_CHATBOT_REASONER_MAX_CONTEXT_DOCS": os.getenv("LEGAL_CHATBOT_REASONER_MAX_CONTEXT_DOCS", "5"),
        "LEGAL_CHATBOT_REASONER_MAX_CONTEXT_CHARS": os.getenv("LEGAL_CHATBOT_REASONER_MAX_CONTEXT_CHARS", "5000"),
        "LEGAL_CHATBOT_DB_PATH": str(QA_DB_DIR),
        "LEGAL_CHATBOT_REASONER_MAX_TOKENS": os.getenv("LEGAL_CHATBOT_REASONER_MAX_TOKENS", "640"),
        "LEGAL_CHATBOT_ANALYZER_MAX_TOKENS": os.getenv("LEGAL_CHATBOT_ANALYZER_MAX_TOKENS", "192"),
        "LEGAL_CHATBOT_INTENT_MAX_TOKENS": os.getenv("LEGAL_CHATBOT_INTENT_MAX_TOKENS", "96"),
        # Stable QA tier to avoid 429 on long suites.
        "LEGAL_CHATBOT_REASONER_MODEL": "llama-3.1-8b-instant",
        "LEGAL_CHATBOT_ANALYZER_MODEL": "llama-3.1-8b-instant",
        "LEGAL_CHATBOT_INTENT_MODEL": "llama-3.1-8b-instant",
        "LEGAL_CHATBOT_REASONER_FALLBACK_MODEL": "llama-3.1-8b-instant",
        "LEGAL_CHATBOT_ANALYZER_FALLBACK_MODEL": "llama-3.1-8b-instant",
        "LEGAL_CHATBOT_INTENT_FALLBACK_MODEL": "llama-3.1-8b-instant",
    }

    _cleanup_qa_db(QA_DB_DIR)

    run_step("Ingest QA DB", [sys.executable, "ingest.py"], env)
    diag_skipped_quota = False
    diag_rc, diag_output = run_step_capture("Diagnostic Sprint", [sys.executable, "scripts/diagnostic_sprint.py"], env)
    if diag_rc != 0:
        if allow_quota_skip and is_quota_limited_text(diag_output):
            diag_skipped_quota = True
            diag_file = None
            diag = {}
            print("\n[WARN] Diagnostic Sprint skipped due provider quota/rate-limit.")
        else:
            raise RuntimeError(f"Diagnostic Sprint failed with exit code {diag_rc}")
    else:
        cooldown(12, "wait token bucket after Diagnostic")
        diag_file = newest_file("diagnostic_sprint_*.json", DIAG_DIR, start)
        if not diag_file:
            raise RuntimeError("Diagnostic report not found")
        diag = parse_diagnostic_summary(diag_file)

    qa_skipped_quota = False
    qa_rc, qa_output = run_step_capture("QA Test", [sys.executable, "qa_test.py"], env)
    if qa_rc != 0:
        if allow_quota_skip and is_quota_limited_text(qa_output):
            qa_skipped_quota = True
            qa_file = None
            qa_pass, qa_fail, qa_warn = 0, 0, 0
            print("\n[WARN] QA Test skipped due provider quota/rate-limit.")
        else:
            raise RuntimeError(f"QA Test failed with exit code {qa_rc}")
    else:
        cooldown(10, "wait token bucket after QA Test")
        qa_file = newest_file("qa_report_*.txt", QA_DIR, start)
        if not qa_file:
            raise RuntimeError("QA report not found")
        qa_pass, qa_fail, qa_warn = parse_txt_summary(qa_file)

    e2e_skipped_quota = False
    e2e_rc, e2e_output = run_step_capture("E2E Test", [sys.executable, "e2e_test.py"], env)
    if e2e_rc != 0:
        if allow_quota_skip and is_quota_limited_text(e2e_output):
            e2e_skipped_quota = True
            e2e_file = None
            e2e_pass, e2e_fail, e2e_warn = 0, 0, 0
            print("\n[WARN] E2E Test skipped due provider quota/rate-limit.")
        else:
            raise RuntimeError(f"E2E Test failed with exit code {e2e_rc}")
    else:
        cooldown(10, "wait token bucket after E2E Test")
        e2e_file = newest_file("e2e_report_*.txt", QA_DIR, start)
        if not e2e_file:
            raise RuntimeError("E2E report not found")
        e2e_pass, e2e_fail, e2e_warn = parse_txt_summary(e2e_file)

    legal_skipped_quota = False
    legal_rc, legal_output = run_step_capture("Legal QA Test", [sys.executable, "test_legal_qa.py"], env)
    if legal_rc != 0:
        quota_hit = is_quota_limited_text(legal_output)
        if allow_quota_skip and quota_hit:
            legal_skipped_quota = True
            print("\n[WARN] Legal QA skipped due provider quota/rate-limit.")
            legal_file = None
            legal_pass, legal_fail = 0, 0
        else:
            raise RuntimeError(f"Legal QA Test failed with exit code {legal_rc}")
    else:
        legal_file = newest_file("legal_qa_report_*.json", LEGAL_QA_DIR, start)
        if not legal_file:
            raise RuntimeError("Legal QA report not found")
        legal_pass, legal_fail = parse_legal_qa_summary(legal_file)

    failures = []
    if not diag_skipped_quota:
        diag_failed = int(diag.get("failed_cases", 0))
        if diag_failed > allowed_diag_fails:
            failures.append(
                f"diagnostic failed_cases={diag_failed} (allowed={allowed_diag_fails})"
            )
        if int(diag.get("probe_failed_cases", 1)) != 0:
            failures.append(f"diagnostic probe_failed_cases={diag.get('probe_failed_cases')}")
    if not qa_skipped_quota and (qa_fail != 0 or qa_warn != 0):
        failures.append(f"qa_test fail={qa_fail}, warn={qa_warn}")
    if not e2e_skipped_quota and (e2e_fail != 0 or e2e_warn != 0):
        failures.append(f"e2e_test fail={e2e_fail}, warn={e2e_warn}")
    if not legal_skipped_quota and legal_fail != 0:
        failures.append(f"test_legal_qa failed_cases={legal_fail}")

    print("\n=== QA Gate Summary ===")
    if diag_skipped_quota:
        print("Diagnostic : skipped (provider quota/rate-limit)")
    else:
        print(f"Diagnostic : {diag_file}")
    if qa_skipped_quota:
        print("QA report  : skipped (provider quota/rate-limit)")
    else:
        print(f"QA report  : {qa_file} | PASS={qa_pass} FAIL={qa_fail} WARN={qa_warn}")
    if e2e_skipped_quota:
        print("E2E report : skipped (provider quota/rate-limit)")
    else:
        print(f"E2E report : {e2e_file} | PASS={e2e_pass} FAIL={e2e_fail} WARN={e2e_warn}")
    if legal_skipped_quota:
        print("Legal QA   : skipped (provider quota/rate-limit)")
    else:
        print(f"Legal QA   : {legal_file} | PASS={legal_pass} FAIL={legal_fail}")

    if failures:
        print("\nQA gate blocked:")
        for item in failures:
            print("-", item)
        sys.exit(1)

    print("\nQA gate passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()
