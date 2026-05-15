import json
import math
import os
import re
import inspect
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Load optional vendor site-packages as early as possible so downstream imports
# (ragas/trulens dependencies) resolve against the intended workspace packages.
_EARLY_VENDOR_PATH = os.getenv("THIRD_PARTY_VENDOR_PATH", "").strip()
if _EARLY_VENDOR_PATH:
    _vendor_path_obj = Path(_EARLY_VENDOR_PATH)
    if _vendor_path_obj.exists():
        _vendor_str = str(_vendor_path_obj)
        if _vendor_str not in sys.path:
            sys.path.insert(0, _vendor_str)

from retrieval import retrieve_documents, retrieve_exact_article
from src.legal_chatbot import policy as shared_policy
from src.legal_chatbot.config import TEST_CASES_PATH, TOP_K
from src.legal_chatbot.evaluation import evaluate_case_with_rubric, summarize_rubric
from src.legal_chatbot.observability import describe_observability_state
from test_legal_qa import evaluate_case, init_runtime


REPORT_DIR = ROOT / "reports" / "third_party"
REPORT_DIR.mkdir(parents=True, exist_ok=True)


def _to_float_or_none(value: Any) -> float | None:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        numeric = float(value)
        if math.isfinite(numeric):
            return numeric
    return None


def _sanitize_for_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _sanitize_for_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_for_json(v) for v in value]
    if isinstance(value, tuple):
        return [_sanitize_for_json(v) for v in value]
    if isinstance(value, (int, float)):
        numeric = float(value)
        if math.isfinite(numeric):
            return value
        return None
    return value


def _extract_retry_after_seconds(message: str) -> float | None:
    match = re.search(r"try again in\s+([0-9]+(?:\.[0-9]+)?)s", message, flags=re.IGNORECASE)
    if not match:
        return None
    try:
        return float(match.group(1))
    except Exception:
        return None


def _enable_vendor_path_from_env() -> str:
    """
    Nạp thêm site-packages nằm trong workspace (D:) cho phần third-party metrics/sync.
    Tránh set PYTHONPATH toàn cục ngay từ đầu để không phá runtime chính.
    """
    vendor = os.getenv("THIRD_PARTY_VENDOR_PATH", "").strip()
    if not vendor:
        return ""
    vendor_path = Path(vendor)
    if not vendor_path.exists():
        return ""
    vendor_str = str(vendor_path)
    if vendor_str not in sys.path:
        sys.path.insert(0, vendor_str)
    return vendor_str


def _parse_case_ids(raw: str) -> set[int]:
    raw = (raw or "").strip()
    if not raw:
        return set()
    ids: set[int] = set()
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        if "-" in token:
            left, right = token.split("-", 1)
            if left.strip().isdigit() and right.strip().isdigit():
                start, end = int(left.strip()), int(right.strip())
                if start <= end:
                    ids.update(range(start, end + 1))
            continue
        if token.isdigit():
            ids.add(int(token))
    return ids


def _load_cases(case_ids: set[int], limit: int) -> list[dict]:
    with open(TEST_CASES_PATH, "r", encoding="utf-8") as f:
        cases = yaml.safe_load(f)["cases"]
    if case_ids:
        cases = [c for c in cases if int(c.get("id", -1)) in case_ids]
    if limit > 0:
        cases = cases[:limit]
    return cases


def _collect_contexts(runtime, query: str) -> list[str]:
    docs = retrieve_documents(user_input=query, retriever=runtime.retriever, k=TOP_K)
    for target in shared_policy.suggest_target_articles(query):
        if target in shared_policy.extract_articles_from_documents(docs):
            continue
        extra = retrieve_exact_article(article_number=target, vector_db=runtime.vector_db, limit=8)
        extra = shared_policy._filter_docs_for_exact_article(extra, target)
        if extra:
            docs = shared_policy._sort_article_docs(extra + docs)
    contexts = []
    for d in docs:
        text = (d.page_content or "").strip()
        if text:
            contexts.append(text)
    return contexts[:TOP_K]


def _build_reference_text(runtime, expected_refs: list[int]) -> str:
    if not expected_refs:
        return ""
    parts: list[str] = []
    for article in expected_refs[:4]:
        exact = retrieve_exact_article(article_number=article, vector_db=runtime.vector_db, limit=12)
        exact = shared_policy._filter_docs_for_exact_article(exact, article)
        article_text = shared_policy._assemble_article_text(exact).strip()
        if article_text:
            parts.append(article_text)
    return "\n\n".join(parts).strip()


def _extract_final_answer(case_result: dict) -> str:
    answer_layer = case_result.get("answer_grounding_layer", {}) or {}
    return str(answer_layer.get("final_answer", "") or "").strip()


def run_predictions(cases: list[dict], runtime) -> tuple[list[dict], dict]:
    records: list[dict] = []
    evaluations = []

    for case in cases:
        case_id = int(case["id"])
        query = case["query"]
        print(f"[RUN] Case #{case_id:02d} :: {query}")
        result = evaluate_case(runtime, case)
        evaluation = evaluate_case_with_rubric(case, result)
        result["evaluation"] = evaluation
        evaluations.append(evaluation)

        final_answer = _extract_final_answer(result)
        contexts = _collect_contexts(runtime, query)
        reference = _build_reference_text(runtime, [int(x) for x in case.get("must_reference_any_of", []) if str(x).isdigit()])

        records.append(
            {
                "case_id": case_id,
                "query": query,
                "expected_mode": case.get("expected_mode", ""),
                "expected_refs": case.get("must_reference_any_of", []),
                "answer": final_answer,
                "contexts": contexts,
                "reference": reference,
                "checks": result.get("checks", {}),
                "fallback": result.get("guard_fallback_layer", {}),
                "evaluation": evaluation,
            }
        )

    summary = {
        "total_cases": len(records),
        "passed_cases": sum(1 for r in records if all(bool(v) for v in r.get("checks", {}).values())),
        "failed_cases": sum(1 for r in records if not all(bool(v) for v in r.get("checks", {}).values())),
        "rubric": summarize_rubric(evaluations),
    }
    return records, summary


def _score_from_trulens_output(raw):
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, dict):
        for key in ("score", "result", "value"):
            if key in raw and isinstance(raw[key], (int, float)):
                return float(raw[key])
    if isinstance(raw, tuple):
        for item in raw:
            if isinstance(item, (int, float)):
                return float(item)
            if isinstance(item, dict):
                parsed = _score_from_trulens_output(item)
                if parsed is not None:
                    return parsed
    return None


def _call_with_fallbacks(func, attempts: list):
    last_exc = None
    for attempt in attempts:
        try:
            if isinstance(attempt, dict):
                return func(**attempt)
            if isinstance(attempt, tuple):
                return func(*attempt)
            return func(attempt)
        except Exception as exc:
            last_exc = exc
            continue
    if last_exc is not None:
        raise last_exc
    return None


def _looks_like_blocked_local_proxy(value: str) -> bool:
    normalized = (value or "").strip().lower()
    if not normalized:
        return False
    return (
        "127.0.0.1:9" in normalized
        or "localhost:9" in normalized
        or "0.0.0.0:9" in normalized
    )


def _sanitize_proxy_env_for_groq() -> None:
    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        if _looks_like_blocked_local_proxy(os.getenv(key, "")):
            os.environ.pop(key, None)


def _unwrap_langchain_llm(llm_obj):
    current = llm_obj
    seen = 0
    while hasattr(current, "runnable") and seen < 4:
        current = getattr(current, "runnable")
        seen += 1
    return current


def _build_ragas_llm(runtime):
    base = _unwrap_langchain_llm(getattr(runtime, "llm", None))
    provider = os.getenv("LEGAL_CHATBOT_LLM_PROVIDER", "groq").strip().lower()
    if provider != "groq":
        return base
    try:
        from langchain_community.chat_models import ChatOpenAI
        from src.legal_chatbot.config import (
            LLM_ANALYZER_MODEL,
            LLM_REASONER_MODEL,
            LLM_TIMEOUT,
        )
    except Exception:
        return base

    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        return base
    _sanitize_proxy_env_for_groq()

    model_name = os.getenv(
        "RAGAS_EVAL_MODEL",
        os.getenv("LEGAL_CHATBOT_ANALYZER_MODEL", LLM_ANALYZER_MODEL).strip()
        or LLM_REASONER_MODEL,
    )
    max_tokens = int(os.getenv("RAGAS_EVAL_MAX_TOKENS", "2048"))
    timeout = int(os.getenv("RAGAS_EVAL_TIMEOUT", str(LLM_TIMEOUT)))

    try:
        return ChatOpenAI(
            model_name=model_name,
            temperature=0.0,
            max_tokens=max_tokens,
            openai_api_base="https://api.groq.com/openai/v1",
            openai_api_key=api_key,
            request_timeout=timeout,
            max_retries=0,
        )
    except Exception:
        return base


def _truncate_text(text: str, limit: int) -> str:
    if not isinstance(text, str):
        return ""
    clean = " ".join(text.split())
    if limit <= 0 or len(clean) <= limit:
        return clean
    return clean[:limit]


def _normalize_contexts(contexts: list[str]) -> list[str]:
    max_contexts = int(os.getenv("RAGAS_MAX_CONTEXTS", "2"))
    max_chars = int(os.getenv("RAGAS_MAX_CONTEXT_CHARS", "900"))
    limited = []
    for ctx in (contexts or [])[: max(1, max_contexts)]:
        truncated = _truncate_text(ctx, max_chars)
        if truncated:
            limited.append(truncated)
    return limited or [""]


def _normalize_reference_contexts(reference: str) -> list[str]:
    max_ref_contexts = int(os.getenv("RAGAS_MAX_REFERENCE_CONTEXTS", "2"))
    max_chars = int(os.getenv("RAGAS_MAX_REFERENCE_CONTEXT_CHARS", "900"))
    chunks = [c.strip() for c in re.split(r"\n{2,}", reference or "") if c.strip()]
    if not chunks and reference:
        chunks = [reference]
    out = []
    for chunk in chunks[: max(1, max_ref_contexts)]:
        truncated = _truncate_text(chunk, max_chars)
        if truncated:
            out.append(truncated)
    return out or [""]


def run_trulens_metrics(records: list[dict]) -> dict:
    try:
        nltk_data_dir = os.getenv(
            "TRULENS_NLTK_DATA_DIR",
            str((ROOT / "tmp" / "nltk_data").resolve()),
        ).strip()
        if nltk_data_dir:
            Path(nltk_data_dir).mkdir(parents=True, exist_ok=True)
            os.environ.setdefault("NLTK_DATA", nltk_data_dir)

        metric_mode = os.getenv("TRULENS_METRIC_MODE", "ground_truth").strip().lower()
        if metric_mode == "ground_truth":
            try:
                from trulens.feedback.groundtruth import GroundTruthAgreement
                from trulens.providers.openai import OpenAI
            except Exception as exc:
                return {"enabled": False, "error": f"truLens ground-truth mode unavailable: {exc}"}

            retrieval_golden_set = []
            for row in records:
                expected_chunks = [
                    {"text": text, "expect_score": 1.0}
                    for text in _normalize_reference_contexts(str(row.get("reference", "") or ""))
                    if text.strip()
                ]
                retrieval_golden_set.append(
                    {
                        "query": str(row.get("query", "") or ""),
                        "expected_chunks": expected_chunks,
                    }
                )

            gt_openai_api_key = (
                os.getenv("TRULENS_OPENAI_API_KEY", "").strip()
                or os.getenv("OPENAI_API_KEY", "").strip()
                or os.getenv("GROQ_API_KEY", "").strip()
            )
            if not gt_openai_api_key:
                return {
                    "enabled": False,
                    "error": "truLens ground-truth mode needs TRULENS_OPENAI_API_KEY/OPENAI_API_KEY/GROQ_API_KEY",
                }
            gt_openai_base_url = os.getenv(
                "TRULENS_OPENAI_BASE_URL",
                "https://api.groq.com/openai/v1",
            ).strip()
            gt_openai_model = os.getenv("TRULENS_OPENAI_MODEL", "llama-3.1-8b-instant").strip()
            gt_provider = OpenAI(
                model_engine=gt_openai_model,
                api_key=gt_openai_api_key,
                base_url=gt_openai_base_url,
            )
            gta = GroundTruthAgreement(ground_truth=retrieval_golden_set, provider=gt_provider)
            per_case = []
            precision_scores = []
            ndcg_scores = []
            errors = []
            for row in records:
                query = str(row.get("query", "") or "")
                contexts = _normalize_contexts(row.get("contexts") or [])
                precision = None
                ndcg = None
                metric_errors = []

                try:
                    precision = _to_float_or_none(gta.precision_at_k(query, contexts))
                except Exception as exc:
                    metric_errors.append(f"precision_at_k: {exc}")

                try:
                    ndcg = _to_float_or_none(gta.ndcg_at_k(query, contexts))
                except Exception as exc:
                    # NDCG is undefined when the candidate list has a single document.
                    # Keep the case with ndcg=None instead of dropping it entirely.
                    if "more than 1 document" not in str(exc).lower():
                        metric_errors.append(f"ndcg_at_k: {exc}")

                if metric_errors:
                    errors.append({"case_id": row.get("case_id"), "error": " | ".join(metric_errors)})
                if precision is not None:
                    precision_scores.append(precision)
                if ndcg is not None:
                    ndcg_scores.append(ndcg)
                per_case.append(
                    {
                        "case_id": row.get("case_id"),
                        "precision_at_k": precision,
                        "ndcg_at_k": ndcg,
                    }
                )

            return {
                "enabled": bool(per_case),
                "metric_mode": "ground_truth",
                "provider": "trulens_ground_truth",
                "aggregate": {
                    "precision_at_k": mean(precision_scores) if precision_scores else None,
                    "ndcg_at_k": mean(ndcg_scores) if ndcg_scores else None,
                    "precision_valid_cases": len(precision_scores),
                    "ndcg_valid_cases": len(ndcg_scores),
                    "total_cases": len(per_case),
                },
                "per_case": per_case,
                "errors": errors,
            }

        provider = None
        provider_name = ""
        model = ""
        provider_errors = []

        preferred = os.getenv("TRULENS_PROVIDER", "auto").strip().lower()
        candidate_order = ["openai", "litellm"] if preferred in {"auto", ""} else [preferred]

        if "openai" in candidate_order:
            try:
                from trulens.providers.openai import OpenAI

                model = os.getenv("TRULENS_OPENAI_MODEL", "llama-3.1-8b-instant").strip()
                openai_api_key = (
                    os.getenv("TRULENS_OPENAI_API_KEY", "").strip()
                    or os.getenv("OPENAI_API_KEY", "").strip()
                    or os.getenv("GROQ_API_KEY", "").strip()
                )
                if not openai_api_key:
                    raise RuntimeError("missing TRULENS_OPENAI_API_KEY/OPENAI_API_KEY/GROQ_API_KEY")
                openai_base_url = os.getenv(
                    "TRULENS_OPENAI_BASE_URL",
                    "https://api.groq.com/openai/v1",
                ).strip()
                provider = OpenAI(
                    model_engine=model,
                    api_key=openai_api_key,
                    base_url=openai_base_url,
                )
                provider_name = "trulens_openai"
            except Exception as exc:
                provider_errors.append(f"openai provider error: {exc}")

        if provider is None and "litellm" in candidate_order:
            try:
                from trulens.providers.litellm import LiteLLM

                model = os.getenv("TRULENS_LITELLM_MODEL", "groq/llama-3.1-8b-instant")
                provider = LiteLLM(model_engine=model)
                provider_name = "trulens_litellm"
            except Exception as exc:
                provider_errors.append(f"litellm provider error: {exc}")

        if provider is None:
            return {
                "enabled": False,
                "error": "truLens unavailable: " + " | ".join(provider_errors or ["no provider initialized"]),
            }

        groundedness_fn = getattr(
            provider,
            "groundedness_measure_with_cot_reasons_consider_answerability",
            None,
        ) or getattr(provider, "groundedness_measure_with_cot_reasons", None)
        answer_rel_fn = getattr(provider, "relevance_with_cot_reasons", None)
        context_rel_fn = getattr(provider, "context_relevance_with_cot_reasons", None)

        if not (groundedness_fn and answer_rel_fn and context_rel_fn):
            return {
                "enabled": False,
                "error": "truLens provider lacks required feedback methods",
            }

        per_case = []
        groundedness_scores = []
        answer_rel_scores = []
        context_rel_scores = []
        per_case_errors = []

        runtime_attempts = max(1, int(os.getenv("TRULENS_RUNTIME_ATTEMPTS", "2")))
        max_contexts = int(os.getenv("TRULENS_MAX_CONTEXTS", "2"))
        max_context_chars = int(os.getenv("TRULENS_MAX_CONTEXT_CHARS", "800"))
        groundedness_signature = inspect.signature(groundedness_fn)
        groundedness_needs_question = "question" in groundedness_signature.parameters

        def _call_trulens_with_retry(func, attempts):
            last_exc = None
            for attempt_idx in range(1, runtime_attempts + 1):
                try:
                    return _call_with_fallbacks(func, attempts)
                except Exception as exc:
                    last_exc = exc
                    message = str(exc)
                    is_rate_limit = ("429" in message) or ("rate limit" in message.lower())
                    if attempt_idx >= runtime_attempts or not is_rate_limit:
                        break
                    retry_after = _extract_retry_after_seconds(message)
                    wait_seconds = retry_after if retry_after is not None else min(20.0, 2.0 * attempt_idx)
                    time.sleep(max(0.5, wait_seconds))
            if last_exc is not None:
                raise last_exc
            return None

        for row in records:
            query = row["query"]
            answer = row["answer"]
            contexts = _normalize_contexts(row["contexts"])[:max_contexts]
            contexts = [_truncate_text(c, max_context_chars) for c in contexts] or [""]
            source_blob = "\n\n".join(contexts).strip()

            try:
                groundedness_attempts = (
                    [
                        {"source": source_blob, "statement": answer, "question": query},
                        (source_blob, answer, query),
                    ]
                    if groundedness_needs_question
                    else [
                        {"source": source_blob, "statement": answer},
                        (source_blob, answer),
                    ]
                )
                groundedness_raw = _call_trulens_with_retry(
                    groundedness_fn,
                    groundedness_attempts,
                )
                answer_rel_raw = _call_trulens_with_retry(
                    answer_rel_fn,
                    [
                        {"prompt": query, "response": answer},
                        {"query": query, "response": answer},
                        (query, answer),
                    ],
                )
            except Exception as exc:
                per_case_errors.append({"case_id": row["case_id"], "error": str(exc)})
                continue

            ctx_scores = []
            for ctx in contexts:
                try:
                    raw = _call_trulens_with_retry(
                        context_rel_fn,
                        [
                            {"question": query, "context": ctx},
                            {"query": query, "context": ctx},
                            (query, ctx),
                        ],
                    )
                except Exception:
                    continue
                score = _score_from_trulens_output(raw)
                if score is not None:
                    ctx_scores.append(score)

            groundedness = _score_from_trulens_output(groundedness_raw)
            answer_rel = _score_from_trulens_output(answer_rel_raw)
            context_rel = mean(ctx_scores) if ctx_scores else None

            if groundedness is not None:
                groundedness_scores.append(groundedness)
            if answer_rel is not None:
                answer_rel_scores.append(answer_rel)
            if context_rel is not None:
                context_rel_scores.append(context_rel)

            per_case.append(
                {
                    "case_id": row["case_id"],
                    "groundedness": groundedness,
                    "answer_relevance": answer_rel,
                    "context_relevance": context_rel,
                }
            )

        return {
            "enabled": bool(per_case),
            "metric_mode": "llm",
            "provider": provider_name,
            "model": model,
            "aggregate": {
                "groundedness": mean(groundedness_scores) if groundedness_scores else None,
                "answer_relevance": mean(answer_rel_scores) if answer_rel_scores else None,
                "context_relevance": mean(context_rel_scores) if context_rel_scores else None,
            },
            "per_case": per_case,
            "errors": per_case_errors,
        }
    except Exception as exc:
        return {"enabled": False, "error": f"truLens runtime error: {exc}"}


def run_ragas_metrics(records: list[dict], runtime) -> dict:
    try:
        from datasets import Dataset
        from ragas import evaluate as ragas_evaluate
        from ragas.embeddings import LangchainEmbeddingsWrapper
        from ragas.llms import LangchainLLMWrapper
    except Exception as exc:
        return {"enabled": False, "error": f"ragas unavailable: {exc}"}
    metric_mode = os.getenv("RAGAS_METRIC_MODE", "non_llm").strip().lower()
    if metric_mode not in {"non_llm", "llm"}:
        metric_mode = "non_llm"

    metric_candidates = []
    if metric_mode == "non_llm":
        try:
            from ragas.metrics._context_precision import NonLLMContextPrecisionWithReference
            from ragas.metrics._context_recall import NonLLMContextRecall

            metric_candidates = [
                NonLLMContextPrecisionWithReference(),
                NonLLMContextRecall(),
            ]
        except Exception as exc:
            return {"enabled": False, "error": f"ragas non-llm metrics unavailable: {exc}"}
    else:
        try:
            from ragas.metrics.collections import (
                Faithfulness,
                ResponseRelevancy,
                context_precision,
            )
        except Exception:
            try:
                from ragas.metrics import Faithfulness, ResponseRelevancy, context_precision
            except Exception:
                Faithfulness = None
                ResponseRelevancy = None
                context_precision = None

        strictness = int(os.getenv("RAGAS_RESPONSE_RELEVANCY_STRICTNESS", "1"))
        if ResponseRelevancy is not None:
            try:
                metric_candidates.append(ResponseRelevancy(strictness=max(1, strictness)))
            except Exception:
                metric_candidates.append(ResponseRelevancy())
        if Faithfulness is not None:
            metric_candidates.append(Faithfulness())
        if context_precision is not None:
            metric_candidates.append(context_precision)

    metric_candidates = [m for m in metric_candidates if m is not None]
    if not metric_candidates:
        return {"enabled": False, "error": "ragas metrics could not be resolved"}

    answer_limit = int(os.getenv("RAGAS_MAX_ANSWER_CHARS", "1400"))
    reference_limit = int(os.getenv("RAGAS_MAX_REFERENCE_CHARS", "1600"))
    ds_rows = {
        # Current ragas (>=0.3) field names.
        "user_input": [],
        "response": [],
        "retrieved_contexts": [],
        "reference": [],
        "reference_contexts": [],
        # Backward compatibility aliases.
        "question": [],
        "answer": [],
        "contexts": [],
        "ground_truth": [],
    }
    for row in records:
        query = str(row.get("query", "") or "")
        answer = _truncate_text(str(row.get("answer", "") or ""), answer_limit)
        contexts = _normalize_contexts(row.get("contexts") or [])
        reference = _truncate_text(str(row.get("reference", "") or ""), reference_limit)
        reference_contexts = _normalize_reference_contexts(reference)

        ds_rows["user_input"].append(query)
        ds_rows["response"].append(answer)
        ds_rows["retrieved_contexts"].append(contexts)
        ds_rows["reference"].append(reference)
        ds_rows["reference_contexts"].append(reference_contexts)

        ds_rows["question"].append(query)
        ds_rows["answer"].append(answer)
        ds_rows["contexts"].append(contexts)
        ds_rows["ground_truth"].append(reference)

    dataset = Dataset.from_dict(ds_rows)
    kwargs = {
        "dataset": dataset,
        "metrics": metric_candidates,
        "raise_exceptions": True,
        "show_progress": False,
        "batch_size": 1,
    }
    try:
        from ragas.run_config import RunConfig

        kwargs["run_config"] = RunConfig(
            timeout=int(os.getenv("RAGAS_TIMEOUT_SECONDS", "120")),
            max_retries=int(os.getenv("RAGAS_MAX_RETRIES", "1")),
            max_workers=int(os.getenv("RAGAS_MAX_WORKERS", "1")),
        )
    except Exception:
        pass

    try:
        from src.legal_chatbot.embeddings import create_embeddings
        from src.legal_chatbot.config import EMBED_MODEL

        kwargs["embeddings"] = LangchainEmbeddingsWrapper(create_embeddings(EMBED_MODEL))
    except Exception:
        pass

    if metric_mode == "llm":
        ragas_llm = _build_ragas_llm(runtime)
        if ragas_llm is not None:
            try:
                kwargs["llm"] = LangchainLLMWrapper(ragas_llm)
            except Exception:
                pass

    trace_env_keys = ("LANGCHAIN_TRACING_V2", "LANGSMITH_TRACING")
    prev_trace_env = {k: os.getenv(k) for k in trace_env_keys}
    for k in trace_env_keys:
        os.environ[k] = "false"
    result = None
    runtime_attempts = max(1, int(os.getenv("RAGAS_RUNTIME_ATTEMPTS", "2")))
    runtime_err = None
    try:
        for attempt in range(1, runtime_attempts + 1):
            try:
                result = ragas_evaluate(**kwargs)
                runtime_err = None
                break
            except Exception as exc:
                runtime_err = exc
                message = str(exc)
                is_retryable = (
                    ("429" in message)
                    or ("rate limit" in message.lower())
                    or ("connection error" in message.lower())
                )
                if attempt >= runtime_attempts or not is_retryable:
                    break
                retry_after = _extract_retry_after_seconds(message)
                wait_seconds = retry_after if retry_after is not None else min(30.0, 2.0 * attempt)
                time.sleep(max(0.5, wait_seconds))
    finally:
        for k, v in prev_trace_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    if runtime_err is not None or result is None:
        return {"enabled": False, "error": f"ragas runtime error: {runtime_err}", "metric_mode": metric_mode}

    metric_names = []
    for metric in metric_candidates:
        name = getattr(metric, "name", "")
        if isinstance(name, str) and name:
            metric_names.append(name)
    metric_names = list(dict.fromkeys(metric_names))

    aggregate: dict[str, float | None] = {name: None for name in metric_names}
    per_case: list[dict[str, Any]] = []
    if hasattr(result, "to_pandas"):
        try:
            df = result.to_pandas()
            for idx, row in df.iterrows():
                case_metric = {"case_id": records[idx]["case_id"] if idx < len(records) else None}
                for name in metric_names:
                    score = _to_float_or_none(row.get(name))
                    case_metric[name] = score
                per_case.append(case_metric)
            for name in metric_names:
                values = [_to_float_or_none(v) for v in df.get(name, [])]
                numeric = [v for v in values if v is not None]
                aggregate[name] = (mean(numeric) if numeric else None)
        except Exception:
            pass

    if all(v is None for v in aggregate.values()):
        return {
            "enabled": False,
            "error": "ragas returned no finite scores; check metric config/runtime",
            "metric_mode": metric_mode,
            "metric_count": len(metric_candidates),
            "aggregate": aggregate,
            "per_case": per_case,
        }

    return {
        "enabled": True,
        "metric_mode": metric_mode,
        "aggregate": aggregate,
        "metric_count": len(metric_candidates),
        "per_case": per_case,
    }


def upload_langsmith_dataset(records: list[dict], dataset_name: str) -> dict:
    try:
        from langsmith import Client
    except Exception as exc:
        return {"enabled": False, "error": f"langsmith unavailable: {exc}"}

    client = Client()
    try:
        client.create_dataset(
            dataset_name=dataset_name,
            description="Legal chatbot RAG evaluation dataset (generated from test_cases.yaml)",
        )
    except Exception:
        pass

    created = 0
    for row in records:
        ex_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{dataset_name}:{row['case_id']}"))
        try:
            client.create_example(
                example_id=ex_id,
                dataset_name=dataset_name,
                inputs={"query": row["query"]},
                outputs={"reference": row["reference"]},
                metadata={
                    "case_id": row["case_id"],
                    "expected_mode": row["expected_mode"],
                    "expected_refs": row["expected_refs"],
                },
            )
            created += 1
        except Exception:
            # Keep idempotent: skip existing examples.
            continue

    return {"enabled": True, "dataset_name": dataset_name, "created_examples": created}


def upload_langfuse_dataset(records: list[dict], dataset_name: str) -> dict:
    try:
        from langfuse import get_client
    except Exception as exc:
        return {"enabled": False, "error": f"langfuse unavailable: {exc}"}

    client = get_client()
    try:
        client.create_dataset(
            name=dataset_name,
            description="Legal chatbot RAG evaluation dataset (generated from test_cases.yaml)",
        )
    except Exception:
        pass

    created = 0
    for row in records:
        item_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{dataset_name}:{row['case_id']}"))
        try:
            client.create_dataset_item(
                dataset_name=dataset_name,
                id=item_id,
                input={"query": row["query"]},
                expected_output={"reference": row["reference"]},
                metadata={
                    "case_id": row["case_id"],
                    "expected_mode": row["expected_mode"],
                    "expected_refs": row["expected_refs"],
                },
            )
            created += 1
        except Exception:
            continue

    try:
        client.flush()
    except Exception:
        pass

    return {"enabled": True, "dataset_name": dataset_name, "created_items": created}


def _runtime_for_metrics_only():
    try:
        from src.legal_chatbot.llm_factory import create_llm_clients
    except Exception as exc:
        raise RuntimeError(f"Không thể khởi tạo LLM cho metrics-only mode: {exc}") from exc

    class _Runtime:
        pass

    runtime = _Runtime()
    runtime.llm = create_llm_clients().llm_reason
    return runtime


def _coerce_int(value: Any) -> int | None:
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return int(value)
        text = str(value).strip()
        if not text:
            return None
        if text.isdigit():
            return int(text)
    except Exception:
        return None
    return None


def _legacy_result_to_record(item: dict) -> dict:
    case_id = _coerce_int(item.get("case_id"))
    query = str(item.get("query", "") or "").strip()

    answer_layer = item.get("answer_grounding_layer", {}) or {}
    answer = str(
        answer_layer.get("final_answer")
        or answer_layer.get("draft_answer")
        or item.get("answer")
        or ""
    ).strip()

    retrieval_layer = item.get("retrieval_layer", {}) or {}
    top_k_chunks = retrieval_layer.get("top_k_chunks", []) or []
    contexts: list[str] = []
    for chunk in top_k_chunks:
        if not isinstance(chunk, dict):
            continue
        snippet = str(chunk.get("snippet", "") or "").strip()
        if snippet:
            contexts.append(snippet)

    expected_refs_raw = (
        item.get("expected_refs")
        or ((item.get("evaluation", {}) or {}).get("reference_coverage", {}) or {}).get("expected_articles", [])
        or []
    )
    expected_refs: list[int] = []
    for ref in expected_refs_raw:
        ref_int = _coerce_int(ref)
        if ref_int is not None and ref_int not in expected_refs:
            expected_refs.append(ref_int)

    # IMPORTANT: avoid leakage by reusing retrieved snippets as "ground truth".
    reference = str(
        item.get("reference")
        or item.get("reference_text")
        or ""
    ).strip()

    return {
        "case_id": case_id,
        "query": query,
        "expected_mode": str(item.get("expected_mode", "") or "").strip(),
        "expected_refs": expected_refs,
        "answer": answer,
        "contexts": contexts,
        "reference": reference,
        "checks": item.get("checks", {}) or {},
        "fallback": item.get("guard_fallback_layer", {}) or {},
        "evaluation": item.get("evaluation", {}) or {},
    }


def _load_records_from_report(report_path: Path) -> tuple[list[dict], dict]:
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    summary = payload.get("summary", {}) or {}

    records = payload.get("records", []) or []
    if not records:
        legacy_results = payload.get("results", []) or []
        records = [_legacy_result_to_record(item) for item in legacy_results if isinstance(item, dict)]

    total = len(records)
    passed = sum(1 for r in records if all(bool(v) for v in (r.get("checks", {}) or {}).values()))
    failed = total - passed

    normalized_summary = dict(summary) if isinstance(summary, dict) else {}
    normalized_summary.setdefault("total_cases", total)
    normalized_summary.setdefault("passed_cases", passed)
    normalized_summary.setdefault("failed_cases", failed)
    return records, normalized_summary


def _hydrate_missing_references(records: list[dict], runtime) -> list[dict]:
    """
    Backfill missing references from expected article ids via exact-article retrieval,
    instead of deriving references from model outputs/retrieved snippets.
    """
    hydrated = []
    for row in records:
        rec = dict(row)
        reference = str(rec.get("reference", "") or "").strip()
        expected_refs = [int(x) for x in (rec.get("expected_refs") or []) if str(x).isdigit()]
        if not reference and expected_refs:
            reference = _build_reference_text(runtime, expected_refs)
            rec["reference"] = reference
        hydrated.append(rec)
    return hydrated


def main():
    case_ids = _parse_case_ids(os.getenv("CASE_IDS", ""))
    limit = int(os.getenv("CASE_LIMIT", "0"))
    dataset_name = os.getenv("THIRD_PARTY_QA_DATASET", "legal-chatbot-rag-cases")
    source_report = os.getenv("THIRD_PARTY_SOURCE_REPORT", "").strip()

    run_ragas = os.getenv("ENABLE_RAGAS", "1").strip().lower() in {"1", "true", "yes", "on"}
    run_trulens = os.getenv("ENABLE_TRULENS", "1").strip().lower() in {"1", "true", "yes", "on"}
    push_langsmith = os.getenv("ENABLE_LANGSMITH_DATASET_SYNC", "1").strip().lower() in {"1", "true", "yes", "on"}
    push_langfuse = os.getenv("ENABLE_LANGFUSE_DATASET_SYNC", "1").strip().lower() in {"1", "true", "yes", "on"}
    ragas_use_vendor = os.getenv("RAGAS_USE_VENDOR_PATH", "0").strip().lower() in {"1", "true", "yes", "on"}
    trulens_use_vendor = os.getenv("TRULENS_USE_VENDOR_PATH", "1").strip().lower() in {"1", "true", "yes", "on"}

    print(f"[INFO] Observability state: {json.dumps(describe_observability_state(), ensure_ascii=False)}")
    if source_report:
        source_path = Path(source_report)
        if not source_path.exists():
            raise FileNotFoundError(f"THIRD_PARTY_SOURCE_REPORT không tồn tại: {source_path}")
        print(f"[INFO] Metrics-only mode from report: {source_path}")
        records, summary = _load_records_from_report(source_path)
        runtime = _runtime_for_metrics_only()
        records = _hydrate_missing_references(records, runtime)
    else:
        cases = _load_cases(case_ids=case_ids, limit=limit)
        print(f"[INFO] Loaded {len(cases)} cases from {TEST_CASES_PATH}")
        try:
            runtime = init_runtime()
            records, summary = run_predictions(cases, runtime)
        except Exception as exc:
            hint = (
                "Không thể khởi tạo runtime/vector DB. "
                "Bạn có thể chạy metrics-only bằng THIRD_PARTY_SOURCE_REPORT=... "
                "để vẫn dùng được third-party QA."
            )
            raise RuntimeError(f"{hint} Root cause: {exc}") from exc

    third_party_metrics = {}
    vendor_announced = False
    if run_ragas:
        if ragas_use_vendor:
            vendor_loaded = _enable_vendor_path_from_env()
            if vendor_loaded and not vendor_announced:
                print(f"[INFO] Loaded third-party vendor path: {vendor_loaded}")
                vendor_announced = True
        print("[INFO] Running Ragas metrics...")
        third_party_metrics["ragas"] = run_ragas_metrics(records, runtime)
    if run_trulens:
        if trulens_use_vendor:
            vendor_loaded = _enable_vendor_path_from_env()
            if vendor_loaded and not vendor_announced:
                print(f"[INFO] Loaded third-party vendor path: {vendor_loaded}")
                vendor_announced = True
        print("[INFO] Running TruLens metrics...")
        third_party_metrics["trulens"] = run_trulens_metrics(records)

    dataset_sync = {}
    if push_langsmith:
        print("[INFO] Syncing dataset to LangSmith...")
        dataset_sync["langsmith"] = upload_langsmith_dataset(records, dataset_name)
    if push_langfuse:
        print("[INFO] Syncing dataset to Langfuse...")
        dataset_sync["langfuse"] = upload_langfuse_dataset(records, dataset_name)

    report = {
        "generated_at": datetime.now().isoformat(),
        "summary": summary,
        "observability": describe_observability_state(),
        "third_party_metrics": third_party_metrics,
        "dataset_sync": dataset_sync,
        "records": records,
    }
    report = _sanitize_for_json(report)

    out_path = REPORT_DIR / f"third_party_eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, allow_nan=False)

    print(f"[DONE] Third-party QA report saved to: {out_path}")


if __name__ == "__main__":
    main()
