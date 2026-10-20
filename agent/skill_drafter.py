import json
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
LOG_FILE = BASE_DIR / "logs" / "tasks.jsonl"
DRAFTS_DIR = BASE_DIR / "skills" / "_drafts"
MIN_COUNT = 5
KNOWN_TOOLS = {"list_files", "read_file", "write_file", "edit_file", "search_files", "run_bash", "project_map", "git_commit"}


def _collect_sequences():
    seqs = Counter()
    current = []
    for line in LOG_FILE.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        event = row.get("event")
        if event == "task_start":
            current = []
        elif event == "tool_execution":
            obs = str(row.get("observation", ""))
            tool = row.get("tool")
            if tool in KNOWN_TOOLS and not obs.startswith(("Error", "Security Error")):
                current.append(tool)
        elif event == "task_finish":
            for i in range(len(current) - 2):
                seqs[tuple(current[i:i + 3])] += 1
    return seqs


DRAFT_TEMPLATE = """# Skill draft: {name}

Pattern seen {count} times in successful tasks: {pattern}

## When to use
When the task asks to change an existing file and check that it still works.

## Steps
1. Find the file (search_files by name or content) or read it (read_file).
2. Change the exact lines with edit_file, keeping old_text unique.
3. Run the file with run_bash to verify the change.
4. If run_bash fails, read the error and fix the file again before finish.

## Status
DRAFT. Waiting for user approval before moving to skills/.
"""


def write_drafts() -> list:
    if not LOG_FILE.exists():
        return []
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    seqs = _collect_sequences()
    edit_verify = [(seq, n) for seq, n in seqs.items() if "edit_file" in seq and seq[-1] == "run_bash"]
    total = sum(n for _, n in edit_verify)
    if total < MIN_COUNT:
        return written
    name = "edit-and-verify"
    path = DRAFTS_DIR / f"{name}.md"
    if path.exists():
        return written
    patterns = "; ".join(" -> ".join(seq) + f" ({n}x)" for seq, n in sorted(edit_verify, key=lambda x: -x[1])[:4])
    path.write_text(DRAFT_TEMPLATE.format(name=name, count=total, pattern=patterns), encoding="utf-8")
    written.append(str(path.relative_to(BASE_DIR)))
    return written


if __name__ == "__main__":
    created = write_drafts()
    if created:
        for item in created:
            print("DRAFT:", item)
    else:
        print("لا توجد مسودات جديدة.")
