# New Features & Ideas

Ideas collected during development sessions for future implementation.

---

## Capacity Limit Handling (Dec 25, 2025)

**Context:** During capacity change testing, discovered system doesn't handle "capacity exceeds all rooms" case.

**Current Behavior:**
- System shows all rooms even when none fit the requested capacity
- Verbalizer produces contradictory messages ("great fit for 150 guests... capacity of 60")
- No routing to Step 2 for alternative dates

**Proposed Solution:**
1. **Room Filtering:** Add option to `ranking.py` to filter out rooms with `capacity_fit=0`
2. **Step 3 Unavailable Handler:** When no room fits capacity:
   - Display clear message: "Our largest room accommodates 120 guests. For 150 guests, consider..."
   - Suggest alternatives: split into two sessions, external venue partnership, reduce capacity
   - Route to Step 2 if date change might help (e.g., multi-room options on specific dates)
3. **Per Workflow V4 Spec:** "S3_Unavailable: [LLM-Verb] unavailability + propose date/capacity change → [HIL]"

**Files to modify:**
- `backend/rooms/ranking.py` - Add `filter_by_capacity=True` option
- `backend/workflows/steps/step3_room_availability/trigger/step3_handler.py` - Handle "no room fits" branch
- Verbalizer prompts for capacity limit messaging

**Priority:** Medium - edge case but poor UX when it happens

---

