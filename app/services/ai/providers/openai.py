from typing import TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
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

OPENAI_TEXT_MODEL = "gpt-5-mini"


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
    if "insufficient_quota" in message:
        return "OpenAI 결제 또는 사용량 한도 때문에 분석을 완료할 수 없습니다."
    if "rate limit" in message or "429" in message or "quota" in message:
        return "OpenAI 요청 한도에 도달해 잠시 분석을 완료할 수 없습니다."
    return "OpenAI 분석을 일시적으로 완료하지 못했습니다."


class OpenAIAnalyzer(BaseAIAnalyzer):
    def __init__(self, model: str | None = None) -> None:
        self.model = (model or OPENAI_TEXT_MODEL).strip() or OPENAI_TEXT_MODEL
        self.api_key = _resolve_openai_api_key()

    def _ensure_client_available(self) -> None:
        if self.api_key is None:
            raise RuntimeError("OpenAI API 키가 설정되지 않아 분석을 실행할 수 없습니다.")

    def _build_chat_model(self) -> ChatOpenAI:
        self._ensure_client_available()
        return ChatOpenAI(model=self.model, api_key=self.api_key)

    def _build_rate_limit_error(self, error: Exception) -> AIProviderRateLimitError:
        reason = "insufficient_quota" if "insufficient_quota" in str(error).lower() else "rate_limit"
        return AIProviderRateLimitError(
            _normalize_openai_error(error),
            provider="openai",
            reason=reason,
            blocked_until=resolve_provider_block_until("openai", error),
        )

    async def generate_report(self, portfolio_str: str) -> str:
        try:
            response = await self._build_chat_model().ainvoke(
                [
                    SystemMessage(content=SYSTEM_PROMPT),
                    HumanMessage(content=portfolio_str),
                ]
            )
        except Exception as error:
            if is_provider_rate_limit_error("openai", error):
                raise self._build_rate_limit_error(error) from error
            raise RuntimeError(_normalize_openai_error(error)) from error

        content = response.content
        if isinstance(content, str) and content.strip():
            return content
        if isinstance(content, list) and content:
            joined = "\n".join(str(item) for item in content if str(item).strip())
            if joined.strip():
                return joined

        return "OpenAI 분석 응답이 비어 있습니다."

    async def generate_structured_analysis(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[StructuredResponseT],
    ) -> StructuredResponseT:
        try:
            structured_model = self._build_chat_model().with_structured_output(response_model)
            result = await structured_model.ainvoke(
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_prompt),
                ]
            )
        except Exception as error:
            if is_provider_rate_limit_error("openai", error):
                raise self._build_rate_limit_error(error) from error
            raise

        if isinstance(result, response_model):
            return result
        if isinstance(result, BaseModel):
            return response_model.model_validate(result.model_dump())
        if isinstance(result, dict):
            return response_model.model_validate(result)

        return response_model.model_validate(result)
