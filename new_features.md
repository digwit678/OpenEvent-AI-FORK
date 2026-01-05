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

## Billing Address Extraction at Every Step (Dec 27, 2025)

**Context:** During E2E testing, noticed billing is only captured after offer confirmation (Step 5).

**Current Behavior:**
- Billing address extraction only triggers in Step 5 when `awaiting_billing_for_accept=True`
- If client proactively provides billing earlier (Step 1-4), it's ignored
- Client may need to repeat billing info after accepting offer

**Proposed Solution:**
1. **Early Billing Detection:** Add billing address regex/NLU to entity extraction in Step 1
2. **Opportunistic Capture:** If billing detected in any step, store to `billing_details` immediately
3. **Skip Prompt:** When reaching Step 5 billing gate, check if `billing_details` already complete
4. **UX Improvement:** Acknowledge early billing: "Thanks for the billing info, I'll use it when we finalize"

**Files to modify:**
- `backend/workflows/steps/step1_intake/trigger/step1_handler.py` - Add billing detection
- `backend/workflows/common/billing.py` - Add `try_capture_billing(message_text, event_entry)`
- `backend/workflows/steps/step5_negotiation/trigger/step5_handler.py` - Check pre-captured billing

**Priority:** Low - nice-to-have UX improvement

---

