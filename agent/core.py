import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

from agent.llm import LocalLLM
from agent.tools import execute_tool
from agent.skills_manager import get_active_skills_prompt

BASE_DIR = Path(__file__).resolve().parent.parent
MEMORY_FILE = BASE_DIR / "MEMORY.md"
LOG_FILE = BASE_DIR / "logs" / "tasks.jsonl"

SYSTEM_PROMPT_TEMPLATE = """You are Mini Coder, a smart local coding agent on macOS.
Work inside the sandboxed workspace. Be direct and concise.

=== PERMANENT MEMORY ===
{memory}

=== AVAILABLE SKILLS ===
{skills}

=== TOOLS ===
1. list_files: {{"path": "."}}
2. read_file: {{"path": "file.py"}}
3. write_file: {{"path": "file.py", "content": "code"}}
4. edit_file: {{"path": "file.py", "old_text": "old", "new_text": "new"}}
5. search_files: {{"query": "text", "path": "."}}
6. run_bash: {{"command": "python3 file.py"}}
7. finish: {{"summary": "done"}}
8. git_commit: {{"message": "short commit message"}} (asks the user for approval)

=== RULES ===
- Keep code simple and direct. Avoid complex constructs when a plain loop or print statement is enough.
- If a tool result contains 'Warning', fix that file with write_file or edit_file and check again BEFORE calling finish. Do not create a different file to work around it.
- For .json files, write valid JSON text directly with write_file (double quotes only), not Python code.
- Write simple, clean code and test it using `run_bash` before finishing.
- Respond with ONLY a single valid JSON object.

Required keys: "thought", "tool", and "args".
Example:
{{
  "thought": "Writing script",
  "tool": "write_file",
  "args": {{"path": "test.py", "content": "print('ok')"}}
}}
"""


def load_memory() -> str:
    if not MEMORY_FILE.exists():
        return "No memory found."
    return "\n".join(MEMORY_FILE.read_text(encoding="utf-8").splitlines()[:30])


def log_event(event_data: Dict[str, Any]) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    record = {"timestamp": datetime.now(timezone.utc).isoformat(), **event_data}
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def parse_agent_json(raw_text: str) -> Optional[Dict[str, Any]]:
    if not raw_text:
        return None
    cleaned = raw_text.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                return None
        return None


class MiniAgent:
    def __init__(self, max_steps: int = 7):
        self.llm = LocalLLM()
        self.max_steps = max_steps

    def run_task(self, task: str) -> str:
        if not self.llm.is_server_running():
            return "❌ Error: Ollama is not running."

        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            memory=load_memory(),
            skills=get_active_skills_prompt(),
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Task: {task}"},
        ]

        print(f"🚀 Mini Coder Task (with Skills & Memory): {task}")
        log_event({"event": "task_start", "task": task})

        for step in range(1, self.max_steps + 1):
            print(f"\n--- [Step {step}/{self.max_steps}] ---")
            raw_reply = self.llm.chat(messages, json_mode=True)
            action = parse_agent_json(raw_reply or "")

            if not action or "tool" not in action:
                messages.append({"role": "assistant", "content": raw_reply or ""})
                messages.append({"role": "user", "content": "Error: Send valid JSON with thought, tool, args."})
                continue

            thought = action.get("thought", "")
            tool_name = action.get("tool", "")
            args = action.get("args", {})
            if not isinstance(args, dict):
                args = {}

            print(f"💭 {thought}")
            print(f"🔧 {tool_name} | {json.dumps(args, ensure_ascii=False)}")

            if tool_name == "finish":
                summary = args.get("summary", "Done.")
                print(f"\n✅ Finished: {summary}")
                log_event({"event": "task_finish", "step": step, "summary": summary})
                return summary

            observation = execute_tool(tool_name, args)
            print(f"📋 Result:\n{observation}")

            log_event({
                "event": "tool_execution",
                "step": step,
                "thought": thought,
                "tool": tool_name,
                "args": args,
                "observation": observation,
            })

            messages.append({"role": "assistant", "content": json.dumps(action, ensure_ascii=False)})
            messages.append({"role": "user", "content": f"Tool Observation:\n{observation}"})

        return "⚠️ Max steps reached."


if __name__ == "__main__":
    task_input = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Print hello."
    agent = MiniAgent()
    agent.run_task(task_input)
