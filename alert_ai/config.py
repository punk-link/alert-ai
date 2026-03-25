from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    telegram_bot_token: str
    telegram_channel_id: str
    anthropic_api_key: str
    anthropic_model: str = "claude-sonnet-4-6"
    max_tokens: int = 600
    temperature: float = 0.2
    dedup_ttl_seconds: int = 600
    anthropic_rate_limit_per_minute: int = 10
    alert_queue_max_size: int = 100

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")
