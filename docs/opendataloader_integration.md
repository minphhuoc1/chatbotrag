# OpenDataLoader PDF Integration

Tài liệu này mô tả cách dùng output JSON từ [`opendataloader-pdf`](https://github.com/opendataloader-project/opendataloader-pdf) để cải thiện chất lượng ingest.

## Mục tiêu
- Giảm lỗi layout/OCR khi parse PDF pháp lý.
- Giữ cấu trúc page tốt hơn cho pipeline chunk theo `Điều`.
- Không tạo runtime dependency cứng: preprocess là bước tùy chọn.

## Cấu hình
- `LEGAL_CHATBOT_PDF_BACKEND=opendataloader_json`
- `LEGAL_CHATBOT_PREPROCESSED_DIR=data/preprocessed`

`ingest.py` sẽ tự tìm JSON theo tên file PDF:
- `data/preprocessed/<ten_pdf>.json`
- `data/preprocessed/<ten_pdf>.opendataloader.json`
- `data/<ten_pdf>.json`

Nếu không tìm thấy JSON hợp lệ, ingest sẽ fallback sang `PyPDFLoader`.

## Yêu cầu format JSON
Ingest hỗ trợ tree JSON kiểu OpenDataLoader (dựa trên `schema.json` của repo):
- Node có thể chứa:
  - `page` hoặc `page_number`
  - `kids` (children)
  - `content` / `text` / `markdown`
- Ingest chỉ lấy content ở leaf node để tránh duplicate container text.

## Luồng đề xuất
1. Chạy OpenDataLoader để export JSON từ PDF luật:
   - `python scripts/preprocess_opendataloader_json.py`
   - Fast mode mặc định, chỉ output `json`, gọi `convert(...)` 1 lần duy nhất.
   - Script có hỗ trợ Java local bằng `jdk4py` trong `.vendor` nếu máy thiếu Java 11+.
2. Lưu JSON vào `data/preprocessed/`.
3. Chạy lại:
   - `python ingest.py`
4. Rebuild QA:
   - `python scripts/qa_gate_runner.py`

## Ghi chú parser ingest
- Parser `ingest.py` đã bám cấu trúc cây OpenDataLoader và hỗ trợ các key phổ biến:
  - page: `page`, `page_number`, `page number`
  - children: `kids`, `children`, `nodes`, `elements`, `blocks`, `pages`, `list items`, `rows`, `cells`
  - text: `content`, `text`, `markdown`
- Có lọc node `header/footer` và noise kiểu `about:blank ...` trước khi đưa vào chunking.
