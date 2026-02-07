# E2E Scenario: Full Booking Flow with Detour + Cancellation

**Date:** 2026-02-06
**Method:** Browser-based (chatkit/respond via Chrome, visible overlay on localhost:3000)
**Status:** PASS (All 9 steps executed; BUG-053 verified; detour + 2nd offer + cancellation confirmed)

## Test Summary

This test verifies the complete booking lifecycle:
1. **BUG-053 fix:** Room selection (Step 3 → Step 4) generates a fresh offer instead of skipping to billing.
2. **Hybrid message handling:** Acceptance + Q&A in one message.
3. **Date change detour:** Mid-flow date change reroutes correctly and generates a second offer.
4. **Second offer generation:** After detour, a new offer is produced for the updated date.
5. **Event cancellation:** `event_cancelled_deleted` action fires and releases the date/room.

## Fixes Verified

### BUG-053: Stale `offer_accepted` Flag
- **Root cause:** `offer_accepted=True` persisted from a previous offer cycle. Step 4's confirmation gate fired immediately, skipping offer generation.
- **Fix:** Guard in `step4_handler.py` clears `offer_accepted` when `previous_step < 4`.
- **Verification:** Room B selection → `offer_draft_prepared` with full pricing.

### Frontend Fixes (discovered during E2E)
- **`fetchWorkflowReply` streaming hang:** `response.body.getReader()` never resolved for non-streaming JSON. Fixed: replaced with `response.text()`.
- **`streamMessageContent` rAF hang:** `requestAnimationFrame` callbacks paused for background/non-focused tabs, causing Promise to never resolve. Fixed: replaced with `setTimeout(step, 25)`.

### Cancellation Feature
- **Handler:** `workflows/common/cancellation_handler.py`
- **Detection:** `is_cancellation` field in `unified.py`
- **Verification:** Cancellation message → `event_cancelled_deleted`, date and room released.

## Conversation Sequence

### 1. Initial Inquiry
**Client:**
```
Hello, I'd like to book a room for 50 guests on April 15, 2026, from 10:00 to 16:00.
```

**Shami:** (action: `room_detour_time_slot`, step: 3)
```
To check room availability, could you please share your preferred time window...
```
- System fast-pathed to Step 3 (room availability) but requested time confirmation.

### 2. Time Confirmation
**Client:**
```
The event would be from 10:00 in the morning to 16:00 in the afternoon.
```

**Shami:** (action: `date_options_proposed`, step: 2)
```
I have several available dates for your event in February 2026: 06.02, 07.02, 08.02, 09.02, 10.02.
```
- System proposed available dates with confirmed time window.

### 3. Date Selection → Room Availability
**Client:**
```
February 9, 2026 works for us. Please show us the available rooms.
```

**Shami:** (action: `room_avail_result`, step: 3)
```
[Room availability for 09.02.2026 with Room B, Room C, etc.]
```
- Date confirmed, room options presented.

### 4. Room Selection → First Offer (BUG-053 VERIFIED)
**Client:**
```
Room B please.
```

**Shami:** (action: `offer_draft_prepared`, step: 4)
```
[Full offer draft with Room B pricing, deposit amount, deposit due date]
```
- **BUG-053 PASS:** Offer was generated with pricing instead of skipping to billing.

### 5. Hybrid Accept + Q&A
**Client:**
```
Room B looks perfect, I accept the offer. By the way, do you offer catering services for events?
```

**Shami:** (action: `offer_accept_requires_billing`, step: 4)
```
Thanks for confirming. I need the billing address before I can send this for approval...
```
- Acceptance processed first (workflow action), billing requested.
- Q&A about catering handled within the response.

### 6. Date Change Detour
**Client:**
```
Actually, we need to change the date. Can we move the event to February 20, 2026 instead?
```

**Shami:** (action: `room_detour_time_slot`, step: 3)
```
To check room availability for the new date, could you confirm the time window...
```
- **Detour PASS:** System correctly rerouted from Step 4 back to Step 3 for the date change.

### 7. Time Confirm → Second Offer
**Client:**
```
Same time window, 10:00 to 16:00 please.
```

**Shami:** (action: `offer_draft_prepared`, step: 4)
```
[New offer draft for 20.02.2026 with Room B pricing]
```
- **Second Offer PASS:** Fresh offer generated for the new date after detour.

### 8. Accept Second Offer + Billing
**Client:**
```
This looks great, I accept the offer. Here are our billing details: Test Corp AG, Bahnhofstrasse 1, 8001 Zurich, Switzerland.
```

**Shami:** (action: `room_avail_result`, step: 4)
```
[Room availability re-shown — known post-billing entity extraction issue]
```
- Known issue: billing text misinterpreted as product preference (same as previous E2E run).

### 9. Event Cancellation (PASS)
**Client:**
```
I'm sorry, but we need to cancel the event. Our plans have changed and we won't be able to proceed with the booking.
```

**Shami:** (action: `event_cancelled_deleted`)
```
Your event has been cancelled, and the date and room have been released.
If you have any future events in mind, we would be happy to assist you.
```

## Key Verifications

- [x] BUG-053 fixed: Room selection leads to offer generation (not billing skip)
- [x] Hybrid message: Acceptance + Q&A processed correctly
- [x] Date change detour: Rerouted from Step 4 → Step 3
- [x] Second offer generated after detour (new date)
- [x] Offer acceptance correctly requests billing details
- [x] Event cancellation fires `event_cancelled_deleted` action
- [x] Cancellation releases date and room
- [x] Frontend streaming bug fixed (`getReader` → `response.text()`)
- [x] Frontend rAF hang fixed (`requestAnimationFrame` → `setTimeout`)
- [ ] Post-billing step progression has entity extraction interference (Step 8)

## Flow Diagram

```
Initial Inquiry ──► Time Confirm ──► Date Selection ──► Room Avail
                                                            │
                                                    Room B Selection
                                                            │
                                                   ┌── FIRST OFFER ◄── BUG-053 PASS
                                                   │
                                           Hybrid Accept + Q&A
                                                   │
                                            Billing Required
                                                   │
                                          DATE CHANGE DETOUR
                                                   │
                                        ┌── Time Confirm (new)
                                        │
                                   SECOND OFFER ◄── Detour + Re-offer PASS
                                        │
                                  Accept + Billing
                                        │
                                   CANCELLATION ◄── event_cancelled_deleted PASS
```

## Environment

- Backend: dev server (port 8000)
- Frontend: Next.js dev (port 3000), Turbopack
- API: chatkit/respond (SSE streaming)
- Browser: Chrome with Claude-in-Chrome extension
- Thread ID: e2e-browser-bq3j5k1s

## Frontend Fixes Applied This Session

### 1. `fetchWorkflowReply` streaming reader hang
**File:** `atelier-ai-frontend/app/page.tsx:194`
**Before:** `response.body.getReader()` + while loop
**After:** `const buffer = await response.text();`
**Why:** `getReader()` waits for the connection to close even after all data is received. For non-streaming JSON responses, it hangs indefinitely.

### 2. `streamMessageContent` rAF hang
**File:** `atelier-ai-frontend/app/page.tsx:481-492`
**Before:** `requestAnimationFrame(step)`
**After:** `setTimeout(step, 25)`
**Why:** Chrome throttles `requestAnimationFrame` to 0 fps for non-focused/background tabs. Since the streaming animation resolves a Promise only when all chunks are rendered, the Promise never resolves if the tab isn't active — blocking `handleAssistantReply` and `setIsLoading(false)`.

## Files Involved

- `workflows/steps/step4_offer/trigger/step4_handler.py` (BUG-053 fix)
- `workflows/common/cancellation_handler.py` (cancellation)
- `detection/unified.py` (is_cancellation detection)
- `atelier-ai-frontend/app/page.tsx` (two frontend fixes)

## Known Issues for Future Investigation

1. **Entity extraction interference:** Billing details like "Test Corp AG" get parsed as product preferences, causing room re-matching at Step 8.
2. **Time slot re-prompt:** Initial inquiry includes time (10:00-16:00) but system still asks for time confirmation at Step 1.
3. **Date drift:** April 15 specified but system proposed February dates — possible date extraction issue.
4. **`/api/start-conversation` vs chatkit:** The frontend's `start-conversation`/`send-message` endpoints produce generic fallback responses while `chatkit/respond` works correctly. The `_extract_workflow_reply()` function returns empty for HIL-pending responses.
