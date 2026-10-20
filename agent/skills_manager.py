from pathlib import Path
from typing import List

BASE_DIR = Path(__file__).resolve().parent.parent
SKILLS_DIR = BASE_DIR / "skills"


def list_available_skills() -> List[str]:
    """استعراض كافة المهارات المخزنة في مجلد skills/ باستثناء المسودات."""
    if not SKILLS_DIR.exists():
        return []
    skills = []
    for item in SKILLS_DIR.glob("*.md"):
        if item.is_file():
            skills.append(item.stem)
    return sorted(skills)


def load_skill_content(skill_name: str) -> str:
    """قراءة محتوى مهارة معينة من ملف Markdown الخاص بها."""
    skill_path = SKILLS_DIR / f"{skill_name}.md"
    if skill_path.exists() and skill_path.is_file():
        return skill_path.read_text(encoding="utf-8")
    return f"Error: Skill '{skill_name}' not found."


def get_active_skills_prompt() -> str:
    """إنشاء قسم المهارات المتاحة لإدراجه تلقائياً في الـ System Prompt للوكيل."""
    skills = list_available_skills()
    if not skills:
        return "No specific skills loaded."

    descriptions = []
    for s in skills:
        content = load_skill_content(s)
        useful = [ln.strip() for ln in content.splitlines() if ln.strip() and not ln.strip().startswith('#')]
        first_line = useful[0] if useful else s
        descriptions.append(f"- **{s}**: {first_line}")

    return "\n".join(descriptions)


if __name__ == "__main__":
    print("📚 اختبار نظام المهارات الديناميكية...")
    print("المهارات المتاحة:", list_available_skills())
    print("ملخص المهارات:\n", get_active_skills_prompt())
