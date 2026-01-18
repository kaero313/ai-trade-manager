from fastapi import APIRouter, HTTPException, Query

from app.core.config import settings
from app.services.upbit_client import upbit_client

router = APIRouter()


def _require_keys() -> None:
    if not settings.upbit_access_key or not settings.upbit_secret_key:
        raise HTTPException(
            status_code=400,
            detail="Upbit keys not configured. Set UPBIT_ACCESS_KEY/UPBIT_SECRET_KEY in .env",
        )


def _parse_csv(value: str | None) -> list[str] | None:
    if not value:
        return None
    items = [item.strip() for item in value.split(",") if item.strip()]
    return items or None


@router.get("/upbit/accounts")
async def get_accounts() -> list[dict]:
    _require_keys()
    return await upbit_client.get_accounts()


@router.get("/upbit/order")
async def get_order(
    uuid: str | None = None,
    identifier: str | None = None,
) -> dict:
    _require_keys()
    return await upbit_client.get_order(uuid_=uuid, identifier=identifier)


@router.get("/upbit/orders/open")
async def get_orders_open(
    market: str | None = None,
    states: str | None = Query(None, description="Comma-separated states"),
    page: int | None = None,
    limit: int | None = None,
    order_by: str | None = None,
) -> list[dict]:
    _require_keys()
    return await upbit_client.get_orders_open(
        market=market,
        states=_parse_csv(states),
        page=page,
        limit=limit,
        order_by=order_by,
    )


@router.get("/upbit/orders/closed")
async def get_orders_closed(
    market: str | None = None,
    states: str | None = Query(None, description="Comma-separated states"),
    page: int | None = None,
    limit: int | None = None,
    order_by: str | None = None,
) -> list[dict]:
    _require_keys()
    return await upbit_client.get_orders_closed(
        market=market,
        states=_parse_csv(states),
        page=page,
        limit=limit,
        order_by=order_by,
    )


@router.get("/upbit/orders/uuids")
async def get_orders_by_uuids(
    uuids: str = Query(..., description="Comma-separated UUIDs"),
    states: str | None = Query(None, description="Comma-separated states"),
    order_by: str | None = None,
) -> list[dict]:
    _require_keys()
    parsed_uuids = _parse_csv(uuids)
    if not parsed_uuids:
        raise HTTPException(status_code=400, detail="uuids is required")
    return await upbit_client.get_orders_by_uuids(
        uuids=parsed_uuids,
        states=_parse_csv(states),
        order_by=order_by,
    )
