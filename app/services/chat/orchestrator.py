from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.repository import get_recent_chat_messages
from app.db.repository import save_chat_message
from app.models.schemas import ReviewerDecision
from app.services.chat.tools import build_chat_tools

SupervisorRoute = Literal["rag_agent", "quant_agent", "ops_agent", "FINISH"]

SUPERVISOR_SYSTEM_PROMPT = """
(당신은 AI 트레이딩 봇의 수석 매니저입니다. 사용자의 질문을 분석하여 rag_agent, quant_agent, ops_agent 중 적절한 에이전트에게 작업을 위임하고, 결과를 종합하여 한국어로 친절하게 답변합니다.)

다음 규칙을 반드시 지키십시오.
1. 과거 주문/분석/대화 이력, 포트폴리오 조회, 일반 설명 중심이면 rag_agent 로 라우팅합니다.
2. 실시간 시세, 기술 지표, 시장 심리 등 정량 데이터 중심이면 quant_agent 로 라우팅합니다.
3. 시스템 설정 조회, 설정 변경 제안, 운영 정책 관련이면 ops_agent 로 라우팅합니다.
4. Tool 호출이나 다른 에이전트 위임 없이 바로 답변할 수 있는 간단한 질문이면 FINISH 를 선택합니다.
5. 이미 rag_agent, quant_agent, ops_agent 의 결과가 들어와 있으면 그 내용을 읽고 최종 답변으로 종합한 뒤 FINISH 를 선택합니다.
6. ops_agent 결과에 설정 변경 제안 JSON 이 포함되어 있으면 그 JSON 을 훼손하지 말고 그대로 보존해 응답에 포함합니다.
7. reviewer 를 거쳐 전달된 답변에 '투자 책임은 본인에게 있습니다.' 면책 조항이 포함되어 있으면, 최종 응답을 종합할 때 그 문구를 삭제하거나 완화하지 말고 그대로 보존합니다.
8. 반드시 next_agent 와 response 두 값만 결정합니다.
9. 모든 응답은 한국어로 작성합니다.
""".strip()

RAG_AGENT_SYSTEM_PROMPT = """
당신은 rag_agent 입니다.
포트폴리오, 과거 주문, AI 분석 로그, 과거 대화 검색 Tool만 사용할 수 있습니다.
사용자 질문에 답하기 위해 필요한 경우에만 Tool을 호출하고, 확인된 정보만 바탕으로 한국어로 답하십시오.
최종 응답은 사실 요약 중심으로 작성하고, 없는 정보는 추측하지 마십시오.
""".strip()

QUANT_AGENT_SYSTEM_PROMPT = """
당신은 quant_agent 입니다.
실시간 시세, 기술 지표, 시장 심리 Tool만 사용할 수 있습니다.
정량 데이터와 시세 정보 중심으로 한국어로 답하고, 투자 조언처럼 과장하지 말고 관측된 수치 위주로 설명하십시오.
""".strip()

OPS_AGENT_SYSTEM_PROMPT = """
당신은 ops_agent 입니다.
현재 시스템 설정 조회 Tool과 설정 변경 제안 Tool만 사용할 수 있습니다.
실제 시스템 설정을 직접 바꿀 수 없으며, 변경이 필요하면 propose_config_change Tool을 호출해 승인 대기 JSON 제안서를 생성해야 합니다.
설정 변경이 적용되었다고 표현하지 말고, 반드시 승인 전 제안 단계임을 분명히 하십시오.
최종 응답에 config_change JSON 이 있으면 그 JSON 문자열을 그대로 포함하십시오.
""".strip()

REVIEWER_SYSTEM_PROMPT = """
당신은 AI 트레이딩 뱅커의 엄격한 최종 검수자(Reviewer)입니다. 이전 에이전트의 답변을 평가하십시오. 1) 출처나 근거 없는 할루시네이션(환각) 정보가 담겨있는지, 2) 투자, 시세 정보가 포함되었음에도 '투자 책임은 본인에게 있습니다.'라는 면책 조항(Disclaimer)이 누락되었는지 확인하십시오. 조건을 위반했다면 is_passed 를 false로 하고, feedback에 구체적인 수정 지시를 적으십시오. 통과라면 is_passed 를 true로 하십시오.
""".strip()

RAG_TOOL_NAMES = {
    "query_portfolio_summary",
    "query_order_history",
    "query_ai_analysis_logs",
    "search_past_conversations",
}
QUANT_TOOL_NAMES = {
    "get_realtime_ticker",
    "get_technical_indicators",
    "get_market_sentiment",
}
OPS_TOOL_NAMES = {
    "propose_config_change",
    "get_current_system_configs",
}
MAX_RETRIES = 2
MAX_TOOL_CALL_ROUNDS = 4
GRAPH_AGENT_NAMES = {"supervisor", "rag_agent", "quant_agent", "ops_agent"}


class OrchestratorState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    next_agent: str
    session_id: str
    retry_count: int


class SupervisorDecision(BaseModel):
    next_agent: SupervisorRoute = Field(...)
    response: str = Field(..., min_length=1)


def _build_chat_model() -> ChatGoogleGenerativeAI:
    if not settings.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY 가 설정되지 않아 Chat Orchestrator 를 실행할 수 없습니다.")

    return ChatGoogleGenerativeAI(
        model="gemini-2.0-flash",
        temperature=0,
        google_api_key=settings.GEMINI_API_KEY,
    )


def build_supervisor_chain() -> object:
    return _build_chat_model().with_structured_output(SupervisorDecision)


def build_reviewer_chain() -> object:
    return _build_chat_model().with_structured_output(ReviewerDecision)


def _increment_retry_count(state: OrchestratorState) -> int:
    return int(state.get("retry_count", 0)) + 1


def _reset_retry_count() -> int:
    return 0


def _stringify_tool_result(result: object) -> str:
    if isinstance(result, str):
        return result
    return json.dumps(result, ensure_ascii=False, default=str)


def _restore_working_memory_messages(history_rows: list[Any]) -> list[BaseMessage]:
    restored: list[BaseMessage] = []
    for row in history_rows:
        role = str(getattr(row, "role", "") or "").strip().lower()
        content = str(getattr(row, "content", "") or "")
        agent_name = getattr(row, "agent_name", None)

        if role == "user":
            restored.append(HumanMessage(content=content))
            continue

        if role == "assistant":
            restored.append(AIMessage(content=content, name=agent_name or None))

    return restored


def _extract_last_ai_message(messages: list[Any] | None) -> AIMessage | None:
    if not messages:
        return None

    for message in reversed(messages):
        if isinstance(message, AIMessage):
            return message
    return None


def _extract_agent_message_content(output: Any) -> str:
    if isinstance(output, dict):
        last_message = _extract_last_ai_message(output.get("messages"))
        if last_message is not None:
            return str(last_message.content or "")
    return ""


def _extract_approval_request_content(raw_output: Any) -> str | None:
    content = _stringify_tool_result(raw_output)
    try:
        payload = json.loads(content)
    except Exception:
        return None

    if (
        isinstance(payload, dict)
        and payload.get("action") == "config_change"
        and payload.get("requires_approval") is True
    ):
        return content
    return None


def _resolve_graph_agent_name(event: dict[str, Any]) -> str | None:
    metadata = event.get("metadata") or {}
    candidate = metadata.get("langgraph_node") or event.get("name")
    if candidate in GRAPH_AGENT_NAMES:
        return str(candidate)
    return None


def _get_filtered_tools(session_id: str, allowed_tool_names: set[str]) -> dict[str, BaseTool]:
    tools = build_chat_tools(session_id)
    return {tool.name: tool for tool in tools if tool.name in allowed_tool_names}


async def _run_worker_agent(
    state: OrchestratorState,
    *,
    agent_name: str,
    system_prompt: str,
    allowed_tool_names: set[str],
    target_agent: str = "supervisor",
) -> OrchestratorState:
    session_id = str(state.get("session_id") or "").strip()
    if not session_id:
        return {
            "messages": [AIMessage(name=agent_name, content="session_id 가 없어 에이전트를 실행할 수 없습니다.")],
            "next_agent": "FINISH",
        }

    messages = list(state.get("messages") or [])
    tools_by_name = _get_filtered_tools(session_id, allowed_tool_names)
    bound_model = _build_chat_model().bind_tools(list(tools_by_name.values()))
    conversation: list[BaseMessage] = [SystemMessage(content=system_prompt), *messages]

    for _ in range(MAX_TOOL_CALL_ROUNDS):
        response = await bound_model.ainvoke(conversation)
        conversation.append(response)

        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            return {
                "messages": [AIMessage(name=agent_name, content=response.content or "")],
                "next_agent": target_agent,
            }

        for tool_call in tool_calls:
            tool_name = str(tool_call.get("name") or "").strip()
            tool_call_id = str(tool_call.get("id") or tool_name or "tool_call")
            tool_args = tool_call.get("args") or {}
            tool = tools_by_name.get(tool_name)
            if tool is None:
                conversation.append(
                    ToolMessage(
                        tool_call_id=tool_call_id,
                        name=tool_name or None,
                        status="error",
                        content=f"허용되지 않은 Tool 호출입니다: {tool_name}",
                    )
                )
                continue

            try:
                result = await tool.ainvoke(tool_args)
                conversation.append(
                    ToolMessage(
                        tool_call_id=tool_call_id,
                        name=tool_name,
                        status="success",
                        content=_stringify_tool_result(result),
                    )
                )
            except Exception as exc:
                conversation.append(
                    ToolMessage(
                        tool_call_id=tool_call_id,
                        name=tool_name,
                        status="error",
                        content=f"Tool 실행 중 오류가 발생했습니다: {exc}",
                    )
                )

    return {
        "messages": [
            AIMessage(
                name=agent_name,
                content="도구 호출 단계가 너무 많아 작업을 마무리하지 못했습니다. 현재까지 수집한 정보만으로 다시 요청해 주세요.",
            )
        ],
        "next_agent": target_agent,
    }


async def supervisor_node(state: OrchestratorState) -> OrchestratorState:
    messages = list(state.get("messages") or [])
    if not messages:
        return {
            "messages": [AIMessage(name="supervisor", content="질문이 비어 있습니다. 먼저 요청 내용을 입력해 주세요.")],
            "next_agent": "FINISH",
        }

    decision = await build_supervisor_chain().ainvoke(
        [
            SystemMessage(content=SUPERVISOR_SYSTEM_PROMPT),
            *messages,
        ]
    )

    return {
        "messages": [AIMessage(name="supervisor", content=decision.response)],
        "next_agent": decision.next_agent,
    }


async def rag_agent_node(state: OrchestratorState) -> OrchestratorState:
    return await _run_worker_agent(
        state,
        agent_name="rag_agent",
        system_prompt=RAG_AGENT_SYSTEM_PROMPT,
        allowed_tool_names=RAG_TOOL_NAMES,
        target_agent="reviewer",
    )


async def quant_agent_node(state: OrchestratorState) -> OrchestratorState:
    return await _run_worker_agent(
        state,
        agent_name="quant_agent",
        system_prompt=QUANT_AGENT_SYSTEM_PROMPT,
        allowed_tool_names=QUANT_TOOL_NAMES,
        target_agent="reviewer",
    )


async def ops_agent_node(state: OrchestratorState) -> OrchestratorState:
    return await _run_worker_agent(
        state,
        agent_name="ops_agent",
        system_prompt=OPS_AGENT_SYSTEM_PROMPT,
        allowed_tool_names=OPS_TOOL_NAMES,
    )


async def _reviewer_node_placeholder(state: OrchestratorState) -> OrchestratorState:
    messages = list(state.get("messages") or [])
    last_message = _extract_last_ai_message(messages)

    if last_message is None:
        return {
            "messages": [
                AIMessage(
                    name="reviewer",
                    content="검토할 직전 에이전트 응답이 없어 supervisor로 복귀합니다.",
                )
            ],
            "next_agent": "supervisor",
        }

    return {
        "messages": [
            AIMessage(
                name="reviewer",
                content="Reviewer 검토 로직은 아직 구현되지 않았습니다.",
            )
        ],
        "next_agent": "supervisor",
    }


async def reviewer_node(state: OrchestratorState) -> OrchestratorState:
    messages = list(state.get("messages") or [])
    last_message = _extract_last_ai_message(messages)

    if last_message is None:
        return {
            "messages": [
                AIMessage(
                    name="reviewer",
                    content="검토할 직전 에이전트 응답이 없어 supervisor로 복귀합니다.",
                )
            ],
            "next_agent": "supervisor",
        }

    decision: ReviewerDecision = await build_reviewer_chain().ainvoke(
        [
            SystemMessage(content=REVIEWER_SYSTEM_PROMPT),
            HumanMessage(content=str(last_message.content or "")),
        ]
    )

    if decision.is_passed:
        return {
            "messages": [
                AIMessage(
                    name="reviewer",
                    content=decision.feedback,
                )
            ],
            "retry_count": _reset_retry_count(),
            "next_agent": "supervisor",
        }

    retry_count = _increment_retry_count(state)
    if retry_count > MAX_RETRIES:
        return {
            "messages": [
                AIMessage(
                    name="reviewer",
                    content="현재 분석에 어려움을 겪고 있습니다. 잠시 후 다시 질문해주세요.",
                )
            ],
            "retry_count": _reset_retry_count(),
            "next_agent": "supervisor",
        }

    return {
        "messages": [
            HumanMessage(
                content=f"Reviewer Feedback: {decision.feedback} - 주의: 위 피드백을 반영하여 처음부터 다시 작성하세요.",
            )
        ],
        "retry_count": retry_count,
        "next_agent": last_message.name,
    }


def _route_from_supervisor(state: OrchestratorState) -> SupervisorRoute:
    next_agent = str(state.get("next_agent") or "FINISH").strip()
    if next_agent in {"rag_agent", "quant_agent", "ops_agent", "FINISH"}:
        return next_agent  # type: ignore[return-value]
    return "FINISH"


def _route_from_reviewer(state: OrchestratorState) -> str:
    next_agent = str(state.get("next_agent") or "supervisor").strip()
    if next_agent in {"supervisor", "rag_agent", "quant_agent"}:
        return next_agent
    return "supervisor"


def build_chat_graph():
    graph = StateGraph(OrchestratorState)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("rag_agent", rag_agent_node)
    graph.add_node("quant_agent", quant_agent_node)
    graph.add_node("ops_agent", ops_agent_node)
    graph.add_node("reviewer", reviewer_node)

    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges(
        "supervisor",
        _route_from_supervisor,
        {
            "rag_agent": "rag_agent",
            "quant_agent": "quant_agent",
            "ops_agent": "ops_agent",
            "FINISH": END,
        },
    )
    graph.add_edge("rag_agent", "reviewer")
    graph.add_edge("quant_agent", "reviewer")
    graph.add_edge("ops_agent", "supervisor")
    return graph.compile()


chat_orchestrator_graph = build_chat_graph()


async def run_chat_stream(
    session_id: str,
    user_message: str,
    db: AsyncSession,
) -> AsyncGenerator[dict[str, str], None]:
    normalized_session_id = str(session_id or "").strip()
    normalized_user_message = str(user_message or "").strip()

    if not normalized_session_id:
        raise ValueError("session_id 는 비어 있을 수 없습니다.")
    if not normalized_user_message:
        raise ValueError("user_message 는 비어 있을 수 없습니다.")

    history_rows = await get_recent_chat_messages(db, normalized_session_id, limit=20)
    working_memory_messages = _restore_working_memory_messages(history_rows)

    await save_chat_message(
        db=db,
        session_id=normalized_session_id,
        role="user",
        content=normalized_user_message,
        agent_name=None,
        is_tool_call=False,
    )

    input_messages = [
        *working_memory_messages,
        HumanMessage(content=normalized_user_message),
    ]

    final_answer_saved = False

    async for event in chat_orchestrator_graph.astream_events(
        {
            "session_id": normalized_session_id,
            "messages": input_messages,
            "next_agent": "",
        },
        version="v2",
    ):
        event_name = str(event.get("event") or "")
        agent_name = _resolve_graph_agent_name(event)
        event_data = event.get("data") or {}

        if event_name == "on_chain_start" and agent_name is not None:
            yield {
                "type": "agent_start",
                "agent_name": agent_name,
                "content": "",
            }
            continue

        if event_name == "on_chain_end" and agent_name is not None:
            yield {
                "type": "agent_end",
                "agent_name": agent_name,
                "content": _extract_agent_message_content(event_data.get("output")),
            }
            continue

        if event_name == "on_tool_end":
            tool_name = str(event.get("name") or "tool")
            tool_output = event_data.get("output")
            tool_content = _stringify_tool_result(tool_output)

            await save_chat_message(
                db=db,
                session_id=normalized_session_id,
                role="tool",
                content=tool_content,
                agent_name=tool_name,
                is_tool_call=True,
            )

            approval_request_content = _extract_approval_request_content(tool_output)
            if approval_request_content is not None:
                yield {
                    "type": "approval_request",
                    "agent_name": "ops_agent",
                    "content": approval_request_content,
                }
                continue

            yield {
                "type": "tool_call",
                "agent_name": tool_name,
                "content": tool_content,
            }
            continue

        if event_name == "on_chain_end" and str(event.get("name") or "") == "LangGraph" and not final_answer_saved:
            output_state = event_data.get("output")
            if isinstance(output_state, dict):
                final_message = _extract_last_ai_message(output_state.get("messages"))
                if final_message is None:
                    continue

                final_content = str(final_message.content or "")
                final_agent_name = str(final_message.name or "supervisor")

                await save_chat_message(
                    db=db,
                    session_id=normalized_session_id,
                    role="assistant",
                    content=final_content,
                    agent_name=final_agent_name,
                    is_tool_call=False,
                )

                final_answer_saved = True
                yield {
                    "type": "final_answer",
                    "agent_name": final_agent_name,
                    "content": final_content,
                }
