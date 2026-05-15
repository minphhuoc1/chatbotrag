import sys
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage

print("--- KIỂM TRA MÔI TRƯỜNG PYTHON ---")
print(f"Python exe: {sys.executable}")

def test_ollama():
    print("\n--- KIỂM TRA KẾT NỐI OLLAMA ---")
    try:
        # Thử khởi tạo model nhỏ trước
        model_name = "qwen2.5:3b"
        print(f"Đang gọi model: {model_name}...")
        llm = ChatOllama(model=model_name, temperature=0.1)
        
        response = llm.invoke([HumanMessage(content="Chào bạn, đây là một bài test. Trả lời 'ok' nếu bạn nghe thấy.")])
        print(f"✅ Ollama kết nối thành công! Trả lời từ model:\n{response.content}")
    except Exception as e:
        print(f"❌ Lỗi kết nối Ollama: {e}")
        print("💡 Gợi ý:")
        print("1. Chắc chắn bạn đã mở ứng dụng Ollama (có biểu tượng dưới taskbar).")
        print("2. Chắc chắn đã tải model bằng lệnh: ollama pull qwen2.5:3b")

if __name__ == "__main__":
    test_ollama()
