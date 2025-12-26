# PERS-002: Preferences Persistence and Auto-Include

**Test ID:** PERS-002
**Category:** Persistence
**Flow:** 1 (with preferences) -> 2 -> 3 -> 4 (preferences in offer)
**Pass Criteria:** Stated preferences persist and appear in offer

---

## Test Steps

### State Preferences in Initial Request

```
ACTION: Navigate, reset client
ACTION: Send request with preferences:
---
Subject: Team Workshop

We need a room for 20 people in April 2026.

Preferences:
- Natural daylight essential
- Need whiteboard walls
- Quiet location preferred
- Coffee service throughout

test-pers002@example.com
---

WAIT: Response appears
```

### Complete Flow

```
ACTION: Confirm date: "05.04.2026"
WAIT: Room options
```

### Verify: Preferences Affect Room Ranking

```
VERIFY: Rooms matching preferences ranked higher
VERIFY: Daylight/whiteboard features mentioned
```

### Continue to Offer

```
ACTION: Select room: "First option please"
WAIT: Response

ACTION: Get offer
WAIT: Offer appears
```

### Verify: Preferences in Offer

```
VERIFY: Offer includes:
  - Room with natural daylight (if selected)
  - Coffee service line item
  - Special requirements noted
VERIFY: Preferences from Step 1 visible
VERIFY: NO re-asking about preferences
VERIFY: NO fallback message
```

---

## Pass Criteria

- [ ] Preferences captured at intake
- [ ] Preferences influence room selection
- [ ] Preferences auto-included in offer
- [ ] No re-asking for stated preferences
- [ ] All original preferences traceable
