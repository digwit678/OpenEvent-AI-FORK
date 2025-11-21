"""
Offer workflow group.

Provides typed node classes used for composing and delivering offers before
handing off to the event confirmation flow.
"""

from __future__ import annotations

from typing import Any, Dict


class WorkflowNode:
    """Minimal base node with a common run signature."""

    role: str = "node"

    def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:  # pragma: no cover - interface
        raise NotImplementedError("Subclasses must implement run()")


class OpenEventAction(WorkflowNode):
    """Manager/system action node (light-blue)."""

    role = "OpenEvent Action"


class LLMNode(WorkflowNode):
    """Generative reasoning node (green/orange)."""

    role = "LLM"


class TriggerNode(WorkflowNode):
    """Client-trigger node (purple)."""

    role = "Trigger"

    def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return payload


class ClientReply(TriggerNode):
    """Shim for the client reply trigger feeding the AnalyzeClientReply node."""

    role = "Client Reply Trigger"


__all__ = [
    "WorkflowNode",
    "OpenEventAction",
    "LLMNode",
    "TriggerNode",
    "ClientReply",
]
