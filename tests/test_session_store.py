from __future__ import annotations

from datetime import UTC

import fakeredis.aioredis
import pytest

from sage.models import Message, ToolCall
from sage_api.models.schemas import SessionData
from sage_api.services.session_store import RedisSessionStore


@pytest.fixture
async def store() -> RedisSessionStore:
    fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    session_store = RedisSessionStore.__new__(RedisSessionStore)
    session_store._redis = fake_redis
    session_store._session_ttl = 1800
    yield session_store
    await fake_redis.aclose()


async def test_create_returns_session_data(store: RedisSessionStore) -> None:
    session_data = await store.create("session-1", "helper", {"source": "test"})

    assert isinstance(session_data, SessionData)
    assert session_data.session_id == "session-1"
    assert session_data.agent_name == "helper"
    assert session_data.metadata == {"source": "test"}
    assert session_data.conversation_history == []
    assert session_data.created_at.tzinfo is UTC
    assert session_data.last_active_at.tzinfo is UTC


async def test_get_returns_none_for_missing(store: RedisSessionStore) -> None:
    assert await store.get("missing") is None


async def test_create_get_roundtrip(store: RedisSessionStore) -> None:
    created = await store.create("session-2", "assistant", {"k": "v"})
    loaded = await store.get("session-2")

    assert loaded == created


async def test_update_persists_changes(store: RedisSessionStore) -> None:
    await store.create("session-3", "assistant", {})
    session_data = await store.get("session-3")
    assert session_data is not None

    session_data.metadata["updated"] = True
    session_data.conversation_history = [{"role": "user", "content": "hello"}]

    await store.update("session-3", session_data)
    updated = await store.get("session-3")

    assert updated is not None
    assert updated.metadata == {"updated": True}
    assert updated.conversation_history == [{"role": "user", "content": "hello"}]


async def test_delete_returns_true_if_existed(store: RedisSessionStore) -> None:
    await store.create("session-4", "assistant", {})

    assert await store.delete("session-4") is True
    assert await store.get("session-4") is None


async def test_delete_returns_false_if_missing(store: RedisSessionStore) -> None:
    assert await store.delete("missing-session") is False


async def test_save_and_load_history_roundtrip(store: RedisSessionStore) -> None:
    await store.create("session-5", "assistant", {})
    messages = [
        Message(role="user", content="Hi"),
        Message(
            role="assistant",
            content=None,
            tool_calls=[ToolCall(id="tool-1", name="search", arguments={"query": "weather"})],
        ),
        Message(role="tool", content="72 and sunny", tool_call_id="tool-1"),
    ]

    await store.save_history("session-5", messages)
    loaded_messages = await store.load_history("session-5")

    assert loaded_messages == messages


async def test_ttl_is_set_on_create(store: RedisSessionStore) -> None:
    await store.create("session-6", "assistant", {})

    ttl = await store._redis.ttl(store._key("session-6"))
    assert ttl > 0
    assert ttl <= store._session_ttl


async def test_exists_and_touch_refreshes_ttl(store: RedisSessionStore) -> None:
    await store.create("session-7", "assistant", {})
    assert await store.exists("session-7") is True

    await store._redis.expire(store._key("session-7"), 1)
    short_ttl = await store._redis.ttl(store._key("session-7"))
    assert short_ttl <= 1

    await store.touch("session-7")
    refreshed_ttl = await store._redis.ttl(store._key("session-7"))
    assert refreshed_ttl > 1
    assert refreshed_ttl <= store._session_ttl
