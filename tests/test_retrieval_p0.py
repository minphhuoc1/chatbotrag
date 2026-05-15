from types import SimpleNamespace

from langchain_core.documents import Document

from src.legal_chatbot import retrieval
from src.legal_chatbot.strategy_router import select_retrieval_strategy


def _doc(article: int, chunk: str) -> Document:
    return Document(
        page_content=f"Điều {article}. Nội dung {chunk}",
        metadata={
            "article_number": article,
            "chunk_id": f"{article}-{chunk}",
            "source_file": "bllđ.pdf",
        },
    )


class DummyRetriever:
    def __init__(self):
        self.vectorstore = None
        self.queries: list[str] = []

    def invoke(self, query: str):
        self.queries.append(query)
        return [_doc(90, "semantic")]


def test_strategy_router_prefers_lookup_for_article_procedural_query():
    decision = select_retrieval_strategy("Điều 35 quy định gì?")

    assert decision.primary_strategy == "lookup"
    assert decision.ordered_strategies[0] == "lookup"
    assert decision.features.has_article_ref is True
    assert decision.features.is_procedural is True


def test_strategy_router_prefers_multi_query_for_comparison():
    decision = select_retrieval_strategy("Điều 40 và Điều 41 khác gì nhau?")

    assert "multi_query" in decision.ordered_strategies
    assert decision.features.needs_comparison is True


def test_retrieve_documents_short_circuits_on_deterministic_lookup(monkeypatch):
    retriever_stub = DummyRetriever()

    def fake_exact_article(article_number: int, **_kwargs):
        if article_number == 35:
            return [_doc(35, "a"), _doc(35, "b")]
        return []

    monkeypatch.setattr(retrieval, "retrieve_exact_article", fake_exact_article)

    docs = retrieval.retrieve_documents(
        user_input="Điều 35 quy định gì?",
        retriever=retriever_stub,
        k=4,
        semantic_query="Điều 35 quy định gì",
    )

    assert len(docs) >= 1
    assert all((d.metadata or {}).get("article_number") == 35 for d in docs)
    assert retriever_stub.queries == []


def test_retrieve_documents_uses_semantic_hybrid_path(monkeypatch):
    retriever_stub = DummyRetriever()
    hybrid_queries: list[str] = []

    def fake_hybrid(retriever, query: str, vector_db, k: int):
        _ = retriever, vector_db, k
        hybrid_queries.append(query)
        return [_doc(96, "hybrid")]

    monkeypatch.setattr(retrieval, "_hybrid_semantic_lexical_search", fake_hybrid)
    monkeypatch.setattr(retrieval, "retrieve_exact_article", lambda **_kwargs: [])
    monkeypatch.setattr(retrieval, "_expand_with_related_articles", lambda **_kwargs: [])

    docs = retrieval.retrieve_documents(
        user_input="Công ty chậm lương 2 tháng thì xử lý sao?",
        retriever=retriever_stub,
        k=3,
        semantic_query="chậm lương 2 tháng xử lý",
    )

    assert docs
    assert (docs[0].metadata or {}).get("article_number") == 96
    assert hybrid_queries
