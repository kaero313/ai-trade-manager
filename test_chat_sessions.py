# ruff: noqa: E402

import asyncio
import sys
from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import status
from sqlalchemy.dialects import sqlite

stub_scheduler_module = ModuleType("app.core.scheduler")


async def _stub_reload_scheduler_jobs() -> None:
    return None


stub_scheduler_module.reload_scheduler_jobs = _stub_reload_scheduler_jobs
sys.modules.setdefault("app.core.scheduler", stub_scheduler_module)

stub_orchestrator_module = ModuleType("app.services.chat.orchestrator")


async def _stub_run_chat_stream(*_args: object, **_kwargs: object):
    if False:
        yield {}


stub_orchestrator_module.run_chat_stream = _stub_run_chat_stream
sys.modules.setdefault("app.services.chat.orchestrator", stub_orchestrator_module)

from app.api.routes import chat as chat_routes
from app.db import repository


def test_delete_chat_session_messages_deletes_all_rows_for_session() -> None:
    db = AsyncMock()

    asyncio.run(repository.delete_chat_session_messages(db, "session-alpha"))

    statement = db.execute.await_args.args[0]
    compiled_sql = str(
        statement.compile(
            dialect=sqlite.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "DELETE FROM ai_chat_messages" in compiled_sql
    assert "session-alpha" in compiled_sql
    assert "is_tool_call" not in compiled_sql
    db.commit.assert_awaited_once()


def test_delete_chat_session_endpoint_keeps_session_queries_in_sync(monkeypatch) -> None:
    created_at = datetime(2026, 4, 23, tzinfo=timezone.utc)
    state = [
        {
            "id": 1,
            "session_id": "session-a",
            "role": "user",
            "content": "첫 번째 질문",
            "agent_name": None,
            "is_tool_call": False,
            "created_at": created_at,
        },
        {
            "id": 2,
            "session_id": "session-a",
            "role": "tool",
            "content": "도구 호출 로그",
            "agent_name": "rag_agent",
            "is_tool_call": True,
            "created_at": created_at,
        },
        {
            "id": 3,
            "session_id": "session-b",
            "role": "assistant",
            "content": "다른 세션 응답",
            "agent_name": "assistant",
            "is_tool_call": False,
            "created_at": created_at,
        },
    ]

    async def fake_delete_chat_session_messages(_db: object, session_id: str) -> None:
        state[:] = [row for row in state if row["session_id"] != session_id]

    async def fake_get_chat_sessions(_db: object) -> list[dict[str, object]]:
        latest_by_session: dict[str, dict[str, object]] = {}
        for row in state:
            if row["is_tool_call"]:
                continue

            current = latest_by_session.get(row["session_id"])
            if current is None or (row["created_at"], row["id"]) > (
                current["created_at"],
                current["id"],
            ):
                latest_by_session[row["session_id"]] = row

        return [
            {
                "session_id": row["session_id"],
                "created_at": row["created_at"],
                "content_preview": str(row["content"])[:120],
            }
            for row in sorted(
                latest_by_session.values(),
                key=lambda item: (item["created_at"], item["session_id"]),
                reverse=True,
            )
        ]

    async def fake_get_recent_chat_messages(
        _db: object,
        session_id: str,
        limit: int = 50,
    ) -> list[SimpleNamespace]:
        visible_rows = [
            SimpleNamespace(**row)
            for row in state
            if row["session_id"] == session_id and not row["is_tool_call"]
        ]
        visible_rows.sort(key=lambda item: (item.created_at, item.id))
        return visible_rows[-limit:]

    monkeypatch.setattr(chat_routes, "delete_chat_session_messages", fake_delete_chat_session_messages)
    monkeypatch.setattr(chat_routes, "get_chat_sessions", fake_get_chat_sessions)
    monkeypatch.setattr(chat_routes, "get_recent_chat_messages", fake_get_recent_chat_messages)

    response = asyncio.run(chat_routes.delete_chat_session("session-a", db=object()))
    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert all(row["session_id"] != "session-a" for row in state)

    sessions = asyncio.run(chat_routes.list_chat_sessions(db=object()))
    assert [item.session_id for item in sessions] == ["session-b"]

    messages = asyncio.run(chat_routes.get_chat_session_messages("session-a", db=object()))
    assert messages == []

    missing_response = asyncio.run(chat_routes.delete_chat_session("missing-session", db=object()))
    assert missing_response.status_code == status.HTTP_204_NO_CONTENT
