FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=7860 \
    USE_MOCK=false \
    BACKEND_URL=http://127.0.0.1:8007 \
    LEGAL_CHATBOT_LLM_PROVIDER=groq \
    LEGAL_CHATBOT_DB_PATH=/app/vector_db \
    LEGAL_CHATBOT_LOGS_DIR=/tmp/legal-chatbot-logs \
    LEGAL_CHATBOT_EMBED_DEVICE=cpu

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates bash build-essential \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-hf.txt ./requirements-hf.txt
RUN pip install --upgrade pip \
    && pip install -r requirements-hf.txt

COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN cd frontend && npm ci

COPY . .
RUN chmod +x scripts/start_hf_space.sh \
    && cd frontend \
    && npm run build

EXPOSE 7860

CMD ["bash", "scripts/start_hf_space.sh"]
