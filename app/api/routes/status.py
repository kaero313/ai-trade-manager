from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.schemas import BotStatus
from app.services.bot_service import get_bot_status

router = APIRouter()


@router.get("/status", response_model=BotStatus)
async def get_status(db: AsyncSession = Depends(get_db)) -> BotStatus:
    return await get_bot_status(db)


@router.post("/bot/start", response_model=BotStatus)
async def start_bot_endpoint(db: AsyncSession = Depends(get_db)) -> BotStatus:
    from app.services.bot_service import start_bot as svc_start
    await svc_start(db)
    return await get_bot_status(db)


@router.post("/bot/stop", response_model=BotStatus)
async def stop_bot_endpoint(db: AsyncSession = Depends(get_db)) -> BotStatus:
    from app.services.trading.engine import stop_bot
    await stop_bot(db)
    return await get_bot_status(db)


@router.post("/bot/liquidate")
async def liquidate_all_endpoint(db: AsyncSession = Depends(get_db)):
    """
    Emergency Liquidate: 
    1. Stops the trading bot.
    2. Sells all assets via the broker at market price.
    """
    await stop_bot(db)
    
    from app.services.brokers.factory import get_broker
    broker = await get_broker()
    accounts = await broker.get_accounts()
    
    for account in accounts:
        currency = str(account.get("currency") or "").upper()
        if not currency or currency == "KRW":
            continue

        balance = float(account.get("balance") or 0)
        locked = float(account.get("locked") or 0)
        available_qty = max(balance - locked, 0.0)
        
        if available_qty <= 0:
            continue

        market = f"KRW-{currency}"
        try:
            await broker.create_order(
                market=market,
                side="ask",
                ord_type="market",
                volume=str(available_qty)
            )
        except Exception as e:
            # Not raising HTTP error immediately to attempt liquidating as many assets as possible.
            print(f"Failed to liquidate {market}: {e}")
            
    return {"message": "Liquidate pipeline executed successfully."}
