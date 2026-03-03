from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncGenerator

from fastapi import HTTPException
from sage import Agent

from sage_api import telemetry
from sage_api.models.schemas import MessageResponse, SessionData, SessionInfo
from sage_api.services.agent_registry import AgentRegistry
from sage_api.services.session_store import RedisSessionStore


class SessionManager:
    def __init__(
        self,
        registry: AgentRegistry,
        store: RedisSessionStore,
        request_timeout: int = 120,
    ) -> None:
        self._registry = registry
        self._store = store
        self._request_timeout = request_timeout
        self._instances: dict[str, Agent] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def create_session(self, agent_name: str, metadata: dict | None = None) -> SessionInfo:
        if self._registry.get_template(agent_name) is None:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")

        session_id = str(uuid.uuid4())
        session_data = await self._store.create(session_id, agent_name, metadata or {})
        self._instances[session_id] = self._registry.create_instance(agent_name)
        self._locks[session_id] = asyncio.Lock()
        telemetry.record_session_created(agent_name)
        return self._to_session_info(session_data)

    async def send_message(self, session_id: str, message: str) -> MessageResponse:
        session_data = await self._store.get(session_id)
        if session_data is None:
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

        lock = self._locks.setdefault(session_id, asyncio.Lock())
        if lock.locked():
            raise HTTPException(status_code=409, detail="Concurrent request to same session")
        await lock.acquire()
        try:
            latest_session_data = await self._store.get(session_id)
            if latest_session_data is None:
                raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

            agent = self._get_or_recover_instance(session_id, latest_session_data)
            agent._conversation_history = latest_session_data.to_messages()

            _t0 = time.monotonic()
            try:
                response = await asyncio.wait_for(agent.run(message), timeout=self._request_timeout)
            except asyncio.TimeoutError as exc:
                raise HTTPException(status_code=504, detail="Request timed out") from exc
            finally:
                telemetry.record_message(latest_session_data.agent_name, "sync", time.monotonic() - _t0)

            await self._store.save_history(session_id, agent._conversation_history)
            return MessageResponse(session_id=session_id, message=response)
        finally:
            lock.release()

    async def stream_message(self, session_id: str, message: str) -> AsyncGenerator[str, None]:
        session_data = await self._store.get(session_id)
        if session_data is None:
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

        lock = self._locks.setdefault(session_id, asyncio.Lock())
        if lock.locked():
            raise HTTPException(status_code=409, detail="Concurrent request to same session")
        await lock.acquire()
        try:
            latest_session_data = await self._store.get(session_id)
            if latest_session_data is None:
                raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

            agent = self._get_or_recover_instance(session_id, latest_session_data)
            agent._conversation_history = latest_session_data.to_messages()

            _t0 = time.monotonic()
            try:
                async with asyncio.timeout(self._request_timeout):
                    async for chunk in agent.stream(message):
                        yield chunk
            except TimeoutError as exc:
                raise HTTPException(status_code=504, detail="Request timed out") from exc
            finally:
                telemetry.record_message(latest_session_data.agent_name, "stream", time.monotonic() - _t0)

            await self._store.save_history(session_id, agent._conversation_history)
        finally:
            lock.release()

    async def get_session(self, session_id: str) -> SessionInfo | None:
        session_data = await self._store.get(session_id)
        if session_data is None:
            return None
        return self._to_session_info(session_data)

    async def delete_session(self, session_id: str) -> bool:
        instance = self._instances.pop(session_id, None)
        self._locks.pop(session_id, None)

        if instance is not None:
            await instance.close()

        deleted = await self._store.delete(session_id)
        if deleted:
            telemetry.record_session_deleted()
        return deleted

    async def close_all(self) -> None:
        """Close all active agent instances during shutdown."""
        for session_id, agent in list(self._instances.items()):
            try:
                await agent.close()
            except Exception:
                pass
        self._instances.clear()
        self._locks.clear()

    def _get_or_recover_instance(self, session_id: str, session_data: SessionData) -> Agent:
        instance = self._instances.get(session_id)
        if instance is not None:
            return instance

        recovered = self._registry.create_instance(session_data.agent_name)
        recovered._conversation_history = session_data.to_messages()
        self._instances[session_id] = recovered
        return recovered

    @staticmethod
    def _to_session_info(session_data: SessionData) -> SessionInfo:
        return SessionInfo(
            session_id=session_data.session_id,
            agent_name=session_data.agent_name,
            created_at=session_data.created_at,
            last_active_at=session_data.last_active_at,
            message_count=len(session_data.conversation_history),
        )
