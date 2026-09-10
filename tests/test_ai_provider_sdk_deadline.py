from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.services.ai.provider_router import AIProviderCandidate
from app.services.ai.providers import gemini as gemini_provider
from app.services.ai.providers import openai as openai_provider
from app.services.ai.providers.base import AI_PROVIDER_HTTP_TIMEOUT_SECONDS
from app.services.ai.providers.base import AIProviderTimeoutError
from app.services.ai.providers.base import await_with_provider_deadline
from app.services.chat import orchestrator


def test_openai_analyzer_builds_clients_with_timeout_and_no_retry(monkeypatch) -> None:
    chat_kwargs: dict[str, Any] = {}
    client_kwargs: dict[str, Any] = {}

    def build_chat(**kwargs):
        chat_kwargs.update(kwargs)
        return object()

    def build_client(**kwargs):
        client_kwargs.update(kwargs)
        return object()

    monkeypatch.setattr(openai_provider, "ChatOpenAI", build_chat)
    monkeypatch.setattr(openai_provider, "AsyncOpenAI", build_client)
    analyzer = openai_provider.OpenAIAnalyzer()
    analyzer.api_key = "test-key"

    analyzer._build_chat_model()
    analyzer._build_async_client()

    assert chat_kwargs["timeout"] == AI_PROVIDER_HTTP_TIMEOUT_SECONDS
    assert chat_kwargs["max_retries"] == 0
    assert client_kwargs["timeout"] == AI_PROVIDER_HTTP_TIMEOUT_SECONDS
    assert client_kwargs["max_retries"] == 0


def test_gemini_analyzer_builds_client_with_timeout_and_single_attempt(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def build_client(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(gemini_provider.genai, "Client", build_client)
    monkeypatch.setattr(gemini_provider.settings, "GEMINI_API_KEY", "test-key")

    gemini_provider.GeminiAnalyzer()

    http_options = captured["http_options"]
    assert http_options.timeout == int(AI_PROVIDER_HTTP_TIMEOUT_SECONDS * 1000)
    assert http_options.retry_options.attempts == 1


def test_chat_openai_model_uses_timeout_and_no_retry(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def build_chat(**kwargs):
        captured.update(kwargs)
        return object()

    import langchain_openai

    monkeypatch.setattr(langchain_openai, "ChatOpenAI", build_chat)
    monkeypatch.setattr(orchestrator.settings, "OPENAI_API_KEY", "test-key")

    orchestrator._build_chat_model(
        AIProviderCandidate(provider="openai", model="gpt-test")
    )

    assert captured["timeout"] == AI_PROVIDER_HTTP_TIMEOUT_SECONDS
    assert captured["max_retries"] == 0


def test_chat_gemini_model_uses_timeout_and_single_attempt(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def build_chat(**kwargs):
        captured.update(kwargs)
        return object()

    import langchain_google_genai

    monkeypatch.setattr(langchain_google_genai, "ChatGoogleGenerativeAI", build_chat)
    monkeypatch.setattr(orchestrator.settings, "GEMINI_API_KEY", "test-key")

    orchestrator._build_chat_model(
        AIProviderCandidate(provider="gemini", model="gemini-test")
    )

    assert captured["request_timeout"] == AI_PROVIDER_HTTP_TIMEOUT_SECONDS
    assert captured["retries"] == 1


@pytest.mark.asyncio
async def test_provider_deadline_helper_cancels_hung_operation() -> None:
    with pytest.raises(AIProviderTimeoutError, match="openai"):
        await asyncio.wait_for(
            await_with_provider_deadline(
                asyncio.Event().wait(),
                provider="openai",
                timeout_seconds=0.02,
            ),
            timeout=0.30,
        )
