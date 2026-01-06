"""
Multi-Variable Q&A Response Composer

Composes responses for multi-variable or hybrid Q&A based on conjunction analysis:
- Independent: Separate answer sections for each Q&A part
- And Combined: Single answer with merged conditions
- Or Union: Ranked results showing items matching ALL conditions first
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from workflows.common.prompts import append_footer
from workflows.common.types import GroupResult, WorkflowState
from workflows.qna.conjunction import (
    ConjunctionAnalysis,
    QnAPart,
    get_combined_conditions,
    get_union_conditions,
)

# Headers for multi-variable responses
MULTI_QNA_HEADER = "Multi-Variable Q&A Response"
INDEPENDENT_SECTION_HEADERS = {
    "rooms": "Room Availability",
    "menus": "Menu Options",
    "dates": "Available Dates",
    "products": "Products & Add-ons",
    "site_visit": "Site Visit Information",
    "policy": "Venue Policies",
}


@dataclass
class ComposedSection:
    """A single section of a multi-part response."""

    header: str
    body_markdown: str
    table_blocks: List[Dict[str, Any]] = field(default_factory=list)
    info_link: Optional[str] = None


@dataclass
class ComposedResponse:
    """Complete composed response with multiple sections."""

    sections: List[ComposedSection]
    relationship: str  # "independent" | "and_combined" | "or_union" | "single"
    workflow_section: Optional[ComposedSection] = None  # For hybrid responses

    @property
    def body_markdown(self) -> str:
        """Combine all sections into single markdown body."""
        parts: List[str] = []

        # Workflow section first (for hybrid)
        if self.workflow_section:
            parts.append(f"**{self.workflow_section.header}**")
            parts.append(self.workflow_section.body_markdown)
            parts.append("")  # Blank line separator

        # Q&A sections
        for section in self.sections:
            parts.append(f"**{section.header}:**")
            parts.append(section.body_markdown)
            if section.info_link:
                parts.append(f"\n[More details: {section.info_link}]")
            parts.append("")  # Blank line separator

        return "\n".join(parts).strip()

    @property
    def all_table_blocks(self) -> List[Dict[str, Any]]:
        """Collect table blocks from all sections."""
        blocks: List[Dict[str, Any]] = []
        for section in self.sections:
            blocks.extend(section.table_blocks)
        return blocks


def compose_multi_variable_response(
    conjunction: ConjunctionAnalysis,
    qna_results: Dict[str, Any],
    stored_requirements: Dict[str, Any],
    state: WorkflowState,
    workflow_result: Optional[GroupResult] = None,
) -> ComposedResponse:
    """
    Compose response based on conjunction relationship.

    Args:
        conjunction: Analysis result from conjunction.py
        qna_results: Results from Q&A engine for each part
        stored_requirements: Current event requirements (for context)
        state: Workflow state
        workflow_result: Optional result from workflow processing (for hybrid)

    Returns:
        ComposedResponse with appropriate sections
    """
    if not conjunction.parts:
        return ComposedResponse(sections=[], relationship="single")

    # Handle workflow part first (for hybrid)
    workflow_section = None
    if workflow_result:
        workflow_section = _build_workflow_section(workflow_result, state)

    # Build Q&A sections based on relationship
    if conjunction.relationship == "independent":
        sections = _compose_independent_sections(conjunction.parts, qna_results, state)
    elif conjunction.relationship == "and_combined":
        sections = _compose_combined_section(conjunction.parts, qna_results, state)
    elif conjunction.relationship == "or_union":
        sections = _compose_ranked_union_section(conjunction.parts, qna_results, state)
    else:
        # Single Q&A part
        sections = _compose_single_section(conjunction.parts, qna_results, state)

    return ComposedResponse(
        sections=sections,
        relationship=conjunction.relationship,
        workflow_section=workflow_section,
    )


def _compose_independent_sections(
    parts: List[QnAPart],
    qna_results: Dict[str, Any],
    state: WorkflowState,
) -> List[ComposedSection]:
    """
    Case A: Generate separate answer section for each independent Q&A part.
    """
    sections: List[ComposedSection] = []

    for part in parts:
        header = INDEPENDENT_SECTION_HEADERS.get(part.select, f"{part.select.title()} Information")
        result_key = f"{part.select}_{part.qna_type}"
        part_result = qna_results.get(result_key, {})

        body_markdown = _render_part_result(part, part_result)
        table_blocks = part_result.get("table_blocks", [])
        info_link = _get_info_link(part.select)

        sections.append(ComposedSection(
            header=header,
            body_markdown=body_markdown,
            table_blocks=table_blocks,
            info_link=info_link,
        ))

    return sections


def _compose_combined_section(
    parts: List[QnAPart],
    qna_results: Dict[str, Any],
    state: WorkflowState,
) -> List[ComposedSection]:
    """
    Case B: Single answer with combined conditions (AND logic).
    """
    # All parts have same select
    select = parts[0].select
    combined_conditions = get_combined_conditions(parts)

    # Build header describing the combined query
    header = _build_combined_header(select, combined_conditions)

    # Get combined result (should already be computed by engine)
    combined_result = qna_results.get("combined", {})
    body_markdown = _render_combined_result(select, combined_result, combined_conditions)
    table_blocks = combined_result.get("table_blocks", [])
    info_link = _get_info_link(select)

    return [ComposedSection(
        header=header,
        body_markdown=body_markdown,
        table_blocks=table_blocks,
        info_link=info_link,
    )]


def _compose_ranked_union_section(
    parts: List[QnAPart],
    qna_results: Dict[str, Any],
    state: WorkflowState,
) -> List[ComposedSection]:
    """
    Case C: Ranked results showing items matching ALL conditions first.
    """
    select = parts[0].select
    union_conditions = get_union_conditions(parts)

    header = f"{INDEPENDENT_SECTION_HEADERS.get(select, select.title())} by Features"

    # Get ranked result
    ranked_result = qna_results.get("ranked", {})
    body_markdown = _render_ranked_result(select, ranked_result, union_conditions)
    table_blocks = ranked_result.get("table_blocks", [])
    info_link = _get_info_link(select)

    return [ComposedSection(
        header=header,
        body_markdown=body_markdown,
        table_blocks=table_blocks,
        info_link=info_link,
    )]


def _compose_single_section(
    parts: List[QnAPart],
    qna_results: Dict[str, Any],
    state: WorkflowState,
) -> List[ComposedSection]:
    """
    Single Q&A part - simple rendering.
    """
    if not parts:
        return []

    part = parts[0]
    header = INDEPENDENT_SECTION_HEADERS.get(part.select, f"{part.select.title()} Information")
    result_key = f"{part.select}_{part.qna_type}"
    part_result = qna_results.get(result_key, qna_results)

    body_markdown = _render_part_result(part, part_result)
    table_blocks = part_result.get("table_blocks", [])
    info_link = _get_info_link(part.select)

    return [ComposedSection(
        header=header,
        body_markdown=body_markdown,
        table_blocks=table_blocks,
        info_link=info_link,
    )]


def _build_workflow_section(
    workflow_result: GroupResult,
    state: WorkflowState,
) -> ComposedSection:
    """
    Build section for workflow action part of hybrid response.
    """
    action = workflow_result.action
    payload = workflow_result.payload

    # Determine header based on action
    header_map = {
        "date_confirmed": "Date Confirmed",
        "room_selected": "Room Selected",
        "offer_sent": "Offer Sent",
        "detour_initiated": "Change Request Received",
        "hil_forwarded": "Forwarded to Manager",
    }
    header = header_map.get(action, "Update")

    # Get body from payload
    body_markdown = payload.get("confirmation_message", payload.get("body", ""))

    return ComposedSection(
        header=header,
        body_markdown=body_markdown,
    )


def _render_part_result(part: QnAPart, result: Dict[str, Any]) -> str:
    """
    Render a single Q&A part result to markdown.
    """
    if result.get("body_markdown"):
        return result["body_markdown"]

    # Fallback rendering
    items = result.get("items", [])
    if not items:
        return f"No {part.select} found matching your criteria."

    # Simple list rendering
    lines = []
    for item in items[:10]:  # Limit to 10 items
        name = item.get("name", item.get("room_name", item.get("id", "Item")))
        details = item.get("details", item.get("notes", ""))
        if details:
            lines.append(f"- **{name}**: {details}")
        else:
            lines.append(f"- {name}")

    return "\n".join(lines)


def _render_combined_result(
    select: str,
    result: Dict[str, Any],
    conditions: Dict[str, Any],
) -> str:
    """
    Render combined AND result.
    """
    if result.get("body_markdown"):
        return result["body_markdown"]

    # Build condition description
    condition_parts = []
    if conditions.get("month"):
        condition_parts.append(f"in {conditions['month'].title()}")
    if conditions.get("features"):
        condition_parts.append(f"with {', '.join(conditions['features'])}")
    if conditions.get("capacity"):
        condition_parts.append(f"for {conditions['capacity']} guests")

    condition_desc = " ".join(condition_parts) if condition_parts else ""

    items = result.get("items", [])
    if not items:
        return f"No {select} found {condition_desc}."

    lines = [f"Available {select} {condition_desc}:"]
    for item in items[:10]:
        name = item.get("name", item.get("room_name", "Item"))
        lines.append(f"- {name}")

    return "\n".join(lines)


def _render_ranked_result(
    select: str,
    result: Dict[str, Any],
    conditions: List[Dict[str, Any]],
) -> str:
    """
    Render ranked OR result with match indicators.
    """
    if result.get("body_markdown"):
        return result["body_markdown"]

    items = result.get("items", [])
    if not items:
        return f"No {select} found matching your criteria."

    # Collect all features from conditions
    all_features = set()
    for cond in conditions:
        all_features.update(cond.get("features", []))

    lines = ["Items matching most features shown first:\n"]
    for item in items[:10]:
        name = item.get("name", item.get("room_name", "Item"))
        matched = item.get("matched_conditions", 0)
        total = len(conditions)
        if matched == total:
            match_indicator = "(matches all)"
        elif matched > 0:
            match_indicator = f"(matches {matched}/{total})"
        else:
            match_indicator = ""
        lines.append(f"- {name} {match_indicator}")

    return "\n".join(lines)


def _build_combined_header(select: str, conditions: Dict[str, Any]) -> str:
    """
    Build descriptive header for combined query.
    """
    base = INDEPENDENT_SECTION_HEADERS.get(select, select.title())

    modifiers = []
    if conditions.get("month"):
        modifiers.append(f"in {conditions['month'].title()}")
    if conditions.get("features"):
        modifiers.append(f"with {', '.join(conditions['features'])}")

    if modifiers:
        return f"{base} {' '.join(modifiers)}"
    return base


def _get_info_link(select: str) -> Optional[str]:
    """
    Get info link for a select type.
    """
    info_links = {
        "rooms": "/info/rooms",
        "menus": "/info/menus",
        "dates": "/info/availability",
        "products": "/info/products",
        "site_visit": "/info/site-visit",
        "policy": "/info/policies",
    }
    return info_links.get(select)


def build_group_result(
    composed: ComposedResponse,
    state: WorkflowState,
) -> GroupResult:
    """
    Convert ComposedResponse to GroupResult for workflow integration.
    """
    event_entry = state.event_entry or {}
    raw_step = event_entry.get("current_step")
    try:
        current_step = int(raw_step) if raw_step is not None else 2
    except (TypeError, ValueError):
        current_step = 2

    thread_state = event_entry.get("thread_state") or state.thread_state or "Awaiting Client"

    body_markdown = composed.body_markdown
    footer_body = append_footer(
        body_markdown,
        step=current_step,
        next_step=current_step,
        thread_state=thread_state,
    )

    draft_message = {
        "body": footer_body,
        "body_markdown": body_markdown,
        "step": current_step,
        "topic": "multi_variable_qna",
        "next_step": current_step,
        "thread_state": thread_state,
        "requires_approval": False,
        "subloop": "multi_variable_qna",
        "table_blocks": composed.all_table_blocks,
    }

    state.record_subloop("multi_variable_qna")
    state.add_draft_message(draft_message)
    state.set_thread_state(thread_state)

    payload = {
        "client_id": state.client_id,
        "event_id": event_entry.get("event_id"),
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "multi_variable_qna": True,
        "conjunction_relationship": composed.relationship,
        "section_count": len(composed.sections),
    }

    return GroupResult(action="multi_variable_qna_result", payload=payload)


__all__ = [
    "ComposedSection",
    "ComposedResponse",
    "compose_multi_variable_response",
    "build_group_result",
]
