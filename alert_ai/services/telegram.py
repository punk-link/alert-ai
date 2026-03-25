import logging

from aiogram import Bot
from aiogram.enums import ParseMode
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)

_TELEGRAM_MAX_LENGTH = 4096


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
async def send_to_telegram(text: str, bot: Bot, channel_id: str) -> None:
    if len(text) > _TELEGRAM_MAX_LENGTH:
        text = text[:_TELEGRAM_MAX_LENGTH - 3] + "..."
    await bot.send_message(
        chat_id=channel_id,
        text=text,
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )
