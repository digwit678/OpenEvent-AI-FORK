from __future__ import annotations

import os
from datetime import datetime
import json
from typing import Any, AsyncGenerator, Dict, List, Optional

import secrets
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import logging

from api.utils.errors import raise_safe_error

logger = logging.getLogger(__name__)

from chatkit import server as chatkit_server
from agents.openevent_agent import OpenEventAgent

router = APIRouter(prefix="/api/agent", tags=["agent"])

# Upload size limit: 10MB default, configurable via environment
MAX_UPLOAD_SIZE_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", "10"))
MAX_UPLOAD_SIZE = MAX_UPLOAD_SIZE_MB * 1024 * 1024

# Allowed content types for uploads (empty = allow all)
ALLOWED_UPLOAD_TYPES = {
    "image/jpeg", "image/png", "image/gif", "image/webp",
    "application/pdf",
    "text/plain", "text/csv",
    "application/json",
}


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
        raise_safe_error(501, "run agent (not implemented)", exc, logger)
    except RuntimeError as exc:
        raise_safe_error(502, "run agent", exc, logger)
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


def _validate_content_type(content_type: Optional[str]) -> None:
    """Raise HTTPException if content type is not in the allowlist."""
    if not ALLOWED_UPLOAD_TYPES:
        return  # Empty allowlist = permit all
    if not content_type or content_type.split(";")[0].strip() not in ALLOWED_UPLOAD_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type: {content_type}. Allowed: {', '.join(sorted(ALLOWED_UPLOAD_TYPES))}",
        )


try:  # pragma: no cover - optional dependency for multipart uploads
    from fastapi import UploadFile

    @router.post("/chatkit/upload")
    async def chatkit_upload(file: UploadFile) -> Dict[str, Any]:
        """Direct upload handler when python-multipart is available.

        Enforces:
        - Content-type allowlist (ALLOWED_UPLOAD_TYPES)
        - Size limit (MAX_UPLOAD_SIZE_MB) via streaming read
        """
        # Validate content type early
        _validate_content_type(file.content_type)

        # Stream content in chunks to enforce size limit without loading huge files
        chunks: list[bytes] = []
        total_size = 0
        chunk_size = 64 * 1024  # 64KB chunks

        while True:
            chunk = await file.read(chunk_size)
            if not chunk:
                break
            total_size += len(chunk)
            if total_size > MAX_UPLOAD_SIZE:
                raise HTTPException(
                    status_code=413,
                    detail=f"File too large. Maximum size: {MAX_UPLOAD_SIZE_MB}MB",
                )
            chunks.append(chunk)

        content = b"".join(chunks)
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
        """Fallback upload handler accepting JSON payloads when multipart is unavailable.

        Enforces:
        - Content-type allowlist (ALLOWED_UPLOAD_TYPES) on declared type
        - Size limit (MAX_UPLOAD_SIZE_MB) on declared size
        """
        payload = await request.json()
        content_type = payload.get("content_type", "application/octet-stream")
        declared_size = payload.get("size", 0)

        # Validate content type
        _validate_content_type(content_type)

        # Validate declared size
        if declared_size > MAX_UPLOAD_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"File too large. Maximum size: {MAX_UPLOAD_SIZE_MB}MB",
            )

        metadata = {
            "file_name": payload.get("file_name", "unknown.bin"),
            "content_type": content_type,
            "size": declared_size,
        }
        return {"upload": metadata}
