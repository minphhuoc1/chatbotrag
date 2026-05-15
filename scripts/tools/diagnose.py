# -*- coding: utf-8 -*-
"""
Script chẩn đoán toàn bộ pipeline RAG:
- Kiểm tra vector_db có tồn tại không
- Xem thử 5 chunk đầu tiên trong DB
- Test retriever với câu hỏi cụ thể
"""
import os
import sys
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma

DB_PATH = "./vector_db"

def diagnose():
    # 1. Kiem tra DB co ton tai khong
    print("=" * 60)
    print("BUOC 1: Kiem tra Vector DB")
    print("=" * 60)
    if not os.path.exists(DB_PATH):
        print(f"[LOI] Thu muc '{DB_PATH}' KHONG TON TAI!")
        print("-> Ban chua chay ingest.py. Hay chay: python ingest.py")
        sys.exit(1)
    
    print(f"[OK] Thu muc '{DB_PATH}' ton tai.")
    files = os.listdir(DB_PATH)
    total_size = sum(
        os.path.getsize(os.path.join(DB_PATH, f))
        for f in files if os.path.isfile(os.path.join(DB_PATH, f))
    )
    print(f"[OK] So file trong DB: {len(files)} | Tong dung luong: {total_size/1024:.1f} KB")

    # 2. Load DB va dem so luong chunks
    print()
    print("=" * 60)
    print("BUOC 2: Ket noi va dem so chunks trong DB")
    print("=" * 60)
    embeddings = HuggingFaceEmbeddings(
        model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    )
    db = Chroma(persist_directory=DB_PATH, embedding_function=embeddings)
    count = db._collection.count()
    print(f"[OK] Tong so chunks (doan van ban) trong DB: {count}")
    
    if count == 0:
        print("[LOI] DB TRONG RONG! Can chay lai: python ingest.py")
        sys.exit(1)

    # 3. Xem thu 3 chunk dau tien trong DB
    print()
    print("=" * 60)
    print("BUOC 3: Noi dung 3 chunks dau tien trong DB")
    print("=" * 60)
    sample = db._collection.get(limit=3)
    for i, doc_text in enumerate(sample["documents"]):
        print(f"\n--- CHUNK {i+1} ---")
        print(doc_text[:400])
        print("...")

    # 4. Test retriever voi cac cau hoi mau
    print()
    print("=" * 60)
    print("BUOC 4: Test Retriever voi cac cau hoi mau")
    print("=" * 60)
    retriever = db.as_retriever(search_kwargs={"k": 3})
    
    test_queries = [
        "Dieu 35",
        "quyen don phuong cham dut hop dong",
        "nghi phep co luong",
        "luong toi thieu"
    ]
    
    for query in test_queries:
        print(f"\n[QUERY]: '{query}'")
        results = retriever.invoke(query)
        if not results:
            print("  -> KET QUA: KHONG TIM THAY GI!")
        else:
            for j, doc in enumerate(results):
                preview = doc.page_content[:200].replace("\n", " ")
                print(f"  -> DOC {j+1} (trang {doc.metadata.get('page','?')}): {preview}...")
    
    print()
    print("=" * 60)
    print("CHAN DOAN HOAN TAT")
    print("=" * 60)

if __name__ == "__main__":
    diagnose()
