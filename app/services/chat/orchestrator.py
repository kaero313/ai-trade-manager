from __future__ import annotations

from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

from app.core.config import settings

SupervisorRoute = Literal["rag_agent", "quant_agent", "ops_agent", "FINISH"]

SUPERVISOR_SYSTEM_PROMPT = """
(당신은 AI 트레이딩 봇의 수석 매니저입니다. 사용자의 질문을 분석하여 rag_agent, quant_agent, ops_agent 중 적절한 에이전트에게 작업을 위임하고, 결과를 종합하여 한국어로 친절하게 답변합니다.)

다음 규칙을 반드시 지키십시오.
1. 사용자의 요청이 과거 주문/분석/대화 이력, 포트폴리오 조회, 일반 설명 중심이면 rag_agent 로 라우팅합니다.
2. 사용자의 요청이 실시간 시세, 기술 지표, 시장 심리 등 정량 데이터 중심이면 quant_agent 로 라우팅합니다.
3. 사용자의 요청이 시스템 설정 조회, 설정 변경 제안, 운영 정책 관련이면 ops_agent 로 라우팅합니다.
4. Tool 호출이나 다른 에이전트 위임 없이 바로 답변할 수 있는 간단한 질문이면 FINISH 를 선택합니다.
5. 모든 응답은 한국어로 작성합니다.
6. 반드시 next_agent 와 response 두 값만 결정합니다.
""".strip()


class OrchestratorState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    next_agent: str


class SupervisorDecision(BaseModel):
    next_agent: SupervisorRoute = Field(...)
    response: str = Field(..., min_length=1)


def build_supervisor_chain() -> object:
    if not settings.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY 가 설정되지 않아 Supervisor 를 초기화할 수 없습니다.")

    model = ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0,
        api_key=settings.OPENAI_API_KEY,
    )
    return model.with_structured_output(SupervisorDecision)


async def supervisor_node(state: OrchestratorState) -> OrchestratorState:
    messages = list(state.get("messages") or [])
    if not messages:
        return {
            "messages": [AIMessage(content="질문이 비어 있습니다. 먼저 요청 내용을 입력해 주세요.")],
            "next_agent": "FINISH",
        }

    chain = build_supervisor_chain()
    decision = await chain.ainvoke(
        [
            SystemMessage(content=SUPERVISOR_SYSTEM_PROMPT),
            *messages,
        ]
    )

    return {
        "messages": [AIMessage(content=decision.response)],
        "next_agent": decision.next_agent,
    }
