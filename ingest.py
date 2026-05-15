# -*- coding: utf-8 -*-
"""
ingest.py — Pipeline xây dựng Vector Database từ các file PDF luật Việt Nam.

Vai trò trong dự án:
    Chạy 1 lần (hoặc khi có PDF mới) để đọc file luật, làm sạch, cắt nhỏ
    theo cấu trúc Điều/Khoản, và lưu vào ChromaDB.

Cách chạy:
    python ingest.py

Khi nào cần chạy lại:
    - Khi thêm file PDF mới vào ./data/
    - Khi thay đổi chunking strategy
    - Khi muốn rebuild toàn bộ database
"""

import os
import re
import json
import uuid
import sys
import hashlib
from datetime import datetime
from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document
from langchain_classic.storage import LocalFileStore, create_kv_docstore

try:
    from langchain_chroma import Chroma
except ImportError:
    from langchain_community.vectorstores import Chroma

from src.legal_chatbot.config import (
    DATA_DIR,
    DB_PATH,
    EMBED_MODEL,
    MAX_ARTICLE_NUMBER,
    PDF_BACKEND,
    PREPROCESSED_DIR,
)
from src.legal_chatbot.embeddings import create_embeddings
from legal_parser import normalize_legal_text, split_into_articles, subchunk_article

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ============================================================
# CẤU HÌNH — xác nhận từ analyze_pdf.py
# ============================================================
EMBEDDING_MODEL = EMBED_MODEL

CHUNK_SIZE    = 1000
CHUNK_OVERLAP = 120
# ============================================================

OPENDL_PAGE_KEYS = (
    "page",
    "page_number",
    "page number",
    "page_index",
    "page index",
)
OPENDL_TEXT_KEYS = ("content", "text", "markdown")
OPENDL_CHILD_KEYS = (
    "kids",
    "children",
    "nodes",
    "elements",
    "blocks",
    "pages",
    "list items",
    "rows",
    "cells",
    "items",
)
OPENDL_SKIP_TYPES = {"header", "footer"}
OPENDL_PREFER_SELF_TYPES = {
    "paragraph",
    "heading",
    "caption",
    "list item",
    "text",
    "title",
    "subtitle",
    "table cell",
}

ARTICLE_CROSS_REF_RE = re.compile(r"(?<!\w)[Đđ]iều\s+(\d{1,3})\b")


def _derive_parent_store_dir(db_path: str) -> str:
    return f"{db_path}_parent_store"


def _derive_parent_index_path(db_path: str) -> str:
    return f"{db_path}_parent_index.json"


def _to_docstore_key(doc_id: str) -> str:
    text = (doc_id or "").strip()
    if re.fullmatch(r"doc_[0-9a-f]{40}", text):
        return text
    digest = hashlib.sha1((doc_id or "").encode("utf-8")).hexdigest()
    return f"doc_{digest}"


def _resolve_target_db_path(db_path: str) -> str:
    """
    Chọn đường dẫn DB đích có thể ghi mà không phụ thuộc thao tác xóa thư mục cũ.
    Một số môi trường Windows/sandbox không cho delete file đã tạo trước đó.
    """
    if not os.path.exists(db_path):
        return db_path

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = f"{db_path}_{stamp}"
    suffix = 1
    while os.path.exists(candidate):
        suffix += 1
        candidate = f"{db_path}_{stamp}_{suffix}"

    print(f"  [WARN] DB path đã tồn tại và không ghi đè tại chỗ: '{db_path}'")
    print(f"  [INFO] Sẽ ghi DB mới tại: '{candidate}'")
    return candidate


def _is_table_of_contents_like(page_content: str) -> bool:
    text = page_content or ""
    head = text[:500]
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return False

    dieu_heading_lines = sum(1 for ln in lines if re.match(r"^[Đđ]iều\s+\d+\.", ln))
    clause_lines = sum(1 for ln in lines if re.match(r"^\d+\.", ln))
    chapter_lines = sum(1 for ln in lines if ln.startswith("Chương") or ln.startswith("Mục"))

    has_toc_marker = "MỤC LỤC" in head or "NỘI DUNG Trang" in head
    dense_index_pattern = dieu_heading_lines >= 25 and clause_lines <= 2 and chapter_lines >= 2
    heavy_index_pattern = dieu_heading_lines >= 40 and clause_lines == 0
    return has_toc_marker or dense_index_pattern or heavy_index_pattern


def _extract_related_articles(text: str, current_article: int | None = None, max_refs: int = 16) -> list[int]:
    refs = []
    seen = set()
    for matched in ARTICLE_CROSS_REF_RE.finditer(text or ""):
        article = int(matched.group(1))
        if article < 1 or article > MAX_ARTICLE_NUMBER:
            continue
        if current_article is not None and article == current_article:
            continue
        if article in seen:
            continue
        seen.add(article)
        refs.append(article)
        if len(refs) >= max_refs:
            break
    return refs


def should_skip_page(page_content: str) -> tuple[bool, str]:
    """
    Quyết định có bỏ qua trang này không.
    Trả về (True, lý_do) nếu bỏ qua, (False, "") nếu giữ lại.

    Căn cứ vào analyze_pdf.py:
    - Trang 1 (cover): không có Điều nào, chỉ có watermark + tên trường
    - Trang 46-49 (Mục Lục): có "MỤC LỤC" ở đầu, chỉ là danh sách tên Điều
    """
    stripped = page_content.strip()

    # Trang quá ngắn (<80 ký tự) → gần như trắng
    if len(stripped) < 80:
        return True, "trang quá ngắn"

    if _is_table_of_contents_like(stripped):
        return True, "trang mục lục"

    # Trang cover — không có điều khoản nào và chứa dấu hiệu watermark
    has_law_content = bool(re.search(r"Điều\s+\d+", stripped))
    has_watermark   = ("Studocu" in stripped or "Studeersnel" in stripped
                       or "Scan to open" in stripped)
    if has_watermark and not has_law_content:
        return True, "trang cover/quảng cáo"

    return False, ""


def _to_int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        matched = re.search(r"\d+", value)
        if matched:
            return int(matched.group(0))
    return None


def _resolve_opendataloader_page(node: dict, current_page):
    for key in OPENDL_PAGE_KEYS:
        value = _to_int(node.get(key))
        if value is not None:
            return value

    metadata = node.get("metadata")
    if isinstance(metadata, dict):
        for key in OPENDL_PAGE_KEYS:
            value = _to_int(metadata.get(key))
            if value is not None:
                return value

    return current_page


def _extract_opendataloader_text(node: dict) -> str:
    def _sanitize(value: str) -> str:
        text = value or ""
        text = re.sub(
            r"\d{1,2}/\d{1,2}/\d{2,4},?\s+\d{1,2}:\d{2}\s*(?:am|pm)?\s+about:blank(?:\s+about:blank)?\s+\d+/\d+",
            " ",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(r"\babout:blank\b(?:\s+about:blank)?\s+\d+/\d+", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"[ \t]{2,}", " ", text)
        return text.strip()

    values = []
    for key in OPENDL_TEXT_KEYS:
        raw = node.get(key)
        if isinstance(raw, str):
            raw = _sanitize(raw)
            if raw:
                values.append(raw)
    if not values:
        return ""

    dedup = []
    seen = set()
    for value in values:
        normalized = re.sub(r"\s+", " ", value).strip()
        if normalized in seen:
            continue
        seen.add(normalized)
        dedup.append(value)
    return "\n".join(dedup).strip()


def _iter_opendataloader_children(node: dict) -> list:
    children = []
    seen = set()

    def _push(value):
        if not isinstance(value, (dict, list)):
            return
        ident = id(value)
        if ident in seen:
            return
        seen.add(ident)
        children.append(value)

    for key in OPENDL_CHILD_KEYS:
        value = node.get(key)
        if isinstance(value, list):
            for child in value:
                _push(child)
        else:
            _push(value)

    return children


def _is_opendataloader_noise(text: str) -> bool:
    compact = re.sub(r"\s+", " ", text).strip().lower()
    if not compact:
        return True
    if re.search(r"^\s*about:blank(?:\s+about:blank)?\s+\d+/\d+\s*$", compact):
        return True
    if re.search(r"^\s*\d{1,2}/\d{1,2}/\d{2,4},?\s+\d{1,2}:\d{2}\s*(am|pm)?\s+about:blank.*$", compact):
        return True
    if re.search(r"about:blank\s+about:blank\s+\d+/\d+", compact):
        return True
    if compact in {"about:blank", "about blank"}:
        return True
    return False


def _should_skip_opendataloader_node(node: dict) -> bool:
    node_type = str(node.get("type", "")).strip().lower()
    if node_type in OPENDL_SKIP_TYPES:
        return True
    if node.get("hidden text") is True:
        return True
    return False


def _walk_opendataloader_nodes(node, rows: list, current_page=None) -> int:
    if isinstance(node, list):
        emitted = 0
        for item in node:
            emitted += _walk_opendataloader_nodes(item, rows, current_page=current_page)
        return emitted

    if not isinstance(node, dict):
        return 0

    if _should_skip_opendataloader_node(node):
        # Prune cả subtree của header/footer để tránh lọt rác từ node con.
        return 0

    page = _resolve_opendataloader_page(node, current_page)
    node_type = str(node.get("type", "")).strip().lower()
    children = _iter_opendataloader_children(node)

    emitted_self = 0
    content = _extract_opendataloader_text(node)
    if content and not _is_opendataloader_noise(content):
        should_emit_self = node_type in OPENDL_PREFER_SELF_TYPES or not children
        if should_emit_self:
            page_idx = None
            page_number = _to_int(page)
            if page_number is not None:
                # OpenDataLoader page number là 1-indexed.
                page_idx = max(page_number - 1, 0)
            rows.append((page_idx, content))
            emitted_self += 1

    emitted_children = 0
    for child in children:
        emitted_children += _walk_opendataloader_nodes(child, rows, current_page=page)

    return emitted_self + emitted_children


def _find_opendataloader_json(pdf_path: Path, preprocessed_dir: str) -> Path:
    base_dir = Path(preprocessed_dir)
    candidates = [
        base_dir / f"{pdf_path.stem}.json",
        base_dir / f"{pdf_path.stem}.opendataloader.json",
        base_dir / f"{pdf_path.name}.json",
        pdf_path.with_suffix(".json"),
        pdf_path.with_suffix(".opendataloader.json"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    if base_dir.exists():
        recursive = sorted(
            base_dir.rglob("*.json"),
            key=lambda p: (0 if p.name.startswith(pdf_path.stem) else 1, len(str(p))),
        )
        for candidate in recursive:
            if pdf_path.stem in candidate.stem or pdf_path.stem in candidate.name:
                return candidate

    raise FileNotFoundError(
        f"Không tìm thấy JSON preprocessed cho {pdf_path.name}. "
        f"Đã kiểm tra: {', '.join(str(p) for p in candidates)}"
    )


def _load_pages_from_opendataloader_json(pdf_path: Path, preprocessed_dir: str) -> list:
    json_path = _find_opendataloader_json(pdf_path, preprocessed_dir)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    rows = []
    _walk_opendataloader_nodes(payload, rows, current_page=None)
    if not rows:
        raise ValueError(f"JSON không chứa nội dung text hợp lệ: {json_path}")

    grouped = {}
    fallback_page = None
    for page_idx, text in rows:
        if page_idx is None:
            page_idx = fallback_page if fallback_page is not None else 0
        else:
            fallback_page = page_idx
        grouped.setdefault(page_idx, []).append(text)

    docs = []
    for page_idx in sorted(grouped.keys()):
        merged_parts = []
        seen = set()
        for text in grouped[page_idx]:
            normalized = re.sub(r"\s+", " ", text).strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            merged_parts.append(text.strip())
        merged = "\n".join(merged_parts).strip()
        if not merged:
            continue
        docs.append(
            Document(
                page_content=merged,
                metadata={"page": page_idx, "loader": "opendataloader_json"},
            )
        )
    return docs


def _load_pdf_pages(pdf_path: Path, backend: str) -> list:
    if backend == "opendataloader_json":
        try:
            return _load_pages_from_opendataloader_json(pdf_path, PREPROCESSED_DIR)
        except Exception as e:
            print(f"  [WARN] Không load được backend opendataloader_json: {e}")
            print("  [INFO] Fallback sang PyPDFLoader.")

    loader = PyPDFLoader(str(pdf_path))
    return loader.load()


def load_and_clean_pdfs(data_dir: str) -> list:
    """
    Đọc toàn bộ PDF trong data_dir.
    - Bỏ qua trang cover, mục lục
    - Làm sạch watermark footer
    - Gắn metadata đầy đủ
    """
    pdf_files = list(Path(data_dir).glob("*.pdf"))
    if not pdf_files:
        raise FileNotFoundError(
            f"Không có file PDF trong '{data_dir}'.\n"
            f"Đường dẫn tuyệt đối: {os.path.abspath(data_dir)}"
        )

    all_documents = []
    for pdf_path in pdf_files:
        print(f"  Đang đọc: {pdf_path.name} ... (backend={PDF_BACKEND})")
        pages = _load_pdf_pages(pdf_path, PDF_BACKEND)
        print(f"  Tổng số trang trong file: {len(pages)}")

        kept = skipped = 0
        for idx, page in enumerate(pages, start=1):
            if page.metadata is None:
                page.metadata = {}
            raw_page = (page.metadata or {}).get("page", idx - 1)
            try:
                page_no = int(raw_page) + 1
            except Exception:
                page_no = idx

            # Kiểm tra có bỏ qua trang này không
            skip, reason = should_skip_page(page.page_content)
            if skip:
                skipped += 1
                if skipped <= 5:  # Chỉ in 5 thông báo skip đầu để không spam
                    print(f"    [SKIP] Trang {page_no}: {reason}")
                continue

            # Làm sạch nội dung
            page.page_content = normalize_legal_text(page.page_content)

            # Gắn metadata để Retriever có thể trích dẫn nguồn
            page.metadata["source_file"] = pdf_path.name
            page.metadata["law_name"]    = pdf_path.stem  # Tên file không đuôi
            page.metadata["loader"] = (page.metadata or {}).get("loader", PDF_BACKEND)

            all_documents.append(page)
            kept += 1

        print(f"  → Giữ lại: {kept} trang | Bỏ qua: {skipped} trang")

    return all_documents


def build_article_chunks(documents: list, include_parent: bool = False):
    """
    2 bước:
    A) normalize text (đã xử lý tại load_and_clean_pdfs)
    B) split theo Điều thực sự, rồi subchunk theo từng Điều.
    """
    # Gom text theo file để parse Điều xuyên trang
    grouped_text = {}
    for doc in documents:
        source_file = doc.metadata.get("source_file", "unknown.pdf")
        page_no = int(doc.metadata.get("page", 0)) + 1
        grouped_text.setdefault(source_file, []).append((page_no, doc.page_content))

    chunks = []
    parent_docs = []
    article_parent_index = {}
    article_related_index = {}
    chunk_id = 0
    for source_file, pages in grouped_text.items():
        pages_sorted = sorted(pages, key=lambda x: x[0])
        merged_text = "\n\n".join(text for _, text in pages_sorted)
        page_spans = []
        cursor = 0
        for i, (page_no, text) in enumerate(pages_sorted):
            start = cursor
            cursor += len(text)
            end = cursor
            page_spans.append((page_no, start, end))
            if i < len(pages_sorted) - 1:
                cursor += 2  # separator "\n\n"

        def _char_to_page(char_pos: int) -> int | None:
            if not page_spans:
                return None
            for page_no, start, end in page_spans:
                if start <= char_pos < end:
                    return page_no
            return page_spans[-1][0]

        articles = split_into_articles(merged_text)
        dedup = {}
        for article in articles:
            article_no = article.get("article_number")
            if article_no is None:
                continue
            prev = dedup.get(article_no)
            if prev is None or len(article.get("content", "")) > len(prev.get("content", "")):
                dedup[article_no] = article
        articles = [dedup[k] for k in sorted(dedup.keys())]
        print(f"  {source_file}: tách được {len(articles)} Điều")

        if not articles:
            # Fallback an toàn nếu không parse được Điều
            fallback_canonical_id = f"{source_file}::article::fallback::{uuid.uuid4().hex}"
            fallback_parent_id = _to_docstore_key(fallback_canonical_id)
            parent_docs.append(
                Document(
                    page_content=merged_text,
                    metadata={
                        "doc_id": fallback_parent_id,
                        "canonical_doc_id": fallback_canonical_id,
                        "source_file": source_file,
                        "article_number": None,
                        "article_title": "",
                        "law_name": Path(source_file).stem,
                        "chunk_type": "article_parent",
                        "page_start": pages_sorted[0][0] if pages_sorted else None,
                        "page_end": pages_sorted[-1][0] if pages_sorted else None,
                    },
                )
            )
            fallback_meta = {
                "source_file": source_file,
                "article_number": None,
                "article_title": "",
                "chunk_type": "article_subchunk",
                "page_start": pages_sorted[0][0] if pages_sorted else None,
                "page_end": pages_sorted[-1][0] if pages_sorted else None,
                "dieu_so": None,
                "chunk_id": chunk_id,
                "doc_id": fallback_parent_id,
                "canonical_doc_id": fallback_canonical_id,
            }
            chunks.append(Document(page_content=merged_text, metadata=fallback_meta))
            chunk_id += 1
            continue

        for article in articles:
            # page_start/page_end dựa trên offset ký tự của Điều trong merged_text.
            article["source_file"] = source_file
            article_start = int(article.get("start_char", 0))
            article_end = max(int(article.get("end_char", article_start + 1)) - 1, article_start)
            article["page_start"] = _char_to_page(article_start)
            article["page_end"] = _char_to_page(article_end)
            article_no = article.get("article_number")
            canonical_parent_doc_id = f"{source_file}::article::{article_no}"
            parent_doc_id = _to_docstore_key(canonical_parent_doc_id)
            article["doc_id"] = parent_doc_id
            article["canonical_doc_id"] = canonical_parent_doc_id

            article_docs = subchunk_article(
                article=article,
                chunk_size=CHUNK_SIZE,
                chunk_overlap=CHUNK_OVERLAP,
            )

            # Parent doc lấy từ subchunks đã chuẩn hóa để tránh nuốt header "Mục/Chương"
            # và giữ đúng thứ tự khoản/điểm.
            parent_parts = []
            seen_parts = set()
            for d in sorted(
                article_docs,
                key=lambda x: (
                    (x.metadata or {}).get("subchunk_index", 10**9),
                    (x.metadata or {}).get("chunk_id", 10**9),
                ),
            ):
                text = (d.page_content or "").strip()
                if not text:
                    continue
                key = re.sub(r"\s+", " ", text).strip().lower()
                if key in seen_parts:
                    continue
                seen_parts.add(key)
                parent_parts.append(text)
            parent_content = "\n\n".join(parent_parts).strip() or (article.get("content") or "").strip()
            parent_content = re.sub(
                r"(?mis)\n+\s*(?:Mục\s+\d+\.?|Chương\s+[IVXLC0-9]+\.?).*$",
                "",
                parent_content,
            ).strip()
            related_articles = _extract_related_articles(
                text=parent_content or article.get("content", ""),
                current_article=article_no,
            )
            related_articles_csv = ",".join(str(a) for a in related_articles)

            parent_docs.append(
                Document(
                    page_content=parent_content,
                    metadata={
                        "doc_id": parent_doc_id,
                        "canonical_doc_id": canonical_parent_doc_id,
                        "source_file": source_file,
                        "law_name": Path(source_file).stem,
                        "article_number": article_no,
                        "article_title": article.get("title", ""),
                        "dieu_so": str(article_no) if article_no is not None else None,
                        "chunk_type": "article_parent",
                        "page_start": article.get("page_start"),
                        "page_end": article.get("page_end"),
                        "page": article.get("page_start"),
                        "related_articles_csv": related_articles_csv,
                        "related_articles_count": len(related_articles),
                    },
                )
            )
            if article_no is not None:
                article_parent_index.setdefault(str(article_no), []).append(parent_doc_id)
                article_related_index.setdefault(str(article_no), [])
                for ref_article in related_articles:
                    if ref_article not in article_related_index[str(article_no)]:
                        article_related_index[str(article_no)].append(ref_article)

            for d in article_docs:
                d.metadata["chunk_id"] = chunk_id
                # Compatibility với QA/report cũ
                d.metadata["law_name"] = Path(source_file).stem
                if d.metadata.get("page_start") is not None:
                    d.metadata["page"] = d.metadata.get("page_start")
                d.metadata["related_articles_csv"] = related_articles_csv
                d.metadata["related_articles_count"] = len(related_articles)
                d.metadata["canonical_doc_id"] = canonical_parent_doc_id
                chunks.append(d)
                chunk_id += 1

    if include_parent:
        return chunks, parent_docs, article_parent_index, article_related_index
    return chunks


def create_vector_db(
    chunks: list,
    db_path: str,
    parent_docs: list | None = None,
    article_parent_index: dict | None = None,
    article_related_index: dict | None = None,
):
    """
    Vector hóa child chunks và lưu vào ChromaDB.
    Đồng thời lưu parent docs + index để dùng Parent-Child Retriever lúc runtime.
    Luôn xóa DB cũ → tạo mới để tránh dữ liệu cũ bị trùng.
    """
    print(f"\n  Embedding model: {EMBEDDING_MODEL}")
    embeddings = create_embeddings(EMBEDDING_MODEL)

    target_db_path = _resolve_target_db_path(db_path)
    parent_store_dir = _derive_parent_store_dir(target_db_path)
    parent_index_path = _derive_parent_index_path(target_db_path)

    print(f"  Đang vector hóa {len(chunks)} chunks và lưu vào ChromaDB...")
    print("  (Có thể mất 2–5 phút...)")
    Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        persist_directory=target_db_path,
    )
    print(f"  ✅ ChromaDB đã lưu tại '{target_db_path}'")

    parent_docs = parent_docs or []
    if parent_docs:
        print(f"  Đang lưu {len(parent_docs)} parent docs...")
        byte_store = LocalFileStore(parent_store_dir)
        docstore = create_kv_docstore(byte_store)
        kv_pairs = []
        doc_id_map = {}
        for parent_doc in parent_docs:
            doc_id = (parent_doc.metadata or {}).get("doc_id")
            if not doc_id:
                continue
            safe_key = _to_docstore_key(str(doc_id))
            doc_id_map[str(doc_id)] = safe_key
            kv_pairs.append((safe_key, parent_doc))
        if kv_pairs:
            docstore.mset(kv_pairs)

        safe_article_parent_index = {}
        for article, doc_ids in (article_parent_index or {}).items():
            mapped = []
            seen = set()
            for doc_id in doc_ids:
                safe_key = doc_id_map.get(str(doc_id))
                if not safe_key or safe_key in seen:
                    continue
                seen.add(safe_key)
                mapped.append(safe_key)
            if mapped:
                safe_article_parent_index[str(article)] = mapped

        index_payload = {
            "version": 2,
            "mode": "parent_child",
            "article_to_doc_ids": safe_article_parent_index,
            "article_related_articles": article_related_index or {},
            "parent_store_dir": parent_store_dir,
            "parent_docs_count": len(kv_pairs),
        }
        Path(parent_index_path).write_text(
            json.dumps(index_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"  ✅ Parent index đã lưu tại '{parent_index_path}'")

    return target_db_path, parent_index_path if parent_docs else None


def preview_chunks(chunks: list, n: int = 3):
    """In thử n chunks mẫu để kiểm tra chất lượng."""
    print(f"\n  --- Xem thử {min(n, len(chunks))} chunks mẫu ---")
    for i in range(min(n, len(chunks))):
        c = chunks[i]
        preview = c.page_content[:400].replace("\n", " | ")
        meta    = c.metadata
        print(f"\n  CHUNK {i}:")
        print(f"    Trang    : {meta.get('page','?')}")
        print(f"    Điều     : {meta.get('dieu_so','(không rõ)')}")
        print(f"    Độ dài   : {len(c.page_content)} ký tự")
        print(f"    Nội dung : {preview}...")


def main():
    print("=" * 60)
    print("  INGEST PIPELINE — XÂY DỰNG VECTOR DATABASE")
    print("=" * 60)

    # BƯỚC 1
    print("\n[BƯỚC 1/3] Đọc và làm sạch file PDF...")
    documents = load_and_clean_pdfs(DATA_DIR)
    total_chars = sum(len(d.page_content) for d in documents)
    print(f"\n✅ Xong bước 1: {len(documents)} trang | {total_chars:,} ký tự tổng.")

    # BƯỚC 2
    print("\n[BƯỚC 2/3] Tách theo Điều thật sự và subchunk theo từng Điều...")
    chunks, parent_docs, article_parent_index, article_related_index = build_article_chunks(
        documents, include_parent=True
    )
    avg    = sum(len(c.page_content) for c in chunks) // max(len(chunks), 1)
    print(
        f"\n✅ Xong bước 2: {len(chunks)} child chunks | "
        f"{len(parent_docs)} parent docs | trung bình {avg} ký tự/chunk."
    )
    preview_chunks(chunks, n=3)

    # BƯỚC 3
    print(f"\n[BƯỚC 3/3] Tạo Vector Database...")
    final_db_path, parent_index_path = create_vector_db(
        chunks=chunks,
        db_path=DB_PATH,
        parent_docs=parent_docs,
        article_parent_index=article_parent_index,
        article_related_index=article_related_index,
    )

    print()
    print("=" * 60)
    print(f"✅ HOÀN TẤT! Đã lưu {len(chunks)} chunks vào ChromaDB.")
    print(f"   DB path thực tế: {final_db_path}")
    if parent_index_path:
        print(f"   Parent index: {parent_index_path}")
    print("   Kiểm tra: python diagnose.py")
    print("   Chạy app: python -m streamlit run app.py")
    print("=" * 60)


if __name__ == "__main__":
    main()
