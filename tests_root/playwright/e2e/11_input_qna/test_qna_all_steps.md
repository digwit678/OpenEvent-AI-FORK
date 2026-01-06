# QNA-003: Q&A at Every Workflow Step

**Test ID:** QNA-003
**Category:** Q&A
**Flow:** 1 -> Q&A -> 2 -> Q&A -> 3 -> Q&A -> 4 -> Q&A
**Pass Criteria:** Q&A works at every step without disrupting workflow

---

## Test Steps

### Step 1: Q&A at Intake

```
ACTION: Navigate, reset client
ACTION: Send booking request with embedded question:
---
Subject: Conference Planning

We're planning a conference for 40 people in February 2026.

Quick question: Do you have any rooms with built-in sound systems?

test-qna003@example.com
---

WAIT: Response appears
```

### Verify: Step 1 Q&A Handled

```
VERIFY: Sound system question answered
VERIFY: Booking intake also processed
VERIFY: Response addresses both:
  - Q&A answer about sound systems
  - Workflow acknowledgment of booking request
VERIFY: NO fallback message
```

---

### Step 2: Q&A During Date Confirmation

```
ACTION: When date options offered, ask question:
---
Before I confirm, is there valet parking available?
Also, let's go with 14.02.2026.
---

WAIT: Response appears
```

### Verify: Step 2 Q&A + Confirmation

```
VERIFY: Parking question answered
VERIFY: Date confirmation processed (14.02.2026)
VERIFY: Flow continues to Step 3
VERIFY: NO fallback message
```

---

### Step 3: Q&A During Room Selection

```
ACTION: When room options shown, ask:
---
Which room has the best natural light?
---

WAIT: Response appears
```

### Verify: Step 3 Q&A Answered

```
VERIFY: Light question answered with specific room recommendation
VERIFY: Room options still available for selection
VERIFY: Q&A doesn't force room selection
VERIFY: NO fallback message
```

### Continue Room Selection

```
ACTION: Select room: "I'll take Room A"
WAIT: Response moves toward offer
```

---

### Step 4: Q&A at Offer Stage

```
ACTION: Before accepting offer, ask:
---
What's included in the catering package? And is the projector rental included?
---

WAIT: Response appears
```

### Verify: Step 4 Q&A Answered

```
VERIFY: Catering details explained
VERIFY: Equipment pricing/inclusion clarified
VERIFY: Offer still pending (not auto-accepted/rejected)
VERIFY: NO fallback message
```

### Accept Offer

```
ACTION: Accept: "Looks good, I accept"
WAIT: Response

VERIFY: Offer accepted
VERIFY: Flow continues (billing/deposit)
VERIFY: NO fallback message
```

---

## Pass Criteria

- [ ] Q&A works at Step 1 (intake)
- [ ] Q&A works at Step 2 (date confirmation)
- [ ] Q&A works at Step 3 (room selection)
- [ ] Q&A works at Step 4 (offer review)
- [ ] Q&A never blocks workflow progression
- [ ] Hybrid messages (Q&A + action) processed correctly
- [ ] No fallback messages at any step
