from app.services.ai.providers.base import BaseAIAnalyzer


class AIAnalyzerFactory:
    @staticmethod
    def get_analyzer(provider: str, model: str | None = None) -> BaseAIAnalyzer:
        normalized = (provider or "").strip().lower()

        if normalized == "openai":
            from app.services.ai.providers.openai import OpenAIAnalyzer

            return OpenAIAnalyzer(model=model)

        from app.services.ai.providers.gemini import GeminiAnalyzer

        return GeminiAnalyzer(model=model)
