import json
import logging

from anthropic import AsyncAnthropic
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from alert_ai.config import Settings
from alert_ai.models import AlertGroup

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
