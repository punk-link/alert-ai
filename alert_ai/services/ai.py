import asyncio
import json
import logging
from collections.abc import Awaitable, Callable

from anthropic import AsyncAnthropic
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from alert_ai.config import Settings
from alert_ai.models import AlertGroup
from alert_ai.services.rate_limiter import AsyncRateLimiter

logger = logging.getLogger(__name__)


def build_prompt(alert_group: AlertGroup) -> str:
    alerts_text = "\n".join(
        f"Alert {i+1}:\n"
        f"  Status: {a.status}\n"
        f"  Labels: {json.dumps(a.labels, ensure_ascii=False, indent=2)}\n"
        f"  Annotations: {json.dumps(a.annotations, ensure_ascii=False, indent=2)}\n"
        f"  StartsAt: {a.startsAt}\n"
        f"  EndsAt: {a.endsAt or '—'}"
        for i, a in enumerate(alert_group.alerts)
    )
    return f"""Ты — опытный SRE / DevOps инженер, мастер шумоподавления Prometheus-алертов.
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


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
async def analyze_alert_group(
    alert_group: AlertGroup,
    client: AsyncAnthropic,
    settings: Settings,
) -> str:
    message = await client.messages.create(
        model=settings.anthropic_model,
        max_tokens=settings.max_tokens,
        temperature=settings.temperature,
        messages=[{"role": "user", "content": build_prompt(alert_group)}],
    )
    return message.content[0].text.strip()


class AlertAnalysisService:
    """Owns the Anthropic client, rate limiter, and overflow queue.

    Call ``start()`` once (e.g. in the FastAPI lifespan) to launch the
    background worker, and ``stop()`` to shut it down cleanly.
    """

    def __init__(
        self,
        client: AsyncAnthropic,
        settings: Settings,
        on_result: Callable[[str], Awaitable[None]],
    ) -> None:
        self._client = client
        self._settings = settings
        self._on_result = on_result
        self._rate_limiter = AsyncRateLimiter(max_calls=settings.anthropic_rate_limit_per_minute)
        self._queue: asyncio.Queue[AlertGroup] = asyncio.Queue(
            maxsize=settings.alert_queue_max_size
        )
        self._worker_task: asyncio.Task | None = None

    async def start(self) -> None:
        self._worker_task = asyncio.create_task(self._worker())

    async def stop(self) -> None:
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass

    async def submit(self, alert_group: AlertGroup) -> str:
        """Process *alert_group* immediately if under the rate limit, otherwise enqueue it.

        Returns one of: ``"processed"``, ``"queued"``, ``"dropped"``.
        Raises on analysis errors so the caller can send an error notification.
        """
        if self._rate_limiter.acquire():
            result = await analyze_alert_group(alert_group, self._client, self._settings)
            await self._on_result(result)
            return "processed"
        try:
            self._queue.put_nowait(alert_group)
            logger.info(
                "Rate limit reached; alert group queued (groupKey=%s, queue_size=%d)",
                alert_group.groupKey,
                self._queue.qsize(),
            )
            return "queued"
        except asyncio.QueueFull:
            logger.warning(
                "Rate limit reached and queue is full; alert group dropped (groupKey=%s)",
                alert_group.groupKey,
            )
            return "dropped"

    async def _worker(self) -> None:
        """Drain the overflow queue, respecting the rate limiter."""
        while True:
            alert_group = await self._queue.get()
            try:
                # Wait for a slot without spamming the warning log.
                while not self._rate_limiter.acquire(silent=True):
                    wait = self._rate_limiter.seconds_until_next_slot()
                    await asyncio.sleep(max(wait, 0.5))

                logger.info(
                    "Processing queued alert group (groupKey=%s, queue_size=%d)",
                    alert_group.groupKey,
                    self._queue.qsize(),
                )
                result = await analyze_alert_group(alert_group, self._client, self._settings)
                await self._on_result(result)
            except asyncio.CancelledError:
                self._queue.task_done()
                raise
            except Exception as e:
                logger.error("Queued alert processing failed: %s", e, exc_info=True)
            finally:
                self._queue.task_done()
