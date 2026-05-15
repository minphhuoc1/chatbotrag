# Hugging Face Spaces Deployment

This repo supports a single-container Hugging Face Space that keeps the current Next.js UI.

## Runtime Layout

```text
Hugging Face Space public port 7860
  -> Next.js frontend
  -> Next.js /api/chat server route
  -> internal FastAPI backend on 127.0.0.1:8007
  -> Chroma vector DB in /app/vector_db
  -> Groq API
```

## Create The Space

Option A - CLI/script deployment:

```powershell
$env:HF_TOKEN='hf_xxx'
python scripts\deploy_hf_space.py --repo-id <username-or-org>/<space-name>
```

You can also place `HF_TOKEN=hf_xxx` in local `.env`; `.env` is ignored by Git.

Option B - manual deployment:

1. Create a new Hugging Face Space.
2. Select `Docker` as the SDK.
3. Connect this GitHub repo or push the same files to the Space repo.
4. Set secrets in Space settings.

Required secret:

```env
GROQ_API_KEY=...
```

Recommended variables:

```env
LEGAL_CHATBOT_LLM_PROVIDER=groq
LEGAL_CHATBOT_REASONER_MODEL=openai/gpt-oss-20b
LEGAL_CHATBOT_ANALYZER_MODEL=llama-3.1-8b-instant
LEGAL_CHATBOT_INTENT_MODEL=llama-3.1-8b-instant
LEGAL_CHATBOT_REASONER_FALLBACK_MODEL=llama-3.1-8b-instant
LEGAL_CHATBOT_ANALYZER_FALLBACK_MODEL=llama-3.1-8b-instant
LEGAL_CHATBOT_INTENT_FALLBACK_MODEL=llama-3.1-8b-instant
LEGAL_CHATBOT_REASONER_MAX_RETRIES=0
LEGAL_CHATBOT_FAST_MAX_RETRIES=0
LEGAL_CHATBOT_EMBED_DEVICE=cpu
USE_MOCK=false
BACKEND_URL=http://127.0.0.1:8007
```

Optional tracing variables should stay disabled for public demo unless you intentionally want traces:

```env
LANGSMITH_TRACING=false
LEGAL_CHATBOT_LANGFUSE_ENABLED=false
LEGAL_CHATBOT_PHOENIX_ENABLED=false
```

## Local Docker Smoke Test

```powershell
docker build -t legal-chatbot-hf .
docker run --rm -p 7860:7860 --env-file .env legal-chatbot-hf
```

Open:

```text
http://127.0.0.1:7860
```

## Notes

- The production vector DB is committed under `vector_db/` so the Space can start without ingesting PDFs at boot.
- Runtime logs are written to `/tmp/legal-chatbot-logs` inside the container.
- Do not commit `.env` or `frontend/.env.local`.
