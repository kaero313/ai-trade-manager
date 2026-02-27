import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.schemas import BotStatus
from app.services.bot_service import get_bot_status, start_bot, stop_bot
from app.services.brokers.factory import BrokerFactory

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/status", response_model=BotStatus)
async def get_status(db: AsyncSession = Depends(get_db)) -> BotStatus:
    return await get_bot_status(db)


@router.post("/bot/start", response_model=BotStatus)
async def start_bot_endpoint(db: AsyncSession = Depends(get_db)) -> BotStatus:
    await start_bot(db)
    return await get_bot_status(db)


@router.post("/bot/stop", response_model=BotStatus)
async def stop_bot_endpoint(db: AsyncSession = Depends(get_db)) -> BotStatus:
    await stop_bot(db)
    return await get_bot_status(db)


@router.post("/bot/liquidate")
async def liquidate_all_endpoint(db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    await stop_bot(db)

    broker = BrokerFactory.get_broker("UPBIT")
    accounts = await broker.get_accounts()

    for account in accounts:
        currency = str(account.get("currency") or "").upper()
        if not currency or currency == "KRW":
            continue

        try:
            balance = float(account.get("balance") or 0)
            locked = float(account.get("locked") or 0)
        except (TypeError, ValueError):
            logger.warning("잔고 파싱 실패로 스킵합니다: account=%s", account)
            continue

        available_qty = max(balance - locked, 0.0)
        if available_qty <= 0:
            continue

        market = f"KRW-{currency}"
        try:
            await broker.create_order(
                market=market,
                side="ask",
                ord_type="market",
                volume=str(available_qty),
            )
        except Exception:
            logger.exception("전량 매도 실패: market=%s", market)

    return {"message": "Liquidate pipeline executed successfully."}
