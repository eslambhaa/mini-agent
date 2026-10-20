import ast
import json
import re
import subprocess
from typing import Dict, Any, Optional, Tuple
from agent.safety import (
    WORKSPACE_DIR,
    SecurityViolationError,
    ensure_workspace_exists,
    validate_workspace_path,
    validate_bash_command,
    _ask_user_approval,
)

MAX_OUTPUT_CHARS = 4000
DEFAULT_TIMEOUT_SEC = 30
MAX_SEARCH_RESULTS = 50


def _check_json(file_path: Path) -> Optional[str]:
    """يتحقق إن ملف JSON صالح، ويرجع رسالة الخطأ للموديل لو فيه مشكلة."""
    try:
        json.loads(file_path.read_text(encoding="utf-8"))
        return None
    except json.JSONDecodeError as err:
        return f"JSONError في السطر {err.lineno}: {err.msg}. الملف لازم يكون JSON صالح، واستخدم json.dump بدل كتابة الـ dict كنص."


def _check_syntax(file_path: Path) -> Optional[str]:
    """يفحص صياغة ملفات بايثون قبل أي تشغيل ويرجع رسالة الخطأ للموديل لو فيه مشكلة."""
    if file_path.suffix == ".json":
        return _check_json(file_path)
    if file_path.suffix != ".py":
        return None
    try:
        compile(file_path.read_text(encoding="utf-8"), str(file_path), "exec")
        return None
    except SyntaxError as err:
        return f"SyntaxError في السطر {err.lineno}: {err.msg}. صلح الصياغة وحاول تاني."


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


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def read_file(rel_path: str, start_line: Any = None, end_line: Any = None) -> str:
    """قراءة محتوى ملف نصي من داخل مساحة العمل."""
    try:
        file_path = validate_workspace_path(rel_path)
        if not file_path.exists():
            return f"Error: الملف '{rel_path}' غير موجود."
        if not file_path.is_file():
            return f"Error: '{rel_path}' ليس ملفاً عادياً."

        content = file_path.read_text(encoding="utf-8", errors="replace")
        if start_line is not None or end_line is not None:
            lines = content.splitlines()
            start = max(_to_int(start_line, 1), 1)
            end = min(_to_int(end_line, len(lines)), len(lines))
            if start > end:
                return f"Error: نطاق الأسطر غير صالح، الملف فيه {len(lines)} سطر."
            numbered = [f"{n}: {lines[n - 1]}" for n in range(start, end + 1)]
            return _truncate_output("\n".join(numbered))
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
        syntax_err = _check_syntax(file_path)
        if syntax_err:
            return f"Success: تم حفظ الملف '{rel_saved}' ({len(content)} bytes).\nWarning: {syntax_err}"
        return f"Success: تم حفظ الملف '{rel_saved}' ({len(content)} bytes)."
    except SecurityViolationError as sec_err:
        return f"Security Error: {sec_err}"
    except Exception as err:
        return f"Error writing file '{rel_path}': {err}"


def _fuzzy_replace(content: str, old_text: str, new_text: str) -> Tuple[Optional[str], Optional[str]]:
    """
    يستبدل old_text بـ new_text داخل content.
    أولاً يحاول المطابقة الحرفية، ولو فشلت يطابق سطراً بسطر متجاهلاً المسافات
    البادئة والزائدة، لأن النماذج الصغيرة بتخطئ كتير في عدد المسافات.
    يرجع (المحتوى الجديد, None) عند النجاح، أو (None, سبب الفشل).
    """
    if not old_text.strip():
        return None, "old_text فارغ، لازم تحدد الجزء اللي عايز تغيّره."

    occurrences = content.count(old_text)
    if occurrences == 1:
        return content.replace(old_text, new_text, 1), None
    if occurrences > 1:
        return None, f"old_text موجود {occurrences} مرات، أضف أسطر إضافية عشان يبقى فريداً."

    old_lines = [line.strip() for line in old_text.strip("\n").splitlines()]
    file_lines = content.splitlines(keepends=True)
    stripped_lines = [line.strip() for line in file_lines]
    n = len(old_lines)

    matches = [
        i for i in range(len(file_lines) - n + 1)
        if stripped_lines[i:i + n] == old_lines
    ]
    if not matches:
        return None, "old_text غير موجود في الملف، اقرا الملف تاني وانسخ الجزء بالظبط."
    if len(matches) > 1:
        return None, f"old_text يطابق {len(matches)} أماكن، أضف أسطر إضافية عشان يبقى فريداً."

    start = matches[0]
    new_block = new_text if new_text.endswith("\n") else new_text + "\n"
    file_lines[start:start + n] = [new_block]
    return "".join(file_lines), None


def edit_file(rel_path: str, old_text: str, new_text: str) -> str:
    """تعديل جزء محدد من ملف موجود بدل إعادة كتابته كاملاً."""
    try:
        file_path = validate_workspace_path(rel_path)
        if not file_path.exists():
            return f"Error: الملف '{rel_path}' غير موجود."
        if not file_path.is_file():
            return f"Error: '{rel_path}' ليس ملفاً عادياً."

        content = file_path.read_text(encoding="utf-8", errors="replace")
        new_content, reason = _fuzzy_replace(content, old_text, new_text)
        if new_content is None:
            if new_text and new_text.strip() and new_text in content:
                return f"Success: الملف '{rel_path}' فيه النص الجديد بالفعل، مفيش تعديل مطلوب تاني."
            return f"Error: فشل التعديل على '{rel_path}': {reason}"

        file_path.write_text(new_content, encoding="utf-8")
        syntax_err = _check_syntax(file_path)
        if syntax_err:
            return f"Success: تم تعديل الملف '{rel_path}'.\nWarning: {syntax_err}"
        return f"Success: تم تعديل الملف '{rel_path}'."
    except SecurityViolationError as sec_err:
        return f"Security Error: {sec_err}"
    except Exception as err:
        return f"Error editing file '{rel_path}': {err}"


def search_files(query: str, path: str = ".") -> str:
    """البحث عن نص داخل الملفات في مساحة العمل وإرجاع رقم السطر لكل تطابق."""
    if not query:
        return "Error: query فارغ."
    try:
        base = validate_workspace_path(path)
        if not base.exists():
            return f"Error: المسار '{path}' غير موجود."

        candidates = [base] if base.is_file() else sorted(base.rglob("*"))
        results = []
        for file_path in candidates:
            if not file_path.is_file():
                continue
            rel_item = file_path.relative_to(WORKSPACE_DIR)
            if query in file_path.name:
                results.append(f"[FILE] {rel_item}")
            try:
                lines = file_path.read_text(encoding="utf-8").splitlines()
            except (UnicodeDecodeError, OSError):
                continue
            for line_no, line in enumerate(lines, start=1):
                if query in line:
                    results.append(f"{rel_item}:{line_no}: {line.strip()}")
                    if len(results) >= MAX_SEARCH_RESULTS:
                        results.append(f"...[توقف البحث عند {MAX_SEARCH_RESULTS} نتيجة]")
                        return _truncate_output("\n".join(results))

        return _truncate_output("\n".join(results)) if results else f"لا توجد نتائج لـ '{query}'."
    except SecurityViolationError as sec_err:
        return f"Security Error: {sec_err}"
    except Exception as err:
        return f"Error searching files: {err}"


MAP_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv"}
MAX_MAP_FILES = 60


def _py_outline(file_path: Path) -> list:
    """يستخرج الكلاسات والدوال وأرقام أسطرها من ملف بايثون بمكتبة ast بدون استهلاك توكن."""
    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return ["    (تعذر تحليل الملف)"]
    func_types = (ast.FunctionDef, ast.AsyncFunctionDef)
    lines = []
    for node in tree.body:
        if isinstance(node, func_types):
            lines.append(f"    def {node.name}  (line {node.lineno})")
        elif isinstance(node, ast.ClassDef):
            lines.append(f"    class {node.name}  (line {node.lineno})")
            for sub in node.body:
                if isinstance(sub, func_types):
                    lines.append(f"        def {sub.name}  (line {sub.lineno})")
    return lines


def project_map(path: str = ".") -> str:
    """خريطة المشروع: الملفات، وللملفات py الكلاسات والدوال مع أرقام الأسطر."""
    try:
        base = validate_workspace_path(path)
        if not base.exists():
            return f"Error: المسار '{path}' غير موجود."
        candidates = [base] if base.is_file() else sorted(base.rglob("*"))
        files = []
        for item in candidates:
            if not item.is_file():
                continue
            parts = item.relative_to(base).parts if base.is_dir() else ()
            if any(part in MAP_SKIP_DIRS or part.startswith(".") for part in parts):
                continue
            files.append(item)

        out = []
        for item in files[:MAX_MAP_FILES]:
            rel = item.relative_to(WORKSPACE_DIR)
            if item.suffix == ".py":
                out.append(str(rel))
                out.extend(_py_outline(item))
            else:
                out.append(f"{rel}  ({item.stat().st_size} bytes)")
        if len(files) > MAX_MAP_FILES:
            out.append(f"...[عرض أول {MAX_MAP_FILES} ملف من {len(files)}]")
        return _truncate_output("\n".join(out)) if out else "(لا توجد ملفات)"
    except SecurityViolationError as sec_err:
        return f"Security Error: {sec_err}"
    except Exception as err:
        return f"Error building project map: {err}"


SECRET_FILE_RE = re.compile(r"(^|/)(\.env(\..*)?|id_rsa.*|.*\.(pem|key))$")


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(WORKSPACE_DIR),
        capture_output=True,
        text=True,
        timeout=DEFAULT_TIMEOUT_SEC,
    )


def git_commit(message: str) -> str:
    """يجهز commit في مساحة العمل، يعرض الملفات المتغيرة، ويستنى موافقة المستخدم. لا يعمل push أبداً."""
    ensure_workspace_exists()
    if not message or not message.strip():
        return "Error: أداة git_commit محتاجة مفتاح 'message' فيه رسالة الـ commit."
    try:
        if _git("rev-parse", "--is-inside-work-tree").returncode != 0:
            return "Error: مساحة العمل مش مستودع git، والمستخدم لازم يعمل git init بنفسه."

        _git("add", "-A")
        names = _git("diff", "--cached", "--name-only").stdout.splitlines()
        if not names:
            return "لا توجد تغييرات للـ commit."

        for name in names:
            if SECRET_FILE_RE.search(name):
                _git("reset", "-q")
                return f"Security Error: الملف '{name}' شكله ملف أسرار ومش هيتعمل له commit."

        print("\n" + _git("diff", "--cached", "--stat").stdout.strip())
        approved, reason = _ask_user_approval(
            f'git commit -m "{message}"',
            ["commit جديد، راجع الملفات المعروضة فوق"],
        )
        if not approved:
            _git("reset", "-q")
            return f"Commit مرفوض: {reason}"

        result = _git("commit", "-m", message)
        out = (result.stdout + result.stderr).strip()
        return _truncate_output(f"Exit Code: {result.returncode}\n{out}")
    except subprocess.TimeoutExpired:
        return "Error: git تجاوز المهلة الزمنية."
    except Exception as err:
        return f"Error in git_commit: {err}"


def run_bash(command: str, timeout: int = DEFAULT_TIMEOUT_SEC) -> str:
    """تشغيل أمر Terminal آمن داخل ~/agent-workspace فقط مع مهلة زمنية."""
    ensure_workspace_exists()
    if not command or not command.strip():
        return "Error: أداة run_bash محتاجة مفتاح 'command' فيه نص الأمر. مثال: {\"tool\": \"run_bash\", \"args\": {\"command\": \"python3 hello.py\"}}"
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
        return read_file(args.get("path", ""), args.get("start_line"), args.get("end_line"))
    elif tool_name == "write_file":
        return write_file(args.get("path", ""), args.get("content", ""))
    elif tool_name == "edit_file":
        return edit_file(args.get("path", ""), args.get("old_text", ""), args.get("new_text", ""))
    elif tool_name == "search_files":
        return search_files(args.get("query", ""), args.get("path", "."))
    elif tool_name == "run_bash":
        return run_bash(args.get("command", ""))
    elif tool_name == "git_commit":
        return git_commit(args.get("message", ""))
    elif tool_name == "project_map":
        return project_map(args.get("path", "."))
    else:
        return (
            f"Error: الأداة '{tool_name}' غير معروفة. "
            "الأدوات المتاحة فقط: list_files, read_file, write_file, edit_file, "
            "search_files, run_bash, git_commit, project_map, finish. لتنفيذ أمر شل مثل mkdir استخدم run_bash "
            "مع args: {\"command\": \"mkdir -p dir\"}."
        )


if __name__ == "__main__":
    print("🛠️ اختبار أدوات الوكيل داخل مساحة العمل...")
    print("1. Write ->", write_file("hello_test.py", "def f():\n    return 1\n"))
    print("2. Edit exact ->", edit_file("hello_test.py", "    return 1", "    return 2"))
    print("3. Edit (single line, no indent) ->", edit_file("hello_test.py", "return 2", "return 3"))
    print("4. Search ->\n" + search_files("return", "."))
    print("5. Run ->", run_bash("python3 hello_test.py"))
    print("6. Cleanup ->", run_bash("rm hello_test.py"))
