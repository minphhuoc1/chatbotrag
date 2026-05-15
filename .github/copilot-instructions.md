# QA Gate Workflow (Haiku -> Codex)

## Mục tiêu
- Mọi code do agent nhanh tạo ra (ví dụ Haiku/subagent) **không được bàn giao trực tiếp**.
- Bắt buộc qua vòng **review + test + edge-case QA** trước khi trả cho user.
- Chỉ bàn giao khi trạng thái cuối là **PASS**.

## Quy trình bắt buộc
1. **Generate phase**: nếu cần tốc độ, có thể dùng subagent để tạo code theo plan.
2. **Gate phase (bắt buộc)** do agent chính thực hiện:
   - Review logic, data flow, error handling, regression risk.
   - Chạy test hiện có của repo.
   - Bổ sung test mục tiêu cho bug vừa sửa (nếu thiếu coverage trực tiếp).
   - Rà edge cases: input rỗng, input nhiễu, unicode/encoding, timeout, fallback path.
3. **Decision phase**:
   - Nếu còn lỗi: tiếp tục sửa và lặp lại Gate phase.
   - Chỉ khi pass hoàn toàn mới trả kết quả.

## Chuẩn trả kết quả
- Luôn mở đầu bằng một trong hai trạng thái:
  - `PASS` (đã qua gate)
  - `BLOCKED` (chưa đạt, nêu nguyên nhân ngắn gọn)
- Không bàn giao code “best effort” hoặc “chưa test”.

## Policy chất lượng
- Không coi “generate thành công” là “hoàn thành”.
- Không merge/commit phần chưa qua QA gate.
- Ưu tiên correctness và production safety hơn tốc độ.
- Không tạo file kế hoạch/báo cáo markdown trừ khi user yêu cầu rõ.
- Mặc định chạy auto-loop Haiku -> qa-gate -> fix -> qa-gate đến PASS.
