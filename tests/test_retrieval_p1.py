from langchain_core.documents import Document

from src.legal_chatbot import policy, retrieval


def _doc(article: int, chunk: str, lexical: float = 0.0, rrf: float = 0.0) -> Document:
    return Document(
        page_content=f"Điều {article}. Nội dung {chunk}",
        metadata={
            "article_number": article,
            "chunk_id": f"{article}-{chunk}",
            "lexical_score": lexical,
            "hybrid_rrf_score": rrf,
            "source_file": "luatlaodong_new.pdf",
        },
    )


def test_reranker_prioritizes_target_article_with_metadata_boost(monkeypatch):
    monkeypatch.setattr(retrieval, "RETRIEVAL_ENABLE_RERANKER", True)
    monkeypatch.setattr(retrieval, "RETRIEVAL_ENABLE_METADATA_BOOST", True)
    monkeypatch.setattr(retrieval, "_safe_suggest_target_articles", lambda _q: [35])

    noisy = _doc(article=90, chunk="noise", lexical=12.0, rrf=0.001)
    target = _doc(article=35, chunk="target", lexical=0.5, rrf=0.001)

    ranked = retrieval._rerank_documents(
        docs=[noisy, target],
        user_input="Điều 35 quy định gì?",
        semantic_query="Điều 35 quy định gì",
        article_number=35,
        strategy_name="lookup",
        limit=2,
    )

    assert ranked
    assert (ranked[0].metadata or {}).get("article_number") == 35
    assert "rerank_score" in (ranked[0].metadata or {})


def test_classify_failure_cause_prefers_retrieval_when_context_weak():
    cause = policy.classify_failure_cause(
        user_input="Tôi bị xử lý kỷ luật",
        query_mode="fact_pattern",
        retrieval_check={"is_strong_enough": False, "reason": "only vague semantic matches"},
    )
    assert cause["primary"] == "retrieval"


def test_classify_failure_cause_marks_policy_for_article_resolution():
    cause = policy.classify_failure_cause(
        user_input="Điều 35",
        query_mode="article_lookup",
        retrieval_check={"is_strong_enough": True},
        used_article_resolution=True,
        answer="Bạn vui lòng nêu rõ chủ đề cần tra cứu.",
    )
    assert cause["primary"] == "policy"


def test_classify_failure_cause_marks_model_on_invalid_citations():
    cause = policy.classify_failure_cause(
        user_input="Nghỉ phép năm bao nhiêu ngày?",
        query_mode="open_ended",
        retrieval_check={"is_strong_enough": True},
        validation={"ok": False, "invalid_articles": [999], "reason": "answer cites articles not in context"},
    )
    assert cause["primary"] == "model"
