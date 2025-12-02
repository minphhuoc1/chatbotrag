import streamlit as st
# Import các module cần thiết
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_core.prompts import ChatPromptTemplate
from dotenv import load_dotenv

# Import Chain (Cách import chuẩn cho v0.3.0)
from langchain.chains import create_retrieval_chain
from langchain.chains.combine_documents import create_stuff_documents_chain

# 1. Load Config
load_dotenv()
DB_PATH = "./vector_db"

# 2. Setup Page
st.set_page_config(page_title="Trợ lý Luật Lao Động", page_icon="⚖️")
st.title("⚖️ Trợ lý AI Tư vấn Luật")

# 3. Load Resources
@st.cache_resource
def load_chain():
    # Load Embeddings (HuggingFace)
    embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
    
    # Load Vector DB
    vector_db = Chroma(persist_directory=DB_PATH, embedding_function=embeddings)
    retriever = vector_db.as_retriever(search_kwargs={"k": 6})
    
    # Setup LLM (Gemini)
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.2, convert_system_message_to_human=True)    
    # Setup Prompt
    system_prompt = (
        "Bạn là một trợ lý ảo tư vấn luật thông minh. "
        "Sử dụng các đoạn văn bản context sau đây để trả lời câu hỏi. "
        "Nếu không có thông tin, hãy nói 'Tôi không tìm thấy thông tin trong tài liệu'. "
        "Trả lời ngắn gọn và trích dẫn điều luật.\n\n"
        "{context}"
    )
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "{input}"),
    ])
    
    # Tạo Chain
    question_answer_chain = create_stuff_documents_chain(llm, prompt)
    rag_chain = create_retrieval_chain(retriever, question_answer_chain)
    
    return rag_chain

# Khởi tạo chain
try:
    rag_chain = load_chain()
    st.success("✅ Đã kết nối thành công với bộ não AI!")
except Exception as e:
    st.error(f"Lỗi khởi động: {e}")
    st.stop()

# 4. Chat Interface
if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if user_input := st.chat_input("Nhập câu hỏi của bạn..."):
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant"):
        with st.spinner("Đang suy nghĩ..."):
            try:
                response = rag_chain.invoke({"input": user_input})
                answer = response["answer"]
                st.markdown(answer)
                # [DEBUG CODE] - Thêm đoạn này
                print(f"\nQUERY: {user_input}")
                print("-" * 30)
                for i, doc in enumerate(response["context"]):
                    print(f"DOC {i+1} (Page {doc.metadata.get('page')}): {doc.page_content[:150]}...") # In 150 ký tự đầu
                print("-" * 30)
                # -----------------------------
                st.session_state.messages.append({"role": "assistant", "content": answer})
            except Exception as e:
                st.error(f"Lỗi xử lý: {e}")