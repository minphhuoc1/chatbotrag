---
title: LexBot Vietnam Labor Law RAG
emoji: ⚖️
colorFrom: red
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
---

# LexBot - Vietnam Labor Law RAG Assistant

Các chatbot pháp luật thường dừng ở `semantic search`: tìm được đoạn văn bản có vẻ liên quan nhưng bỏ sót logic pháp lý ngầm như thời hiệu, loại chấm dứt hợp đồng, ngoại lệ báo trước hoặc điều kiện áp dụng. LexBot nâng cấp hướng tiếp cận đó thành một pipeline `legal-reasoning RAG` có kiểm soát, trong đó bước nhận diện vấn đề, `hybrid retrieval`, `policy guards` và kiểm tra citation cùng tham gia trước khi trả lời. QA gate hiện tại đạt `33/33 PASS` với `97.27` average weighted score, bao gồm các `fact-pattern` về thời hiệu kỷ luật, hợp đồng hết hạn khác với đơn phương chấm dứt, và ngoại lệ không cần báo trước. Live demo chạy bằng UI Next.js, backend FastAPI và được deploy trên Hugging Face Spaces.

> Lưu ý: Đây là project demo kỹ thuật/portfolio, không thay thế tư vấn pháp lý chính thức.

## What This Project Demonstrates

- Legal-reasoning RAG: xây dựng pipeline biến tình huống lao động thực tế thành các vấn đề pháp lý cần kiểm tra trước khi retrieve, thay vì chỉ dựa vào độ giống ngữ nghĩa bề mặt.
- Prompt engineering với policy guards: thiết kế system prompt và các safeguard xác định để buộc câu trả lời có căn cứ, đúng phạm vi điều luật và biết hỏi lại khi dữ kiện chưa đủ.
- Hybrid retrieval engineering: kết hợp vector retrieval, lexical matching, article-number routing, reranking và metadata boost để tăng khả năng tìm đúng điều luật trong văn bản pháp luật tiếng Việt.
- Production-style application architecture: tách AI backend và UI bằng FastAPI, Next.js, typed API payloads và Docker deployment path để project dễ demo, debug và mở rộng.
- Evaluation discipline: xây bộ QA 33 case chấm riêng retrieval, grounding, policy behavior và reasoning; bổ sung fact-pattern cases sau khi phát hiện bot pass test đơn giản nhưng fail ở tình huống thực tế phức tạp.
- Deployment readiness: đóng gói hệ thống lên Hugging Face Spaces với Chroma vector DB build sẵn, runtime secrets, health checks và public demo URL phù hợp để nhà tuyển dụng review.

## Demo Status

- Live demo: https://minphhuoc-lexbotvn.hf.space
- Hugging Face Space: https://huggingface.co/spaces/minphhuoc/lexbotvn
- Backend: FastAPI + LangChain + ChromaDB
- Frontend: Next.js + Tailwind CSS
- LLM provider: Groq API
- Reasoner mặc định: `openai/gpt-oss-20b`
- Analyzer/Intent mặc định: `llama-3.1-8b-instant`
- Embedding: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
- Vector DB production: `vector_db/`, `314` chunks
- Legal QA gate mới nhất: `33/33 PASS`, average weighted score `97.27`
- Multi-turn context test: `5/5 PASS`
- Held-out raw legal cases: đã bổ sung để kiểm tra generalization

## Key Engineering Decisions

- Controlled legal issue spotting: xử lý lỗi phổ biến khi semantic search tìm đúng chủ đề nhưng bỏ sót điều kiện pháp lý ẩn như thời hiệu, ngoại lệ hoặc loại quan hệ pháp lý.
- Route-aware answering: tách các luồng direct article lookup, quote retrieval, RAG reasoning, rule-based fallback và clarification để mỗi loại câu hỏi đi qua đường xử lý an toàn nhất.
- Primary versus secondary citations: tránh việc UI hiển thị điều luật được nhắc phụ như căn cứ chính bằng cách tách `primary_cited_articles` khỏi `cross_references`.
- Out-of-scope article guard: ngăn bot hallucinate tự tin khi người dùng hỏi điều luật ngoài phạm vi dữ liệu, ví dụ `Điều 250` trong corpus Bộ luật Lao động hiện tại.
- High-risk labor-law guards: thêm kiểm tra có chủ đích cho sa thải, tự ý bỏ việc, đơn phương chấm dứt, bảo vệ lao động mang thai và ngoại lệ nghĩa vụ báo trước.
- Deterministic severance helper: xử lý các câu hỏi tính trợ cấp thôi việc bằng logic có điều kiện rõ ràng thay vì để toàn bộ phép tính cho LLM.
- Multi-turn context carry: giữ lại dữ kiện pháp lý quan trọng qua các câu hỏi nối tiếp để analyzer retrieve theo toàn bộ ngữ cảnh hội thoại, không chỉ câu hỏi ngắn cuối cùng.
- QA-first workflow: biến lỗi mới thành regression candidate bằng targeted tests, held-out cases và multi-turn checks, thay vì vá prompt cho đúng một câu hỏi riêng lẻ.

## Architecture

```text
User
  -> Next.js UI
  -> Next.js /api/chat proxy
  -> FastAPI /api/chat
  -> LegalReasoningEngine
  -> Intent/Analyzer/Policy guards
  -> Hybrid retrieval over ChromaDB
  -> Groq LLM reasoner
  -> Answer + citations + evidence
```

## Important Files

```text
api_server.py                         FastAPI adapter cho RAG engine
app.py                                Legacy Streamlit UI để debug local
frontend/                             UI demo production
src/legal_chatbot/reasoning_chain.py  Logic điều phối chính và guarded reasoning
src/legal_chatbot/retrieval.py        Hybrid retrieval, BM25/RRF/rerank logic
src/legal_chatbot/policy.py           Legal hints, guards, citation helpers
src/legal_chatbot/severance.py        Severance-pay helper
src/legal_chatbot/config.py           Runtime config và env variables
prompts/system_prompt_guarded.md      Production system prompt
vector_db/                            Prebuilt Chroma DB cho demo deploy
test_cases.yaml                       Bộ Legal QA chính
tests/cases/                          Multi-turn và held-out cases
docs/                                 Technical notes, handoff, deployment docs
```

## Local Run

### 1. Backend

```powershell
cd chatbotrag
$env:PYTHONUTF8='1'
python -m uvicorn api_server:app --host 127.0.0.1 --port 8007
```

Health check:

```text
http://127.0.0.1:8007/api/health
```

Expected shape:

```json
{"ok": true, "vector_count": 314}
```

### 2. Frontend

```powershell
cd chatbotrag\frontend
npm run dev
```

Open:

```text
http://127.0.0.1:3000
```

`frontend/.env.local` cho backend thật:

```env
USE_MOCK=false
BACKEND_URL=http://127.0.0.1:8007
BACKEND_TIMEOUT_MS=60000
```

## Environment Variables

Copy `.env.example` thành `.env` và set tối thiểu:

```env
LEGAL_CHATBOT_LLM_PROVIDER=groq
GROQ_API_KEY=...
LEGAL_CHATBOT_REASONER_MODEL=openai/gpt-oss-20b
LEGAL_CHATBOT_ANALYZER_MODEL=llama-3.1-8b-instant
LEGAL_CHATBOT_INTENT_MODEL=llama-3.1-8b-instant
LEGAL_CHATBOT_REASONER_FALLBACK_MODEL=llama-3.1-8b-instant
LEGAL_CHATBOT_ANALYZER_FALLBACK_MODEL=llama-3.1-8b-instant
LEGAL_CHATBOT_INTENT_FALLBACK_MODEL=llama-3.1-8b-instant
LEGAL_CHATBOT_REASONER_MAX_RETRIES=0
LEGAL_CHATBOT_FAST_MAX_RETRIES=0
```

Không commit `.env` hoặc `frontend/.env.local`.

## QA

Main gate:

```powershell
$env:PYTHONUTF8='1'
python test_legal_qa.py --report-path reports\legal_qa\after_reasoning_upgrade.json
```

Multi-turn:

```powershell
python tests\test_multi_turn.py
```

Targeted quality subset:

```powershell
python tests\test_answer_quality_subset.py
```

Third-party QA runner:

```powershell
python scripts\third_party_qa_runner.py
```

## Hugging Face Deployment

Repo này có Docker-based Hugging Face Space setup và vẫn giữ UI Next.js hiện tại.

```text
Public Space port 7860
  -> Next.js UI
  -> internal FastAPI backend on 127.0.0.1:8007
```

Files:

```text
Dockerfile
requirements-hf.txt
scripts/start_hf_space.sh
docs/HUGGINGFACE_DEPLOYMENT.md
```

Required Space secret:

```env
GROQ_API_KEY=...
```

Recommended Space variables:

```env
USE_MOCK=false
BACKEND_URL=http://127.0.0.1:8007
LEGAL_CHATBOT_EMBED_DEVICE=cpu
LANGSMITH_TRACING=false
LEGAL_CHATBOT_LANGFUSE_ENABLED=false
LEGAL_CHATBOT_PHOENIX_ENABLED=false
```

Xem `docs/HUGGINGFACE_DEPLOYMENT.md` để biết checklist deploy đầy đủ.

Current public Space:

```text
https://minphhuoc-lexbotvn.hf.space
```
