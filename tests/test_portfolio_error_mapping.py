from app.services.brokers.upbit import UpbitAPIError
from app.services.portfolio.aggregator import UPBIT_API_ERROR_CODE
from app.services.portfolio.aggregator import UPBIT_AUTH_ERROR_CODE
from app.services.portfolio.aggregator import UPBIT_AUTH_IP_NOT_ALLOWED_ERROR
from app.services.portfolio.aggregator import _resolve_upbit_portfolio_error


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
