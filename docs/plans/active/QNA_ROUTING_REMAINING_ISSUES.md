# Q&A Routing - Remaining Issues

**Created**: 2026-01-19
**Status**: Open
**Priority**: Medium

## Context

Fixed 3 Q&A routing bugs that were causing 17 E2E test failures. After fixes:
- **Before**: 112/129 tests passed (87%)
- **After**: 118/129 tests passed (91%)
- **Improvement**: +6 tests fixed

## Fixes Applied (2026-01-19)

1. **Bug 1 - Step 6**: Added Q&A guard before `_collect_blockers()` in `step6_handler.py:29-40`
2. **Bug 2 - Step 4**: Added pure Q&A detection with early return in `step4_handler.py:574-597`
3. **Bug 3 - Step 2**: Strengthened Q&A guard with `?` heuristic in `step2_handler.py:580-593`

## Remaining Failures (11 tests)

### Category 1: Room Feature Q&A Triggering Step 3 Detour (9 tests)

**Symptom**: Room-related Q&A like "Does Room A have a projector?" triggers change detection and routes to Step 3 (room availability) instead of being answered inline.

**Failed Tests**:
- `test_room_features_qna_full_e2e[2]` - Step 2 → 3
- `test_room_features_qna_full_e2e[4]` - Step 4 → 3
- `test_room_features_qna_full_e2e[5]` - Step 5 → 3
- `test_room_features_qna_full_e2e[6]` - Step 6 → 3
- `test_room_features_qna_full_e2e[7]` - Step 7 → 3
- `test_various_qna_never_changes_step[What's the maximum capacity of Room A?-4]` - Step 4 → 3
- `test_qna_with_room_mention_not_room_change` - Step 4 → 3

**Root Cause**: Change detection (`detect_change_type_enhanced`) is catching room mentions in Q&A messages and misinterpreting them as room change requests.

**Proposed Fix**: Add Q&A guard in change detection - if `general_qna_detected=True` and no explicit change signal, skip change routing.

**Files to Investigate**:
- `workflows/change_propagation.py` - `detect_change_type_enhanced()`
- Step handlers before change detection runs

### Category 2: Step 2 Q&A Auto-Progression (2 tests)

**Symptom**: Certain Q&A types at Step 2 with `date_confirmed=True` still progress to Step 3.

**Failed Tests**:
- `test_catering_qna_full_e2e[2]` - Catering Q&A at Step 2 → 3
- `test_availability_qna_full_e2e[2]` - Availability Q&A at Step 2 → 3

**Root Cause**: Sequential workflow detection or other logic after Q&A guard may be triggering Step 3 auto-run.

**Proposed Fix**: Review Step 2 flow after Q&A guard - ensure no fallthrough to `_finalize_confirmation()` when Q&A is detected.

### Category 3: Response Quality (1 test)

**Failed Test**:
- `test_qna_includes_relevant_info` - Parking info not included in response

**Root Cause**: Q&A response generation not pulling parking info from knowledge base.

## Test Command

```bash
# Run all Q&A E2E tests
AGENT_MODE=openai pytest tests_root/specs/e2e_comprehensive/test_qna_from_all_steps.py -v --tb=short

# Run only failing tests
AGENT_MODE=openai pytest tests_root/specs/e2e_comprehensive/test_qna_from_all_steps.py -v --tb=short -k "room_features or catering_qna_full_e2e or availability_qna_full_e2e or maximum_capacity or room_mention or relevant_info"
```

### Category 4: Q&A Response Quality - Wrong Answers (E2E Observed)

**Symptom**: Q&A engine gives generic room info instead of answering the actual question asked.

**Example**:
- Client asked: "Does Room B have wheelchair accessibility? What's included in the room rate?"
- Response gave: Generic room features (parking, background music, projector) and parking info
- Missing: Wheelchair accessibility answer, room rate/pricing info

**Root Cause**: Q&A extraction/routing not detecting specific question topics (accessibility, pricing).

**Partial Fixes Applied (2026-01-19)**:
1. Added accessibility and rate_inclusions keywords to `detection/intent/classifier.py`
2. Added accessibility and rate_inclusions data to all rooms in `data/rooms.json`
3. Updated `load_room_static()` in `services/qna_readonly.py` to include accessibility, rate_inclusions, services, equipment

**Status**: Data is now available. Q&A extraction/routing still needs work to properly route questions to correct data sources.

**Files to Investigate**:
- `workflows/qna/extraction.py` - Question extraction (needs to detect accessibility/rate topics)
- `workflows/qna/router.py` - Q&A topic routing
- `workflows/qna/engine.py` - Response generation

## Other Fixes Applied (2026-01-19)

### Site Visit Dynamic Workflow Reminder ✅

Added dynamic step-aware reminder to site visit confirmation messages.

**File**: `workflows/common/site_visit_handler.py` - `_confirm_site_visit()` function

**Behavior**: When a client books a site visit, the confirmation message now includes a reminder specific to which workflow step they left:
- Step 2: "Whenever you're ready to continue with confirming your event date, just let me know!"
- Step 3: "Whenever you're ready to continue with selecting a room, just let me know!"
- Step 4: "Whenever you're ready to continue with reviewing your offer, just let me know!"
- etc.

**Verified**: E2E Playwright test confirmed - client at Step 3 booking site visit sees "select a room" reminder.

## Next Steps

1. Fix Category 1 (highest impact - 9 tests) by adding Q&A guard before change detection
2. Fix Category 2 by auditing Step 2 flow after Q&A guard
3. Fix Category 3 by improving Q&A response generation
4. Fix Category 4 by improving Q&A extraction to detect and route accessibility/rate questions to correct data
