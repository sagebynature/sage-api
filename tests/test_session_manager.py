from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from sage_api.models.schemas import SessionData
from sage_api.services.agent_registry import AgentRegistry
from sage_api.services.session_manager import SessionManager
from sage_api.services.session_store import RedisSessionStore


def build_session_data(
    session_id: str = "session-1",
    agent_name: str = "assistant",
    conversation_history: list[dict] | None = None,
) -> SessionData:
    now = datetime.now(UTC)
    return SessionData(
        session_id=session_id,
        agent_name=agent_name,
        conversation_history=conversation_history or [],
        created_at=now,
        last_active_at=now,
        metadata={},
    )


def build_manager() -> tuple[SessionManager, MagicMock, MagicMock, MagicMock]:
    registry = MagicMock(spec=AgentRegistry)
    store = MagicMock(spec=RedisSessionStore)

    agent = MagicMock()
    agent.run = AsyncMock(return_value="Hello back!")
    agent.stream = MagicMock()
    agent.close = AsyncMock()
    agent._conversation_history = []

    registry.get_template.return_value = MagicMock(name="assistant-template")
    registry.create_instance.return_value = agent

    manager = SessionManager(registry=registry, store=store, request_timeout=1)
    return manager, registry, store, agent


async def async_gen(*chunks: str):
    for chunk in chunks:
        yield chunk


async def test_create_session_happy_path() -> None:
    manager, registry, store, _agent = build_manager()

    async def create_side_effect(session_id: str, agent_name: str, metadata: dict) -> SessionData:
        return build_session_data(
            session_id=session_id,
            agent_name=agent_name,
            conversation_history=[],
        )

    store.create = AsyncMock(side_effect=create_side_effect)

    session = await manager.create_session("assistant", metadata={"source": "test"})

    uuid.UUID(session.session_id)
    assert session.agent_name == "assistant"
    assert session.message_count == 0
    store.create.assert_awaited_once()
    registry.create_instance.assert_called_once_with("assistant")


async def test_create_session_unknown_agent_raises_404() -> None:
    manager, registry, _store, _agent = build_manager()
    registry.get_template.return_value = None

    with pytest.raises(HTTPException, match="not found") as exc:
        await manager.create_session("missing")

    assert exc.value.status_code == 404


async def test_send_message_happy_path() -> None:
    manager, _registry, store, agent = build_manager()
    session_data = build_session_data(session_id="session-1")
    store.get = AsyncMock(side_effect=[session_data, session_data])
    store.save_history = AsyncMock()
    agent._conversation_history = [{"role": "user", "content": "hi"}]

    response = await manager.send_message("session-1", "hello")

    assert response.session_id == "session-1"
    assert response.message == "Hello back!"
    agent.run.assert_awaited_once_with("hello")
    store.save_history.assert_awaited_once_with("session-1", agent._conversation_history)


async def test_send_message_session_not_found_raises_404() -> None:
    manager, _registry, store, _agent = build_manager()
    store.get = AsyncMock(return_value=None)

    with pytest.raises(HTTPException, match="not found") as exc:
        await manager.send_message("missing", "hello")

    assert exc.value.status_code == 404


async def test_send_message_concurrent_raises_409() -> None:
    manager, _registry, store, _agent = build_manager()
    session_data = build_session_data(session_id="session-1")
    store.get = AsyncMock(return_value=session_data)

    lock = asyncio.Lock()
    await lock.acquire()
    manager._locks["session-1"] = lock

    try:
        with pytest.raises(HTTPException, match="Concurrent request") as exc:
            await manager.send_message("session-1", "hello")
    finally:
        lock.release()

    assert exc.value.status_code == 409


async def test_session_recovery() -> None:
    manager, registry, store, _agent = build_manager()
    history = [{"role": "user", "content": "existing"}]
    session_data = build_session_data(session_id="session-1", conversation_history=history)
    recovered_agent = MagicMock()
    recovered_agent._conversation_history = []
    recovered_agent.run = AsyncMock(return_value="Recovered response")
    recovered_agent.close = AsyncMock()
    registry.create_instance.return_value = recovered_agent

    store.get = AsyncMock(side_effect=[session_data, session_data])
    store.save_history = AsyncMock()
    manager._instances.clear()

    response = await manager.send_message("session-1", "hello")

    assert response.message == "Recovered response"
    assert manager._instances["session-1"] is recovered_agent
    assert recovered_agent._conversation_history == session_data.to_messages()


async def test_delete_session_calls_agent_close() -> None:
    manager, _registry, store, agent = build_manager()
    store.delete = AsyncMock(return_value=True)
    manager._instances["session-1"] = agent
    manager._locks["session-1"] = asyncio.Lock()

    deleted = await manager.delete_session("session-1")

    assert deleted is True
    agent.close.assert_awaited_once()
    assert "session-1" not in manager._instances
    assert "session-1" not in manager._locks


async def test_send_message_timeout_raises_504() -> None:
    manager, _registry, store, agent = build_manager()
    session_data = build_session_data(session_id="session-1")
    store.get = AsyncMock(side_effect=[session_data, session_data])
    agent.run = AsyncMock(side_effect=asyncio.TimeoutError)

    with pytest.raises(HTTPException, match="timed out") as exc:
        await manager.send_message("session-1", "hello")

    assert exc.value.status_code == 504


async def test_stream_message_happy_path_saves_history() -> None:
    manager, _registry, store, agent = build_manager()
    session_data = build_session_data(session_id="session-1")
    store.get = AsyncMock(side_effect=[session_data, session_data])
    store.save_history = AsyncMock()
    agent.stream = MagicMock(return_value=async_gen("chunk1", "chunk2"))

    chunks = [chunk async for chunk in manager.stream_message("session-1", "hello")]

    assert chunks == ["chunk1", "chunk2"]
    store.save_history.assert_awaited_once_with("session-1", agent._conversation_history)


async def test_get_session_returns_session_info() -> None:
    manager, _registry, store, _agent = build_manager()
    session_data = build_session_data(
        session_id="session-1",
        conversation_history=[{"role": "user", "content": "hello"}],
    )
    store.get = AsyncMock(return_value=session_data)

    info = await manager.get_session("session-1")

    assert info is not None
    assert info.session_id == "session-1"
    assert info.message_count == 1
