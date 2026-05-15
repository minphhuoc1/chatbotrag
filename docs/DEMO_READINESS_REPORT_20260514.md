# Demo Readiness Report - 2026-05-14

## Status

Project is ready for a controlled RAG chatbot demo.

Latest verified results:

- Legal QA real LLM: 30/30 passed
- Average weighted score: 97.0
- Root cause distribution: retrieval 0, prompt 0, policy 0, model 0
- Multi-turn mock: 5/5 passed
- UI smoke via Streamlit AppTest: 8/8 passed
- Targeted regression: 12/12 passed

## Final Reports

- `reports/legal_qa/legal_qa_full_demo_green_final_20260514.json`
- `reports/ui_smoke/ui_smoke_20260514_020028.json`
- `reports/ui_smoke/ui_smoke_20260514_020028.log`
- `reports/multi_turn/multi_turn_mock_llm_20260514_020028.json`
- `reports/route_distribution/route_distribution_mock_llm_20260514_015756.json`

## Fixes Completed In This Sprint

- Fixed multi-turn context carry into analyzer and retrieval.
- Added legal hints for common demo-critical topics: unlawful dismissal, prolonged probation, job-loss allowance, internal labor rules.
- Repaired inline invalid citations when the model confuses clause numbers with article numbers.
- Reduced false positives in runaway generation detection for repeated legal terms.
- Added retry/fallback handling for empty reasoner output in QA runner.
- Added a wage-arrears guardrail for the UI demo path to avoid drifting into unrelated unlawful termination duties.
- Added CLI flags to `test_legal_qa.py`: `--case-ids` and `--report-path`.

## Demo Command Checklist

Run core QA:

```powershell
$env:PYTHONUTF8='1'
python test_legal_qa.py --report-path reports\legal_qa\legal_qa_full_demo_green_final_20260514.json
```

Run multi-turn check:

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONPATH='D:\chatbotrag\scripts;D:\chatbotrag'
python tests\test_multi_turn.py
```

Run UI smoke:

```powershell
$env:PYTHONUTF8='1'
python scripts\ui_smoke_streamlit_apptest.py
```

Start manual Streamlit demo:

```powershell
python -m streamlit run app.py --server.headless true --server.port 8511
```

## Demo Questions

- `Điều 35`
- `Trích nguyên văn Điều 113`
- `Đơn phương chấm dứt trái luật phải bồi thường gì?`
- `Tôi là người lao động, hợp đồng 24 tháng, công ty đang nợ lương tôi 2 tháng.`
- `Vậy tôi nghỉ ngay không báo trước có được không?`
- `Nếu tôi nghỉ ngay thì công ty còn phải thanh toán cho tôi những khoản nào?`
- `Lao động nữ mang thai có được bảo vệ khi chấm dứt hợp đồng không?`
- `Real Madrid tối qua đá sao rồi?`

## Known Constraints

- Groq free tier can still rate-limit real LLM runs.
- Full third-party Ragas runtime remains environment-sensitive; TruLens/Phoenix artifacts exist but should not be treated as the main demo gate.
- The repo still contains local vector DB, cache, and report artifacts. Before publishing, curate `.gitignore` and include only representative reports.
