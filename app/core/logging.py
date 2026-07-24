import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from app.core.config import settings


def configure_http_client_logging(log_level: int) -> None:
    """인증 정보가 포함될 수 있는 HTTP 요청 URL·헤더의 기본 로그를 차단합니다."""
    protected_level = max(log_level, logging.WARNING)
    for logger_name in ("httpx", "httpcore"):
        logging.getLogger(logger_name).setLevel(protected_level)


def configure_logging() -> None:
    project_root = Path(__file__).resolve().parents[2]
    log_dir = project_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "app.log"

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    rotating_handler = TimedRotatingFileHandler(
        filename=str(log_file),
        when="midnight",
        interval=1,
        backupCount=7,
        encoding="utf-8",
    )
    rotating_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    root_logger.addHandler(stream_handler)
    root_logger.addHandler(rotating_handler)
    configure_http_client_logging(log_level)

    # docker-compose-dev.yml의 api 서비스는 ".:/app" 볼륨 매핑을 사용하므로 logs/가 호스트에도 보존됩니다.
