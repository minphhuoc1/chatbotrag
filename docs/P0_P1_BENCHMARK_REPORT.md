# P0/P1 Retrieval Benchmark Report

## Scope
- Benchmark `before_p0` vs `after_p0` (P0 only).
- Benchmark `after_p0` vs `after_p1` (P1 improvements).
- Dataset: `test_cases.yaml` (30 cases, 25 cases có expected article refs).
- Metric focus: `Hit@K`, `Mean Recall@K`, `MRR@K`, latency (`mean`, `p50`, `p95`).

## Commands Used

### 1) Compare Before/After P0
```powershell
python scripts\benchmark_retrieval_ab.py --mode compare
```

### 2) Run After P1
```powershell
$env:LEGAL_CHATBOT_RETRIEVAL_ENABLE_STRATEGY_ROUTER='1'
$env:LEGAL_CHATBOT_RETRIEVAL_ENABLE_LEXICAL='1'
$env:LEGAL_CHATBOT_RETRIEVAL_ENABLE_DETERMINISTIC_ARTICLE_BRANCH='1'
$env:LEGAL_CHATBOT_RETRIEVAL_ENABLE_RERANKER='1'
$env:LEGAL_CHATBOT_RETRIEVAL_ENABLE_METADATA_BOOST='1'
python scripts\benchmark_retrieval_ab.py --mode single --label after_p1
```

## Generated Reports
- P0 compare:
  - `reports/benchmarks/retrieval_single_before_p0_20260512_113812.json`
  - `reports/benchmarks/retrieval_single_after_p0_20260512_113812.json`
  - `reports/benchmarks/retrieval_benchmark_compare_20260512_113812.json`
- P1 compare helper:
  - `reports/benchmarks/retrieval_benchmark_after_p1_20260512_113948.json`
  - `reports/benchmarks/retrieval_benchmark_after_p1_compare_20260512_113812_113948.json`

## Results

### Before P0 -> After P0
- `Hit@K`: `1.0000 -> 1.0000` (`+0.0000`)
- `Mean Recall@K`: `1.0000 -> 1.0000` (`+0.0000`)
- `MRR@K`: `0.7247 -> 0.7600` (`+0.0353`)
- `Latency mean`: `50.89ms -> 82.78ms` (`+31.89ms`)
- `Latency p95`: `87.59ms -> 225.70ms` (`+138.11ms`)

Interpretation:
- P0 tăng chất lượng xếp hạng sớm (MRR tăng).
- Chi phí latency tăng do thêm lexical + strategy routing.

### After P0 -> After P1
- `Hit@K`: `1.0000 -> 1.0000` (`+0.0000`)
- `Mean Recall@K`: `1.0000 -> 1.0000` (`+0.0000`)
- `MRR@K`: `0.7600 -> 0.8147` (`+0.0547`)
- `Latency mean`: `82.78ms -> 35.99ms` (`-46.79ms`)
- `Latency p95`: `225.70ms -> 101.51ms` (`-124.19ms`)

Interpretation:
- P1 tiếp tục cải thiện độ ưu tiên đúng evidence (MRR tăng thêm).
- Latency giảm đáng kể nhờ rerank/metadata boost giúp ổn định top-k hiệu quả hơn trong pipeline hiện tại.

## Runtime Notes
- Persistent Chroma tại `DB_PATH` đang lỗi `disk I/O error (code: 2570)`.
- Benchmark tự động fallback sang memory backend (`load_and_clean_pdfs` + `build_article_chunks` + `Chroma.from_documents`).
- Embedding device ưu tiên CUDA nếu khả dụng (`LEGAL_CHATBOT_EMBED_DEVICE=cuda`), script tự ép CUDA khi phát hiện GPU.

## Reproducibility
- Script benchmark chính: `scripts/benchmark_retrieval_ab.py`
- Các cờ quan trọng:
  - `LEGAL_CHATBOT_RETRIEVAL_ENABLE_STRATEGY_ROUTER`
  - `LEGAL_CHATBOT_RETRIEVAL_ENABLE_LEXICAL`
  - `LEGAL_CHATBOT_RETRIEVAL_ENABLE_DETERMINISTIC_ARTICLE_BRANCH`
  - `LEGAL_CHATBOT_RETRIEVAL_ENABLE_RERANKER`
  - `LEGAL_CHATBOT_RETRIEVAL_ENABLE_METADATA_BOOST`
