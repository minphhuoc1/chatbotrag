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

Legal chatbots often stop at semantic search: they retrieve passages that look relevant but miss latent legal logic such as limitation periods, contract-ending categories, and statutory exceptions. LexBot upgrades that baseline into a controlled legal-reasoning RAG pipeline where issue routing, hybrid retrieval, policy guards, and citation validation work together before the final answer is returned. The current QA gate passes `33/33` legal cases with a `97.27` average weighted score, including fact-pattern cases for disciplinary limitation periods, fixed-term contract expiry versus unilateral termination, and exceptions to advance-notice obligations. The live demo runs a Next.js interface over a FastAPI RAG backend deployed on Hugging Face Spaces.

> Lưu ý: Đây là project demo kỹ thuật/portfolio, không thay thế tư vấn pháp lý chính thức.

## What This Project Demonstrates

- Legal-reasoning RAG: built a pipeline that turns realistic labor-law situations into legal issues before retrieval, so the bot does not rely only on surface-level semantic similarity.
- Prompt engineering with policy guards: designed system prompts and deterministic safeguards that force grounded answers, scoped legal citations, and clarification when the facts are insufficient.
- Hybrid retrieval engineering: combined vector retrieval, lexical matching, article-number routing, reranking, and metadata boosts to improve recall on Vietnamese legal text.
- Production-style application architecture: separated the AI backend from the user interface using FastAPI, Next.js, typed API payloads, and a Docker-based deployment path.
- Evaluation discipline: built a 33-case QA suite scoring retrieval, grounding, policy behavior, and reasoning separately; added fact-pattern cases after discovering that simple internal tests missed complex legal failures.
- Deployment readiness: packaged the system for Hugging Face Spaces with a prebuilt Chroma vector DB, runtime secrets, health checks, and a public demo URL suitable for recruiter review.

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

- Controlled legal issue spotting: addresses the failure mode where semantic search retrieves the right topic but misses hidden legal conditions such as limitation periods or exceptions.
- Route-aware answering: separates direct article lookup, quote retrieval, RAG reasoning, rule-based fallback, and clarification so each query type receives the safest processing path.
- Primary versus secondary citations: prevents the UI from presenting cross-references as the main legal basis by separating `primary_cited_articles` from `cross_references`.
- Out-of-scope article guard: prevents confident hallucination for invalid article requests such as `Điều 250` when the active labor-law corpus only supports valid article ranges.
- High-risk labor-law guards: handles dismissal, abandonment, unilateral termination, pregnancy protection, and notice-period exceptions with targeted policy checks before final reasoning.
- Deterministic severance helper: handles severance-pay calculation patterns with explicit statutory assumptions instead of leaving arithmetic-heavy cases entirely to the LLM.
- Multi-turn context carry: preserves legally relevant facts across follow-up questions so the analyzer can retrieve based on the whole conversation, not only the latest short message.
- QA-first workflow: treats every new failure as a regression candidate by adding targeted tests, held-out cases, and multi-turn checks instead of patching one prompt answer at a time.

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
