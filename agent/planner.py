import json
import os
import time
from typing import List, Tuple

import requests
from dotenv import load_dotenv

load_dotenv()

PLANNER_MODEL = "gemini-3.8-flash"
PLANNER_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{PLANNER_MODEL}:generateContent"
PLANNER_TIMEOUT_SEC = 120
PLANNER_RETRIES = 3
MAX_PLAN_STEPS = 6

PLANNER_INSTRUCTION = """You plan coding tasks for a small local agent.
The agent can use these tools: list_files, read_file, write_file, edit_file, search_files, run_bash, project_map, finish.
Return ONLY a JSON object: {"steps": ["step 1", "step 2"]}.
Use at most 6 short steps. Each step is one concrete action, for example: find the file that defines a function, edit one line, run the script to verify.
Do not write the code yourself. Do not add any text outside the JSON."""


def _post_with_retry(api_key: str, payload: dict) -> requests.Response:
    """يرسل الطلب، ويعيد المحاولة عند 429 أو 503 بانتظار متزايد."""
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
    response = None
    for attempt in range(PLANNER_RETRIES):
        response = requests.post(PLANNER_URL, headers=headers, json=payload, timeout=PLANNER_TIMEOUT_SEC)
        if response.status_code not in (429, 503):
            break
        time.sleep(5 * (attempt + 1))
    return response


def make_plan(task: str) -> Tuple[List[str], str]:
    """يكتب خطة قصيرة للمهمة بـ Gemini. يرجع (الخطوات, رسالة الخطأ). لا يرمي استثناء أبداً."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return [], "GEMINI_API_KEY غير موجود في ملف .env"
    if not task or not task.strip():
        return [], "المهمة فاضية"

    payload = {
        "systemInstruction": {"parts": [{"text": PLANNER_INSTRUCTION}]},
        "contents": [{"role": "user", "parts": [{"text": f"Task: {task}"}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2},
    }
    try:
        response = _post_with_retry(api_key, payload)
        if response.status_code != 200:
            return [], f"HTTP {response.status_code}: {response.text[:200]}"
        text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        data = json.loads(text)
        steps = data.get("steps", []) if isinstance(data, dict) else []
    except requests.RequestException as err:
        return [], f"فشل الاتصال: {type(err).__name__}"
    except (KeyError, IndexError, TypeError, ValueError) as err:
        return [], f"رد غير متوقع من Gemini: {err}"

    if not isinstance(steps, list):
        return [], "الخطوات مش في شكل قائمة"
    clean = [str(step).strip() for step in steps if str(step).strip()]
    return clean[:MAX_PLAN_STEPS], ""


if __name__ == "__main__":
    import sys

    task_text = " ".join(sys.argv[1:]) or "Create hello.py that prints Hello and run it to verify."
    plan_steps, plan_error = make_plan(task_text)
    if plan_error:
        print("ERROR:", plan_error)
    for index, step in enumerate(plan_steps, start=1):
        print(index, step)
