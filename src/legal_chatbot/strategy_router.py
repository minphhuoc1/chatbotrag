# -*- coding: utf-8 -*-
"""
strategy_router.py — feature-based retrieval routing.

P0 goal:
- Tách lớp routing ra khỏi reasoning/retrieval để dễ kiểm thử.
- Chấm điểm các chiến lược retrieval theo feature thay vì if/else cứng.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class QueryFeatures:
    has_article_ref: bool
    has_clause_ref: bool
    has_doc_number: bool
    is_procedural: bool
    needs_comparison: bool
    token_count: int
    has_followup_marker: bool


@dataclass(frozen=True)
class StrategyDecision:
    primary_strategy: str
    ordered_strategies: tuple[str, ...]
    scores: dict[str, float]
    features: QueryFeatures


PROCEDURAL_MARKERS = (
    "quy định gì",
    "nội dung gì",
    "nguyên văn",
    "trích",
    "khoản bao nhiêu",
    "điểm nào",
)

COMPARISON_MARKERS = (
    "khác gì",
    "so sánh",
    "so với",
    "phân biệt",
    "điểm giống",
    "điểm khác",
    "hay là",
)

FOLLOWUP_MARKERS = (
    "vậy",
    "thế",
    "còn",
    "nếu",
    "trường hợp này",
    "trường hợp đó",
)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def extract_query_features(user_input: str) -> QueryFeatures:
    text = _normalize(user_input)
    tokens = [t for t in text.split(" ") if t]

    has_article_ref = bool(re.search(r"\bđiều\s*\d+\b", text))
    has_clause_ref = bool(re.search(r"\bkhoản\s*\d+\b|\bđiểm\s*[a-z]\b", text))
    has_doc_number = bool(re.search(r"\b\d+/\d{4}/[a-zđ-]+\b", text))
    is_procedural = any(marker in text for marker in PROCEDURAL_MARKERS)
    needs_comparison = any(marker in text for marker in COMPARISON_MARKERS)
    has_followup_marker = any(marker in text for marker in FOLLOWUP_MARKERS)

    return QueryFeatures(
        has_article_ref=has_article_ref,
        has_clause_ref=has_clause_ref,
        has_doc_number=has_doc_number,
        is_procedural=is_procedural,
        needs_comparison=needs_comparison,
        token_count=len(tokens),
        has_followup_marker=has_followup_marker,
    )


def select_retrieval_strategy(user_input: str) -> StrategyDecision:
    """
    Strategy set:
    - lookup: deterministic lookup theo Điều/Khoản/số hiệu.
    - semantic: vector + lexical hybrid 1 query.
    - multi_query: vector + lexical hybrid nhiều query variants.
    """
    features = extract_query_features(user_input)
    scores: dict[str, float] = {"lookup": 0.0, "semantic": 0.0, "multi_query": 0.0}

    # Lookup favors exact references.
    if features.has_article_ref:
        scores["lookup"] += 4.0
    if features.has_clause_ref:
        scores["lookup"] += 1.5
    if features.has_doc_number:
        scores["lookup"] += 2.0
    if features.is_procedural:
        scores["lookup"] += 1.2

    # Semantic default baseline.
    scores["semantic"] += 1.5
    if not features.has_article_ref:
        scores["semantic"] += 1.2
    if features.token_count > 12:
        scores["semantic"] += 0.4

    # Multi-query favors comparison and dense follow-up prompts.
    if features.needs_comparison:
        scores["multi_query"] += 3.0
    if features.token_count >= 16:
        scores["multi_query"] += 1.0
    if features.has_followup_marker and features.token_count <= 10:
        scores["multi_query"] += 0.8
    if features.has_article_ref and features.needs_comparison:
        scores["multi_query"] += 1.0

    ordered = tuple(
        name
        for name, _score in sorted(
            scores.items(),
            key=lambda item: item[1],
            reverse=True,
        )
        if _score > 0
    )
    if not ordered:
        ordered = ("semantic",)

    return StrategyDecision(
        primary_strategy=ordered[0],
        ordered_strategies=ordered,
        scores=scores,
        features=features,
    )
