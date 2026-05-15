import os
# Force transformers dùng PyTorch backend — tránh lỗi Keras 3 incompatibility
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_TORCH", "1")

import logging
import json
import re
import streamlit as st
import time
from typing import Dict, List
from langchain_core.messages import HumanMessage, AIMessage
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential, RetryError
from retrieval import build_runtime_retriever
from src.legal_chatbot.config import (
    ANSWER_PROMPT_PATH,
    DATA_DIR,
    DB_PATH,
    EMBED_MODEL,
    LLM_ANALYZER_MODEL,
    LLM_FAST_MAX_RETRIES,
    LLM_INTENT_MODEL,
    LLM_PROVIDER,
    LLM_REASONER_MAX_RETRIES,
    LLM_REASONER_MODEL,
    VECTOR_BACKEND,
)
from src.legal_chatbot.embeddings import create_embeddings, get_embedding_runtime_device
from src.legal_chatbot.llm_factory import create_llm_clients
from src.legal_chatbot.observability import describe_observability_state
from src.legal_chatbot import policy as shared_policy
from ingest import build_article_chunks, load_and_clean_pdfs

try:
    from langchain_chroma import Chroma
except ImportError:
    from langchain_community.vectorstores import Chroma

# ── 1. Config ─────────────────────────────────────────────────────────────────
load_dotenv()


def _build_memory_vector_db(embeddings):
    documents = load_and_clean_pdfs(DATA_DIR)
    chunks, parent_docs, article_parent_index, article_related_index = build_article_chunks(
        documents,
        include_parent=True,
    )
    vector_db = Chroma.from_documents(documents=chunks, embedding=embeddings)
    return vector_db, len(chunks), parent_docs, article_parent_index, article_related_index


def _build_doc_evidence_rows(documents: list) -> List[Dict]:
    rows = []
    for idx, doc in enumerate(documents, 1):
        meta = doc.metadata or {}
        article_number = meta.get("article_number") or meta.get("dieu_so")
        snippet = re.sub(r"\s+", " ", doc.page_content).strip()[:220]
        rows.append(
            {
                "rank": idx,
                "article_number": str(article_number) if article_number is not None else "?",
                "article_title": meta.get("article_title") or meta.get("title") or "",
                "page": str(meta.get("page", meta.get("page_start", "?"))),
                "chunk_id": str(meta.get("chunk_id", "?")),
                "source_file": meta.get("source_file", ""),
                "score": meta.get("score", meta.get("relevance_score", None)),
                "snippet": snippet,
            }
        )
    return rows


def _build_grounding_rows(answer: str, documents: list) -> List[Dict]:
    if not answer or not documents:
        return []
    cited_articles = set(extract_article_references(answer))
    normalized_answer = _normalize_for_match(answer)
    rows = []
    for idx, doc in enumerate(documents, 1):
        meta = doc.metadata or {}
        article_number = meta.get("article_number") or meta.get("dieu_so")
        doc_norm = _normalize_for_match(doc.page_content)
        has_cited_article = False
        if article_number is not None and str(article_number).isdigit():
            has_cited_article = int(article_number) in cited_articles
        else:
            article_hits = set(int(m) for m in re.findall(r"[Đđ]iều\s*(\d+)", doc.page_content))
            has_cited_article = bool(cited_articles.intersection(article_hits))
        overlap = False
        for token in [t for t in re.split(r"[,\.;:\n\-]+", normalized_answer) if len(t.strip()) >= 35]:
            if token.strip() in doc_norm:
                overlap = True
                break
        if has_cited_article or overlap:
            rows.append(
                {
                    "rank": idx,
                    "chunk_id": str(meta.get("chunk_id", "?")),
                    "article_number": str(article_number) if article_number is not None else "?",
                    "page": str(meta.get("page", meta.get("page_start", "?"))),
                    "grounding_signal": "article_ref" if has_cited_article else "text_overlap",
                }
            )
    return rows


# Shared policy helpers used by UI evidence rendering.
extract_article_references = shared_policy.extract_article_references
_normalize_for_match = shared_policy._normalize_for_match


def _yield_text_chunks(text: str, chunk_size: int = 24):
    for i in range(0, len(text), chunk_size):
        yield text[i : i + chunk_size]


def _render_assistant_answer(answer: str) -> str:
    content = (answer or "").strip()
    if not content:
        st.markdown("")
        return ""
    try:
        streamed = st.write_stream(_yield_text_chunks(content))
        if isinstance(streamed, str) and streamed.strip():
            return streamed
    except Exception as stream_err:
        logging.getLogger(__name__).debug("write_stream fallback: %s", stream_err)
    st.markdown(content)
    return content

# ── 2. Logging setup ──────────────────────────────────────────────────────────
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/app.log", encoding="utf-8"),
        # Không stream ra console để tránh nhiễu Streamlit
    ]
)
logger = logging.getLogger(__name__)

# ── 3. Page config ────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Trợ lý Luật Lao Động",
    page_icon="⚖️",
    layout="centered",
)

# ── 4. Load resources (cached) ────────────────────────────────────────────────
@st.cache_resource(show_spinner="⏳ Đang khởi động hệ thống AI...")
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True
)
def load_resources():
    """
    Load embeddings, vector DB, and LLM with retry logic.
    
    Retry Strategy:
    - Attempt 1: Immediately
    - Attempt 2: Wait 2 seconds
    - Attempt 3: Wait 10 seconds
    This handles brief provider connection hiccups.
    """
    try:
        logger.info("Loading embeddings...")
        embeddings = create_embeddings(EMBED_MODEL)
        logger.info("Embedding runtime device: %s", get_embedding_runtime_device(embeddings))
        
        logger.info("Loading vector database...")
        parent_docs = []
        article_parent_index = {}
        article_related_index = {}
        active_vector_backend = VECTOR_BACKEND
        if VECTOR_BACKEND == "memory":
            (
                vector_db,
                chunk_count,
                parent_docs,
                article_parent_index,
                article_related_index,
            ) = _build_memory_vector_db(
                embeddings
            )
        else:
            try:
                vector_db = Chroma(persist_directory=DB_PATH, embedding_function=embeddings)
                chunk_count = vector_db._collection.count()
            except Exception as vector_error:
                logger.warning(
                    "Persistent vector DB load failed (%s). Fallback to memory backend.",
                    vector_error,
                )
                (
                    vector_db,
                    chunk_count,
                    parent_docs,
                    article_parent_index,
                    article_related_index,
                ) = _build_memory_vector_db(
                    embeddings
                )
                active_vector_backend = "memory_fallback"

        retriever = build_runtime_retriever(
            vector_db=vector_db,
            k=6,
            parent_docs=parent_docs,
            article_parent_index=article_parent_index,
            article_related_index=article_related_index,
        )
        
        logger.info("Initializing LLM provider...")
        llm_clients = create_llm_clients()
        llm = llm_clients.llm_reason
        llm_json = llm_clients.llm_json
        llm_intent = llm_clients.llm_intent
        if llm_clients.analyzer_model == llm_clients.reasoner_model:
            logger.warning(
                "Analyzer model is same as reasoner (%s). Consider using a smaller analyzer model to reduce 429 risk.",
                llm_clients.reasoner_model,
            )
        if llm_clients.intent_model == llm_clients.reasoner_model:
            logger.warning(
                "Intent model is same as reasoner (%s). Consider using a smaller intent model to reduce 429 risk.",
                llm_clients.reasoner_model,
            )
        
        # Health check: try a simple invoke to verify provider is responding
        logger.info("Performing provider health check...")
        try:
            llm.invoke("test")
            logger.info("Provider health check passed")
        except Exception as health_check_error:
            logger.warning("Provider health check failed: %s", health_check_error)
            raise ConnectionError(
                f"LLM provider '{llm_clients.provider}' not responding: {health_check_error}"
            )
        
        logger.info("Loading system prompt...")
        with open(ANSWER_PROMPT_PATH, "r", encoding="utf-8") as f:
            system_prompt = f.read()

        logger.info("Initializing legal reasoning engine...")
        from reasoning_chain import LegalReasoningEngine, CitationValidator
        engine = LegalReasoningEngine(
            retriever,
            llm_json,
            llm,
            system_prompt,
            llm_intent=llm_intent,
        )

        logger.info(
            "System started. provider=%s reasoner=%s analyzer=%s intent=%s reasoner_fallback=%s analyzer_fallback=%s intent_fallback=%s reasoner_retries=%s fast_retries=%s chunks=%s retriever_mode=%s vector_backend=%s",
            llm_clients.provider,
            llm_clients.reasoner_model,
            llm_clients.analyzer_model,
            llm_clients.intent_model,
            llm_clients.reasoner_fallback_model,
            llm_clients.analyzer_fallback_model,
            llm_clients.intent_fallback_model,
            LLM_REASONER_MAX_RETRIES,
            LLM_FAST_MAX_RETRIES,
            chunk_count,
            getattr(retriever, "retrieval_mode", "unknown"),
            active_vector_backend,
        )
        logger.info("Observability state: %s", json.dumps(describe_observability_state(), ensure_ascii=False))
        return engine, llm, llm_intent, llm_clients, chunk_count, active_vector_backend
        
    except Exception as e:
        logger.error(f"Resource loading failed: {e}")
        raise

try:
    engine, _llm_unused, _llm_intent_unused, llm_clients_meta, chunk_count, active_vector_backend = load_resources()
    load_ok = True
except RetryError as e:
    load_ok = False
    load_error = f"Failed to connect to provider after 3 retries. Check LLM provider and API key."
    logger.error(f"Startup failed (after retries): {e}")
except ConnectionError as e:
    load_ok = False
    load_error = f"LLM provider connection error: {e}"
    logger.error(f"LLM provider health check failed: {e}")
except Exception as e:
    load_ok = False
    load_error = str(e)
    logger.error(f"Startup failed: {e}")

# ── 5. Sidebar ────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("⚖️ Thông tin hệ thống")
    st.divider()

    if load_ok:
        st.success("🟢 Đã kết nối")
        st.markdown(f"**Provider:** `{LLM_PROVIDER}`")
        st.markdown(f"**Reasoner model:** `{LLM_REASONER_MODEL}`")
        st.markdown(f"**Analyzer model:** `{LLM_ANALYZER_MODEL}`")
        st.markdown(f"**Intent model:** `{LLM_INTENT_MODEL}`")
        st.markdown(f"**Reasoner max retries:** `{LLM_REASONER_MAX_RETRIES}`")
        st.markdown(f"**Fast-path max retries:** `{LLM_FAST_MAX_RETRIES}`")
        if getattr(llm_clients_meta, "reasoner_fallback_model", ""):
            st.markdown(f"**Reasoner fallback:** `{llm_clients_meta.reasoner_fallback_model}`")
        if getattr(llm_clients_meta, "analyzer_fallback_model", ""):
            st.markdown(f"**Analyzer fallback:** `{llm_clients_meta.analyzer_fallback_model}`")
        if getattr(llm_clients_meta, "intent_fallback_model", ""):
            st.markdown(f"**Intent fallback:** `{llm_clients_meta.intent_fallback_model}`")
        st.markdown(f"**Chunks trong DB:** `{chunk_count}`")
        st.markdown(f"**Vector backend:** `{active_vector_backend}`")
        st.markdown(f"**Embedding:** `MiniLM-L12-v2`")
    else:
        st.error("🔴 Lỗi khởi động")
        st.code(load_error)

    st.divider()
    if st.button("🗑️ Xóa lịch sử hội thoại", use_container_width=True):
        st.session_state.messages    = []
        st.session_state.chat_history = []
        st.rerun()

    st.divider()
    st.caption("Trợ lý chỉ hỗ trợ **Bộ luật Lao động Việt Nam 2019**.")

# ── 6. Dừng nếu load thất bại ─────────────────────────────────────────────────
if not load_ok:
    st.error(f"Không thể khởi động: {load_error}")
    st.stop()

# ── 7. Chat Interface ──────────────────────────────────────────────────────────
st.title("⚖️ Trợ lý AI Tư vấn Luật Lao Động")
st.caption("Hỏi về quyền lợi lao động, hợp đồng, sa thải, lương thưởng, nghỉ phép...")

if "messages" not in st.session_state:
    st.session_state.messages     = []
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# Render toàn bộ lịch sử
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ── 8. Xử lý input ────────────────────────────────────────────────────────────
if user_input := st.chat_input("Nhập câu hỏi của bạn..."):
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant"):
        try:
            limit_history = (
                st.session_state.chat_history[-4:]
                if len(st.session_state.chat_history) >= 4
                else st.session_state.chat_history
            )
            with st.spinner("🔍 Đang phân tích câu hỏi và tra cứu tài liệu..."):
                result = engine.run_structured(user_input=user_input, chat_history=limit_history)

            intent_obj = getattr(result.intent_result, "intent", None)
            intent_name = getattr(intent_obj, "name", "UNKNOWN")
            intent_source = getattr(result.intent_result, "source", "unknown")
            docs = list(result.docs or [])
            context_text = result.context_text or ""
            route = result.route or "unknown"
            query_mode = result.query_mode or "open_ended"
            logger.info(
                "QUERY='%s' INTENT=%s SOURCE=%s ROUTE=%s MODE=%s DOCS=%s SEARCH='%s'",
                user_input,
                intent_name,
                intent_source,
                route,
                query_mode,
                len(docs),
                result.search_query,
            )

            evidence_rows = _build_doc_evidence_rows(docs)
            if evidence_rows:
                logger.info(
                    "Retrieval evidence: %s",
                    json.dumps(evidence_rows[:6], ensure_ascii=False),
                )

            answer = _render_assistant_answer(result.answer)
            grounding_rows = _build_grounding_rows(answer, docs)
            if grounding_rows:
                logger.info(
                    "Grounding evidence: %s",
                    json.dumps(grounding_rows[:6], ensure_ascii=False),
                )

            if evidence_rows:
                st.caption("🔎 Top retrieved articles")
                st.dataframe(
                    evidence_rows,
                    width="stretch",
                    hide_index=True,
                )
            if grounding_rows:
                st.caption("🧷 Answer grounded trên các chunk sau")
                st.dataframe(
                    grounding_rows,
                    width="stretch",
                    hide_index=True,
                )

            with st.expander("📄 Tài liệu AI đã tham khảo (bấm để xem)"):
                st.text(context_text[:3000] if context_text else "Không có tài liệu.")

            logger.info(f"ANSWER (first 200 chars): {answer[:200]}")

            # Lưu vào session state
            st.session_state.messages.append({"role": "assistant", "content": answer})
            st.session_state.chat_history.append(HumanMessage(content=user_input))
            st.session_state.chat_history.append(AIMessage(content=answer))

        except ConnectionError as conn_err:
            logger.error(f"Connection error during query='{user_input}': {conn_err}")
            st.error("❌ Lỗi kết nối LLM provider.")
            st.info("Kiểm tra API key, network, và model ID trong cấu hình.")
        except TimeoutError as timeout_err:
            logger.error(f"Timeout during query='{user_input}': {timeout_err}")
            st.error("❌ Hết thời gian chờ phản hồi từ LLM provider. Hãy thử lại.")
        except Exception as e:
            logger.error(f"Error processing query='{user_input}': {e}", exc_info=True)
            st.error(f"Lỗi xử lý: {e}")
