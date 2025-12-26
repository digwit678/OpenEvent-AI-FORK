# PREF-002: Verbalizer Preference Match Indication

**Test ID:** PREF-002
**Category:** Preferences
**Flow:** 1 -> 2 -> 3 (verify verbalizer mentions match quality)
**Pass Criteria:** Response indicates "100% match" or "closest match" based on preference alignment

---

## Test Steps

### Test Case A: Perfect Match

```
ACTION: Navigate, reset client
ACTION: Send email with preferences that perfectly match a room:
---
Subject: Training Session - March 2026

We need a room for 25 people training session.

Requirements:
- Projector and screen
- U-shape seating
- Coffee service available

14.03.2026 is our preferred date.

test-pref002a@example.com
---

WAIT: Response appears
```

### Verify: 100% Match Indication

```
VERIFY: Date confirmed (14.03.2026)
WAIT: Room options presented

VERIFY: Response includes match quality indicator:
  - "100% match" OR
  - "perfect match" OR
  - "meets all your requirements" OR
  - Similar exact-match language
VERIFY: Room with all requested features highlighted
VERIFY: NO fallback message
```

---

### Test Case B: Closest Match (No Perfect Match)

```
ACTION: Navigate, reset client
ACTION: Send email with unusual preferences:
---
Subject: Special Event - March 2026

We need a room for 35 people with very specific needs:
- Outdoor terrace access required
- Industrial kitchen for cooking demo
- Sound-proofed for music

21.03.2026 preferred.

test-pref002b@example.com
---

WAIT: Response appears
```

### Verify: Closest Match Indication

```
ACTION: Confirm date: "21.03.2026 works"
WAIT: Room options presented

VERIFY: Response indicates partial/closest match:
  - "closest match" OR
  - "best available option" OR
  - "meets most of your requirements" OR
  - Lists which requirements ARE met vs NOT met
VERIFY: Honest about limitations
VERIFY: Suggests alternatives or workarounds
VERIFY: NO fallback message
```

---

### Complete Flow

```
ACTION: Select offered room: "That works, please proceed"
WAIT: Response

ACTION: Get offer: "Send the offer"
WAIT: Offer appears

VERIFY: Offer generated successfully
VERIFY: NO fallback message
```

---

## Pass Criteria

- [ ] 100% match indicated when all preferences satisfied
- [ ] "Closest match" indicated when partial match
- [ ] Verbalizer honestly reports match quality
- [ ] Unmet requirements clearly communicated
- [ ] Flow continues regardless of match quality
