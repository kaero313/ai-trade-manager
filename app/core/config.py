from pydantic_settings import BaseSettings, SettingsConfigDict


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

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
