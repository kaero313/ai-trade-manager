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
    slack_bot_token: str | None = None
    slack_app_token: str | None = None
    slack_signing_secret: str | None = None
    slack_allowed_user_ids: str | None = None
    slack_trade_channel_ids: str | None = None

    postgres_user: str = "postgres"
    postgres_password: str = "postgres"
    postgres_db: str = "trading_bot"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    @property
    def async_database_url(self) -> str:
        return (
            "postgresql+asyncpg://"
            f"{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    model_config = SettingsConfigDict(
        env_file=(".env.prod", ".env.local"),
        env_file_encoding="utf-8",
    )


settings = Settings()
