import os
from dotenv import load_dotenv
from langchain_community.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma

load_dotenv()
# Đảm bảo đường dẫn file đúng
PDF_PATH = "./data/luatlaodong.pdf" 
DB_PATH = "./vector_db"

def create_vector_db():
    print("--- 1. Đang đọc dữ liệu ---")
    loader = PyPDFLoader(PDF_PATH)
    raw_documents = loader.load()
    
    # --- BƯỚC MỚI: CLEAN DATA ---
    # Loại bỏ các dòng footer gây nhiễu
    cleaned_documents = []
    for doc in raw_documents:
        content = doc.page_content
        # Xóa các dòng rác cụ thể trong file của bạn
        content = content.replace("Downloaded by Ph??c ?oàn Vận Minh (phuocdoan333@gmail.com)", "")
        content = content.replace("studeersnel", "")
        content = content.replace("Dit document is beschikbaar op", "")
        
        doc.page_content = content
        cleaned_documents.append(doc)
    print("✅ Đã làm sạch dữ liệu (loại bỏ watermark).")
    # -----------------------------

    print("--- 2. Chia nhỏ văn bản (New Strategy) ---")
    # Tinh chỉnh chunk size nhỏ hơn cho văn bản luật
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=512, 
        chunk_overlap=128,
        separators=["\nĐiều", "\n\n", "\n", " ", ""] # Ưu tiên cắt theo Điều luật
    )
    texts = text_splitter.split_documents(cleaned_documents)
    print(f"✅ Đã chia thành {len(texts)} chunks nhỏ (tối ưu hóa ngữ nghĩa).")

    print("--- 3. Tạo Vector DB ---")
    embedding_model = HuggingFaceEmbeddings(model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
    
    # Xóa DB cũ nếu cần (hoặc code sẽ tự ghi đè/append tùy thư viện, tốt nhất là xóa folder vector_db thủ công trước khi chạy)
    db = Chroma.from_documents(documents=texts, embedding=embedding_model, persist_directory=DB_PATH)
    print(f"✅ Hoàn tất! Database mới đã sẵn sàng.")

if __name__ == "__main__":
    create_vector_db()