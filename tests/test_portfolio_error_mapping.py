import asyncio

from app.services.brokers.upbit import UpbitAPIError
from app.services.portfolio import aggregator
from app.services.portfolio.aggregator import UPBIT_API_ERROR_CODE
from app.services.portfolio.aggregator import UPBIT_AUTH_ERROR_CODE
from app.services.portfolio.aggregator import UPBIT_AUTH_IP_NOT_ALLOWED_ERROR
from app.services.portfolio.aggregator import _resolve_upbit_portfolio_error
from app.services.portfolio.aggregator import PORTFOLIO_AGGREGATION_FAILED_ERROR, PortfolioService


def test_resolve_upbit_portfolio_error_maps_ip_authorization_failure() -> None:
    exc = UpbitAPIError(
        status_code=401,
        detail={"error": {"name": "no_authorization_ip", "message": "This is not a verified IP."}},
        error_name="no_authorization_ip",
        message="This is not a verified IP.",
    )

    assert _resolve_upbit_portfolio_error(exc) == UPBIT_AUTH_IP_NOT_ALLOWED_ERROR


def test_resolve_upbit_portfolio_error_maps_generic_auth_failure() -> None:
    exc = UpbitAPIError(status_code=401, detail={}, error_name="invalid_access_key")

    assert _resolve_upbit_portfolio_error(exc) == UPBIT_AUTH_ERROR_CODE


def test_resolve_upbit_portfolio_error_keeps_non_auth_api_failure() -> None:
    exc = UpbitAPIError(status_code=500, detail={})

    assert _resolve_upbit_portfolio_error(exc) == UPBIT_API_ERROR_CODE


def test_unavailable_trading_mode_never_calls_upbit_private_api(monkeypatch) -> None:
    async def unavailable_mode(_db):
        raise RuntimeError("TRADING_MODE_MIRROR_MISMATCH")

    def private_api_must_not_be_created(_name):
        raise AssertionError("Upbit private API를 호출하면 안 됩니다.")

    monkeypatch.setattr(aggregator, "get_trading_mode", unavailable_mode)
    monkeypatch.setattr(
        aggregator.BrokerFactory,
        "get_broker",
        private_api_must_not_be_created,
    )

    result = asyncio.run(PortfolioService(object()).get_aggregated_portfolio())

    assert result.error == PORTFOLIO_AGGREGATION_FAILED_ERROR
    assert result.items == []
