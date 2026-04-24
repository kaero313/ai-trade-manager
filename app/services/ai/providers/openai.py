from openai import AsyncOpenAI

from app.core.config import settings
from app.services.ai.providers.base import BaseAIAnalyzer, SYSTEM_PROMPT


def _resolve_openai_api_key() -> str | None:
    api_key = str(settings.OPENAI_API_KEY or "").strip()
    if not api_key:
        return None

    normalized = api_key.lower()
    if normalized.startswith("your_"):
        return None
    if normalized.endswith("_here") or normalized.endswith("here"):
        return None
    return api_key


class OpenAIAnalyzer(BaseAIAnalyzer):
    def __init__(self) -> None:
        api_key = _resolve_openai_api_key()
        self.client = AsyncOpenAI(api_key=api_key) if api_key else None

    async def generate_report(self, portfolio_str: str) -> str:
        if self.client is None:
            return " OpenAI API 키가 설정되지 않아 분석 리포트를 생성할 수 없습니다."

        try:
            response = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": portfolio_str},
                ],
            )

            if response.choices and response.choices[0].message:
                content = response.choices[0].message.content
                if isinstance(content, str) and content.strip():
                    return content

            return " AI 분석 응답이 비어 있습니다."
        except Exception as error:
            return f" AI 분석을 가져오는 중 오류가 발생했습니다: {error}"
