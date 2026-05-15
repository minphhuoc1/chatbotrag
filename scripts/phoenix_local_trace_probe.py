import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.legal_chatbot.observability import describe_observability_state, ensure_phoenix_instrumentation
from test_legal_qa import evaluate_case, init_runtime


PROBE_CASES = [
    {"id": 9001, "query": "Điều 35 quy định gì về quyền đơn phương chấm dứt hợp đồng của người lao động?"},
    {"id": 9002, "query": "Công ty chậm lương 2 tháng, tôi nghỉ ngay không báo trước được không?"},
    {"id": 9003, "query": "Trích nguyên văn Điều 113 Bộ luật Lao động."},
]


def main():
    os.environ.setdefault("LEGAL_CHATBOT_PHOENIX_ENABLED", "1")
    ensure_phoenix_instrumentation()
    print(f"[INFO] Observability: {json.dumps(describe_observability_state(), ensure_ascii=False)}")

    runtime = init_runtime()
    for case in PROBE_CASES:
        payload = {
            "id": case["id"],
            "query": case["query"],
            "expected_mode": "grounded_legal_answer",
            "must_reference_any_of": [],
            "must_not_hallucinate": True,
        }
        result = evaluate_case(runtime, payload)
        answer = result.get("answer_grounding_layer", {}).get("final_answer", "")
        print(f"[TRACE] Case {case['id']} => {answer[:180]}")

    print("[DONE] Phoenix probe completed. Open Phoenix UI to inspect traces.")


if __name__ == "__main__":
    main()

