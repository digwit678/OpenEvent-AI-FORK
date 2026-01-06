# DET-005: Date Change from Step 5 (Post-Acceptance)

**Test ID:** DET-005
**Category:** Detours
**Flow:** 1 -> 2 -> 3 -> 4 -> 5 (detour to 2) -> 3 -> 4 -> 5
**Pass Criteria:** Full detour chain executes, new offer generated

---

## Test Steps

### Setup: Get to Step 5 (After Acceptance)

```
ACTION: Navigate, reset client
ACTION: Complete full flow:
  - Send email (30 people, February)
  - Confirm date (07.02.2026)
  - Select room (Room A)
  - Accept offer
  - Provide billing if requested
VERIFY: At Step 5 (offer accepted)
VERIFY: May see deposit request or site visit prompt
```

### Trigger: Date Change After Acceptance

```
ACTION: Send: "We need to move the event to March instead. How about 14.03.2026?"
WAIT: Response appears
```

### Verify: Full Detour Chain

```
VERIFY: Date change acknowledged even post-acceptance
VERIFY: System processes change:
  - Detours to Step 2 (new date confirmation)
  - Returns to Step 3 (room availability check)
  - Returns to Step 4 (new offer)
  - Returns to Step 5 (re-acceptance needed)
VERIFY: Offer hash invalidated
VERIFY: New offer generated with March date
```

### Complete New Acceptance

```
ACTION: Accept new offer: "Yes, I accept the updated offer"
WAIT: Response
VERIFY: New acceptance processed
VERIFY: Flow continues toward confirmation
VERIFY: NO fallback message
```

---

## Pass Criteria

- [ ] Date change detected at Step 5
- [ ] Full detour chain: 5 -> 2 -> 3 -> 4 -> 5
- [ ] New offer generated
- [ ] Re-acceptance processed correctly
- [ ] No fallback messages throughout
