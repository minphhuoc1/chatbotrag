import type { Metadata } from "next"
import "./globals.css"

export const metadata: Metadata = {
  title: "LexBot — Tư vấn Pháp luật Lao động",
  description: "Trợ lý hỏi đáp Bộ luật Lao động Việt Nam 2019 có trích dẫn căn cứ",
  icons: { icon: "/favicon.svg" },
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="vi" suppressHydrationWarning>
      <body className="h-screen overflow-hidden">{children}</body>
    </html>
  )
}
