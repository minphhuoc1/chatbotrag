# QA Gate Workflow: Haiku ↔ qa-gate (Full 2-Chiều)

## Mục tiêu
- Haiku tạo code → **tự động invoke qa-gate** review/test → nếu fail → Haiku fix → quay lại qa-gate (lặp).
- Chỉ **PASS** mới handoff user.
- User thấy toàn bộ conversation Haiku ↔ qa-gate trong session.

## 2-Chiều Flow (Full Auto)

```
User Request
    ↓
Haiku: Generate Code
    ↓
[AUTO] Haiku: invoke @qa-gate
    ↓
qa-gate: Review + Test + Edge-case
    ↓
    ├─→ ✅ PASS → Haiku: Handoff to user
    │
    └─→ ❌ BLOCKED → Haiku: Fix + re-invoke @qa-gate (loop)
```

## Haiku Responsibility
1. Tạo code theo spec/plan.
2. **Tự động gọi qa-gate** (sau mỗi code generation).
3. Nếu qa-gate BLOCKED:
   - Đọc lỗi
   - Sửa code
   - **Gọi qa-gate lại**
   - Lặp cho đến PASS
4. Khi qa-gate PASS → báo user kết quả.

## qa-gate Responsibility
1. Review code logic + error handling.
2. Chạy test hiện có + targeted test.
3. Xác nhận edge case coverage.
4. Trả PASS hoặc BLOCKED (chi tiết nguyên nhân).

## Output Format (Haiku)
- **PASS case:** `✅ HANDOFF READY - [files, tests, coverage info]`
- **BLOCKED case:** `⚠️ BLOCKED - [reason after retry attempts]`

## Policy
- Haiku không được bỏ qa-gate.
- qa-gate không được skip test.
- Ưu tiên correctness > tốc độ.
- Toàn bộ trao đổi hiển thị → user biết flow đang diễn ra.
