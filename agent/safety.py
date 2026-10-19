import os
import re
from pathlib import Path
from typing import Tuple

WORKSPACE_DIR = Path(os.path.expanduser("~/agent-workspace")).resolve()

BLOCKED_COMMANDS = [
    r"\bsudo\b",
    r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r)\b",
    r"\brm\s+-rf\s+/",
    r"\bmkfs\b",
    r"\bdd\b",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bchmod\s+777\b",
    r"\bchown\b",
    r">\s*/dev/sd",
    r"\bcurl\b.*\|\s*(sh|bash|zsh)",
    r"\bwget\b.*\|\s*(sh|bash|zsh)",
]


class SecurityViolationError(Exception):
    """يُرفع عندما يحاول الوكيل خرق حدود الأمان أو مساحة العمل."""
    pass


def ensure_workspace_exists() -> Path:
    """التأكد من وجود مجلد مساحة العمل وإرجاع مساره الحقيقي."""
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    return WORKSPACE_DIR


def validate_workspace_path(target_path: str) -> Path:
    """
    يتحقق من أن المسار المطلوب يقع داخل ~/agent-workspace فقط.
    يمنع هجمات Path Traversal مثل ../../mini-agent/agent/llm.py
    """
    ensure_workspace_exists()
    candidate = Path(target_path)

    if not candidate.is_absolute():
        resolved_path = (WORKSPACE_DIR / candidate).resolve()
    else:
        resolved_path = candidate.expanduser().resolve()

    if resolved_path != WORKSPACE_DIR and WORKSPACE_DIR not in resolved_path.parents:
        raise SecurityViolationError(
            f"Access Denied: المسار '{target_path}' يقع خارج مساحة العمل الآمنة ({WORKSPACE_DIR})."
        )

    return resolved_path


def validate_bash_command(command: str) -> Tuple[bool, str]:
    """
    يفحص أمر الـ Terminal قبل تنفيذه لمنع الأوامر المدمرة أو الخروج من مساحة العمل.
    يرجع (True, 'OK') إذا كان آمناً، أو (False, سبب_المنع) إذا كان خطيراً.
    """
    cmd_stripped = command.strip()
    if not cmd_stripped:
        return False, "الأمر فارغ."

    for pattern in BLOCKED_COMMANDS:
        if re.search(pattern, cmd_stripped, re.IGNORECASE):
            return False, f"تم حظر الأمر لاحتوائه على نمط خطير محظور: {pattern}"

    if ".." in cmd_stripped or "~/mini-agent" in cmd_stripped:
        return False, "تم حظر الأمر: غير مسموح بالوصول إلى خارج مساحة العمل أو لمجلد الوكيل."

    return True, "OK"


if __name__ == "__main__":
    print(f"🔒 فحص جدار الحماية | مساحة العمل: {WORKSPACE_DIR}")

    safe_file = validate_workspace_path("project1/index.html")
    print(f"✅ مسار آمن مسموح: {safe_file}")

    try:
        validate_workspace_path("../mini-agent/MEMORY.md")
        print("❌ فشل الاختبار: تم السماح بمسار خارجي!")
    except SecurityViolationError as e:
        print(f"✅ تم صد محاولة اختراق المسار بنجاح: {e}")

    is_ok, msg = validate_bash_command("python3 main.py")
    print(f"✅ فحص أمر آمن (python3 main.py): {is_ok} ({msg})")

    is_ok, msg = validate_bash_command("sudo rm -rf /")
    print(f"✅ صد أمر خطير (sudo rm -rf /): {not is_ok} -> {msg}")
