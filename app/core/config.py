from pathlib import Path
from urllib.parse import urlsplit

from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILES = tuple(str(PROJECT_ROOT / name) for name in (".env", ".env.prod", ".env.local"))
DEFAULT_CORS_ALLOWED_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"


def parse_cors_allowed_origins(value: str | None) -> list[str]:
    origins: list[str] = []
    for raw_origin in str(value or "").split(","):
        origin = raw_origin.strip()
        if not origin:
            continue
        if origin == "*":
            raise ValueError("CORS_ALLOWED_ORIGINS에는 wildcard를 사용할 수 없습니다.")

        parsed = urlsplit(origin)
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(f"허용되지 않는 CORS origin 형식입니다: {origin}")
        try:
            parsed.port
        except ValueError as exc:
            raise ValueError(f"허용되지 않는 CORS origin port입니다: {origin}") from exc

        normalized = f"{parsed.scheme.lower()}://{parsed.netloc.rstrip('/')}"
        if normalized not in origins:
            origins.append(normalized)
    return origins


class Settings(BaseSettings):
    app_name: str = "ai-trade-manager"
    log_level: str = "INFO"
    cors_allowed_origins: str = DEFAULT_CORS_ALLOWED_ORIGINS

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
    admin_api_token: str | None = None
    admin_reauth_signing_secret: str | None = None
    rate_limit_subject_secret: str | None = None
    admin_basic_auth_user: str | None = None
    admin_basic_auth_hash: str | None = None

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

    @property
    def cors_origins(self) -> list[str]:
        return parse_cors_allowed_origins(self.cors_allowed_origins)

    model_config = SettingsConfigDict(env_file=ENV_FILES, env_file_encoding="utf-8")


settings = Settings()
