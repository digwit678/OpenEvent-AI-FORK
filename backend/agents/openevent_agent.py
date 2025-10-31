from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from backend.workflow_email import process_msg as workflow_process_msg
from backend.agents.guardrails import safe_envelope

logger = logging.getLogger(__name__)


class OpenEventAgent:
    """
    Facade that prefers the OpenAI Agents SDK when available, falling back to
    the deterministic workflow router when the SDK or network access is not
    present.  This keeps the codebase ready for agent orchestration without
    breaking the existing deterministic behaviour relied upon by tests.
    """

    _SYSTEM_PROMPT = (
        "You are OpenEvent, an empathetic event-planning assistant. "
        "Follow Workflow v3 strictly: Step 2 (date) → Step 3 (room) → Step 4 "
        "(offer) → Step 5 (negotiation) → Step 6 (transition) → Step 7 "
        "(confirmation), honouring detours via caller_step and hash checks. "
        "Always reply with JSON in the schema {assistant_text, requires_hil, "
        "action, payload}.  Preserve provided facts verbatim (menus, dates, "
        "prices).  Never mutate the database directly—call the provided tools."
    )

    def __init__(self) -> None:
        self._sdk_available = False
        self._client = None
        self._agent_id: Optional[str] = None
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._initialise_sdk()

    def _initialise_sdk(self) -> None:
        try:  # pragma: no cover - optional dependency probe
            from openai import OpenAI  # type: ignore

            self._client = OpenAI()
            self._sdk_available = True
            logger.info("OpenAI Agents SDK detected. Agent orchestration enabled.")
        except Exception as exc:  # pragma: no cover - optional dependency probe
            self._client = None
            self._sdk_available = False
            logger.info("Agents SDK unavailable (%s); using workflow fallback.", exc)

    def _ensure_agent(self) -> Optional[str]:
        if not self._sdk_available or not self._client:
            return None
        if self._agent_id:
            return self._agent_id
        try:
            response = self._client.agents.create(  # type: ignore[attr-defined]
                model="gpt-4.1-mini",
                instructions=self._SYSTEM_PROMPT,
                tools=[
                    {"type": "function", "function": {"name": "tool_suggest_dates"}},
                    {"type": "function", "function": {"name": "tool_persist_confirmed_date"}},
                    {"type": "function", "function": {"name": "tool_evaluate_rooms"}},
                    {"type": "function", "function": {"name": "tool_room_status"}},
                    {"type": "function", "function": {"name": "tool_compose_offer"}},
                    {"type": "function", "function": {"name": "tool_persist_offer"}},
                    {"type": "function", "function": {"name": "tool_send_offer"}},
                    {"type": "function", "function": {"name": "tool_negotiate_offer"}},
                    {"type": "function", "function": {"name": "tool_transition_sync"}},
                    {"type": "function", "function": {"name": "tool_classify_confirmation"}},
                ],
            )
            self._agent_id = response.id  # type: ignore[attr-defined]
            return self._agent_id
        except Exception as exc:  # pragma: no cover - network guarded
            logger.warning("Failed to create Agents SDK agent: %s", exc)
            self._agent_id = None
            self._sdk_available = False
            return None

    def _ensure_session(self, thread_id: str) -> Dict[str, Any]:
        session = self._sessions.get(thread_id)
        if session:
            return session
        session = {
            "thread_id": thread_id,
            "state": {
                "event_id": None,
                "current_step": None,
                "caller_step": None,
                "requirements_hash": None,
                "room_eval_hash": None,
                "offer_hash": None,
                "status": None,
            },
        }
        self._sessions[thread_id] = session
        return session

    def create_session(self, thread_id: str) -> Dict[str, Any]:
        """Public helper for API endpoints to initialise a session."""

        return self._ensure_session(thread_id)

    def run(self, session: Dict[str, Any], message: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a turn via the Agents SDK when possible, otherwise fall back to
        the deterministic workflow router.
        """

        if self._sdk_available and self._ensure_agent():
            try:
                return self._run_via_agent(session, message)
            except Exception as exc:  # pragma: no cover - network guarded
                logger.warning("Agents SDK execution failed (%s); falling back.", exc)

        return self._run_fallback(message)

    def _run_via_agent(self, session: Dict[str, Any], message: Dict[str, Any]) -> Dict[str, Any]:
        assert self._client is not None  # for type checkers
        agent_id = self._ensure_agent()
        if not agent_id:
            raise RuntimeError("Agent ID unavailable after initialisation.")

        thread_id = session["thread_id"]
        try:
            run = self._client.agents.runs.create(  # type: ignore[attr-defined]
                agent_id=agent_id,
                thread_id=thread_id,
                input=message["body"],
                session_state=session.get("state", {}),
            )
            envelope = run.output[0].content  # type: ignore[attr-defined]
            validated = safe_envelope(envelope if isinstance(envelope, dict) else {})
            session["state"] = run.session_state  # type: ignore[attr-defined]
            return validated
        except Exception as exc:  # pragma: no cover - network guarded
            raise RuntimeError(f"Agents SDK run failed: {exc}") from exc

    def _run_fallback(self, message: Dict[str, Any]) -> Dict[str, Any]:
        wf_res = workflow_process_msg(message)
        assistant_text = self._compose_reply(wf_res)
        requires_hil = True
        action = wf_res.get("action") or "workflow_response"
        payload = {k: v for k, v in wf_res.items() if k not in {"draft_messages", "summary"}}
        payload.setdefault("draft_messages", wf_res.get("draft_messages") or [])
        envelope = {
            "assistant_text": assistant_text,
            "requires_hil": requires_hil,
            "action": action,
            "payload": payload,
        }
        return safe_envelope(envelope)

    @staticmethod
    def _compose_reply(workflow_result: Dict[str, Any]) -> str:
        drafts = workflow_result.get("draft_messages") or []
        bodies = [d.get("body") for d in drafts if d.get("body")]
        if bodies:
            return "\n\n".join(str(body) for body in bodies)
        if workflow_result.get("summary"):
            return str(workflow_result["summary"])
        if workflow_result.get("reason"):
            return str(workflow_result["reason"])
        return "Thanks for the update — I'll keep you posted."
