from openai import AsyncOpenAI

from app.core.config import settings

SYSTEM_PROMPT = (
    "당신은 월스트리트의 냉철하고 전문적인 크립토/주식 포트폴리오 분석가입니다. "
    "주어진 포트폴리오의 자산 비중과 수익률을 객관적으로 분석하십시오. "
    "리스크가 높은 자산은 경고하며, 다음 트레이딩 액션에 대한 시나리오 기반의 조언(3문단 이내)을 "
    "읽기 쉬운 마크다운 텍스트 템플릿 포맷으로 제공하십시오."
)

client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY) if settings.OPENAI_API_KEY else None


async def generate_portfolio_report(portfolio_str: str) -> str:
    if client is None:
        return " OpenAI API 키가 설정되지 않아 분석 리포트를 생성할 수 없습니다."

    try:
        response = await client.chat.completions.create(
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

        return " AI 분석 응답이 비어 있습니다."
    except Exception as error:
        return f" AI 분석을 가져오는 중 오류가 발생했습니다: {error}"
