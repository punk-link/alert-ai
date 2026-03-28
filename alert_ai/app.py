import json
import logging

from anthropic import AsyncAnthropic
from aiogram import Bot
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from prometheus_fastapi_instrumentator import Instrumentator

from alert_ai.config import Settings
from alert_ai.models import AlertAnalysisResult, AlertGroup
from alert_ai.services.ai import AlertAnalysisService, format_result_for_telegram
from alert_ai.services.dedup import AlertDeduplicator
from alert_ai.services.telegram import send_to_telegram

logger = logging.getLogger(__name__)

_ERROR_PAYLOAD_MAX = 500


def create_app() -> FastAPI:
    settings = Settings()
    bot = Bot(token=settings.telegram_bot_token)
    anthropic_client = AsyncAnthropic(
        api_key=settings.anthropic_api_key,
        timeout=30.0,
    )
    deduplicator = AlertDeduplicator(ttl_seconds=settings.dedup_ttl_seconds)

    async def _send_result(result: AlertAnalysisResult) -> None:
        if result.verdict == "SUPPRESS":
            logger.info("Alert suppressed by AI (priority=%s), not forwarding to Telegram", result.priority)
            return
        resolved = result.status == "resolved"
        header = "✅ *Алерт восстановлен*" if resolved else "🚨 *AI-обработанный алерт от Prometheus*"
        await send_to_telegram(
            header + "\n\n" + format_result_for_telegram(result, resolved=resolved),
            bot,
            settings.telegram_channel_id,
        )

    ai_service = AlertAnalysisService(
        client=anthropic_client,
        settings=settings,
        on_result=_send_result,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await ai_service.start()
        yield
        await ai_service.stop()
        await bot.session.close()

    app = FastAPI(title="Prometheus Alert → AI → Telegram", lifespan=lifespan)

    Instrumentator().instrument(app).expose(app)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    async def _parse_payload(payload: dict) -> AlertGroup:
        try:
            return AlertGroup(**payload)
        except Exception as e:
            logger.warning("Invalid alert payload: %s", e)
            raw_preview = json.dumps(payload, ensure_ascii=False)[:_ERROR_PAYLOAD_MAX]
            await send_to_telegram(
                f"⚠️ *Получен невалидный payload от AlertManager!*\n\nОшибка:\n```\n{e}\n```\n\nRaw (preview):\n```\n{raw_preview}\n```",
                bot,
                settings.telegram_channel_id,
            )
            raise HTTPException(status_code=400, detail="Invalid alert payload")

    @app.post("/webhook")
    async def handle_alert(request: Request):
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON")

        if "alerts" not in payload:
            return {"status": "ignored"}

        alert_group = await _parse_payload(payload)

        if deduplicator.is_duplicate(alert_group):
            return {"status": "deduplicated"}

        try:
            status = await ai_service.submit(alert_group)
            return {"status": status}
        except Exception as e:
            logger.error("Alert processing failed: %s", e, exc_info=True)
            raw_preview = json.dumps(payload, ensure_ascii=False)[:_ERROR_PAYLOAD_MAX]
            await send_to_telegram(
                f"⚠️ *Ошибка обработки алерта!*\n\nПодробности — в логах сервиса.\n\nRaw (preview):\n```\n{raw_preview}\n```",
                bot,
                settings.telegram_channel_id,
            )
            return {"status": "error"}

    return app
