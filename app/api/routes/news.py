from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.news_scraper import fetch_crypto_news

router = APIRouter()


class NewsItem(BaseModel):
    title: str = Field(...)
    summary: str = Field(...)
    link: str = Field(...)


class NewsResponse(BaseModel):
    analysis_completed_at: str = Field(...)
    count: int = Field(...)
    items: list[NewsItem] = Field(default_factory=list)


@router.get("/", response_model=NewsResponse)
async def get_news() -> NewsResponse:
    payload = fetch_crypto_news()
    raw_items = payload.get("items") or []
    items = [
        NewsItem(
            title=str(item.get("title") or ""),
            summary=str(item.get("summary") or ""),
            link=str(item.get("link") or ""),
        )
        for item in raw_items
        if isinstance(item, dict)
    ]
    analysis_completed_at = str(payload.get("analysis_completed_at") or "")
    return NewsResponse(
        analysis_completed_at=analysis_completed_at,
        count=len(items),
        items=items,
    )
