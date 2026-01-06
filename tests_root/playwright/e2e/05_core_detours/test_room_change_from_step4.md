# DET-003: Room Change from Step 4

**Test ID:** DET-003
**Category:** Detours
**Flow:** 1 -> 2 -> 3 -> 4 (detour to 3) -> 4
**Pass Criteria:** Room change processed, updated offer generated

---

## Test Steps

### Setup: Get to Step 4 (Offer)

```
ACTION: Navigate, reset client
ACTION: Send email: 30 people, February 2026
ACTION: Confirm date: "07.02.2026"
ACTION: Select room: "Room A"
ACTION: Request offer (if not automatic)
WAIT: Offer displayed
VERIFY: At Step 4 with offer showing Room A
```

### Trigger: Room Change at Offer Stage

```
ACTION: Send: "Can we switch to Room B instead?"
WAIT: Response appears
```

### Verify: Fast-Skip Back to Offer

```
VERIFY: Room change acknowledged
VERIFY: Requirements unchanged, so:
  - No capacity re-evaluation needed
  - Fast-skip back to offer
VERIFY: Updated offer with Room B
VERIFY: Price reflects Room B pricing
VERIFY: NO fallback message
```

---

## Pass Criteria

- [ ] Room change detected at Step 4
- [ ] No requirement re-evaluation (same capacity)
- [ ] Updated offer with new room
- [ ] Prices updated correctly

---

## Test Run Results

### Run 1: 2024-12-24

**Setup: Get to Step 4**
- INPUT: "Need a conference room for 25 people, March 2026."
- ACTUAL: System auto-picked 20.03.2026, showed Room B, E, F options
- Selected Room B
- ✅ Reached offer stage

**Trigger: Room Change**
- INPUT: "Can we switch to Room E instead?"
- EXPECTED: Room change processed, updated offer with Room E
- ACTUAL:
  - System responded asking about TIME preference (14-18, 18-22)
  - Date shown as 24.12.2025 (TODAY!) instead of 20.03.2026
  - No mention of room change
  - Workflow dropped back to Step 2 behavior

**ISSUES FOUND:**
- 🔴 DATE CORRUPTED: 20.03.2026 → 24.12.2025 (today's date)
- 🔴 STEP REGRESSION: Dropped from Step 4 (offer) to Step 2 (date/time confirmation)
- 🔴 ROOM CHANGE IGNORED: Instead of updating offer, asked about time
- 🔴 Same pattern as DET-001 - detour handling systematically broken

**OVERALL STATUS:** 🔴 FAIL - Detour handling corrupts workflow state

**Root Cause Hypothesis:**
Same as DET-001 - detour detection may work but execution corrupts state.
Date defaulting to TODAY suggests state reset/corruption during detour attempt.
