import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

from app.api.routes import dashboard as dashboard_route
from app.schemas.portfolio import AssetItem, PortfolioSummary


class _LivePortfolioService:
    def __init__(self, _db) -> None:
        pass

    async def get_aggregated_portfolio(self) -> PortfolioSummary:
        return PortfolioSummary(
            total_net_worth=100_000,
            total_pnl=5_000,
            items=[
                AssetItem(
                    broker="UPBIT",
                    currency="KRW",
                    balance=100_000,
                    locked=0,
                    avg_buy_price=1,
                    current_price=1,
                    total_value=100_000,
                    pnl_percentage=0,
                )
            ],
            error=None,
        )


def _snapshot() -> SimpleNamespace:
    return SimpleNamespace(
        total_net_worth=80_000,
        total_pnl=-2_000,
        snapshot_data=[
            {
                "currency": "KRW",
                "balance": 80_000,
                "current_price": 1,
                "total_value": 80_000,
                "pnl_percentage": 0,
            }
        ],
        created_at=datetime(2026, 4, 30, 1, 2, 3, tzinfo=UTC),
    )


def test_dashboard_returns_live_portfolio_metadata(monkeypatch) -> None:
    monkeypatch.setattr(dashboard_route, "PortfolioService", _LivePortfolioService)

    result = asyncio.run(dashboard_route.get_dashboard_snapshot(object()))

    assert result.source == "live"
    assert result.is_stale is False
    assert result.updated_at is not None
    assert result.total_net_worth == 100_000


def test_dashboard_uses_snapshot_when_live_portfolio_times_out(monkeypatch) -> None:
    class SlowPortfolioService:
        def __init__(self, _db) -> None:
            pass

        async def get_aggregated_portfolio(self) -> PortfolioSummary:
            await asyncio.sleep(1)
            return PortfolioSummary(total_net_worth=1, total_pnl=0, items=[])

    async def fake_get_portfolio_snapshots(_db, limit: int = 168):
        assert limit == 1
        return [_snapshot()]

    monkeypatch.setattr(dashboard_route, "PortfolioService", SlowPortfolioService)
    monkeypatch.setattr(dashboard_route, "get_portfolio_snapshots", fake_get_portfolio_snapshots)
    monkeypatch.setattr(dashboard_route, "DASHBOARD_PORTFOLIO_TIMEOUT_SECONDS", 0.01)

    result = asyncio.run(dashboard_route.get_dashboard_snapshot(object()))

    assert result.source == "snapshot"
    assert result.is_stale is True
    assert result.error == dashboard_route.DASHBOARD_TIMEOUT_ERROR
    assert result.total_net_worth == 80_000
    assert result.updated_at == "2026-04-30T01:02:03+00:00"


def test_dashboard_uses_snapshot_when_live_portfolio_has_error(monkeypatch) -> None:
    class ErrorPortfolioService:
        def __init__(self, _db) -> None:
            pass

        async def get_aggregated_portfolio(self) -> PortfolioSummary:
            return PortfolioSummary(
                total_net_worth=0,
                total_pnl=0,
                items=[],
                error="UPBIT_API_ERROR",
            )

    async def fake_get_portfolio_snapshots(_db, limit: int = 168):
        return [_snapshot()]

    monkeypatch.setattr(dashboard_route, "PortfolioService", ErrorPortfolioService)
    monkeypatch.setattr(dashboard_route, "get_portfolio_snapshots", fake_get_portfolio_snapshots)

    result = asyncio.run(dashboard_route.get_dashboard_snapshot(object()))

    assert result.source == "snapshot"
    assert result.is_stale is True
    assert result.error == "UPBIT_API_ERROR"
    assert result.total_pnl == -2_000


def test_dashboard_returns_empty_when_no_snapshot_exists(monkeypatch) -> None:
    class BrokenPortfolioService:
        def __init__(self, _db) -> None:
            pass

        async def get_aggregated_portfolio(self) -> PortfolioSummary:
            raise RuntimeError("upstream unavailable")

    async def fake_get_portfolio_snapshots(_db, limit: int = 168):
        return []

    monkeypatch.setattr(dashboard_route, "PortfolioService", BrokenPortfolioService)
    monkeypatch.setattr(dashboard_route, "get_portfolio_snapshots", fake_get_portfolio_snapshots)

    result = asyncio.run(dashboard_route.get_dashboard_snapshot(object()))

    assert result.source == "empty"
    assert result.is_stale is True
    assert result.error == dashboard_route.DASHBOARD_FETCH_FAILED_ERROR
    assert result.items == []
