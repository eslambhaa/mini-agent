import os
import requests
from typing import List, Dict, Optional

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
DEFAULT_MODEL = os.getenv("MINI_AGENT_MODEL", "qwen2.5-coder:3b")


class LocalLLM:
    """
    وحدة الاتصال بالموديل المحلي عبر Ollama API.
    مُحسّنة للعمل على جهاز MacBook Air 8GB RAM.
    """

    def __init__(self, model: str = DEFAULT_MODEL, num_ctx: int = 4096):
        self.model = model
        self.num_ctx = num_ctx
        self.chat_Endpoint = f"{OLLAMA_BASE_URL}/api/chat"

    def is_server_running(self) -> bool:
        """التحقق من أن خادم Ollama يعمل في الخلفية."""
        try:
            response = requests.get(OLLAMA_BASE_URL, timeout=3)
            return response.status_code == 200
        except requests.RequestException:
            return False

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.1,
    ) -> Optional[str]:
        """
        إرسال محادثة للموديل المحلي وإرجاع النص الناتج.
        temperature=0.1 لزيادة الدقة البرمجية وتقليل الهلوسة.
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "keep_alive": "2m",
            "options": {
                "num_ctx": self.num_ctx,
                "temperature": temperature,
            },
        }

        try:
            response = requests.post(self.chat_Endpoint, json=payload, timeout=120)
            response.raise_for_status()
            data = response.json()
            return data.get("message", {}).get("content", "").strip()
        except requests.RequestException as err:
            print(f"[LLM Error] فشل الاتصال بـ Ollama: {err}")
            return None


if __name__ == "__main__":
    llm = LocalLLM()
    if not llm.is_server_running():
        print("❌ خادم Ollama غير مشغل. شغّل تطبيق Ollama أو نفذ: ollama serve")
        exit(1)

    print(f"✅ متصل بـ Ollama | الموديل: {llm.model} | السياق: {llm.num_ctx}")
    test_messages = [
        {"role": "system", "content": "You are a concise coding assistant. Reply with code only."},
        {"role": "user", "content": "Write a one-line Python function to add two numbers a and b."}
    ]
    reply = llm.chat(test_messages)
    print("=== رد الموديل ===")
    print(reply)
