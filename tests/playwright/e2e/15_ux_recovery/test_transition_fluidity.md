# EXIT-003: Transition Fluidity Across Paths

**Test ID:** EXIT-003
**Category:** Exit/Recovery
**Flow:** Various paths -> always reaches Step 4
**Pass Criteria:** Any path combination leads to successful offer

---

## Test Steps

### Path 1: Detour + Q&A + Continue

```
ACTION: Navigate, reset client
ACTION: Complete intake and date confirmation (07.02.2026)
ACTION: Select Room A
ACTION: Request date change: "Actually, let's do 14.02.2026 instead"
WAIT: Date change processed

ACTION: Ask Q&A: "Do you have projectors?"
WAIT: Q&A answered

ACTION: Continue: "Ok, keep Room A for 14.02"
WAIT: Response
```

### Verify: Path 1 Success

```
VERIFY: At Step 4 (offer stage)
VERIFY: Date is 14.02.2026
VERIFY: Room is Room A
VERIFY: NO fallback message
```

---

### Path 2: Q&A + Nonsense + Continue

```
ACTION: Navigate, reset client
ACTION: Send booking request (25 people, March)
WAIT: Date options

ACTION: Ask Q&A: "What's included in room rental?"
WAIT: Q&A response

ACTION: Send gibberish: "hmm ok idk"
WAIT: Clarification

ACTION: Confirm date: "07.03.2026"
WAIT: Room options

ACTION: Select and continue to offer
```

### Verify: Path 2 Success

```
VERIFY: Reached Step 4
VERIFY: NO fallback message
```

---

### Path 3: Multiple Detours

```
ACTION: Navigate, reset client
ACTION: Complete to offer (Room A, 14.02.2026)
ACTION: Request room change: "Switch to Room B"
WAIT: Offer updated
ACTION: Request date change: "Make it 21.02.2026"
WAIT: Process
ACTION: Request back to original: "Actually 14.02 with Room B"
WAIT: Process
```

### Verify: Path 3 Success

```
VERIFY: Final state: Room B, 14.02.2026
VERIFY: Offer available
VERIFY: NO fallback message
```

---

### Path 4: Hybrid + Preference + Continue

```
ACTION: Navigate, reset client
ACTION: Send: "Booking for 30 people in April with projector and coffee. What rooms have natural light?"
WAIT: Response handles hybrid

ACTION: Confirm: "12.04.2026, your brightest room"
WAIT: Room recommendation

ACTION: Accept recommendation and continue to offer
```

### Verify: Path 4 Success

```
VERIFY: Reached Step 4
VERIFY: Products (projector, coffee) in offer
VERIFY: Room matches preference
VERIFY: NO fallback message
```

---

## Pass Criteria

- [ ] Detour + Q&A + continue works
- [ ] Q&A + nonsense + continue works
- [ ] Multiple detours work
- [ ] Hybrid + preference + continue works
- [ ] ALL paths reach Step 4
- [ ] No fallback messages in any path
