from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    telegram_bot_token: str
    telegram_channel_id: str
    anthropic_api_key: str
    anthropic_model: str = "claude-sonnet-4-6"
    max_tokens: int = 600
    temperature: float = 0.2

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")
