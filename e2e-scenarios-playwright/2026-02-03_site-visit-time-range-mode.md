# E2E Test: Site Visit Time Range Mode with Configurable Duration

**Date:** 2026-02-03
**Feature:** Time slot booking with configurable start time, end time, and duration
**Status:** PASSED
**Test Method:** Playwright Browser Automation

## Feature Summary

This test demonstrates the new **Time Range Mode** for site visit booking, which replaces the legacy fixed-slot system (10:00, 14:00, 16:00) with configurable time ranges and durations.

### Configuration Used
```json
{
  "use_time_range_mode": true,
  "range_start_hour": 9,
  "range_end_hour": 18,
  "slot_duration_minutes": 45
}
```

### Generated Time Slots
With the above config, the system generates slots at 45-minute intervals:
- 09:00, 09:45, 10:30, 11:15, 12:00, 12:45, 13:30, 14:15, 15:00, 15:45, 16:30, 17:15

---

## Comprehensive E2E Test Scenario

This test verifies the complete flow including:
- Site visit detour (blocked event day)
- Site visit booking with 45-min intervals
- Event flow with room selection
- First offer generation
- Event detour (date change)
- Second offer with preserved billing
- Second offer confirmation

### Step 1: Initial Client Inquiry with Site Visit Request

**Client Message:**
```
Subject: Corporate Retreat Inquiry + Site Visit

Dear Team,

I'm organizing a corporate retreat for 40 participants on August 15th, 2026.
We're interested in your larger rooms.

Before booking, I'd like to schedule a site visit to see the venue.
Could we arrange this for August 15th at 10:00?

Looking forward to your response.

Best regards,
Maria Chen
maria.chen-e2e-comprehensive@example.com
```

### Step 2: Site Visit Detour (Event Day Blocked)

**Shami Response:**
```
Unfortunately, 15.08.2026 at 10:00 is already booked for an event,
so site visits won't be possible at that time.

Here are some alternative dates for you to consider:
10.02.2026, 11.02.2026, and 12.02.2026.

Which date works best for you? Once you choose, I can share the available time slots.

---
Here's how site visits work at our venue:
Site visits run Tuesday–Thursday between 10:00 and 18:00.
We need a confirmed event date and time window before booking the tour.
```

**Key Verification:** System correctly blocked Aug 15th (event day) and offered alternatives.

### Step 3: Client Selects Alternative Date

**Client:** "February 10th at 10:30 works for me."

### Step 4: System Shows 45-Minute Interval Time Slots

**Shami Response:**
```
Here are the available time slots on 10.02.2026:
- 09:00
- 09:45
- 10:30
- 11:15
- 12:00
- 12:45
- 13:30
- 14:15
- 15:00
- 15:45
- 16:30
- 17:15

Which time works best for you?
```

**Key Verification:** Time slots generated at 45-minute intervals from 09:00 to 17:15.

### Step 5: Client Confirms Time Slot

**Client:** "10:30 please"

### Step 6: Site Visit Confirmed

**Shami Response:**
```
Your site visit is confirmed for 10.02.2026 at 10:30.
We look forward to welcoming you and showcasing our venue!

When you're ready to confirm your event date, just reach out!
```

### Step 7: Event Booking Proceeds

**Client:** "Great! Now let's proceed with the event booking. I confirm August 15th, 2026 for the retreat. What rooms do you have available for 40 people?"

### Step 8: Room Availability

**Shami Response:**
```
Availability overview

For your event on 15.08.2026 with 40 guests, I recommend Room A
because it accommodates up to 40 guests.
Alternatives: Room B (capacity 60); Room C (capacity 80).

Let me know which room you'd prefer and I'll prepare the offer.
```

### Step 9: Room Selection

**Client:** "Room A sounds perfect. Please send me the offer."

### Step 10: First Offer Generated

**Shami Response:**
```
Offer

Great choice! Room A on 15.08.2026 is confirmed for your event with 40 guests.

Offer draft for 15.08.2026 · Room A
Client: Maria Chen · maria.chen-e2e-comprehensive@example.com
Billing address: Not Specified

Room booking:
- Room A · CHF 500.00

Total: CHF 500.00
Deposit to reserve: CHF 150.00 (required before confirmation)
Deposit due by: 05 August 2026
```

### Step 11: Client Accepts with Billing Address

**Client:** "I accept this offer. My billing address is: Maria Chen, Seestrasse 100, 8002 Zurich, Switzerland."

### Step 12: Deposit Gate Triggered

**Shami Response:**
```
Thank you for wanting to confirm! Before I can proceed with your booking,
please complete the deposit payment of CHF 150.00.
Once the deposit is received, I'll finalize your booking.
```

### Step 13: Event Detour - Date Change

**Client:** "Actually, I need to change the event date to August 22nd, 2026 instead. Can we update the booking?"

### Step 14: System Re-routes to Room Availability

**Shami Response:**
```
To check room availability, could you please share your preferred time window for the event?
For example, you might consider a start time of 9 AM and an end time of 5 PM,
or simply indicate if it's in the morning or afternoon.
```

**Key Verification:** System detected date change and re-routed to Step 3 for availability check.

### Step 15: Client Provides Time Window

**Client:** "The event would run from 9 AM to 6 PM."

### Step 16: Second Offer Generated (Billing Preserved)

**Shami Response:**
```
Offer

Here is your offer for Room A, accommodating 40 participants.

Offer draft for 22.08.2026 · Room A
Client: Maria Chen · maria.chen-e2e-comprehensive@example.com
Billing address: Maria Chen, Seestrasse 100, 8002 Zurich, Switzerland

Room booking:
- Room A · CHF 500.00

Total: CHF 500.00
Deposit to reserve: CHF 150.00 (required before confirmation)
Deposit due by: 12 August 2026
```

**Key Verifications:**
- Date updated to 22.08.2026
- Billing address preserved from first acceptance
- Deposit due date updated accordingly

### Step 17: Client Accepts Second Offer

**Client:** "I accept this updated offer for August 22nd. Please proceed with the booking."

### Step 18: Deposit Payment

**Action:** Client clicks "Pay Deposit" button.
**Dialog:** "Deposit of CHF 150.00 marked as paid. You can now proceed with the confirmation."

### Step 19: Final Confirmation

**Shami Response:**
```
We're thrilled to confirm your booking for Room A on 22.08.2026.
Your deposit of CHF 150 has been successfully received.

Your site visit is scheduled for 10.02.2026 at 10:30.
We'll finalize all details as we approach your event date.

Looking forward to your upcoming event!

---
Step: 7 Event Confirmation · Next: Finalize booking
```

**Key Verification:** Booking confirmed at Step 7 with both event and site visit details.

---

## Key Feature Verifications

### 1. Time Range Mode Configuration
- [x] `use_time_range_mode: true` enables the new slot generation
- [x] `range_start_hour: 9` sets first slot at 09:00
- [x] `range_end_hour: 18` sets last slot start before 18:00
- [x] `slot_duration_minutes: 45` generates slots at 45-min intervals

### 2. Slot Generation Algorithm
- [x] Slots generated from `range_start_hour` to `range_end_hour - 1`
- [x] Each slot is `slot_duration_minutes` apart
- [x] Last slot (17:15) ensures full duration before closing time

### 3. Site Visit Detour
- [x] Event day (Aug 15) correctly blocked for site visits
- [x] Alternative dates offered (Feb 10, 11, 12)
- [x] Detour handled gracefully without disrupting workflow

### 4. Event Detour (Date Change)
- [x] Date change detected via `is_date_change` signal
- [x] Re-routed to Step 3 for room availability check
- [x] Time window prompt displayed
- [x] Second offer generated with updated date

### 5. State Preservation Across Offers
- [x] Billing address captured during first acceptance
- [x] Billing address preserved in second offer after detour
- [x] Site visit booking preserved through event changes

### 6. Deposit Gate
- [x] First offer acceptance triggered deposit requirement
- [x] Second offer acceptance also required deposit
- [x] Deposit payment completed workflow to Step 7

### 7. State Machine Flow
```
Site Visit: idle → date_pending → time_pending → scheduled
Event:      Step 1 → Step 3 → Step 4 → (detour) → Step 3 → Step 4 → Step 5 → Step 7
```

### 8. Database Storage
Site visit bookings store:
- `date_iso`: "2026-02-10"
- `time_slot`: "10:30"
- `duration_minutes`: 45 (stored for future overlap calculations)
- `status`: "scheduled"

Configuration persisted:
- `use_time_range_mode`: true
- `range_start_hour`: 9
- `range_end_hour`: 18
- `slot_duration_minutes`: 45

---

## Files Involved

- `workflows/io/config_store.py` - Time range mode configuration
- `workflows/common/site_visit_handler.py` - Slot generation and booking logic
- `workflows/common/site_visit_state.py` - State management with duration storage
- `api/routes/config.py` - Config API endpoints
- `workflows/runtime/pre_route.py` - Detour detection and routing

## Configuration API

```bash
# Get current site visit config
curl http://localhost:8000/api/config/site-visit

# Enable time range mode (requires admin)
curl -X POST http://localhost:8000/api/config/site-visit \
  -H "Content-Type: application/json" \
  -d '{
    "use_time_range_mode": true,
    "range_start_hour": 9,
    "range_end_hour": 18,
    "slot_duration_minutes": 45
  }'
```

## Test Summary

| Feature | Status |
|---------|--------|
| 45-minute time slot intervals | PASSED |
| Site visit detour (blocked event day) | PASSED |
| Event detour (date change) | PASSED |
| Billing address preservation | PASSED |
| Deposit gate enforcement | PASSED |
| Second offer confirmation | PASSED |
| Final booking at Step 7 | PASSED |

**Overall Result: PASSED**

This comprehensive E2E test validates that the new time range mode for site visits works correctly alongside the existing event workflow, including detours and state preservation.
