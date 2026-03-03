"""Session lifecycle endpoints for Sage API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from sage_api.middleware.auth import verify_api_key
from sage_api.models.schemas import CreateSessionRequest, SessionInfo
from sage_api.services.session_manager import SessionManager

router = APIRouter(
    prefix="/v1",
    tags=["sessions"],
    dependencies=[Depends(verify_api_key)],
)


def get_session_manager(request: Request) -> SessionManager:
    """Retrieve the SessionManager from app state."""
    return request.app.state.session_manager


@router.post(
    "/agents/{name}/sessions",
    response_model=SessionInfo,
    status_code=201,
)
async def create_session(
    name: str,
    body: CreateSessionRequest = CreateSessionRequest(),
    session_manager: SessionManager = Depends(get_session_manager),
) -> SessionInfo:
    """Create a new session for the given agent."""
    return await session_manager.create_session(agent_name=name, metadata=body.metadata)


@router.get(
    "/agents/{name}/sessions",
    response_model=SessionInfo,
)
async def get_session(
    name: str,
    session_id: str = Query(..., description="Session ID to retrieve"),
    session_manager: SessionManager = Depends(get_session_manager),
) -> SessionInfo:
    """Get session info by session_id."""
    session = await session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    if session.agent_name != name:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    return session


@router.delete(
    "/agents/{name}/sessions",
    status_code=204,
)
async def delete_session(
    name: str,
    session_id: str = Query(..., description="Session ID to delete"),
    session_manager: SessionManager = Depends(get_session_manager),
) -> Response:
    """Delete a session by session_id."""
    existing = await session_manager.get_session(session_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    if existing.agent_name != name:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    deleted = await session_manager.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    return Response(status_code=204)
