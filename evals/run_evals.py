import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from agent.core import MiniAgent
from agent.safety import WORKSPACE_DIR, ensure_workspace_exists

EVAL_RESULTS_FILE = Path(__file__).resolve().parent / "results.jsonl"


def clean_workspace() -> None:
    """تنظيف مساحة العمل قبل بدء اختبارات القياس لضمان بيئة معزولة."""
    ensure_workspace_exists()
    for item in WORKSPACE_DIR.iterdir():
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()


def setup_buggy_file() -> None:
    """تجهيز ملف يحتوي على خطأ برمجي للمهمة الثانية (Debugging)."""
    buggy_code = (
        "def compute_answer():\n"
        "    a = '40'\n"
        "    b = 2\n"
        "    return a + b\n\n"
        "print('Result:', compute_answer())\n"
    )
    (WORKSPACE_DIR / "eval_2_buggy.py").write_text(buggy_code, encoding="utf-8")


EVAL_SUITE = [
    {
        "id": "1_python_fib",
        "name": "Python Fibonacci Script",
        "setup": None,
        "prompt": (
            "Create a Python script named 'eval_1_fib.py' that prints the first 6 Fibonacci numbers "
            "as a comma-separated line: '0, 1, 1, 2, 3, 5'. Run it with run_bash to verify, then finish."
        ),
        "verify": lambda: (
            (WORKSPACE_DIR / "eval_1_fib.py").exists()
            and "0, 1, 1, 2, 3, 5" in __import__("subprocess").run(
                ["python3", str(WORKSPACE_DIR / "eval_1_fib.py")],
                capture_output=True, text=True, timeout=10
            ).stdout
        ),
    },
    {
        "id": "2_python_bugfix",
        "name": "Debug & Fix Existing Python File",
        "setup": setup_buggy_file,
        "prompt": (
            "There is a buggy file named 'eval_2_buggy.py' in the workspace. "
            "Read it, fix the TypeError so that running 'python3 eval_2_buggy.py' prints 'Result: 42', "
            "verify with run_bash, and then finish."
        ),
        "verify": lambda: (
            (WORKSPACE_DIR / "eval_2_buggy.py").exists()
            and "Result: 42" in __import__("subprocess").run(
                ["python3", str(WORKSPACE_DIR / "eval_2_buggy.py")],
                capture_output=True, text=True, timeout=10
            ).stdout
        ),
    },
    {
        "id": "3_web_html_js",
        "name": "HTML/JS Web Component Creation",
        "setup": None,
        "prompt": (
            "Create an HTML5 file named 'eval_3_index.html' containing an <h1> tag with text 'Mini-Agent', "
            "a <button> with id='action-btn', and a <script> tag. Then finish."
        ),
        "verify": lambda: (
            (WORKSPACE_DIR / "eval_3_index.html").exists()
            and "<h1" in (WORKSPACE_DIR / "eval_3_index.html").read_text(encoding="utf-8").lower()
            and "mini-agent" in (WORKSPACE_DIR / "eval_3_index.html").read_text(encoding="utf-8").lower()
            and "action-btn" in (WORKSPACE_DIR / "eval_3_index.html").read_text(encoding="utf-8")
            and "<script" in (WORKSPACE_DIR / "eval_3_index.html").read_text(encoding="utf-8").lower()
        ),
    },
    {
        "id": "4_bash_automation",
        "name": "Bash Directory & File Automation",
        "setup": None,
        "prompt": (
            "Create a directory named 'eval_4_dir' and inside it create a file 'eval_4_dir/status.txt' "
            "containing the exact word 'READY'. Verify it exists and then finish."
        ),
        "verify": lambda: (
            (WORKSPACE_DIR / "eval_4_dir" / "status.txt").exists()
            and "READY" in (WORKSPACE_DIR / "eval_4_dir" / "status.txt").read_text(encoding="utf-8")
        ),
    },
    {
        "id": "5_json_generation",
        "name": "Structured JSON File Output via Python",
        "setup": None,
        "prompt": (
            "Write and run a Python script that generates a JSON file named 'eval_5_out.json' "
            "with exact keys: {\"status\": \"passed\", \"count\": 3}. Verify the file content and finish."
        ),
        "verify": lambda: (
            (WORKSPACE_DIR / "eval_5_out.json").exists()
            and json.loads((WORKSPACE_DIR / "eval_5_out.json").read_text(encoding="utf-8")).get("status") == "passed"
            and json.loads((WORKSPACE_DIR / "eval_5_out.json").read_text(encoding="utf-8")).get("count") == 3
        ),
    },
]


def run_all_evals() -> None:
    print("🧪 بدء تشغيل مهام القياس الخمس الثابتة (Mini-Agent Benchmark)...")
    clean_workspace()
    agent = MiniAgent(max_steps=6)

    passed_count = 0
    details = []
    start_all = time.time()

    for idx, item in enumerate(EVAL_SUITE, start=1):
        print(f"\n==========================================")
        print(f"📌 اختبار [{idx}/5]: {item['name']} ({item['id']})")
        print(f"==========================================")

        if item["setup"]:
            item["setup"]()

        t0 = time.time()
        agent.run_task(item["prompt"])
        elapsed = round(time.time() - t0, 2)

        try:
            is_passed = bool(item["verify"]())
        except Exception as err:
            print(f"⚠️ خطأ أثناء فحص النتيجة: {err}")
            is_passed = False

        status_icon = "✅ PASS" if is_passed else "❌ FAIL"
        print(f"\n---> نتيجة [{item['id']}]: {status_icon} ({elapsed}s)")

        if is_passed:
            passed_count += 1

        details.append({
            "id": item["id"],
            "passed": is_passed,
            "elapsed_sec": elapsed,
        })

    total_time = round(time.time() - start_all, 2)
    score_pct = round((passed_count / len(EVAL_SUITE)) * 100, 1)

    print("\n==========================================")
    print(f"🏆 النتيجة النهائية للقياس (Eval Score): {passed_count}/{len(EVAL_SUITE)} ({score_pct}%) | الزمن الكلي: {total_time}s")
    print("==========================================")

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": agent.llm.model,
        "passed": passed_count,
        "total": len(EVAL_SUITE),
        "score_pct": score_pct,
        "total_time_sec": total_time,
        "details": details,
    }
    with EVAL_RESULTS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    run_all_evals()
