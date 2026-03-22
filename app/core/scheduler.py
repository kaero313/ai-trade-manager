import asyncio
import logging
import threading
from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.api.routes.ai import analyze_portfolio
from app.api.routes.news import get_news_sentiment
from app.db.session import AsyncSessionLocal
from app.services.rag.ingestion import run_market_news_ingestion_job

logger = logging.getLogger(__name__)

SCHEDULER_TIMEZONE = "Asia/Seoul"
DAILY_BRIEFING_JOB_ID = "daily_ai_briefing"
MARKET_NEWS_INGESTION_JOB_ID = "market_news_ingestion_hourly"
DEFAULT_PROVIDER = "openai"

scheduler = BackgroundScheduler(timezone=SCHEDULER_TIMEZONE)


def start_scheduler() -> None:
    if scheduler.running:
        return

    register_daily_jobs()
    register_market_news_jobs()
    scheduler.start()
    logger.info("APScheduler started: timezone=%s", SCHEDULER_TIMEZONE)


def stop_scheduler() -> None:
    if not scheduler.running:
        return

    scheduler.shutdown(wait=False)
    logger.info("APScheduler 종료")


def register_daily_jobs() -> None:
    trigger = CronTrigger(hour=8, minute=30, timezone=SCHEDULER_TIMEZONE)
    scheduler.add_job(
        run_daily_ai_briefing_job,
        trigger=trigger,
        id=DAILY_BRIEFING_JOB_ID,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=1800,
    )


def register_market_news_jobs() -> None:
    trigger = CronTrigger(minute=0, timezone=SCHEDULER_TIMEZONE)
    scheduler.add_job(
        run_market_news_ingestion_scheduler_job,
        trigger=trigger,
        id=MARKET_NEWS_INGESTION_JOB_ID,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=1800,
    )


def run_market_news_ingestion_scheduler_job() -> None:
    try:
        asyncio.run(run_market_news_ingestion_job())
    except Exception:
        logger.exception("market_news ingestion scheduler job failed.")


def run_daily_ai_briefing_job() -> None:
    try:
        asyncio.run(daily_ai_briefing(force_refresh_news=False, provider=DEFAULT_PROVIDER))
    except Exception:
        logger.exception("daily_ai_briefing 스케줄 작업 실행 중 오류가 발생했습니다.")


def trigger_daily_ai_briefing_now() -> None:
    def _runner() -> None:
        try:
            asyncio.run(daily_ai_briefing(force_refresh_news=True, provider=DEFAULT_PROVIDER))
        except Exception:
            logger.exception("daily_ai_briefing 수동 실행 중 오류가 발생했습니다.")

    threading.Thread(
        target=_runner,
        name="daily-ai-briefing-manual",
        daemon=True,
    ).start()


async def daily_ai_briefing(force_refresh_news: bool = False, provider: str = DEFAULT_PROVIDER) -> None:
    from app.services.slack_bot import slack_bot

    try:
        sentiment = await get_news_sentiment(force_refresh=force_refresh_news)

        async with AsyncSessionLocal() as db:
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
            text="🌅 AI 모닝 브리핑",
            blocks=blocks,
        )
    except Exception:
        logger.exception("daily_ai_briefing 생성 중 오류가 발생했습니다.")
        slack_bot.send_message("🚨 [브리핑 실패] AI 모닝 브리핑 생성 중 오류가 발생했습니다.")


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
    updated_local = updated_at.astimezone() if updated_at.tzinfo else updated_at.replace(tzinfo=timezone.utc).astimezone()

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "🌅 AI 모닝 브리핑"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*시장 심리 점수:* `{score}` ({label})\n"
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
