"""공용 테스트 격리.

- Settings를 .env·.env.prod·.env.local 없이 다시 만들어 실계정 값이 테스트에 섞이지 않게 한다.
- 비밀값 환경변수를 지운다. TEST_DATABASE_URL은 유지한다.
- 루프백과 TEST_DATABASE_URL의 host:port 외 이름 해석·소켓 연결을 차단한다.
  Upbit·LLM 실호출이 테스트에 섞이면 여기서 즉시 실패한다.
  (Windows Proactor 루프는 socket.connect를 거치지 않으므로 호스트명 해석 단계에서 막는다.
   숫자 IP 직접 접속은 Windows에서 걸리지 않을 수 있다. Linux CI에서는 둘 다 걸린다.)
- test_database_url 픽스처: DSN이 없으면 skip.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlsplit

import pytest

SECRET_ENV_VARS = (
    "UPBIT_ACCESS_KEY", "UPBIT_SECRET_KEY",
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_ALLOWED_USER_ID",
    "SLACK_WEBHOOK_URL", "SLACK_BOT_TOKEN", "SLACK_APP_TOKEN",
    "SLACK_ALLOWED_USER_ID", "SLACK_ALLOWED_USER_IDS", "SLACK_TRADE_CHANNEL_IDS",
    "OPENAI_API_KEY", "GEMINI_API_KEY", "CRYPTOPANIC_API_KEY",
    "NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET",
    "ADMIN_API_TOKEN", "ADMIN_REAUTH_SIGNING_SECRET", "RATE_LIMIT_SUBJECT_SECRET",
    "ADMIN_BASIC_AUTH_USER", "ADMIN_BASIC_AUTH_HASH",
)
for _name in SECRET_ENV_VARS:
    os.environ.pop(_name, None)
    os.environ.pop(_name.lower(), None)

from app.core import config as _config  # noqa: E402  환경 정리 뒤에 import해야 한다

_config.settings = _config.Settings(_env_file=None)


def _allowed_targets() -> set[tuple[str, int]]:
    url = os.getenv("TEST_DATABASE_URL", "").strip()
    if not url:
        return set()
    parts = urlsplit(url)
    if not parts.hostname:
        return set()
    port = parts.port or 5432
    targets = {(parts.hostname, port)}
    try:
        for info in socket.getaddrinfo(parts.hostname, port, type=socket.SOCK_STREAM):
            targets.add((str(info[4][0]), port))
    except socket.gaierror:
        pass
    return targets


def _is_loopback(host: str) -> bool:
    if host in {"localhost", "::1", ""}:
        return True
    try:
        return ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


_ALLOWED = _allowed_targets()
_ALLOWED_HOSTS = {host for host, _ in _ALLOWED}
_ORIGINAL_CONNECT = socket.socket.connect
_ORIGINAL_CONNECT_EX = socket.socket.connect_ex
_ORIGINAL_GETADDRINFO = socket.getaddrinfo


def _reject(host: str, port: object) -> None:
    raise RuntimeError(
        f"테스트에서 외부 네트워크 접속을 차단했습니다: {host}:{port}. "
        "대역(fake·MockTransport·monkeypatch)을 쓰세요."
    )


def _check_address(address: object) -> None:
    if not isinstance(address, tuple) or len(address) < 2:
        return
    host, port = str(address[0]), int(address[1])
    if not (_is_loopback(host) or (host, port) in _ALLOWED):
        _reject(host, port)


def _guarded_connect(self, address):  # noqa: ANN001
    _check_address(address)
    return _ORIGINAL_CONNECT(self, address)


def _guarded_connect_ex(self, address):  # noqa: ANN001
    _check_address(address)
    return _ORIGINAL_CONNECT_EX(self, address)


def _guarded_getaddrinfo(host, port, *args, **kwargs):  # noqa: ANN001
    name = "" if host is None else str(host)
    if not (_is_loopback(name) or name in _ALLOWED_HOSTS):
        _reject(name, port)
    return _ORIGINAL_GETADDRINFO(host, port, *args, **kwargs)


def pytest_configure(config: pytest.Config) -> None:
    leaked = [n for n in ("upbit_access_key", "upbit_secret_key", "OPENAI_API_KEY", "GEMINI_API_KEY")
              if getattr(_config.settings, n)]
    if leaked:
        raise pytest.UsageError(f"테스트 Settings에 실계정 값이 남아 있습니다: {', '.join(leaked)}")
    socket.socket.connect = _guarded_connect
    socket.socket.connect_ex = _guarded_connect_ex
    socket.getaddrinfo = _guarded_getaddrinfo


def pytest_unconfigure(config: pytest.Config) -> None:
    socket.socket.connect = _ORIGINAL_CONNECT
    socket.socket.connect_ex = _ORIGINAL_CONNECT_EX
    socket.getaddrinfo = _ORIGINAL_GETADDRINFO


@pytest.fixture
def test_database_url() -> str:
    url = os.getenv("TEST_DATABASE_URL", "").strip()
    if not url:
        pytest.skip("TEST_DATABASE_URL이 없어 PostgreSQL 테스트를 건너뜁니다.")
    if not url.startswith(("postgresql://", "postgresql+")):
        pytest.fail("TEST_DATABASE_URL은 PostgreSQL 테스트 DB를 가리켜야 합니다.")
    return url
