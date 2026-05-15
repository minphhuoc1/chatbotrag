"use client"

import { FormEvent, useEffect, useMemo, useRef, useState } from "react"
import {
  AlertCircle,
  Bot,
  CheckCircle2,
  Database,
  FileCheck2,
  History,
  Loader2,
  Scale,
  Send,
  ShieldCheck,
  Sparkles,
  User,
} from "lucide-react"

import { ArticleCard } from "@/components/ArticleCard"
import { RouteBadge } from "@/components/RouteBadge"
import { DEMO_SCENARIOS } from "@/lib/mock-data"
import type { ChatResponse, Message } from "@/lib/types"
import { cn, generateId } from "@/lib/utils"

const initialMessage: Message = {
  id: "welcome",
  role: "assistant",
  content:
    "Chào bạn. Mình là trợ lý tư vấn Bộ luật Lao động Việt Nam 2019. Hãy mô tả tình huống cụ thể, mình sẽ tra cứu điều luật liên quan và nêu căn cứ rõ ràng.",
  timestamp: new Date(),
}

function InlineMarkdown({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g)
  return (
    <>
      {parts.map((part, index) => {
        if (part.startsWith("**") && part.endsWith("**")) {
          return <strong key={index}>{part.slice(2, -2)}</strong>
        }
        return <span key={index}>{part}</span>
      })}
    </>
  )
}

function AnswerText({ text }: { text: string }) {
  const lines = text.split("\n")
  return (
    <div className="answer-prose">
      {lines.map((line, index) => {
        const trimmed = line.trim()
        if (!trimmed) return <div key={index} className="h-2" />
        if (trimmed.startsWith("- ")) {
          return (
            <div key={index} className="flex gap-2">
              <span className="mt-2 h-1.5 w-1.5 flex-shrink-0 rounded-full bg-teal" />
              <p className="mb-1">
                <InlineMarkdown text={trimmed.slice(2)} />
              </p>
            </div>
          )
        }
        return (
          <p key={index}>
            <InlineMarkdown text={trimmed} />
          </p>
        )
      })}
    </div>
  )
}

function MetricCard({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Database
  label: string
  value: string
}) {
  return (
    <div className="rounded-lg border border-border bg-surface/70 p-3 shadow-card">
      <div className="mb-2 flex items-center gap-2 text-ink-faint">
        <Icon size={14} />
        <span className="label-legal">{label}</span>
      </div>
      <div className="font-mono text-sm font-semibold text-ink">{value}</div>
    </div>
  )
}

function ChatBubble({ message }: { message: Message }) {
  const isUser = message.role === "user"
  return (
    <div className={cn("flex gap-3 animate-slide-up", isUser && "flex-row-reverse")}>
      <div
        className={cn(
          "flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full border",
          isUser
            ? "border-legal-red/20 bg-legal-red text-white"
            : "border-teal/20 bg-teal-light text-teal"
        )}
      >
        {isUser ? <User size={15} /> : <Bot size={15} />}
      </div>
      <div
        className={cn(
          "max-w-[86%] rounded-2xl border px-4 py-3 shadow-card",
          isUser
            ? "border-legal-red/15 bg-legal-red text-white"
            : "border-border bg-surface"
        )}
      >
        {message.meta?.route && (
          <div className="mb-2 flex items-center gap-2">
            <RouteBadge route={message.meta.route} size="sm" />
            {message.meta.validation?.grounded && (
              <span className="inline-flex items-center gap-1 rounded bg-teal-light px-1.5 py-0.5 font-mono text-2xs text-teal">
                <CheckCircle2 size={10} />
                có căn cứ
              </span>
            )}
          </div>
        )}
        {isUser ? (
          <p className="text-sm leading-relaxed">{message.content}</p>
        ) : (
          <AnswerText text={message.content} />
        )}
      </div>
    </div>
  )
}

function EvidencePanel({ response }: { response?: ChatResponse }) {
  const primaryArticles = response?.primary_cited_articles?.length
    ? response.primary_cited_articles
    : response?.cited_articles ?? []
  const crossReferences = response?.cross_references ?? []
  const cited = useMemo(() => new Set(primaryArticles), [primaryArticles])

  if (!response) {
    return (
      <aside className="hidden border-l border-border bg-surface/50 lg:flex lg:flex-col">
        <div className="border-b border-border p-4">
          <p className="label-legal">Căn cứ</p>
          <h2 className="heading-serif mt-1 text-xl">Chưa có truy xuất</h2>
        </div>
        <div className="flex flex-1 items-center justify-center p-6 text-center text-sm text-ink-muted">
          Gửi một câu hỏi để xem luồng xử lý, điều luật được trích dẫn và tài liệu hệ thống đã sử dụng.
        </div>
      </aside>
    )
  }

  return (
    <aside className="hidden border-l border-border bg-surface/50 lg:flex lg:flex-col">
      <div className="border-b border-border p-4">
        <div className="mb-2 flex items-center justify-between gap-2">
          <p className="label-legal">Căn cứ</p>
          <RouteBadge route={response.route || "unknown"} size="sm" />
        </div>
        <h2 className="heading-serif text-xl">Căn cứ pháp lý</h2>
        <p className="mt-1 text-xs text-ink-muted">
          Điều chính: {primaryArticles.length ? primaryArticles.map((a) => `Điều ${a}`).join(", ") : "không có"}
        </p>
        {crossReferences.length ? (
          <p className="mt-1 text-2xs text-ink-faint">
            Dẫn chiếu trong nội dung: {crossReferences.map((a) => `Điều ${a}`).join(", ")}
          </p>
        ) : null}
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
        {response.validation?.reason && (
          <div className="rounded-lg border border-border bg-surface p-3 text-xs text-ink-muted">
            <div className="mb-1 flex items-center gap-1.5 font-mono font-semibold text-ink">
              <ShieldCheck size={13} />
              Kiểm chứng
            </div>
            {response.validation.reason}
          </div>
        )}

        {response.retrieved_articles.length ? (
          response.retrieved_articles.map((article, index) => (
            <ArticleCard
              key={`${article.article_number}-${index}`}
              article={article}
              rank={index + 1}
              isCited={cited.has(article.article_number)}
            />
          ))
        ) : (
          <div className="rounded-lg border border-dashed border-border p-4 text-center text-xs text-ink-muted">
            Luồng này không cần truy xuất tài liệu.
          </div>
        )}
      </div>
    </aside>
  )
}

export default function HomePage() {
  const [messages, setMessages] = useState<Message[]>([initialMessage])
  const [input, setInput] = useState("")
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState("")
  const endRef = useRef<HTMLDivElement | null>(null)
  const inputRef = useRef<HTMLTextAreaElement | null>(null)

  const latestResponse = useMemo(
    () => [...messages].reverse().find((msg) => msg.role === "assistant" && msg.meta)?.meta,
    [messages]
  )

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" })
  }, [messages, isLoading])

  useEffect(() => {
    ;(window as Window & { __LEXBOT_READY__?: boolean }).__LEXBOT_READY__ = true
  }, [])

  async function sendMessage(content: string) {
    const trimmed = content.trim()
    if (!trimmed || isLoading) return

    setError("")
    const userMessage: Message = {
      id: generateId(),
      role: "user",
      content: trimmed,
      timestamp: new Date(),
    }

    const history = messages
      .filter((msg) => msg.id !== "welcome")
      .map((msg) => ({ role: msg.role, content: msg.content }))

    setMessages((prev) => [...prev, userMessage])
    setInput("")
    setIsLoading(true)

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: trimmed, chat_history: history }),
      })

      if (!response.ok) {
        const payload = await response.json().catch(() => ({}))
        throw new Error(payload.error || `Request failed: ${response.status}`)
      }

      const data = (await response.json()) as ChatResponse
      setMessages((prev) => [
        ...prev,
        {
          id: generateId(),
          role: "assistant",
          content: data.answer,
          timestamp: new Date(),
          meta: data,
        },
      ])
    } catch (err) {
      const message = err instanceof Error ? err.message : "Không thể gọi API."
      setError(message)
      setMessages((prev) => [
        ...prev,
        {
          id: generateId(),
          role: "assistant",
          content:
            "Mình chưa kết nối được máy chủ xử lý. Nếu chỉ xem giao diện, hãy bật `USE_MOCK=true`; nếu muốn dùng hệ thống thật, hãy chạy Python API server và đặt `USE_MOCK=false`.",
          timestamp: new Date(),
          meta: {
            answer: "",
            route: "error",
            cited_articles: [],
            retrieved_articles: [],
            validation: { grounded: false, reason: message },
          },
        },
      ])
    } finally {
      setIsLoading(false)
    }
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    void sendMessage(inputRef.current?.value ?? input)
  }

  return (
    <main className="grid h-dvh max-h-dvh overflow-hidden grid-cols-1 bg-porcelain text-ink lg:grid-cols-[280px_minmax(0,1fr)_360px]">
      <section className="hidden h-dvh min-h-0 overflow-hidden border-r border-border bg-porcelain/95 p-4 lg:flex lg:flex-col">
        <div className="mb-6">
          <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-xl bg-legal-red text-white shadow-card">
            <Scale size={22} />
          </div>
          <p className="label-legal">Trợ lý luật lao động Việt Nam</p>
          <h1 className="heading-serif mt-1 text-3xl leading-tight">LexBot</h1>
          <p className="mt-3 text-sm leading-relaxed text-ink-muted">
            Hệ thống hỏi đáp pháp luật lao động dựa trên truy xuất tài liệu, trích dẫn điều luật và hiển thị căn cứ sử dụng.
          </p>
        </div>

        <div className="grid gap-2">
          <MetricCard icon={Database} label="Văn bản" value="Bộ luật Lao động 2019" />
          <MetricCard icon={FileCheck2} label="Độ tin cậy" value="33/33 ca kiểm thử đạt" />
          <MetricCard icon={History} label="Hội thoại" value="Nhớ ngữ cảnh nhiều lượt" />
        </div>

        <div className="mt-6 min-h-0 flex-1">
          <div className="mb-2 flex items-center gap-2">
            <Sparkles size={14} className="text-legal-red" />
            <p className="label-legal">Tình huống mẫu</p>
          </div>
          <div className="max-h-full space-y-2 overflow-y-auto pr-1">
            {DEMO_SCENARIOS.map((scenario) => (
              <button
                key={scenario.id}
                type="button"
                onClick={() => void sendMessage(scenario.prompt)}
                className="w-full rounded-lg border border-border bg-surface p-3 text-left shadow-card transition hover:border-border-strong hover:shadow-card-hover disabled:opacity-50"
                disabled={isLoading}
              >
                <div className="mb-1 flex items-center justify-between gap-2">
                  <span className="text-sm font-semibold text-ink">{scenario.label}</span>
                  <span className="rounded bg-surface-raised px-1.5 py-0.5 font-mono text-2xs text-ink-muted">
                    {scenario.tag}
                  </span>
                </div>
                <p className="line-clamp-2 text-xs leading-relaxed text-ink-muted">
                  {scenario.prompt}
                </p>
              </button>
            ))}
          </div>
        </div>
      </section>

      <section className="relative flex h-dvh min-h-0 flex-col overflow-hidden">
        <header className="flex-none border-b border-border bg-porcelain/90 px-4 py-3 backdrop-blur">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="label-legal">Trợ lý pháp lý</p>
              <h2 className="heading-serif text-xl">Tư vấn pháp luật lao động</h2>
            </div>
            {latestResponse?.route ? <RouteBadge route={latestResponse.route} /> : null}
          </div>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5">
          <div className="mx-auto flex max-w-3xl flex-col gap-4">
            {messages.map((message) => (
              <ChatBubble key={message.id} message={message} />
            ))}
            {isLoading && (
              <div className="flex gap-3">
                <div className="flex h-8 w-8 items-center justify-center rounded-full border border-teal/20 bg-teal-light text-teal">
                  <Bot size={15} />
                </div>
                <div className="rounded-2xl border border-border bg-surface px-4 py-3 shadow-card">
                  <div className="flex items-center gap-2 text-sm text-ink-muted">
                    <Loader2 size={15} className="animate-spin" />
                    Đang phân loại câu hỏi, truy xuất điều luật và kiểm tra căn cứ...
                  </div>
                </div>
              </div>
            )}
            <div ref={endRef} />
          </div>
        </div>

        <div className="sticky bottom-0 z-20 flex-none border-t border-border bg-porcelain/95 p-4 shadow-[0_-8px_24px_rgba(0,0,0,0.04)]">
          {error && (
            <div className="mx-auto mb-3 flex max-w-3xl items-start gap-2 rounded-lg border border-legal-red/20 bg-legal-red-light p-3 text-xs text-legal-red">
              <AlertCircle size={14} className="mt-0.5 flex-shrink-0" />
              {error}
            </div>
          )}
          <form onSubmit={onSubmit} className="mx-auto flex max-w-3xl gap-2">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.nativeEvent.isComposing) return
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault()
                  void sendMessage(inputRef.current?.value ?? input)
                }
              }}
              placeholder="Nhập tình huống lao động của bạn..."
              className="min-h-[56px] flex-1 resize-none rounded-xl border border-border bg-surface px-4 py-3 text-sm leading-relaxed text-ink shadow-card outline-none transition placeholder:text-ink-faint focus:border-teal"
              disabled={isLoading}
            />
            <button
              type="button"
              onClick={() => void sendMessage(inputRef.current?.value ?? input)}
              disabled={isLoading}
              className="flex h-[56px] min-w-[96px] items-center justify-center gap-2 rounded-xl bg-teal px-4 font-medium text-white shadow-card transition hover:bg-teal-mid disabled:cursor-wait disabled:bg-ink-faint"
              aria-label="Gửi câu hỏi"
            >
              {isLoading ? <Loader2 size={18} className="animate-spin" /> : <Send size={18} />}
              <span>Gửi</span>
            </button>
          </form>
        </div>
      </section>

      <EvidencePanel response={latestResponse} />
    </main>
  )
}
