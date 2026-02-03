# Plan: Mandatory Time Slot Booking (Event + Site Visit)

## Goal
Make time slots mandatory for every booked date (event date and site visit date). Time ranges must come from manager-configured availability. If the client does not specify a time range or “full day/multi-day” intent, the system must ask for time slot selection. Time-slot messaging must route through the verbalizer for a more human tone.

## Requirements Summary
- Use manager-defined time ranges (configurable in DB) for both events and site visits.
- Time slot selection is mandatory unless the client explicitly requests:
  - full day (all available slots on a date), or
  - multiple days (multi-day with same or multiple time ranges).
- If the client already provided valid time slots, do not ask again.
- Date suggestions should include time ranges, but avoid repeating the same time ranges per date when the ranges are identical across all proposed dates.
  - Example: “01, 05, 08 are free from 14:00–18:00 and 18:00–22:00.”
- Use the verbalizer for time-slot prompts and suggestions.

## Current State (Gaps)
- Step 2 date confirmation uses a static fallback slot (e.g., “18:00–22:00”) in messaging.
- Time slots are not enforced as mandatory; a date can be confirmed without a slot.
- Site visit slots are hours-based and auto-formatted per slot, not time ranges.
- Time slot messaging is mostly assembled inline (not through verbalizer).

## Proposed Behavior
1. **Date suggestion with grouped time ranges**
   - For a set of candidate dates, compute available time ranges for each date.
   - If all dates share the same time ranges, show dates once and list ranges once.
   - If time ranges differ per date, list per-date ranges.
2. **Mandatory time selection**
   - If the client specifies a date without a time range and no “full day/multi-day” intent, ask for time slot selection.
   - If a time range is already provided and matches manager-configured slots, proceed without the extra prompt.
3. **Applies to both event date and site visit date flows**
   - Event date confirmation (Step 2) enforces slot selection.
   - Site visit scheduling enforces slot selection too.

## Data and Config Changes
### Config store
Add manager-defined time ranges (not just hours):
- `venue.event_time_slots`: list of ranges, e.g. `[{"start": "14:00", "end": "18:00"}, {"start": "18:00", "end": "22:00"}]`
- `site_visit.time_slots`: list of ranges for visits (may differ from event slots)

Expose these via API config endpoints alongside existing site visit defaults.

### Event/visit state
- Event date confirmation should store `start_time` + `end_time` for the chosen slot.
- Site visit state should store a selected time slot range, not just a single hour.

## Verbalizer Changes
Add verbalizer topics for:
- `event_time_slot_prompt`
- `event_time_slot_suggestions`
- `site_visit_time_slot_prompt`
- `site_visit_time_slot_suggestions`

Ensure Step 2 and site visit handler call verbalizer instead of assembling the full message inline.

## Implementation Phases
1. **Config and helpers**
   - Add config accessors in `workflows/io/config_store.py` for event slots and site visit slots (time ranges).
   - Create a formatter that groups dates by identical slot sets.
2. **Step 2 date confirmation**
   - Use manager-defined slots to compute availability per date.
   - If no time range specified, prompt for time selection (verbalizer).
   - Support “full day” and “multiple days” intent to bypass time-slot prompt.
3. **Site visit scheduling**
   - Replace hour-based site visit slots with time-range slots.
   - Enforce time slot selection before confirming a visit.
4. **Parsing and intent**
   - Use unified detection `start_time`/`end_time`, plus explicit “full day”/“multiple days” detection.
   - Allow multi-day selection with shared time ranges (e.g., Mon/Tue/Wed 18:00–22:00).
5. **Verbalizer integration**
   - Route time slot prompt and suggestion messages through `ux/universal_verbalizer.py`.

## Files Likely Touched
- `workflows/steps/step2_date_confirmation/trigger/step2_handler.py`
- `workflows/io/config_store.py`
- `workflows/common/time_window.py`
- `workflows/common/site_visit_handler.py`
- `workflows/common/site_visit_state.py`
- `ux/universal_verbalizer.py`
- `api/routes/config.py`
- `tests/workflows/date/*`, `tests/workflows/site_visit/*`

## Tests
- Step 2: date-only input triggers time-slot prompt.
- Step 2: date + valid time slot skips prompt.
- Step 2: multiple days + time range confirms all dates.
- Site visit: date-only input triggers slot prompt; slot selection required.
- Verbalizer: output matches expected grouped date + time range format.

## Open Questions
- Should event and site visit share the same time slot definitions, or be separate configs?
- For “full day,” do we treat it as all manager-defined slots or as a literal 00:00–23:59 window?
- How many dates and slots should be shown in a single suggestion message before splitting into multiple messages?
