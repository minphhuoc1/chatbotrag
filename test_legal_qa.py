import os
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_TORCH", "1")

import argparse
import json
import re
import time
import warnings
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from difflib import SequenceMatcher
from typing import Dict, List, Tuple

import yaml

try:
    from langchain_chroma import Chroma
except ImportError:
    from langchain_community.vectorstores import Chroma

from retrieval import build_runtime_retriever, retrieve_documents, retrieve_exact_article
from intent import classify_intent, Intent
from reasoning_chain import LegalReasoningEngine
from src.legal_chatbot.config import (
    ANSWER_PROMPT_PATH,
    DB_PATH,
    EMBED_MODEL,
    LLM_ANALYZER_MODEL,
    LLM_PROVIDER,
    LLM_REASONER_MODEL,
    TEST_CASES_PATH,
    TOP_K,
)
from src.legal_chatbot.embeddings import create_embeddings
from src.legal_chatbot.evaluation import evaluate_case_with_rubric, summarize_rubric
from src.legal_chatbot.llm_factory import create_llm_clients
from src.legal_chatbot.text_quality import detect_runaway_generation
from src.legal_chatbot import policy as shared_policy

REPORT_DIR = Path("reports/legal_qa")
REPORT_DIR.mkdir(parents=True, exist_ok=True)


def parse_case_ids(raw: str | None = None) -> set:
    raw = (raw if raw is not None else os.getenv("CASE_IDS", "")).strip()
    if not raw:
        return set()
    ids = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            s, e = part.split("-", 1)
            if s.strip().isdigit() and e.strip().isdigit():
                start, end = int(s.strip()), int(e.strip())
                if start <= end:
                    ids.update(range(start, end + 1))
            continue
        if part.isdigit():
            ids.add(int(part))
            ids.add(part)
        else:
            ids.add(part)
    return ids


def _load_cases_payload(path: str) -> list:
    with open(path, "r", encoding="utf-8") as f:
        payload = yaml.safe_load(f) or {}
    cases = payload.get("cases")
    if cases is None:
        cases = payload.get("held_out_cases")
    if not isinstance(cases, list):
        raise KeyError("cases")

    normalized = []
    for case in cases:
        if not isinstance(case, dict):
            continue
        item = dict(case)
        if "expected_articles" in item and "must_reference_any_of" not in item:
            item["must_reference_any_of"] = [
                int(a) if isinstance(a, str) and a.isdigit() else a
                for a in item.get("expected_articles", [])
            ]
        if "expected_articles" in item and "expected_mode" not in item:
            item["expected_mode"] = "grounded_legal_answer"
        item.setdefault("must_not_hallucinate", True)
        normalized.append(item)
    return normalized


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run legal QA cases and write a JSON report.")
    parser.add_argument(
        "--case-ids",
        default=os.getenv("CASE_IDS", ""),
        help="Comma/range case selector, e.g. '2,5,10-12'. Defaults to CASE_IDS env.",
    )
    parser.add_argument(
        "--report-path",
        default=os.getenv("REPORT_PATH", ""),
        help="Output JSON path. Defaults to reports/legal_qa/legal_qa_report_<timestamp>.json.",
    )
    return parser


def classify_query_mode(user_input: str) -> str:
    text = user_input.lower().strip()
    is_article_lookup = bool(re.search(r"[đd]iều\s*\d+", text))
    is_quote_request = (
        "trích nguyên văn" in text
        or "trich nguyen van" in text
        or "trích dẫn nguyên văn" in text
        or "quote nguyên văn" in text
    )
    is_fact_pattern = any(
        kw in text
        for kw in [
            "có hợp pháp không",
            "đúng hay sai",
            "có vi phạm không",
            "bị",
            "đi làm",
            "không có hợp đồng",
            "đòi lương",
            "đền bù",
        ]
    )
    if is_quote_request:
        return "quote_request"
    if is_article_lookup:
        return "article_lookup"
    if is_fact_pattern:
        return "fact_pattern"
    return "open_ended"


def extract_requested_articles(user_input: str) -> List[int]:
    return [int(m) for m in re.findall(r"[đd]iều\s*(\d+)", user_input.lower())]


def extract_articles_from_documents(documents: list) -> List[int]:
    articles = set()
    for doc in documents:
        meta_article = doc.metadata.get("dieu_so")
        if meta_article and str(meta_article).isdigit():
            articles.add(int(meta_article))
        for m in re.findall(r"[Đđ]iều\s*(\d+)", doc.page_content):
            if m.isdigit():
                articles.add(int(m))
    return sorted(articles)


def assess_retrieval_strength(user_input: str, documents: list) -> Dict:
    query_mode = classify_query_mode(user_input)
    requested_articles = extract_requested_articles(user_input)
    matched_articles = extract_articles_from_documents(documents)

    has_exact_article_match = bool(requested_articles) and all(a in matched_articles for a in requested_articles)
    if query_mode in {"article_lookup", "quote_request"}:
        if requested_articles:
            if has_exact_article_match:
                return {
                    "is_strong_enough": True,
                    "has_exact_article_match": True,
                    "matched_articles": matched_articles,
                    "reason": "exact article found",
                }
            return {
                "is_strong_enough": False,
                "has_exact_article_match": False,
                "matched_articles": matched_articles,
                "reason": "requested article not found in retrieved context",
            }
        if documents:
            return {
                "is_strong_enough": True,
                "has_exact_article_match": False,
                "matched_articles": matched_articles,
                "reason": "quote/article request without explicit article, docs present",
            }
        return {
            "is_strong_enough": False,
            "has_exact_article_match": False,
            "matched_articles": matched_articles,
            "reason": "no context retrieved",
        }

    if len(documents) >= 2:
        return {
            "is_strong_enough": True,
            "has_exact_article_match": has_exact_article_match,
            "matched_articles": matched_articles,
            "reason": "sufficient semantic context",
        }
    return {
        "is_strong_enough": False,
        "has_exact_article_match": has_exact_article_match,
        "matched_articles": matched_articles,
        "reason": "only vague semantic matches",
    }


def extract_article_references(answer: str) -> List[int]:
    refs = set(int(m) for m in re.findall(r"[Đđ]iều\s*(\d+)", answer) if m.isdigit())
    return sorted(refs)


def _extract_quoted_segments(answer: str) -> List[str]:
    patterns = [r"“([^”]{8,})”", r"\"([^\"]{8,})\"", r"'([^']{8,})'"]
    quotes = []
    for pattern in patterns:
        quotes.extend(re.findall(pattern, answer))
    return [q.strip() for q in quotes if q.strip()]


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def validate_quote_grounding(answer: str, context_text: str) -> bool:
    quotes = _extract_quoted_segments(answer)
    norm_context = normalize(context_text)
    if not quotes:
        norm_answer = normalize(answer)
        return bool(norm_answer) and len(norm_answer) >= 30 and norm_answer in norm_context
    for quote in quotes:
        if normalize(quote) not in norm_context:
            return False
    return True


def validate_answer_against_context(
    answer: str,
    documents: list,
    query_mode: str,
    context_override: str = "",
) -> Dict:
    available_articles = set(extract_articles_from_documents(documents))
    answer_articles = extract_article_references(answer)
    invalid_articles = [a for a in answer_articles if a not in available_articles]

    if invalid_articles:
        return {
            "ok": False,
            "reason": f"answer cites articles not in context: {invalid_articles}",
            "invalid_articles": invalid_articles,
        }
    if query_mode == "quote_request":
        context_text = context_override or "\n\n".join(d.page_content for d in documents)
        if not validate_quote_grounding(answer, context_text):
            return {
                "ok": False,
                "reason": "quoted text is not grounded in retrieved context",
                "invalid_articles": [],
            }
    return {"ok": True, "reason": "grounded", "invalid_articles": []}


def build_insufficient_context_response(user_input: str, query_mode: str) -> str:
    requested_articles = extract_requested_articles(user_input)
    if query_mode == "article_lookup" and requested_articles:
        return (
            f"Tôi không tìm thấy Điều {requested_articles[0]} trong tài liệu/context hiện có. "
            "Không đủ căn cứ trong tài liệu hiện có để kết luận."
        )
    if query_mode == "quote_request":
        return (
            "Tôi chưa thấy đủ căn cứ trong tài liệu hiện có để trích nguyên văn chính xác. "
            "Vui lòng nêu rõ Điều/Khoản cần trích."
        )
    return (
        "Tôi chưa thấy đủ căn cứ trong tài liệu hiện có để kết luận chắc chắn. "
        "Bạn có thể nêu rõ hơn Điều/Khoản hoặc chủ đề cụ thể để tôi kiểm tra chính xác hơn."
    )


def build_validation_fallback(validation: Dict, query_mode: str) -> str:
    if validation.get("invalid_articles"):
        return (
            "Tôi phát hiện phần viện dẫn Điều luật chưa khớp với context retrieve được, "
            "nên chưa thể kết luận chắc chắn. Không đủ căn cứ trong tài liệu hiện có."
        )
    if query_mode == "quote_request":
        return (
            "Tôi chưa thể xác thực phần trích nguyên văn từ context hiện có. "
            "Không đủ căn cứ trong tài liệu hiện có để trích dẫn nguyên văn."
        )
    return "Không đủ căn cứ trong tài liệu hiện có để kết luận chắc chắn."


def resolve_article_query(user_input: str, documents: list) -> str:
    mode = classify_query_mode(user_input)
    if mode != "article_lookup":
        return ""
    requested_articles = extract_requested_articles(user_input)
    if not requested_articles:
        return "Bạn vui lòng nêu rõ số Điều cần tra cứu (ví dụ: Điều 35)."

    matched = extract_articles_from_documents(documents)
    if requested_articles and all(a in matched for a in requested_articles):
        return ""

    text = user_input.lower()
    has_labor_context = "bộ luật lao động" in text or "luật lao động" in text or "lao động" in text
    if not has_labor_context:
        return (
            "Bạn vui lòng xác nhận văn bản luật cần tra cứu. "
            "Nếu bạn hỏi Bộ luật Lao động 2019, tôi sẽ trả lời theo văn bản đó."
        )

    return (
        f"Tôi chưa thấy đúng Điều {requested_articles[0]} trong context retrieve được. "
        "Không đủ căn cứ trong tài liệu hiện có để trả lời dứt khoát."
    )


def _doc_article_number(doc) -> int | None:
    meta = doc.metadata or {}
    raw = meta.get("article_number", meta.get("dieu_so"))
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str) and raw.isdigit():
        return int(raw)
    return None


def _sort_article_docs(docs: list) -> list:
    return sorted(
        docs,
        key=lambda d: (
            (d.metadata or {}).get("subchunk_index", 10**9),
            (d.metadata or {}).get("chunk_id", 10**9),
        ),
    )


def _assemble_article_text(docs: list) -> str:
    if not docs:
        return ""
    def _merge_with_overlap(base: str, nxt: str, min_overlap: int = 40, max_overlap: int = 260) -> str:
        left = (base or "").rstrip()
        right = (nxt or "").lstrip()
        if not left:
            return right
        if not right:
            return left
        max_len = min(max_overlap, len(left), len(right))
        for n in range(max_len, min_overlap - 1, -1):
            if left[-n:] == right[:n]:
                return left + right[n:]
        return left + "\n\n" + right

    merged = ""
    seen = set()
    for d in _sort_article_docs(docs):
        text = (d.page_content or "").strip()
        if not text:
            continue
        key = normalize(text)[:220]
        if key in seen:
            continue
        seen.add(key)
        merged = _merge_with_overlap(merged, text)
    return merged.strip()


def _filter_docs_for_exact_article(docs: list, article_number: int) -> list:
    out = []
    for d in docs:
        art = _doc_article_number(d)
        if art == article_number:
            out.append(d)
    return _sort_article_docs(out)

# Shared policy contract for app + QA harnesses (P1)
classify_query_mode = shared_policy.classify_query_mode
extract_requested_articles = shared_policy.extract_requested_articles
extract_articles_from_documents = shared_policy.extract_articles_from_documents
assess_retrieval_strength = shared_policy.assess_retrieval_strength
extract_article_references = shared_policy.extract_article_references
_extract_quoted_segments = shared_policy._extract_quoted_segments
normalize = shared_policy.normalize
validate_quote_grounding = shared_policy.validate_quote_grounding
validate_answer_against_context = shared_policy.validate_answer_against_context
build_insufficient_context_response = shared_policy.build_insufficient_context_response
build_validation_fallback = shared_policy.build_validation_fallback
resolve_article_query = shared_policy.resolve_article_query
_doc_article_number = shared_policy._doc_article_number
_sort_article_docs = shared_policy._sort_article_docs
_assemble_article_text = shared_policy._assemble_article_text
_filter_docs_for_exact_article = shared_policy._filter_docs_for_exact_article
suggest_target_articles = shared_policy.suggest_target_articles
enforce_citation_contract = shared_policy.enforce_citation_contract
repair_answer_citations = shared_policy.repair_answer_citations
build_extractive_fallback_answer = shared_policy.build_extractive_fallback_answer
normalize_high_risk_fact_answer = shared_policy.normalize_high_risk_fact_answer


def short_snippet(text: str, min_len: int = 150, max_len: int = 300) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= max_len:
        return cleaned
    cut = cleaned[:max_len]
    if len(cut) < min_len:
        return cleaned[:min_len]
    return cut


def _extract_retry_after_seconds(error_text: str) -> float | None:
    match = re.search(r"try again in\s+([0-9]+(?:\.[0-9]+)?)s", error_text, flags=re.IGNORECASE)
    if not match:
        return None
    try:
        return float(match.group(1))
    except Exception:
        return None


def _invoke_reasoner_with_backoff(runtime: "Runtime", query: str, context_text: str, max_attempts: int = 4) -> str:
    """
    QA harness helper: giảm fail cứng do Groq 429.
    - Retry với backoff khi rate limit.
    - Giảm context dần để hạ token request nếu cần.
    """
    attempt = 0
    current_context = context_text or ""
    while attempt < max_attempts:
        attempt += 1
        try:
            response = runtime.engine.reasoner_chain.invoke(
                {"context": current_context, "chat_history": [], "input": query}
            )
            if str(response or "").strip():
                return response
            if attempt >= max_attempts:
                return ""
            time.sleep(min(3.0, 0.8 * attempt))
        except Exception as exc:
            msg = str(exc)
            is_rate_limit = ("429" in msg) or ("rate limit" in msg.lower())
            if not is_rate_limit or attempt >= max_attempts:
                raise
            retry_after = _extract_retry_after_seconds(msg)
            wait_seconds = retry_after if retry_after is not None else min(20.0, 3.0 * attempt)
            time.sleep(max(0.8, wait_seconds))
            # Context decay để giảm token burst ở lượt kế tiếp.
            if len(current_context) > 1200:
                current_context = current_context[: max(1200, int(len(current_context) * 0.75))]
    raise RuntimeError("reasoner invocation failed after retries")


def doc_key_from_doc(doc) -> Tuple[str, str, str]:
    meta = doc.metadata or {}
    return (
        str(meta.get("chunk_id", "")),
        str(meta.get("dieu_so", meta.get("article_number", ""))),
        str(meta.get("page", meta.get("page_start", ""))),
    )


def quote_match_status(quote: str, context_text: str) -> Tuple[str, str]:
    quote_norm = normalize(quote)
    context_norm = normalize(context_text)
    if not quote_norm:
        return "hallucinated_quote", ""
    if quote_norm in context_norm:
        return "exact_match", quote

    best_ratio = 0.0
    best_candidate = ""
    words = context_norm.split(" ")
    q_len = max(len(quote_norm.split(" ")), 6)
    for i in range(max(len(words) - q_len + 1, 1)):
        candidate = " ".join(words[i:i + q_len + 8]).strip()
        if not candidate:
            continue
        ratio = SequenceMatcher(None, quote_norm, candidate).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_candidate = candidate
    if best_ratio >= 0.85:
        return "near_match", best_candidate
    return "hallucinated_quote", best_candidate


@dataclass
class Runtime:
    vector_db: Chroma
    retriever: any
    llm: object
    llm_intent: object
    engine: LegalReasoningEngine


def init_runtime() -> Runtime:
    embeddings = create_embeddings(EMBED_MODEL)
    vector_db = Chroma(persist_directory=DB_PATH, embedding_function=embeddings)
    retriever = build_runtime_retriever(vector_db=vector_db, k=TOP_K)
    llm_clients = create_llm_clients()
    llm = llm_clients.llm_reason
    llm_json = llm_clients.llm_json
    llm_intent = llm_clients.llm_intent
    with open(ANSWER_PROMPT_PATH, "r", encoding="utf-8") as f:
        system_prompt = f.read()
    engine = LegalReasoningEngine(
        retriever,
        llm_json,
        llm,
        system_prompt,
        llm_intent=llm_intent,
    )
    return Runtime(
        vector_db=vector_db,
        retriever=retriever,
        llm=llm,
        llm_intent=llm_intent,
        engine=engine,
    )


def build_retrieval_rows(query: str, docs: list, vector_db: Chroma) -> List[Dict]:
    score_map = {}
    try:
        scored = vector_db.similarity_search_with_score(query, k=TOP_K)
        for d, score in scored:
            score_map[doc_key_from_doc(d)] = float(score)
    except Exception:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                scored = vector_db.similarity_search_with_relevance_scores(query, k=TOP_K)
            for d, score in scored:
                score_map[doc_key_from_doc(d)] = float(score)
        except Exception:
            pass

    rows = []
    for i, doc in enumerate(docs, 1):
        meta = doc.metadata or {}
        rows.append(
            {
                "rank": i,
                "article_number": meta.get("dieu_so", meta.get("article_number")),
                "article_title": meta.get("article_title") or meta.get("title"),
                "score_or_relevance": score_map.get(doc_key_from_doc(doc)),
                "snippet": short_snippet(doc.page_content),
                "page": meta.get("page", meta.get("page_start")),
                "chunk_id": meta.get("chunk_id"),
                "source_file": meta.get("source_file"),
            }
        )
    return rows


def classify_fallback_reason(query_mode: str, retrieval_check: Dict, validation: Dict, used_article_resolution: bool) -> str:
    if used_article_resolution:
        return "missing_exact_article_or_ambiguous_law_scope"
    if not retrieval_check.get("is_strong_enough", False):
        reason = retrieval_check.get("reason", "")
        if "requested article not found" in reason:
            return "missing_exact_article"
        if "no context" in reason or "vague" in reason:
            return "weak_context"
        return "insufficient_context"
    if not validation.get("ok", True):
        if validation.get("invalid_articles"):
            return "citation_not_in_context"
        if query_mode == "quote_request":
            return "quote_not_grounded"
        return "validation_failed"
    return ""


def evaluate_case(runtime: Runtime, case: Dict) -> Dict:
    query = case["query"]
    query_mode = classify_query_mode(query)
    intent_res = classify_intent(query, runtime.llm_intent, chat_history=[])
    docs = retrieve_documents(user_input=query, retriever=runtime.retriever, k=TOP_K)
    target_articles = suggest_target_articles(query)
    for target_article in target_articles:
        if target_article in extract_articles_from_documents(docs):
            continue
        extra_docs = retrieve_exact_article(
            article_number=target_article,
            vector_db=runtime.vector_db,
            limit=12,
        )
        extra_docs = _filter_docs_for_exact_article(extra_docs, target_article)
        if extra_docs:
            docs = _sort_article_docs(extra_docs + docs)
    context_text = "\n\n".join(d.page_content for d in docs)
    requested_articles = extract_requested_articles(query)
    has_exact_article_match = False
    exact_article_text = ""

    def _format_article_lookup_answer(article_number: int, article_text: str) -> str:
        clean = (article_text or "").strip()
        if not clean:
            return f"Tôi không tìm thấy đủ nội dung Điều {article_number} trong tài liệu hiện có."
        return f"Điều {article_number} quy định như sau:\n\n{clean}"
    if query_mode in {"article_lookup", "quote_request"} and requested_articles:
        target_article = requested_articles[0]
        exact_article_docs = _filter_docs_for_exact_article(docs, target_article)
        if not exact_article_docs:
            vector_db = getattr(runtime.retriever, "vectorstore", None)
            if vector_db is not None:
                exact_article_docs = retrieve_exact_article(
                    article_number=target_article,
                    vector_db=vector_db,
                    limit=12,
                )
                exact_article_docs = _filter_docs_for_exact_article(exact_article_docs, target_article)
        exact_article_text = _assemble_article_text(exact_article_docs)
        has_exact_article_match = bool(exact_article_docs) and bool(exact_article_text)
        if exact_article_docs:
            docs = exact_article_docs
            context_text = exact_article_text
    retrieval_check = assess_retrieval_strength(query, docs)
    retrieval_rows = build_retrieval_rows(query, docs, runtime.vector_db)

    article_resolution = resolve_article_query(query, docs)
    used_article_resolution = bool(article_resolution)
    draft_answer = ""
    final_answer = ""
    validation = {"ok": True, "reason": "not_run", "invalid_articles": []}

    if intent_res.intent != Intent.LEGAL:
        final_answer = intent_res.response
    else:
        if article_resolution:
            final_answer = article_resolution
        elif not retrieval_check["is_strong_enough"]:
            final_answer = build_insufficient_context_response(query, query_mode)
        elif query_mode == "quote_request" and has_exact_article_match:
            final_answer = exact_article_text
            validation = validate_answer_against_context(
                answer=final_answer,
                documents=docs,
                query_mode=query_mode,
                context_override=exact_article_text,
            )
            if not validation.get("ok", False):
                final_answer = build_validation_fallback(validation, query_mode)
        elif query_mode == "article_lookup" and has_exact_article_match:
            target_article = requested_articles[0]
            final_answer = _format_article_lookup_answer(target_article, exact_article_text)
            validation = {"ok": True, "reason": "exact_article_lookup", "invalid_articles": []}
        else:
            try:
                draft_answer = _invoke_reasoner_with_backoff(
                    runtime=runtime,
                    query=query,
                    context_text=context_text,
                    max_attempts=4,
                )
            except Exception as exc:
                draft_answer = ""
                validation = {
                    "ok": False,
                    "reason": f"reasoner_error:{str(exc)[:160]}",
                    "invalid_articles": [],
                }
            draft_answer = runtime.engine._remove_chinese_characters(draft_answer)
            if not str(draft_answer or "").strip():
                if validation.get("reason") == "not_run":
                    validation = {
                        "ok": False,
                        "reason": "empty answer from reasoner",
                        "invalid_articles": [],
                    }
                final_answer = normalize_high_risk_fact_answer(
                    answer="",
                    user_input=query,
                    documents=docs,
                ) or build_extractive_fallback_answer(
                    user_input=query,
                    documents=docs,
                ) or build_insufficient_context_response(
                    query,
                    query_mode,
                    retrieval_check,
                    failure_cause="model",
                )
                fallback_validation = validate_answer_against_context(
                    answer=final_answer,
                    documents=docs,
                    query_mode=query_mode,
                )
                if fallback_validation.get("ok", False):
                    validation = fallback_validation
                draft_answer = ""
            else:
                contract_answer = enforce_citation_contract(
                    answer=draft_answer,
                    user_input=query,
                    documents=docs,
                    query_mode=query_mode,
                )
                validation = validate_answer_against_context(
                    answer=contract_answer,
                    documents=docs,
                    query_mode=query_mode,
                )
                if validation["ok"]:
                    final_answer = contract_answer
                else:
                    repaired_answer = repair_answer_citations(
                        answer=contract_answer,
                        user_input=query,
                        documents=docs,
                        query_mode=query_mode,
                    )
                    repaired_validation = validate_answer_against_context(
                        answer=repaired_answer,
                        documents=docs,
                        query_mode=query_mode,
                    )
                    if repaired_validation.get("ok", False):
                        final_answer = repaired_answer
                        validation = repaired_validation
                    else:
                        final_answer = build_validation_fallback(validation, query_mode)

    fallback_triggered = (
        used_article_resolution
        or (intent_res.intent == Intent.LEGAL and not retrieval_check.get("is_strong_enough", False))
        or (intent_res.intent == Intent.LEGAL and not validation.get("ok", True))
    )
    fallback_reason = classify_fallback_reason(query_mode, retrieval_check, validation, used_article_resolution)
    cited_articles = extract_article_references(final_answer)
    if query_mode in {"article_lookup", "quote_request"} and has_exact_article_match and requested_articles:
        cited_articles = [requested_articles[0]]
    allowed_articles = set(extract_articles_from_documents(docs))
    context_mentions = {
        int(m)
        for m in re.findall(r"[Đđ]iều\s*(\d+)", context_text)
        if str(m).isdigit()
    }
    allowed_articles.update(context_mentions)
    invalid_citations = [a for a in cited_articles if a not in allowed_articles]

    expected_mode = case.get("expected_mode")
    mode_ok = (expected_mode == "fallback_refusal" and fallback_triggered) or (
        expected_mode == "grounded_legal_answer" and not fallback_triggered and intent_res.intent == Intent.LEGAL
    )
    expected_refs = set(case.get("must_reference_any_of", []))
    must_ref_ok = True if not expected_refs else bool(expected_refs.intersection(set(cited_articles)))
    must_not_hallucinate = bool(case.get("must_not_hallucinate", True))
    no_hallucinated_articles = len(invalid_citations) == 0
    runaway_check = detect_runaway_generation(final_answer)

    quote_details = []
    quote_ok = True
    if query_mode == "quote_request":
        if fallback_triggered and not has_exact_article_match:
            quote_ok = True
            quote_details.append(
                {
                    "quote_returned": final_answer,
                    "retrieved_reference_text": "",
                    "result": "refusal_without_quote",
                }
            )
        elif has_exact_article_match:
            quote_ok = normalize(final_answer) == normalize(exact_article_text)
            quote_details.append(
                {
                    "quote_returned": final_answer,
                    "retrieved_reference_text": exact_article_text,
                    "result": "exact_match" if quote_ok else "hallucinated_quote",
                }
            )
        else:
            quote_segments = _extract_quoted_segments(final_answer)
            if not quote_segments:
                quote_ok = False
            for q in quote_segments:
                status, matched_text = quote_match_status(q, context_text)
                quote_details.append(
                    {
                        "quote_returned": q,
                        "retrieved_reference_text": matched_text,
                        "result": status,
                    }
                )
                if status == "hallucinated_quote":
                    quote_ok = False

    grounded_ok = (
        validation.get("ok", True)
        and no_hallucinated_articles
        and (quote_ok if query_mode == "quote_request" else True)
        and (not runaway_check.get("is_runaway", False))
    )
    fail_reasons = []
    if invalid_citations:
        fail_reasons.append("viện dẫn điều không có trong context")
    if query_mode == "quote_request" and not quote_ok:
        fail_reasons.append("trích nguyên văn không nằm trong retrieved text")
    if fallback_triggered and expected_mode == "grounded_legal_answer":
        fail_reasons.append("retrieval/guard không đủ căn cứ để trả lời trực tiếp")
    if runaway_check.get("is_runaway", False):
        fail_reasons.append(
            f"runaway generation detected (max_ngram_repeat={runaway_check.get('max_ngram_repeat', 0)})"
        )

    ask_back = any(
        token in final_answer.lower()
        for token in ["vui lòng", "bạn có thể cho biết", "nêu rõ", "cần thêm thông tin", "xác nhận"]
    )
    overclaim = ("vi phạm luật" in final_answer.lower()) and not retrieval_check.get("is_strong_enough", False)

    return {
        "case_id": case["id"],
        "query": query,
        "execution_layer": {
            "runner_mode": "manual_pipeline_v1",
            "uses_engine_run_structured": False,
            "known_limitations": [
                "single_turn_only",
                "does_not_execute_rule_based_pre_answer_branch",
            ],
        },
        "checks": {
            "mode_ok": mode_ok,
            "must_reference_ok": must_ref_ok,
            "must_not_hallucinate_ok": (
                ((not must_not_hallucinate) or no_hallucinated_articles)
                and (not runaway_check.get("is_runaway", False))
            ),
            "no_runaway_generation_ok": not runaway_check.get("is_runaway", False),
            "grounded_ok": grounded_ok,
            "correct_refusal_on_weak_context": (expected_mode != "fallback_refusal") or fallback_triggered,
        },
        "retrieval_layer": {
            "query_original": query,
            "query_mode_detected": query_mode,
            "article_lookup": query_mode == "article_lookup",
            "quote_request": query_mode == "quote_request",
            "fact_pattern": query_mode == "fact_pattern",
            "open_ended": query_mode == "open_ended",
            "top_k_chunks": retrieval_rows,
            "has_exact_article_match": retrieval_check.get("has_exact_article_match", False),
            "retrieval_guard": retrieval_check,
            "is_strong_enough": retrieval_check.get("is_strong_enough", False),
            "reason": retrieval_check.get("reason", ""),
            "exact_article_text_used": exact_article_text,
        },
        "guard_fallback_layer": {
            "passed_as_legal_answer": not fallback_triggered,
            "fallback_triggered": fallback_triggered,
            "fallback_reason": fallback_reason,
            "final_fallback_message": final_answer if fallback_triggered else "",
            "fallback_signals": {
                "not_found_exact_article_phrase": "không tìm thấy đúng điều này trong tài liệu hiện có" in final_answer.lower(),
                "not_enough_basis_phrase": "chưa đủ căn cứ để kết luận" in final_answer.lower() or "không đủ căn cứ trong tài liệu hiện có" in final_answer.lower(),
                "needs_more_facts_phrase": "cần thêm" in final_answer.lower() or "nêu rõ hơn" in final_answer.lower(),
            },
        },
        "answer_grounding_layer": {
            "draft_answer": draft_answer,
            "final_answer": final_answer,
            "cited_articles": cited_articles,
            "validator_verdict": validation.get("reason", ""),
            "citation_ok": len(invalid_citations) == 0,
            "quote_ok": quote_ok if query_mode == "quote_request" else None,
            "grounded_ok": grounded_ok,
            "fail_reasons": fail_reasons,
            "quote_comparison": quote_details if query_mode == "quote_request" else [],
        },
        "legal_behavior_layer": {
            "issue_recognition_ok": intent_res.intent == Intent.LEGAL,
            "special_trigger_missing": False,
            "used_general_instead_of_specific": False,
            "asked_back_when_needed": ask_back if fallback_triggered else True,
            "asked_back_redundantly": ask_back and not fallback_triggered,
            "overclaim_without_evidence": overclaim,
            "hard_fail_hallucinated_law_or_quote": (len(invalid_citations) > 0) or (query_mode == "quote_request" and not quote_ok),
            "runaway_generation_detected": runaway_check.get("is_runaway", False),
            "runaway_signal": runaway_check,
            "manual_review_note": "",
        },
    }


def main():
    args = build_arg_parser().parse_args()
    cases = _load_cases_payload(TEST_CASES_PATH)
    selected_ids = parse_case_ids(args.case_ids)
    if selected_ids:
        cases = [
            c for c in cases
            if c.get("id") in selected_ids or str(c.get("id", "")) in selected_ids
        ]

    runtime = init_runtime()
    results = []
    evaluations = []
    for case in cases:
        print(f"Running case #{case['id']}...")
        case_result = evaluate_case(runtime, case)
        case_eval = evaluate_case_with_rubric(case, case_result)
        case_result["evaluation"] = case_eval
        results.append(case_result)
        evaluations.append(case_eval)

    passed = 0
    for r in results:
        checks = r["checks"]
        if all(bool(v) for v in checks.values()):
            passed += 1

    report = {
        "generated_at": datetime.now().isoformat(),
        "config": {
            "db_path": DB_PATH,
            "provider": LLM_PROVIDER,
            "reasoner_model": LLM_REASONER_MODEL,
            "analyzer_model": LLM_ANALYZER_MODEL,
            "top_k": TOP_K,
            "total_cases": len(cases),
        },
        "summary": {
            "passed_cases": passed,
            "failed_cases": len(cases) - passed,
            "rubric": summarize_rubric(evaluations),
        },
        "results": results,
    }

    out_override = (args.report_path or "").strip()
    if out_override:
        out_path = Path(out_override)
    else:
        out_path = REPORT_DIR / f"legal_qa_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Report saved: {out_path}")


if __name__ == "__main__":
    main()
