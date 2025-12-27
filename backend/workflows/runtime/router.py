"""Step router for workflow message processing.

Extracted from workflow_email.py as part of W3 refactoring (Dec 2025).
Contains the main step dispatching loop that routes messages through Steps 2-7.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from backend.workflows.common.types import GroupResult, WorkflowState
from backend.workflows.steps import step2_date_confirmation as date_confirmation
from backend.workflows.steps import step3_room_availability as room_availability
from backend.workflows.steps.step4_offer.trigger import process as process_offer
from backend.workflows.steps.step5_negotiation import process as process_negotiation
from backend.workflows.steps.step6_transition import process as process_transition
from backend.workflows.steps.step7_confirmation.trigger import process as process_confirmation


# Type aliases for callback functions
PersistFn = Callable[[WorkflowState, Path, Path], None]
DebugFn = Callable[[str, WorkflowState], None]
FinalizeFn = Callable[[GroupResult, WorkflowState, Path, Path], Dict[str, Any]]


def dispatch_step(state: WorkflowState, step: int) -> Optional[GroupResult]:
    """Dispatch to the appropriate step handler.

    Returns the GroupResult from the step handler, or None if step is not recognized.
    """
    if step == 2:
        return date_confirmation.process(state)
    if step == 3:
        return room_availability.process(state)
    if step == 4:
        return process_offer(state)
    if step == 5:
        return process_negotiation(state)
    if step == 6:
        return process_transition(state)
    if step == 7:
        return process_confirmation(state)
    return None


def run_routing_loop(
    state: WorkflowState,
    initial_result: GroupResult,
    path: Path,
    lock_path: Path,
    *,
    persist_fn: PersistFn,
    debug_fn: DebugFn,
    finalize_fn: FinalizeFn,
    max_iterations: int = 6,
) -> Tuple[Optional[Dict[str, Any]], GroupResult]:
    """Run the step routing loop through Steps 2-7.

    Iterates through workflow steps, calling the appropriate handler for each step.
    The loop continues until:
    - A step handler returns with halt=True (early return)
    - No event_entry exists (break)
    - Step is not recognized (break)
    - Max iterations reached (break)

    Args:
        state: Current workflow state
        initial_result: Result from intake step
        path: Database file path
        lock_path: Database lock file path
        persist_fn: Callback to persist state after each step
        debug_fn: Callback for debug logging
        finalize_fn: Callback to finalize and return result
        max_iterations: Maximum loop iterations (default 6)

    Returns:
        Tuple of (finalized_output, last_result) where:
        - finalized_output is the Dict to return if loop halted, or None if loop completed
        - last_result is the most recent GroupResult for post-loop handling
    """
    last_result = initial_result

    for iteration in range(max_iterations):
        event_entry = state.event_entry
        if not event_entry:
            print(f"[WF][ROUTE][{iteration}] No event_entry, breaking")
            break

        step = event_entry.get("current_step")
        print(f"[WF][ROUTE][{iteration}] current_step={step}")

        step_result = dispatch_step(state, step)

        if step_result is None:
            print(f"[WF][ROUTE] No handler for step {step}, breaking")
            break

        last_result = step_result

        # Debug and persist after each step
        debug_fn(f"post_step{step}", state)
        persist_fn(state, path, lock_path)

        # Check for halt - return early with finalized result
        if last_result.halt:
            debug_fn(f"halt_step{step}", state)
            return finalize_fn(last_result, state, path, lock_path), last_result

    # Loop completed without halting
    return None, last_result
