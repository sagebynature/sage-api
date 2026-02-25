"""Message sending endpoints for Sage API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from sage_api.middleware.auth import verify_api_key
from sage_api.models.schemas import MessageResponse, SendMessageRequest
from sage_api.services.session_manager import SessionManager

router = APIRouter(
    prefix="/v1",
    tags=["messages"],
    dependencies=[Depends(verify_api_key)],
)


def get_session_manager(request: Request) -> SessionManager:
    """Retrieve the SessionManager from app state."""
    return request.app.state.session_manager


@router.post(
    "/agents/{name}/sessions/{session_id}/messages",
    response_model=MessageResponse,
)
async def send_message(
    name: str,
    session_id: str,
    body: SendMessageRequest,
    session_manager: SessionManager = Depends(get_session_manager),
) -> MessageResponse:
    """Send a message to an agent session and get a response."""
    session = await session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.agent_name != name:
        raise HTTPException(status_code=404, detail="Session not found")
    # HTTPException (409, 504) from session_manager bubbles up as-is
    return await session_manager.send_message(
        session_id=session_id,
        message=body.message,
    )


@router.post(
    "/agents/{name}/sessions/{session_id}/messages/stream",
)
async def stream_messages(
    name: str,
    session_id: str,
    body: SendMessageRequest,
    session_manager: SessionManager = Depends(get_session_manager),
) -> EventSourceResponse:
    """Stream agent response via Server-Sent Events."""
    session = await session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.agent_name != name:
        raise HTTPException(status_code=404, detail="Session not found")

    async def event_generator():
        async for chunk in session_manager.stream_message(
            session_id=session_id,
            message=body.message,
        ):
            yield {"event": "message", "data": chunk}
        yield {"event": "done", "data": "{}"}

    return EventSourceResponse(event_generator())
