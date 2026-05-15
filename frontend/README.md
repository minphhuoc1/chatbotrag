# LexBot Frontend

Next.js frontend for the Vietnamese Labor Law RAG chatbot.

## Run in mock mode

```powershell
cd D:\chatbotrag\frontend
copy .env.example .env.local
npm install
npm run dev
```

Default `USE_MOCK=true` lets the UI run without Python backend.

## Run with the real RAG backend

In terminal 1:

```powershell
cd D:\chatbotrag
python -m uvicorn api_server:app --host 127.0.0.1 --port 8000
```

In terminal 2:

```powershell
cd D:\chatbotrag\frontend
Set-Content .env.local "USE_MOCK=false`nBACKEND_URL=http://localhost:8000"
npm run dev
```
