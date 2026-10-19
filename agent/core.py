import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

from agent.llm import LocalLLM
from agent.tools import execute_tool

BASE_DIR = Path(__file__).resolve().parent.parent
MEMORY_FILE = BASE_DIR / "MEMORY.md"
LOG_FILE = BASE_DIR / "logs" / "tasks.jsonl"

SYSTEM_PROMPT_TEMPLATE = """You are Mini-Agent, a local coding agent running on macOS.
You work strictly inside the sandboxed workspace directory.

=== PERMANENT MEMORY ===
{memory}

=== AVAILABLE TOOLS ===
1. list_files: {{"path": "."}}
2. read_file: {{"path": "relative/path.py"}}
3. write_file: {{"path": "relative/path.py", "content": "full file code"}}
4. run_bash: {{"command": "python3 relative/path.py"}}
5. finish: {{"summary": "Final answer and summary of what was accomplished"}}

=== STRICT OUTPUT FORMAT ===
Respond with ONLY a single valid JSON object per turn. Do NOT add extra text outside the JSON:
{{
  "thought": "Brief explanation of your next step",
  "tool": "tool_name",
  "args": {{ ... }}
}}
"""


def load_memory() -> str:
    """قراءة ملف الذاكرة الدائمة MEMORY.md (بحد أقصى 50 سطراً)."""
    if not MEMORY_FILE.exists():
        return "No memory file found."
    lines = MEMORY_FILE.read_text(encoding="utf-8").splitlines()[:50]
    return "\n".join(lines)


def log_event(event_data: Dict[str, Any]) -> None:
    """تسجيل خطوات المهمة والأوامر والأخطاء في logs/tasks.jsonl."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **event_data,
    }
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def parse_agent_json(raw_text: str) -> Optional[Dict[str, Any]]:
    """استخراج كائن JSON من رد الموديل حتى لو أحيط بعلامات Markdown."""
    if not raw_text:
        return None

    cleaned = raw_text.strip()
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1)
    else:
        brace_match = re.search(r"(\{.*\})", cleaned, re.DOTALL)
        if brace_match:
            cleaned = brace_match.group(1)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None


class MiniAgent:
    """الوكيل الأساسي المسؤول عن إدارة حلقة التفكير والتنفيذ (ReAct Loop)."""

    def __init__(self, max_steps: int = 8):
        self.llm = LocalLLM()
        self.max_steps = max_steps

    def run_task(self, task: str) -> str:
        if not self.llm.is_server_running():
            return "❌ Error: خادم Ollama غير مشغل."

        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(memory=load_memory())
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Task: {task}"},
        ]

        print(f"🚀 بدء المهمة: {task}")
        log_event({"event": "task_start", "task": task})

        for step in range(1, self.max_steps + 1):
            print(f"\n--- [Step {step}/{self.max_steps}] ---")
            raw_reply = self.llm.chat(messages)
            action = parse_agent_json(raw_reply or "")

            if not action or "tool" not in action:
                print(f"⚠️ رد غير منظم من الموديل، جاري طلب تصحيح JSON...")
                log_event({"event": "parse_error", "step": step, "raw": raw_reply})
                messages.append({"role": "assistant", "content": raw_reply or ""})
                messages.append({
                    "role": "user",
                    "content": "Error: Invalid JSON format. Respond ONLY with a valid JSON object containing 'thought', 'tool', and 'args'."
                })
                continue

            thought = action.get("thought", "")
            tool_name = action.get("tool", "")
            args = action.get("args", {})

            print(f"💭 التفكير: {thought}")
            print(f"🔧 الأداة: {tool_name} | المعاملات: {json.dumps(args, ensure_ascii=False)}")

            if tool_name == "finish":
                summary = args.get("summary", "تم إنجاز المهمة بنجاح.")
                print(f"\n✅ اكتملت المهمة: {summary}")
                log_event({"event": "task_finish", "step": step, "summary": summary})
                return summary

            observation = execute_tool(tool_name, args)
            print(f"📋 النتيجة:\n{observation}")

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

        timeout_msg = "⚠️ وصل الوكيل للحد الأقصى من الخطوات قبل استدعاء finish."
        print(f"\n{timeout_msg}")
        log_event({"event": "task_max_steps_reached", "task": task})
        return timeout_msg


if __name__ == "__main__":
    task_input = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else (
        "Create a Python script named 'calc.py' that prints the sum of squares from 1 to 5, "
        "run it using run_bash to verify the output is 55, and then finish."
    )
    agent = MiniAgent()
    agent.run_task(task_input)
