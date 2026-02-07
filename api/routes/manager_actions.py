"""
MODULE: api/routes/manager_actions.py
PURPOSE: Manager action API endpoints for frontend integration.

These endpoints allow the frontend (app.openevent.io) to notify the backend
when a manager creates, updates, or cancels objects, triggering workflow
adaptation.

ENDPOINTS:
    PUT  /api/manager/events/{id}/date         - Manager changes event date
    PUT  /api/manager/events/{id}/room         - Manager changes room
    PUT  /api/manager/events/{id}/requirements - Manager updates requirements
    POST /api/manager/events/{id}/cancel-room  - Manager cancels room reservation
    PUT  /api/manager/offers/{id}/update       - Manager modifies offer
    POST /api/manager/site-visit/{id}/reschedule - Manager reschedules site visit
    POST /api/manager/hil/{task_id}/approve    - Manager approves HIL task
    POST /api/manager/hil/{task_id}/reject     - Manager rejects HIL task

SECURITY:
    All endpoints require manager authentication (JWT + team context).
    The middleware validates permissions before these handlers run.

DEPENDS ON:
    - workflows/manager_actions.py  # Core processing logic
    - workflows/notifications/manager_action_drafts.py  # Notification templates
    - workflow_email.py  # Database operations
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from api.utils.errors import raise_safe_error
from workflow_email import load_db as wf_load_db, save_db as wf_save_db
from workflows.manager_actions import (
    ManagerActionType,
    ManagerActionResult,
    process_manager_action,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/manager", tags=["manager-actions"])


# =============================================================================
# REQUEST MODELS
# =============================================================================


class DateChangeRequest(BaseModel):
    """Request to change an event's date."""
    new_date: str = Field(..., description="New event date (YYYY-MM-DD or DD.MM.YYYY)")


class RoomChangeRequest(BaseModel):
    """Request to change an event's room."""
    new_room: str = Field(..., description="New room ID or name")


class RoomCancellationRequest(BaseModel):
    """Request to cancel a room reservation."""
    reason: Optional[str] = Field(None, description="Optional reason for cancellation")


class RequirementsUpdateRequest(BaseModel):
    """Request to update event requirements."""
    participants: Optional[int] = Field(None, description="Number of participants")
    layout: Optional[str] = Field(None, description="Seating layout (theater, u-shape, etc.)")
    special_requirements: Optional[str] = Field(None, description="Special requirements text")
    event_duration: Optional[Dict[str, Any]] = Field(None, description="Event duration details")


class OfferUpdateRequest(BaseModel):
    """Request to update an offer."""
    price: Optional[float] = Field(None, description="New total price")
    discount: Optional[float] = Field(None, description="Discount percentage")
    terms: Optional[str] = Field(None, description="Updated terms")
    notes: Optional[str] = Field(None, description="Additional notes")


class SiteVisitRescheduleRequest(BaseModel):
    """Request to reschedule a site visit."""
    new_date: Optional[str] = Field(None, description="New date (YYYY-MM-DD or DD.MM.YYYY)")
    new_time: Optional[str] = Field(None, description="New time (HH:MM)")


class HILApproveRequest(BaseModel):
    """Request to approve a HIL task."""
    modified_response: Optional[str] = Field(None, description="Edited response text (optional)")


class HILRejectRequest(BaseModel):
    """Request to reject a HIL task."""
    reason: str = Field(..., description="Reason for rejection")


# =============================================================================
# RESPONSE MODEL
# =============================================================================


class ManagerActionResponse(BaseModel):
    """Standard response for manager action endpoints."""
    success: bool
    action_type: str
    event_id: str
    previous_step: int
    new_step: int
    needs_client_notification: bool
    notification_draft: Optional[str] = None
    error: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def _get_event_entry(event_id: str, db: Dict[str, Any]) -> Dict[str, Any]:
    """Find event entry by ID, raise 404 if not found."""
    events = db.get("events") or []
    for event in events:
        if event.get("event_id") == event_id:
            return event
    raise HTTPException(status_code=404, detail=f"Event {event_id} not found")


def _get_manager_id(request: Request) -> Optional[str]:
    """Extract manager ID from request context (set by auth middleware)."""
    # The auth middleware should set this in request.state
    return getattr(request.state, "manager_id", None) or getattr(request.state, "user_id", None)


def _process_action(
    event_id: str,
    action_type: ManagerActionType,
    payload: Dict[str, Any],
    request: Request,
) -> ManagerActionResponse:
    """Common processing logic for all manager actions."""
    try:
        db = wf_load_db()
        event_entry = _get_event_entry(event_id, db)
        manager_id = _get_manager_id(request)

        result = process_manager_action(
            event_entry=event_entry,
            action_type=action_type,
            payload=payload,
            manager_id=manager_id,
        )

        # Persist changes if successful
        if result.success:
            wf_save_db(db)
            logger.info(
                "[MANAGER_API] Action %s completed for event %s (step %d -> %d)",
                action_type.value, event_id, result.previous_step, result.new_step
            )
        else:
            logger.warning(
                "[MANAGER_API] Action %s failed for event %s: %s",
                action_type.value, event_id, result.error
            )

        return ManagerActionResponse(
            success=result.success,
            action_type=result.action_type.value,
            event_id=result.event_id,
            previous_step=result.previous_step,
            new_step=result.new_step,
            needs_client_notification=result.needs_client_notification,
            notification_draft=result.notification_draft,
            error=result.error,
            details=result.details,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise_safe_error(500, f"process manager action {action_type.value}", e, logger)


# =============================================================================
# DATE CHANGE ENDPOINT
# =============================================================================


@router.put("/events/{event_id}/date", response_model=ManagerActionResponse)
async def change_event_date(
    event_id: str,
    request_body: DateChangeRequest,
    request: Request,
) -> ManagerActionResponse:
    """
    Change an event's date.

    This triggers a detour to Step 2 (date confirmation) so the client
    can confirm the new date. A notification draft is generated for
    manager review before sending to the client.

    Effects:
    - Updates chosen_date
    - Clears date_confirmed (client must re-confirm)
    - Invalidates room_eval_hash (room availability may change)
    - Invalidates offer_hash (offer shows date)
    - Routes to Step 2
    """
    return _process_action(
        event_id=event_id,
        action_type=ManagerActionType.DATE_CHANGE,
        payload={"new_date": request_body.new_date},
        request=request,
    )


# =============================================================================
# ROOM CHANGE ENDPOINT
# =============================================================================


@router.put("/events/{event_id}/room", response_model=ManagerActionResponse)
async def change_event_room(
    event_id: str,
    request_body: RoomChangeRequest,
    request: Request,
) -> ManagerActionResponse:
    """
    Change an event's room.

    If the event is past Step 3, the room is updated in place.
    Otherwise, routes to Step 3 for room confirmation.

    Effects:
    - Updates locked_room_id
    - Invalidates offer_hash (offer shows room)
    - Optionally routes to Step 3
    """
    return _process_action(
        event_id=event_id,
        action_type=ManagerActionType.ROOM_CHANGE,
        payload={"new_room": request_body.new_room},
        request=request,
    )


# =============================================================================
# ROOM CANCELLATION ENDPOINT
# =============================================================================


@router.post("/events/{event_id}/cancel-room", response_model=ManagerActionResponse)
async def cancel_room_reservation(
    event_id: str,
    request_body: RoomCancellationRequest,
    request: Request,
) -> ManagerActionResponse:
    """
    Cancel a room reservation.

    Clears the locked room and routes to Step 3 for new room selection.
    A notification is generated to inform the client.

    Effects:
    - Clears locked_room_id
    - Clears room_eval_hash
    - Invalidates offer_hash
    - Routes to Step 3
    """
    return _process_action(
        event_id=event_id,
        action_type=ManagerActionType.ROOM_CANCELLATION,
        payload={"reason": request_body.reason},
        request=request,
    )


# =============================================================================
# REQUIREMENTS UPDATE ENDPOINT
# =============================================================================


@router.put("/events/{event_id}/requirements", response_model=ManagerActionResponse)
async def update_event_requirements(
    event_id: str,
    request_body: RequirementsUpdateRequest,
    request: Request,
) -> ManagerActionResponse:
    """
    Update event requirements (participants, layout, etc.).

    If the requirements hash changes and a room is locked, triggers
    room re-evaluation to ensure the room still fits.

    Effects:
    - Updates requirements fields
    - Recomputes requirements_hash
    - May route to Step 3 if room re-evaluation needed
    """
    payload = {}
    if request_body.participants is not None:
        payload["participants"] = request_body.participants
    if request_body.layout is not None:
        payload["layout"] = request_body.layout
    if request_body.special_requirements is not None:
        payload["special_requirements"] = request_body.special_requirements
    if request_body.event_duration is not None:
        payload["event_duration"] = request_body.event_duration

    return _process_action(
        event_id=event_id,
        action_type=ManagerActionType.REQUIREMENTS_UPDATE,
        payload=payload,
        request=request,
    )


# =============================================================================
# OFFER UPDATE ENDPOINT
# =============================================================================


@router.put("/offers/{event_id}/update", response_model=ManagerActionResponse)
async def update_offer(
    event_id: str,
    request_body: OfferUpdateRequest,
    request: Request,
) -> ManagerActionResponse:
    """
    Update an offer's price or terms.

    The offer hash is invalidated so a new offer will be generated
    on the next Step 4 run.

    Effects:
    - Updates offer fields
    - Invalidates offer_hash
    """
    payload = {}
    if request_body.price is not None:
        payload["price"] = request_body.price
    if request_body.discount is not None:
        payload["discount"] = request_body.discount
    if request_body.terms is not None:
        payload["terms"] = request_body.terms
    if request_body.notes is not None:
        payload["notes"] = request_body.notes

    return _process_action(
        event_id=event_id,
        action_type=ManagerActionType.OFFER_UPDATE,
        payload=payload,
        request=request,
    )


# =============================================================================
# SITE VISIT RESCHEDULE ENDPOINT
# =============================================================================


@router.post("/site-visit/{event_id}/reschedule", response_model=ManagerActionResponse)
async def reschedule_site_visit(
    event_id: str,
    request_body: SiteVisitRescheduleRequest,
    request: Request,
) -> ManagerActionResponse:
    """
    Reschedule a site visit.

    Updates the site visit date and/or time and generates a notification
    for the client.

    Effects:
    - Updates site_visit_date and/or site_visit_time
    """
    return _process_action(
        event_id=event_id,
        action_type=ManagerActionType.SITE_VISIT_RESCHEDULE,
        payload={
            "new_date": request_body.new_date,
            "new_time": request_body.new_time,
        },
        request=request,
    )


# =============================================================================
# HIL APPROVE ENDPOINT
# =============================================================================


@router.post("/hil/{task_id}/approve", response_model=ManagerActionResponse)
async def approve_hil_task(
    task_id: str,
    request_body: HILApproveRequest,
    request: Request,
) -> ManagerActionResponse:
    """
    Approve a HIL (Human-in-the-Loop) task.

    This sends the queued message to the client and advances the workflow.
    The manager can optionally provide a modified response.

    Note: This endpoint handles the workflow state update. The actual task
    status update is handled by the existing /api/tasks endpoints.
    """
    # For HIL tasks, we need to find the event_id from the task
    try:
        db = wf_load_db()

        # Find task to get event_id
        tasks = db.get("tasks") or []
        task_entry = None
        for task in tasks:
            if task.get("task_id") == task_id or task.get("id") == task_id:
                task_entry = task
                break

        if not task_entry:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

        event_id = task_entry.get("event_id")
        if not event_id:
            raise HTTPException(status_code=400, detail="Task has no associated event_id")

        return _process_action(
            event_id=event_id,
            action_type=ManagerActionType.HIL_APPROVE,
            payload={
                "task_id": task_id,
                "modified_response": request_body.modified_response,
            },
            request=request,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise_safe_error(500, "approve HIL task", e, logger)


# =============================================================================
# HIL REJECT ENDPOINT
# =============================================================================


@router.post("/hil/{task_id}/reject", response_model=ManagerActionResponse)
async def reject_hil_task(
    task_id: str,
    request_body: HILRejectRequest,
    request: Request,
) -> ManagerActionResponse:
    """
    Reject a HIL (Human-in-the-Loop) task.

    This logs the rejection and does NOT send the message to the client.
    The workflow state remains unchanged.

    Note: This endpoint handles the workflow state update. The actual task
    status update is handled by the existing /api/tasks endpoints.
    """
    try:
        db = wf_load_db()

        # Find task to get event_id
        tasks = db.get("tasks") or []
        task_entry = None
        for task in tasks:
            if task.get("task_id") == task_id or task.get("id") == task_id:
                task_entry = task
                break

        if not task_entry:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

        event_id = task_entry.get("event_id")
        if not event_id:
            raise HTTPException(status_code=400, detail="Task has no associated event_id")

        return _process_action(
            event_id=event_id,
            action_type=ManagerActionType.HIL_REJECT,
            payload={
                "task_id": task_id,
                "reason": request_body.reason,
            },
            request=request,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise_safe_error(500, "reject HIL task", e, logger)
