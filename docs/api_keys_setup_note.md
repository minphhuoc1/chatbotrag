# API Keys Setup Note (Từng loại một)

Mục tiêu: lấy đủ API keys để chạy project RAG + third-party QA stack.

---

## 1) Groq API Key (`GROQ_API_KEY`)

### Dùng cho:
- LLM runtime chính của chatbot.
- Có thể dùng luôn cho Ragas/TruLens nếu bạn cấu hình judge model qua Groq.

### Cách lấy:
1. Vào: `https://console.groq.com`
2. Đăng nhập / tạo tài khoản.
3. Vào phần `API Keys` trong console.
4. Nhấn `Create API Key`.
5. Copy key (thường bắt đầu bằng `gsk_...`) và lưu ngay (key thường chỉ hiện đầy đủ 1 lần).

### Ghi vào `.env`:
```env
GROQ_API_KEY=gsk_xxx_your_key
```

---

## 2) LangSmith API Key (`LANGSMITH_API_KEY`)

### Dùng cho:
- Trace, dataset, experiment tracking trong LangSmith.

### Cách lấy:
1. Vào: `https://smith.langchain.com`
2. Đăng nhập.
3. Vào `Settings` -> `API Keys`.
4. Nhấn `Create API Key`.
5. Copy key và lưu.

### Ghi vào `.env`:
```env
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2_xxx_your_key
LANGSMITH_PROJECT=legal-chatbot-rag
```

---

## 3) Langfuse Keys (`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`)

### Dùng cho:
- Trace + dataset + eval tracking trên Langfuse.

### Cách lấy:
1. Vào: `https://cloud.langfuse.com` (EU) hoặc `https://us.cloud.langfuse.com` (US).
2. Đăng nhập / tạo account.
3. Tạo `Project` mới (hoặc vào project sẵn có).
4. Vào `Project -> Settings -> API Keys`.
5. Tạo/copy:
   - Public key (`pk-lf-...`)
   - Secret key (`sk-lf-...`)

### Ghi vào `.env`:
```env
LEGAL_CHATBOT_LANGFUSE_ENABLED=true
LANGFUSE_PUBLIC_KEY=pk-lf-xxx
LANGFUSE_SECRET_KEY=sk-lf-xxx
LANGFUSE_BASE_URL=https://cloud.langfuse.com
# Nếu dùng US region:
# LANGFUSE_BASE_URL=https://us.cloud.langfuse.com
```

---

## 4) Phoenix API Key (`PHOENIX_API_KEY`) - chỉ khi bật auth

### Dùng cho:
- Quan sát trace/eval local hoặc server Phoenix có authentication.

### Trường hợp A: chạy local nhanh, chưa bật auth
- Không cần `PHOENIX_API_KEY`.

### Trường hợp B: bật auth cho Phoenix
1. Bật auth ở Phoenix deployment (`PHOENIX_ENABLE_AUTH=True` + secret cấu hình server).
2. Đăng nhập Phoenix UI.
3. Vào `Settings -> API Keys`.
4. Tạo `System API Key` (khuyên dùng cho automation) hoặc `User API Key`.
5. Copy key.

### Ghi vào `.env`:
```env
LEGAL_CHATBOT_PHOENIX_ENABLED=true
PHOENIX_API_KEY=phx_xxx_your_key
```

---

## 5) Keys bổ sung cho Ragas/TruLens (tùy model judge)

Ragas/TruLens là thư viện OSS, nhưng metric LLM-based sẽ gọi model provider.

Nếu bạn dùng:
- Groq: dùng `GROQ_API_KEY`
- OpenAI: thêm `OPENAI_API_KEY`
- Anthropic: thêm `ANTHROPIC_API_KEY`
- Provider khác: thêm key tương ứng.

---

## 6) Mẫu `.env` gợi ý (copy nhanh)

```env
# ===== Core LLM =====
GROQ_API_KEY=gsk_xxx_your_key

# ===== LangSmith =====
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2_xxx_your_key
LANGSMITH_PROJECT=legal-chatbot-rag

# ===== Langfuse =====
LEGAL_CHATBOT_LANGFUSE_ENABLED=true
LANGFUSE_PUBLIC_KEY=pk-lf-xxx
LANGFUSE_SECRET_KEY=sk-lf-xxx
LANGFUSE_BASE_URL=https://cloud.langfuse.com

# ===== Phoenix =====
LEGAL_CHATBOT_PHOENIX_ENABLED=true
# Nếu server Phoenix bật auth thì điền thêm:
# PHOENIX_API_KEY=phx_xxx
```

---

## 7) Lưu ý bảo mật

- Không commit `.env` lên git.
- Không gửi key qua chat/email công khai.
- Nếu lộ key: revoke ngay và tạo key mới.
- Nên đặt spend/rate limit ở provider (nhất là Groq/OpenAI).
