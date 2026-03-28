import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable

from anthropic import AsyncAnthropic
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from alert_ai.config import Settings
from alert_ai.models import AlertAnalysisResult, AlertGroup
from alert_ai.services.rate_limiter import AsyncRateLimiter

logger = logging.getLogger(__name__)

PROMPT_VERSION = "3"

SYSTEM_PROMPT = """\
Ты — опытный SRE / DevOps инженер, мастер шумоподавления Prometheus-алертов.

Твоя задача — проанализировать группу алертов и решить:
- Это реальная проблема или шум / flapping / дубликат / ожидаемое поведение?
- Если проблема — объясни простым русским языком, что именно сломалось.
- Присвой приоритет:
  - P0 — критично, будить всех немедленно
  - P1 — срочно, требует внимания в течение часа
  - P2 — в рабочее время, не критично
  - P3 — можно игнорировать, информационный
  - P4 — шум, безопасно подавить
- Предложи 1–3 конкретных действия прямо сейчас.
- Если безопасно подавить — verdict должен быть "SUPPRESS", иначе "PROBLEM".
- Учитывай окружение при выборе приоритета:
  - Алерты из non-production окружений (dev, staging, test, qa и т.п.) понижаются на один уровень по сравнению с аналогичным инцидентом в prod (например, P1 → P2, P0 → P1). Никогда не присваивай P0 non-production окружению.
  - Тем не менее, если алерт является чистым шумом или flapping вне зависимости от окружения — присваивай P4 и verdict SUPPRESS.
- Оцени уверенность в диагнозе (0.0–1.0).
- Если можешь оценить масштаб/воздействие — укажи кратко (estimated_impact).
- Если можешь идентифицировать релевантный runbook или ключевое слово для поиска — укажи (related_runbook).

Отвечай СТРОГО в формате JSON (без markdown-обёрток, без пояснений):
{
  "priority": "Px",
  "verdict": "SUPPRESS" | "PROBLEM",
  "explanation": "кратко и понятно",
  "actions": ["шаг 1", "шаг 2"],
  "confidence": 0.0–1.0,
  "estimated_impact": "строка или null",
  "related_runbook": "строка или null"
}
"""


def build_user_message(alert_group: AlertGroup) -> str:
    common_label_keys = set(alert_group.commonLabels.keys())
    common_annotation_keys = set(alert_group.commonAnnotations.keys())

    alerts_data = []
    for a in alert_group.alerts:
        unique_labels = {k: v for k, v in a.labels.items() if k not in common_label_keys}
        unique_annotations = {k: v for k, v in a.annotations.items() if k not in common_annotation_keys}
        alert_entry: dict = {
            "status": a.status,
            "startsAt": a.startsAt,
        }
        if a.endsAt:
            alert_entry["endsAt"] = a.endsAt
        if a.fingerprint:
            alert_entry["fingerprint"] = a.fingerprint
        if unique_labels:
            alert_entry["labels"] = unique_labels
        if unique_annotations:
            alert_entry["annotations"] = unique_annotations
        alerts_data.append(alert_entry)

    payload = {
        "groupKey": alert_group.groupKey,
        "status": alert_group.status,
        "groupLabels": alert_group.groupLabels,
        "commonLabels": alert_group.commonLabels,
        "commonAnnotations": alert_group.commonAnnotations,
        "alerts": alerts_data,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def format_result_for_telegram(result: AlertAnalysisResult, *, resolved: bool = False) -> str:
    confidence_pct = f"{result.confidence * 100:.0f}%"

    if resolved:
        return "\n".join([
            f"**Приоритет:** {result.priority}",
            f"**Объяснение:** {result.explanation}",
            f"**Уверенность:** {confidence_pct}",
        ])

    verdict_display = "ПОДАВИТЬ" if result.verdict == "SUPPRESS" else "ПРОБЛЕМА"
    lines = [
        f"**Приоритет:** {result.priority}",
        f"**Вердикт:** {verdict_display}",
        f"**Объяснение:** {result.explanation}",
    ]
    if result.estimated_impact:
        lines.append(f"**Воздействие:** {result.estimated_impact}")
    lines.append("**Действия:**")
    for action in result.actions:
        lines.append(f"- {action}")
    lines.append(f"**Уверенность:** {confidence_pct}")
    if result.related_runbook:
        lines.append(f"**Runbook:** {result.related_runbook}")

    return "\n".join(lines)


def _extract_json(text: str) -> str:
    """Return the first top-level JSON object found in *text*, stripping any
    surrounding prose or markdown code fences the model may have added."""
    # Unwrap ```json ... ``` or ``` ... ``` fences first.
    fence = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
    if fence:
        return fence.group(1).strip()
    # Fall back to extracting the outermost { ... } block.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


def _parse_result(raw: str) -> AlertAnalysisResult:
    text = _extract_json(raw.strip())
    try:
        return AlertAnalysisResult.model_validate_json(text)
    except Exception as exc:
        logger.warning(
            "Failed to parse AI response as JSON (prompt_version=%s, error=%s); raw=%r",
            PROMPT_VERSION,
            exc,
            raw,
        )
        return AlertAnalysisResult(
            priority="P2",
            verdict="PROBLEM",
            explanation=raw,
            actions=[],
            confidence=0.0,
        )


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
) -> AlertAnalysisResult:
    message = await client.messages.create(
        model=settings.anthropic_model,
        max_tokens=settings.max_tokens,
        temperature=settings.temperature,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": build_user_message(alert_group)}],
    )
    logger.debug(
        "Anthropic usage (prompt_version=%s, groupKey=%s): %s",
        PROMPT_VERSION,
        alert_group.groupKey,
        message.usage,
    )
    text_block = next(b for b in message.content if b.type == "text")
    result = _parse_result(text_block.text.strip())
    result.status = alert_group.status
    return result


class AlertAnalysisService:
    """Owns the Anthropic client, rate limiter, and overflow queue.

    Call ``start()`` once (e.g. in the FastAPI lifespan) to launch the
    background worker, and ``stop()`` to shut it down cleanly.
    """

    def __init__(
        self,
        client: AsyncAnthropic,
        settings: Settings,
        on_result: Callable[[AlertAnalysisResult], Awaitable[None]],
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
