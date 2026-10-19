import sys
from agent.core import MiniAgent


def main():
    print("==================================================")
    print("🤖 مرحباً بك في واجهة تفاعل Mini Coder المباشرة!")
    print("اكتب مهمتك البرمجية، أو اكتب 'exit' أو 'quit' للخروج.")
    print("==================================================")

    agent = MiniAgent()

    while True:
        try:
            task_input = input("\n💬 أدخل مهمتك لـ Mini Coder > ").strip()
            if not task_input:
                continue
            
            # التحقق من أمر الخروج في بايثون مباشرة قبل إرساله للوكيل
            if task_input.lower() in ["exit", "quit"]:
                print("👋 إلى اللقاء! تم إغلاق Mini Coder.")
                break

            agent.run_task(task_input)

        except KeyboardInterrupt:
            print("\n👋 تم إيقاف التشغيل بواسطة المستخدم.")
            break
        except Exception as e:
            print(f"❌ حدث خطأ غير متوقع: {e}")


if __name__ == "__main__":
    main()
