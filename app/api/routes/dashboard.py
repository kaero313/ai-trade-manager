import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repository import get_portfolio_snapshots
from app.db.session import get_db
from app.schemas.portfolio import AssetItem, PortfolioSummary
from app.services.portfolio.aggregator import PortfolioService

router = APIRouter()
logger = logging.getLogger(__name__)

DASHBOARD_PORTFOLIO_TIMEOUT_SECONDS = 4.0
DASHBOARD_TIMEOUT_ERROR = "PORTFOLIO_FETCH_TIMEOUT"
DASHBOARD_FETCH_FAILED_ERROR = "PORTFOLIO_FETCH_FAILED"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _datetime_to_iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc).isoformat()
        return value.astimezone(timezone.utc).isoformat()
    return None


def _to_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _snapshot_asset_item(raw_item: Any) -> AssetItem:
    item = raw_item if isinstance(raw_item, dict) else {}
    currency = str(item.get("currency") or "").strip().upper()
    current_price = _to_float(item.get("current_price"))
    return AssetItem(
        broker=str(item.get("broker") or "SNAPSHOT"),
        currency=currency,
        balance=_to_float(item.get("balance")),
        locked=_to_float(item.get("locked")),
        avg_buy_price=_to_float(item.get("avg_buy_price")) or current_price or 1.0,
        current_price=current_price,
        total_value=_to_float(item.get("total_value")),
        pnl_percentage=_to_float(item.get("pnl_percentage")),
    )


async def _snapshot_fallback_dashboard(
    db: AsyncSession,
    *,
    error_code: str,
) -> PortfolioSummary:
    snapshots = await get_portfolio_snapshots(db, limit=1)
    if snapshots:
        latest_snapshot = snapshots[0]
        snapshot_items = [
            _snapshot_asset_item(item)
            for item in latest_snapshot.snapshot_data
            if isinstance(item, dict)
        ]
        return PortfolioSummary(
            total_net_worth=latest_snapshot.total_net_worth,
            total_pnl=latest_snapshot.total_pnl,
            items=snapshot_items,
            error=error_code,
            source="snapshot",
            is_stale=True,
            updated_at=_datetime_to_iso(latest_snapshot.created_at),
        )

    return PortfolioSummary(
        total_net_worth=0.0,
        total_pnl=0.0,
        items=[],
        error=error_code,
        source="empty",
        is_stale=True,
        updated_at=None,
    )


@router.get("/dashboard", response_model=PortfolioSummary)
async def get_dashboard_snapshot(db: AsyncSession = Depends(get_db)) -> PortfolioSummary:
    try:
        portfolio = await asyncio.wait_for(
            PortfolioService(db).get_aggregated_portfolio(),
            timeout=DASHBOARD_PORTFOLIO_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        logger.warning(
            "Dashboard portfolio aggregation timed out after %.1f seconds.",
            DASHBOARD_PORTFOLIO_TIMEOUT_SECONDS,
        )
        return await _snapshot_fallback_dashboard(db, error_code=DASHBOARD_TIMEOUT_ERROR)
    except Exception:
        logger.exception("Dashboard portfolio aggregation failed.")
        return await _snapshot_fallback_dashboard(db, error_code=DASHBOARD_FETCH_FAILED_ERROR)

    if portfolio.error is not None:
        return await _snapshot_fallback_dashboard(db, error_code=portfolio.error)

    return portfolio.model_copy(
        update={
            "source": "live",
            "is_stale": False,
            "updated_at": _utc_now_iso(),
        }
    )
