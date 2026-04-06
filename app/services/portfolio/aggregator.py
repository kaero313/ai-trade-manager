import logging
from typing import Any

from jwt.exceptions import DecodeError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import Asset
from app.models.domain import Position
from app.schemas.portfolio import AssetItem, PortfolioSummary
from app.services.brokers.factory import BrokerFactory
from app.services.brokers.upbit import UpbitAPIError
from app.services.trading.paper import get_trading_mode
from app.services.trading.paper import load_paper_cash_balance

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
            trading_mode = await get_trading_mode(self.db)
        except Exception as exc:
            logger.error("Portfolio trading_mode 조회 실패: %s", exc, exc_info=True)
            return _empty_portfolio(error=PORTFOLIO_AGGREGATION_FAILED_ERROR)

        if trading_mode == "paper":
            return await self._get_paper_portfolio()

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

    async def _get_paper_portfolio(self) -> PortfolioSummary:
        try:
            broker = BrokerFactory.get_broker("UPBIT")
            paper_cash_balance = await load_paper_cash_balance(self.db)
            result = await self.db.execute(
                select(Position, Asset)
                .join(Asset, Position.asset_id == Asset.id)
                .where(
                    Position.is_paper.is_(True),
                    Position.status == "open",
                    Position.quantity > 0,
                )
                .order_by(Position.id.asc())
            )
            position_rows = result.all()

            markets = [
                asset.symbol
                for _, asset in position_rows
                if isinstance(asset.symbol, str) and asset.symbol.strip()
            ]
            try:
                tickers = await broker.get_ticker(markets=markets) if markets else []
            except UpbitAPIError as exc:
                logger.warning("Paper 포트폴리오 현재가 조회 실패. 빈 ticker로 대체합니다: %s", exc)
                tickers = []

            ticker_map = {
                str(ticker.get("market") or "").upper(): _to_float(ticker.get("trade_price"))
                for ticker in tickers
                if isinstance(ticker, dict) and ticker.get("market")
            }

            items: list[AssetItem] = [
                AssetItem(
                    broker="PAPER",
                    currency="KRW",
                    balance=paper_cash_balance,
                    locked=0.0,
                    avg_buy_price=1.0,
                    current_price=1.0,
                    total_value=paper_cash_balance,
                    pnl_percentage=0.0,
                )
            ]
            total_net_worth = paper_cash_balance
            total_pnl = 0.0

            for position, asset in position_rows:
                qty = max(_to_float(position.quantity), 0.0)
                if qty <= 0:
                    continue

                market = str(asset.symbol or "").upper()
                current_price = ticker_map.get(market, 0.0)
                avg_buy_price = max(_to_float(position.avg_entry_price), 0.0)
                invested = qty * avg_buy_price * BUY_FEE_MULTIPLIER
                total_value = qty * current_price * SELL_FEE_MULTIPLIER
                pnl_amount = total_value - invested

                try:
                    pnl_percentage = (pnl_amount / invested) * 100.0 if invested > 0 else 0.0
                except ZeroDivisionError:
                    pnl_percentage = 0.0

                items.append(
                    AssetItem(
                        broker="PAPER",
                        currency=_extract_target_currency(market),
                        balance=qty,
                        locked=0.0,
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
        except UpbitAPIError as exc:
            logger.error("Paper 포트폴리오 집계 실패(UpbitAPIError): %s", exc, exc_info=True)
            return _empty_portfolio(error=UPBIT_API_ERROR_CODE)
        except Exception as exc:
            logger.error("Paper 포트폴리오 집계 실패: %s", exc, exc_info=True)
            return _empty_portfolio(error=PORTFOLIO_AGGREGATION_FAILED_ERROR)


def _extract_target_currency(symbol: str) -> str:
    normalized_symbol = str(symbol or "").strip().upper()
    if "-" not in normalized_symbol:
        return normalized_symbol
    return normalized_symbol.split("-", 1)[1]
