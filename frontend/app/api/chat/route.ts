import { NextRequest, NextResponse } from "next/server"
import { getMockResponse } from "@/lib/mock-data"

// ── Set USE_MOCK=false in .env.local to forward to real Python backend ────────
const USE_MOCK = process.env.USE_MOCK !== "false"
const BACKEND_URL = process.env.BACKEND_URL || "http://127.0.0.1:8007"
const BACKEND_TIMEOUT_MS = Number(process.env.BACKEND_TIMEOUT_MS || 60_000)

export async function POST(req: NextRequest) {
  const body = await req.json()
  const { message, chat_history = [] } = body

  if (!message?.trim()) {
    return NextResponse.json({ error: "message is required" }, { status: 400 })
  }

  // ── Mock mode ─────────────────────────────────────────────────────────────
  if (USE_MOCK) {
    await new Promise((r) => setTimeout(r, 600 + Math.random() * 800)) // simulate latency
    return NextResponse.json(getMockResponse(message))
  }

  // ── Real backend passthrough ──────────────────────────────────────────────
  // Expects Python backend to expose: POST /api/chat
  // with same request/response contract as this endpoint.
  try {
    const res = await fetch(`${BACKEND_URL}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, chat_history }),
      signal: AbortSignal.timeout(BACKEND_TIMEOUT_MS),
    })

    if (!res.ok) {
      const err = await res.text()
      console.error("[backend error]", res.status, err)
      return NextResponse.json(
        { error: `Backend error: ${res.status}` },
        { status: 502 }
      )
    }

    const data = await res.json()
    return NextResponse.json(data)
  } catch (err) {
    console.error("[backend unreachable]", err)
    return NextResponse.json(
      { error: "Backend không phản hồi. Kiểm tra BACKEND_URL trong .env.local." },
      { status: 503 }
    )
  }
}
