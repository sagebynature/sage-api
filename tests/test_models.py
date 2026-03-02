"""Tests for Pydantic models and schemas."""

from datetime import datetime, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from sage.config import ContextConfig, ModelParams, Permission
from sage.models import Message, ToolCall

from sage_api.models.schemas import (
    AgentDetail,
    AgentSummary,
    CreateSessionRequest,
    ErrorResponse,
    MessageResponse,
    SendMessageRequest,
    SessionData,
    SessionInfo,
    SkillInfo,
    SSEEvent,
    SubagentDetail,
)


class TestSendMessageRequest:
    """Test SendMessageRequest validation and serialization."""

    def test_basic_message_request(self):
        """Test creating a basic message request."""
        req = SendMessageRequest(message="Hello, world!")
        assert req.message == "Hello, world!"
        assert req.metadata is None

    def test_message_request_with_metadata(self):
        """Test message request with metadata."""
        meta = {"user_id": "123", "source": "web"}
        req = SendMessageRequest(message="Hi", metadata=meta)
        assert req.message == "Hi"
        assert req.metadata == meta

    def test_message_request_missing_required_field(self):
        """Test that message field is required."""
        with pytest.raises(ValidationError):
            SendMessageRequest()

    def test_message_request_json_serialization(self):
        """Test JSON serialization."""
        req = SendMessageRequest(message="test", metadata={"key": "value"})
        json_str = req.model_dump_json()
        req2 = SendMessageRequest.model_validate_json(json_str)
        assert req2.message == "test"
        assert req2.metadata == {"key": "value"}


class TestCreateSessionRequest:
    """Test CreateSessionRequest validation."""

    def test_create_session_no_metadata(self):
        """Test creating session without metadata."""
        req = CreateSessionRequest()
        assert req.metadata is None

    def test_create_session_with_metadata(self):
        """Test creating session with metadata."""
        meta = {"agent_config_path": "/path/to/agent.md"}
        req = CreateSessionRequest(metadata=meta)
        assert req.metadata == meta

    def test_create_session_json_roundtrip(self):
        """Test JSON serialization roundtrip."""
        req = CreateSessionRequest(metadata={"key": "value"})
        json_str = req.model_dump_json()
        req2 = CreateSessionRequest.model_validate_json(json_str)
        assert req2.metadata == {"key": "value"}


class TestSessionInfo:
    """Test SessionInfo model."""

    def test_session_info(self):
        """Test creating session info."""
        now = datetime.now(timezone.utc)
        info = SessionInfo(
            session_id="sess-123",
            agent_name="assistant",
            created_at=now,
            last_active_at=now,
            message_count=5,
        )
        assert info.session_id == "sess-123"
        assert info.agent_name == "assistant"
        assert info.created_at == now
        assert info.last_active_at == now
        assert info.message_count == 5

    def test_session_info_json_serialization(self):
        """Test JSON serialization with datetimes."""
        now = datetime.now(timezone.utc)
        info = SessionInfo(
            session_id="sess-456",
            agent_name="test-agent",
            created_at=now,
            last_active_at=now,
            message_count=10,
        )
        json_str = info.model_dump_json()
        info2 = SessionInfo.model_validate_json(json_str)
        assert info2.session_id == "sess-456"
        assert info2.agent_name == "test-agent"
        assert info2.message_count == 10


class TestMessageResponse:
    """Test MessageResponse model."""

    def test_message_response_basic(self):
        """Test basic message response."""
        resp = MessageResponse(
            session_id="sess-123",
            message="Hello!",
        )
        assert resp.session_id == "sess-123"
        assert resp.message == "Hello!"
        assert resp.metadata is None

    def test_message_response_with_metadata(self):
        """Test message response with metadata."""
        meta = {"timestamp": "2025-01-01T00:00:00Z"}
        resp = MessageResponse(
            session_id="sess-123",
            message="Hello!",
            metadata=meta,
        )
        assert resp.metadata == meta

    def test_message_response_json_serialization(self):
        """Test JSON serialization."""
        resp = MessageResponse(
            session_id="sess-789",
            message="test message",
            metadata={"key": "value"},
        )
        json_str = resp.model_dump_json()
        resp2 = MessageResponse.model_validate_json(json_str)
        assert resp2.session_id == "sess-789"
        assert resp2.message == "test message"
        assert resp2.metadata == {"key": "value"}


class TestSSEEvent:
    """Test SSEEvent model."""

    def test_sse_event_basic(self):
        """Test basic SSE event."""
        event = SSEEvent(event="message", data="Hello")
        assert event.event == "message"
        assert event.data == "Hello"

    def test_sse_event_done(self):
        """Test done event."""
        event = SSEEvent(event="done", data="")
        assert event.event == "done"

    def test_sse_event_json_serialization(self):
        """Test JSON serialization."""
        event = SSEEvent(event="chunk", data="some text")
        json_str = event.model_dump_json()
        event2 = SSEEvent.model_validate_json(json_str)
        assert event2.event == "chunk"
        assert event2.data == "some text"


class TestErrorResponse:
    """Test ErrorResponse model."""

    def test_error_response_basic(self):
        """Test basic error response."""
        resp = ErrorResponse(
            error="NotFound",
            status_code=404,
        )
        assert resp.error == "NotFound"
        assert resp.detail is None
        assert resp.status_code == 404

    def test_error_response_with_detail(self):
        """Test error response with detail."""
        resp = ErrorResponse(
            error="ValidationError",
            detail="Invalid message format",
            status_code=400,
        )
        assert resp.error == "ValidationError"
        assert resp.detail == "Invalid message format"
        assert resp.status_code == 400

    def test_error_response_json_serialization(self):
        """Test JSON serialization."""
        resp = ErrorResponse(
            error="ServerError",
            detail="Internal server error",
            status_code=500,
        )
        json_str = resp.model_dump_json()
        resp2 = ErrorResponse.model_validate_json(json_str)
        assert resp2.error == "ServerError"
        assert resp2.detail == "Internal server error"
        assert resp2.status_code == 500


class TestSessionData:
    """Test SessionData model and message conversion."""

    def test_session_data_basic(self):
        """Test creating session data."""
        now = datetime.now(timezone.utc)
        data = SessionData(
            session_id="sess-123",
            agent_name="assistant",
            conversation_history=[],
            created_at=now,
            last_active_at=now,
            metadata={},
        )
        assert data.session_id == "sess-123"
        assert data.agent_name == "assistant"
        assert data.conversation_history == []
        assert data.metadata == {}

    def test_session_data_with_history(self):
        """Test session data with conversation history."""
        now = datetime.now(timezone.utc)
        history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        data = SessionData(
            session_id="sess-456",
            agent_name="test-agent",
            conversation_history=history,
            created_at=now,
            last_active_at=now,
            metadata={"source": "web"},
        )
        assert len(data.conversation_history) == 2
        assert data.conversation_history[0]["role"] == "user"
        assert data.metadata == {"source": "web"}

    def test_from_messages_single_message(self):
        """Test converting a single Message to SessionData."""
        msg = Message(role="user", content="Hello")
        session = SessionData.from_messages(
            session_id="sess-789",
            agent_name="assistant",
            messages=[msg],
            metadata={},
        )
        assert session.session_id == "sess-789"
        assert session.agent_name == "assistant"
        assert len(session.conversation_history) == 1
        assert session.conversation_history[0]["role"] == "user"
        assert session.conversation_history[0]["content"] == "Hello"

    def test_from_messages_multiple_messages(self):
        """Test converting multiple Messages to SessionData."""
        messages = [
            Message(role="user", content="Hello"),
            Message(role="assistant", content="Hi!"),
            Message(role="user", content="How are you?"),
        ]
        session = SessionData.from_messages(
            session_id="sess-123",
            agent_name="test-agent",
            messages=messages,
            metadata={"user": "john"},
        )
        assert len(session.conversation_history) == 3
        assert session.conversation_history[0]["role"] == "user"
        assert session.conversation_history[1]["role"] == "assistant"
        assert session.conversation_history[2]["content"] == "How are you?"

    def test_from_messages_with_tool_calls(self):
        """Test converting messages with tool calls."""
        tool_call = ToolCall(id="tc-1", name="search", arguments={"query": "test"})
        msg = Message(role="assistant", content=None, tool_calls=[tool_call])
        session = SessionData.from_messages(
            session_id="sess-tc",
            agent_name="assistant",
            messages=[msg],
            metadata={},
        )
        assert len(session.conversation_history) == 1
        history_msg = session.conversation_history[0]
        assert history_msg["role"] == "assistant"
        assert history_msg["tool_calls"] is not None
        assert len(history_msg["tool_calls"]) == 1
        assert history_msg["tool_calls"][0]["name"] == "search"

    def test_to_messages_single_message(self):
        """Test converting SessionData back to Message objects."""
        now = datetime.now(timezone.utc)
        session = SessionData(
            session_id="sess-456",
            agent_name="assistant",
            conversation_history=[
                {"role": "user", "content": "Hello"},
            ],
            created_at=now,
            last_active_at=now,
            metadata={},
        )
        messages = session.to_messages()
        assert len(messages) == 1
        assert messages[0].role == "user"
        assert messages[0].content == "Hello"

    def test_to_messages_multiple_messages(self):
        """Test converting SessionData with multiple messages back to Message objects."""
        now = datetime.now(timezone.utc)
        session = SessionData(
            session_id="sess-789",
            agent_name="assistant",
            conversation_history=[
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi!"},
                {"role": "user", "content": "How are you?"},
            ],
            created_at=now,
            last_active_at=now,
            metadata={},
        )
        messages = session.to_messages()
        assert len(messages) == 3
        assert messages[0].role == "user"
        assert messages[0].content == "Hello"
        assert messages[1].role == "assistant"
        assert messages[1].content == "Hi!"
        assert messages[2].role == "user"

    def test_to_messages_with_tool_calls(self):
        """Test converting messages with tool calls back to Message objects."""
        now = datetime.now(timezone.utc)
        session = SessionData(
            session_id="sess-tc",
            agent_name="assistant",
            conversation_history=[
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "tc-1",
                            "name": "search",
                            "arguments": {"query": "python"},
                        }
                    ],
                    "tool_call_id": None,
                }
            ],
            created_at=now,
            last_active_at=now,
            metadata={},
        )
        messages = session.to_messages()
        assert len(messages) == 1
        assert messages[0].role == "assistant"
        assert messages[0].tool_calls is not None
        assert len(messages[0].tool_calls) == 1
        assert messages[0].tool_calls[0].name == "search"

    def test_roundtrip_messages_simple(self):
        """Test roundtrip: Message → SessionData → Message (simple)."""
        original_messages = [
            Message(role="user", content="Hello"),
            Message(role="assistant", content="Hi there!"),
        ]
        # Convert to SessionData
        session = SessionData.from_messages(
            session_id="sess-rt",
            agent_name="assistant",
            messages=original_messages,
            metadata={},
        )
        # Convert back to Messages
        reconstructed = session.to_messages()

        # Verify equivalence
        assert len(reconstructed) == len(original_messages)
        for orig, recon in zip(original_messages, reconstructed):
            assert recon.role == orig.role
            assert recon.content == orig.content
            assert recon.tool_calls == orig.tool_calls

    def test_roundtrip_messages_with_tool_calls(self):
        """Test roundtrip: Message with tool calls → SessionData → Message."""
        tool_call = ToolCall(id="tc-1", name="calculate", arguments={"expr": "2+2"})
        original_messages = [
            Message(role="user", content="What is 2+2?"),
            Message(role="assistant", content=None, tool_calls=[tool_call]),
            Message(role="tool", content="4", tool_call_id="tc-1"),
        ]
        # Convert to SessionData
        session = SessionData.from_messages(
            session_id="sess-tc-rt",
            agent_name="assistant",
            messages=original_messages,
            metadata={},
        )
        # Convert back to Messages
        reconstructed = session.to_messages()

        # Verify
        assert len(reconstructed) == 3
        assert reconstructed[0].role == "user"
        assert reconstructed[0].content == "What is 2+2?"
        assert reconstructed[1].role == "assistant"
        assert reconstructed[1].tool_calls is not None
        assert reconstructed[1].tool_calls[0].name == "calculate"
        assert reconstructed[2].role == "tool"
        assert reconstructed[2].content == "4"
        assert reconstructed[2].tool_call_id == "tc-1"

    def test_session_data_json_serialization(self):
        """Test JSON serialization of SessionData."""
        now = datetime.now(timezone.utc)
        session = SessionData(
            session_id="sess-json",
            agent_name="assistant",
            conversation_history=[
                {"role": "user", "content": "Test"},
            ],
            created_at=now,
            last_active_at=now,
            metadata={"key": "value"},
        )
        json_str = session.model_dump_json()
        session2 = SessionData.model_validate_json(json_str)
        assert session2.session_id == "sess-json"
        assert len(session2.conversation_history) == 1
        assert session2.metadata == {"key": "value"}

    def test_from_messages_with_none_content(self):
        """Test from_messages with None content (e.g., tool calls message)."""
        tool_call = ToolCall(id="tc-1", name="search", arguments={})
        msg = Message(role="assistant", content=None, tool_calls=[tool_call])
        session = SessionData.from_messages(
            session_id="sess-none",
            agent_name="assistant",
            messages=[msg],
            metadata={},
        )
        assert session.conversation_history[0]["content"] is None
        assert session.conversation_history[0]["tool_calls"] is not None


class TestSkillInfo:
    def test_minimal(self):
        info = SkillInfo(name="clean-code")
        assert info.name == "clean-code"
        assert info.description is None

    def test_with_description(self):
        info = SkillInfo(name="clean-code", description="Code quality skill")
        assert info.description == "Code quality skill"


class TestSubagentDetail:
    def test_full_fields(self):
        detail = SubagentDetail(
            name="explorer",
            description="Explores code",
            model="gpt-4o",
            max_turns=10,
            skills=["clean-code"],
            model_params=ModelParams(temperature=0.0, max_tokens=4096),
            permission=Permission(read="allow", edit="deny"),
        )
        assert detail.name == "explorer"
        assert detail.model_params.temperature == 0.0
        assert detail.permission.read == "allow"
        assert detail.skills == ["clean-code"]

    def test_null_permission(self):
        detail = SubagentDetail(
            name="helper",
            model="gpt-4o-mini",
            max_turns=5,
            skills=[],
            model_params=ModelParams(),
            permission=None,
        )
        assert detail.permission is None


class TestAgentSummary:
    def test_full_fields(self):
        summary = AgentSummary(
            name="coder",
            description="A coding agent",
            model="claude-sonnet-4-6",
            skills_count=3,
            subagents_count=2,
        )
        assert summary.name == "coder"
        assert summary.model == "claude-sonnet-4-6"
        assert summary.skills_count == 3
        assert summary.subagents_count == 2

    def test_null_description(self):
        summary = AgentSummary(
            name="helper",
            model="gpt-4o",
            skills_count=0,
            subagents_count=0,
        )
        assert summary.description is None


class TestAgentDetail:
    def test_full_fields(self):
        detail = AgentDetail(
            name="coder",
            description="A coding agent",
            model="claude-sonnet-4-6",
            max_turns=25,
            max_depth=3,
            model_params=ModelParams(temperature=0.0, max_tokens=8192),
            permission=Permission(read="allow", edit="allow"),
            skills=[SkillInfo(name="clean-code", description="Code quality")],
            subagents=[
                SubagentDetail(
                    name="explorer",
                    description="Explores code",
                    model="gpt-4o",
                    max_turns=10,
                    skills=[],
                    model_params=ModelParams(),
                    permission=Permission(read="allow"),
                ),
            ],
            context=ContextConfig(compaction_threshold=0.75, reserve_tokens=4096),
        )
        assert detail.name == "coder"
        assert len(detail.subagents) == 1
        assert detail.subagents[0].name == "explorer"
        assert len(detail.skills) == 1
        assert detail.context.reserve_tokens == 4096

    def test_minimal(self):
        detail = AgentDetail(
            name="simple",
            model="gpt-4o-mini",
            max_turns=10,
            max_depth=3,
            model_params=ModelParams(),
            permission=None,
            skills=[],
            subagents=[],
            context=None,
        )
        assert detail.permission is None
        assert detail.context is None
        assert detail.subagents == []

    def test_json_round_trip(self):
        detail = AgentDetail(
            name="rt",
            model="gpt-4o",
            max_turns=10,
            max_depth=3,
            model_params=ModelParams(temperature=0.5),
            permission=Permission(read="allow"),
            skills=[SkillInfo(name="s1")],
            subagents=[],
            context=None,
        )
        json_str = detail.model_dump_json()
        restored = AgentDetail.model_validate_json(json_str)
        assert restored.name == "rt"
        assert restored.model_params.temperature == 0.5
