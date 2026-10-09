import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.api.routes.ai import _is_probable_legacy_quote_amount_buy
from app.services.trading.ai_executor import _parse_bool_config
from app.services.trading.ai_executor import _resolve_order_price
from app.services.trading.ai_executor import _resolve_order_qty
from app.services.trading.ai_executor import _resolve_weighted_amount
from app.services.trading.ai_executor import _send_live_order_accepted_notification
from app.services.trading.ai_executor import _send_trade_notification
from app.services.trading.ai_analyst import is_fallback_news_item
from app.services.trading.entry_policy import AIConfidenceCalibration
from app.services.trading.entry_policy import DEFAULT_MIN_CALIBRATED_CONFIDENCE
from app.services.trading.entry_policy import DEFAULT_TRADE_EXCLUDED_SYMBOLS
from app.services.trading.entry_policy import DEFAULT_TRADE_TARGET_SYMBOLS
from app.services.trading.entry_policy import EntryGateConfig
from app.services.trading.entry_policy import filter_trade_symbols
from app.services.trading.entry_policy import score_entry_context
from app.services.trading.live_order_execution import LiveOrderResult


def test_quote_amount_bid_uses_trade_vwap_not_order_amount() -> None:
    order_result = {
        "side": "bid",
        "ord_type": "price",
        "price": "10000",
        "executed_volume": "0.0001",
        "trades": [
            {"price": "100000000", "volume": "0.00005", "funds": "5000"},
            {"price": "100500000", "volume": "0.00005", "funds": "5025"},
        ],
    }

    assert _resolve_order_price(order_result, 112_000_000, side="buy") == pytest.approx(
        100_250_000
    )
    assert _resolve_order_qty(order_result, 0) == pytest.approx(0.0001)


def test_quote_amount_bid_without_trade_ignores_requested_krw_price() -> None:
    order_result = {
        "side": "bid",
        "ord_type": "price",
        "price": "10000",
    }

    assert _resolve_order_price(order_result, 112_000_000, side="buy") == 112_000_000


def test_buy_weight_cap_uses_effective_weight() -> None:
    assert _resolve_weighted_amount(100_000, 40) == 40_000
    assert min(100, 40.0) == 40.0


def test_bool_config_defaults_to_live_buy_locked() -> None:
    assert _parse_bool_config("true", default=False) is True
    assert _parse_bool_config("false", default=True) is False
    assert _parse_bool_config(None, default=False) is False


def test_live_order_accepted_notification_describes_receipt_not_fill(monkeypatch) -> None:
    messages: list[str] = []

    monkeypatch.setattr(
        "app.services.trading.ai_executor.slack_bot.send_message",
        lambda text: messages.append(text),
    )

    asyncio.run(
        _send_live_order_accepted_notification(
            symbol="KRW-BTC",
            decision="BUY",
            confidence=82,
            recommended_weight=20,
            result=LiveOrderResult(
                intent_id=123,
                identifier="a" * 32,
                submission_status="ACCEPTED",
                exchange_uuid="order-123",
                exchange_state="wait",
                projection_status="PENDING",
                order_history_id=None,
                error_code=None,
                error_message=None,
            ),
        )
    )

    assert len(messages) == 1
    assert "KRW-BTC" in messages[0]
    assert "BUY" in messages[0]
    assert "order-123" in messages[0]
    assert "주문 접수" in messages[0]
    assert "체결" not in messages[0]


def test_paper_trade_notification_skips_slack_bot(monkeypatch) -> None:
    called = False

    def fake_send_message(_text: str) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(
        "app.services.trading.ai_executor.slack_bot.send_message",
        fake_send_message,
    )

    asyncio.run(
        _send_trade_notification(
            symbol="KRW-BTC",
            decision="BUY",
            confidence=82,
            recommended_weight=20,
            order_result={"uuid": "order-123"},
            trading_mode="paper",
        )
    )

    assert called is False


def test_legacy_quote_amount_buy_is_excluded_only_before_cutoff() -> None:
    legacy_order = SimpleNamespace(
        side="buy",
        ai_analysis_log_id=1,
        executed_at=datetime(2026, 4, 28, 1, 0, tzinfo=UTC),
        price=10000.0,
        qty=1.0,
    )
    fixed_order = SimpleNamespace(
        side="buy",
        ai_analysis_log_id=1,
        executed_at=datetime(2026, 4, 30, 8, 0, tzinfo=UTC),
        price=10000.0,
        qty=1.0,
    )

    assert _is_probable_legacy_quote_amount_buy(legacy_order) is True
    assert _is_probable_legacy_quote_amount_buy(fixed_order) is False


def test_default_trade_universe_excludes_doge() -> None:
    config = EntryGateConfig(
        target_symbols=DEFAULT_TRADE_TARGET_SYMBOLS,
        excluded_symbols=DEFAULT_TRADE_EXCLUDED_SYMBOLS,
        score_threshold=70,
        shadow_mode=True,
        min_success_rate_pct=45,
        max_concurrent_positions=2,
        min_calibrated_confidence=DEFAULT_MIN_CALIBRATED_CONFIDENCE,
    )

    assert filter_trade_symbols(["KRW-DOGE", "KRW-BTC", "KRW-XRP"], config) == [
        "KRW-BTC",
        "KRW-XRP",
    ]


def test_fallback_news_is_not_scored_as_positive_signal() -> None:
    assert is_fallback_news_item(
        {
            "title": "Bitcoin volatility check fallback feed",
            "content": "Fallback global market headline because the CryptoPanic request failed.",
            "source": "cryptopanic",
            "link": "dummy://cryptopanic/bitcoin-volatility-check",
        }
    )

    config = EntryGateConfig(
        target_symbols=DEFAULT_TRADE_TARGET_SYMBOLS,
        excluded_symbols=DEFAULT_TRADE_EXCLUDED_SYMBOLS,
        score_threshold=70,
        shadow_mode=True,
        min_success_rate_pct=45,
        max_concurrent_positions=2,
        min_calibrated_confidence=DEFAULT_MIN_CALIBRATED_CONFIDENCE,
    )
    calibration = AIConfidenceCalibration(
        checked_count=20,
        success_count=10,
        success_rate_pct=50.0,
        calibrated_confidence=90,
    )
    score = score_entry_context(
        {
            "technical": {
                "close": 110,
                "sma_20": 100,
                "ema_50": 105,
                "rsi_14": 55,
                "bb_upper_20_2": 120,
                "bb_lower_20_2": 90,
                "price_vs_sma20_pct": 10,
            },
            "sentiment": {"score": 45},
            "news": {
                "items": [
                    {
                        "title": "KRW market fallback headline",
                        "content": "Fallback local market headline because Naver credentials are unavailable.",
                        "source": "naver",
                        "link": "dummy://naver/krw-market-standby",
                    }
                ]
            },
        },
        calibration,
        config,
    )

    assert score.components["news"] == 0
    assert score.real_news_count == 0
    assert score.technical_ok is True
    assert score.sentiment_ok is True
