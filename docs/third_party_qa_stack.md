# Third-party QA Stack

## Mục tiêu
- Theo dõi trace + experiment ngoài hệ thống report nội bộ.
- Đo chất lượng RAG bằng metric chuẩn từ công cụ bên thứ 3.
- Có local observability cho debug nhanh.

## Thành phần đã tích hợp

### 1) LangSmith / Langfuse (trace + dataset tracking)
- Runtime hook nằm trong:
  - `src/legal_chatbot/observability.py`
  - `src/legal_chatbot/llm_factory.py`
- Cách hoạt động:
  - LangSmith: bật qua ENV (`LANGSMITH_TRACING=true`) để trace LangChain runs.
  - Langfuse: gắn callback handler vào LLM client khi `LEGAL_CHATBOT_LANGFUSE_ENABLED=true`.
- Dataset sync:
  - Script: `scripts/third_party_qa_runner.py`
  - Đẩy test cases lên:
    - LangSmith dataset
    - Langfuse dataset

### 2) Ragas / TruLens (RAG metrics)
- Script: `scripts/third_party_qa_runner.py`
- Tập metric mục tiêu:
  - Retrieval-related relevance
  - Groundedness / faithfulness
  - Answer relevance
- Ragas có 2 mode:
  - `RAGAS_METRIC_MODE=non_llm` (khuyến nghị): metric ổn định, ít phụ thuộc network/rate-limit.
  - `RAGAS_METRIC_MODE=llm`: metric judge sâu hơn nhưng tốn token và dễ dính 429.
- Output:
  - `reports/third_party/third_party_eval_*.json`

### 3) Phoenix local (trace/eval local)
- Runtime auto instrumentation qua OpenInference khi:
  - `LEGAL_CHATBOT_PHOENIX_ENABLED=true`
- Probe script:
  - `scripts/phoenix_local_trace_probe.py`

## ENV chính
- `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`
- `LEGAL_CHATBOT_LANGFUSE_ENABLED`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`
- `LEGAL_CHATBOT_PHOENIX_ENABLED`, `LEGAL_CHATBOT_PHOENIX_AUTO_INSTRUMENT`, `LEGAL_CHATBOT_PHOENIX_PROJECT`
- `LEGAL_CHATBOT_TRACE_TAG`

## Quy trình chạy đề xuất
1. Cấu hình ENV keys cho provider + observability.
2. Chạy:
   - Khuyến nghị Windows (ổn định, tránh crash do trộn global/vendor packages):
     - `powershell -ExecutionPolicy Bypass -File scripts/run_third_party_qa_isolated.ps1`
   - Hoặc chạy trực tiếp:
     - `python scripts/third_party_qa_runner.py`
   - Hoặc metrics-only (không chạy lại prediction/runtime):
     - set `THIRD_PARTY_SOURCE_REPORT=reports/third_party/third_party_eval_YYYYMMDD_HHMMSS.json`
     - rồi chạy lại `python scripts/third_party_qa_runner.py`
3. Kiểm tra:
   - `reports/third_party/third_party_eval_*.json`
   - LangSmith/Langfuse dashboard
   - Phoenix UI (nếu bật local trace)

## Ghi chú
- Nếu thiếu package/keys, script vẫn tạo report và ghi rõ phần nào bị skip/error.
- Metric của Ragas/TruLens phụ thuộc phiên bản thư viện; runner đã có fallback import cho nhiều phiên bản phổ biến.
- Report JSON được sanitize trước khi ghi (`allow_nan=False`) nên không còn xuất hiện `NaN` trong file output.
- TruLens hiện ưu tiên `OpenAI provider` (có thể trỏ tới Groq qua `TRULENS_OPENAI_BASE_URL`) và fallback sang `LiteLLM` nếu cần.
- TruLens có 2 mode:
  - `TRULENS_METRIC_MODE=ground_truth` (khuyến nghị): dùng `GroundTruthAgreement` (Precision@k, NDCG@k), không phụ thuộc LLM API.
  - `TRULENS_METRIC_MODE=llm`: dùng judge metric (groundedness/answer/context relevance), phụ thuộc API và dễ dính rate-limit.
- Nếu gặp popup `python.exe - Application Error` kiểu `memory could not be read`:
  - Đây thường là xung đột native dependency (ABI) khi trộn package global với package trong `.vendor`, không phải lỗi prompt hay thiếu VRAM.
  - Dùng chế độ isolated (`run_third_party_qa_isolated.ps1`) để ép Python chỉ nạp stack trong workspace.
