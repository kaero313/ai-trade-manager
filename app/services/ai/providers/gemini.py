from google import genai

from app.core.config import settings
from app.services.ai.providers.base import BaseAIAnalyzer, SYSTEM_PROMPT


class GeminiAnalyzer(BaseAIAnalyzer):
    def __init__(self) -> None:
        self.client = genai.Client(api_key=settings.GEMINI_API_KEY) if settings.GEMINI_API_KEY else None

    async def generate_report(self, portfolio_str: str) -> str:
        if self.client is None:
            return " Gemini API 키가 설정되지 않아 분석 리포트를 생성할 수 없습니다."

        try:
            response = await self.client.aio.models.generate_content(
                model="gemini-2.5-flash",
                contents=portfolio_str,
                config={"system_instruction": SYSTEM_PROMPT},
            )

            response_text = getattr(response, "text", None)
            if isinstance(response_text, str) and response_text.strip():
                return response_text

            return " AI 분석 응답이 비어 있습니다."
        except Exception as error:
            return f" AI 분석을 가져오는 중 오류가 발생했습니다: {error}"
