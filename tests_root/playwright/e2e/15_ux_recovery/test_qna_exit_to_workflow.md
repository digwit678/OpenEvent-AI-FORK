# EXIT-001: Q&A Exit to Workflow Continuation

**Test ID:** EXIT-001
**Category:** Exit/Recovery
**Flow:** Workflow -> Q&A subpath -> Exit Q&A -> Workflow continues
**Pass Criteria:** Leaving Q&A smoothly returns to workflow

---

## Test Steps

### Setup: Start Booking, Enter Q&A

```
ACTION: Navigate, reset client
ACTION: Send booking request:
---
Subject: Team Retreat

Planning a team retreat for 15 people in April 2026.

test-exit001@example.com
---

WAIT: Response with date options
```

### Enter Q&A Subpath

```
ACTION: Ask question instead of confirming:
---
What are your opening hours?
---

WAIT: Q&A response
```

### Ask More Questions (Deep into Q&A)

```
ACTION: Continue Q&A:
---
Do you have parking? What about wheelchair access?
---

WAIT: Response
```

### Exit Q&A, Continue Workflow

```
ACTION: Return to booking without explicit transition:
---
12.04.2026 works for us.
---

WAIT: Response appears
```

### Verify: Smooth Transition

```
VERIFY: Date confirmed (12.04.2026)
VERIFY: No "returning from Q&A" awkwardness
VERIFY: No need to re-state booking intent
VERIFY: Flow continues to room selection
VERIFY: Previous Q&A context doesn't interfere
VERIFY: NO fallback message
```

### Complete Flow

```
ACTION: Select room: "Room A"
WAIT: Response
ACTION: Get offer
WAIT: Offer

VERIFY: Offer generated successfully
VERIFY: NO fallback message
```

---

## Pass Criteria

- [ ] Q&A subpath entered without issues
- [ ] Multiple Q&A messages handled
- [ ] Exit to workflow is seamless
- [ ] No explicit "back to booking" needed
- [ ] Workflow state preserved
- [ ] Full flow completes successfully
