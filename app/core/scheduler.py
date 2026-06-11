import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.base import BaseTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import desc, select

from app.api.routes.ai import analyze_portfolio
from app.api.routes.news import get_news_sentiment
from app.db.repository import AI_BRIEFING_TIME_KEY
from app.db.repository import AUTONOMOUS_AI_INTERVAL_HOURS_KEY
from app.db.repository import AUTONOMOUS_AI_INTERVAL_MINUTES_KEY
from app.db.repository import DEFAULT_SLACK_PORTFOLIO_ALERT_SETTINGS_VALUE
from app.db.repository import NEWS_INTERVAL_HOURS_KEY
from app.db.repository import SENTIMENT_INTERVAL_MINUTES_KEY
from app.db.repository import SLACK_PORTFOLIO_ALERT_SETTINGS_KEY
from app.db.repository import get_system_config_value
from app.db.repository import save_portfolio_snapshot
from app.db.session import AsyncSessionLocal
from app.models.domain import AIAnalysisLog
from app.models.domain import Favorite
from app.services.market.sentiment_fetcher import refresh_market_sentiment_cache
from app.services.portfolio.aggregator import PortfolioService
from app.services.rag.ingestion import run_market_news_ingestion_job
from app.services.rag.opensearch_client import INDEX_NAME
from app.services.rag.opensearch_client import get_opensearch_client
from app.services.ai.providers.gemini import AIProviderRateLimitError
from app.services.bot_service import update_bot_runtime_status
from app.services.trading.accuracy_worker import update_ai_analysis_accuracy
from app.services.trading.ai_analyst import execute_ai_analysis
from app.services.trading.ai_executor import execute_hard_tp_sl_check
from app.services.trading.ai_executor import execute_ai_trade
from app.services.trading.entry_policy import filter_trade_symbols
from app.services.trading.entry_policy import load_entry_gate_config

logger = logging.getLogger(__name__)

SCHEDULER_TIMEZONE = "Asia/Seoul"
SCHEDULER_ZONEINFO = ZoneInfo(SCHEDULER_TIMEZONE)
DAILY_BRIEFING_JOB_ID = "daily_ai_briefing"
MARKET_NEWS_INGESTION_JOB_ID = "market_news_ingestion_hourly"
MARKET_SENTIMENT_REFRESH_JOB_ID = "market_sentiment_refresh"
AUTONOMOUS_AI_ANALYST_JOB_ID = "autonomous_ai_analyst_watchlist"
AI_ACCURACY_CHECK_JOB_ID = "ai_accuracy_check"
PORTFOLIO_SNAPSHOT_JOB_ID = "portfolio_snapshot_hourly"
SLACK_PORTFOLIO_ALERT_JOB_PREFIX = "slack_portfolio_alert"
DEFAULT_PROVIDER = "auto"

DEFAULT_NEWS_INTERVAL_HOURS = 4
DEFAULT_SENTIMENT_INTERVAL_MINUTES = 5
DEFAULT_AI_BRIEFING_HOUR = 8
DEFAULT_AI_BRIEFING_MINUTE = 30
DEFAULT_AUTONOMOUS_AI_INTERVAL_HOURS = 1
DEFAULT_AUTONOMOUS_AI_INTERVAL_MINUTES = DEFAULT_AUTONOMOUS_AI_INTERVAL_HOURS * 60
AUTONOMOUS_AI_ANALYST_SYMBOL_DELAY_SECONDS = 2
SLACK_ALERT_WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
SLACK_ALERT_SECTIONS = ("portfolio", "fear_index", "favorite_ai_signals", "market_impact_news")
SLACK_ALERT_SIGNAL_DECISIONS = ("BUY", "SELL", "HOLD")
SLACK_ALERT_DEFAULT_SECTIONS = [
    "portfolio",
    "fear_index",
    "favorite_ai_signals",
    "market_impact_news",
]
SLACK_ALERT_DEFAULT_DECISIONS = ["BUY", "SELL"]
MARKET_IMPACT_NEWS_LIMIT = 3
MARKET_IMPACT_NEWS_CANDIDATE_LIMIT = 40
MARKET_IMPACT_RECENT_HOURS = 48
MARKET_IMPACT_KEYWORDS: tuple[dict[str, Any], ...] = (
    {"label": "ETF", "terms": ("etf", "현물 etf"), "direction": "상방", "weight": 18},
    {"label": "승인", "terms": ("approval", "approved", "승인", "인가"), "direction": "상방", "weight": 15},
    {"label": "SEC", "terms": ("sec", "증권거래위원회"), "direction": "혼재", "weight": 12},
    {"label": "Fed", "terms": ("fed", "fomc", "연준", "파월"), "direction": "혼재", "weight": 12},
    {"label": "CPI", "terms": ("cpi", "물가", "인플레이션"), "direction": "혼재", "weight": 10},
    {"label": "금리", "terms": ("rate cut", "rate hike", "금리", "인하", "인상"), "direction": "혼재", "weight": 10},
    {"label": "규제", "terms": ("regulation", "regulatory", "규제", "단속"), "direction": "하방", "weight": 12},
    {"label": "상장", "terms": ("listing", "listed", "상장"), "direction": "상방", "weight": 10},
    {"label": "해킹", "terms": ("hack", "exploit", "breach", "해킹", "탈취"), "direction": "하방", "weight": 16},
    {"label": "소송", "terms": ("lawsuit", "sue", "court", "소송", "기소"), "direction": "하방", "weight": 12},
    {"label": "청산", "terms": ("liquidation", "liquidated", "청산"), "direction": "하방", "weight": 10},
    {"label": "업그레이드", "terms": ("upgrade", "hard fork", "업그레이드"), "direction": "상방", "weight": 8},
    {"label": "Whale", "terms": ("whale", "고래", "대량 이체"), "direction": "혼재", "weight": 8},
)
MARKET_IMPACT_SYMBOL_ALIASES: dict[str, tuple[str, ...]] = {
    "BTC": ("BTC", "Bitcoin", "비트코인"),
    "ETH": ("ETH", "Ethereum", "이더리움"),
    "XRP": ("XRP", "Ripple", "리플"),
    "SOL": ("SOL", "Solana", "솔라나"),
    "DOGE": ("DOGE", "Dogecoin", "도지"),
    "ADA": ("ADA", "Cardano", "카르다노"),
}
SLACK_ALERT_PRESET_WEEKDAYS: dict[str, list[str]] = {
    "daily_once": list(SLACK_ALERT_WEEKDAYS),
    "daily_twice": list(SLACK_ALERT_WEEKDAYS),
    "weekday_once": ["mon", "tue", "wed", "thu", "fri"],
    "weekday_twice": ["mon", "tue", "wed", "thu", "fri"],
    "weekend_once": ["sat", "sun"],
    "weekly_once": ["mon"],
    "mon_wed_fri": ["mon", "wed", "fri"],
    "tue_thu": ["tue", "thu"],
}
SLACK_ALERT_PRESET_TIMES: dict[str, list[str]] = {
    "daily_once": ["08:30"],
    "daily_twice": ["08:30", "18:30"],
    "weekday_once": ["08:30"],
    "weekday_twice": ["08:30", "18:30"],
    "weekend_once": ["10:00"],
    "weekly_once": ["09:00"],
    "mon_wed_fri": ["08:30"],
    "tue_thu": ["08:30"],
}

scheduler = AsyncIOScheduler(timezone=SCHEDULER_TIMEZONE)
_scheduler_loop: asyncio.AbstractEventLoop | None = None


@dataclass(slots=True)
class SchedulerRuntimeConfig:
    news_interval_hours: int = DEFAULT_NEWS_INTERVAL_HOURS
    sentiment_interval_minutes: int = DEFAULT_SENTIMENT_INTERVAL_MINUTES
    ai_briefing_hour: int = DEFAULT_AI_BRIEFING_HOUR
    ai_briefing_minute: int = DEFAULT_AI_BRIEFING_MINUTE
    autonomous_ai_interval_minutes: int = DEFAULT_AUTONOMOUS_AI_INTERVAL_MINUTES
    slack_portfolio_alert_settings: dict[str, Any] | None = None


def _parse_interval_hours(
    raw_value: str | None,
    default: int = DEFAULT_NEWS_INTERVAL_HOURS,
) -> int:
    try:
        value = int(str(raw_value).strip())
    except (TypeError, ValueError, AttributeError):
        return default

    if value <= 0 or value >= 24:
        return default
    return value


def _parse_interval_minutes(raw_value: str | None) -> int:
    try:
        value = int(str(raw_value).strip())
    except (TypeError, ValueError, AttributeError):
        return DEFAULT_SENTIMENT_INTERVAL_MINUTES

    if value <= 0 or value >= 60:
        return DEFAULT_SENTIMENT_INTERVAL_MINUTES
    return value


def _parse_autonomous_ai_interval_minutes(raw_value: str | None) -> int | None:
    try:
        value = int(str(raw_value).strip())
    except (TypeError, ValueError, AttributeError):
        return None

    if value <= 0:
        return None
    return value


def _parse_ai_briefing_time(raw_value: str | None) -> tuple[int, int]:
    if not raw_value:
        return DEFAULT_AI_BRIEFING_HOUR, DEFAULT_AI_BRIEFING_MINUTE

    try:
        hour_text, minute_text = str(raw_value).strip().split(":", maxsplit=1)
        hour = int(hour_text)
        minute = int(minute_text)
    except (ValueError, AttributeError):
        return DEFAULT_AI_BRIEFING_HOUR, DEFAULT_AI_BRIEFING_MINUTE

    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return DEFAULT_AI_BRIEFING_HOUR, DEFAULT_AI_BRIEFING_MINUTE
    return hour, minute


def _parse_slack_alert_time(raw_value: Any) -> str | None:
    if not isinstance(raw_value, str):
        return None

    try:
        hour_text, minute_text = raw_value.strip().split(":", maxsplit=1)
        hour = int(hour_text)
        minute = int(minute_text)
    except (ValueError, AttributeError):
        return None

    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return f"{hour:02d}:{minute:02d}"


def _parse_slack_alert_time_parts(raw_value: Any) -> tuple[int, int] | None:
    normalized = _parse_slack_alert_time(raw_value)
    if normalized is None:
        return None
    hour_text, minute_text = normalized.split(":", maxsplit=1)
    return int(hour_text), int(minute_text)


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if value not in deduped:
            deduped.append(value)
    return deduped


def _normalize_slack_alert_weekdays(raw_value: Any) -> list[str]:
    if not isinstance(raw_value, list):
        return []
    values = [
        str(item).strip().lower()
        for item in raw_value
        if str(item).strip().lower() in SLACK_ALERT_WEEKDAYS
    ]
    return _dedupe_preserve_order(values)


def _normalize_slack_alert_times(raw_value: Any) -> list[str]:
    if not isinstance(raw_value, list):
        return []
    values = [
        normalized
        for item in raw_value
        if (normalized := _parse_slack_alert_time(item)) is not None
    ]
    return _dedupe_preserve_order(values)


def _normalize_slack_alert_sections(raw_value: Any) -> list[str]:
    if not isinstance(raw_value, list):
        return list(SLACK_ALERT_DEFAULT_SECTIONS)
    values = [
        str(item).strip()
        for item in raw_value
        if str(item).strip() in SLACK_ALERT_SECTIONS
    ]
    return _dedupe_preserve_order(values) or list(SLACK_ALERT_DEFAULT_SECTIONS)


def _normalize_slack_alert_decisions(raw_value: Any) -> list[str]:
    if not isinstance(raw_value, list):
        return list(SLACK_ALERT_DEFAULT_DECISIONS)
    values = [
        str(item).strip().upper()
        for item in raw_value
        if str(item).strip().upper() in SLACK_ALERT_SIGNAL_DECISIONS
    ]
    return _dedupe_preserve_order(values) or list(SLACK_ALERT_DEFAULT_DECISIONS)


def _normalize_slack_alert_min_confidence(raw_value: Any) -> int:
    try:
        value = int(float(raw_value))
    except (TypeError, ValueError):
        return 70
    return max(0, min(100, value))


def _sanitize_slack_alert_rule_id(raw_value: Any, fallback: str) -> str:
    raw_text = str(raw_value or "").strip().lower()
    sanitized = "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in raw_text)
    return sanitized.strip("_") or fallback


def _normalize_slack_portfolio_alert_rule(
    raw_rule: Any,
    fallback_id: str,
) -> dict[str, Any] | None:
    if not isinstance(raw_rule, dict):
        return None

    weekdays = _normalize_slack_alert_weekdays(raw_rule.get("weekdays"))
    times = _normalize_slack_alert_times(raw_rule.get("times"))
    if not weekdays or not times:
        logger.warning(
            "Slack 포트폴리오 알림 규칙 스킵: rule_id=%s weekdays=%s times=%s",
            raw_rule.get("id"),
            weekdays,
            times,
        )
        return None

    return {
        "id": _sanitize_slack_alert_rule_id(raw_rule.get("id"), fallback_id),
        "enabled": bool(raw_rule.get("enabled", True)),
        "weekdays": weekdays,
        "times": times,
        "sections": _normalize_slack_alert_sections(raw_rule.get("sections")),
        "signal_decisions": _normalize_slack_alert_decisions(raw_rule.get("signal_decisions")),
        "min_confidence": _normalize_slack_alert_min_confidence(raw_rule.get("min_confidence")),
    }


def _build_slack_alert_preset_rules(preset: str) -> list[dict[str, Any]]:
    resolved_preset = preset if preset in SLACK_ALERT_PRESET_WEEKDAYS else "daily_once"
    return [
        {
            "id": resolved_preset,
            "enabled": True,
            "weekdays": SLACK_ALERT_PRESET_WEEKDAYS[resolved_preset],
            "times": SLACK_ALERT_PRESET_TIMES[resolved_preset],
            "sections": list(SLACK_ALERT_DEFAULT_SECTIONS),
            "signal_decisions": list(SLACK_ALERT_DEFAULT_DECISIONS),
            "min_confidence": 70,
        }
    ]


def _normalize_slack_portfolio_alert_settings(raw_value: Any) -> dict[str, Any]:
    if isinstance(raw_value, str):
        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError:
            parsed = json.loads(DEFAULT_SLACK_PORTFOLIO_ALERT_SETTINGS_VALUE)
    elif isinstance(raw_value, dict):
        parsed = raw_value
    else:
        parsed = json.loads(DEFAULT_SLACK_PORTFOLIO_ALERT_SETTINGS_VALUE)

    mode = str(parsed.get("mode") or "preset").strip().lower()
    if mode not in {"preset", "advanced"}:
        mode = "preset"
    preset = str(parsed.get("preset") or "daily_once").strip()
    if preset not in SLACK_ALERT_PRESET_WEEKDAYS:
        preset = "daily_once"

    raw_rules = parsed.get("rules")
    if mode == "preset" and not raw_rules:
        raw_rules = _build_slack_alert_preset_rules(preset)

    normalized_rules: list[dict[str, Any]] = []
    if isinstance(raw_rules, list):
        for index, raw_rule in enumerate(raw_rules):
            normalized_rule = _normalize_slack_portfolio_alert_rule(
                raw_rule,
                fallback_id=f"rule_{index + 1}",
            )
            if normalized_rule is not None:
                normalized_rules.append(normalized_rule)

    if mode == "preset" and not normalized_rules:
        normalized_rules = _build_slack_alert_preset_rules(preset)

    return {
        "enabled": bool(parsed.get("enabled", False)),
        "mode": mode,
        "preset": preset,
        "rules": normalized_rules,
    }


async def load_scheduler_runtime_config() -> SchedulerRuntimeConfig:
    async with AsyncSessionLocal() as db:
        news_interval_hours = _parse_interval_hours(
            await get_system_config_value(db, NEWS_INTERVAL_HOURS_KEY)
        )
        sentiment_interval_minutes = _parse_interval_minutes(
            await get_system_config_value(db, SENTIMENT_INTERVAL_MINUTES_KEY)
        )
        ai_briefing_hour, ai_briefing_minute = _parse_ai_briefing_time(
            await get_system_config_value(db, AI_BRIEFING_TIME_KEY)
        )
        autonomous_ai_interval_minutes = _parse_autonomous_ai_interval_minutes(
            await get_system_config_value(db, AUTONOMOUS_AI_INTERVAL_MINUTES_KEY)
        )
        if autonomous_ai_interval_minutes is None:
            autonomous_ai_interval_hours = _parse_interval_hours(
                await get_system_config_value(db, AUTONOMOUS_AI_INTERVAL_HOURS_KEY),
                default=DEFAULT_AUTONOMOUS_AI_INTERVAL_HOURS,
            )
            autonomous_ai_interval_minutes = autonomous_ai_interval_hours * 60
        slack_portfolio_alert_settings = _normalize_slack_portfolio_alert_settings(
            await get_system_config_value(
                db,
                SLACK_PORTFOLIO_ALERT_SETTINGS_KEY,
                DEFAULT_SLACK_PORTFOLIO_ALERT_SETTINGS_VALUE,
            )
        )

    return SchedulerRuntimeConfig(
        news_interval_hours=news_interval_hours,
        sentiment_interval_minutes=sentiment_interval_minutes,
        ai_briefing_hour=ai_briefing_hour,
        ai_briefing_minute=ai_briefing_minute,
        autonomous_ai_interval_minutes=autonomous_ai_interval_minutes,
        slack_portfolio_alert_settings=slack_portfolio_alert_settings,
    )


def _build_daily_briefing_trigger(runtime_config: SchedulerRuntimeConfig) -> CronTrigger:
    return CronTrigger(
        hour=runtime_config.ai_briefing_hour,
        minute=runtime_config.ai_briefing_minute,
        timezone=SCHEDULER_TIMEZONE,
    )


def _build_market_news_trigger(runtime_config: SchedulerRuntimeConfig) -> CronTrigger:
    return CronTrigger(
        hour=f"*/{runtime_config.news_interval_hours}",
        minute=0,
        timezone=SCHEDULER_TIMEZONE,
    )


def _build_market_sentiment_trigger(runtime_config: SchedulerRuntimeConfig) -> CronTrigger:
    return CronTrigger(
        minute=f"*/{runtime_config.sentiment_interval_minutes}",
        timezone=SCHEDULER_TIMEZONE,
    )


def _build_autonomous_ai_analyst_trigger(runtime_config: SchedulerRuntimeConfig) -> IntervalTrigger:
    return IntervalTrigger(
        minutes=runtime_config.autonomous_ai_interval_minutes,
        timezone=SCHEDULER_TIMEZONE,
    )


def _build_ai_accuracy_check_trigger() -> CronTrigger:
    return CronTrigger(
        minute="*/30",
        timezone=SCHEDULER_TIMEZONE,
    )


def _build_portfolio_snapshot_trigger() -> CronTrigger:
    return CronTrigger(
        minute=0,
        timezone=SCHEDULER_TIMEZONE,
    )


def _upsert_scheduler_job(
    job_id: str,
    func,
    trigger: BaseTrigger,
    kwargs: dict[str, Any] | None = None,
) -> None:
    existing_job = scheduler.get_job(job_id)
    if existing_job is None:
        scheduler.add_job(
            func,
            trigger=trigger,
            kwargs=kwargs,
            id=job_id,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=1800,
        )
        logger.info("Scheduler job added: job_id=%s trigger=%s", job_id, trigger)
        return

    scheduler.reschedule_job(job_id, trigger=trigger)
    logger.info("Scheduler job rescheduled: job_id=%s trigger=%s", job_id, trigger)


def register_daily_jobs(runtime_config: SchedulerRuntimeConfig) -> None:
    _upsert_scheduler_job(
        DAILY_BRIEFING_JOB_ID,
        daily_ai_briefing,
        _build_daily_briefing_trigger(runtime_config),
        kwargs={"force_refresh_news": False, "provider": DEFAULT_PROVIDER},
    )


def register_market_news_jobs(runtime_config: SchedulerRuntimeConfig) -> None:
    _upsert_scheduler_job(
        MARKET_NEWS_INGESTION_JOB_ID,
        run_market_news_ingestion_job,
        _build_market_news_trigger(runtime_config),
    )


def register_market_sentiment_jobs(runtime_config: SchedulerRuntimeConfig) -> None:
    _upsert_scheduler_job(
        MARKET_SENTIMENT_REFRESH_JOB_ID,
        refresh_market_sentiment_cache_job,
        _build_market_sentiment_trigger(runtime_config),
    )


def register_autonomous_ai_analyst_jobs(runtime_config: SchedulerRuntimeConfig) -> None:
    _upsert_scheduler_job(
        AUTONOMOUS_AI_ANALYST_JOB_ID,
        autonomous_ai_analyst_job,
        _build_autonomous_ai_analyst_trigger(runtime_config),
    )


def register_ai_accuracy_jobs(runtime_config: SchedulerRuntimeConfig) -> None:
    _upsert_scheduler_job(
        AI_ACCURACY_CHECK_JOB_ID,
        ai_accuracy_check_job,
        _build_ai_accuracy_check_trigger(),
    )


def register_portfolio_snapshot_jobs() -> None:
    _upsert_scheduler_job(
        PORTFOLIO_SNAPSHOT_JOB_ID,
        save_portfolio_snapshot_job,
        _build_portfolio_snapshot_trigger(),
    )


def _build_slack_portfolio_alert_job_specs(
    settings: dict[str, Any] | None,
) -> list[tuple[str, CronTrigger, dict[str, Any]]]:
    normalized = _normalize_slack_portfolio_alert_settings(
        settings or DEFAULT_SLACK_PORTFOLIO_ALERT_SETTINGS_VALUE
    )
    if not normalized["enabled"]:
        return []

    specs: list[tuple[str, CronTrigger, dict[str, Any]]] = []
    for rule in normalized["rules"]:
        if not rule.get("enabled", True):
            continue
        weekdays = _normalize_slack_alert_weekdays(rule.get("weekdays"))
        times = _normalize_slack_alert_times(rule.get("times"))
        if not weekdays or not times:
            logger.warning(
                "Slack 포트폴리오 알림 job 등록 스킵: rule_id=%s weekdays=%s times=%s",
                rule.get("id"),
                weekdays,
                times,
            )
            continue

        for time_index, time_value in enumerate(times):
            time_parts = _parse_slack_alert_time_parts(time_value)
            if time_parts is None:
                logger.warning(
                    "Slack 포트폴리오 알림 job 등록 스킵: rule_id=%s time=%s",
                    rule.get("id"),
                    time_value,
                )
                continue
            hour, minute = time_parts
            job_id = f"{SLACK_PORTFOLIO_ALERT_JOB_PREFIX}:{rule['id']}:{time_index}"
            specs.append(
                (
                    job_id,
                    CronTrigger(
                        day_of_week=",".join(weekdays),
                        hour=hour,
                        minute=minute,
                        timezone=SCHEDULER_TIMEZONE,
                    ),
                    {"rule": {**rule, "times": [time_value]}},
                )
            )
    return specs


def _remove_slack_portfolio_alert_jobs() -> None:
    for job in scheduler.get_jobs():
        if job.id.startswith(f"{SLACK_PORTFOLIO_ALERT_JOB_PREFIX}:"):
            scheduler.remove_job(job.id)
            logger.info("Scheduler job removed: job_id=%s", job.id)


def register_slack_portfolio_alert_jobs(runtime_config: SchedulerRuntimeConfig) -> None:
    _remove_slack_portfolio_alert_jobs()
    specs = _build_slack_portfolio_alert_job_specs(runtime_config.slack_portfolio_alert_settings)
    for job_id, trigger, kwargs in specs:
        _upsert_scheduler_job(
            job_id,
            slack_portfolio_alert_job,
            trigger,
            kwargs=kwargs,
        )


async def reload_scheduler_jobs() -> SchedulerRuntimeConfig:
    runtime_config = await load_scheduler_runtime_config()
    register_daily_jobs(runtime_config)
    register_market_news_jobs(runtime_config)
    register_market_sentiment_jobs(runtime_config)
    register_autonomous_ai_analyst_jobs(runtime_config)
    register_ai_accuracy_jobs(runtime_config)
    register_portfolio_snapshot_jobs()
    register_slack_portfolio_alert_jobs(runtime_config)
    logger.info(
        "Scheduler jobs reloaded: news_interval_hours=%s sentiment_interval_minutes=%s ai_briefing_time=%02d:%02d autonomous_ai_interval_minutes=%s slack_portfolio_alert_jobs=%s",
        runtime_config.news_interval_hours,
        runtime_config.sentiment_interval_minutes,
        runtime_config.ai_briefing_hour,
        runtime_config.ai_briefing_minute,
        runtime_config.autonomous_ai_interval_minutes,
        len(_build_slack_portfolio_alert_job_specs(runtime_config.slack_portfolio_alert_settings)),
    )
    return runtime_config


async def start_scheduler() -> None:
    global _scheduler_loop
    if scheduler.running:
        return

    _scheduler_loop = asyncio.get_running_loop()
    await reload_scheduler_jobs()
    scheduler.start()
    logger.info("APScheduler started: timezone=%s", SCHEDULER_TIMEZONE)


def stop_scheduler() -> None:
    global _scheduler_loop
    if not scheduler.running:
        _scheduler_loop = None
        return

    scheduler.shutdown(wait=False)
    _scheduler_loop = None
    logger.info("APScheduler 종료")


def trigger_daily_ai_briefing_now() -> None:
    if _scheduler_loop is None or _scheduler_loop.is_closed():
        logger.warning("daily_ai_briefing 수동 실행을 위한 이벤트 루프를 찾을 수 없습니다.")
        return

    def _schedule_manual_job() -> None:
        asyncio.create_task(_run_manual_daily_ai_briefing_job())

    _scheduler_loop.call_soon_threadsafe(_schedule_manual_job)


async def _run_manual_daily_ai_briefing_job() -> None:
    try:
        await daily_ai_briefing(force_refresh_news=True, provider=DEFAULT_PROVIDER)
    except Exception:
        logger.error(
            "daily_ai_briefing 수동 실행이 실패했습니다. 서버는 계속 실행합니다.",
            exc_info=True,
        )


async def refresh_market_sentiment_cache_job() -> None:
    try:
        async with AsyncSessionLocal() as db:
            await refresh_market_sentiment_cache(db)
    except Exception:
        logger.error(
            "시장 심리 갱신 스케줄 작업이 실패했습니다. 서버는 계속 실행합니다.",
            exc_info=True,
        )


async def ai_accuracy_check_job() -> None:
    try:
        async with AsyncSessionLocal() as db:
            updated_count = await update_ai_analysis_accuracy(db)
        logger.info("AI 분석 정확도 체크 완료: updated_count=%s", updated_count)
    except Exception:
        logger.error(
            "AI 분석 정확도 체크 작업이 실패했습니다. 서버는 계속 실행합니다.",
            exc_info=True,
        )


async def save_portfolio_snapshot_job() -> None:
    try:
        async with AsyncSessionLocal() as db:
            portfolio = await PortfolioService(db).get_aggregated_portfolio()
            if portfolio.error is not None:
                logger.warning(
                    "포트폴리오 스냅샷 저장 스킵: portfolio_error=%s",
                    portfolio.error,
                )
                return

            snapshot_data = [
                {
                    "currency": item.currency,
                    "balance": item.balance,
                    "current_price": item.current_price,
                    "total_value": item.total_value,
                    "pnl_percentage": item.pnl_percentage,
                }
                for item in portfolio.items
            ]

            await save_portfolio_snapshot(
                db,
                total_net_worth=portfolio.total_net_worth,
                total_pnl=portfolio.total_pnl,
                snapshot_data=snapshot_data,
            )

        logger.info(
            "포트폴리오 스냅샷 저장 완료: item_count=%s total_net_worth=%s",
            len(snapshot_data),
            portfolio.total_net_worth,
        )
    except Exception:
        logger.error(
            "포트폴리오 스냅샷 저장 잡 실행 중 오류가 발생했습니다. 스케줄러는 계속 실행됩니다.",
            exc_info=True,
        )


async def autonomous_ai_analyst_job() -> None:
    try:
        liquidated_symbols: set[str] = set()
        async with AsyncSessionLocal() as db:
            try:
                liquidated_symbols = await execute_hard_tp_sl_check(db)
                if liquidated_symbols:
                    logger.info(
                        "하드 TP/SL 선제 청산 완료: liquidated_symbols=%s",
                        sorted(liquidated_symbols),
                    )
            except Exception:
                logger.error(
                    "하드 TP/SL 선제 청산 작업이 실패했습니다. 기존 AI 분석 루프는 계속 진행합니다.",
                    exc_info=True,
                )

            result = await db.execute(
                select(Favorite.symbol).order_by(desc(Favorite.created_at), desc(Favorite.id))
            )
            symbols = [
                str(symbol).strip().upper()
                for symbol in result.scalars().all()
                if str(symbol).strip()
            ]
            entry_gate_config = await load_entry_gate_config(db)
            symbols = filter_trade_symbols(symbols, entry_gate_config)
            if liquidated_symbols:
                symbols = [
                    symbol
                    for symbol in symbols
                    if symbol not in liquidated_symbols
                ]

        if not symbols:
            logger.info("Watchlist 자율주행 AI 분석 대상이 없습니다.")
            return

        logger.info("Watchlist 자율주행 AI 분석 시작: symbol_count=%s", len(symbols))

        for index, symbol in enumerate(symbols):
            async with AsyncSessionLocal() as db:
                try:
                    await execute_ai_analysis(db, symbol)
                    logger.info("Watchlist 자율주행 AI 분석 완료: symbol=%s", symbol)
                except AIProviderRateLimitError as exc:
                    logger.warning(
                        "Watchlist 자율주행 AI 분석 조기 중단: symbol=%s reason=%s",
                        symbol,
                        exc,
                    )
                    await update_bot_runtime_status(
                        db,
                        latest_action="Gemini 분석 제한으로 AI 루프 조기 중단",
                        last_error=str(exc),
                    )
                    break
                except Exception:
                    logger.error(
                        "Watchlist 자율주행 AI 분석 실패: symbol=%s",
                        symbol,
                        exc_info=True,
                    )
                    if index < len(symbols) - 1:
                        await asyncio.sleep(AUTONOMOUS_AI_ANALYST_SYMBOL_DELAY_SECONDS)
                    continue

                try:
                    await execute_ai_trade(db, symbol)
                    logger.info("Watchlist 자율주행 AI 집행 완료: symbol=%s", symbol)
                except Exception:
                    logger.error(
                        "Watchlist 자율주행 AI 집행 실패: symbol=%s",
                        symbol,
                        exc_info=True,
                    )

            if index < len(symbols) - 1:
                await asyncio.sleep(AUTONOMOUS_AI_ANALYST_SYMBOL_DELAY_SECONDS)
    except Exception:
        logger.error(
            "Watchlist 자율주행 AI 분석 작업이 실패했습니다. 서버는 계속 실행합니다.",
            exc_info=True,
        )


def _format_krw(value: Any) -> str:
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        amount = 0.0
    return f"₩{amount:,.0f}"


def _format_signed_krw(value: Any) -> str:
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        amount = 0.0
    sign = "+" if amount >= 0 else "-"
    return f"{sign}₩{abs(amount):,.0f}"


def _format_percentage(value: Any) -> str:
    try:
        percentage = float(value or 0)
    except (TypeError, ValueError):
        percentage = 0.0
    return f"{percentage:+.2f}%"


def _format_local_datetime(value: datetime | None = None) -> str:
    resolved = value or datetime.now(timezone.utc)
    if resolved.tzinfo is None:
        resolved = resolved.replace(tzinfo=timezone.utc)
    return resolved.astimezone(SCHEDULER_ZONEINFO).strftime("%Y-%m-%d %H:%M:%S")


def _truncate_alert_text(text: Any, max_len: int = 120) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= max_len:
        return normalized
    return f"{normalized[: max_len - 1]}…"


def _parse_datetime_value(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _is_fallback_market_news_candidate(item: dict[str, Any]) -> bool:
    link = str(item.get("link") or "").strip().lower()
    content = str(item.get("content") or item.get("summary") or "").strip().lower()
    return (
        link.startswith("dummy://")
        or "credentials are unavailable" in content
        or "request failed" in content
        or "generated to keep the rag ingestion pipeline alive" in content
    )


def _normalize_market_news_hit(hit: dict[str, Any]) -> dict[str, Any]:
    source = hit.get("_source")
    if not isinstance(source, dict):
        source = hit
    title = str(source.get("title") or "").strip()
    content = str(source.get("content") or source.get("summary") or title).strip()
    return {
        "title": title or "제목 없음",
        "content": content,
        "summary": str(source.get("summary") or content or title).strip(),
        "source": str(source.get("source") or "").strip() or "-",
        "published_at": source.get("published_at"),
        "link": str(source.get("link") or "").strip() or None,
        "parent_id": str(source.get("parent_id") or source.get("link") or title).strip(),
        "search_score": float(hit.get("_score") or source.get("search_score") or 0),
    }


def _symbol_aliases(symbol: str) -> tuple[str, ...]:
    normalized = str(symbol or "").strip().upper()
    currency = normalized.split("-", maxsplit=1)[-1] if "-" in normalized else normalized
    aliases = {normalized, currency}
    aliases.update(MARKET_IMPACT_SYMBOL_ALIASES.get(currency, ()))
    return tuple(alias for alias in aliases if alias)


def _extract_impact_keywords(text: str) -> tuple[list[str], str, int]:
    normalized_text = text.lower()
    labels: list[str] = []
    directions: set[str] = set()
    score = 0
    for keyword in MARKET_IMPACT_KEYWORDS:
        terms = keyword["terms"]
        if any(str(term).lower() in normalized_text for term in terms):
            labels.append(str(keyword["label"]))
            direction = str(keyword["direction"])
            if direction in {"상방", "하방"}:
                directions.add(direction)
            score += int(keyword["weight"])

    if "상방" in directions and "하방" in directions:
        direction_label = "혼재"
    elif "상방" in directions:
        direction_label = "상방"
    elif "하방" in directions:
        direction_label = "하방"
    elif labels:
        direction_label = "혼재"
    else:
        direction_label = "불명"
    return _dedupe_preserve_order(labels), direction_label, score


def _recency_impact_score(published_at: Any, now: datetime) -> int:
    parsed = _parse_datetime_value(published_at)
    if parsed is None:
        return 0
    age = now - parsed.astimezone(timezone.utc)
    if age <= timedelta(hours=6):
        return 20
    if age <= timedelta(hours=24):
        return 14
    if age <= timedelta(hours=48):
        return 9
    if age <= timedelta(days=7):
        return 4
    return 0


def _related_symbols_for_news(text: str, reference_symbols: list[str]) -> list[str]:
    normalized_text = text.lower()
    related: list[str] = []
    for symbol in reference_symbols:
        if any(alias.lower() in normalized_text for alias in _symbol_aliases(symbol)):
            related.append(symbol)
    return _dedupe_preserve_order(related)


def _score_market_impact_news_item(
    item: dict[str, Any],
    *,
    reference_symbols: list[str],
    now: datetime,
) -> dict[str, Any] | None:
    if _is_fallback_market_news_candidate(item):
        return None

    text = f"{item.get('title') or ''}\n{item.get('content') or item.get('summary') or ''}"
    keywords, direction, keyword_score = _extract_impact_keywords(text)
    related_symbols = _related_symbols_for_news(text, reference_symbols)
    recency_score = _recency_impact_score(item.get("published_at"), now)
    content_length = len(str(item.get("content") or item.get("summary") or ""))
    content_quality_score = min(content_length // 250, 8)
    related_score = 18 if related_symbols else 0
    search_score = min(float(item.get("search_score") or 0), 10.0)
    impact_score = keyword_score + recency_score + content_quality_score + related_score + search_score
    scored = dict(item)
    scored.update(
        {
            "impact_score": round(float(impact_score), 4),
            "impact_keywords": keywords,
            "impact_direction": direction,
            "related_symbols": related_symbols,
        }
    )
    return scored


def _parent_key_for_market_news(item: dict[str, Any]) -> str:
    return str(item.get("parent_id") or item.get("link") or item.get("title") or "").strip()


def _rank_market_impact_news_candidates(
    candidates: list[dict[str, Any]],
    *,
    reference_symbols: list[str] | None = None,
    limit: int = MARKET_IMPACT_NEWS_LIMIT,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    normalized_symbols = _dedupe_preserve_order(
        [str(symbol).strip().upper() for symbol in (reference_symbols or []) if str(symbol).strip()]
    )
    best_by_parent: dict[str, dict[str, Any]] = {}

    for candidate in candidates:
        scored = _score_market_impact_news_item(
            candidate,
            reference_symbols=normalized_symbols,
            now=now_utc,
        )
        if scored is None:
            continue
        parent_key = _parent_key_for_market_news(scored)
        if not parent_key:
            continue
        current = best_by_parent.get(parent_key)
        if current is None or (
            scored["impact_score"],
            _parse_datetime_value(scored.get("published_at")) or datetime.min.replace(tzinfo=timezone.utc),
        ) > (
            current["impact_score"],
            _parse_datetime_value(current.get("published_at")) or datetime.min.replace(tzinfo=timezone.utc),
        ):
            best_by_parent[parent_key] = scored

    ranked = sorted(
        best_by_parent.values(),
        key=lambda item: (
            item["impact_score"],
            _parse_datetime_value(item.get("published_at")) or datetime.min.replace(tzinfo=timezone.utc),
        ),
        reverse=True,
    )
    return ranked[:limit]


async def _load_favorite_ai_signals(
    db,
    decisions: list[str],
    min_confidence: int,
    limit: int = 8,
) -> list[dict[str, Any]]:
    favorite_result = await db.execute(
        select(Favorite.symbol).order_by(desc(Favorite.created_at), desc(Favorite.id))
    )
    symbols = [
        str(symbol).strip().upper()
        for symbol in favorite_result.scalars().all()
        if str(symbol).strip()
    ]
    if not symbols:
        return []

    allowed_decisions = {decision.upper() for decision in decisions}
    signal_items: list[dict[str, Any]] = []
    for symbol in symbols:
        analysis_result = await db.execute(
            select(AIAnalysisLog)
            .where(AIAnalysisLog.symbol == symbol)
            .order_by(desc(AIAnalysisLog.created_at), desc(AIAnalysisLog.id))
            .limit(1)
        )
        analysis = analysis_result.scalar_one_or_none()
        if analysis is None:
            continue

        decision = str(analysis.decision or "").upper()
        if decision not in allowed_decisions:
            continue
        if int(analysis.confidence or 0) < min_confidence:
            continue

        signal_items.append(
            {
                "symbol": symbol,
                "decision": decision,
                "confidence": int(analysis.confidence or 0),
                "recommended_weight": int(analysis.recommended_weight or 0),
                "created_at": analysis.created_at,
            }
        )
        if len(signal_items) >= limit:
            break
    return signal_items


async def _load_alert_reference_symbols(db, portfolio: Any | None) -> list[str]:
    symbols: list[str] = []
    if portfolio is not None:
        for item in getattr(portfolio, "items", []):
            currency = str(getattr(item, "currency", "") or "").strip().upper()
            if currency and currency != "KRW":
                symbols.append(f"KRW-{currency}")

    try:
        favorite_result = await db.execute(
            select(Favorite.symbol).order_by(desc(Favorite.created_at), desc(Favorite.id))
        )
        symbols.extend(
            str(symbol).strip().upper()
            for symbol in favorite_result.scalars().all()
            if str(symbol).strip()
        )
    except Exception:
        logger.exception("Slack 가격 영향 뉴스 관심종목 조회 실패")

    return _dedupe_preserve_order(symbols)


def _build_market_impact_news_query(*, recent_only: bool) -> dict[str, Any]:
    filters: list[dict[str, Any]] = [{"exists": {"field": "parent_id"}}]
    if recent_only:
        filters.append(
            {
                "range": {
                    "published_at": {
                        "gte": (
                            datetime.now(timezone.utc)
                            - timedelta(hours=MARKET_IMPACT_RECENT_HOURS)
                        ).isoformat(),
                    }
                }
            }
        )

    return {
        "size": MARKET_IMPACT_NEWS_CANDIDATE_LIMIT,
        "_source": [
            "title",
            "content",
            "summary",
            "source",
            "published_at",
            "link",
            "parent_id",
            "chunk_index",
            "chunk_count",
        ],
        "query": {
            "bool": {
                "filter": filters,
                "must_not": [
                    {"wildcard": {"link": "dummy://*"}},
                    {"match_phrase": {"content": "credentials are unavailable"}},
                    {"match_phrase": {"content": "request failed"}},
                    {
                        "match_phrase": {
                            "content": "generated to keep the rag ingestion pipeline alive",
                        }
                    },
                ],
            }
        },
        "sort": [
            {"published_at": {"order": "desc", "missing": "_last"}},
            {"_score": {"order": "desc"}},
        ],
    }


async def _search_market_impact_news_candidates(*, recent_only: bool) -> list[dict[str, Any]]:
    client = get_opensearch_client()
    response = await client.search(
        index=INDEX_NAME,
        body=_build_market_impact_news_query(recent_only=recent_only),
    )
    hits = response.get("hits", {}).get("hits", [])
    if not isinstance(hits, list):
        return []
    return [
        _normalize_market_news_hit(hit)
        for hit in hits
        if isinstance(hit, dict)
    ]


async def _load_market_impact_news_items(reference_symbols: list[str]) -> list[dict[str, Any]]:
    try:
        candidates = await _search_market_impact_news_candidates(recent_only=True)
        ranked = _rank_market_impact_news_candidates(
            candidates,
            reference_symbols=reference_symbols,
        )
        if ranked:
            return ranked

        fallback_candidates = await _search_market_impact_news_candidates(recent_only=False)
        return _rank_market_impact_news_candidates(
            fallback_candidates,
            reference_symbols=reference_symbols,
        )
    except Exception:
        logger.exception("Slack 가격 영향 뉴스 후보 조회 실패")
        return []


def _build_portfolio_alert_section(portfolio: Any) -> dict[str, Any]:
    if portfolio is None:
        text = "포트폴리오 섹션이 비활성화되어 있습니다."
    elif getattr(portfolio, "error", None):
        text = f"*포트폴리오:* 조회 실패 `{portfolio.error}`"
    else:
        items = sorted(
            [item for item in getattr(portfolio, "items", []) if getattr(item, "currency", "") != "KRW"],
            key=lambda item: float(getattr(item, "total_value", 0) or 0),
            reverse=True,
        )
        item_lines = [
            (
                f"- `{item.currency}` { _format_krw(item.total_value) } "
                f"({ _format_percentage(item.pnl_percentage) })"
            )
            for item in items[:5]
        ]
        if not item_lines:
            item_lines = ["- 보유 중인 코인 포지션이 없습니다."]
        text = (
            f"*포트폴리오*\n"
            f"총 평가금액: `{_format_krw(portfolio.total_net_worth)}`\n"
            f"총 손익: `{_format_signed_krw(portfolio.total_pnl)}`\n"
            + "\n".join(item_lines)
        )
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _build_fear_index_alert_section(sentiment: Any) -> dict[str, Any]:
    if sentiment is None:
        text = "공포지수 섹션이 비활성화되어 있습니다."
    else:
        score = max(0, min(100, int(getattr(sentiment, "score", 50))))
        updated_at = getattr(sentiment, "updated_at", None)
        text = (
            f"*오늘 공포지수*\n"
            f"점수: `{score}` ({_sentiment_label(score)})\n"
            f"갱신: `{_format_local_datetime(updated_at)}`"
        )
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _build_ai_signal_alert_section(signal_items: list[dict[str, Any]]) -> dict[str, Any]:
    if not signal_items:
        text = "*관심종목 AI 신호*\n조건에 맞는 BUY/SELL 신호가 없습니다."
    else:
        lines = [
            (
                f"- `{item['symbol']}` {item['decision']} "
                f"확신도 `{item['confidence']}%`, 추천비중 `{item['recommended_weight']}%` "
                f"({ _format_local_datetime(item.get('created_at')) })"
            )
            for item in signal_items
        ]
        text = "*관심종목 AI 신호*\n" + "\n".join(lines)
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _format_news_title_for_slack(item: dict[str, Any]) -> str:
    title = _truncate_alert_text(item.get("title") or "제목 없음", max_len=96)
    link = str(item.get("link") or "").strip()
    if not link.startswith(("http://", "https://")):
        return title
    safe_title = title.replace("|", " ").replace(">", "")
    safe_link = link.replace(">", "")
    return f"<{safe_link}|{safe_title}>"


def _format_news_published_at(value: Any) -> str:
    parsed = _parse_datetime_value(value)
    if parsed is None:
        return "-"
    return _format_local_datetime(parsed)


def _build_market_impact_news_alert_section(items: list[dict[str, Any]]) -> dict[str, Any]:
    if not items:
        text = "*가격 영향 뉴스 Top3*\n가격 영향 후보 뉴스가 없습니다."
    else:
        lines: list[str] = []
        for index, item in enumerate(items[:MARKET_IMPACT_NEWS_LIMIT], start=1):
            keywords = item.get("impact_keywords") or []
            related_symbols = item.get("related_symbols") or []
            keyword_text = ", ".join(str(keyword) for keyword in keywords[:4]) or "-"
            related_text = ", ".join(str(symbol) for symbol in related_symbols[:4]) or "-"
            direction = str(item.get("impact_direction") or "불명")
            source = str(item.get("source") or "-")
            published_at = _format_news_published_at(item.get("published_at"))
            lines.append(
                (
                    f"{index}. `{direction}` {_format_news_title_for_slack(item)}\n"
                    f"   관련: `{related_text}` | 키워드: `{keyword_text}` | "
                    f"{source} · `{published_at}`"
                )
            )
        text = "*가격 영향 뉴스 Top3*\n" + "\n".join(lines)
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _build_slack_portfolio_alert_blocks(
    rule: dict[str, Any],
    portfolio: Any = None,
    sentiment: Any = None,
    signal_items: list[dict[str, Any]] | None = None,
    market_impact_news_items: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    sections = set(_normalize_slack_alert_sections(rule.get("sections")))
    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "📊 포트폴리오 알림"},
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        f"rule=`{rule.get('id', 'unknown')}` | "
                        f"generated_at=`{_format_local_datetime()}`"
                    ),
                }
            ],
        },
    ]

    if "portfolio" in sections:
        blocks.append(_build_portfolio_alert_section(portfolio))
    if "fear_index" in sections:
        blocks.append(_build_fear_index_alert_section(sentiment))
    if "favorite_ai_signals" in sections:
        blocks.append(_build_ai_signal_alert_section(signal_items or []))
    if "market_impact_news" in sections:
        blocks.append(_build_market_impact_news_alert_section(market_impact_news_items or []))

    return blocks


async def slack_portfolio_alert_job(rule: dict[str, Any]) -> None:
    from app.services.slack_bot import slack_bot

    normalized_rule = _normalize_slack_portfolio_alert_rule(rule, fallback_id="manual")
    if normalized_rule is None or not normalized_rule.get("enabled", True):
        logger.warning("Slack 포트폴리오 알림 실행 스킵: invalid_rule=%s", rule)
        return

    sections = set(normalized_rule["sections"])
    try:
        portfolio = None
        sentiment = None
        signal_items: list[dict[str, Any]] = []
        market_impact_news_items: list[dict[str, Any]] = []
        async with AsyncSessionLocal() as db:
            if "portfolio" in sections or "market_impact_news" in sections:
                portfolio = await PortfolioService(db).get_aggregated_portfolio()
            if "fear_index" in sections:
                sentiment = await get_news_sentiment(force_refresh=False, db=db)
            if "favorite_ai_signals" in sections:
                signal_items = await _load_favorite_ai_signals(
                    db,
                    decisions=normalized_rule["signal_decisions"],
                    min_confidence=normalized_rule["min_confidence"],
                )
            if "market_impact_news" in sections:
                reference_symbols = await _load_alert_reference_symbols(db, portfolio)
                market_impact_news_items = await _load_market_impact_news_items(reference_symbols)

        slack_bot.send_message(
            text="Slack 포트폴리오 알림",
            blocks=_build_slack_portfolio_alert_blocks(
                normalized_rule,
                portfolio=portfolio,
                sentiment=sentiment,
                signal_items=signal_items,
                market_impact_news_items=market_impact_news_items,
            ),
        )
    except Exception:
        logger.exception("Slack 포트폴리오 알림 생성 중 오류가 발생했습니다.")
        slack_bot.send_message("⚠️ [알림 실패] Slack 포트폴리오 알림 생성 중 오류가 발생했습니다.")


async def daily_ai_briefing(force_refresh_news: bool = False, provider: str = DEFAULT_PROVIDER) -> None:
    from app.services.slack_bot import slack_bot

    try:
        async with AsyncSessionLocal() as db:
            sentiment = await get_news_sentiment(force_refresh=force_refresh_news, db=db)
            portfolio_payload = await analyze_portfolio(provider=provider, db=db)

        report = str(portfolio_payload.get("report") or "").strip()
        resolved_provider = str(portfolio_payload.get("provider") or provider).strip().lower() or provider
        blocks = _build_briefing_blocks(
            sentiment_score=int(sentiment.score),
            sentiment_summary=list(sentiment.summary),
            updated_at=sentiment.updated_at,
            report=report,
            provider=resolved_provider,
        )
        slack_bot.send_message(
            text="🧠 AI 모닝 브리핑",
            blocks=blocks,
        )
    except Exception:
        logger.exception("daily_ai_briefing 생성 중 오류가 발생했습니다.")
        slack_bot.send_message("⚠️ [브리핑 실패] AI 모닝 브리핑 생성 중 오류가 발생했습니다.")


def _build_briefing_blocks(
    sentiment_score: int,
    sentiment_summary: list[str],
    updated_at: datetime,
    report: str,
    provider: str,
) -> list[dict[str, Any]]:
    score = max(0, min(100, sentiment_score))
    label = _sentiment_label(score)
    summary_lines = [str(line).strip() for line in sentiment_summary if str(line).strip()]
    while len(summary_lines) < 3:
        summary_lines.append("요약 정보가 부족하여 기본 문구로 대체되었습니다.")
    summary_lines = summary_lines[:3]

    now_local = datetime.now().astimezone()
    updated_local = (
        updated_at.astimezone()
        if updated_at.tzinfo
        else updated_at.replace(tzinfo=timezone.utc).astimezone()
    )

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "🧠 AI 모닝 브리핑"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*시장 심리 지수:* `{score}` ({label})\n"
                    f"*분석 시각:* `{updated_local.strftime('%Y-%m-%d %H:%M:%S')}`"
                ),
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*뉴스 요약 3줄*\n"
                    f"1. {summary_lines[0]}\n"
                    f"2. {summary_lines[1]}\n"
                    f"3. {summary_lines[2]}"
                ),
            },
        },
        {"type": "divider"},
    ]

    safe_report = report if report else "AI 포트폴리오 리포트를 생성하지 못했습니다."
    for chunk in _chunk_text(safe_report, max_len=2800):
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": chunk,
                },
            }
        )

    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        f"provider=`{provider}` | generated_at=`{now_local.strftime('%Y-%m-%d %H:%M:%S')}`"
                    ),
                }
            ],
        }
    )
    return blocks


def _chunk_text(text: str, max_len: int) -> list[str]:
    lines = text.splitlines() or [text]
    chunks: list[str] = []
    current = ""

    for line in lines:
        candidate = line if not current else f"{current}\n{line}"
        if len(candidate) <= max_len:
            current = candidate
            continue

        if current:
            chunks.append(current)
            current = ""

        while len(line) > max_len:
            chunks.append(line[:max_len])
            line = line[max_len:]
        current = line

    if current:
        chunks.append(current)

    return chunks or [text[:max_len]]


def _sentiment_label(score: int) -> str:
    if score >= 75:
        return "극단적 탐욕"
    if score >= 56:
        return "탐욕"
    if score >= 45:
        return "중립"
    if score >= 25:
        return "공포"
    return "극단적 공포"
