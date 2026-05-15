# BACKLOG — Cải tiến sau khi hoàn thành end-to-end

> Tạo: 2026-04-12. Áp dụng SAU KHI toàn bộ pipeline chạy ổn.
> Nguồn: ingest_review_report.md + QA findings

---

## 🔴 P0 — Bắt buộc xem xét (ảnh hưởng đến chất lượng sản phẩm)

### [INGEST-1] Thay RecursiveCharacterTextSplitter → Structural Parser
- **Vấn đề:** splitter không đảm bảo ranh giới Khoản/Điểm. Chunk có thể
  chứa cuối Điều A + đầu Điều B.
- **Hệ quả:** citation metadata `dieu_so` chỉ đúng 71%, không đáng tin cho
  trích dẫn pháp lý chuẩn.
- **Giải pháp:** parser cấu trúc `Chương → Mục → Điều → Khoản → Điểm`,
  emit 1 chunk = 1 Khoản.
- **Ước tính:** 2-3 ngày dev + test.

### [INGEST-2] Metadata pháp lý đầy đủ
- **Hiện tại:** chỉ có `source_file`, `law_name`, `chunk_id`, `dieu_so` (không chắc)
- **Cần thêm:** `chapter_no`, `chapter_title`, `article_no`, `article_title`,
  `clause_no`, `point_letter`, `citation` (dạng "Điều X, Khoản Y, BLLĐ 2019")
- **Lý do:** citation rõ ràng trong câu trả lời, debug dễ hơn.

### [INGEST-3] Skip page theo độ dài `<80` cứng → classify_page()
- **Vấn đề:** có thể bỏ trang hợp lệ ngắn (ví dụ: trang chỉ có tiêu đề Chương)
- **Giải pháp:** `classify_page() → body | cover | toc | noise | uncertain`.
  Trang `uncertain` thì log ra để review, không bỏ ngay.

---

## 🟡 P1 — Nên làm sau khi P0 xong

### [INGEST-4] Thay PyPDFLoader → PyMuPDF (fitz)
- **Lý do:** cần khi thêm PDF có layout phức tạp (hai cột, header/footer
  theo tọa độ, scan OCR).
- **Hiện tại:** file luatlaodong.pdf đang extract ổn với PyPDFLoader. Không
  cần thay ngay.
- **Điều kiện kích hoạt:** khi thêm file PDF từ nguồn khác Studocu, hoặc
  khi thấy reading order sai.

### [INGEST-5] Structured JSON output trước khi index vào Chroma
- **Lý do:** dễ audit, dễ debug, dễ re-index mà không cần parse lại PDF.
  Pipeline: PDF → parse → `chunks.jsonl` → index.
- **Lợi ích phụ:** cache — nếu PDF không thay đổi, không cần parse lại.

### [INGEST-6] Validation script sau ingest
- Kiểm tra: số Điều parse được vs tổng Điều trong luật.
- Kiểm tra: chunk nào thiếu article metadata.
- Kiểm tra: có chunk lai nhiều Điều không.
- Kiểm tra: còn watermark trong corpus không.

---

## 🟢 P2 — Nâng cấp chất lượng (khi có thời gian)

### [APP-1] Tốc độ LLM: 37.6s/lượt
- **Vấn đề:** qwen2.5:7b chạy chậm trên GTX 1650 4GB (một phần load CPU).
- **Giải pháp:** thử qwen2.5:3b cho các câu trả lời đơn giản, giữ 7b cho
  câu phức tạp. Hoặc stream response để UX mượt hơn.

### [APP-2] Streaming response trong Streamlit
- Thay `st.markdown(answer)` bằng `st.write_stream()` để user thấy text
  chạy ra từng chữ, không phải chờ 37s rồi hiện cả đoạn.

### [RAG-1] Query rewriting trước khi Retrieve
- **Vấn đề đã thấy từ QA:** "Điều 35 quy định gì?" → Retriever không tìm
  được tốt bằng "quyền đơn phương chấm dứt hợp đồng".
- **Giải pháp:** rewrite query về ngữ nghĩa trước khi gọi Retriever.
  Ví dụ: "Điều 35" → extract số → lookup nội dung Điều.

---

## 📌 Nguyên tắc khi implement backlog

1. **Test trước khi merge.** Mỗi P0 phải có test riêng xác nhận cải thiện.
2. **Không phá pipeline đang chạy.** Làm trên branch/file mới, merge sau khi test pass.
3. **Ưu tiên theo thứ tự P0 → P1 → P2.** Không skip.
