export interface RetrievedArticle {
  article_number: string
  article_title: string
  snippet: string
  source_file: string
  score: number | null
}

export interface Validation {
  grounded: boolean
  reason: string
}

export interface ChatResponse {
  answer: string
  route: string
  cited_articles: string[]
  primary_cited_articles?: string[]
  cross_references?: string[]
  retrieved_articles: RetrievedArticle[]
  validation: Validation
}

export interface Message {
  id: string
  role: "user" | "assistant"
  content: string
  timestamp: Date
  meta?: ChatResponse
}

export interface DemoScenario {
  id: string
  label: string
  prompt: string
  tag: string
}

export type RouteType =
  | "rag"
  | "rule_based"
  | "clarifying"
  | "quote_direct"
  | "insufficient_context"
  | "article_resolution"
  | "article_direct"
  | "rule_followup"
  | "intent_non_legal"
  | "error"
