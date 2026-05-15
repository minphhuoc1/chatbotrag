# -*- coding: utf-8 -*-
"""
peek_pdf.py — Xem nhanh nội dung thô của file PDF để hiểu cấu trúc.
Chạy: python peek_pdf.py
"""
from langchain_community.document_loaders import PyPDFLoader

PDF_PATH = "./data/luatlaodong.pdf"

def peek():
    print("Dang doc file PDF...")
    loader = PyPDFLoader(PDF_PATH)
    pages = loader.load()

    print(f"Tong so trang trong PDF: {len(pages)}")
    print("=" * 60)

    # In noi dung thu nghiem cua 3 trang dau
    for i in [0, 1, 2, 5, 10]:
        if i >= len(pages):
            break
        print(f"\n===== TRANG {i+1} (index={i}) =====")
        # In nguyen van khong chinh sua
        print(repr(pages[i].page_content[:800]))
        print()

    # Tim trang co chu "Dieu" de kiem tra cach viet
    print("\n===== TIM TRANG DAU TIEN CO CHU 'Dieu' =====")
    for i, page in enumerate(pages):
        if "Điều" in page.page_content or "dieu" in page.page_content.lower():
            print(f"Trang {i+1}:")
            print(repr(page.page_content[:1200]))
            break

if __name__ == "__main__":
    peek()
