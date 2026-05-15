---
mode: "agent"
description: "Run full QA gate after code generation: review, test, edge-case checks, fix until PASS"
---
Run the QA gate workflow on current unstaged changes.

Requirements:
1. Review changed files for correctness, error handling, and regression risk.
2. Run existing tests relevant to changed areas.
3. Add/adjust targeted tests only if direct bug path lacks coverage.
4. Validate edge cases (empty input, malformed input, unicode/encoding, timeout/fallback paths).
5. If any check fails, fix code and repeat until PASS.
6. Return only final gate status:
   - PASS: ready to handoff
   - BLOCKED: include shortest root cause and required action
