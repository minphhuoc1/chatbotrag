"use client"
import { cn } from "@/lib/utils"
import { ROUTE_META } from "@/lib/utils"
import type { RouteType } from "@/lib/types"

const colorMap: Record<string, string> = {
  teal:  "bg-teal-light text-teal border border-teal/20",
  blue:  "bg-blue-50 text-blue-700 border border-blue-200",
  amber: "bg-amber-50 text-amber-700 border border-amber-200",
  red:   "bg-legal-red-light text-legal-red border border-legal-red/20",
  gray:  "bg-surface-raised text-ink-muted border border-border",
}

interface RouteBadgeProps {
  route: string
  size?: "sm" | "md"
  className?: string
}

export function RouteBadge({ route, size = "md", className }: RouteBadgeProps) {
  const meta = ROUTE_META[route as RouteType] ?? {
    label: route,
    color: "gray",
    description: route,
  }

  return (
    <span
      title={meta.description}
      className={cn(
        "inline-flex items-center rounded font-mono font-medium tracking-wide whitespace-nowrap",
        size === "sm" ? "text-2xs px-1.5 py-0.5" : "text-xs px-2 py-0.5",
        colorMap[meta.color] ?? colorMap.gray,
        className
      )}
    >
      {meta.label}
    </span>
  )
}
