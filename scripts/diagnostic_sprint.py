import os
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_TORCH", "1")

import json
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import yaml

# Ensure repo root is importable when running from scripts/
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from retrieval import retrieve_exact_article
from src.legal_chatbot import policy as shared_policy
from src.legal_chatbot.config import TEST_CASES_PATH, TOP_K
from src.legal_chatbot.evaluation import (
    ROOT_CAUSE_LABELS,
    evaluate_case_with_rubric,
    summarize_rubric,
)
from test_legal_qa import evaluate_case, init_runtime


REPORT_DIR = Path("reports/diagnostics")
REPORT_DIR.mkdir(parents=True, exist_ok=True)

PROBE_CASES = [
    {
        "id": 1001,
        "query": (
            "Tôi mới tốt nghiệp cấp 2, đi làm quán nhậu từ 10h sáng đến 10h đêm, "
            "có khi 11h đêm mới về. Không có hợp đồng, chỉ thỏa thuận miệng. "
            "Tôi làm 20 ngày xin ứng lương thì chỉ được 400k. Nếu nghỉ ngang tôi có đòi đủ lương được không?"
        ),
        "expected_mode": "grounded_legal_answer",
        "must_reference_any_of": [14, 35, 48, 90, 146],
        "must_not_hallucinate": True,
        "source": "probe",
    },
    {
        "id": 1002,
        "query": "Em 15 tuổi làm ca đêm ở quán karaoke từ 18h đến 1h sáng có hợp pháp không?",
        "expected_mode": "grounded_legal_answer",
        "must_reference_any_of": [146, 147],
        "must_not_hallucinate": True,
        "source": "probe",
    },
    {
        "id": 1003,
        "query": "Công ty chậm lương 2 tháng, tôi nghỉ ngay không báo trước có được không?",
        "expected_mode": "grounded_legal_answer",
        "must_reference_any_of": [35, 97],
        "must_not_hallucinate": True,
        "source": "probe",
    },
    {
        "id": 1004,
        "query": "Tôi làm 20 ngày rồi nghỉ, chủ phải thanh toán lương trong bao lâu?",
        "expected_mode": "grounded_legal_answer",
        "must_reference_any_of": [48, 95],
        "must_not_hallucinate": True,
        "source": "probe",
    },
    {
        "id": 1005,
        "query": "Thỏa thuận miệng có được coi là hợp đồng lao động không?",
        "expected_mode": "grounded_legal_answer",
        "must_reference_any_of": [14],
        "must_not_hallucinate": True,
        "source": "probe",
    },
    {
        "id": 1006,
        "query": "Điều 999 có cho phép sa thải không cần lý do không?",
        "expected_mode": "fallback_refusal",
        "must_reference_any_of": [],
        "must_not_hallucinate": True,
        "source": "probe",
    },
]


@dataclass
class OracleResult:
    ran: bool
    context_ready: bool
    pass_case: bool
    missing_refs: List[int]
    cited_articles: List[int]
    invalid_citations: List[int]
    validation_ok: bool
    answer_preview: str


def _doc_key(doc) -> tuple:
    meta = doc.metadata or {}
    return (
        meta.get("article_number", meta.get("dieu_so")),
        meta.get("chunk_id"),
        (doc.page_content or "")[:120],
    )


def _dedup_docs(docs: List[Any]) -> List[Any]:
    out = []
    seen = set()
    for d in docs:
        key = _doc_key(d)
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    return out


def _extract_retry_after_seconds(message: str) -> float | None:
    match = re.search(r"try again in\s+([0-9]+(?:\.[0-9]+)?)s", message, flags=re.IGNORECASE)
    if not match:
        return None
    try:
        return float(match.group(1))
    except Exception:
        return None


def _invoke_reasoner_with_backoff(runtime, query: str, context_text: str, max_attempts: int = 4) -> str:
    attempt = 0
    current_context = context_text or ""
    while attempt < max_attempts:
        attempt += 1
        try:
            return runtime.engine.reasoner_chain.invoke(
                {"context": current_context, "chat_history": [], "input": query}
            )
        except Exception as exc:
            msg = str(exc)
            is_rate_limit = ("429" in msg) or ("rate limit" in msg.lower())
            if not is_rate_limit or attempt >= max_attempts:
                raise
            retry_after = _extract_retry_after_seconds(msg)
            wait_seconds = retry_after if retry_after is not None else min(20.0, 3.0 * attempt)
            time.sleep(max(0.8, wait_seconds))
            if len(current_context) > 1200:
                current_context = current_context[: max(1200, int(len(current_context) * 0.75))]
    raise RuntimeError("reasoner invocation failed after retries")


def run_oracle_probe(runtime, case: Dict) -> OracleResult:
    expected_refs = [int(x) for x in case.get("must_reference_any_of", []) if str(x).isdigit()]
    if not expected_refs:
        return OracleResult(
            ran=False,
            context_ready=False,
            pass_case=True,
            missing_refs=[],
            cited_articles=[],
            invalid_citations=[],
            validation_ok=True,
            answer_preview="",
        )

    query = case["query"]
    query_mode = shared_policy.classify_query_mode(query)

    docs = []
    missing_refs = []
    for ref in expected_refs:
        extra = retrieve_exact_article(article_number=ref, vector_db=runtime.vector_db, limit=12)
        extra = shared_policy._filter_docs_for_exact_article(extra, ref)
        if not extra:
            missing_refs.append(ref)
            continue
        docs.extend(extra)

    docs = _dedup_docs(docs)
    context_ready = len(docs) > 0 and len(missing_refs) < len(expected_refs)
    if not context_ready:
        return OracleResult(
            ran=True,
            context_ready=False,
            pass_case=False,
            missing_refs=missing_refs,
            cited_articles=[],
            invalid_citations=[],
            validation_ok=False,
            answer_preview="",
        )

    context_text = "\n\n".join(d.page_content for d in docs)
    draft_answer = _invoke_reasoner_with_backoff(
        runtime=runtime,
        query=query,
        context_text=context_text,
        max_attempts=4,
    )
    draft_answer = runtime.engine._remove_chinese_characters(draft_answer)
    final_answer = shared_policy.enforce_citation_contract(
        answer=draft_answer,
        user_input=query,
        documents=docs,
        query_mode=query_mode,
    )
    validation = shared_policy.validate_answer_against_context(
        answer=final_answer,
        user_input=query,
        documents=docs,
        query_mode=query_mode,
    )

    cited = shared_policy.extract_article_references(final_answer)
    available = set(shared_policy.extract_articles_from_documents(docs))
    invalid_citations = [a for a in cited if a not in available]
    must_ref_ok = bool(set(expected_refs).intersection(set(cited)))
    pass_case = bool(validation.get("ok", False)) and must_ref_ok and len(invalid_citations) == 0

    return OracleResult(
        ran=True,
        context_ready=True,
        pass_case=pass_case,
        missing_refs=missing_refs,
        cited_articles=cited,
        invalid_citations=invalid_citations,
        validation_ok=bool(validation.get("ok", False)),
        answer_preview=(final_answer or "")[:240],
    )


def classify_root_cause(case: Dict, result: Dict, oracle: OracleResult, evaluation: Dict) -> str:
    if all(result.get("checks", {}).values()):
        return "none"

    # Oracle says "expected legal refs are not even available in retrieved corpus path"
    # => treat as retrieval class (includes coverage/data quality gaps).
    expected_refs = [int(x) for x in case.get("must_reference_any_of", []) if str(x).isdigit()]
    if expected_refs and oracle.ran and not oracle.context_ready:
        return "retrieval"

    primary = str(evaluation.get("root_cause", {}).get("primary", "model")).strip().lower()
    if primary in ROOT_CAUSE_LABELS:
        return primary
    return "model"


def summarize_findings(records: List[Dict]) -> Dict:
    total = len(records)
    failed = [r for r in records if not r["full_pass"]]
    full_pass = total - len(failed)

    suite_cases = [r for r in records if r["case"].get("source", "suite") == "suite"]
    probe_cases = [r for r in records if r["case"].get("source") == "probe"]
    suite_failed = [r for r in suite_cases if not r["full_pass"]]
    probe_failed = [r for r in probe_cases if not r["full_pass"]]

    cause_counter = Counter(r["root_cause"] for r in failed if r["root_cause"] != "none")
    fallback_counter = Counter(
        r["result"].get("guard_fallback_layer", {}).get("fallback_reason", "")
        for r in records
        if r["result"].get("guard_fallback_layer", {}).get("fallback_triggered", False)
    )
    rubric_summary = summarize_rubric([r["evaluation"] for r in records])

    grounded_cases = [
        r for r in records
        if r["case"]["expected_mode"] == "grounded_legal_answer"
    ]
    oracle_ran = [r for r in grounded_cases if r["oracle"].get("ran", False)]
    oracle_context_ready = [r for r in oracle_ran if r["oracle"].get("context_ready", False)]
    oracle_pass = [r for r in oracle_context_ready if r["oracle"].get("pass_case", False)]

    return {
        "total_cases": total,
        "full_pass_cases": full_pass,
        "failed_cases": len(failed),
        "suite_cases": len(suite_cases),
        "suite_failed_cases": len(suite_failed),
        "probe_cases": len(probe_cases),
        "probe_failed_cases": len(probe_failed),
        "failure_causes": dict(cause_counter),
        "fallback_reason_distribution": dict(fallback_counter),
        "rubric": rubric_summary,
        "oracle": {
            "ran_cases": len(oracle_ran),
            "context_ready_cases": len(oracle_context_ready),
            "pass_cases": len(oracle_pass),
            "pass_rate_on_ready_context": (
                round(len(oracle_pass) / len(oracle_context_ready), 4)
                if oracle_context_ready
                else None
            ),
        },
    }


def build_recommendations(summary: Dict) -> List[str]:
    recs = []
    causes = summary.get("failure_causes", {})

    if causes.get("retrieval", 0) > 0:
        recs.append(
            "Retrieval: nâng query-rewrite theo semantic intent + rerank, "
            "và thêm retrieval regression cho các cụm pháp lý dài/ngôn ngữ đời thường."
        )
    if causes.get("prompt", 0) > 0:
        recs.append(
            "Prompt: siết answer contract theo mode (article_lookup/quote_request/fact_pattern), "
            "bắt buộc viện dẫn Điều/Khoản khi context đủ mạnh, và thêm few-shot phản ví dụ."
        )
    if causes.get("policy", 0) > 0:
        recs.append(
            "Policy: gom toàn bộ guard thành một state-machine thống nhất "
            "(intent -> retrieval quality -> answerability -> response mode), tránh rule chồng chéo."
        )
    if causes.get("model", 0) > 0:
        recs.append(
            "Model: thêm verifier bước 2 (claim-evidence check) hoặc nâng model cho reasoning pháp lý; "
            "giảm phụ thuộc vào một lần sinh duy nhất."
        )

    if not recs:
        recs.append(
            "Bộ test chuẩn hiện tại đang xanh; nên thêm stress tests ngoài distribution "
            "(case dài, đa sự kiện, lao động chưa thành niên, tranh chấp lương) để đo độ bền logic."
        )
    return recs


def load_cases() -> List[Dict]:
    with open(TEST_CASES_PATH, "r", encoding="utf-8") as f:
        cases = yaml.safe_load(f)["cases"]
    for case in cases:
        case.setdefault("source", "suite")
    return cases + PROBE_CASES


def run() -> Dict:
    runtime = init_runtime()
    cases = load_cases()
    records = []

    for case in cases:
        result = evaluate_case(runtime, case)
        evaluation = evaluate_case_with_rubric(case, result)
        result["evaluation"] = evaluation
        oracle = run_oracle_probe(runtime, case)
        full_pass = all(result.get("checks", {}).values())
        root_cause = classify_root_cause(case, result, oracle, evaluation)
        records.append(
            {
                "case": case,
                "result": result,
                "evaluation": evaluation,
                "oracle": {
                    "ran": oracle.ran,
                    "context_ready": oracle.context_ready,
                    "pass_case": oracle.pass_case,
                    "missing_refs": oracle.missing_refs,
                    "cited_articles": oracle.cited_articles,
                    "invalid_citations": oracle.invalid_citations,
                    "validation_ok": oracle.validation_ok,
                    "answer_preview": oracle.answer_preview,
                },
                "full_pass": full_pass,
                "root_cause": root_cause,
            }
        )

    summary = summarize_findings(records)
    recommendations = build_recommendations(summary)
    payload = {
        "generated_at": datetime.now().isoformat(),
        "summary": summary,
        "recommendations": recommendations,
        "records": records,
    }
    return payload


def save_report(payload: Dict) -> Dict[str, str]:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = REPORT_DIR / f"diagnostic_sprint_{stamp}.json"
    md_path = REPORT_DIR / f"diagnostic_sprint_{stamp}.md"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    summary = payload["summary"]
    recs = payload["recommendations"]
    failed_records = [r for r in payload["records"] if not r["full_pass"]]

    lines = []
    lines.append("# Diagnostic Sprint Report")
    lines.append("")
    lines.append(f"- Generated at: `{payload['generated_at']}`")
    lines.append(f"- Total cases: `{summary['total_cases']}`")
    lines.append(f"- Full pass: `{summary['full_pass_cases']}`")
    lines.append(f"- Failed: `{summary['failed_cases']}`")
    lines.append("")
    lines.append("## Failure Causes")
    if summary["failure_causes"]:
        for k, v in summary["failure_causes"].items():
            lines.append(f"- `{k}`: {v}")
    else:
        lines.append("- None")
    lines.append("")
    lines.append("## Rubric")
    rubric = summary.get("rubric", {})
    lines.append(f"- Rubric version: `{rubric.get('rubric_version')}`")
    lines.append(f"- Average weighted score: `{rubric.get('average_weighted_score')}`")
    lines.append(f"- Low-score cases (<70): `{rubric.get('low_score_cases')}`")
    lines.append(f"- Dimension averages: `{rubric.get('dimension_averages')}`")
    lines.append(f"- Grade distribution: `{rubric.get('grade_distribution')}`")
    lines.append(f"- Root-cause distribution: `{rubric.get('root_cause_distribution')}`")
    lines.append("")
    lines.append("## Oracle Ablation")
    oracle = summary["oracle"]
    lines.append(f"- Ran cases: `{oracle['ran_cases']}`")
    lines.append(f"- Context-ready cases: `{oracle['context_ready_cases']}`")
    lines.append(f"- Pass cases: `{oracle['pass_cases']}`")
    lines.append(f"- Pass rate on ready context: `{oracle['pass_rate_on_ready_context']}`")
    lines.append("")
    lines.append("## Recommendations")
    for rec in recs:
        lines.append(f"- {rec}")
    lines.append("")
    lines.append("## Failed Cases Detail")
    if not failed_records:
        lines.append("- None")
    else:
        for rec in failed_records:
            case = rec["case"]
            checks = rec["result"]["checks"]
            lines.append(f"- Case `{case['id']}`: {case['query']}")
            lines.append(f"  Root cause: `{rec['root_cause']}`")
            lines.append(f"  Rubric score: `{rec['evaluation'].get('weighted_score')}` | grade=`{rec['evaluation'].get('grade')}`")
            lines.append(f"  Root cause evidence: `{rec['evaluation'].get('root_cause', {}).get('evidence', [])}`")
            lines.append(f"  Checks: `{checks}`")
            lines.append(f"  Oracle: `{rec['oracle']}`")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return {"json": str(json_path), "md": str(md_path)}


def main():
    payload = run()
    paths = save_report(payload)
    print(f"Diagnostic JSON: {paths['json']}")
    print(f"Diagnostic MD: {paths['md']}")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
