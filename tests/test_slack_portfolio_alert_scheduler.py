# ruff: noqa: E402

from datetime import UTC, datetime
import sys
from types import SimpleNamespace

stub_scheduler = sys.modules.get("app.core.scheduler")
if stub_scheduler is not None and not hasattr(stub_scheduler, "_build_slack_portfolio_alert_job_specs"):
    del sys.modules["app.core.scheduler"]

from app.core.scheduler import _build_slack_portfolio_alert_blocks
from app.core.scheduler import _build_slack_portfolio_alert_job_specs
from app.core.scheduler import _build_market_impact_news_alert_section
from app.core.scheduler import _normalize_slack_portfolio_alert_settings
from app.core.scheduler import _rank_market_impact_news_candidates


def test_slack_alert_preset_daily_twice_registers_two_jobs() -> None:
    settings = {
        "enabled": True,
        "mode": "preset",
        "preset": "daily_twice",
        "rules": [],
    }

    normalized = _normalize_slack_portfolio_alert_settings(settings)
    specs = _build_slack_portfolio_alert_job_specs(normalized)

    assert normalized["rules"][0]["weekdays"] == ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    assert normalized["rules"][0]["times"] == ["08:30", "18:30"]
    assert [spec[0] for spec in specs] == [
        "slack_portfolio_alert:daily_twice:0",
        "slack_portfolio_alert:daily_twice:1",
    ]


def test_slack_alert_advanced_rules_register_each_time() -> None:
    settings = {
        "enabled": True,
        "mode": "advanced",
        "rules": [
            {
                "id": "weekday_ai_signal",
                "enabled": True,
                "weekdays": ["mon", "wed", "fri"],
                "times": ["08:30", "12:30"],
                "sections": ["favorite_ai_signals"],
                "signal_decisions": ["BUY"],
                "min_confidence": 80,
            },
            {
                "id": "weekly_summary",
                "enabled": True,
                "weekdays": ["sun"],
                "times": ["21:00"],
                "sections": ["portfolio", "fear_index"],
                "signal_decisions": ["BUY", "SELL"],
                "min_confidence": 70,
            },
        ],
    }

    specs = _build_slack_portfolio_alert_job_specs(settings)

    assert [spec[0] for spec in specs] == [
        "slack_portfolio_alert:weekday_ai_signal:0",
        "slack_portfolio_alert:weekday_ai_signal:1",
        "slack_portfolio_alert:weekly_summary:0",
    ]
    assert specs[0][2]["rule"]["sections"] == ["favorite_ai_signals"]
    assert specs[0][2]["rule"]["signal_decisions"] == ["BUY"]
    assert specs[0][2]["rule"]["min_confidence"] == 80


def test_slack_alert_invalid_rule_is_skipped_but_valid_rule_remains() -> None:
    settings = {
        "enabled": True,
        "mode": "advanced",
        "rules": [
            {
                "id": "invalid_time",
                "enabled": True,
                "weekdays": ["mon"],
                "times": ["25:99"],
                "sections": ["portfolio"],
            },
            {
                "id": "valid",
                "enabled": True,
                "weekdays": ["tue"],
                "times": ["09:15"],
                "sections": ["portfolio"],
            },
        ],
    }

    specs = _build_slack_portfolio_alert_job_specs(settings)

    assert [spec[0] for spec in specs] == ["slack_portfolio_alert:valid:0"]


def test_slack_alert_blocks_follow_rule_sections() -> None:
    rule = {
        "id": "signals_only",
        "enabled": True,
        "weekdays": ["mon"],
        "times": ["08:30"],
        "sections": ["favorite_ai_signals"],
        "signal_decisions": ["BUY", "SELL"],
        "min_confidence": 70,
    }
    portfolio = SimpleNamespace(total_net_worth=1_000_000, total_pnl=10_000, items=[], error=None)
    sentiment = SimpleNamespace(score=20, updated_at=datetime(2026, 6, 10, 0, 0, tzinfo=UTC))
    signals = [
        {
            "symbol": "KRW-BTC",
            "decision": "BUY",
            "confidence": 82,
            "recommended_weight": 20,
            "created_at": datetime(2026, 6, 10, 0, 0, tzinfo=UTC),
        }
    ]

    blocks = _build_slack_portfolio_alert_blocks(
        rule,
        portfolio=portfolio,
        sentiment=sentiment,
        signal_items=signals,
    )
    block_text = "\n".join(
        str(block.get("text", {}).get("text", ""))
        for block in blocks
        if isinstance(block.get("text"), dict)
    )

    assert "KRW-BTC" in block_text
    assert "총 평가금액" not in block_text
    assert "오늘 공포지수" not in block_text


def test_market_impact_news_excludes_fallback_candidates() -> None:
    now = datetime(2026, 6, 10, 0, 0, tzinfo=UTC)
    ranked = _rank_market_impact_news_candidates(
        [
            {
                "parent_id": "dummy",
                "title": "Bitcoin ETF approval",
                "content": "generated to keep the rag ingestion pipeline alive",
                "link": "dummy://cryptopanic/fallback",
                "published_at": now.isoformat(),
            },
            {
                "parent_id": "real",
                "title": "Bitcoin ETF approval expands market access",
                "content": "SEC approved a spot Bitcoin ETF filing.",
                "link": "https://example.com/real",
                "published_at": now.isoformat(),
            },
        ],
        reference_symbols=["KRW-BTC"],
        now=now,
    )

    assert [item["parent_id"] for item in ranked] == ["real"]


def test_market_impact_news_deduplicates_parent_chunks() -> None:
    now = datetime(2026, 6, 10, 0, 0, tzinfo=UTC)
    ranked = _rank_market_impact_news_candidates(
        [
            {
                "parent_id": "article-1",
                "title": "Bitcoin market update",
                "content": "General market recap.",
                "published_at": now.isoformat(),
            },
            {
                "parent_id": "article-1",
                "title": "Bitcoin ETF approval sparks institutional inflows",
                "content": "SEC approval and ETF inflows are mentioned.",
                "published_at": now.isoformat(),
            },
        ],
        reference_symbols=["KRW-BTC"],
        now=now,
    )

    assert len(ranked) == 1
    assert ranked[0]["title"] == "Bitcoin ETF approval sparks institutional inflows"
    assert "ETF" in ranked[0]["impact_keywords"]


def test_market_impact_news_keywords_rank_above_general_news() -> None:
    now = datetime(2026, 6, 10, 0, 0, tzinfo=UTC)
    ranked = _rank_market_impact_news_candidates(
        [
            {
                "parent_id": "general",
                "title": "Crypto market daily recap",
                "content": "Prices moved sideways during the session.",
                "published_at": now.isoformat(),
            },
            {
                "parent_id": "impact",
                "title": "SEC approval puts Bitcoin ETF back in focus",
                "content": "ETF approval can change institutional demand.",
                "published_at": now.isoformat(),
            },
        ],
        reference_symbols=[],
        now=now,
    )

    assert ranked[0]["parent_id"] == "impact"
    assert ranked[0]["impact_direction"] == "상방"


def test_market_impact_news_reference_symbol_boosts_related_news() -> None:
    now = datetime(2026, 6, 10, 0, 0, tzinfo=UTC)
    ranked = _rank_market_impact_news_candidates(
        [
            {
                "parent_id": "unrelated",
                "title": "Altcoin market update",
                "content": "The broader crypto market was mixed.",
                "published_at": now.isoformat(),
            },
            {
                "parent_id": "xrp",
                "title": "XRP liquidity improves after exchange listing",
                "content": "XRP order book depth improved after listing news.",
                "published_at": now.isoformat(),
            },
        ],
        reference_symbols=["KRW-XRP"],
        now=now,
    )

    assert ranked[0]["parent_id"] == "xrp"
    assert ranked[0]["related_symbols"] == ["KRW-XRP"]


def test_market_impact_news_empty_block_is_stable() -> None:
    block = _build_market_impact_news_alert_section([])
    text = block["text"]["text"]

    assert "가격 영향 뉴스 Top3" in text
    assert "후보 뉴스가 없습니다" in text
