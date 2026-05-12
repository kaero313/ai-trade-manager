import logging
import re
import threading
from datetime import datetime, timedelta, timezone
from html import unescape
from typing import Any

import feedparser

logger = logging.getLogger(__name__)

RSS_FEED_URLS: list[str] = [
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://www.tokenpost.kr/rss",
    "https://cointelegraph.com/rss",
    "https://news.google.com/rss/search?q=%EA%B0%80%EC%83%81%EC%9E%90%EC%82%B0&hl=ko&gl=KR&ceid=KR:ko",
]
MAX_NEWS_ITEMS = 15
CACHE_TTL_SECONDS = 300

_CACHE_LOCK = threading.Lock()
_NEWS_CACHE: dict[str, Any] = {
    "items": [],
    "analysis_completed_at": None,
    "fetched_at": None,
}


def _sanitize_text(raw: Any) -> str:
    text = str(raw or "")
    text = unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _parse_feed_entries(feed_url: str) -> list[dict[str, str]]:
    parsed = feedparser.parse(feed_url)
    if getattr(parsed, "bozo", False):
        logger.warning("RSS 파싱 경고가 발생했습니다: feed=%s", feed_url)

    entries = getattr(parsed, "entries", [])
    results: list[dict[str, str]] = []
    for entry in entries:
        title = _sanitize_text(entry.get("title"))
        summary = _sanitize_text(entry.get("summary") or entry.get("description"))
        link = _sanitize_text(entry.get("link"))

        if not title or not link:
            continue

        results.append(
            {
                "title": title,
                "summary": summary,
                "link": link,
            }
        )
    return results


def _deduplicate(items: list[dict[str, str]]) -> list[dict[str, str]]:
    deduped: list[dict[str, str]] = []
    seen_keys: set[str] = set()

    for item in items:
        key = item.get("link") or item.get("title") or ""
        if not key or key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(item)
    return deduped


def _snapshot_cache() -> dict[str, Any]:
    with _CACHE_LOCK:
        return {
            "items": list(_NEWS_CACHE.get("items") or []),
            "analysis_completed_at": _NEWS_CACHE.get("analysis_completed_at"),
            "fetched_at": _NEWS_CACHE.get("fetched_at"),
        }


def _cache_is_valid(snapshot: dict[str, Any], now_utc: datetime) -> bool:
    fetched_at = snapshot.get("fetched_at")
    if not isinstance(fetched_at, datetime):
        return False
    return now_utc - fetched_at < timedelta(seconds=CACHE_TTL_SECONDS)


def fetch_crypto_news(force_refresh: bool = False) -> dict[str, Any]:
    now_utc = datetime.now(timezone.utc)
    snapshot = _snapshot_cache()
    if not force_refresh and _cache_is_valid(snapshot, now_utc):
        return {
            "items": snapshot["items"],
            "analysis_completed_at": snapshot.get("analysis_completed_at") or now_utc.isoformat(),
        }

    collected: list[dict[str, str]] = []
    for feed_url in RSS_FEED_URLS:
        try:
            collected.extend(_parse_feed_entries(feed_url))
        except Exception:
            logger.exception("RSS 수집 중 예외가 발생했습니다: feed=%s", feed_url)

    deduped = _deduplicate(collected)[:MAX_NEWS_ITEMS]
    if not deduped and snapshot.get("items"):
        logger.warning("신규 RSS 수집 결과가 없어 캐시된 뉴스를 반환합니다.")
        return {
            "items": snapshot["items"],
            "analysis_completed_at": snapshot.get("analysis_completed_at") or now_utc.isoformat(),
        }

    analysis_completed_at = now_utc.isoformat()
    with _CACHE_LOCK:
        _NEWS_CACHE["items"] = deduped
        _NEWS_CACHE["analysis_completed_at"] = analysis_completed_at
        _NEWS_CACHE["fetched_at"] = now_utc

    return {
        "items": deduped,
        "analysis_completed_at": analysis_completed_at,
    }
