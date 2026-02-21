import logging
from typing import Any

from jwt.exceptions import DecodeError
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.portfolio import AssetItem, PortfolioSummary
from app.services.brokers.factory import BrokerFactory
from app.services.brokers.upbit import UpbitAPIError

logger = logging.getLogger(__name__)


def _to_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _empty_portfolio() -> PortfolioSummary:
    return PortfolioSummary(
        total_net_worth=0.0,
        total_pnl=0.0,
        items=[],
    )


class PortfolioService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_aggregated_portfolio(self) -> PortfolioSummary:
        try:
            broker = BrokerFactory.get_broker("UPBIT")
            accounts = await broker.get_accounts()

            markets: list[str] = []
            for account in accounts:
                currency = str(account.get("currency") or "").upper()
                if not currency or currency == "KRW":
                    continue
                market = f"KRW-{currency}"
                if market not in markets:
                    markets.append(market)

            tickers = await broker.get_ticker(markets=markets) if markets else []
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
                    avg_buy_price = raw_avg_buy_price if raw_avg_buy_price > 0 else 1.0
                else:
                    market = f"KRW-{currency}"
                    current_price = ticker_map.get(market, 0.0)
                    avg_buy_price = raw_avg_buy_price

                invested = qty * avg_buy_price
                total_value = qty * current_price
                pnl_amount = total_value - invested

                try:
                    pnl_percentage = (
                        ((current_price - avg_buy_price) / avg_buy_price) * 100.0
                        if avg_buy_price > 0
                        else 0.0
                    )
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
            )
        except DecodeError as exc:
            logger.error("Portfolio aggregation failed due to JWT decode error: %s", exc, exc_info=True)
            return _empty_portfolio()
        except UpbitAPIError as exc:
            logger.error("Portfolio aggregation failed due to Upbit API error: %s", exc, exc_info=True)
            return _empty_portfolio()
        except Exception as exc:
            logger.error("Portfolio aggregation failed due to unexpected error: %s", exc, exc_info=True)
            return _empty_portfolio()
