#!/usr/bin/env bash
set -euo pipefail

export PORT="${PORT:-7860}"
export USE_MOCK="${USE_MOCK:-false}"
export BACKEND_URL="${BACKEND_URL:-http://127.0.0.1:8007}"
export LEGAL_CHATBOT_LLM_PROVIDER="${LEGAL_CHATBOT_LLM_PROVIDER:-groq}"
export LEGAL_CHATBOT_DB_PATH="${LEGAL_CHATBOT_DB_PATH:-/app/vector_db}"
export LEGAL_CHATBOT_DATA_DIR="${LEGAL_CHATBOT_DATA_DIR:-/app/data}"
export LEGAL_CHATBOT_PROMPTS_DIR="${LEGAL_CHATBOT_PROMPTS_DIR:-/app/prompts}"
export LEGAL_CHATBOT_LOGS_DIR="${LEGAL_CHATBOT_LOGS_DIR:-/tmp/legal-chatbot-logs}"
export HF_HOME="${HF_HOME:-/tmp/huggingface}"
export HF_CACHE_DIR="${HF_CACHE_DIR:-/tmp/huggingface}"

mkdir -p "${LEGAL_CHATBOT_LOGS_DIR}" "${HF_HOME}"

python -m uvicorn api_server:app --host 127.0.0.1 --port 8007 &
backend_pid=$!

cleanup() {
  if kill -0 "${backend_pid}" >/dev/null 2>&1; then
    kill "${backend_pid}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

for i in {1..60}; do
  if python - <<'PY'
import json
import urllib.request

try:
    with urllib.request.urlopen("http://127.0.0.1:8007/api/health", timeout=2) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    raise SystemExit(0 if payload.get("ok") else 1)
except Exception:
    raise SystemExit(1)
PY
  then
    break
  fi

  if ! kill -0 "${backend_pid}" >/dev/null 2>&1; then
    echo "FastAPI backend exited before becoming healthy." >&2
    exit 1
  fi

  sleep 2
  if [ "$i" -eq 60 ]; then
    echo "FastAPI backend did not become healthy in time." >&2
    exit 1
  fi
done

cd /app/frontend
exec npm run start -- -H 0.0.0.0 -p "${PORT}"
