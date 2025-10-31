from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Dict, Iterable, Optional, Set

from backend.agents.guardrails import safe_envelope
from backend.agents.openevent_agent import OpenEventAgent

logger = logging.getLogger(__name__)

ENGINE_TOOL_ALLOWLIST: Dict[str, Set[str]] = {
    "2": {
        "tool_suggest_dates",
        "tool_parse_date_intent",
    },
    "3": {
        "tool_room_status_on_date",
        "tool_capacity_check",
    },
    "4": {
        "tool_build_offer_draft",
        "tool_list_products",
        "tool_list_catering",
        "tool_add_product_to_offer",
        "tool_remove_product_from_offer",
    },
    "5": {
        "tool_site_visit_slots",
    },
    "7": {
        "tool_follow_up_suggest",
    },
}

CLIENT_STOP_AT_TOOLS: Set[str] = {
    "client_confirm_offer",
    "client_change_offer",
    "client_discard_offer",
    "client_see_catering",
    "client_see_products",
}


class ToolExecutionError(RuntimeError):
    """Raised when a tool invocation violates the step-aware allowlist."""

    def __init__(self, tool_name: str, step: Optional[int]) -> None:
        self.tool_name = tool_name
        self.step = step
        allowed = StepToolPolicy.allowed_tools_for(step)
        detail = {
            "tool": tool_name,
            "step": step,
            "allowed_tools": sorted(allowed),
        }
        super().__init__(json.dumps(detail))
        self.detail = detail


@dataclass
class StepToolPolicy:
    current_step: Optional[int]
    allowed_tools: Set[str] = field(init=False)

    def __post_init__(self) -> None:
        self.allowed_tools = self.allowed_tools_for(self.current_step)

    @staticmethod
    def allowed_tools_for(step: Optional[int]) -> Set[str]:
        if step is None:
            return set().union(*ENGINE_TOOL_ALLOWLIST.values()) if ENGINE_TOOL_ALLOWLIST else set()
        return set(ENGINE_TOOL_ALLOWLIST.get(str(step), set()))

    def ensure_allowed(self, tool_name: str) -> None:
        if tool_name in CLIENT_STOP_AT_TOOLS:
            # Client tools are surfaced via StopAtTools; they are not executed automatically.
            return
        if tool_name not in self.allowed_tools:
            raise ToolExecutionError(tool_name, self.current_step)


@dataclass
class StepAwareAgent:
    thread_id: str
    state: Dict[str, Any]
    policy: StepToolPolicy


def build_agent(state: Dict[str, Any]) -> StepAwareAgent:
    current_step = state.get("current_step")
    policy = StepToolPolicy(current_step)
    return StepAwareAgent(
        thread_id=state.get("thread_id") or "unknown-thread",
        state=state,
        policy=policy,
    )


async def _fallback_stream(thread_id: str, message: Dict[str, Any], state: Dict[str, Any]) -> AsyncGenerator[str, None]:
    """
    Deterministic fallback path when the Agents SDK is unavailable.

    We reuse the existing OpenEventAgent facade so behaviour mirrors the
    traditional workflow-backed path. The output is wrapped in SSE format.
    """

    agent = OpenEventAgent()
    session = agent.create_session(thread_id)
    envelope = agent.run(session, message)
    payload = safe_envelope(envelope)
    yield f"data: {json.dumps(payload)}\n\n"


async def run_streamed(thread_id: str, message: Dict[str, Any], state: Dict[str, Any]) -> AsyncGenerator[str, None]:
    """
    Stream the assistant response for ChatKit.

    When the Agents SDK or network access is not available the function falls
    back to the deterministic workflow pipeline so tests can run offline.
    """

    policy = StepToolPolicy(state.get("current_step"))
    agent_mode = os.getenv("AGENT_MODE", "workflow").lower()

    if agent_mode != "openai":
        async for chunk in _fallback_stream(thread_id, message, state):
            yield chunk
        return

    try:  # pragma: no cover - SDK path exercised only in integration runs
        from openai import OpenAI  # type: ignore

        client = OpenAI()
        allowed_tools = [{"type": "function", "function": {"name": tool}} for tool in policy.allowed_tools]
        stop_tools = [{"type": "function", "function": {"name": tool}} for tool in CLIENT_STOP_AT_TOOLS]
        system_instructions = (
            "You are OpenEvent, an empathetic venue assistant. Follow Workflow v3 strictly.\n"
            f"Current step: {state.get('current_step') or 'unknown'}; "
            f"Status: {state.get('status') or 'Lead'}.\n"
            "Only invoke engine tools that appear in the provided allowlist. "
            "Client tools (confirm/change/discard offer, see catering/products) must use StopAtTools."
        )

        response = client.responses.stream.create(  # type: ignore[attr-defined]
            model=os.getenv("OPENAI_AGENT_MODEL", "gpt-4.1-mini"),
            input=[
                {"role": "system", "content": system_instructions},
                {"role": "user", "content": message["body"]},
            ],
            tools=allowed_tools + stop_tools,
            tool_choice={"type": "auto"},
        )

        async for event in response:
            if event.type == "response.error":
                raise RuntimeError(event.error)  # type: ignore[attr-defined]
            if event.type != "response.output_text.delta":  # type: ignore[attr-defined]
                continue
            text = event.delta  # type: ignore[attr-defined]
            yield f"data: {json.dumps({'delta': text})}\n\n"

        final = response.get_final_response()
        yield f"data: {json.dumps({'assistant_text': final.output_text})}\n\n"
    except Exception as exc:
        logger.warning("Agents SDK unavailable or failed (%s); using fallback workflow path.", exc)
        async for chunk in _fallback_stream(thread_id, message, state):
            yield chunk


def validate_tool_call(tool_name: str, state: Dict[str, Any]) -> None:
    """
    Helper exposed for tests so we can assert allowlist enforcement without
    needing to exercise the Agents SDK.
    """

    policy = StepToolPolicy(state.get("current_step"))
    policy.ensure_allowed(tool_name)

