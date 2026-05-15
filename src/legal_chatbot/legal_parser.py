# -*- coding: utf-8 -*-
"""
legal_parser.py — Chuẩn hóa văn bản pháp lý và tách theo Điều thực sự.
"""

import re
from typing import Dict, List

from langchain_core.documents import Document

ARTICLE_HEADING_RE = re.compile(r"^\s*Điều\s+(\d+)\s*[\.:]\s*(.*)$", re.IGNORECASE)
CLAUSE_RE = re.compile(r"^\s*\d+\.\s+")
POINT_RE = re.compile(r"^\s*[a-zđ]\)\s+", re.IGNORECASE)


def normalize_legal_text(raw_text: str) -> str:
    """
    Chuẩn hóa text pháp lý:
    - Xóa watermark
    - Xóa page numbers rời
    - Xóa pattern lOMoARcPSD|...
    - Xóa dòng rác lẻ
    """
    text = raw_text or ""

    # Watermark/footer phổ biến
    text = re.sub(r"Downloaded by[^\n]*\n?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"Studocu[^\n]*\n?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"Studeersnel[^\n]*\n?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"Scan to open[^\n]*\n?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"lOMoARcPSD\|\d+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"lOMoAR[^\s\n]*", "", text, flags=re.IGNORECASE)

    # Browser header/footer artifacts from printed PDF
    text = re.sub(
        r"\d{1,2}/\d{1,2}/\d{2,4},?\s+\d{1,2}:\d{2}\s*(?:am|pm)?\s+about:blank(?:\s+about:blank)?\s+\d+/\d+",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\babout:blank\b(?:\s+\babout:blank\b)?\s+\d+/\d+", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"(?im)^\s*\d{1,2}/\d{1,2}/\d{2,4},?\s+\d{1,2}:\d{2}\s*(?:am|pm)?\s+about:blank.*$", "", text)
    text = re.sub(r"(?im)^\s*about:blank(?:\s+about:blank)?\s+\d+/\d+\s*$", "", text)

    # Xóa số trang rời đứng riêng dòng
    text = re.sub(r"(?m)^\s*\d{1,3}\s*$", "", text)

    # Xóa dòng rác chỉ gồm ký tự trang trí
    text = re.sub(r"(?m)^\s*[-_=~•·]{3,}\s*$", "", text)

    # Xóa dòng quá ngắn không có chữ/số (rác OCR)
    cleaned_lines = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            cleaned_lines.append("")
            continue
        if len(s) <= 2 and not re.search(r"[A-Za-zÀ-ỹ0-9]", s):
            continue
        cleaned_lines.append(line)
    text = "\n".join(cleaned_lines)

    # Chuẩn hóa whitespace
    text = re.sub(r"\r", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def split_into_articles(text: str) -> List[Dict]:
    """
    Tách văn bản thành danh sách Điều.
    Mỗi object:
    {
      "article_number": 113,
      "title": "Nghỉ hằng năm",
      "content": "...",
      "start_char": ...,
      "end_char": ...
    }
    """
    pattern = re.compile(r"(?mi)^\s*Điều\s+(\d+)\s*[\.:]\s*(.*)$")
    matches = list(pattern.finditer(text))
    articles: List[Dict] = []

    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        article_number = int(match.group(1))
        title = match.group(2).strip()
        articles.append(
            {
                "article_number": article_number,
                "title": title,
                "content": content,
                "start_char": start,
                "end_char": end,
            }
        )

    return articles


def _is_article_heading(line: str) -> bool:
    return bool(ARTICLE_HEADING_RE.match((line or "").strip()))


def _is_clause_marker(line: str) -> bool:
    return bool(CLAUSE_RE.match((line or "").strip()))


def _is_point_marker(line: str) -> bool:
    return bool(POINT_RE.match((line or "").strip()))


def _normalize_compare_key(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


def _split_inline_legal_markers(line: str) -> List[str]:
    """
    Tách marker pháp lý inline thành nhiều unit để tránh chunk bị cắt giữa điểm/khoản.
    Ví dụ:
      "e) ...; g) ...; h) ..."
      -> ["e) ...;", "g) ...;", "h) ..."]
    """
    raw = re.sub(r"[ \t]+", " ", (line or "").strip())
    if not raw:
        return []

    parts = re.split(
        r"(?<=;)\s+(?=[a-zđ]\)\s)|(?<=:)\s+(?=[a-zđ]\)\s)|(?<=;)\s+(?=\d+\.\s)|(?<=:)\s+(?=\d+\.\s)",
        raw,
        flags=re.IGNORECASE,
    )

    out = []
    for part in parts:
        cleaned = part.strip()
        if cleaned:
            out.append(cleaned)
    return out


def _build_legal_units(content: str) -> List[str]:
    """
    Chuyển content Điều thành danh sách unit có nghĩa pháp lý.
    """
    text = (content or "").strip()
    if not text:
        return []

    lines = re.sub(r"\r", "", text).splitlines()
    units: List[str] = []
    for raw_line in lines:
        for part in _split_inline_legal_markers(raw_line):
            key = _normalize_compare_key(part)
            if units and _normalize_compare_key(units[-1]) == key:
                continue
            units.append(part)
    return units


def _group_units_into_sections(units: List[str]) -> List[str]:
    """
    Gom unit thành section theo Khoản.
    Mỗi section giữ trọn ý (khoản + điểm liên quan) để chunk theo cấu trúc pháp lý.
    """
    if not units:
        return []

    sections: List[str] = []
    current: List[str] = []
    article_heading = ""
    seen_article_heading = False

    for unit in units:
        stripped = unit.strip()
        if not stripped:
            continue

        if _is_article_heading(stripped):
            if not seen_article_heading:
                article_heading = stripped
                seen_article_heading = True
                continue
            # Nếu lỡ leak sang Điều kế tiếp thì dừng section hiện tại.
            break

        if seen_article_heading and re.match(r"^(Mục|Chương)\b", stripped, flags=re.IGNORECASE):
            # Đây thường là dấu hiệu sang phần mới, tránh nuốt sang Điều tiếp theo.
            break

        if _is_clause_marker(stripped):
            if current:
                sections.append("\n".join(current).strip())
            current = [stripped]
            continue

        if current:
            current.append(stripped)
        else:
            current = [stripped]

    if current:
        sections.append("\n".join(current).strip())

    if article_heading:
        if sections:
            sections[0] = f"{article_heading}\n{sections[0]}".strip()
        else:
            sections = [article_heading]

    return [sec for sec in sections if sec.strip()]


def _split_long_line_by_words(line: str, chunk_size: int) -> List[str]:
    words = line.split()
    if not words:
        return []

    parts = []
    current = []
    cur_len = 0
    for word in words:
        add_len = len(word) + (1 if current else 0)
        if current and cur_len + add_len > chunk_size:
            parts.append(" ".join(current).strip())
            current = [word]
            cur_len = len(word)
        else:
            current.append(word)
            cur_len += add_len
    if current:
        parts.append(" ".join(current).strip())
    return parts


def _split_large_section(section: str, chunk_size: int) -> List[str]:
    """
    Nếu section vẫn quá dài, tách theo line và giữ context clause cho chunk bắt đầu bằng điểm.
    """
    lines = [ln.strip() for ln in (section or "").splitlines() if ln.strip()]
    if not lines:
        return []

    clause_context = ""
    for ln in lines:
        if _is_clause_marker(ln):
            clause_context = ln
            break

    pieces: List[str] = []
    current: List[str] = []
    cur_len = 0

    def flush():
        nonlocal current, cur_len
        if current:
            pieces.append("\n".join(current).strip())
            current = []
            cur_len = 0

    for line in lines:
        if len(line) > chunk_size:
            flush()
            pieces.extend(_split_long_line_by_words(line, chunk_size))
            continue

        add_len = len(line) + (1 if current else 0)
        if current and cur_len + add_len > chunk_size:
            flush()
            if _is_point_marker(line) and clause_context:
                current = [clause_context]
                cur_len = len(clause_context)
                add_len = len(line) + 1

        if not current:
            current = [line]
            cur_len = len(line)
        else:
            current.append(line)
            cur_len += add_len

    flush()
    return [p for p in pieces if p.strip()]


def _chunk_sections_semantic(sections: List[str], chunk_size: int) -> List[str]:
    """
    Chunk theo section pháp lý (không cắt giữa từ, ưu tiên giữ nguyên Khoản/Điểm).
    """
    chunks: List[str] = []
    current_parts: List[str] = []
    cur_len = 0

    def flush():
        nonlocal current_parts, cur_len
        if current_parts:
            chunks.append("\n\n".join(current_parts).strip())
            current_parts = []
            cur_len = 0

    for section in sections:
        section = (section or "").strip()
        if not section:
            continue

        candidate_sections = [section]
        if len(section) > chunk_size:
            candidate_sections = _split_large_section(section, chunk_size)

        for candidate in candidate_sections:
            if not candidate.strip():
                continue
            add_len = len(candidate) + (2 if current_parts else 0)
            if current_parts and cur_len + add_len > chunk_size:
                flush()

            if not current_parts:
                current_parts = [candidate]
                cur_len = len(candidate)
            else:
                current_parts.append(candidate)
                cur_len += add_len

    flush()
    return [c for c in chunks if c.strip()]


def subchunk_article(article: Dict, chunk_size: int = 1000, chunk_overlap: int = 120) -> List[Document]:
    """
    Nếu Điều quá dài thì chia nhỏ thành subchunks.
    Metadata bắt buộc:
    - article_number
    - article_title
    - source_file
    - chunk_type (article_full, article_subchunk)
    - page_start/page_end (nếu có)
    """
    content = article.get("content", "").strip()
    if not content:
        return []

    base_metadata = {
        "article_number": article.get("article_number"),
        "article_title": article.get("title", ""),
        "source_file": article.get("source_file", ""),
        "chunk_type": "article_full",
        "page_start": article.get("page_start"),
        "page_end": article.get("page_end"),
        # Compatibility với code cũ/QA
        "dieu_so": str(article.get("article_number")) if article.get("article_number") is not None else None,
        "doc_id": article.get("doc_id"),
    }

    if len(content) <= chunk_size:
        return [Document(page_content=content, metadata=base_metadata)]

    # chunk_overlap được giữ cho tương thích API hiện tại nhưng không dùng
    # trong semantic chunking để tránh cắt/copy chồng lấn thiếu kiểm soát.
    _ = chunk_overlap

    units = _build_legal_units(content)
    sections = _group_units_into_sections(units)
    chunks = _chunk_sections_semantic(sections, chunk_size)
    if not chunks:
        return [Document(page_content=content, metadata=base_metadata)]

    docs: List[Document] = []
    for idx, chunk_text in enumerate(chunks):
        meta = dict(base_metadata)
        meta["chunk_type"] = "article_subchunk"
        meta["subchunk_index"] = idx
        docs.append(Document(page_content=chunk_text.strip(), metadata=meta))
    return docs
