"use client"
import { cn } from "@/lib/utils"
import { FileText, Star } from "lucide-react"
import type { RetrievedArticle } from "@/lib/types"

interface ArticleCardProps {
  article: RetrievedArticle
  rank: number
  isCited: boolean
}

export function ArticleCard({ article, rank, isCited }: ArticleCardProps) {
  return (
    <div
      className={cn(
        "rounded-lg border p-3 transition-all duration-200",
        isCited
          ? "border-teal/30 bg-teal-light/50 shadow-sm"
          : "border-border bg-surface hover:border-border-strong"
      )}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="flex items-center gap-1.5 min-w-0">
          <span
            className={cn(
              "flex-shrink-0 w-5 h-5 rounded text-2xs font-mono font-bold flex items-center justify-center",
              isCited ? "bg-teal text-white" : "bg-surface-raised text-ink-muted"
            )}
          >
            {rank}
          </span>
          <span className="font-mono text-xs font-semibold text-legal-red truncate">
            Điều {article.article_number}
          </span>
          {isCited && (
            <Star size={10} className="flex-shrink-0 text-teal fill-teal" />
          )}
        </div>
        {article.score !== null && (
          <span className="flex-shrink-0 text-2xs font-mono text-ink-faint bg-surface-raised px-1.5 py-0.5 rounded">
            {article.score.toFixed(1)}
          </span>
        )}
      </div>

      {/* Title */}
      <p className="text-xs font-semibold text-ink mb-1.5 leading-snug">
        {article.article_title}
      </p>

      {/* Snippet */}
      <p className="text-2xs text-ink-muted leading-relaxed line-clamp-3">
        {article.snippet}
      </p>

      {/* Source */}
      <div className="flex items-center gap-1 mt-2">
        <FileText size={9} className="text-ink-faint" />
        <span className="text-2xs text-ink-faint font-mono truncate">
          {article.source_file}
        </span>
      </div>
    </div>
  )
}
