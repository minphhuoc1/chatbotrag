# Claude Instruction Packet (Process-Locked)

Date: 2026-05-13 (Asia/Saigon)  
Source of truth: `D:\chatbotrag\docs\implementation_contract_claude_codex.md`

## Mandatory rules
- You must update Task board status before and after each task.
- You must append Handoff log at end of each task batch.
- Any code change without contract update is treated as not delivered.
- Do not edit `D:\chatbotrag\app.py` in this phase.

## Execution scope (Claude only)
- `D:\chatbotrag\src\legal_chatbot\reasoning_chain.py`
- `D:\chatbotrag\src\legal_chatbot\policy.py`
- Engine/Policy tests under `D:\chatbotrag\tests\`

## Ordered tasks
1. A1: Add `RunResult` dataclass (contract fields).
2. A2: Add `run_structured(user_input, chat_history)` returning `RunResult`.
3. A3: Keep backward compatibility: `run()` wraps `run_structured()`.
4. A4: Fix validation fallback path to use `repaired_validation` (not old `validation`).
5. C1: Narrow `classify_query_mode` marker set (remove broad marker `"bị"`).
6. C2: Normalize `build_validation_fallback(validation, query_mode, failure_cause="")`.
7. D1/D2: Add tests for `run_structured` contract and analyzer mismatch regression.

## Technical constraints
- Keep public signature of `run(user_input, chat_history)` unchanged.
- `run_structured()` is additive API only, do not break existing callers.
- Do not leave varargs ambiguity in fallback API.
- Ensure no direct analyzer string `.get(...)` assumption remains in engine path.

## Required test commands (minimum)
- `pytest tests/test_policy_unilateral_compensation.py -q`
- `pytest tests/test_policy_dynamic_hints.py -q`
- `pytest tests/test_retrieval_p1.py -q`
- New tests for `run_structured` + analyzer mismatch regression.

## Delivery format (in Handoff log)
- Task IDs completed.
- Files touched.
- Commands executed + PASS/FAIL.
- Residual risks.
- Next owner action for Codex.
