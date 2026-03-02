"""Pydantic models and schemas for the Sage API."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict

from sage.config import ContextConfig, ModelParams, Permission
from sage.models import Message


class SendMessageRequest(BaseModel):
    """Request body for sending a message to an agent."""

    model_config = ConfigDict(from_attributes=True)

    message: str
    metadata: dict[str, Any] | None = None


class CreateSessionRequest(BaseModel):
    """Request body for creating a new session."""

    model_config = ConfigDict(from_attributes=True)

    metadata: dict[str, Any] | None = None


class SkillInfo(BaseModel):
    """Metadata for a skill (excludes content)."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    description: str | None = None


class SubagentDetail(BaseModel):
    """Full detail for a subagent."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    description: str | None = None
    model: str
    max_turns: int
    skills: list[str]
    model_params: ModelParams
    permission: Permission | None = None


class AgentSummary(BaseModel):
    """Summary information about an agent (for list endpoints)."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    description: str | None = None
    model: str
    skills_count: int
    subagents_count: int


class AgentDetail(BaseModel):
    """Comprehensive agent detail (for detail endpoints)."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    description: str | None = None
    model: str
    max_turns: int
    max_depth: int
    model_params: ModelParams
    permission: Permission | None = None
    skills: list[SkillInfo]
    subagents: list[SubagentDetail]
    context: ContextConfig | None = None


# Backward-compat alias — removed in Task 4 after all consumers migrate.
AgentInfo = AgentSummary


class SessionInfo(BaseModel):
    """Information about a session."""

    model_config = ConfigDict(from_attributes=True)

    session_id: str
    agent_name: str
    created_at: datetime
    last_active_at: datetime
    message_count: int


class MessageResponse(BaseModel):
    """Response containing a message from the agent."""

    model_config = ConfigDict(from_attributes=True)

    session_id: str
    message: str
    metadata: dict[str, Any] | None = None


class SSEEvent(BaseModel):
    """Server-Sent Event for streaming responses."""

    model_config = ConfigDict(from_attributes=True)

    event: str
    data: str


class ErrorResponse(BaseModel):
    """Error response with details."""

    model_config = ConfigDict(from_attributes=True)

    error: str
    detail: str | None = None
    status_code: int


class SessionData(BaseModel):
    """Session data stored in Redis-like backend."""

    model_config = ConfigDict(from_attributes=True)

    session_id: str
    agent_name: str
    conversation_history: list[dict[str, Any]]
    created_at: datetime
    last_active_at: datetime
    metadata: dict[str, Any]

    @classmethod
    def from_messages(
        cls,
        session_id: str,
        agent_name: str,
        messages: list[Message],
        metadata: dict[str, Any] | None = None,
    ) -> SessionData:
        """Convert SDK Message objects to SessionData.

        Args:
            session_id: The session identifier.
            agent_name: The agent name.
            messages: List of sage.models.Message objects.
            metadata: Optional metadata dictionary.

        Returns:
            SessionData instance with serialized messages.
        """
        now = datetime.now(timezone.utc)
        conversation_history = [msg.model_dump() for msg in messages]
        return cls(
            session_id=session_id,
            agent_name=agent_name,
            conversation_history=conversation_history,
            created_at=now,
            last_active_at=now,
            metadata=metadata or {},
        )

    def to_messages(self) -> list[Message]:
        """Reconstruct SDK Message objects from stored history.

        Returns:
            List of sage.models.Message objects.
        """
        messages = []
        for msg_dict in self.conversation_history:
            messages.append(Message.model_validate(msg_dict))
        return messages
