from typing import TypeVar

from google import genai
from google.genai import types
from pydantic import BaseModel

from app.core.config import settings
from app.services.ai.providers.base import BaseAIAnalyzer
from app.services.ai.providers.base import SYSTEM_PROMPT

StructuredResponseT = TypeVar("StructuredResponseT", bound=BaseModel)


class AIProviderRateLimitError(RuntimeError):
    """AI provider quota/rate-limit으로 인해 즉시 중단이 필요한 경우."""


def _is_gemini_rate_limit_error(error: Exception) -> bool:
    message = str(error).lower()
    return "resource_exhausted" in message or "quota" in message or "429" in message


def _normalize_gemini_error(error: Exception) -> str:
    message = str(error).lower()
    if "resource_exhausted" in message or "quota" in message or "429" in message:
        return "Gemini 쿼터 초과로 잠시 분석을 완료할 수 없습니다."
    if "api key" in message or "permission" in message or "403" in message:
        return "Gemini API 설정이 필요해 분석을 완료하지 못했습니다."
    return "Gemini 분석을 일시적으로 완료하지 못했습니다."


class GeminiAnalyzer(BaseAIAnalyzer):
    def __init__(self) -> None:
        self.client = genai.Client(api_key=settings.GEMINI_API_KEY) if settings.GEMINI_API_KEY else None

    async def generate_report(self, portfolio_str: str) -> str:
        if self.client is None:
            return "Gemini API 설정이 필요해 분석을 완료하지 못했습니다."

        try:
            response = await self.client.aio.models.generate_content(
                model="gemini-3-flash-preview",
                contents=portfolio_str,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                ),
            )

            response_text = getattr(response, "text", None)
            if isinstance(response_text, str) and response_text.strip():
                return response_text

            return "Gemini 분석 응답이 비어 있습니다."
        except Exception as error:
            return _normalize_gemini_error(error)

    async def generate_structured_analysis(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[StructuredResponseT],
    ) -> StructuredResponseT:
        if self.client is None:
            raise RuntimeError("Gemini API 키가 설정되지 않아 구조화 분석을 실행할 수 없습니다.")

        try:
            response = await self.client.aio.models.generate_content(
                model="gemini-3-flash-preview",
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    response_mime_type="application/json",
                    response_schema=response_model,
                ),
            )
        except Exception as error:
            if _is_gemini_rate_limit_error(error):
                raise AIProviderRateLimitError(_normalize_gemini_error(error)) from error
            raise

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
