# Repomix Benchmark: `RAGCHATBOTV2`

## 1) Snapshot đã chạy
- Repo benchmark: `https://github.com/phamtho034ls/RAGCHATBOTV2`
- Local clone: `C:\tmp\RAGCHATBOTV2`
- Repomix outputs:
  - `D:\chatbotrag\tmp\repomix_ragchatbotv2.xml`
  - `D:\chatbotrag\tmp\repomix_ragchatbotv2.json`
- Quy mô snapshot (compress):
  - `130` files
  - khoảng `112k–132k` tokens (tùy style XML/JSON)

## 2) Họ đang làm tốt ở đâu (đáng học)

### 2.1 Retrieval hybrid thực chiến
- Kết hợp nhiều nguồn retrieval:
  - vector search
  - keyword/FTS trên PostgreSQL
  - fallback ILIKE khi FTS lỗi
  - RRF merge + rerank
- Tham chiếu:
  - `C:\tmp\RAGCHATBOTV2\backend\app\retrieval\hybrid_retriever.py`
  - `C:\tmp\RAGCHATBOTV2\backend\app\retrieval\keyword_retriever.py`
  - `C:\tmp\RAGCHATBOTV2\backend\app\retrieval\reranker.py`

Ý nghĩa: giảm phụ thuộc tuyệt đối vào semantic embedding, tăng recall cho câu pháp lý có cấu trúc “Điều/Khoản/số hiệu”.

### 2.2 Lookup thẳng theo Điều/Khoản/số hiệu văn bản
- Có nhánh DB lookup riêng cho:
  - “Điều X …”
  - “Khoản Y Điều X …”
  - “49/2025/QĐ-UBND …”
  - query theo chủ đề trong một luật cụ thể
- Tham chiếu:
  - `C:\tmp\RAGCHATBOTV2\backend\app\retrieval\article_lookup.py`

Ý nghĩa: giảm lỗi “vector bốc sai điều”, nhất là câu hỏi dạng tra cứu chính xác.

### 2.3 Strategy router theo score (không if/else cứng)
- Trích feature query, chấm điểm strategy, chọn `lookup/semantic/multi_query`.
- Tham chiếu:
  - `C:\tmp\RAGCHATBOTV2\backend\app\services\query_features.py`
  - `C:\tmp\RAGCHATBOTV2\backend\app\services\strategy_router.py`

Ý nghĩa: dễ mở rộng, dễ QA, tránh route sai vì 1 rule đơn lẻ.

### 2.4 Intent multi-layer rõ ràng
- Guard -> classifier -> semantic prototype -> structural rules (YAML) -> LLM fallback.
- Tham chiếu:
  - `C:\tmp\RAGCHATBOTV2\backend\app\services\intent_detector.py`
  - `C:\tmp\RAGCHATBOTV2\backend\app\intent_patterns\routing.yaml`

Ý nghĩa: có “defense in depth”, giảm phụ thuộc 100% vào LLM.

### 2.5 Ingest chú trọng cấu trúc luật
- Parse theo line-based legal structure:
  - Chương/Mục/Điều/Khoản/Điểm
  - nhận diện appendix/table-like để tách khỏi phần RAG chính
- Tham chiếu:
  - `C:\tmp\RAGCHATBOTV2\backend\app\pipeline\structure_detector.py`
  - `C:\tmp\RAGCHATBOTV2\backend\app\pipeline\ingestor.py`

Ý nghĩa: giảm chunk rác, giảm đảo trật tự clauses.

### 2.6 Hậu kiểm trả lời (validator)
- Có lớp kiểm groundedness + completeness theo điều khoản.
- Tham chiếu:
  - `C:\tmp\RAGCHATBOTV2\backend\app\services\answer_validator.py`

Ý nghĩa: tăng an toàn trước hallucination.

## 3) Điểm yếu/chi phí của họ (không copy nguyên xi)

### 3.1 Độ phức tạp hạ tầng cao
- PostgreSQL + Qdrant + Redis + nhiều service route.
- Chi phí vận hành/debug cao hơn stack đơn giản.

### 3.2 Rule/regex dày đặc
- File pattern rất dài, dễ drift theo data mới.
- Cần quy trình quản trị rule nghiêm ngặt, nếu không sẽ nợ kỹ thuật lớn.

### 3.3 QA report có phần chưa end-to-end
- `data_clean_eval_report.json` thiên về intent/rag_flags; `with_answers=false`.
- Chưa đủ thay thế hoàn toàn answer-level QA thực chiến.

## 4) So với project hiện tại của chúng ta

## 4.1 Chúng ta đã có
- Parent-child retrieval + exact article enrichment + guard/citation policy.
- Ingest theo OpenDataLoader JSON + xử lý header/footer + tách legal sections.
- Third-party QA pipeline (Ragas + TruLens) chạy full ổn định.

## 4.2 Chúng ta còn thiếu (so với benchmark)
- Hybrid retrieval thật sự (vector + lexical/FTS + merge/rerank).
- Strategy scoring router tách riêng (feature -> score -> selected strategies).
- DB-level article/topic lookup như một nhánh độc lập có ưu tiên cao.
- Domain metadata boost/penalty ở tầng retrieval.

## 5) Đề xuất áp dụng cho project hiện tại

### P0 (nên làm ngay)
1. Thêm lexical retrieval nhẹ (BM25/keyword index nội bộ hoặc FTS nếu có DB) song song vector.
2. Thiết kế `strategy_router` tối giản:
   - feature: `has_article_ref`, `has_doc_number`, `is_procedural`, `needs_comparison`
   - strategies: `lookup`, `semantic`, `multi_query`
3. Tách nhánh `article_lookup` deterministic trước khi đi semantic retrieval.

### P1 (nên làm tiếp)
1. Thêm reranker stage (cross-encoder nhẹ hoặc API rerank) sau merge retrieval.
2. Thêm metadata-based boost:
   - ưu tiên cùng `doc_number`
   - ưu tiên cùng `article_number`
3. Chuẩn hóa pipeline post-validation:
   - completeness theo điều/khoản
   - fallback logic theo nguyên nhân lỗi (retrieval/prompt/policy/model)

### P2 (sau khi P0/P1 xanh)
1. Chuyển regex hints sang config YAML có versioning + test coverage.
2. Bổ sung benchmark dataset “multi-turn legal facts” chuyên cho memory carry-over.
3. Mở rộng QA gate CI: fail nếu retrieval metrics tụt dưới ngưỡng baseline.

## 6) Kết luận ngắn
- Repo benchmark có nhiều kỹ thuật production tốt ở retrieval/router.
- Điểm học giá trị nhất cho chúng ta: **hybrid retrieval + deterministic lookup + strategy scoring**.
- Không nên bê nguyên kiến trúc; nên lấy “xương sống retrieval” và giữ stack hiện tại gọn, dễ ship.

