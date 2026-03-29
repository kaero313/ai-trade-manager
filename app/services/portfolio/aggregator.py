import logging
from typing import Any

from jwt.exceptions import DecodeError
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.portfolio import AssetItem, PortfolioSummary
from app.services.brokers.factory import BrokerFactory
from app.services.brokers.upbit import UpbitAPIError

logger = logging.getLogger(__name__)

BUY_FEE_MULTIPLIER = 1.0005
SELL_FEE_MULTIPLIER = 0.9995
UPBIT_KEY_MISSING_ERROR = "UPBIT_KEY_MISSING"
UPBIT_API_ERROR_CODE = "UPBIT_API_ERROR"
PORTFOLIO_AGGREGATION_FAILED_ERROR = "PORTFOLIO_AGGREGATION_FAILED"


def _to_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _empty_portfolio(error: str | None = None) -> PortfolioSummary:
    return PortfolioSummary(
        total_net_worth=0.0,
        total_pnl=0.0,
        items=[],
        error=error,
    )


def _is_missing_upbit_key_error(exc: ValueError) -> bool:
    return "key not configured" in str(exc).lower()


class PortfolioService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_aggregated_portfolio(self) -> PortfolioSummary:
        try:
            broker = BrokerFactory.get_broker("UPBIT")
            accounts = await broker.get_accounts()

            all_markets = await broker.get_markets()
            valid_market_symbols = {
                str(m.get("market") or "").upper()
                for m in all_markets
                if isinstance(m, dict) and m.get("market")
            }

            markets: list[str] = []
            for account in accounts:
                currency = str(account.get("currency") or "").upper()
                if not currency or currency == "KRW":
                    continue
                market = f"KRW-{currency}"
                if market not in markets and market in valid_market_symbols:
                    markets.append(market)

            try:
                tickers = await broker.get_ticker(markets=markets) if markets else []
            except UpbitAPIError as exc:
                logger.warning("Failed to fetch tickers for valid markets. Defaulting to empty tickers: %s", exc)
                tickers = []
            ticker_map = {
                str(ticker.get("market") or "").upper(): _to_float(ticker.get("trade_price"))
                for ticker in tickers
                if isinstance(ticker, dict) and ticker.get("market")
            }

            items: list[AssetItem] = []
            total_net_worth = 0.0
            total_pnl = 0.0

            for account in accounts:
                currency = str(account.get("currency") or "").upper()
                if not currency:
                    continue

                balance = _to_float(account.get("balance"))
                locked = _to_float(account.get("locked"))
                qty = balance + locked
                raw_avg_buy_price = _to_float(account.get("avg_buy_price"))

                if currency == "KRW":
                    current_price = 1.0
                    avg_buy_price = 1.0
                    invested = qty
                    total_value = qty
                    pnl_amount = 0.0
                    pnl_percentage = 0.0
                else:
                    market = f"KRW-{currency}"
                    current_price = ticker_map.get(market, 0.0)
                    avg_buy_price = raw_avg_buy_price

                    invested = qty * avg_buy_price * BUY_FEE_MULTIPLIER
                    total_value = qty * current_price * SELL_FEE_MULTIPLIER
                    pnl_amount = total_value - invested

                    try:
                        pnl_percentage = (pnl_amount / invested) * 100.0 if invested > 0 else 0.0
                    except ZeroDivisionError:
                        pnl_percentage = 0.0

                items.append(
                    AssetItem(
                        broker="UPBIT",
                        currency=currency,
                        balance=balance,
                        locked=locked,
                        avg_buy_price=avg_buy_price,
                        current_price=current_price,
                        total_value=total_value,
                        pnl_percentage=pnl_percentage,
                    )
                )

                total_net_worth += total_value
                total_pnl += pnl_amount

            return PortfolioSummary(
                total_net_worth=total_net_worth,
                total_pnl=total_pnl,
                items=items,
                error=None,
            )
        except ValueError as exc:
            if _is_missing_upbit_key_error(exc):
                logger.warning(
                    "Portfolio aggregation bypassed because Upbit API keys are missing: %s",
                    exc,
                )
                return _empty_portfolio(error=UPBIT_KEY_MISSING_ERROR)

            logger.error(
                "Portfolio aggregation failed due to unexpected value error: %s",
                exc,
                exc_info=True,
            )
            return _empty_portfolio(error=PORTFOLIO_AGGREGATION_FAILED_ERROR)
        except DecodeError as exc:
            logger.error("Portfolio aggregation failed due to JWT decode error: %s", exc, exc_info=True)
            return _empty_portfolio(error=UPBIT_API_ERROR_CODE)
        except UpbitAPIError as exc:
            logger.error("Portfolio aggregation failed due to Upbit API error: %s", exc, exc_info=True)
            return _empty_portfolio(error=UPBIT_API_ERROR_CODE)
        except Exception as exc:
            logger.error("Portfolio aggregation failed due to unexpected error: %s", exc, exc_info=True)
            return _empty_portfolio(error=PORTFOLIO_AGGREGATION_FAILED_ERROR)
