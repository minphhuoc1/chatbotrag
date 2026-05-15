# -*- coding: utf-8 -*-
"""
Sinh candidate legal hints tự động (offline) từ cấu trúc Điều luật đã ingest.

Mục tiêu:
1) Tạo bộ hint phong phú hơn hard-code hiện tại.
2) Không tự động bật ngay; tất cả hint sinh ra đều ở trạng thái review.
3) Dùng cho bước evaluate trước khi merge vào runtime policy.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from ingest import build_article_chunks, load_and_clean_pdfs
from src.legal_chatbot.config import DATA_DIR


STOPWORDS = {
    "và",
    "hoặc",
    "của",
    "cho",
    "về",
    "đối",
    "với",
    "theo",
    "khi",
    "trong",
    "tại",
    "các",
    "những",
    "được",
    "phải",
    "người",
    "lao",
    "động",
    "quy",
    "định",
}

GENERIC_PHRASES = {
    "người lao động",
    "người sử dụng",
    "sử dụng lao động",
    "quy định chung",
    "điều khoản thi hành",
}


def _norm_text(text: str) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip().lower())
    return text


def _tokenize_vi(text: str) -> list[str]:
    return re.findall(r"[a-zà-ỹ0-9]+", _norm_text(text))


def _extract_title_phrases(title: str, max_phrases: int = 10) -> list[str]:
    title_norm = _norm_text(title)
    if not title_norm:
        return []

    phrases = []
    seen = set()

    def _push(phrase: str):
        norm = _norm_text(phrase)
        if not norm or norm in seen:
            return
        if norm in GENERIC_PHRASES:
            return
        if len(norm) < 6:
            return
        seen.add(norm)
        phrases.append(norm)

    # 1) Full title phrase.
    if 2 <= len(title_norm.split()) <= 10:
        _push(title_norm)

    # 2) Split by separators để lấy các sub-phrase có nghĩa.
    for part in re.split(r"[,:;]| và | hoặc ", title_norm):
        part = _norm_text(part)
        if 2 <= len(part.split()) <= 8:
            _push(part)

    # 3) N-gram theo token đã bỏ stopword để tăng recall.
    filtered = [tok for tok in _tokenize_vi(title_norm) if tok not in STOPWORDS]
    for n in (2, 3):
        for i in range(0, max(len(filtered) - n + 1, 0)):
            gram = " ".join(filtered[i : i + n]).strip()
            if gram:
                _push(gram)

    return phrases[:max_phrases]


def _candidate_confidence(phrase: str, article_count: int) -> float:
    tokens = phrase.split()
    base = 0.8 if len(tokens) >= 3 else 0.66
    spread_penalty = min(article_count - 1, 5) * 0.08
    score = max(0.2, min(0.95, base - spread_penalty))
    return round(score, 3)


def build_candidates(max_hints: int = 450) -> tuple[list[dict], dict]:
    documents = load_and_clean_pdfs(DATA_DIR)
    _, parent_docs, _, _ = build_article_chunks(documents, include_parent=True)

    phrase_to_articles: dict[str, set[int]] = defaultdict(set)
    phrase_sources: dict[str, list[dict]] = defaultdict(list)

    for doc in parent_docs:
        meta = doc.metadata or {}
        article_number = meta.get("article_number")
        if not isinstance(article_number, int):
            continue
        title = str(meta.get("article_title", "") or "")
        if not title.strip():
            continue

        phrases = _extract_title_phrases(title)
        for phrase in phrases:
            phrase_to_articles[phrase].add(article_number)
            phrase_sources[phrase].append(
                {
                    "article": article_number,
                    "title": title.strip(),
                }
            )

    hints = []
    for phrase, article_set in phrase_to_articles.items():
        articles = sorted(int(a) for a in article_set)
        confidence = _candidate_confidence(phrase, len(articles))
        hints.append(
            {
                "keywords": [phrase],
                "articles": articles,
                "confidence": confidence,
                "enabled": False,
                "source": "title_ngram",
                "evidence": phrase_sources.get(phrase, [])[:4],
            }
        )

    hints.sort(
        key=lambda x: (
            -float(x.get("confidence", 0)),
            len(x.get("articles", [])),
            x.get("keywords", [""])[0],
        )
    )
    hints = hints[:max_hints]

    stats = {
        "documents_count": len(documents),
        "parent_docs_count": len(parent_docs),
        "candidate_hints_count": len(hints),
    }
    return hints, stats


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic legal hints from article titles.")
    parser.add_argument(
        "--output-dir",
        default=str(ROOT_DIR / "artifacts" / "hints"),
        help="Directory lưu candidate hints JSON.",
    )
    parser.add_argument(
        "--max-hints",
        type=int,
        default=450,
        help="Giới hạn số hint sinh ra.",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    hints, stats = build_candidates(max_hints=args.max_hints)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = output_dir / f"candidate_hints_{stamp}.json"
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now().isoformat(),
        "generator": "synthetic_hints_title_ngram_v1",
        "status": "review_required",
        "source_data_dir": str(DATA_DIR),
        "stats": stats,
        "hints": hints,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("✅ Synthetic hint generation completed.")
    print(f"   Output: {out_path}")
    print(f"   Candidate hints: {len(hints)}")


if __name__ == "__main__":
    main()
