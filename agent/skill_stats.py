import json
import os
from pathlib import Path
from typing import List, Tuple

BASE_DIR = Path(__file__).resolve().parent.parent
STATS_FILE = BASE_DIR / "skills" / "_stats.json"
SKILL_RULES = {"edit-and-verify": ("edit_file", "run_bash")}
FAILED_PREFIXES = ("Error", "Security Error")


def _is_subsequence(seq: List[str], pattern: Tuple[str, ...]) -> bool:
    """يتحقق إن الأدوات جت بالترتيب المطلوب، حتى لو فيه أدوات تانية بينهم."""
    idx = 0
    for tool in seq:
        if idx < len(pattern) and tool == pattern[idx]:
            idx += 1
    return idx == len(pattern)


def _verified(events: List[Tuple[str, str]]) -> bool:
    """النجاح لازم يكون إن آخر run_bash خرج بكود 0."""
    runs = [obs for tool, obs in events if tool == "run_bash"]
    return bool(runs) and "Exit Code: 0" in runs[-1]


def _load() -> dict:
    if not STATS_FILE.exists():
        return {}
    data = json.loads(STATS_FILE.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("stats file is not a JSON object")
    return data


def _save(data: dict) -> None:
    STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, STATS_FILE)


def record_task(events: List[Tuple[str, str]], finished: bool) -> None:
    """يسجل نتيجة المهمة لكل مهارة انطبقت عليها. يتجاهل تشغيلات القياس، ولا يكتب لو الملف بايظ."""
    if os.getenv("MINI_AGENT_WORKSPACE"):
        return
    try:
        successful = [tool for tool, obs in events if not obs.startswith(FAILED_PREFIXES)]
        matched = [name for name, pattern in SKILL_RULES.items() if _is_subsequence(successful, pattern)]
        if not matched:
            return
        stats = _load()
        ok = finished and _verified(events)
        for name in matched:
            entry = stats.setdefault(name, {"used": 0, "ok": 0, "failed": 0})
            entry["used"] += 1
            entry["ok" if ok else "failed"] += 1
        _save(stats)
    except Exception:
        return
