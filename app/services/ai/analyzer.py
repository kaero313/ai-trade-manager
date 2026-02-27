from app.services.ai.providers.base import BaseAIAnalyzer
from app.services.ai.providers.gemini import GeminiAnalyzer
from app.services.ai.providers.openai import OpenAIAnalyzer


class AIAnalyzerFactory:
    @staticmethod
    def get_analyzer(provider: str) -> BaseAIAnalyzer:
        normalized = (provider or "").strip().lower()

        if normalized == "gemini":
            return GeminiAnalyzer()

        if normalized == "openai":
            return OpenAIAnalyzer()

        return OpenAIAnalyzer()
