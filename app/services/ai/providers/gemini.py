from typing import TypeVar

from google import genai
from google.genai import types
from pydantic import BaseModel

from app.core.config import settings
from app.services.ai.providers.base import BaseAIAnalyzer
from app.services.ai.providers.base import SYSTEM_PROMPT

StructuredResponseT = TypeVar("StructuredResponseT", bound=BaseModel)


class GeminiAnalyzer(BaseAIAnalyzer):
    def __init__(self) -> None:
        self.client = genai.Client(api_key=settings.GEMINI_API_KEY) if settings.GEMINI_API_KEY else None

    async def generate_report(self, portfolio_str: str) -> str:
        if self.client is None:
            return "Gemini API 키가 설정되지 않아 분석 리포트를 생성할 수 없습니다."

        try:
            response = await self.client.aio.models.generate_content(
                model="gemini-2.0-flash",
                contents=portfolio_str,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                ),
            )

            response_text = getattr(response, "text", None)
            if isinstance(response_text, str) and response_text.strip():
                return response_text

            return "AI 분석 응답이 비어 있습니다."
        except Exception as error:
            return f"AI 분석을 가져오는 중 오류가 발생했습니다: {error}"

    async def generate_structured_analysis(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[StructuredResponseT],
    ) -> StructuredResponseT:
        if self.client is None:
            raise RuntimeError("Gemini API 키가 설정되지 않아 구조화 분석을 실행할 수 없습니다.")

        response = await self.client.aio.models.generate_content(
            model="gemini-2.0-flash",
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
                response_schema=response_model,
            ),
        )

        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, response_model):
            return parsed

        if isinstance(parsed, BaseModel):
            return response_model.model_validate(parsed.model_dump())

        if isinstance(parsed, dict):
            return response_model.model_validate(parsed)

        response_text = getattr(response, "text", None)
        if isinstance(response_text, str) and response_text.strip():
            return response_model.model_validate_json(response_text)

        raise RuntimeError("Gemini 구조화 응답이 비어 있습니다.")
