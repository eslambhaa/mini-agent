import os
import re
import shlex
import sys
from pathlib import Path
from typing import List, Tuple

from typing import List as _L

WORKSPACE_DIR = Path(os.path.expanduser("~/agent-workspace")).resolve()

SYSTEM_BIN_DIRS = [
    "/usr/bin",
    "/bin",
    "/usr/sbin",
    "/sbin",
    "/usr/local/bin",
    "/opt/homebrew/bin",
]

BLOCKED_PATTERNS = [
    r"\bsudo\b",
    r"\bsu\b",
    r"\beval\b",
    r"\bkill(all)?\b",
    r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r)\b",
    r"\bmkfs\b",
    r"\bdd\b",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bchmod\s+777\b",
    r"\bchown\b",
    r"\bcurl\b.*\|\s*(sh|bash|zsh)",
    r"\bwget\b.*\|\s*(sh|bash|zsh)",
    r"\bgit\s+push\b.*(--force|\s-f\b)",
    r"\$\(",
    r"`",
    r"\$HOME",
    r"\$\{",
    r">\s*(?!/dev/null)[/~]",
]

ALLOWED_COMMANDS = {
    "ls", "pwd", "cat", "head", "tail", "wc", "echo", "grep",
    "find", "mkdir", "touch", "pytest", "ruff", "python3",
}

ALLOWED_GIT_SUBCOMMANDS = {"status", "diff", "log", "add", "commit", "branch", "show"}

DANGEROUS_FIND_FLAGS = {"-exec", "-execdir", "-ok", "-delete"}


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


def _split_segments(command: str) -> List[str]:
    """تقسيم الأمر المركب (&&، ||، ;، |) لأجزاء منفصلة كل جزء يتفحص لوحده."""
    parts = re.split(r"&&|\|\||;|\||\n", command)
    return [p.strip() for p in parts if p.strip()]


def _check_path_tokens(tokens: List[str]) -> Tuple[bool, str]:
    """يتأكد إن أي مسار مطلق أو يبدأ بـ ~ يقع داخل مساحة العمل، مع استثناء الأوامر النظامية و/dev/null."""
    for token in tokens:
        if token.startswith("-"):
            continue
        if not (token.startswith("/") or token.startswith("~")):
            continue

        resolved = Path(token).expanduser().resolve()
        resolved_str = str(resolved)

        if resolved_str == "/dev/null":
            continue
        if any(resolved_str == d or resolved_str.startswith(d + "/") for d in SYSTEM_BIN_DIRS):
            continue
        if resolved != WORKSPACE_DIR and WORKSPACE_DIR not in resolved.parents:
            return False, f"Access Denied: المسار '{token}' خارج مساحة العمل."

    return True, "OK"


def _tier_for_tokens(tokens: List[str]) -> Tuple[str, str]:
    """يرجع (allow) للأوامر الآمنة، أو (approve) للأوامر اللي محتاجة موافقة المستخدم."""
    name = os.path.basename(tokens[0])

    if name == "git":
        sub = tokens[1] if len(tokens) > 1 else ""
        if sub in ALLOWED_GIT_SUBCOMMANDS:
            return "allow", ""
        return "approve", f"الأمر 'git {sub}' يحتاج موافقتك."

    if name == "python3":
        if len(tokens) >= 2 and tokens[1].endswith(".py") and "-c" not in tokens:
            return "allow", ""
        return "approve", "تشغيل python3 بدون ملف .py يحتاج موافقتك."

    if name == "find" and any(t in DANGEROUS_FIND_FLAGS for t in tokens):
        return "approve", "الأمر 'find' مع تنفيذ أو حذف يحتاج موافقتك."

    if name in ALLOWED_COMMANDS:
        return "allow", ""

    return "approve", f"الأمر '{name}' يحتاج موافقتك."


def _ask_user_approval(command: str, reasons: List[str]) -> Tuple[bool, str]:
    """يطلب موافقة المستخدم في الـ Terminal. لو مفيش مستخدم متاح يرفض تلقائياً."""
    reason_text = "; ".join(reasons)
    if not sys.stdin.isatty():
        return False, f"يحتاج موافقة المستخدم ولا يوجد مستخدم متاح للموافقة: {reason_text}"

    print(f"\n⚠️ طلب تنفيذ أمر يحتاج موافقتك:\n   {command}\n   السبب: {reason_text}")
    answer = input("هل توافق على التنفيذ؟ (y/n): ").strip().lower()
    if answer in ("y", "yes", "نعم"):
        return True, "OK (approved by user)"
    return False, "رفض المستخدم تنفيذ الأمر."


def validate_bash_command(command: str) -> Tuple[bool, str]:
    """
    يفحص أمر الـ Terminal قبل تنفيذه على 3 مستويات:
    1) ممنوع قطعاً (sudo، rm -rf، خروج من المجلد، command substitution).
    2) يحتاج موافقة المستخدم (rm، pip، git push، أي أمر غير مدرج في القائمة البيضاء).
    3) مسموح مباشرة (ls، cat، python3 ملف.py، git status، ...).
    يرجع (True, 'OK') للمسموح، أو (False, سبب_المنع).
    """
    cmd = command.strip()
    if not cmd:
        return False, "الأمر فارغ."

    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, cmd, re.IGNORECASE):
            return False, f"تم حظر الأمر لاحتوائه على نمط محظور: {pattern}"

    if ".." in cmd or "~/mini-agent" in cmd:
        return False, "تم حظر الأمر: غير مسموح بالوصول إلى خارج مساحة العمل أو لمجلد الوكيل."

    reasons = []
    for segment in _split_segments(cmd):
        try:
            tokens = shlex.split(segment)
        except ValueError:
            return False, "تم حظر الأمر: تنصيص غير مغلق."

        if not tokens:
            continue

        ok, msg = _check_path_tokens(tokens)
        if not ok:
            return False, msg

        tier, why = _tier_for_tokens(tokens)
        if tier == "approve":
            reasons.append(why)

    if reasons:
        return _ask_user_approval(cmd, reasons)

    return True, "OK"


TEST_CASES = [
    ("python3 hello.py", True),
    ("ls -la", True),
    ("git status", True),
    ("echo hi > out.txt", True),
    ("echo hi > /dev/null", True),
    ("cat /etc/passwd", False),
    ("cat ../x.txt", False),
    ("cat ~/.ssh/id_rsa", False),
    ("echo hi > /tmp/x", False),
    ("sudo ls", False),
    ("rm -rf /", False),
    ("echo $HOME", False),
    ("echo `whoami`", False),
    ("git push --force", False),
    ("cd /", False),
    ("rm hello.py", False),
    ("python3 -c 'import os'", False),
    ("ls && rm -rf /", False),
]


def run_self_test() -> None:
    passed = 0
    for command, expected in TEST_CASES:
        got, msg = validate_bash_command(command)
        ok = got == expected
        if ok:
            passed += 1
        status = "PASS" if ok else "FAIL"
        print(f"{status} | expected={expected} | got={got} | {command} | {msg}")
    print(f"نتيجة فحص الأوامر: {passed}/{len(TEST_CASES)}")

    try:
        validate_workspace_path("../mini-agent/MEMORY.md")
        print("FAIL | تم السماح بالخروج من المجلد")
    except SecurityViolationError:
        print("PASS | تم صد الخروج من المجلد")


if __name__ == "__main__":
    print(f"🔒 فحص جدار الحماية | مساحة العمل: {WORKSPACE_DIR}")
    run_self_test()
