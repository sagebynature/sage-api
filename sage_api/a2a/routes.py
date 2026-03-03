from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError
from sse_starlette.sse import EventSourceResponse

from sage_api.logging import get_logger
from sage_api.middleware.auth import verify_api_key
from sage_api.services.session_manager import SessionManager

logger = get_logger(__name__)

router = APIRouter(
    prefix="",
    tags=["a2a"],
    dependencies=[Depends(verify_api_key)],
)


class JsonRpcRequest(BaseModel):
    jsonrpc: str
    id: str | int
    method: str
    params: dict[str, Any]


class MessagePart(BaseModel):
    kind: str
    text: str | None = None


class A2AMessage(BaseModel):
    messageId: str | None = None
    role: str
    parts: list[MessagePart]


class MessageParams(BaseModel):
    message: A2AMessage
    sessionId: str | None = None


def get_session_manager(request: Request) -> SessionManager:
    return request.app.state.session_manager


def _jsonrpc_error(request_id: str | int, code: int, message: str) -> JSONResponse:
    return JSONResponse(
        content={
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }
    )


def _extract_text_input(message: A2AMessage) -> str:
    return "".join(part.text for part in message.parts if part.kind == "text" and part.text is not None)


async def _resolve_session_id(
    request: Request,
    session_manager: SessionManager,
    session_id: str | None,
) -> str:
    if session_id is not None:
        return session_id

    registry = request.app.state.registry
    agents = registry.list_agents()
    if not agents:
        raise HTTPException(status_code=503, detail="No agents registered")
    agent_name = agents[0].name
    session_info = await session_manager.create_session(agent_name=agent_name)
    return session_info.session_id


async def _stream_events(stream, first_chunk: str | None, request_id: str | int, session_id: str):
    yield {
        "event": "message",
        "data": json.dumps({"kind": "status-update", "status": {"state": "working"}}),
    }
    try:
        if first_chunk is not None:
            yield {
                "event": "message",
                "data": json.dumps({"kind": "artifact-update", "artifact": {"parts": [{"text": first_chunk}]}}),
            }
        async for chunk in stream:
            yield {
                "event": "message",
                "data": json.dumps({"kind": "artifact-update", "artifact": {"parts": [{"text": chunk}]}}),
            }
    except HTTPException as exc:
        yield {
            "event": "error",
            "data": json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": exc.status_code, "message": str(exc.detail)},
                }
            ),
        }
    yield {"event": "done", "data": json.dumps({"kind": "status-update", "status": {"state": "completed"}})}


@router.post("/a2a", response_model=None)
async def handle_a2a_request(
    body: JsonRpcRequest,
    request: Request,
    session_manager: SessionManager = Depends(get_session_manager),
) -> JSONResponse | EventSourceResponse:
    if body.jsonrpc != "2.0":
        return _jsonrpc_error(body.id, -32600, "Invalid Request")

    if body.method not in {"message/send", "message/stream"}:
        return _jsonrpc_error(body.id, -32601, "Method not found")

    try:
        params = MessageParams.model_validate(body.params)
        text_input = _extract_text_input(params.message)
        session_id = await _resolve_session_id(request, session_manager, params.sessionId)
    except HTTPException as exc:
        return _jsonrpc_error(body.id, exc.status_code, str(exc.detail))
    except ValidationError:
        return _jsonrpc_error(body.id, -32602, "Invalid params")
    except Exception:
        logger.exception("a2a_param_parsing_failed", method=body.method)
        return _jsonrpc_error(body.id, -32602, "Invalid params")

    if body.method == "message/send":
        try:
            response = await session_manager.send_message(session_id, text_input)
        except HTTPException as exc:
            return _jsonrpc_error(body.id, exc.status_code, str(exc.detail))

        return JSONResponse(
            content={
                "jsonrpc": "2.0",
                "id": body.id,
                "result": {
                    "id": session_id,
                    "status": {"state": "completed"},
                    "artifacts": [{"parts": [{"text": response.message}]}],
                },
            }
        )

    stream = session_manager.stream_message(session_id, text_input)
    try:
        first_chunk = await anext(stream)
    except StopAsyncIteration:
        first_chunk = None
    except HTTPException as exc:
        return _jsonrpc_error(body.id, exc.status_code, str(exc.detail))

    return EventSourceResponse(_stream_events(stream, first_chunk, body.id, session_id))
