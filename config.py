from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # LINE Messaging API
    line_channel_secret: str
    line_channel_access_token: str

    # Google Gemini API
    gemini_api_key: str
    gemini_model: str = "gemini-1.5-flash"

    # データストア
    store_type: Literal["redis", "sqlite"] = "sqlite"
    redis_url: str = "redis://localhost:6379/0"

    # アプリ設定
    max_history_turns: int = 20
    history_ttl_seconds: int = 86400
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
