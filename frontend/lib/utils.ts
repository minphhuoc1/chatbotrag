import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"
import type { RouteType } from "./types"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function generateId(): string {
  return Math.random().toString(36).slice(2, 9)
}

export const ROUTE_META: Record<RouteType, { label: string; color: string; description: string }> = {
  rag: {
    label: "Truy xuất",
    color: "teal",
    description: "Trả lời từ ngữ nghĩa, truy xuất văn bản pháp luật",
  },
  rule_based: {
    label: "Quy tắc",
    color: "blue",
    description: "Trả lời từ quy tắc tất định — độ chính xác cao",
  },
  clarifying: {
    label: "Làm rõ",
    color: "amber",
    description: "Câu hỏi mơ hồ — hệ thống yêu cầu thông tin thêm",
  },
  quote_direct: {
    label: "Trích dẫn",
    color: "teal",
    description: "Trích nguyên văn điều luật từ nguồn luật",
  },
  insufficient_context: {
    label: "Thiếu căn cứ",
    color: "red",
    description: "Không đủ cơ sở pháp lý để kết luận",
  },
  article_resolution: {
    label: "Giải quyết",
    color: "blue",
    description: "Kiểm tra tính hợp lệ của số Điều",
  },
  article_direct: {
    label: "Điều trực tiếp",
    color: "teal",
    description: "Tra cứu chính xác một Điều cụ thể",
  },
  rule_followup: {
    label: "Tiếp nối",
    color: "blue",
    description: "Tiếp nối hội thoại, nhớ ngữ cảnh trước đó",
  },
  intent_non_legal: {
    label: "Ngoài phạm vi",
    color: "gray",
    description: "Câu hỏi không thuộc pháp luật lao động",
  },
  error: {
    label: "Lỗi",
    color: "red",
    description: "Lỗi hệ thống",
  },
}

export function formatArticleRef(num: string): string {
  return `Điều ${num}`
}
