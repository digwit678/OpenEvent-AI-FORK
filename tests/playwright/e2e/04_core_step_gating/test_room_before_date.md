# GATE-001: Room Selection Before Date Confirmation

**Test ID:** GATE-001
**Category:** Step Gating
**Flow:** 1 -> attempt Step 3 -> polite reminder -> Step 2 -> Step 3
**Pass Criteria:** System politely enforces step order

---

## Test Steps

### Initial Request with Room (No Date)

```
ACTION: Navigate, reset client
ACTION: Send request specifying room but no specific date:
---
Subject: Booking Request

I want to book Room A for 30 people.

test-gate001@example.com
---

WAIT: Response appears
```

### Verify: Date Required First

```
VERIFY: Response acknowledges Room A preference
VERIFY: Response requests date confirmation FIRST
VERIFY: Response is polite (not error-like)
VERIFY: Message explains why date is needed first:
  - "When would you like to hold this event?" OR
  - "Which date works for you?" OR
  - Similar date-first request
VERIFY: Room preference is saved for later
VERIFY: NO fallback message
VERIFY: NO "cannot process" type error
```

### Provide Date

```
ACTION: Respond with date:
---
14.02.2026
---

WAIT: Response appears
```

### Verify: Room Preference Remembered

```
VERIFY: Date confirmed
VERIFY: Room A preference carried forward
VERIFY: System either:
  - Automatically selects Room A (if available), OR
  - Presents Room A as first/preferred option
VERIFY: NO need to re-state room preference
VERIFY: NO fallback message
```

---

## Pass Criteria

- [ ] Room preference captured but not processed
- [ ] Polite date request (not error)
- [ ] Preference remembered after date provided
- [ ] Smooth flow once date given
- [ ] No fallback messages

---

## Test Run Results

### Run 1: 2024-12-24

**Step 1: Initial Request with Room (No Date)**
- INPUT: "I want to book Room A for 30 people."
- EXPECTED: Polite message asking for date first, acknowledging Room A preference
- ACTUAL: System responded with date options for December 2025 (26-30)
- ISSUES:
  - ⚠️ No explicit acknowledgment of Room A preference in response
  - ⚠️ Dates offered are in Dec 2025 (only 2 days away) - may not be realistic
  - ✅ No fallback message
  - ✅ Did enforce date-first (didn't skip to room selection)

**Step 2: Provide Date**
- INPUT: "26.12.2025"
- EXPECTED: Date confirmed, Room A auto-selected or presented first
- ACTUAL: System asked for preferred TIME (14-18, 18-22)
- ISSUES:
  - ⚠️ HIL task appeared for "date confirmation message" at Step 2 - unexpected
  - ❓ Room A preference status unknown - flow interrupted by time question

**Step 3: Provide Time**
- INPUT: "14-18"
- EXPECTED: Room options with Room A first (since requested earlier)
- ACTUAL: "Rooms for 30 people on 24.12.2025" - offered Room B, E, F
- ISSUES:
  - 🔴 DATE WRONG: I said 26.12.2025, system shows 24.12.2025 (today!)
  - 🔴 ROOM A FORGOTTEN: Original request was for Room A, not mentioned at all
  - 🔴 No acknowledgment like "Room A you requested is unavailable..."
  - ⚠️ System just ignored the room preference entirely

**OVERALL STATUS:** 🔴 FAIL

**Bugs Found:**
1. Date extraction error: "26.12.2025" → "24.12.2025"
2. Room preference not persisted from intake to Step 3
3. No user feedback about requested room unavailability
