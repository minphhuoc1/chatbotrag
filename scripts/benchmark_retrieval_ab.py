import os
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_TORCH", "1")
os.environ["LANGSMITH_TRACING"] = "false"

import argparse
import json
import re
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import yaml

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    from langchain_chroma import Chroma
except ImportError:
    from langchain_community.vectorstores import Chroma

from ingest import build_article_chunks, load_and_clean_pdfs
from retrieval import build_runtime_retriever, retrieve_documents, retrieve_exact_article
from src.legal_chatbot.config import (
    DATA_DIR,
    DB_PATH,
    EMBED_MODEL,
    RETRIEVAL_ENABLE_DETERMINISTIC_ARTICLE_BRANCH,
    RETRIEVAL_ENABLE_LEXICAL,
    RETRIEVAL_ENABLE_METADATA_BOOST,
    RETRIEVAL_ENABLE_RERANKER,
    RETRIEVAL_ENABLE_STRATEGY_ROUTER,
    TEST_CASES_PATH,
    TOP_K,
)
from src.legal_chatbot.embeddings import create_embeddings, get_embedding_runtime_device
from src.legal_chatbot.policy import extract_articles_from_documents, suggest_target_articles

REPORT_DIR = ROOT_DIR / "reports" / "benchmarks"
REPORT_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class BenchmarkRuntime:
    vector_db: object
    retriever: object
    backend: str
    chunk_count: int
    embed_device: str


def _to_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name, "1" if default else "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _ensure_gpu_embed_env() -> str:
    explicit = os.getenv("LEGAL_CHATBOT_EMBED_DEVICE", "").strip().lower()
    if explicit and explicit != "auto":
        return explicit
    try:
        import torch  # pylint: disable=import-outside-toplevel
    except Exception:
        return explicit or "auto"
    if torch.cuda.is_available():
        os.environ["LEGAL_CHATBOT_EMBED_DEVICE"] = "cuda"
        return "cuda"
    return explicit or "auto"


def _load_cases() -> List[Dict]:
    payload = yaml.safe_load(Path(TEST_CASES_PATH).read_text(encoding="utf-8"))
    return list(payload.get("cases", []))


def _build_memory_vector_db(embeddings):
    documents = load_and_clean_pdfs(DATA_DIR)
    chunks, parent_docs, article_parent_index, article_related_index = build_article_chunks(
        documents,
        include_parent=True,
    )
    vector_db = Chroma.from_documents(documents=chunks, embedding=embeddings)
    retriever = build_runtime_retriever(
        vector_db=vector_db,
        k=TOP_K,
        parent_docs=parent_docs,
        article_parent_index=article_parent_index,
        article_related_index=article_related_index,
    )
    return vector_db, retriever, len(chunks), "memory"


def _init_runtime() -> BenchmarkRuntime:
    embeddings = create_embeddings(EMBED_MODEL)
    embed_device = get_embedding_runtime_device(embeddings)

    try:
        vector_db = Chroma(persist_directory=DB_PATH, embedding_function=embeddings)
        count = vector_db._collection.count()
        retriever = build_runtime_retriever(vector_db=vector_db, k=TOP_K)
        if count <= 0:
            raise RuntimeError("persistent DB has zero chunks")
        return BenchmarkRuntime(
            vector_db=vector_db,
            retriever=retriever,
            backend="persistent",
            chunk_count=count,
            embed_device=embed_device,
        )
    except Exception as exc:
        print(f"[WARN] persistent vector DB failed: {exc}. Fallback to memory backend.")
        vector_db, retriever, count, backend = _build_memory_vector_db(embeddings)
        return BenchmarkRuntime(
            vector_db=vector_db,
            retriever=retriever,
            backend=backend,
            chunk_count=count,
            embed_device=embed_device,
        )


def _doc_key(doc) -> tuple:
    meta = doc.metadata or {}
    return (
        meta.get("chunk_id"),
        meta.get("doc_id"),
        meta.get("article_number", meta.get("dieu_so")),
        (doc.page_content or "")[:120],
    )


def _dedup_docs(docs: list) -> list:
    out = []
    seen = set()
    for d in docs:
        key = _doc_key(d)
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    return out


def _rank_of_expected_article(docs: list, expected_articles: set[int]) -> int | None:
    if not expected_articles:
        return None
    for idx, doc in enumerate(docs, 1):
        meta = doc.metadata or {}
        raw = meta.get("article_number", meta.get("dieu_so"))
        if raw is None:
            continue
        raw_str = str(raw).strip()
        if raw_str.isdigit() and int(raw_str) in expected_articles:
            return idx
    return None


def _enrich_docs_with_hints(query: str, docs: list, runtime: BenchmarkRuntime) -> list:
    vector_db = getattr(runtime.retriever, "vectorstore", None) or runtime.vector_db
    if vector_db is None:
        return docs

    matched_articles = set(extract_articles_from_documents(docs))
    boosted = list(docs)
    for target_article in suggest_target_articles(query):
        if target_article in matched_articles:
            continue
        extra_docs = retrieve_exact_article(
            article_number=target_article,
            vector_db=vector_db,
            retriever=runtime.retriever,
            limit=6,
        )
        if extra_docs:
            boosted = extra_docs[:2] + boosted
            matched_articles.add(target_article)
    return _dedup_docs(boosted)


def run_single(label: str, output: Path) -> Dict:
    forced_embed = _ensure_gpu_embed_env()
    runtime = _init_runtime()
    cases = _load_cases()

    case_rows = []
    latencies = []
    hit_values = []
    recall_values = []
    rr_values = []

    for case in cases:
        case_id = int(case.get("id", -1))
        query = str(case.get("query", "")).strip()
        expected_refs = {
            int(x) for x in case.get("must_reference_any_of", [])
            if str(x).isdigit()
        }

        t0 = time.perf_counter()
        docs = retrieve_documents(
            user_input=query,
            retriever=runtime.retriever,
            k=TOP_K,
            semantic_query=query,
        )
        docs = _enrich_docs_with_hints(query, docs, runtime)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        latencies.append(elapsed_ms)

        retrieved_articles = set(extract_articles_from_documents(docs))
        rank = _rank_of_expected_article(docs, expected_refs)
        recall = (
            len(expected_refs.intersection(retrieved_articles)) / len(expected_refs)
            if expected_refs else None
        )
        hit = bool(expected_refs.intersection(retrieved_articles)) if expected_refs else None
        rr = (1.0 / rank) if rank else 0.0
        if expected_refs:
            hit_values.append(1.0 if hit else 0.0)
            recall_values.append(recall if recall is not None else 0.0)
            rr_values.append(rr)

        case_rows.append(
            {
                "id": case_id,
                "query": query,
                "expected_articles": sorted(expected_refs),
                "retrieved_articles": sorted(retrieved_articles),
                "hit_at_k": hit,
                "recall_at_k": recall,
                "first_relevant_rank": rank,
                "rr": rr if expected_refs else None,
                "latency_ms": round(elapsed_ms, 2),
            }
        )

    latency_mean = statistics.mean(latencies) if latencies else 0.0
    latency_p50 = statistics.median(latencies) if latencies else 0.0
    latency_p95 = (
        sorted(latencies)[max(0, min(len(latencies) - 1, int(len(latencies) * 0.95) - 1))]
        if latencies else 0.0
    )
    summary = {
        "total_cases": len(cases),
        "evaluated_cases_with_expected_refs": len(hit_values),
        "hit_at_k": round(statistics.mean(hit_values), 4) if hit_values else 0.0,
        "mean_recall_at_k": round(statistics.mean(recall_values), 4) if recall_values else 0.0,
        "mrr_at_k": round(statistics.mean(rr_values), 4) if rr_values else 0.0,
        "latency_ms": {
            "mean": round(latency_mean, 2),
            "p50": round(latency_p50, 2),
            "p95": round(latency_p95, 2),
        },
    }

    payload = {
        "label": label,
        "generated_at": datetime.now().isoformat(),
        "config": {
            "top_k": TOP_K,
            "embed_model": EMBED_MODEL,
            "embed_device_runtime": runtime.embed_device,
            "embed_device_forced_env": forced_embed,
            "vector_backend": runtime.backend,
            "chunk_count": runtime.chunk_count,
            "retrieval_flags": {
                "strategy_router": RETRIEVAL_ENABLE_STRATEGY_ROUTER,
                "lexical": RETRIEVAL_ENABLE_LEXICAL,
                "deterministic_article_branch": RETRIEVAL_ENABLE_DETERMINISTIC_ARTICLE_BRANCH,
                "reranker": RETRIEVAL_ENABLE_RERANKER,
                "metadata_boost": RETRIEVAL_ENABLE_METADATA_BOOST,
            },
        },
        "summary": summary,
        "cases": case_rows,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[BENCH] single report saved: {output}")
    print(json.dumps(summary, ensure_ascii=False))
    return payload


def _metric_delta(after: float, before: float) -> float:
    return round(after - before, 4)


def run_compare(output: Path) -> Dict:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    single_before = REPORT_DIR / f"retrieval_single_before_p0_{stamp}.json"
    single_after = REPORT_DIR / f"retrieval_single_after_p0_{stamp}.json"

    script_path = Path(__file__).resolve()
    scenarios = [
        {
            "label": "before_p0",
            "output": single_before,
            "env": {
                "LEGAL_CHATBOT_RETRIEVAL_ENABLE_STRATEGY_ROUTER": "0",
                "LEGAL_CHATBOT_RETRIEVAL_ENABLE_LEXICAL": "0",
                "LEGAL_CHATBOT_RETRIEVAL_ENABLE_DETERMINISTIC_ARTICLE_BRANCH": "0",
                "LEGAL_CHATBOT_RETRIEVAL_ENABLE_RERANKER": "0",
                "LEGAL_CHATBOT_RETRIEVAL_ENABLE_METADATA_BOOST": "0",
            },
        },
        {
            "label": "after_p0",
            "output": single_after,
            "env": {
                "LEGAL_CHATBOT_RETRIEVAL_ENABLE_STRATEGY_ROUTER": "1",
                "LEGAL_CHATBOT_RETRIEVAL_ENABLE_LEXICAL": "1",
                "LEGAL_CHATBOT_RETRIEVAL_ENABLE_DETERMINISTIC_ARTICLE_BRANCH": "1",
                "LEGAL_CHATBOT_RETRIEVAL_ENABLE_RERANKER": "0",
                "LEGAL_CHATBOT_RETRIEVAL_ENABLE_METADATA_BOOST": "0",
            },
        },
    ]

    for scenario in scenarios:
        env = os.environ.copy()
        env.update(scenario["env"])
        cmd = [
            sys.executable,
            str(script_path),
            "--mode",
            "single",
            "--label",
            scenario["label"],
            "--output",
            str(scenario["output"]),
        ]
        subprocess.run(cmd, cwd=str(ROOT_DIR), env=env, check=True)

    before_payload = json.loads(single_before.read_text(encoding="utf-8"))
    after_payload = json.loads(single_after.read_text(encoding="utf-8"))
    b = before_payload["summary"]
    a = after_payload["summary"]

    comparison = {
        "generated_at": datetime.now().isoformat(),
        "before_report": str(single_before),
        "after_report": str(single_after),
        "before_summary": b,
        "after_summary": a,
        "delta": {
            "hit_at_k": _metric_delta(a["hit_at_k"], b["hit_at_k"]),
            "mean_recall_at_k": _metric_delta(a["mean_recall_at_k"], b["mean_recall_at_k"]),
            "mrr_at_k": _metric_delta(a["mrr_at_k"], b["mrr_at_k"]),
            "latency_mean_ms": _metric_delta(a["latency_ms"]["mean"], b["latency_ms"]["mean"]),
            "latency_p95_ms": _metric_delta(a["latency_ms"]["p95"], b["latency_ms"]["p95"]),
        },
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[BENCH] compare report saved: {output}")
    print(json.dumps(comparison["delta"], ensure_ascii=False))
    return comparison


def main():
    parser = argparse.ArgumentParser(description="Retrieval benchmark: before/after P0 comparison")
    parser.add_argument("--mode", choices=["single", "compare"], default="compare")
    parser.add_argument("--label", default="single_run")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    if args.output:
        out_path = Path(args.output)
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = "compare" if args.mode == "compare" else args.label
        out_path = REPORT_DIR / f"retrieval_benchmark_{suffix}_{stamp}.json"

    if args.mode == "single":
        run_single(label=args.label, output=out_path)
    else:
        run_compare(output=out_path)


if __name__ == "__main__":
    main()
