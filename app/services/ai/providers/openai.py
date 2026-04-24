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


def _normalize_openai_error(error: Exception) -> str:
    message = str(error).lower()
    if "invalid_api_key" in message or "incorrect api key" in message:
        return "OpenAI API 설정이 필요해 분석을 완료하지 못했습니다."
    if "rate limit" in message or "429" in message:
        return "OpenAI 요청 한도에 도달해 잠시 분석을 완료할 수 없습니다."
    return "OpenAI 분석을 일시적으로 완료하지 못했습니다."


class OpenAIAnalyzer(BaseAIAnalyzer):
    def __init__(self) -> None:
        api_key = _resolve_openai_api_key()
        self.client = AsyncOpenAI(api_key=api_key) if api_key else None

    async def generate_report(self, portfolio_str: str) -> str:
        if self.client is None:
            return "OpenAI API 설정이 필요해 분석을 완료하지 못했습니다."

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

            return "OpenAI 분석 응답이 비어 있습니다."
        except Exception as error:
            return _normalize_openai_error(error)
