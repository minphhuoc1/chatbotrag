# -*- coding: utf-8 -*-
"""FastAPI adapter for the Legal Chatbot RAG engine.

This file exists so the Next.js frontend can talk to the same engine that the
Streamlit app uses, without coupling the frontend to Streamlit internals.
"""

import logging
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal

os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_TORCH", "1")

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel, Field

try:
    from langchain_chroma import Chroma
except ImportError:  # pragma: no cover - compatibility fallback
    from langchain_community.vectorstores import Chroma

from reasoning_chain import LegalReasoningEngine
from retrieval import build_runtime_retriever
from src.legal_chatbot import policy as shared_policy
from src.legal_chatbot.config import ANSWER_PROMPT_PATH, DB_PATH, EMBED_MODEL, LOGS_DIR, TOP_K
from src.legal_chatbot.embeddings import create_embeddings
from src.legal_chatbot.llm_factory import create_llm_clients

load_dotenv()
logger = logging.getLogger("legal_chatbot.api")

os.makedirs(LOGS_DIR, exist_ok=True)
if not logger.handlers:
    file_handler = logging.FileHandler(os.path.join(LOGS_DIR, "api_server.log"), encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    )
    logger.addHandler(file_handler)
logger.setLevel(logging.INFO)
logger.propagate = False


@dataclass
class Runtime:
    engine: LegalReasoningEngine
    vector_count: int


class ChatHistoryItem(BaseModel):
    role: Literal["user", "assistant", "human", "ai"]
    content: str = Field(default="")


class ChatRequest(BaseModel):
    message: str
    chat_history: list[ChatHistoryItem] = Field(default_factory=list)


def _cors_origins() -> list[str]:
    raw = os.getenv("LEGAL_CHATBOT_CORS_ORIGINS", "").strip()
    if raw:
        return [item.strip() for item in raw.split(",") if item.strip()]
    return [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:7860",
        "http://127.0.0.1:7860",
    ]


app = FastAPI(title="Legal Chatbot RAG API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_origin_regex=os.getenv(
        "LEGAL_CHATBOT_CORS_ORIGIN_REGEX",
        r"https://.*\.hf\.space|https://.*\.vercel\.app",
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@lru_cache(maxsize=1)
def get_runtime() -> Runtime:
    embeddings = create_embeddings(EMBED_MODEL)
    vector_db = Chroma(persist_directory=DB_PATH, embedding_function=embeddings)
    retriever = build_runtime_retriever(vector_db=vector_db, k=TOP_K)

    llm_clients = create_llm_clients()
    with open(ANSWER_PROMPT_PATH, "r", encoding="utf-8") as f:
        system_prompt = f.read()

    engine = LegalReasoningEngine(
        retriever,
        llm_clients.llm_json,
        llm_clients.llm_reason,
        system_prompt,
        llm_intent=llm_clients.llm_intent,
    )

    try:
        vector_count = vector_db._collection.count()
    except Exception:
        vector_count = 0

    logger.info("RAG API runtime loaded. vector_count=%s", vector_count)
    return Runtime(engine=engine, vector_count=vector_count)


def _to_langchain_history(items: list[ChatHistoryItem]) -> list[Any]:
    messages: list[Any] = []
    for item in items[-12:]:
        content = item.content.strip()
        if not content:
            continue
        if item.role in {"user", "human"}:
            messages.append(HumanMessage(content=content))
        elif item.role in {"assistant", "ai"}:
            messages.append(AIMessage(content=content))
    return messages


def _snippet(text: str, limit: int = 360) -> str:
    return re.sub(r"\s+", " ", text or "").strip()[:limit]


def _doc_to_article(doc: Any) -> dict[str, Any]:
    meta = getattr(doc, "metadata", {}) or {}
    article_number = meta.get("article_number") or meta.get("dieu_so") or "?"
    score = meta.get("score", meta.get("relevance_score"))
    try:
        score = float(score) if score is not None else None
    except (TypeError, ValueError):
        score = None

    return {
        "article_number": str(article_number),
        "article_title": meta.get("article_title") or meta.get("title") or "",
        "snippet": _snippet(getattr(doc, "page_content", "")),
        "source_file": meta.get("source_file") or meta.get("source") or "",
        "score": score,
    }


def _validation_payload(result: Any) -> dict[str, Any]:
    validation = getattr(result, "validation", None) or {}
    if "grounded" in validation:
        grounded = bool(validation.get("grounded"))
    elif "ok" in validation:
        grounded = bool(validation.get("ok"))
    else:
        grounded = bool(shared_policy.extract_article_references(getattr(result, "answer", "") or ""))

    reason = (
        validation.get("reason")
        or validation.get("error")
        or validation.get("failure_cause")
        or getattr(result, "route", "")
        or ""
    )
    return {"grounded": grounded, "reason": str(reason)}


def _citation_payload(message: str, result: Any) -> tuple[list[str], list[str], list[str]]:
    """Return all citations, primary citations, and cross-references separately."""
    answer = getattr(result, "answer", "") or ""
    all_cited = [str(num) for num in shared_policy.extract_article_references(answer)]
    docs = getattr(result, "docs", None) or []
    route = getattr(result, "route", "") or ""

    requested = [str(num) for num in shared_policy.extract_requested_articles(message)]
    retrieved = {
        str(article)
        for article in shared_policy.extract_articles_from_documents(docs)
        if article is not None
    }

    primary: list[str] = []
    if route in {"quote_direct", "article_direct"} and requested:
        primary = [num for num in requested if num in retrieved or route == "quote_direct"]
    elif docs:
        primary = [
            str(num)
            for num in shared_policy.choose_reference_articles(
                user_input=message,
                documents=docs,
                max_articles=3,
            )
        ]
        if all_cited:
            primary = [num for num in primary if num in all_cited or num in retrieved]
    elif route in {"rag", "rule_based", "rule_followup"}:
        primary = [num for num in all_cited if num.isdigit() and int(num) <= shared_policy.MAX_ARTICLE_NUMBER][:3]

    # Avoid presenting out-of-range or ungrounded article numbers as citations.
    primary = [
        num for num in dict.fromkeys(primary)
        if num.isdigit() and 1 <= int(num) <= shared_policy.MAX_ARTICLE_NUMBER
    ]
    cross_refs = [
        num for num in dict.fromkeys(all_cited)
        if num not in primary and num.isdigit() and 1 <= int(num) <= shared_policy.MAX_ARTICLE_NUMBER
    ]
    return all_cited, primary, cross_refs


@app.get("/api/health")
def health() -> dict[str, Any]:
    runtime = get_runtime()
    return {"ok": True, "vector_count": runtime.vector_count}


@app.get("/")
def root() -> dict[str, str]:
    return {
        "service": "Legal Chatbot RAG API",
        "health": "/api/health",
        "docs": "/docs",
    }


@app.post("/api/chat")
def chat(payload: ChatRequest) -> dict[str, Any]:
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    runtime = get_runtime()
    try:
        result = runtime.engine.run_structured(
            user_input=message,
            chat_history=_to_langchain_history(payload.chat_history),
        )
    except Exception as exc:
        logger.exception("RAG engine failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    answer = result.answer or ""
    cited_articles, primary_cited_articles, cross_references = _citation_payload(message, result)
    retrieved_articles = [_doc_to_article(doc) for doc in (result.docs or [])]
    logger.info(
        "QUERY=%r ROUTE=%s CITED=%s DOCS=%s ANSWER=%r",
        message,
        result.route or "unknown",
        cited_articles,
        len(retrieved_articles),
        _snippet(answer, limit=220),
    )

    return {
        "answer": answer,
        "route": result.route or "unknown",
        "cited_articles": cited_articles,
        "primary_cited_articles": primary_cited_articles,
        "cross_references": cross_references,
        "retrieved_articles": retrieved_articles,
        "validation": _validation_payload(result),
    }
