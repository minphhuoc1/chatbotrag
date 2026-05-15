# -*- coding: utf-8 -*-
"""
analyze_pdf.py — Quét TOÀN BỘ file PDF, tìm tất cả pattern và vấn đề.
Mục đích: cung cấp dữ liệu đầy đủ để viết ingest.py chính xác.
Chạy: python analyze_pdf.py
Kết quả sẽ được lưu vào: pdf_analysis_report.txt
"""

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from langchain_community.document_loaders import PyPDFLoader

PDF_PATH    = "./data/luatlaodong.pdf"
REPORT_PATH = "./pdf_analysis_report.txt"

# ── Helpers ──────────────────────────────────────────────────────────────────

def find_all(pattern: str, text: str, flags=0) -> list:
    return re.findall(pattern, text, flags)


# ── Phân tích ─────────────────────────────────────────────────────────────────

def analyze(pages: list) -> dict:
    result = {
        "total_pages"          : len(pages),
        "page_lengths"         : [],      # ký tự mỗi trang
        "empty_pages"          : [],      # index trang trắng
        "watermark_pages"      : [],      # index trang chứa watermark
        "watermark_patterns"   : Counter(),  # pattern watermark nào xuất hiện nhiều
        "dieu_formats"         : Counter(),  # format xuất hiện trước "Điều X"
        "chuong_formats"       : Counter(),  # format của Chương
        "page_number_formats"  : Counter(),  # pattern số trang đầu trang
        "ocr_artifacts"        : Counter(),  # khoảng trắng sai trong từ
        "special_chars"        : Counter(),  # ký tự đặc biệt lạ
        "long_lines"           : [],      # dòng > 200 ký tự (dính dòng)
        "dieu_list"            : [],      # danh sách tất cả Điều tìm được
        "pages_without_dieu"   : [],      # trang không có Điều nào
        "raw_samples"          : {},      # repr() của 1 đoạn mỗi trang
    }

    # Pattern watermark phổ biến trong PDF Studocu
    watermark_checks = {
        "lOMoARcPSD"        : r"lOMoAR[^\s]*",
        "Downloaded by"     : r"Downloaded by .+",
        "Studeersnel"       : r"[Ss]tudeersnel",
        "Studocu"           : r"[Ss]tudocu",
        "Scan to open"      : r"Scan to open",
        "Dit document"      : r"Dit document",
    }

    for idx, page in enumerate(pages):
        raw = page.page_content

        # Độ dài trang
        result["page_lengths"].append(len(raw))

        # Trang trắng / rất ngắn
        if len(raw.strip()) < 30:
            result["empty_pages"].append(idx + 1)
            continue

        # Lưu repr() đoạn đầu mỗi trang (200 ký tự) để xem ký tự thực
        result["raw_samples"][idx + 1] = repr(raw[:200])

        # ── Watermark ────────────────────────────────────────────────────────
        page_has_watermark = False
        for label, pattern in watermark_checks.items():
            hits = find_all(pattern, raw)
            if hits:
                result["watermark_patterns"][label] += len(hits)
                page_has_watermark = True
        if page_has_watermark:
            result["watermark_pages"].append(idx + 1)

        # ── Format Số Trang đứng đầu trang ──────────────────────────────────
        # Ví dụ tìm thấy: '1 \n \n', '10 \n \n', '\n5\n'
        page_num_match = re.match(r"^(\d{1,3})\s*\n", raw.strip())
        if page_num_match:
            result["page_number_formats"][f"^{page_num_match.group(0)!r}"] += 1

        # ── Format trước "Điều" ───────────────────────────────────────────────
        # Lấy 5 ký tự đứng ngay trước "Điều X" để biết separator thực sự
        for m in re.finditer(r".{0,6}Điều\s+\d+", raw):
            prefix = m.group()[:6]
            result["dieu_formats"][repr(prefix)] += 1

        # Danh sách Điều xuất hiện trong trang này
        dieus_in_page = re.findall(r"Điều\s+(\d+)", raw)
        result["dieu_list"].extend(dieus_in_page)
        if not dieus_in_page:
            result["pages_without_dieu"].append(idx + 1)

        # ── Format Chương ─────────────────────────────────────────────────────
        for m in re.finditer(r".{0,6}Chương\s+[IVXLCDM\d]+", raw):
            prefix = m.group()[:6]
            result["chuong_formats"][repr(prefix)] += 1

        # ── OCR Artifact — khoảng trắng sai giữa từ ─────────────────────────
        # Tìm pattern: chữ + dấu + khoảng trắng + chữ thường (dấu hiệu OCR tách từ)
        ocr_hits = re.findall(r"[a-zA-ZÀ-ỹắằẳẵặấầẩẫậéèẻẽẹ]\s{1}[a-zA-ZÀ-ỹắằẳẵặấầẩẫậéèẻẽẹ](?=[a-zA-ZÀ-ỹ])", raw)
        for hit in ocr_hits:
            result["ocr_artifacts"][hit] += 1

        # ── Ký tự đặc biệt / lạ ─────────────────────────────────────────────
        # Tìm ký tự ngoài ASCII và unicode tiếng Việt thông thường
        special = re.findall(r"[^\x00-\x7FÀÁÂÃÈÉÊÌÍÒÓÔÕÙÚÝàáâãèéêìíòóôõùúýĂăĐđƠơƯư"
                             r"Ạ-ỹẮắẰằẲẳẴẵẶặẤấẦầẨẩẪẫẬậ\s\-\.,:;!?()/\"\'%0-9]", raw)
        for ch in special:
            result["special_chars"][ch] += 1

        # ── Dòng quá dài (dính dòng) ─────────────────────────────────────────
        for line in raw.split("\n"):
            if len(line) > 200:
                result["long_lines"].append((idx + 1, line[:120] + "..."))

    return result


# ── Viết báo cáo ──────────────────────────────────────────────────────────────

def write_report(r: dict, path: str):
    lines = []
    w = lines.append  # shortcut

    w("=" * 70)
    w("  BÁO CÁO PHÂN TÍCH TOÀN BỘ FILE PDF")
    w("=" * 70)

    w(f"\n📄 TỔNG QUÁT")
    w(f"  Tổng số trang       : {r['total_pages']}")
    avg = sum(r['page_lengths']) // max(len(r['page_lengths']), 1)
    w(f"  Độ dài trung bình   : {avg} ký tự/trang")
    w(f"  Trang ngắn nhất     : {min(r['page_lengths'])} ký tự (trang {r['page_lengths'].index(min(r['page_lengths']))+1})")
    w(f"  Trang dài nhất      : {max(r['page_lengths'])} ký tự (trang {r['page_lengths'].index(max(r['page_lengths']))+1})")
    w(f"  Trang trắng/rất ngắn: {r['empty_pages']}")

    w(f"\n🚿 WATERMARK")
    w(f"  Trang có watermark  : {r['watermark_pages']}")
    w(f"  Pattern xuất hiện   :")
    for label, count in r["watermark_patterns"].most_common():
        w(f"    {label:30s}: {count} lần")

    w(f"\n📌 FORMAT ĐIỀU LUẬT (ký tự TRƯỚC 'Điều X')")
    w("  → Dùng để xác định separator chính xác cho chunk:")
    for fmt, count in r["dieu_formats"].most_common(10):
        w(f"    {fmt:30s}: {count} lần")

    w(f"\n📌 FORMAT CHƯƠNG")
    for fmt, count in r["chuong_formats"].most_common(10):
        w(f"    {fmt:30s}: {count} lần")

    w(f"\n🔢 FORMAT SỐ TRANG ĐẦU TRANG")
    w("  → Dùng để viết regex xóa số trang:")
    for fmt, count in r["page_number_formats"].most_common(10):
        w(f"    {fmt:30s}: {count} trang")

    dieu_unique = sorted(set(int(x) for x in r["dieu_list"] if x.isdigit()))
    w(f"\n⚖️  ĐIỀU LUẬT")
    w(f"  Tổng số lần 'Điều X' xuất hiện : {len(r['dieu_list'])}")
    w(f"  Số Điều khác nhau tìm thấy     : {len(dieu_unique)}")
    if dieu_unique:
        w(f"  Điều nhỏ nhất → lớn nhất       : Điều {min(dieu_unique)} → Điều {max(dieu_unique)}")
        # Tìm Điều bị thiếu
        full_range = set(range(min(dieu_unique), max(dieu_unique)+1))
        missing = full_range - set(dieu_unique)
        if missing:
            w(f"  Điều bị thiếu (không tìm thấy): {sorted(missing)}")
        else:
            w(f"  Tất cả Điều trong khoảng trên đều có mặt.")
    w(f"  Trang không có Điều nào        : {r['pages_without_dieu']}")

    w(f"\n🔧 LỖI OCR (khoảng trắng sai giữa từ)")
    w("  → Dùng để viết regex sửa lỗi OCR trong clean_text():")
    if r["ocr_artifacts"]:
        for art, count in r["ocr_artifacts"].most_common(20):
            w(f"    {repr(art):20s}: {count} lần")
    else:
        w("    Không phát hiện lỗi OCR đáng kể.")

    w(f"\n❓ KÝ TỰ ĐẶC BIỆT / LẠ")
    if r["special_chars"]:
        for ch, count in r["special_chars"].most_common(15):
            w(f"    {repr(ch):10s}: {count} lần")
    else:
        w("    Không có ký tự bất thường.")

    if r["long_lines"]:
        w(f"\n⚠️  DÒNG QUÁ DÀI (>200 ký tự) — có thể bị dính dòng")
        for page, line in r["long_lines"][:10]:
            w(f"  Trang {page}: {line}")
    else:
        w(f"\n✅ Không có dòng nào quá dài.")

    w(f"\n📖 MẪU repr() ĐẦU MỖI TRANG (200 ký tự đầu)")
    w("  → Kiểm tra pattern số trang, watermark, cấu trúc")
    for page_num in sorted(r["raw_samples"].keys()):
        w(f"\n  -- TRANG {page_num} --")
        w(f"  {r['raw_samples'][page_num]}")

    w("\n" + "=" * 70)
    w("  KẾT LUẬN & ĐỀ XUẤT CHO ingest.py")
    w("=" * 70)
    # Tự suy luận đề xuất từ dữ liệu
    top_dieu_fmt = r["dieu_formats"].most_common(1)
    if top_dieu_fmt:
        w(f"\n  SEPARATOR PHÙ HỢP NHẤT : dựa trên format '{top_dieu_fmt[0][0]}' xuất hiện {top_dieu_fmt[0][1]} lần")
    if r["watermark_pages"]:
        w(f"  TRANG CẦN BỎ QUA      : {r['watermark_pages']}")
    top_ocr = r["ocr_artifacts"].most_common(5)
    if top_ocr:
        w(f"  LỖI OCR CẦN SỬA      :")
        for art, cnt in top_ocr:
            w(f"    regex: {repr(art)} → xuất hiện {cnt} lần")

    report_text = "\n".join(lines)

    # Ghi file
    with open(path, "w", encoding="utf-8") as f:
        f.write(report_text)

    # In ra terminal
    print(report_text)
    print(f"\n\n✅ Báo cáo đã được lưu vào: {path}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"Đang đọc toàn bộ {PDF_PATH}...")
    loader = PyPDFLoader(PDF_PATH)
    pages  = loader.load()
    print(f"Đã đọc {len(pages)} trang. Đang phân tích...\n")

    result = analyze(pages)
    write_report(result, REPORT_PATH)


if __name__ == "__main__":
    main()
