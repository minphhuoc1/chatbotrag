# -*- coding: utf-8 -*-
"""
retrieval.py — Retrieval helpers với ưu tiên exact article lookup trước semantic retrieval.
Hỗ trợ chế độ Parent-Child Retriever (LangChain) với fallback tương thích backend cũ.
"""

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import List

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_classic.retrievers import ParentDocumentRetriever
from langchain_classic.storage import InMemoryStore, LocalFileStore, create_kv_docstore

from .config import (
    DB_PATH,
    MAX_ARTICLE_NUMBER,
    RETRIEVAL_ENABLE_DETERMINISTIC_ARTICLE_BRANCH,
    RETRIEVAL_ENABLE_LEXICAL,
    RETRIEVAL_ENABLE_METADATA_BOOST,
    RETRIEVAL_ENABLE_RERANKER,
    RETRIEVAL_ENABLE_STRATEGY_ROUTER,
    RETRIEVAL_MAX_QUERY_VARIANTS,
    RETRIEVAL_RERANK_CANDIDATE_POOL,
    RETRIEVAL_RRF_K,
)
from .strategy_router import StrategyDecision, select_retrieval_strategy

_PARENT_INDEX_CACHE: dict[str, dict] = {}
_PARENT_DOCSTORE_CACHE: dict[str, object] = {}
_LEXICAL_INDEX_CACHE: dict[str, "LexicalIndex"] = {}
_DEFAULT_RRF_K = RETRIEVAL_RRF_K

# Rerank weights (heuristic, centralized for easier ablation/tuning).
RERANK_W_RRF = 100.0
RERANK_W_LEXICAL = 0.55
RERANK_W_OVERLAP = 3.5
META_BOOST_EXACT_ARTICLE = 6.0
META_BOOST_HINTED_ARTICLE = 2.2
META_BOOST_RELATED_ARTICLE = 0.9
META_BOOST_DOC_NUMBER = 1.5
META_BOOST_LOOKUP_STRATEGY = 0.4
META_BOOST_QUOTE_PARENT = 1.2


@dataclass
class LexicalIndex:
    documents: list[str]
    metadatas: list[dict]
    token_freqs: list[Counter]
    doc_lengths: list[int]
    doc_freq: Counter
    avg_doc_len: float
    size: int


def _attach_runtime_attr(target, name: str, value):
    try:
        setattr(target, name, value)
        return
    except Exception:
        pass

    # Pydantic models có thể chặn setattr với field không khai báo.
    object.__setattr__(target, name, value)


def _extract_article_number(user_input: str) -> int | None:
    m = re.search(r"[Đđ]iều\s*(\d+)", user_input)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _derive_parent_store_dir(db_path: str) -> str:
    return f"{db_path}_parent_store"


def _derive_parent_index_path(db_path: str) -> str:
    return f"{db_path}_parent_index.json"


def _resolve_db_path(vector_db=None) -> str:
    if vector_db is not None:
        for attr in ("_persist_directory", "persist_directory"):
            value = getattr(vector_db, attr, None)
            if isinstance(value, str) and value.strip():
                return value
    return DB_PATH


def _load_parent_index(db_path: str) -> dict:
    if db_path in _PARENT_INDEX_CACHE:
        return _PARENT_INDEX_CACHE[db_path]

    index_path = Path(_derive_parent_index_path(db_path))
    if not index_path.exists():
        _PARENT_INDEX_CACHE[db_path] = {}
        return {}

    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    _PARENT_INDEX_CACHE[db_path] = payload
    return payload


def _load_parent_docstore(db_path: str):
    if db_path in _PARENT_DOCSTORE_CACHE:
        return _PARENT_DOCSTORE_CACHE[db_path]

    parent_store_dir = Path(_derive_parent_store_dir(db_path))
    if not parent_store_dir.exists():
        _PARENT_DOCSTORE_CACHE[db_path] = None
        return None

    try:
        byte_store = LocalFileStore(str(parent_store_dir))
        docstore = create_kv_docstore(byte_store)
    except Exception:
        docstore = None
    _PARENT_DOCSTORE_CACHE[db_path] = docstore
    return docstore


def _get_parent_sources(retriever=None, vector_db=None):
    if retriever is not None:
        index = getattr(retriever, "parent_index", None) or getattr(retriever, "_parent_index", None)
        docstore = getattr(retriever, "parent_docstore", None) or getattr(retriever, "_parent_docstore", None)
        if isinstance(index, dict) and docstore is not None:
            return index, docstore

    db_path = _resolve_db_path(vector_db)
    index = _load_parent_index(db_path)
    docstore = _load_parent_docstore(db_path)
    if not isinstance(index, dict) or docstore is None:
        return {}, None
    return index, docstore


def _dedup_documents(documents: list) -> list:
    deduped = []
    seen = set()
    for doc in documents:
        key = (
            doc.metadata.get("doc_id"),
            doc.metadata.get("article_number"),
            doc.metadata.get("dieu_so"),
            doc.metadata.get("chunk_id"),
            doc.metadata.get("source_file"),
            doc.page_content[:120],
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(doc)
    return deduped


def _parse_related_articles(raw_value) -> list[int]:
    if raw_value is None:
        return []
    values = []
    if isinstance(raw_value, list):
        values = raw_value
    elif isinstance(raw_value, int):
        values = [raw_value]
    elif isinstance(raw_value, str):
        text = raw_value.strip()
        if not text:
            return []
        if text.startswith("[") and text.endswith("]"):
            try:
                decoded = json.loads(text)
                if isinstance(decoded, list):
                    values = decoded
            except Exception:
                values = re.findall(r"\d+", text)
        else:
            values = re.findall(r"\d+", text)
    parsed = []
    seen = set()
    for item in values:
        if isinstance(item, str) and item.isdigit():
            item = int(item)
        if not isinstance(item, int):
            continue
        if item < 1 or item > MAX_ARTICLE_NUMBER or item in seen:
            continue
        seen.add(item)
        parsed.append(item)
    return parsed


def _tokenize_for_lexical(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", (text or "").lower()).strip()
    if not normalized:
        return []
    base_tokens = [tok for tok in re.findall(r"[\wÀ-ỹ]+", normalized) if len(tok) >= 2]
    if not base_tokens:
        return []
    # Add simple bigrams for Vietnamese legal phrases (e.g., "người_lao", "lao_động")
    # to reduce lexical fragmentation on compound terms.
    bigrams = [f"{base_tokens[i]}_{base_tokens[i + 1]}" for i in range(len(base_tokens) - 1)]
    return base_tokens + bigrams


def _build_lexical_index(vector_db) -> LexicalIndex | None:
    if vector_db is None:
        return None
    try:
        raw_payload = vector_db._collection.get(include=["documents", "metadatas"])
    except Exception:
        return None

    raw_docs = raw_payload.get("documents", []) or []
    raw_meta = raw_payload.get("metadatas", []) or []
    documents = [str(doc or "") for doc in raw_docs]
    metadatas = [meta or {} for meta in raw_meta]
    if not documents:
        return None
    if len(metadatas) < len(documents):
        metadatas.extend({} for _ in range(len(documents) - len(metadatas)))

    token_freqs: list[Counter] = []
    doc_lengths: list[int] = []
    doc_freq: Counter = Counter()
    for text in documents:
        freq = Counter(_tokenize_for_lexical(text))
        token_freqs.append(freq)
        length = sum(freq.values())
        doc_lengths.append(length)
        for token in freq.keys():
            doc_freq[token] += 1

    avg_doc_len = sum(doc_lengths) / len(doc_lengths) if doc_lengths else 1.0
    return LexicalIndex(
        documents=documents,
        metadatas=metadatas,
        token_freqs=token_freqs,
        doc_lengths=doc_lengths,
        doc_freq=doc_freq,
        avg_doc_len=max(avg_doc_len, 1.0),
        size=len(documents),
    )


def _get_lexical_index(vector_db) -> LexicalIndex | None:
    if vector_db is None:
        return None
    db_path = _resolve_db_path(vector_db)
    if db_path in _LEXICAL_INDEX_CACHE:
        return _LEXICAL_INDEX_CACHE[db_path]

    index = _build_lexical_index(vector_db)
    if index is None:
        return None
    _LEXICAL_INDEX_CACHE[db_path] = index
    return index


def _bm25_score(
    query_tokens: list[str],
    freq: Counter,
    doc_len: int,
    index: LexicalIndex,
    k1: float = 1.5,
    b: float = 0.75,
) -> float:
    if not query_tokens or not freq:
        return 0.0

    score = 0.0
    n_docs = max(index.size, 1)
    for token in query_tokens:
        tf = freq.get(token, 0)
        if tf <= 0:
            continue
        df = index.doc_freq.get(token, 0)
        idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
        denom = tf + k1 * (1 - b + b * (doc_len / index.avg_doc_len))
        score += idf * ((tf * (k1 + 1)) / max(denom, 1e-9))
    return score


def _lexical_search(vector_db, query: str, k: int = 6) -> list:
    if not RETRIEVAL_ENABLE_LEXICAL:
        return []
    index = _get_lexical_index(vector_db)
    if index is None:
        return []
    query_tokens = _tokenize_for_lexical(query)
    if not query_tokens:
        return []

    ranked: list[tuple[float, int]] = []
    for idx, freq in enumerate(index.token_freqs):
        score = _bm25_score(query_tokens, freq, index.doc_lengths[idx], index)
        if score > 0:
            ranked.append((score, idx))

    if not ranked:
        return []

    ranked.sort(key=lambda item: item[0], reverse=True)
    docs = []
    for score, idx in ranked[:k]:
        meta = dict(index.metadatas[idx] or {})
        meta["lexical_score"] = float(score)
        docs.append(Document(page_content=index.documents[idx], metadata=meta))
    return docs


def _doc_fingerprint(doc) -> tuple:
    meta = doc.metadata or {}
    return (
        meta.get("doc_id"),
        meta.get("chunk_id"),
        meta.get("article_number", meta.get("dieu_so")),
        meta.get("source_file"),
        (doc.page_content or "")[:120],
    )


def _rrf_merge(ranked_lists: list[list], k: int = _DEFAULT_RRF_K) -> list:
    if not ranked_lists:
        return []

    fused_scores: dict[tuple, float] = {}
    doc_by_key: dict[tuple, Document] = {}

    for doc_list in ranked_lists:
        for rank, doc in enumerate(doc_list):
            key = _doc_fingerprint(doc)
            fused_scores[key] = fused_scores.get(key, 0.0) + 1.0 / (k + rank + 1)
            if key not in doc_by_key:
                doc_by_key[key] = doc

    ordered_keys = sorted(fused_scores.keys(), key=lambda key: fused_scores[key], reverse=True)
    merged_docs = []
    for key in ordered_keys:
        doc = doc_by_key[key]
        meta = dict(doc.metadata or {})
        meta["hybrid_rrf_score"] = round(fused_scores[key], 6)
        merged_docs.append(Document(page_content=doc.page_content, metadata=meta))
    return merged_docs


def _build_query_variants(user_input: str, semantic_query: str | None = None, max_variants: int = 3) -> list[str]:
    base = (semantic_query or "").strip() or user_input
    variants = [base]

    article = _extract_article_number(user_input)
    if article:
        variants.append(f"Điều {article} bộ luật lao động")

    normalized_user = re.sub(r"\s+", " ", (user_input or "").strip())
    if normalized_user and normalized_user not in variants:
        variants.append(normalized_user)

    # Light split for comparison intents.
    lowered = normalized_user.lower()
    if any(marker in lowered for marker in ("khác gì", "so với", "so sánh", "phân biệt")):
        parts = re.split(r"\b(?:và|hay|so với)\b", normalized_user, flags=re.IGNORECASE)
        compact = " ".join(p.strip() for p in parts if p.strip())
        if compact and compact not in variants:
            variants.append(compact)

    deduped = []
    seen = set()
    for q in variants:
        norm = q.lower().strip()
        if not norm or norm in seen:
            continue
        seen.add(norm)
        deduped.append(q)
        if len(deduped) >= max_variants:
            break
    return deduped


def _safe_suggest_target_articles(user_input: str) -> list[int]:
    try:
        from .policy import suggest_target_articles  # local import to avoid heavy/cyclic initialization
    except Exception:
        return []
    try:
        return suggest_target_articles(user_input)
    except Exception:
        return []


def _extract_doc_number_hint(user_input: str) -> str:
    text = (user_input or "").lower()
    m = re.search(r"\b(\d+/\d{4}/[a-zđ0-9\-]+)\b", text)
    return m.group(1).strip() if m else ""


def _token_overlap_ratio(query: str, content: str) -> float:
    q_tokens = set(_tokenize_for_lexical(query))
    if not q_tokens:
        return 0.0
    d_tokens = set(_tokenize_for_lexical(content))
    if not d_tokens:
        return 0.0
    return len(q_tokens.intersection(d_tokens)) / max(len(q_tokens), 1)


def _metadata_boost_score(
    doc: Document,
    user_input: str,
    article_number: int | None,
    hinted_articles: set[int],
    doc_number_hint: str,
    strategy_name: str,
) -> float:
    if not RETRIEVAL_ENABLE_METADATA_BOOST:
        return 0.0

    meta = doc.metadata or {}
    score = 0.0

    raw_article = meta.get("article_number", meta.get("dieu_so"))
    article = int(raw_article) if str(raw_article).isdigit() else None

    if article_number and article == article_number:
        score += META_BOOST_EXACT_ARTICLE
    if article is not None and article in hinted_articles:
        score += META_BOOST_HINTED_ARTICLE

    related_raw = (
        meta.get("related_articles")
        or meta.get("related_articles_csv")
        or meta.get("related_articles_json")
    )
    related_articles = set(_parse_related_articles(related_raw))
    if related_articles and hinted_articles.intersection(related_articles):
        score += META_BOOST_RELATED_ARTICLE

    if doc_number_hint:
        doc_fields = " ".join(
            str(meta.get(k, "") or "")
            for k in ("source_file", "law_name", "canonical_doc_id")
        ).lower()
        if doc_number_hint in doc_fields:
            score += META_BOOST_DOC_NUMBER

    if strategy_name == "lookup" and article is not None:
        score += META_BOOST_LOOKUP_STRATEGY

    text = (user_input or "").lower()
    if "trích nguyên văn" in text and meta.get("chunk_type") == "article_parent":
        score += META_BOOST_QUOTE_PARENT

    return score


def _rerank_documents(
    docs: list,
    user_input: str,
    semantic_query: str,
    article_number: int | None,
    strategy_name: str,
    limit: int,
) -> list:
    if not docs:
        return []
    if not RETRIEVAL_ENABLE_RERANKER:
        return docs[:limit]

    hinted_articles = set(_safe_suggest_target_articles(user_input))
    doc_number_hint = _extract_doc_number_hint(user_input)
    query_for_overlap = (semantic_query or "").strip() or user_input

    scored: list[tuple[float, Document]] = []
    for doc in docs:
        meta = doc.metadata or {}
        rrf_score = float(meta.get("hybrid_rrf_score", 0.0) or 0.0)
        lexical_score = float(meta.get("lexical_score", 0.0) or 0.0)
        overlap_ratio = _token_overlap_ratio(query_for_overlap, doc.page_content or "")
        meta_boost = _metadata_boost_score(
            doc=doc,
            user_input=user_input,
            article_number=article_number,
            hinted_articles=hinted_articles,
            doc_number_hint=doc_number_hint,
            strategy_name=strategy_name,
        )

        # Deterministic hybrid rerank score:
        # - rrf_score ưu tiên thống nhất nhiều retriever
        # - lexical_score giữ lợi thế exact legal phrase
        # - overlap_ratio giữ mức relevance cơ bản
        # - meta_boost tăng ưu tiên Điều mục tiêu / metadata phù hợp
        score = (
            (rrf_score * RERANK_W_RRF)
            + (lexical_score * RERANK_W_LEXICAL)
            + (overlap_ratio * RERANK_W_OVERLAP)
            + meta_boost
        )
        enriched_meta = dict(meta)
        enriched_meta["rerank_score"] = round(score, 6)
        scored.append((score, Document(page_content=doc.page_content, metadata=enriched_meta)))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [doc for _, doc in scored[:limit]]


def _hybrid_semantic_lexical_search(
    retriever,
    query: str,
    vector_db,
    k: int,
) -> list:
    try:
        semantic_docs = retriever.invoke(query) if retriever is not None else []
    except Exception:
        semantic_docs = []
    lexical_docs = _lexical_search(vector_db=vector_db, query=query, k=max(k, 6))
    if lexical_docs and semantic_docs:
        merged = _rrf_merge([semantic_docs, lexical_docs])
        return merged[: max(k, 6)]
    if semantic_docs:
        return semantic_docs[: max(k, 6)]
    return lexical_docs[: max(k, 6)]


def _collect_related_articles_from_docs(docs: list, exclude: set | None = None, max_articles: int = 6) -> list[int]:
    exclude = exclude or set()
    ordered = []
    seen = set()
    for doc in docs:
        meta = doc.metadata or {}
        raw_related = (
            meta.get("related_articles")
            or meta.get("related_articles_csv")
            or meta.get("related_articles_json")
        )
        for article in _parse_related_articles(raw_related):
            if article in exclude or article in seen:
                continue
            seen.add(article)
            ordered.append(article)
            if len(ordered) >= max_articles:
                return ordered
    return ordered


def _expand_with_related_articles(
    docs: list,
    retriever=None,
    vector_db=None,
    limit: int = 2,
    exclude: set | None = None,
) -> list:
    if limit <= 0:
        return []
    if vector_db is None and retriever is not None:
        vector_db = getattr(retriever, "vectorstore", None)
    if retriever is None and vector_db is None:
        return []

    related_articles = _collect_related_articles_from_docs(
        docs,
        exclude=exclude,
        max_articles=max(limit * 2, 4),
    )
    expanded = []
    for article in related_articles:
        extra_docs = retrieve_exact_article(
            article_number=article,
            vector_db=vector_db,
            retriever=retriever,
            limit=2,
        )
        if not extra_docs:
            continue
        expanded.extend(extra_docs[:1])
        if len(expanded) >= limit:
            break
    return expanded


def build_runtime_retriever(
    vector_db,
    k: int = 6,
    parent_docs: list | None = None,
    article_parent_index: dict | None = None,
    article_related_index: dict | None = None,
):
    """
    Ưu tiên ParentDocumentRetriever nếu đã có parent docstore/index.
    Fallback về vector_db.as_retriever khi chưa migrate dữ liệu.
    """
    memory_parent_docs = parent_docs or []
    memory_parent_index = article_parent_index or {}
    memory_related_index = article_related_index or {}
    if memory_parent_docs and memory_parent_index:
        mem_store = InMemoryStore()
        docstore = create_kv_docstore(mem_store)
        kv_pairs = []
        for parent_doc in memory_parent_docs:
            doc_id = (parent_doc.metadata or {}).get("doc_id")
            if not doc_id:
                continue
            kv_pairs.append((str(doc_id), parent_doc))
        if kv_pairs:
            docstore.mset(kv_pairs)
            index = {
                "article_to_doc_ids": memory_parent_index,
                "article_related_articles": memory_related_index,
            }
            retriever = ParentDocumentRetriever(
                vectorstore=vector_db,
                docstore=docstore,
                child_splitter=RecursiveCharacterTextSplitter(chunk_size=400, chunk_overlap=40),
                search_kwargs={"k": k},
            )
            _attach_runtime_attr(retriever, "_parent_index", index)
            _attach_runtime_attr(retriever, "_parent_docstore", docstore)
            _attach_runtime_attr(retriever, "retrieval_mode", "parent_child_memory")
            return retriever

    db_path = _resolve_db_path(vector_db)
    index = _load_parent_index(db_path)
    docstore = _load_parent_docstore(db_path)

    article_to_doc_ids = {}
    if isinstance(index, dict):
        article_to_doc_ids = index.get("article_to_doc_ids", {}) or {}

    if docstore is not None and article_to_doc_ids:
        retriever = ParentDocumentRetriever(
            vectorstore=vector_db,
            docstore=docstore,
            child_splitter=RecursiveCharacterTextSplitter(chunk_size=400, chunk_overlap=40),
            search_kwargs={"k": k},
        )
        _attach_runtime_attr(retriever, "_parent_index", index)
        _attach_runtime_attr(retriever, "_parent_docstore", docstore)
        _attach_runtime_attr(retriever, "retrieval_mode", "parent_child")
        return retriever

    retriever = vector_db.as_retriever(search_kwargs={"k": k})
    _attach_runtime_attr(retriever, "retrieval_mode", "child_only")
    return retriever


def _retrieve_parent_article_docs(article_number: int, retriever=None, vector_db=None, limit: int = 5) -> list:
    index, docstore = _get_parent_sources(retriever=retriever, vector_db=vector_db)
    if not index or docstore is None:
        return []

    article_to_doc_ids = index.get("article_to_doc_ids", {}) if isinstance(index, dict) else {}
    doc_ids = article_to_doc_ids.get(str(article_number), [])
    if not doc_ids:
        return []

    docs = docstore.mget([str(doc_id) for doc_id in doc_ids])
    resolved = [d for d in docs if isinstance(d, Document)]
    resolved = _dedup_documents(resolved)
    return resolved[:limit]


def retrieve_exact_article(
    article_number: int,
    vector_db=None,
    retriever=None,
    limit: int = 5,
) -> list:
    """
    Exact article retrieval ưu tiên parent docs (nếu có), sau đó fallback child chunks.
    """
    if article_number <= 0:
        return []

    parent_docs = _retrieve_parent_article_docs(
        article_number=article_number,
        retriever=retriever,
        vector_db=vector_db,
        limit=limit,
    )
    if parent_docs:
        return parent_docs[:limit]

    if vector_db is None and retriever is not None:
        vector_db = getattr(retriever, "vectorstore", None)
    if vector_db is None:
        return []

    # 1) Query metadata article_number
    results = vector_db._collection.get(
        where={"article_number": article_number},
        include=["documents", "metadatas"],
    )
    docs = []
    for doc_text, meta in zip(results.get("documents", []), results.get("metadatas", [])):
        docs.append(Document(page_content=doc_text, metadata=meta or {}))

    # 2) Fallback metadata dieu_so (legacy)
    if len(docs) < limit:
        legacy = vector_db._collection.get(
            where={"dieu_so": str(article_number)},
            include=["documents", "metadatas"],
        )
        for doc_text, meta in zip(legacy.get("documents", []), legacy.get("metadatas", [])):
            docs.append(Document(page_content=doc_text, metadata=meta or {}))

    # 3) Fallback content contains "Điều <N>"
    if len(docs) < limit:
        sem = vector_db.similarity_search(f"Điều {article_number}", k=max(limit * 2, 8))
        for d in sem:
            if re.search(rf"[Đđ]iều\s*{article_number}\b", d.page_content):
                docs.append(d)

    docs = _dedup_documents(docs)
    return docs[:limit]


def retrieve_documents(user_input: str, retriever, k: int = 6, semantic_query: str | None = None) -> list:
    """
    P0 retrieval flow:
    1) Strategy router chọn nhánh lookup/semantic/multi_query theo feature.
    2) Lookup deterministic chạy trước semantic path.
    3) Semantic path dùng hybrid (vector + lexical) và RRF merge.
    """
    strategy = select_retrieval_strategy(user_input)
    if not RETRIEVAL_ENABLE_STRATEGY_ROUTER:
        strategy = StrategyDecision(
            primary_strategy="semantic",
            ordered_strategies=("semantic",),
            scores={"lookup": 0.0, "semantic": 1.0, "multi_query": 0.0},
            features=strategy.features,
        )
    article_number = _extract_article_number(user_input)
    vector_db = getattr(retriever, "vectorstore", None)
    collected: list[Document] = []

    run_lookup = (
        RETRIEVAL_ENABLE_DETERMINISTIC_ARTICLE_BRANCH
        and (strategy.primary_strategy == "lookup" or "lookup" in strategy.ordered_strategies)
    )
    run_semantic = "semantic" in strategy.ordered_strategies
    run_multi_query = "multi_query" in strategy.ordered_strategies

    if run_lookup and article_number:
        lookup_docs = retrieve_exact_article(
            article_number=article_number,
            vector_db=vector_db,
            retriever=retriever,
            limit=max(4, min(8, k)),
        )
        collected.extend(lookup_docs)
        if lookup_docs:
            collected.extend(
                _expand_with_related_articles(
                    docs=lookup_docs,
                    retriever=retriever,
                    vector_db=vector_db,
                    limit=max(1, min(2, k)),
                    exclude={article_number},
                )
            )
        collected = _dedup_documents(collected)

        # Deterministic short-circuit cho query tra cứu Điều/Khoản dạng thủ tục.
        if (
            strategy.primary_strategy == "lookup"
            and strategy.features.is_procedural
            and collected
        ):
            return collected[:k]

    queries = []
    base_query = (semantic_query or "").strip() or user_input
    if run_multi_query:
        queries = _build_query_variants(
            user_input=user_input,
            semantic_query=base_query,
            max_variants=max(1, RETRIEVAL_MAX_QUERY_VARIANTS),
        )
    elif run_semantic or not collected:
        queries = [base_query]

    semantic_candidates: list[Document] = []
    for query in queries:
        semantic_candidates.extend(
            _hybrid_semantic_lexical_search(
                retriever=retriever,
                query=query,
                vector_db=vector_db,
                k=max(k, 6),
            )
        )

    if semantic_candidates:
        collected.extend(semantic_candidates)
        collected = _dedup_documents(collected)

    if collected:
        rerank_limit = max(k, RETRIEVAL_RERANK_CANDIDATE_POOL)
        collected = _rerank_documents(
            docs=collected,
            user_input=user_input,
            semantic_query=base_query,
            article_number=article_number,
            strategy_name=strategy.primary_strategy,
            limit=rerank_limit,
        )

    if len(collected) < k:
        collected.extend(
            _expand_with_related_articles(
                docs=collected,
                retriever=retriever,
                vector_db=vector_db,
                limit=min(2, max(1, k - len(collected))),
                exclude={article_number} if article_number else None,
            )
        )
    collected = _dedup_documents(collected)
    collected = _rerank_documents(
        docs=collected,
        user_input=user_input,
        semantic_query=base_query,
        article_number=article_number,
        strategy_name=strategy.primary_strategy,
        limit=k,
    )
    return collected[:k]
