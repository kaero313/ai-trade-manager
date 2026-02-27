from app.services.ai.providers.openai import OpenAIAnalyzer

_analyzer = OpenAIAnalyzer()


async def generate_portfolio_report(portfolio_str: str) -> str:
    return await _analyzer.generate_report(portfolio_str)
