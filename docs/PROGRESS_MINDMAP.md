# Project Progress Mindmap

```mermaid
mindmap
  root((Chatbot RAG Legal<br/>Demo Ready 2026-05-14))
    Done
      Retrieval P0/P1
        Strategy router
        Hybrid lexical + semantic
        Deterministic article branch
        Reranker + metadata boost
      Ingest quality
        OpenDataLoader JSON pipeline
        Better article metadata
      Reasoning quality
        Clarify-first guardrails
        Failure-cause classification
        Citation contract + repair
        Delta 2026-05-14
          Multi-turn context carry into analyzer + retrieval
          Inline citation repair (Điều 3 -> Điều 137 when context proves Điều 137)
          Empty reasoner retry/fallback in QA runner
          Wage-arrears guardrail for demo UI flow
          Less noisy runaway detection for legal boilerplate phrases
        Delta 2026-05-13
          Off-topic guard chạy trước context-carry
          Follow-up deterministic cho case nợ lương
          Reasoner 429 fallback không trả rỗng
      Benchmarks
        Before/After P0/P1 reports
        Multi-run aggregate reports
      QA hardening
        Retry/backoff for 429
        Quota-aware QA/E2E pass handling
        QA gate runner with cooldown
        UI smoke automation (Streamlit AppTest)
    Current status
      Latest demo run (2026-05-14)
        Legal QA real LLM PASS 30/30
          Average weighted score 97.0
          Root causes 0 retrieval 0 prompt 0 policy 0 model
        UI smoke PASS 8/8
        Multi-turn mock PASS 5/5
        Regression tests PASS 12/12
        Route distribution mock
          rag 19/30
          rule_based 3/30
          insufficient_context 3/30
          quote_direct 2/30
          article_resolution 2/30
          article_direct 1/30
      QA gate
        Pass when quota available
        Quota-skip mode active under TPD exhaustion
      Reports
        Legal QA final reports/legal_qa/legal_qa_full_demo_green_final_20260514.json
        UI smoke final reports/ui_smoke/ui_smoke_20260514_020028.json
        Multi-turn final reports/multi_turn/multi_turn_mock_llm_20260514_020028.json
        Route distribution reports/route_distribution/route_distribution_mock_llm_20260514_015756.json
      Third-party
        TruLens metrics running
        No NaN in latest third-party reports
    Blockers
      Groq free-tier limits
        TPM bursts
        TPD exhaustion
      Third-party stack
        Ragas dependency conflicts
        Vendor-path instability for mixed runtime
    Next
      P0
        Package repo for CV/demo
        Hide bulky local artifacts behind .gitignore or docs note
        Create short demo script with 6-8 curated questions
      P1
        Expand UI smoke lên 15-20 tình huống mới
      P2
        Isolated venv cho Ragas + third-party full rerun
      P3
        Export final demo pack
        Benchmark + QA + third-party summary for CV
```

## Notes
- This map is a high-level summary for decision making.
- Source of truth remains JSON/TXT reports in `reports/`.
- Delta mới nhất được chốt theo:
  - `reports/legal_qa/legal_qa_full_demo_green_final_20260514.json`
  - `reports/ui_smoke/ui_smoke_20260514_020028.json`
  - `reports/multi_turn/multi_turn_mock_llm_20260514_020028.json`
