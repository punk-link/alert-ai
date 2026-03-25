# main.py
import os
import json
from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel
from anthropic import AsyncAnthropic
from aiogram import Bot
from aiogram.enums import ParseMode
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Prometheus Alert → AI → Telegram")

@app.get("/health")
async def health():
 return {"status": "ok"}

# Настройки
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")   # @channelname или -100XXXXXXXXXX
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

if not all([TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID, ANTHROPIC_API_KEY]):
    raise ValueError("Не все переменные окружения заданы в .env")

bot = Bot(token=TELEGRAM_BOT_TOKEN)
anthropic_client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

class AlertGroup(BaseModel):
    version: str
    groupKey: str
    status: str
    receiver: str
    groupLabels: dict
    commonLabels: dict
    commonAnnotations: dict
    externalURL: str
    alerts: list[dict]

@app.post("/webhook")
async def handle_alert(request: Request):
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Простая валидация
    if "alerts" not in payload:
        return {"status": "ignored"}

    alert_group = AlertGroup(**payload)

    # Формируем текст алертов для промпта
    alerts_text = "\n".join(
        f"Alert {i+1}:\n"
        f"  Status: {a['status']}\n"
        f"  Labels: {json.dumps(a['labels'], ensure_ascii=False, indent=2)}\n"
        f"  Annotations: {json.dumps(a['annotations'], ensure_ascii=False, indent=2)}\n"
        f"  StartsAt: {a['startsAt']}\n"
        f"  EndsAt: {a.get('endsAt', '—')}"
        for i, a in enumerate(alert_group.alerts)
    )

    prompt = f"""Ты — опытный SRE / DevOps инженер, мастер шумоподавления Prometheus-алертов.
Твоя задача — проанализировать группу алертов и решить:
- Это реальная проблема или шум / flapping / дубликат / ожидаемое поведение?
- Если проблема — объясни простым русским языком, что именно сломалось.
- Присвой приоритет: P0 (критично, будить всех), P1 (срочно), P2 (в рабочее время), P3 (можно игнорировать), P4 (шум).
- Что делать прямо сейчас (1–3 коротких действия).
- Если это безопасно подавить — ответь ровно словом "ПОДАВИТЬ" в начале ответа.

Группа алертов:
{alerts_text}

Отвечай ТОЛЬКО в формате Markdown, строго:
**Приоритет:** Px  
**Вердикт:** [ПОДАВИТЬ / ПРОБЛЕМА]  
**Объяснение:** [кратко и понятно]  
**Действия:**  
- шаг 1  
- шаг 2  

Без лишних слов, без приветствий.
"""

    try:
        message = await anthropic_client.messages.create(
            model="claude-sonnet-4-6",  # ← здесь можно claude-sonnet-4-6 если уже доступен
            # model="claude-sonnet-4-6",   # актуальный на март 2026 — проверь в https://docs.anthropic.com
            max_tokens=600,
            temperature=0.2,
            messages=[{"role": "user", "content": prompt}]
        )

        ai_response = message.content[0].text.strip()

        # Отправляем в Telegram-канал
        header = "🚨 AI-обработанный алерт от Prometheus\n\n"
        full_text = header + ai_response

        await bot.send_message(
            chat_id=TELEGRAM_CHANNEL_ID,
            text=full_text,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True
        )

        return {"status": "processed"}

    except Exception as e:
        # Логируй ошибку в продакшене (sentry / logging)
        print(f"Ошибка: {e}")
        await bot.send_message(
            chat_id=TELEGRAM_CHANNEL_ID,
            text=f"⚠️ Ошибка обработки алерта!\n\n{e}\n\nRaw:\n{json.dumps(payload, ensure_ascii=False, indent=2)}",
            parse_mode=ParseMode.MARKDOWN
        )
        return {"status": "error"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)