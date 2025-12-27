"""Pre-routing pipeline for workflow message processing.

Extracted from workflow_email.py as part of P1 refactoring (Dec 2025).
Contains pre-routing checks that run after intake but before the step router:
- Duplicate message detection
- Post-intake halt handling
- Guard evaluation
- Smart shortcuts
- Billing flow step correction
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from backend.workflows.common.types import GroupResult, WorkflowState
from backend.workflow.guards import evaluate as evaluate_guards
from backend.workflows.planner import maybe_run_smart_shortcuts


# Type aliases for callback functions
PersistFn = Callable[[WorkflowState, Path, Path], None]
DebugFn = Callable[[str, WorkflowState, Optional[Dict[str, Any]]], None]
FinalizeFn = Callable[[GroupResult, WorkflowState, Path, Path], Dict[str, Any]]


def check_duplicate_message(
    state: WorkflowState,
    combined_text: str,
    path: Path,
    lock_path: Path,
    finalize_fn: FinalizeFn,
) -> Optional[Dict[str, Any]]:
    """Check if client sent the exact same message twice in a row.

    Returns finalized response if duplicate detected, None otherwise.
    Also stores current message for next comparison.
    """
    if not state.event_entry:
        return None

    last_client_msg = state.event_entry.get("last_client_message", "")
    normalized_current = combined_text.strip().lower()
    normalized_last = (last_client_msg or "").strip().lower()

    # Only check for duplicates if we have a previous message and messages are identical
    if normalized_last and normalized_current == normalized_last:
        # Don't flag as duplicate if this is a detour return or offer update flow
        is_detour = state.event_entry.get("caller_step") is not None
        current_step = state.event_entry.get("current_step", 1)
        # Don't flag as duplicate during billing flow - client may resend billing info
        in_billing_flow = (
            state.event_entry.get("offer_accepted")
            and (state.event_entry.get("billing_requirements") or {}).get("awaiting_billing_for_accept")
        )

        if not is_detour and not in_billing_flow and current_step >= 2:
            # Return friendly "same message" response instead of processing
            duplicate_response = GroupResult(
                action="duplicate_message",
                halt=True,
                payload={
                    "draft": {
                        "body_markdown": (
                            "I notice this is the same message as before. "
                            "Is there something specific you'd like to add or clarify? "
                            "I'm happy to help with any questions or changes."
                        ),
                        "hil_required": False,
                    },
                },
            )
            from backend.debug.hooks import trace_marker  # pylint: disable=import-outside-toplevel

            trace_marker(
                state.thread_id,
                "DUPLICATE_MESSAGE_DETECTED",
                detail="Client sent identical message twice in a row",
                owner_step=f"Step{current_step}",
            )
            return finalize_fn(duplicate_response, state, path, lock_path)

    # Store current message for next comparison (only if not a duplicate)
    state.event_entry["last_client_message"] = combined_text.strip()
    state.extras["persist"] = True
    return None


def evaluate_pre_route_guards(state: WorkflowState) -> None:
    """Evaluate guards and store candidate dates if step2 required."""
    guard_snapshot = evaluate_guards(state)
    if guard_snapshot.step2_required and guard_snapshot.candidate_dates:
        state.extras["guard_candidate_dates"] = list(guard_snapshot.candidate_dates)


def try_smart_shortcuts(
    state: WorkflowState,
    path: Path,
    lock_path: Path,
    debug_fn: DebugFn,
    persist_fn: PersistFn,
    finalize_fn: FinalizeFn,
) -> Optional[Dict[str, Any]]:
    """Try to run smart shortcuts.

    Returns finalized response if shortcut fired, None otherwise.
    """
    shortcut_result = maybe_run_smart_shortcuts(state)
    if shortcut_result is not None:
        debug_fn(
            "smart_shortcut",
            state,
            {"shortcut_action": shortcut_result.action},
        )
        persist_fn(state, path, lock_path)
        return finalize_fn(shortcut_result, state, path, lock_path)
    return None


def correct_billing_flow_step(state: WorkflowState) -> None:
    """Force step=5 when in billing flow.

    This handles cases where step was incorrectly set before billing flow started.
    """
    if not state.event_entry:
        return

    in_billing_flow = (
        state.event_entry.get("offer_accepted")
        and (state.event_entry.get("billing_requirements") or {}).get("awaiting_billing_for_accept")
    )
    stored_step = state.event_entry.get("current_step")

    if in_billing_flow and stored_step != 5:
        print(f"[WF][BILLING_FIX] Correcting step from {stored_step} to 5 for billing flow")
        state.event_entry["current_step"] = 5
        state.extras["persist"] = True
    elif in_billing_flow:
        print(f"[WF][BILLING_FLOW] Already at step 5, proceeding with billing flow")


def run_pre_route_pipeline(
    state: WorkflowState,
    intake_result: GroupResult,
    combined_text: str,
    path: Path,
    lock_path: Path,
    *,
    persist_fn: PersistFn,
    debug_fn: DebugFn,
    finalize_fn: FinalizeFn,
) -> Tuple[Optional[Dict[str, Any]], GroupResult]:
    """Run the complete pre-routing pipeline.

    Executes all pre-routing checks after intake:
    1. Duplicate message detection
    2. Post-intake halt check
    3. Guard evaluation
    4. Smart shortcuts
    5. Billing flow step correction

    Args:
        state: Current workflow state
        intake_result: Result from intake step
        combined_text: Combined subject + body text
        path: Database file path
        lock_path: Database lock file path
        persist_fn: Callback to persist state
        debug_fn: Callback for debug logging
        finalize_fn: Callback to finalize and return result

    Returns:
        Tuple of (early_return, last_result) where:
        - early_return is the Dict to return if pipeline short-circuited, or None to continue
        - last_result is the intake result (unchanged if continuing to router)
    """
    # 1. Duplicate message detection
    duplicate_result = check_duplicate_message(state, combined_text, path, lock_path, finalize_fn)
    if duplicate_result is not None:
        return duplicate_result, intake_result

    # 2. Post-intake halt check
    persist_fn(state, path, lock_path)
    if intake_result.halt:
        debug_fn("halt_post_intake", state, None)
        return finalize_fn(intake_result, state, path, lock_path), intake_result

    # 3. Guard evaluation
    evaluate_pre_route_guards(state)

    # 4. Smart shortcuts
    shortcut_response = try_smart_shortcuts(
        state, path, lock_path, debug_fn, persist_fn, finalize_fn
    )
    if shortcut_response is not None:
        return shortcut_response, intake_result

    # 5. Billing flow step correction
    correct_billing_flow_step(state)

    # Pre-route debug logging
    print(f"[WF][PRE_ROUTE] About to enter routing loop, event_entry exists={state.event_entry is not None}")
    if state.event_entry:
        print(f"[WF][PRE_ROUTE] current_step={state.event_entry.get('current_step')}, offer_accepted={state.event_entry.get('offer_accepted')}")

    # Continue to router
    return None, intake_result
