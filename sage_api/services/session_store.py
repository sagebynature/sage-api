from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis

from sage.models import Message
from sage_api.models.schemas import SessionData


class RedisSessionStore:
    def __init__(self, redis_url: str = None, redis_client=None, session_ttl: int = 3600) -> None:
        if redis_client is not None:
            self._redis = redis_client
        else:
            if redis_url is None:
                raise ValueError("Either redis_url or redis_client must be provided")
            self._redis = aioredis.from_url(redis_url, decode_responses=True)
        self._session_ttl = session_ttl

    def _key(self, session_id: str) -> str:
        return f"session:{session_id}"

    async def create(self, session_id: str, agent_name: str, metadata: dict[str, Any]) -> SessionData:
        now = datetime.now(timezone.utc)
        session_data = SessionData(
            session_id=session_id,
            agent_name=agent_name,
            conversation_history=[],
            created_at=now,
            last_active_at=now,
            metadata=metadata,
        )
        await self.update(session_id, session_data)
        return session_data

    async def get(self, session_id: str) -> SessionData | None:
        raw = await self._redis.get(self._key(session_id))
        if raw is None:
            return None
        return SessionData.model_validate_json(raw)

    async def update(self, session_id: str, session_data: SessionData) -> None:
        key = self._key(session_id)
        await self._redis.set(key, session_data.model_dump_json())
        await self._redis.expire(key, self._session_ttl)

    async def delete(self, session_id: str) -> bool:
        deleted_count = await self._redis.delete(self._key(session_id))
        return deleted_count > 0

    async def exists(self, session_id: str) -> bool:
        return bool(await self._redis.exists(self._key(session_id)))

    async def touch(self, session_id: str) -> None:
        await self._redis.expire(self._key(session_id), self._session_ttl)

    async def save_history(self, session_id: str, messages: list[Message]) -> None:
        session_data = await self.get(session_id)
        if session_data is None:
            raise ValueError(f"Session '{session_id}' not found")

        session_data.conversation_history = json.loads(json.dumps([message.model_dump() for message in messages]))
        session_data.last_active_at = datetime.now(timezone.utc)
        await self.update(session_id, session_data)

    async def load_history(self, session_id: str) -> list[Message]:
        session_data = await self.get(session_id)
        if session_data is None:
            return []
        return [Message.model_validate(item) for item in session_data.conversation_history]

    async def close(self) -> None:
        await self._redis.aclose()
