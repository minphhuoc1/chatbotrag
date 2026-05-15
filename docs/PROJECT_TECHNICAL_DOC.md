# Tài liệu Kỹ thuật — Legal RAG Chatbot

> Phiên bản: 2026-04-13 | Model: `qwen2.5:3b` | Stack: LangChain + Streamlit + ChromaDB + Ollama

---

## Mục lục

1. [Tổng quan dự án](#1-tổng-quan-dự-án)
2. [Kiến trúc tổng thể](#2-kiến-trúc-tổng-thể)
3. [Tech Stack](#3-tech-stack)
4. [Luồng dữ liệu end-to-end](#4-luồng-dữ-liệu-end-to-end)
5. [Chi tiết từng module](#5-chi-tiết-từng-module)
6. [Các quyết định kỹ thuật quan trọng](#6-các-quyết-định-kỹ-thuật-quan-trọng)
7. [Vấn đề đã biết & Giới hạn](#7-vấn-đề-đã-biết--giới-hạn)
8. [Cấu trúc thư mục](#8-cấu-trúc-thư-mục)
9. [Hướng phát triển tiếp theo](#9-hướng-phát-triển-tiếp-theo)

---

## 1. Tổng quan dự án

**Legal RAG Chatbot** là hệ thống tư vấn pháp luật lao động Việt Nam chạy hoàn toàn **local** (không cần
internet sau khi setup), tối ưu cho phần cứng giới hạn (GPU GTX 1650, 4GB VRAM).

### Mục tiêu cốt lõi

| Mục tiêu | Chi tiết |
|---|---|
| **Chính xác pháp lý** | Chỉ trả lời dựa trên tài liệu PDF đã nạp — không bịa căn cứ |
| **Mixed-initiative** | Bot chủ động hỏi ngược lại khi câu hỏi thiếu thông tin |
| **Nhớ ngữ cảnh** | Duy trì mạch hội thoại qua nhiều lượt |
| **Local & nhẹ** | Thời gian phản hồi < 35s trên laptop phổ thông |

### Giới hạn rõ ràng

- Chỉ hỗ trợ **Bộ luật Lao động Việt Nam 2019** (file PDF đã nạp vào vector DB)
- Không thay thế luật sư — chỉ hỗ trợ tra cứu
- Độ chính xác phụ thuộc vào chất lượng chunking của PDF nguồn

---

## 2. Kiến trúc tổng thể

```
┌─────────────────────────────────────────────────────────────┐
│                        USER (Streamlit)                      │
└───────────────────────────┬─────────────────────────────────┘
                            │ câu hỏi
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                  INTENT CLASSIFIER (intent.py)               │
│                                                             │
│  Tầng 0: context_carry  — nhận biết follow-up pháp lý      │
│  Tầng 1: Rule-based     — 0ms, không tốn VRAM              │
│  Tầng 2: LLM fallback   — chỉ khi tầng 1 không chắc       │
└────────┬──────────────────────┬──────────────────────────────┘
         │ GREETING/OFF_TOPIC   │ LEGAL
         │ (template sẵn)       ▼
         │         ┌─────────────────────────────────────────┐
         │         │    LEGAL REASONING ENGINE               │
         │         │    (reasoning_chain.py)                 │
         │         │                                         │
         │         │  Bước 4A: ANALYZER (LLM #1, json)      │
         │         │  → Trích xuất keyword → JSON            │
         │         │                                         │
         │         │  Bước 4B: RETRIEVER                     │
         │         │  → Query ChromaDB bằng keyword sạch     │
         │         │                                         │
         │         │  Bước 4C: REASONER (LLM #2, stream)    │
         │         │  → Đọc context + system_prompt.md       │
         │         │  → Sinh câu trả lời tiếng Việt          │
         │         └─────────────────────────────────────────┘
         │                         │ tokens (stream)
         └─────────────────────────┘
                            │
                            ▼
                    ┌───────────────┐
                    │   Streamlit   │
                    │  st.write_   │
                    │   _stream()  │
                    └───────────────┘
```

---

## 3. Tech Stack

### Core

| Thành phần | Công nghệ | Lý do chọn |
|---|---|---|
| **LLM** | `qwen2.5:3b` qua Ollama | Chạy được trên GTX 1650 4GB VRAM; hỗ trợ tiếng Việt tốt nhất trong các model cùng kích thước local |
| **Orchestration** | LangChain (Python) | Chuỗi xử lý rõ ràng, hỗ trợ streaming, prompt template linh hoạt |
| **Vector DB** | ChromaDB | Local, không cần server riêng, persist trên disk, open source |
| **Embedding** | `paraphrase-multilingual-MiniLM-L12-v2` | Hỗ trợ tiếng Việt, nhẹ (67M params), chạy trên CPU |
| **UI** | Streamlit | Prototype nhanh, hỗ trợ `st.write_stream` cho streaming token |
| **Runtime ML** | Ollama | Quản lý model, tối ưu VRAM, expose HTTP API local |
| **Backend compute** | PyTorch | Backend cho sentence-transformers (thay vì TensorFlow/Keras) |

### Dependency constraints quan trọng

```
numpy < 2.0    # chromadb/hnswlib compiled với numpy 1.x — KHÔNG nâng lên 2.x
USE_TF = 0     # Force transformers dùng PyTorch
USE_TORCH = 1  # Tránh lỗi "Keras 3 not supported"
```

---

## 4. Luồng dữ liệu end-to-end

### 4.1 Phase 0 — Xây dựng Vector DB (chạy 1 lần, `ingest.py`)

```
PDF file(s) trong ./data/
        │
        ▼  PyPDFLoader
Raw text theo từng trang
        │
        ▼  Tiền xử lý (ingest.py)
        │   - Gộp 2 trang liền nhau (tránh cắt đứt Điều giữa trang)
        │   - Regex detect số Điều: r"Điều\s+(\d+)"
        │   - Gán metadata: source_file, page, dieu_so
        │
        ▼  RecursiveCharacterTextSplitter
        │   chunk_size=1000, chunk_overlap=200
        │   (1000 chars ≈ 1 Điều hoàn chỉnh)
        │
        ▼  HuggingFaceEmbeddings (MiniLM-L12-v2)
Vectors 384 chiều
        │
        ▼  ChromaDB.persist()
./vector_db/   ← 318 chunks từ Bộ luật Lao động 2019
```

### 4.2 Phase 1 — Xử lý câu hỏi real-time

```
User gõ câu hỏi
        │
        │─── classify_intent(text, llm, chat_history)
        │
        │    Tầng 0: context_carry
        │    Điều kiện: AIMessage cuối chứa "bạn có thể cho biết"
        │               / "lĩnh vực nào" / "thỏa thuận" / ...
        │    Nếu đúng → LEGAL ngay (giữ mạch hội thoại pháp lý)
        │
        │    Tầng 1: Rule-based (0ms)
        │    Có LEGAL_KEYWORD? → LEGAL
        │    Match GREETING_PATTERN + ≤10 từ? → GREETING
        │    Có OFF_TOPIC_KEYWORD? → OFF_TOPIC
        │
        │    Tầng 2: LLM fallback (~3-5s)
        │    Chỉ gọi khi tầng 1 không chắc chắn
        │
        ├── GREETING/OFF_TOPIC
        │   → Trả về template response (không gọi LLM/RAG)
        │
        └── LEGAL → engine.stream(user_input, chat_history)
                │
                │  PHA 1 (blocking ~10-12s)
                │  ┌── Analyzer (LLM #1, format=json)
                │  │   Prompt → JSON {issue, keywords, law_type}
                │  │   Ví dụ: keywords = ["sa thải", "văn bản", "Điều 38"]
                │  │   Fallback: nếu JSON lỗi → dùng nguyên câu user
                │  │
                │  └── Retriever
                │       search_query = " ".join(keywords)  ← keyword sạch
                │       docs = ChromaDB.similarity_search(search_query, k=6)
                │       context_text = join(docs.page_content)
                │
                │  yield ("context", context_text) → Spinner kết thúc
                │
                │  PHA 2 (streaming ~15-20s)
                │  Reasoner (LLM #2, stream)
                │  Input: context + chat_history[-6:] + câu gốc
                │  System: system_prompt.md (State Machine 5 nhóm A-E)
                │
                └── yield ("token", chunk) → st.write_stream() → UI
```

---

## 5. Chi tiết từng module

---

### 5.1 `ingest.py` — Xây dựng Vector DB

**Khi nào chạy:** Chỉ chạy 1 lần, hoặc khi thêm PDF mới vào `./data/`.

**Kỹ thuật đặc biệt — gộp 2 trang liền nhau:**

```python
# Lý do: PDF tiếng Việt hay ngắt trang giữa Điều
# Nếu không gộp → chunk bị đứt giữa nội dung Điều → retriever kéo về chunk không đầy đủ
for i in range(0, len(raw_docs), 2):
    merged_content = page1.content + "\n" + page2.content
```

**Metadata được gán cho mỗi chunk:**

| Field | Nguồn | Dùng để |
|---|---|---|
| `source_file` | Tên file PDF | Biết chunk đến từ đâu |
| `page` | Số trang PDF | Debug, filter nếu cần |
| `dieu_so` | Regex `r"Điều\s+(\d+)"` | Filter theo điều khoản cụ thể (tương lai) |

**Kết quả:** `./vector_db/` chứa 318 chunks, 71% có `dieu_so`.

---

### 5.2 `intent.py` — Phân loại ý định (3 tầng)

**Mục đích:** Phân loại câu hỏi TRƯỚC khi quyết định có gọi RAG không. Nếu là GREETING/OFF_TOPIC → trả template ngay, tiết kiệm ~25s.

**Ba loại intent:**

```python
class Intent(str, Enum):
    GREETING  = "GREETING"   # Chào hỏi, cảm ơn, hỏi về bot
    OFF_TOPIC = "OFF_TOPIC"  # Ngoài phạm vi luật lao động
    LEGAL     = "LEGAL"      # Câu hỏi pháp lý → đi vào RAG
```

**Tầng 0 — Context-carry (quan trọng nhất, mới nhất):**

Giải quyết bug: User trả lời câu hỏi của bot nhưng câu trả lời đó không có keyword pháp lý → bị classify sai thành OFF_TOPIC → bot từ chối chính thông tin nó vừa hỏi user.

```python
# Nếu AIMessage cuối cùng chứa signal "đang hỏi thêm thông tin"
# thì follow-up của user luôn là LEGAL — không cần phân loại lại

asking_followup_signals = [
    "bạn có thể cho biết", "cần thêm thông tin",
    "lĩnh vực nào", "thỏa thuận", "văn bản nào",
    "loại hợp đồng", "thời gian làm việc", ...
]
# Kết quả: source = "context_carry"
```

**Tầng 1 — Rule-based (0ms, không tốn VRAM):**

```python
# Ưu tiên cao nhất:
LEGAL_KEYWORDS  = ["luật", "điều", "khoản", "hợp đồng",
                   "lao động", "sa thải", "bảo hiểm", "thai sản", ...]

GREETING_PATTERNS = [r"^(xin\s+chào|chào|hello|hi)...", ...]

OFF_TOPIC_KEYWORDS = ["bóng đá", "blockchain", "thời tiết",
                      "ăn gì", "lập trình", "python", ...]
```

Logic đánh giá:
1. Có `LEGAL_KEYWORD` → LEGAL ngay (ưu tiên nhất)
2. Câu ≤10 từ + khớp `GREETING_PATTERN` → GREETING
3. Có `OFF_TOPIC_KEYWORD` + không có `LEGAL_KEYWORD` → OFF_TOPIC
4. Không xác định → trả `None` → gọi Tầng 2

**Tầng 2 — LLM fallback (chỉ khi Tầng 1 uncertain):**

```python
INTENT_PROMPT = """Phân loại câu hỏi vào 1 trong 3 nhóm:
- GREETING / LEGAL / OFF_TOPIC
Chỉ trả lời đúng 1 từ.
Câu hỏi: {question}"""

# Lý do không dùng model riêng:
# GTX 1650 chỉ có 4GB VRAM → load 2 model cùng lúc → crash
# Giải pháp: dùng chung llm đang chạy với prompt cực ngắn
```

---

### 5.3 `reasoning_chain.py` — Cỗ máy suy luận 2 bước

**Vấn đề giải quyết:**

Nếu dùng câu hỏi nguyên văn của user để tìm kiếm vector DB, chất lượng sẽ kém vì câu hỏi chứa đại từ nhân xưng, cảm xúc, ngữ cảnh xã hội không liên quan đến văn bản pháp luật.

```
❌ Search: "Hôm qua sếp tôi gọi lên bảo từ mai không cần đến nữa mà chả có giấy tờ"
   → DB tìm: "sếp", "hôm qua", "từ mai" → context kém

✅ Search: "sa thải đơn phương chấm dứt hợp đồng văn bản thông báo"
   → DB tìm: Điều 36, 38, 39 về đơn phương chấm dứt → context đúng
```

**Ba thành phần bên trong:**

#### Analyzer Chain (LLM #1)

```python
self.analyzer_chain = prompt | llm_json | JsonOutputParser()

# Yêu cầu trả về JSON:
{
  "issue": "mô tả vấn đề pháp lý ngắn gọn",
  "keywords": ["từ khóa 1", "từ khóa 2", "Điều 138"],
  "law_type": "luật lao động"
}

# Quy tắc extraction:
# - Nếu user đề cập "Điều X" → BẮT BUỘC đưa vào keywords
# - Không đưa đại từ nhân xưng vào
# - Tối đa 5 keywords

# Fallback nếu JSON parse lỗi:
search_query = user_input  # dùng nguyên câu user
```

#### Retriever (Bước 4B)

```python
search_query = " ".join(keywords)  # "sa thải đơn phương Điều 38"
docs = self.retriever.invoke(search_query)  # k=6 docs
context_text = "\n\n".join(d.page_content for d in docs)
```

#### Reasoner Chain (LLM #2)

```python
self.reasoner_chain = ChatPromptTemplate([
    ("system", system_prompt),    # system_prompt.md với {context}
    MessagesPlaceholder("chat_history"),
    ("human", "{input}")
]) | llm | StrOutputParser()
```

**Hai mode hoạt động:**

```python
# Mode blocking — dùng trong QA test
answer, context_text = engine.run(query, chat_history)

# Mode streaming — dùng trong app UI
# Yield 3 loại event:
# ("analyzing", None)       → Pha 1 đang chạy (hiển thị spinner)
# ("context", context_text) → Retriever xong (tắt spinner, bắt đầu stream)
# ("token", chunk_str)      → Token từ LLM (hiện dần lên UI)
for event_type, payload in engine.stream(query, chat_history):
    ...
```

**Private method `_analyze_and_retrieve()`:**

Chứa logic Bước 4A + 4B, dùng chung cho cả `run()` và `stream()` — tránh duplicate code.

---

### 5.4 `system_prompt.md` — State Machine Prompt

**Triết lý thiết kế:** Toàn bộ hành vi của bot được định nghĩa trong file Markdown, không hard-code trong Python. Muốn thay đổi hành vi → sửa file MD, không cần sửa code.

**Cấu trúc:**

```
⚠️ QUY TẮC NGÔN NGỮ (đặt ĐẦU TIÊN)
│  Lý do: Qwen 3B đọc từ trên xuống trong context window.
│  Đặt lệnh cấm tiếng Trung đầu tiên → hiệu lực cao nhất.
│
├── Vai trò — bot là gì, làm được gì
│
├── Nguồn thông tin được phép — chỉ từ TÀI LIỆU PHÁP LUẬT
│
└── State Machine (5 nhóm hành vi):
    │
    ├── Nhóm A — Ngoài phạm vi
    │   → Từ chối ngắn, không giải thích dài
    │
    ├── Nhóm B — Trong phạm vi nhưng câu hỏi mơ hồ
    │   → Hỏi ngược lại để làm rõ
    │   VD: "Điều 35 nói gì?" → "Bạn đang hỏi về văn bản nào?"
    │
    ├── Nhóm C — Tình huống thực tế thiếu dữ kiện
    │   → Yêu cầu 1-4 thông tin quan trọng nhất
    │   VD: "Tôi bị sa thải" → Hỏi: loại HĐ? lý do? thời gian?
    │
    ├── Nhóm D — Đúng phạm vi nhưng tài liệu không đủ căn cứ
    │   → Nói rõ "chưa đủ căn cứ trong tài liệu hiện có"
    │
    └── Nhóm E — Đủ điều kiện → Trả lời đầy đủ
        Format:
        - Kết luận sơ bộ (1-2 câu)
        - Căn cứ pháp lý (Điều/Khoản/Điểm cụ thể)
        - Phân tích áp dụng vào tình huống user
```

**Placeholder `{context}`:**

```markdown
## TÀI LIỆU PHÁP LUẬT
==================
{context}
==================
```

LangChain fill `{context}` bằng `context_text` từ Retriever khi `invoke({"context": ...})`.

**Lưu ý quan trọng:** Thay đổi file MD có hiệu lực sau khi restart Streamlit, vì nội dung được cache trong `@st.cache_resource`.

---

### 5.5 `app.py` — Giao diện & Điều phối

**Cấu trúc tổng thể (theo thứ tự trong file):**

```python
# 1. Force PyTorch backend TRƯỚC MỌI IMPORT
os.environ["USE_TF"] = "0"
os.environ["USE_TORCH"] = "1"

# 2. Logging — ghi vào file, không spam terminal Streamlit
logging.basicConfig(handlers=[FileHandler("logs/app.log")])

# 3. @st.cache_resource — load tất cả resources 1 lần
@st.cache_resource(show_spinner="⏳ Đang khởi động...")
def load_resources():
    embeddings → vector_db → retriever → llm → llm_json → engine
    return engine, llm, chunk_count

# 4. Import intent ở module level (1 lần, không import trong vòng lặp)
from intent import classify_intent, Intent

# 5. Sidebar — cố định, không bị re-render khi user chat
with st.sidebar:
    st.success/error  # trạng thái
    model, chunk_count  # thông tin hệ thống
    st.button("🗑️ Xóa lịch sử")  # reset session

# 6. Chat loop
for msg in st.session_state.messages:  # render lại history
    st.markdown(msg["content"])

if user_input := st.chat_input(...):
    intent_res = classify_intent(user_input, llm,
                                 chat_history=st.session_state.chat_history)

    if GREETING/OFF_TOPIC:
        st.markdown(template_response)  # tức thì

    else:  # LEGAL
        # PHA 1: Spinner trong khi Analyzer + Retriever chạy
        with st.spinner("🔍 Đang phân tích..."):
            stream_gen = engine.stream(user_input, chat_history)
            for event_type, payload in stream_gen:
                if event_type == "context":
                    context_text = payload
                    break  # Tắt spinner

        # PHA 2: Stream token ra UI
        answer = st.write_stream(token_generator())

        # Nguồn tài liệu
        with st.expander("📄 Tài liệu AI đã tham khảo"):
            st.text(context_text)
```

**Quản lý Session State:**

```python
st.session_state.messages      # List[{role, content}] → render UI
st.session_state.chat_history  # List[HumanMessage|AIMessage] → truyền vào LLM prompt
```

Hai list tách biệt vì mục đích khác nhau: `messages` để render UI (cần format dict); `chat_history` để truyền vào LangChain (cần LangChain Message objects).

---

### 5.6 `qa_test.py` — Bộ kiểm thử hồi quy

Chạy sau mỗi thay đổi lớn để đảm bảo không break tính năng cũ.

**5 nhóm test:**

| Nhóm | Test gì | Cách đánh giá |
|---|---|---|
| **1. DB Integrity** | Số chunks, metadata | Đếm, tỷ lệ |
| **Intent** | 7 câu mẫu phân loại | So predicted vs expected intent |
| **3. LLM Quality** | 4 câu qua full RAG chain | must_contain semantic keywords |
| **4. Memory** | Kịch bản 3 lượt hội thoại | Keywords trong lượt cuối |
| **5. Performance** | Tốc độ Retriever + LLM | Threshold: Retriever <2s, LLM <40s |

**Cách gọi engine trong test (dùng `.run()` thay vì `.stream()`):**

```python
# Blocking để lấy đầy đủ kết quả trước khi evaluate
ans, context_text = chain.run(query, chat_history=[])
```

---

### 5.7 `e2e_test.py` — Kiểm thử hành vi end-to-end

Dùng câu hỏi khác hoàn toàn với `qa_test.py` để tránh overlap. Test từ góc nhìn người dùng thực.

**7 nhóm test:**

| Nhóm | Mục tiêu kiểm tra |
|---|---|
| **A. Greeting/Identity** | Bot tự giới thiệu đúng, nhận dạng chào hỏi |
| **B. Off-topic cứng** | Từ chối bóng đá, nấu ăn, lập trình — tức thì |
| **C. Ambiguous** | Hỏi ngược khi câu mơ hồ (Nhóm B/C của prompt) |
| **D. Full answer** | Câu hỏi rõ → trả lời đầy đủ có trích dẫn điều khoản |
| **E. Language** | Không có ký tự tiếng Trung trong bất kỳ output nào |
| **F. Context-carry** | Follow-up = LEGAL dù không có keyword pháp lý |
| **G. Multi-turn** | Nhớ chủ đề qua 3 lượt hội thoại liên tiếp |

---

## 6. Các quyết định kỹ thuật quan trọng

### 6.1 Tại sao dùng 2 LLM instance khác config?

```python
llm      = ChatOllama(model="qwen2.5:3b", temperature=0.1)
                              # ↑ Free-form text → Reasoner sinh câu tự nhiên
llm_json = ChatOllama(model="qwen2.5:3b", temperature=0.1, format="json")
                              # ↑ Ollama enforce JSON → Analyzer luôn trả dict hợp lệ
```

Cùng 1 model vật lý (dùng chung VRAM) nhưng 2 behavior khác nhau nhờ `format`.

### 6.2 Tại sao giới hạn chat_history khác nhau giữa Analyzer và Reasoner?

```python
limit_history = chat_history[-4:]   # Analyzer: chỉ 4 lượt gần nhất
chat_history[-6:]                    # Reasoner: 6 lượt gần nhất
```

- Analyzer cần biết ngữ cảnh gần nhất để extract keyword đúng chủ đề. Nếu truyền quá nhiều → keyword bị nhiễu, lạc đề.
- Reasoner cần biết nhiều hơn để duy trì mạch hội thoại dài, câu trả lời có chất lượng hơn.

### 6.3 Tại sao Language Lock phải đứng đầu file system_prompt.md?

Qwen 3B (model nhỏ) xử lý context window theo cơ chế attention — các token đầu nhận được attention weight cao hơn. Đặt lệnh cấm tiếng Trung ở phần đầu tiên của prompt → model "nhớ" quy tắc này trong suốt quá trình sinh token.

### 6.4 Tại sao import intent ở module level, không trong vòng lặp?

```python
# Đúng — module level (app.py dòng 62)
from intent import classify_intent, Intent

# Sai (cũ) — trong vòng lặp mỗi lần user chat
if user_input:
    from intent import classify_intent  # Python cache lại nhưng vẫn overhead
```

Streamlit re-render script mỗi khi có interaction. Import ở module level → Python chỉ thực thi import 1 lần, sau đó dùng cache của `sys.modules`.

### 6.5 Tại sao dùng `@st.cache_resource` không phải `@st.cache_data`?

- `@st.cache_data`: Cache dữ liệu serializable (dict, list, DataFrame)
- `@st.cache_resource`: Cache objects không serializable (model, DB connection, engine)

LLM instance, ChromaDB connection, LegalReasoningEngine đều là non-serializable → buộc phải dùng `@st.cache_resource`.

### 6.6 Tại sao phải ghim numpy < 2.0?

ChromaDB sử dụng `hnswlib` (C extension) được compile với numpy 1.x. Numpy 2.0 thay đổi internal struct `dtype` từ 88 bytes → 96 bytes. Khi import ChromaDB với numpy 2.x → size mismatch → crash. Fix: downgrade về `numpy 1.26.4` và ghim trong `requirements.txt`.

---

## 7. Vấn đề đã biết & Giới hạn

| Vấn đề | Mức độ | Trạng thái | Giải thích |
|---|---|---|---|
| **Tiếng Trung trong output** | Trung bình | ✅ Giảm đáng kể | Language lock đầu prompt + quy tắc ngôn ngữ trong reasoning. Qwen 3B vẫn có thể slip đôi khi |
| **Multi-turn lượt 3+ bị OFF_TOPIC** | Trung bình | ⚠️ Cần cải thiện | context_carry chỉ trigger khi AIMessage có "asking signals" rõ ràng. Câu trả lời đầy đủ không kích hoạt signal → lượt tiếp theo bị classify sai |
| **Số Điều trích dẫn đôi khi lệch** | Nhỏ | ⚠️ Known | Khi Analyzer không extract được số Điều → Retriever trả về context có nội dung đúng nhưng không chứa số Điều → LLM tự suy luận số Điều → có thể sai |
| **Phản hồi ~25-35s** | Giới hạn HW | ⚠️ Acceptable | GTX 1650 + 2 lần gọi LLM sequential. Không thể cải thiện nhiều mà không đổi hardware/model |
| **Chỉ hỗ trợ 1 file PDF** | Nhỏ | 🔲 Chưa làm | Bước 6 trong plan: scan toàn bộ `./data/` |

---

## 8. Cấu trúc thư mục

```
chatbotrag/
│
├── app.py                      ← Entry point — Streamlit UI & điều phối
├── intent.py                   ← Intent classifier (3 tầng: context_carry + rule + llm)
├── reasoning_chain.py          ← LegalReasoningEngine (2 bước: Analyzer + Reasoner)
├── ingest.py                   ← Xây dựng Vector DB từ PDF (chạy 1 lần)
│
├── system_prompt.md            ← Toàn bộ hành vi bot (chỉnh tại đây, không sửa code)
├── PROJECT_TECHNICAL_DOC.md    ← File tài liệu này
│
├── qa_test.py                  ← Kiểm thử hồi quy (5 nhóm, chạy sau mỗi thay đổi lớn)
├── e2e_test.py                 ← Kiểm thử hành vi end-to-end (7 nhóm, câu hỏi mới hoàn toàn)
│
├── data/
│   └── luatlaodong.pdf         ← Bộ luật Lao động 2019 (nguồn duy nhất hiện tại)
│
├── vector_db/                  ← ChromaDB persist directory
│   └── ...                        (318 chunks, 384-dim vectors)
│
├── logs/
│   └── app.log                 ← Runtime log với timestamp và log level
│
├── requirements.txt            ← Dependencies (numpy<2.0 ghim cứng)
│
├── qa_report_*.txt             ← Lịch sử chạy qa_test (report 1→7)
└── e2e_report_*.txt            ← Lịch sử chạy e2e_test
```

---

## 9. Hướng phát triển tiếp theo

Theo `implementation_plan.md`:

| Bước | Tính năng | Chi tiết kỹ thuật |
|---|---|---|
| **Bước 5** | TTS (Text-to-Speech) | `edge-tts` + giọng `vi-VN-HoaiMyNeural`, toggle trong sidebar, stream audio |
| **Bước 6** | Multi-file Ingest | Scan toàn bộ `./data/`, hỗ trợ nhiều văn bản pháp luật cùng lúc |
| **Bước 7 (còn lại)** | Polish | Fix multi-turn WARN, streaming UI mượt hơn |

**Cải tiến kỹ thuật cụ thể nên làm:**

1. **Mở rộng `asking_followup_signals`** — thêm signal khi bot trả lời đầy đủ để context-carry hoạt động lượt 3, 4+
2. **Metadata filter trong Retriever** — nếu Analyzer extract được `"Điều 138"`, filter ChromaDB bằng `dieu_so=138` để tăng độ chính xác
3. **Streaming intent LLM** — hiện tại Tầng 2 vẫn blocking ~3-5s; có thể async để UX mượt hơn

---

*Tài liệu được tổng hợp từ toàn bộ quá trình phát triển. Cập nhật lần cuối: 2026-04-13.*
