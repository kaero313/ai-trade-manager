from typing import TypeVar

from google import genai
from google.genai import types
from pydantic import BaseModel

from app.core.config import settings
from app.services.ai.providers.base import (
    AIProviderRateLimitError,
    SYSTEM_PROMPT,
    BaseAIAnalyzer,
    is_provider_rate_limit_error,
    resolve_provider_block_until,
)

StructuredResponseT = TypeVar("StructuredResponseT", bound=BaseModel)

GEMINI_TEXT_MODEL = "gemini-3-flash-preview"
GEMINI_EMBEDDING_MODEL = "gemini-embedding-001"
GEMINI_EMBEDDING_DIMENSION = 1536


def _normalize_gemini_error(error: Exception) -> str:
    message = str(error).lower()
    if "resource_exhausted" in message or "quota" in message or "429" in message:
        return "Gemini 쿼터 초과로 잠시 분석을 완료할 수 없습니다."
    if "503" in message or "unavailable" in message or "high demand" in message:
        return "Gemini 모델이 일시적으로 불안정해 잠시 분석을 완료할 수 없습니다."
    if "api key" in message or "permission" in message or "403" in message:
        return "Gemini API 설정이 필요해 분석을 완료하지 못했습니다."
    return "Gemini 분석을 일시적으로 완료하지 못했습니다."


class GeminiAnalyzer(BaseAIAnalyzer):
    def __init__(self, model: str | None = None) -> None:
        self.model = (model or GEMINI_TEXT_MODEL).strip() or GEMINI_TEXT_MODEL
        self.client = genai.Client(api_key=settings.GEMINI_API_KEY) if settings.GEMINI_API_KEY else None

    def _ensure_client_available(self) -> None:
        if self.client is None:
            raise RuntimeError("Gemini API 키가 설정되지 않아 분석을 실행할 수 없습니다.")

    def _build_rate_limit_error(self, error: Exception) -> AIProviderRateLimitError:
        return AIProviderRateLimitError(
            _normalize_gemini_error(error),
            provider="gemini",
            reason="rate_limit",
            blocked_until=resolve_provider_block_until("gemini", error),
        )

    async def generate_report(self, portfolio_str: str) -> str:
        self._ensure_client_available()

        try:
            response = await self.client.aio.models.generate_content(
                model=self.model,
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
            if is_provider_rate_limit_error("gemini", error):
                raise self._build_rate_limit_error(error) from error
            raise RuntimeError(_normalize_gemini_error(error)) from error

    async def generate_embeddings(
        self,
        texts: list[str],
        *,
        task_type: str,
    ) -> list[list[float]]:
        if not texts:
            return []

        self._ensure_client_available()

        try:
            response = await self.client.aio.models.embed_content(
                model=GEMINI_EMBEDDING_MODEL,
                contents=texts,
                config=types.EmbedContentConfig(
                    task_type=task_type,
                    output_dimensionality=GEMINI_EMBEDDING_DIMENSION,
                ),
            )
        except Exception as error:
            if is_provider_rate_limit_error("gemini", error):
                raise self._build_rate_limit_error(error) from error
            raise

        response_embeddings = getattr(response, "embeddings", None)
        if not isinstance(response_embeddings, list) or len(response_embeddings) != len(texts):
            raise RuntimeError("Gemini 임베딩 응답 개수가 요청 개수와 일치하지 않습니다.")

        embeddings: list[list[float]] = []
        for index, item in enumerate(response_embeddings):
            values = getattr(item, "values", None)
            if not isinstance(values, list) or len(values) != GEMINI_EMBEDDING_DIMENSION:
                raise RuntimeError(f"Gemini 임베딩 차원이 올바르지 않습니다: index={index}")
            embeddings.append([float(value) for value in values])

        return embeddings

    async def generate_embedding(self, text: str, *, task_type: str) -> list[float]:
        embeddings = await self.generate_embeddings([text], task_type=task_type)
        return embeddings[0]

    async def generate_structured_analysis(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[StructuredResponseT],
    ) -> StructuredResponseT:
        self._ensure_client_available()

        try:
            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    response_mime_type="application/json",
                    response_schema=response_model,
                ),
            )
        except Exception as error:
            if is_provider_rate_limit_error("gemini", error):
                raise self._build_rate_limit_error(error) from error
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
