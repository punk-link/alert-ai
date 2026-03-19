# ──────────────────────────────────────────────────────────────
# Stage 1: Builder (зависимости + кэш)
# ──────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

# Устанавливаем uv — самый быстрый менеджер зависимостей 2025–2026
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.cargo/bin:$PATH"

WORKDIR /app

# Копируем только файлы зависимостей сначала → отличный кэш слоёв
COPY pyproject.toml uv.lock* requirements.txt* ./

# Если используешь uv + pyproject.toml → предпочтительно
# RUN uv sync --frozen --no-install-project
# Иначе классический requirements.txt
RUN uv venv /venv && \
    . /venv/bin/activate && \
    uv pip install --no-cache-dir \
        fastapi==0.115.* \
        uvicorn[standard]==0.32.* \
        gunicorn==23.0.* \
        anthropic==0.45.* \
        aiogram==3.13.* \
        python-dotenv==1.0.* \
        pydantic==2.10.*

# Копируем весь код приложения
COPY . .

# ──────────────────────────────────────────────────────────────
# Stage 2: Runtime (минимальный образ)
# ──────────────────────────────────────────────────────────────
FROM python:3.12-slim

# Безопасность: не-root пользователь
RUN useradd --create-home appuser
WORKDIR /app

# Копируем виртуальное окружение из builder
COPY --from=builder /venv /venv
COPY --from=builder /app /app

# Права на папку
RUN chown -R appuser:appuser /app /venv

USER appuser

ENV PATH="/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

# Рекомендую gunicorn + uvicorn workers в проде (лучше стабильность и graceful reload)
CMD ["gunicorn", "main:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "4", \
     "--bind", "0.0.0.0:8000", \
     "--timeout", "120", \
     "--graceful-timeout", "30", \
     "--log-level", "info"]