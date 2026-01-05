# PREF-001: Preference-Based Room Ranking

**Test ID:** PREF-001
**Category:** Preferences
**Flow:** 1 -> 2 -> 3 (verify room order reflects preferences)
**Pass Criteria:** Rooms presented in order that respects stated preferences

---

## Test Steps

### Send Request with Specific Preferences

```
ACTION: Navigate, reset client
ACTION: Send email with clear room preferences:
---
Subject: Workshop Booking with Specific Needs

We're planning a creative workshop for 20 people in March 2026.

Key requirements:
- Natural daylight is essential
- Need whiteboard walls
- Prefer quiet location away from main areas
- Good ventilation important

test-pref001@example.com
---

WAIT: Response appears
```

### Confirm Date

```
ACTION: Confirm date when offered: "07.03.2026 works perfectly"
WAIT: Response with room options
```

### Verify: Room Ranking Reflects Preferences

```
VERIFY: Room options presented
VERIFY: Rooms with matching features ranked higher:
  - Rooms with natural light listed before windowless ones
  - Rooms with whiteboard capability prioritized
  - Quiet/secluded rooms ranked higher
VERIFY: Response mentions preference matching:
  - "Based on your requirements" OR
  - "Matching your preferences" OR
  - Reference to specific requested features
VERIFY: NO fallback message
```

### Complete Room Selection

```
ACTION: Select recommended room: "The first option sounds perfect"
WAIT: Response

ACTION: Request offer: "Please send the offer"
WAIT: Offer appears

VERIFY: Offer shows selected room
VERIFY: Room features align with stated preferences
```

---

## Pass Criteria

- [ ] Preferences captured from initial message
- [ ] Room ranking influenced by preferences
- [ ] Best-match rooms presented first
- [ ] Response acknowledges preference matching
- [ ] Flow continues normally to offer
