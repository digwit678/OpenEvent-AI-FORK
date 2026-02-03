# Plan: On-Demand Site Visit Scheduling (LLM-Only Trigger)

## Goal
Enable clients to request a site visit at any workflow step without extra LLM cost or keyword debugging. Use the unified detection call already run per message. Default date suggestions should be event_date - 7 days when available, otherwise today + 7 days. Site visits are never confirmed without explicit client confirmation. If a proposed date is booked for site visits, suggest alternatives (same behavior as date confirmation).

## Current Behavior Snapshot
- Site visit intercept exists in `workflows/runtime/router.py` but blocks early steps unless explicit keywords are found.
- `workflows/common/site_visit_handler.py` auto-confirms when a requested date is not blocked.
- Conflict checks only consider event dates and config-blocked dates, not booked site visits.
- `site_visit_allowed()` requires `locked_room_id`, which blocks early-step requests.

## Proposed Behavior
1. On-demand site visit detection at any step (2-7, optionally Step 1) using unified detection output.
2. No auto-confirmation. All scheduling requires explicit client confirmation after availability is checked.
3. Default suggestion logic:
   - If event date exists: base = event_date - 7 days.
   - If event date missing: base = today + 7 days.
4. Site visit availability must be free (avoid event dates and already scheduled site visits). If booked, offer alternative slots.

## Architecture Changes
### Detection and Routing
- Extend `UnifiedDetectionResult` to keep `llm_qna_types` (LLM-only) alongside merged `qna_types`.
- Update `is_site_visit_intent()` to prefer `llm_qna_types` so early-step routing does not rely on regex.
- Remove the explicit keyword guard in `workflows/runtime/router.py` for steps < 5.

### State Machine
Add a confirmation gate before scheduling:
- `idle` -> `date_pending` (offer slots or check requested date)
- `date_pending` -> `confirm_pending` (availability OK, ask for confirmation)
- `confirm_pending` -> `scheduled` (only after explicit confirmation)

New fields in `site_visit_state`:
- `pending_slot`: string label or structured {date_iso, time}
- `status`: add `confirm_pending`

### Slot Generation
- Update `_generate_visit_slots()` to use the base date rule above.
- Respect `get_site_visit_min_days_ahead()` and `get_site_visit_weekdays_only()`.

### Availability and Conflicts
- Block dates that already have scheduled site visits in the DB.
- Continue to block event dates and configured blocked dates.
- If client proposes a booked date, respond with alternative slots.

### Policy Gate
- Relax `site_visit_allowed()` so site visits can happen before room lock, or add a policy flag that enables early-step site visits.

## Implementation Phases
1. Detection plumbing and routing
   - Add `llm_qna_types` to `UnifiedDetectionResult` and persist in extras.
   - Update `is_site_visit_intent()` and remove early-step keyword guard.
2. State and confirmation gate
   - Add `confirm_pending` state and `pending_slot` tracking.
   - Replace auto-confirm with explicit confirmation prompt.
3. Slot defaults and conflict checks
   - Update slot generation base date.
   - Add booked site visit conflicts to `_get_blocked_dates()` or a new helper.
4. Tests
   - Detection: early-step LLM routing uses llm_qna_types.
   - Handler: default date suggestions; no auto-confirm; conflict alternatives.
   - E2E: early-step request triggers site visit flow.

## Files to Touch (Expected)
- `detection/unified.py`
- `workflows/runtime/router.py`
- `workflows/common/site_visit_handler.py`
- `workflows/common/site_visit_state.py`
- `workflows/common/room_rules.py`
- `tests/detection/*`, `tests/workflows/*`

## Open Questions
- Should `site_visit_overview` (info question) trigger scheduling, or only `site_visit_request`?
- When no event date exists, do we always use today + 7, or clamp to `min_days_ahead` if larger?
- Are site visits blocked per day or per time slot (use `date_iso` vs `date_iso + time_slot`)?
