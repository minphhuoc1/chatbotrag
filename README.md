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

LexBot là chatbot RAG tư vấn Bộ luật Lao động Việt Nam 2019. Project tập trung vào retrieval có kiểm soát, citation theo điều luật, guard chống hallucination, multi-turn memory và demo UI chuyên nghiệp bằng Next.js.

> Lưu ý: Đây là project demo kỹ thuật/portfolio, không thay thế tư vấn pháp lý chính thức.

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

## Core Capabilities

- Trả lời câu hỏi pháp luật lao động bằng RAG có citation.
- Phân biệt route: RAG, quote direct, article resolution, rule-based fallback, clarification.
- Citation display tách `Điều chính` và `Dẫn chiếu`.
- Guard cho điều luật ngoài phạm vi, ví dụ Điều 250.
- Guard cho các tình huống sa thải, bỏ việc, đơn phương chấm dứt.
- Module tính trợ cấp thôi việc theo Điều 46.
- Multi-turn memory cho các câu hỏi nối tiếp.
- QA framework gồm internal rubric, regression tests, multi-turn tests và third-party QA runner.

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
api_server.py                         FastAPI adapter for the RAG engine
app.py                                Legacy Streamlit UI for local debugging
frontend/                             Production demo UI
src/legal_chatbot/reasoning_chain.py  Main orchestration and guarded reasoning
src/legal_chatbot/retrieval.py        Hybrid retrieval, BM25/RRF/rerank logic
src/legal_chatbot/policy.py           Legal hints, guards, citation helpers
src/legal_chatbot/severance.py        Severance-pay helper
src/legal_chatbot/config.py           Runtime config and env variables
prompts/system_prompt_guarded.md      Production system prompt
vector_db/                            Prebuilt Chroma DB for demo deploy
test_cases.yaml                       Main legal QA cases
tests/cases/                          Multi-turn and held-out cases
docs/                                 Technical notes, handoff, deployment docs
```

## Local Run

### 1. Backend

```powershell
cd D:\chatbotrag
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
cd D:\chatbotrag\frontend
npm run dev
```

Open:

```text
http://127.0.0.1:3000
```

`frontend/.env.local` for real backend:

```env
USE_MOCK=false
BACKEND_URL=http://127.0.0.1:8007
BACKEND_TIMEOUT_MS=60000
```

## Environment Variables

Copy `.env.example` to `.env` and set at least:

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

Never commit `.env` or `frontend/.env.local`.

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

This repo includes a Docker-based Hugging Face Space setup that keeps the current Next.js UI.

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

See `docs/HUGGINGFACE_DEPLOYMENT.md` for the full deployment checklist.

Current public Space:

```text
https://minphhuoc-lexbotvn.hf.space
```

## Portfolio Notes

This project is intended to demonstrate:

- RAG system design for Vietnamese legal NLP.
- Prompt engineering and guarded legal reasoning.
- Hybrid retrieval and deterministic policy fallback.
- Production-style API/frontend separation.
- Evaluation discipline: regression tests, held-out cases, multi-turn tests and QA gates.
- Deployable AI application architecture.
