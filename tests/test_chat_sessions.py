import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import sqlite

from app.api.routes import chat as chat_routes
from app.db import repository
from app.models.domain import AIChatMessage as AIChatMessageORM
from app.models.domain import ChatSessionSurface


def test_create_chat_session_defaults_to_ai_banker_surface(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def fake_create_chat_session_record(_db: object, surface: ChatSessionSurface) -> SimpleNamespace:
        captured["surface"] = surface
        return SimpleNamespace(session_id="session-ai")

    monkeypatch.setattr(chat_routes, "create_chat_session_record", fake_create_chat_session_record)

    response = asyncio.run(chat_routes.create_chat_session(payload=None, db=object()))

    assert response.session_id == "session-ai"
    assert captured["surface"] == ChatSessionSurface.AI_BANKER


def test_list_chat_sessions_uses_requested_surface(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    created_at = datetime(2026, 4, 24, tzinfo=timezone.utc)

    async def fake_get_chat_sessions(_db: object, surface: ChatSessionSurface) -> list[dict[str, object]]:
        captured["surface"] = surface
        return [
            {
                "session_id": "portfolio-session",
                "created_at": created_at,
                "content_preview": "portfolio auto briefing",
            }
        ]

    monkeypatch.setattr(chat_routes, "get_chat_sessions", fake_get_chat_sessions)

    response = asyncio.run(
        chat_routes.list_chat_sessions(
            surface=ChatSessionSurface.PORTFOLIO,
            db=object(),
        )
    )

    assert captured["surface"] == ChatSessionSurface.PORTFOLIO
    assert [item.session_id for item in response] == ["portfolio-session"]


def test_delete_chat_session_returns_404_for_missing_session(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_chat_session_record(_db: object, _session_id: str) -> None:
        return None

    monkeypatch.setattr(chat_routes, "get_chat_session_record", fake_get_chat_session_record)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(chat_routes.delete_chat_session("missing-session", db=object()))

    assert exc_info.value.status_code == 404


def test_get_chat_session_messages_returns_404_for_missing_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get_chat_session_record(_db: object, _session_id: str) -> None:
        return None

    monkeypatch.setattr(chat_routes, "get_chat_session_record", fake_get_chat_session_record)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(chat_routes.get_chat_session_messages("missing-session", db=object()))

    assert exc_info.value.status_code == 404


def test_delete_chat_session_record_deletes_parent_session_row() -> None:
    db = AsyncMock()

    asyncio.run(repository.delete_chat_session_record(db, "session-alpha"))

    statement = db.execute.await_args.args[0]
    compiled_sql = str(
        statement.compile(
            dialect=sqlite.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "DELETE FROM chat_sessions" in compiled_sql
    assert "session-alpha" in compiled_sql
    db.commit.assert_awaited_once()


def test_get_chat_sessions_filters_by_surface() -> None:
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(all=lambda: [])

    asyncio.run(repository.get_chat_sessions(db, ChatSessionSurface.PORTFOLIO))

    statement = db.execute.await_args.args[0]
    compiled_sql = str(
        statement.compile(
            dialect=sqlite.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "FROM chat_sessions" in compiled_sql
    assert "chat_sessions.surface = 'portfolio'" in compiled_sql


def test_ai_chat_message_session_id_uses_cascade_foreign_key() -> None:
    foreign_key = next(iter(AIChatMessageORM.__table__.c.session_id.foreign_keys))

    assert foreign_key.target_fullname == "chat_sessions.session_id"
    assert foreign_key.ondelete == "CASCADE"
