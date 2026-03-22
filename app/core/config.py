from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ai-trade-manager"
    log_level: str = "INFO"

    upbit_access_key: str | None = None
    upbit_secret_key: str | None = None
    upbit_base_url: str = "https://api.upbit.com"
    upbit_timeout: float = 10.0

    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    slack_webhook_url: str | None = None
    slack_timeout: float = 10.0
    SLACK_BOT_TOKEN: str = ""
    SLACK_APP_TOKEN: str = ""
    SLACK_ALLOWED_USER_ID: str = ""
    slack_bot_token: str | None = None
    slack_app_token: str | None = None
    slack_signing_secret: str | None = None
    slack_allowed_user_ids: str | None = None
    slack_trade_channel_ids: str | None = None
    OPENAI_API_KEY: str | None = None
    GEMINI_API_KEY: str | None = None
    cryptopanic_api_key: str | None = None
    naver_client_id: str | None = None
    naver_client_secret: str | None = None
    opensearch_url: str = "http://localhost:9200"

    postgres_user: str = "postgres"
    postgres_password: str = "postgres"
    postgres_db: str = "ai_trade_manager"
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
        env_file=(".env", ".env.prod", ".env.local"),
        env_file_encoding="utf-8",
    )


settings = Settings()
