# Claude x Codex Implementation Contract

Last updated: 2026-05-13 (Asia/Saigon)

## PROCESS LOCK
Status: **ACTIVE**  
Activated at: **2026-05-13 00:00 Asia/Saigon**

Lock intent:
- Từ thời điểm này, mọi thay đổi code phải đi qua Task board + Handoff log trong file này.
- Không chấp nhận "đã làm xong nhưng chưa cập nhật contract".
- Không merge phần việc chưa có bằng chứng test.

## 1) Mục tiêu
File này là **single source of truth** cho việc phối hợp Claude + Codex.

Mục tiêu:
- Tránh làm trùng lặp.
- Tránh sửa chồng file gây bug tích hợp.
- Theo dõi rõ phần nào đã xong/chưa xong.
- Bàn giao chính xác để người còn lại tiếp tục ngay.

## 2) Quy tắc bắt buộc cập nhật
**Claude và Codex đều phải tuân thủ.**

- Trước khi bắt đầu task: cập nhật `Status = IN_PROGRESS`.
- Sau khi xong task: cập nhật `Status = DONE` + ghi cách làm + file đã sửa + test đã chạy.
- Nếu bị kẹt: cập nhật `Status = BLOCKED` + nêu blocker cụ thể + đề xuất hướng xử lý.
- Mỗi lần commit hoặc kết thúc phiên làm việc phải thêm 1 bản ghi vào `Handoff Log`.

Nếu không cập nhật file này, phần việc được xem là **chưa bàn giao hợp lệ**.

### 2.1 Quy trình bắt buộc riêng cho Claude (nhấn mạnh)
- Mỗi khi Claude nhận 1 task trong `Task board`, Claude phải:
  - đổi trạng thái task sang `IN_PROGRESS` ngay khi bắt đầu;
  - đổi sang `DONE` hoặc `BLOCKED` ngay khi kết thúc phiên làm task đó;
  - ghi rõ các file đã sửa và test đã chạy.
- Nếu Claude quên cập nhật trạng thái trong file này:
  - Codex xem task đó là **chưa hoàn tất**;
  - Codex **không** tiếp tục phụ thuộc vào phần đó để tránh bug dây chuyền.
- Claude phải luôn ghi “Next owner action” trong Handoff Log để Codex biết chính xác phần còn lại.
- Claude không được tự ý sửa task ngoài ownership lock nếu chưa ghi lock/handoff trong file này.

## 3) Status legend
- `TODO`: chưa bắt đầu.
- `IN_PROGRESS`: đang làm.
- `DONE`: hoàn tất và đã test.
- `BLOCKED`: bị chặn, cần người khác xử lý.
- `SKIPPED`: tạm bỏ qua, có lý do rõ ràng.

## 4) Ownership lock (chống đụng file)
### 4.1 Claude ownership (không ai khác sửa song song khi chưa handoff)
- `D:\chatbotrag\src\legal_chatbot\reasoning_chain.py`
- `D:\chatbotrag\src\legal_chatbot\policy.py`
- Engine/Policy tests mới trong `D:\chatbotrag\tests\`

### 4.2 Codex ownership (không ai khác sửa song song khi chưa handoff)
- `D:\chatbotrag\app.py`
- App/integration tests mới trong `D:\chatbotrag\tests\`
- Adapter liên quan `D:\chatbotrag\qa_test.py`, `D:\chatbotrag\e2e_test.py`

### 4.3 Shared files (phải ghi rõ người giữ lock tạm thời)
- `D:\chatbotrag\docs\implementation_contract_claude_codex.md`
- Bất kỳ file config/chung nào phát sinh

## 5) Task board (phải cập nhật liên tục)
| Task ID | Hạng mục | Owner | Status | Cập nhật lúc | Cách làm / Ghi chú bàn giao |
|---|---|---|---|---|---|
| A1 | Thêm `RunResult` dataclass (contract fields chuẩn) | Claude | DONE | 2026-05-13 10:15 | Đã có trong reasoning_chain.py:33-52. Fields: answer, context_text, docs, intent_result, query_mode, search_query, retrieval_check, validation, is_clarifying, route, debug_flags. |
| A2 | Thêm `run_structured()` trả `RunResult` | Claude | DONE | 2026-05-13 10:15 | Đã có trong reasoning_chain.py:474-632. Full RAG flow: intent→rule-based→classify→retrieve→validate→repair. |
| A3 | `run()` wrap `run_structured()` để giữ backward compatibility | Claude | DONE | 2026-05-13 10:15 | Đã có trong reasoning_chain.py:634-642. run() gọi run_structured() và trả (answer, context_text). |
| A4 | Fix validation fallback dùng đúng `repaired_validation` | Claude | DONE | 2026-05-13 10:15 | Đã fix: reasoning_chain.py:608-614 dùng repaired_validation đúng, không phải validation gốc. |
| B1 | Refactor `app.py` gọi `engine.run_structured()` (không gọi analyzer/reasoner trực tiếp) | Codex | DONE | 2026-05-13 10:43 | Đã refactor flow chat sang `engine.run_structured()`; bỏ toàn bộ call trực tiếp vào analyzer/reasoner chains. |
| B2 | Giữ evidence tables dựa trên `result.docs` | Codex | DONE | 2026-05-13 10:43 | Giữ `_build_doc_evidence_rows` + `_build_grounding_rows`, nguồn dữ liệu lấy từ `RunResult.docs`. |
| B3 | Xóa dead code bị override trong `app.py` nhưng giữ helper đang dùng thật | Codex | DONE | 2026-05-13 10:43 | Đã xóa các policy/helper local bị override; giữ helper render evidence cần thiết. |
| C1 | Thu hẹp marker `classify_query_mode` (loại bỏ marker quá rộng như `"bị"`) | Claude | DONE | 2026-05-13 10:43 | Đã loại marker `"bị"` khỏi `is_fact_pattern`; có test guard xác nhận không false-positive. |
| C2 | Chuẩn hóa API `build_validation_fallback(validation, query_mode, failure_cause="")` | Claude | DONE | 2026-05-13 10:43 | Đã chuẩn hóa signature explicit, bỏ varargs API. |
| D1 | Test engine contract `run_structured` | Claude | DONE | 2026-05-13 10:43 | `tests/test_engine_run_structured.py` pass sau khi cài dependency tối thiểu cho venv. |
| D2 | Test anti-regression analyzer mismatch | Claude | DONE | 2026-05-13 10:43 | `tests/test_analyzer_mismatch_regression.py` pass; khóa regression `.get()` trên string analyzer output. |
| D3 | Test app route: không còn `engine.analyzer_chain.invoke(` trong flow UI | Codex | DONE | 2026-05-13 10:43 | Thêm `tests/test_app_structured_flow.py` và pass. |
| D4 | Cập nhật test harness (`qa_test.py`/`e2e_test.py`) nếu cần | Codex | DONE | 2026-05-13 10:43 | Không cần sửa: `run()` backward-compat vẫn giữ tuple `(answer, context_text)`. |
| E1 | Manual smoke test Streamlit (ít nhất 5 câu pháp lý) | Codex | TODO | - | - |
| E2 | Chốt QA pass/fail + risk còn lại | Claude + Codex | TODO | - | - |

## 6) Checklist chất lượng cho từng task DONE
Khi đổi status sang `DONE`, bắt buộc ghi đủ các mục sau trong cột ghi chú hoặc Handoff Log:

- Mã commit (nếu có).
- Danh sách file đã sửa.
- Test/command đã chạy.
- Kết quả test (`PASS/FAIL`).
- Rủi ro còn lại (nếu có).
- Việc tiếp theo người còn lại cần làm.

## 7) Handoff log (bắt buộc append, không được ghi đè)
> Dùng đúng mẫu dưới đây cho mỗi lần bàn giao.

```md
### [YYYY-MM-DD HH:mm Asia/Saigon] Actor: Claude|Codex
- Task IDs: A1, A2, ...
- Status changes:
  - A1: TODO -> DONE
  - A2: TODO -> IN_PROGRESS
- Summary:
  - ...
- Files touched:
  - D:\chatbotrag\src\legal_chatbot\reasoning_chain.py
  - ...
- Tests executed:
  - `pytest tests/test_xxx.py -q` -> PASS
  - ...
- Blockers/Risks:
  - ...
- Next owner action:
  - ...
```

---

### Handoff entries

<!-- Append entries below. Không xóa lịch sử cũ. -->

### [2026-05-13 00:05 Asia/Saigon] Actor: Codex
- Task IDs: Governance Lock
- Status changes:
  - Process lock: inactive -> ACTIVE
- Summary:
  - Kích hoạt cơ chế khóa quy trình cho toàn bộ sprint sửa sai.
  - Bổ sung chỉ dẫn bắt buộc cho Claude (execution order, done criteria, handoff payload).
  - Từ mốc này, mọi thay đổi không ghi trong Task board/Handoff log sẽ bị coi là chưa bàn giao hợp lệ.
- Files touched:
  - D:\chatbotrag\docs\implementation_contract_claude_codex.md
- Tests executed:
  - N/A (documentation/process change only)
- Blockers/Risks:
  - Nếu Claude cập nhật code nhưng quên cập nhật contract thì Codex sẽ không consume kết quả để tránh bug dây chuyền.
- Next owner action:
  - Claude tiếp tục A1/A2/A3/A4 -> C1/C2 -> D1/D2 và cập nhật trạng thái + handoff đúng template.

### [2026-05-13 00:10 Asia/Saigon] Actor: Codex
- Task IDs: Governance Packet
- Status changes:
  - Claude instruction packet: missing -> created
- Summary:
  - Tạo packet chỉ dẫn riêng cho Claude để copy chạy trực tiếp, bám tuyệt đối theo process lock.
  - Packet cố định phạm vi file, thứ tự task, ràng buộc kỹ thuật, lệnh test tối thiểu, và định dạng bàn giao.
- Files touched:
  - D:\chatbotrag\docs\claude_instruction_packet_20260513.md
  - D:\chatbotrag\docs\implementation_contract_claude_codex.md
- Tests executed:
  - N/A (documentation/process change only)
- Blockers/Risks:
  - Nếu Claude chạy lệch thứ tự task trong packet, khả năng xung đột với phase app refactor sẽ tăng.
- Next owner action:
  - Claude bắt đầu từ A1 và cập nhật Task board status trước khi sửa code.

### [2026-05-13 10:43 Asia/Saigon] Actor: Codex
- Task IDs: C1, C2, D1, D2, B1, B2, B3, D3, D4
- Status changes:
  - C1: IN_PROGRESS -> DONE
  - C2: IN_PROGRESS -> DONE
  - D1: IN_PROGRESS -> DONE
  - D2: IN_PROGRESS -> DONE
  - B1: TODO -> DONE
  - B2: TODO -> DONE
  - B3: TODO -> DONE
  - D3: TODO -> DONE
  - D4: TODO -> DONE
- Summary:
  - Tiếp quản phần dở dang do Claude hit quota và hoàn tất contract hóa engine/policy qua verify thực tế.
  - Refactor `app.py` sang `engine.run_structured()` làm entrypoint duy nhất của UI path.
  - Loại bỏ dead code local bị override trong `app.py` nhưng giữ nguyên evidence rendering helpers.
  - Bổ sung guard test chống hồi quy UI gọi analyzer/reasoner trực tiếp.
- Files touched:
  - D:\chatbotrag\app.py
  - D:\chatbotrag\tests\test_app_structured_flow.py
  - D:\chatbotrag\docs\implementation_contract_claude_codex.md
- Tests executed:
  - `.\.venv\Scripts\python.exe -m pytest tests/test_engine_run_structured.py tests/test_analyzer_mismatch_regression.py -q` -> PASS (27 passed)
  - `.\.venv\Scripts\python.exe -m pytest tests/test_policy_dynamic_hints.py tests/test_policy_unilateral_compensation.py tests/test_retrieval_p1.py tests/test_app_structured_flow.py -q` -> PASS (12 passed)
  - `.\.venv\Scripts\python.exe -m pytest tests/test_retrieval_p0.py -q` -> PASS (4 passed)
  - `.\.venv\Scripts\python.exe -m compileall app.py src\legal_chatbot\reasoning_chain.py src\legal_chatbot\policy.py tests\test_engine_run_structured.py tests\test_analyzer_mismatch_regression.py` -> PASS
- Blockers/Risks:
  - `E1` (manual Streamlit smoke) chưa chạy trong lượt này; cần xác nhận thêm qua UI thực tế.
- Next owner action:
  - Chạy `E1` (5+ câu smoke trên Streamlit), sau đó chốt `E2` QA pass/fail và residual risk.

## 8) Quy tắc chống bug tích hợp lớn
- Không đổi chữ ký hàm public nếu chưa ghi rõ trong Task board + Handoff log.
- Không sửa file ngoài ownership khi chưa ghi lock/handoff.
- Không merge khi còn `BLOCKED` mà không có workaround rõ.
- Mọi thay đổi liên quan pipeline phải có test tối thiểu 1 happy path + 1 failure path.

## 9) Điều kiện “đủ để bàn giao demo”
- `app.py` dùng chung engine flow với QA flow (không pipeline tách đôi).
- Không còn lỗi `.get` trên analyzer output string.
- Không còn double intent classification gây tốn quota.
- Test regressions chính pass.
- Có log/handoff đầy đủ trong file này để audit.

## 10) Chỉ dẫn thực thi cho Claude (bắt buộc làm theo)
### 10.1 Mục tiêu phase hiện tại
- Ưu tiên sửa lỗi pipeline gốc trước khi tối ưu retrieval.
- Chốt 1 contract thống nhất giữa UI path và QA path.

### 10.2 Thứ tự triển khai bắt buộc
1. A1 -> A2 -> A3 -> A4
2. C1 -> C2
3. D1 -> D2
4. Bàn giao cho Codex để làm B1/B2/B3 + D3/D4/E1

### 10.3 Định nghĩa "DONE" cho task của Claude
- Đã cập nhật status trong Task board.
- Đã append Handoff log theo đúng template.
- Có liệt kê file đã sửa.
- Có lệnh test và kết quả PASS/FAIL.
- Có ghi rõ "Next owner action" cho Codex.

### 10.4 Guardrail kỹ thuật (để tránh bug tích hợp)
- Không đổi chữ ký public `run(user_input, chat_history)` hiện có.
- `run_structured()` phải là API mới, không phá backward compatibility.
- Không để `build_validation_fallback` bị nhập nhằng kiểu args.
- Không chuyển ownership sang file `app.py` trong phase của Claude.

### 10.5 Payload bàn giao tối thiểu Claude phải ghi
- Patch summary theo từng Task ID.
- Danh sách test đã chạy:
  - `pytest tests/test_policy_unilateral_compensation.py -q`
  - `pytest tests/test_policy_dynamic_hints.py -q`
  - test mới cho `run_structured` và analyzer mismatch.
- Known risks (nếu còn) + cách reproduce.
- Step tiếp theo cho Codex theo thứ tự thực thi.
