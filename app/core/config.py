from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = BASE_DIR / ".env"


class Settings(BaseSettings):
    app_name: str = "trading-bot"
    log_level: str = "INFO"

    upbit_access_key: str | None = None
    upbit_secret_key: str | None = None
    upbit_base_url: str = "https://api.upbit.com"
    upbit_timeout: float = 10.0

    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    slack_webhook_url: str | None = None
    slack_timeout: float = 10.0
    slack_bot_token: str | None = None
    slack_app_token: str | None = None
    slack_signing_secret: str | None = None
    slack_allowed_user_ids: str | None = None
    slack_trade_channel_ids: str | None = None

    model_config = SettingsConfigDict(env_file=str(ENV_FILE), env_file_encoding="utf-8")


settings = Settings()
