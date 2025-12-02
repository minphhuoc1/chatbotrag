# ⚖️ Vietnam Legal AI Assistant (RAG Chatbot)

Một trợ lý ảo AI giúp tra cứu và giải đáp thắc mắc về Luật Lao Động Việt Nam, được xây dựng dựa trên kiến trúc RAG (Retrieval-Augmented Generation).

## 🚀 Tính năng chính
- **Tra cứu chính xác:** Trả lời câu hỏi dựa trên văn bản luật thực tế, giảm thiểu ảo giác (hallucination).
- **Trích dẫn nguồn:** Chỉ rõ điều luật (Điều X, Khoản Y) để người dùng đối chứng.
- **Đa ngôn ngữ:** Hỗ trợ xử lý ngữ nghĩa tiếng Việt tốt nhờ model embedding đa ngữ.

## 🛠️ Công nghệ sử dụng (Tech Stack)
- **LLM:** Google Gemini 1.5 Flash
- **Framework:** LangChain, LangChain Community
- **Vector Database:** ChromaDB
- **Embeddings:** sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
- **Interface:** Streamlit

## 📸 Demo
(Bạn chụp ảnh màn hình giao diện lúc chat thành công và dán vào đây)

## ⚙️ Cài đặt & Chạy
1. Clone repo này về máy.
2. Tạo file `.env` và điền `GOOGLE_API_KEY`.
3. Cài đặt thư viện: `pip install -r requirements.txt`
4. Chạy App: `python -m streamlit run app.py`