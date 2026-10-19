import subprocess
from typing import Dict, Any
from agent.safety import (
    WORKSPACE_DIR,
    SecurityViolationError,
    ensure_workspace_exists,
    validate_workspace_path,
    validate_bash_command,
)

MAX_OUTPUT_CHARS = 4000
DEFAULT_TIMEOUT_SEC = 30


def _truncate_output(text: str, max_chars: int = MAX_OUTPUT_CHARS) -> str:
    """قص النصوص الطويلة جداً لحماية نافذة السياق (Context Window) وذاكرة الرام."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n...[Output truncated: exceeded {max_chars} chars]..."


def list_files(rel_path: str = ".") -> str:
    """عرض قائمة الملفات والمجلدات داخل مسار معين في مساحة العمل."""
    try:
        target_dir = validate_workspace_path(rel_path)
        if not target_dir.exists():
            return f"Error: المسار '{rel_path}' غير موجود."
        if not target_dir.is_dir():
            return f"Error: '{rel_path}' ليس مجلداً."

        items = []
        for item in sorted(target_dir.iterdir()):
            prefix = "[DIR] " if item.is_dir() else "[FILE]"
            rel_item = item.relative_to(WORKSPACE_DIR)
            items.append(f"{prefix} {rel_item}")

        return "\n".join(items) if items else "(المجلد فارغ)"
    except SecurityViolationError as sec_err:
        return f"Security Error: {sec_err}"
    except Exception as err:
        return f"Error listing files: {err}"


def read_file(rel_path: str) -> str:
    """قراءة محتوى ملف نصي من داخل مساحة العمل."""
    try:
        file_path = validate_workspace_path(rel_path)
        if not file_path.exists():
            return f"Error: الملف '{rel_path}' غير موجود."
        if not file_path.is_file():
            return f"Error: '{rel_path}' ليس ملفاً عادياً."

        content = file_path.read_text(encoding="utf-8", errors="replace")
        return _truncate_output(content)
    except SecurityViolationError as sec_err:
        return f"Security Error: {sec_err}"
    except Exception as err:
        return f"Error reading file '{rel_path}': {err}"


def write_file(rel_path: str, content: str) -> str:
    """إنشاء أو كتابة محتوى داخل ملف في مساحة العمل."""
    try:
        file_path = validate_workspace_path(rel_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        rel_saved = file_path.relative_to(WORKSPACE_DIR)
        return f"Success: تم حفظ الملف '{rel_saved}' ({len(content)} bytes)."
    except SecurityViolationError as sec_err:
        return f"Security Error: {sec_err}"
    except Exception as err:
        return f"Error writing file '{rel_path}': {err}"


def run_bash(command: str, timeout: int = DEFAULT_TIMEOUT_SEC) -> str:
    """تشغيل أمر Terminal آمن داخل ~/agent-workspace فقط مع مهلة زمنية."""
    ensure_workspace_exists()
    is_safe, reason = validate_bash_command(command)
    if not is_safe:
        return f"Security Error: {reason}"

    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=str(WORKSPACE_DIR),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        output_parts = [f"Exit Code: {result.returncode}"]
        if stdout:
            output_parts.append(f"STDOUT:\n{stdout}")
        if stderr:
            output_parts.append(f"STDERR:\n{stderr}")

        return _truncate_output("\n".join(output_parts))
    except subprocess.TimeoutExpired:
        return f"Error: تجاوز الأمر المهلة الزمنية المحددة ({timeout}s) وتم إيقافه لمنع التجميد."
    except Exception as err:
        return f"Error executing command: {err}"


def execute_tool(tool_name: str, args: Dict[str, Any]) -> str:
    """موجّه موحّد (Dispatcher) لتنفيذ الأداة المطلوبة بناءً على اسمها."""
    if tool_name == "list_files":
        return list_files(args.get("path", "."))
    elif tool_name == "read_file":
        return read_file(args.get("path", ""))
    elif tool_name == "write_file":
        return write_file(args.get("path", ""), args.get("content", ""))
    elif tool_name == "run_bash":
        return run_bash(args.get("command", ""))
    else:
        return f"Error: الأداة '{tool_name}' غير معروفة."


if __name__ == "__main__":
    print("🛠️ اختبار أدوات الوكيل داخل مساحة العمل...")

    w_res = write_file("hello_test.py", "print('Hello from Mini-Agent Workspace!')\n")
    print("1. Write File ->", w_res)

    l_res = list_files(".")
    print("2. List Files ->\n" + l_res)

    r_res = read_file("hello_test.py")
    print("3. Read File ->", r_res.strip())

    b_res = run_bash("python3 hello_test.py")
    print("4. Run Bash ->\n" + b_res)

    clean_res = run_bash("rm hello_test.py")
    print("5. Cleanup ->", clean_res)
