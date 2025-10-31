from __future__ import annotations

from datetime import datetime
import json
from typing import Any, AsyncGenerator, Dict, List, Optional

import secrets
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.chatkit import server as chatkit_server
from backend.agents.openevent_agent import OpenEventAgent

router = APIRouter(prefix="/api/agent", tags=["agent"])


class AgentReplyRequest(BaseModel):
    thread_id: str = Field(..., description="Conversation thread identifier.")
    message: str = Field(..., description="Client message body.")
    subject: Optional[str] = Field(None, description="Optional subject line when available.")
    from_email: Optional[str] = Field(None, description="Client email address.")
    from_name: Optional[str] = Field(None, description="Client display name.")
    attachments: Optional[List[Dict[str, Any]]] = None


@router.post("/reply")
async def agent_reply(request: AgentReplyRequest) -> Dict[str, Any]:
    """
    Entry point for the Agents SDK orchestration.

    When the Agents SDK has not yet been configured the endpoint falls back to
    the deterministic workflow so existing functionality continues to work.
    """

    agent = OpenEventAgent()
    session = agent.create_session(request.thread_id)
    message_payload = {
        "msg_id": f"agent-{datetime.utcnow().timestamp()}",
        "from_name": request.from_name or "Client (Agent)",
        "from_email": request.from_email or "unknown@example.com",
        "subject": request.subject or "Client message",
        "ts": datetime.utcnow().isoformat() + "Z",
        "body": request.message,
    }
    try:
        result = agent.run(session, message_payload)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return result


class ChatKitMessage(BaseModel):
    thread_id: str
    text: str
    attachments: Optional[List[Dict[str, Any]]] = None
    from_email: Optional[str] = None
    from_name: Optional[str] = None
    subject: Optional[str] = None
    current_step: Optional[int] = Field(
        None, description="Optional hint about the current workflow step for tool gating."
    )
    status: Optional[str] = Field(None, description="Optional event status hint.")


class ChatKitSessionRequest(BaseModel):
    thread_id: Optional[str] = None
    device_id: Optional[str] = None


class ChatKitSessionResponse(BaseModel):
    client_secret: str
    thread_id: Optional[str] = None


@router.post("/chatkit/session", response_model=ChatKitSessionResponse)
async def chatkit_session(_: ChatKitSessionRequest) -> ChatKitSessionResponse:
    """
    Minimal session endpoint for custom ChatKit frontends.

    ChatKit expects a short-lived client_secret so we mint a random token per request.
    The token is not persisted because the workflow backend authenticates on thread_id.
    """

    secret = secrets.token_urlsafe(32)
    return ChatKitSessionResponse(client_secret=secret)


@router.post("/chatkit/respond")
async def chatkit_respond(request: ChatKitMessage) -> StreamingResponse:
    return await chatkit_server.respond(request)


try:  # pragma: no cover - optional dependency for multipart uploads
    from fastapi import UploadFile

    @router.post("/chatkit/upload")
    async def chatkit_upload(file: UploadFile) -> Dict[str, Any]:
        """Direct upload handler when python-multipart is available."""

        content = await file.read()
        return {
            "upload": {
                "file_name": file.filename,
                "content_type": file.content_type,
                "size": len(content),
            }
        }

except RuntimeError:  # pragma: no cover - python-multipart missing

    @router.post("/chatkit/upload")
    async def chatkit_upload_json(request: Request) -> Dict[str, Any]:
        """Fallback upload handler accepting JSON payloads when multipart is unavailable."""

        payload = await request.json()
        metadata = {
            "file_name": payload.get("file_name", "unknown.bin"),
            "content_type": payload.get("content_type", "application/octet-stream"),
            "size": payload.get("size", 0),
        }
        return {"upload": metadata}
