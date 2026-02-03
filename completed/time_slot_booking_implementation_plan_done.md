# Implementation Plan: Time Slot Booking + Option-Aware Suggestions

## Goal
Make time slots mandatory for every booked date (event + site visit) while avoiding suggestions that are already blocked by Option/Confirmed holds. Use unified detection (no additional LLM cost) to interpret time scope (date-only vs full day vs multi-day vs explicit time range). If the client explicitly requests a date+time+room that is already Option/Confirmed, trigger the option-conflict flow instead of silently filtering it.

## Key Behavior Rules
1. **No default suggestions on option-only dates/times**
   - When suggesting date+time slots, only include slots that have at least one room with status = Available.
   - Slots where all rooms are Option/Confirmed are excluded from suggestions.
   - Lead status does NOT block suggestions.
2. **Explicit client request overrides the filter**
   - If the client explicitly requests a date + time range (+ room if provided) that is Option/Confirmed, trigger the option-conflict flow.
3. **Time selection is mandatory**
   - Date-only messages must get a follow-up to choose a time slot, unless the client explicitly requests full-day or multi-day booking.
4. **Site visit follows the same time-slot rules**
   - Site visit date selection must include time-slot selection (ranges, not single hours).

## Detection (LLM, no extra cost)
Use the unified detection call already run in `workflows/runtime/pre_route.py`.
- Extend `UnifiedDetectionResult` to include `time_scope`:
  - `"range"` (explicit time range)
  - `"full_day"` (explicit full/whole/entire day)
  - `"multi_day"` (explicit multiple days)
  - `"date_only"` (date without time context)
- Add optional fields:
  - `multi_day_dates` (if LLM can extract a list)
  - `time_range` (normalized start/end)

## Availability Evaluation (Option-aware)
### Event slots
For each candidate date + time range:
1. Build a `requested_window` with the time range.
2. Evaluate every room using `services/room_eval.evaluate_rooms()` or a new helper.
3. Include a slot in suggestions only if **any room** is `Available`.
4. Exclude slots if **all rooms** are `Option` or `Unavailable`.
5. If the client explicitly asks for a slot that is `Option`, trigger conflict handling.

### Site visit slots
- Use site visit time ranges from config.
- Exclude slots that overlap blocked event dates and already scheduled site visits.
- Apply the same mandatory time-slot selection rules.

## Implementation Steps
1. **Unified detection extensions**
   - Add `time_scope`, `time_range`, and `multi_day_dates` to `UnifiedDetectionResult` and prompt.
   - Store these in `state.extras` to reuse downstream.
2. **Config for time ranges**
   - Add event and site visit time ranges in `workflows/io/config_store.py`.
   - Extend `api/routes/config.py` to read/write these ranges.
3. **Slot grouping + verbalizer**
   - Add a helper to group dates by identical slot sets and format output.
   - Route slot prompts and suggestions through the verbalizer.
4. **Step 2 date confirmation changes**
   - If date-only, prompt for time slot selection.
   - Suggest only slots with at least one Available room.
   - If explicit date+time(+room) is Option/Confirmed, trigger conflict flow.
5. **Site visit scheduling changes**
   - Replace hour-based slots with time ranges.
   - Enforce time-slot selection before confirming the site visit.

## Files to Update (Code)
- `detection/unified.py` (new fields + prompt)
- `workflows/runtime/pre_route.py` (store new detection fields)
- `workflows/io/config_store.py` (event + site visit time ranges)
- `api/routes/config.py` (config endpoints)
- `workflows/common/time_window.py` (helper for range overlap if needed)
- `services/room_eval.py` (slot evaluation helper)
- `workflows/common/conflict.py` or `detection/special/room_conflict.py` (option conflict trigger with time range)
- `workflows/steps/step2_date_confirmation/trigger/step2_handler.py` (slot prompting, filtering, verbalizer)
- `workflows/steps/step2_date_confirmation/trigger/candidate_dates.py` (slot-aware candidate evaluation)
- `workflows/steps/step2_date_confirmation/trigger/calendar_checks.py` (option-aware availability)
- `workflows/steps/step2_date_confirmation/trigger/step2_utils.py` (formatting + grouping helpers)
- `workflows/steps/step2_date_confirmation/trigger/confirmation.py` (store confirmed slot)
- `workflows/planner/date_handler.py` (shortcut slot formatting)
- `workflows/common/site_visit_handler.py` (time ranges + prompt)
- `workflows/common/site_visit_state.py` (store time range)
- `workflows/steps/step7_confirmation/trigger/site_visit.py` (time ranges + slot selection)
- `ux/universal_verbalizer.py` (time-slot topics)

## Tests to Update or Add
### Expected Updates
- `tests/flow/test_happy_path_step1_to_4.py` (time slot phrasing)
- `tests/flow/test_time_window.py` (slot range semantics if changed)
- `tests_root/_legacy/test_verbalizer_agent.py` (slot formatting)
- `tests_root/_legacy/test_workflow_v3_alignment.py` (default slot expectations)
- `tests_root/workflows/date/test_confirmation_window_recovery.py` (slot capture)
- `tests_root/workflows/date/test_step3_autorun_failure.py` (default slot usage)
- `tests/detection/test_acceptance.py` (time range confirmation handling)
- `tests/detection/test_detour_changes.py` (start/end time changes)
- `tests_root/playwright/e2e/*` (new time-slot prompt in flow)

### New Tests
- Step2: date-only input triggers time-slot prompt with available ranges.
- Step2: date+time+room in Option triggers option-conflict path.
- Step2: suggestion list excludes slots where all rooms are Option/Confirmed.
- Site visit: date-only input triggers time-slot prompt; confirmation requires slot selection.

## Open Questions
- Where should option vs confirmed be sourced (calendar adapter vs DB event status)?
- Should lead holds ever block slot suggestions? (Current requirement: no.)
- How many dates and ranges should be shown before splitting into multiple messages?
