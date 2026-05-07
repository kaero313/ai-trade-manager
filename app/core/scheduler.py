import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

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
from app.db.repository import NEWS_INTERVAL_HOURS_KEY
from app.db.repository import SENTIMENT_INTERVAL_MINUTES_KEY
from app.db.repository import get_system_config_value
from app.db.repository import save_portfolio_snapshot
from app.db.session import AsyncSessionLocal
from app.models.domain import Favorite
from app.services.market.sentiment_fetcher import refresh_market_sentiment_cache
from app.services.portfolio.aggregator import PortfolioService
from app.services.rag.ingestion import run_market_news_ingestion_job
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
DAILY_BRIEFING_JOB_ID = "daily_ai_briefing"
MARKET_NEWS_INGESTION_JOB_ID = "market_news_ingestion_hourly"
MARKET_SENTIMENT_REFRESH_JOB_ID = "market_sentiment_refresh"
AUTONOMOUS_AI_ANALYST_JOB_ID = "autonomous_ai_analyst_watchlist"
AI_ACCURACY_CHECK_JOB_ID = "ai_accuracy_check"
PORTFOLIO_SNAPSHOT_JOB_ID = "portfolio_snapshot_hourly"
DEFAULT_PROVIDER = "auto"

DEFAULT_NEWS_INTERVAL_HOURS = 4
DEFAULT_SENTIMENT_INTERVAL_MINUTES = 5
DEFAULT_AI_BRIEFING_HOUR = 8
DEFAULT_AI_BRIEFING_MINUTE = 30
DEFAULT_AUTONOMOUS_AI_INTERVAL_HOURS = 1
DEFAULT_AUTONOMOUS_AI_INTERVAL_MINUTES = DEFAULT_AUTONOMOUS_AI_INTERVAL_HOURS * 60
AUTONOMOUS_AI_ANALYST_SYMBOL_DELAY_SECONDS = 2

scheduler = AsyncIOScheduler(timezone=SCHEDULER_TIMEZONE)
_scheduler_loop: asyncio.AbstractEventLoop | None = None


@dataclass(slots=True)
class SchedulerRuntimeConfig:
    news_interval_hours: int = DEFAULT_NEWS_INTERVAL_HOURS
    sentiment_interval_minutes: int = DEFAULT_SENTIMENT_INTERVAL_MINUTES
    ai_briefing_hour: int = DEFAULT_AI_BRIEFING_HOUR
    ai_briefing_minute: int = DEFAULT_AI_BRIEFING_MINUTE
    autonomous_ai_interval_minutes: int = DEFAULT_AUTONOMOUS_AI_INTERVAL_MINUTES


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

    return SchedulerRuntimeConfig(
        news_interval_hours=news_interval_hours,
        sentiment_interval_minutes=sentiment_interval_minutes,
        ai_briefing_hour=ai_briefing_hour,
        ai_briefing_minute=ai_briefing_minute,
        autonomous_ai_interval_minutes=autonomous_ai_interval_minutes,
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


async def reload_scheduler_jobs() -> SchedulerRuntimeConfig:
    runtime_config = await load_scheduler_runtime_config()
    register_daily_jobs(runtime_config)
    register_market_news_jobs(runtime_config)
    register_market_sentiment_jobs(runtime_config)
    register_autonomous_ai_analyst_jobs(runtime_config)
    register_ai_accuracy_jobs(runtime_config)
    register_portfolio_snapshot_jobs()
    logger.info(
        "Scheduler jobs reloaded: news_interval_hours=%s sentiment_interval_minutes=%s ai_briefing_time=%02d:%02d autonomous_ai_interval_minutes=%s",
        runtime_config.news_interval_hours,
        runtime_config.sentiment_interval_minutes,
        runtime_config.ai_briefing_hour,
        runtime_config.ai_briefing_minute,
        runtime_config.autonomous_ai_interval_minutes,
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
