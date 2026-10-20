import json
import os
import sys
import time
from datetime import datetime, timezone

from agent.core import MiniAgent, LOG_FILE
from agent.safety import WORKSPACE_DIR
from evals.run_evals import EVAL_SUITE, EVAL_RESULTS_FILE, clean_workspace

DEFAULT_RUNS = 3
BENCH_RESULTS_FILE = EVAL_RESULTS_FILE.parent / "bench.jsonl"
STEP_EVENTS = {"tool_execution", "parse_error", "task_finish", "task_max_steps_reached"}


def read_log_lines():
    if not LOG_FILE.exists():
        return []
    return LOG_FILE.read_text(encoding="utf-8").splitlines()


def new_events(before):
    events = []
    for line in read_log_lines()[before:]:
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def run_once(run_index):
    clean_workspace()
    agent = MiniAgent(max_steps=6, use_planner=os.getenv("MINI_AGENT_PLANNER") == "1")
    details = []
    start_all = time.time()

    for idx, item in enumerate(EVAL_SUITE, start=1):
        print(f"\n[run {run_index}] [{idx}/{len(EVAL_SUITE)}] {item['id']}")
        if item["setup"]:
            item["setup"]()

        before = len(read_log_lines())
        t0 = time.time()
        agent.run_task(item["prompt"])
        elapsed = round(time.time() - t0, 2)

        events = new_events(before)
        steps = sum(1 for e in events if e.get("event") in STEP_EVENTS)
        parse_errors = sum(1 for e in events if e.get("event") == "parse_error")

        try:
            passed = bool(item["verify"]())
        except Exception as err:
            print(f"verify error: {err}")
            passed = False

        status = "PASS" if passed else "FAIL"
        print(f"---> {item['id']}: {status} | steps={steps} | parse_errors={parse_errors} | {elapsed}s")

        details.append({
            "id": item["id"],
            "passed": passed,
            "elapsed_sec": elapsed,
            "steps": steps,
            "parse_errors": parse_errors,
        })

    total = len(EVAL_SUITE)
    passed_count = sum(1 for d in details if d["passed"])
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run": run_index,
        "model": agent.llm.model,
        "passed": passed_count,
        "total": total,
        "score_pct": round(passed_count / total * 100, 1),
        "total_time_sec": round(time.time() - start_all, 2),
        "avg_steps": round(sum(d["steps"] for d in details) / total, 2),
        "parse_errors": sum(d["parse_errors"] for d in details),
        "details": details,
    }


def main():
    if "MINI_AGENT_WORKSPACE" not in os.environ:
        print("ERROR: لازم تحدد MINI_AGENT_WORKSPACE عشان ما يمسحش agent-workspace الحقيقي.")
        sys.exit(1)

    runs = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_RUNS
    print(f"workspace: {WORKSPACE_DIR}")
    print(f"runs: {runs}")

    records = []
    for r in range(1, runs + 1):
        record = run_once(r)
        records.append(record)
        with BENCH_RESULTS_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"\n=== run {r} score: {record['score_pct']}% | avg_steps: {record['avg_steps']} | parse_errors: {record['parse_errors']} | time: {record['total_time_sec']}s")

    avg_score = round(sum(r["score_pct"] for r in records) / len(records), 1)
    avg_time = round(sum(r["total_time_sec"] for r in records) / len(records), 2)
    avg_steps = round(sum(r["avg_steps"] for r in records) / len(records), 2)
    avg_parse = round(sum(r["parse_errors"] for r in records) / len(records), 2)

    print("\n==========================================")
    print(f"BASELINE over {runs} runs")
    print(f"متوسط نسبة النجاح: {avg_score}%")
    print(f"متوسط الزمن: {avg_time}s")
    print(f"متوسط عدد الخطوات لكل مهمة: {avg_steps}")
    print(f"متوسط أخطاء JSON لكل تشغيل: {avg_parse}")
    print("==========================================")


if __name__ == "__main__":
    main()
