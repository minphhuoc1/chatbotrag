import argparse
import json
import os
import statistics
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
BENCH_DIR = ROOT_DIR / "reports" / "benchmarks"
BENCH_DIR.mkdir(parents=True, exist_ok=True)


def _run_cmd(cmd: list[str], env: dict | None = None):
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    subprocess.run(cmd, cwd=str(ROOT_DIR), env=merged_env, check=True)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _single_after_p1(stamp: str, idx: int) -> Path:
    out = BENCH_DIR / f"retrieval_single_after_p1_{stamp}_run{idx}.json"
    env = {
        "LEGAL_CHATBOT_RETRIEVAL_ENABLE_STRATEGY_ROUTER": "1",
        "LEGAL_CHATBOT_RETRIEVAL_ENABLE_LEXICAL": "1",
        "LEGAL_CHATBOT_RETRIEVAL_ENABLE_DETERMINISTIC_ARTICLE_BRANCH": "1",
        "LEGAL_CHATBOT_RETRIEVAL_ENABLE_RERANKER": "1",
        "LEGAL_CHATBOT_RETRIEVAL_ENABLE_METADATA_BOOST": "1",
    }
    cmd = [
        sys.executable,
        str(ROOT_DIR / "scripts" / "benchmark_retrieval_ab.py"),
        "--mode",
        "single",
        "--label",
        "after_p1",
        "--output",
        str(out),
    ]
    _run_cmd(cmd, env=env)
    return out


def _compare_before_after_p0(stamp: str, idx: int) -> Path:
    out = BENCH_DIR / f"retrieval_compare_p0_{stamp}_run{idx}.json"
    cmd = [
        sys.executable,
        str(ROOT_DIR / "scripts" / "benchmark_retrieval_ab.py"),
        "--mode",
        "compare",
        "--output",
        str(out),
    ]
    _run_cmd(cmd)
    return out


def _calc_stats(values: list[float]) -> dict:
    if not values:
        return {"mean": None, "stdev": None, "min": None, "max": None}
    return {
        "mean": round(statistics.mean(values), 4),
        "stdev": round(statistics.pstdev(values), 4),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
    }


def main():
    parser = argparse.ArgumentParser(description="Repeat retrieval benchmark and aggregate stats")
    parser.add_argument("--runs", type=int, default=5)
    args = parser.parse_args()

    runs = max(1, args.runs)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    before_p0_rows = []
    after_p0_rows = []
    after_p1_rows = []
    deltas_p0 = []
    deltas_p1 = []
    artifacts = []

    for idx in range(1, runs + 1):
        compare_path = _compare_before_after_p0(stamp, idx)
        compare_payload = _read_json(compare_path)
        before = compare_payload["before_summary"]
        after_p0 = compare_payload["after_summary"]
        before_p0_rows.append(before)
        after_p0_rows.append(after_p0)
        deltas_p0.append(compare_payload["delta"])
        artifacts.append(str(compare_path))

        after_p1_path = _single_after_p1(stamp, idx)
        after_p1_payload = _read_json(after_p1_path)
        after_p1 = after_p1_payload["summary"]
        after_p1_rows.append(after_p1)
        artifacts.append(str(after_p1_path))

        delta_p1 = {
            "hit_at_k": round(after_p1["hit_at_k"] - after_p0["hit_at_k"], 4),
            "mean_recall_at_k": round(after_p1["mean_recall_at_k"] - after_p0["mean_recall_at_k"], 4),
            "mrr_at_k": round(after_p1["mrr_at_k"] - after_p0["mrr_at_k"], 4),
            "latency_mean_ms": round(after_p1["latency_ms"]["mean"] - after_p0["latency_ms"]["mean"], 4),
            "latency_p95_ms": round(after_p1["latency_ms"]["p95"] - after_p0["latency_ms"]["p95"], 4),
        }
        deltas_p1.append(delta_p1)

    def _collect(rows: list[dict], key: str, nested: bool = False):
        vals = []
        for row in rows:
            if nested:
                vals.append(float(row["latency_ms"][key]))
            else:
                vals.append(float(row[key]))
        return vals

    aggregate = {
        "before_p0": {
            "hit_at_k": _calc_stats(_collect(before_p0_rows, "hit_at_k")),
            "mean_recall_at_k": _calc_stats(_collect(before_p0_rows, "mean_recall_at_k")),
            "mrr_at_k": _calc_stats(_collect(before_p0_rows, "mrr_at_k")),
            "latency_mean_ms": _calc_stats(_collect(before_p0_rows, "mean", nested=True)),
            "latency_p95_ms": _calc_stats(_collect(before_p0_rows, "p95", nested=True)),
        },
        "after_p0": {
            "hit_at_k": _calc_stats(_collect(after_p0_rows, "hit_at_k")),
            "mean_recall_at_k": _calc_stats(_collect(after_p0_rows, "mean_recall_at_k")),
            "mrr_at_k": _calc_stats(_collect(after_p0_rows, "mrr_at_k")),
            "latency_mean_ms": _calc_stats(_collect(after_p0_rows, "mean", nested=True)),
            "latency_p95_ms": _calc_stats(_collect(after_p0_rows, "p95", nested=True)),
        },
        "after_p1": {
            "hit_at_k": _calc_stats(_collect(after_p1_rows, "hit_at_k")),
            "mean_recall_at_k": _calc_stats(_collect(after_p1_rows, "mean_recall_at_k")),
            "mrr_at_k": _calc_stats(_collect(after_p1_rows, "mrr_at_k")),
            "latency_mean_ms": _calc_stats(_collect(after_p1_rows, "mean", nested=True)),
            "latency_p95_ms": _calc_stats(_collect(after_p1_rows, "p95", nested=True)),
        },
        "delta_before_after_p0": {
            "hit_at_k": _calc_stats([float(x["hit_at_k"]) for x in deltas_p0]),
            "mean_recall_at_k": _calc_stats([float(x["mean_recall_at_k"]) for x in deltas_p0]),
            "mrr_at_k": _calc_stats([float(x["mrr_at_k"]) for x in deltas_p0]),
            "latency_mean_ms": _calc_stats([float(x["latency_mean_ms"]) for x in deltas_p0]),
            "latency_p95_ms": _calc_stats([float(x["latency_p95_ms"]) for x in deltas_p0]),
        },
        "delta_after_p0_after_p1": {
            "hit_at_k": _calc_stats([float(x["hit_at_k"]) for x in deltas_p1]),
            "mean_recall_at_k": _calc_stats([float(x["mean_recall_at_k"]) for x in deltas_p1]),
            "mrr_at_k": _calc_stats([float(x["mrr_at_k"]) for x in deltas_p1]),
            "latency_mean_ms": _calc_stats([float(x["latency_mean_ms"]) for x in deltas_p1]),
            "latency_p95_ms": _calc_stats([float(x["latency_p95_ms"]) for x in deltas_p1]),
        },
    }

    payload = {
        "generated_at": datetime.now().isoformat(),
        "runs": runs,
        "artifacts": artifacts,
        "aggregate": aggregate,
    }

    out = BENCH_DIR / f"retrieval_repeat_{stamp}.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[BENCH-REPEAT] saved: {out}")
    print(json.dumps(aggregate["delta_before_after_p0"], ensure_ascii=False))
    print(json.dumps(aggregate["delta_after_p0_after_p1"], ensure_ascii=False))


if __name__ == "__main__":
    main()
