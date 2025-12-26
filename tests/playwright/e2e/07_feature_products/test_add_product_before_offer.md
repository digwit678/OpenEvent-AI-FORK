
⏺ Bash(source scripts/oe_env.sh 2>/dev/null || true                                                             timeout: 30s
      PYTHONDONTWRITEBYTECODE=1 nohup uvicorn backend.main:app --reload --port 8000 > .dev/backend.log 2>&1 &…)
  ⎿  ==> .dev/backend.log <==                                                                           
     INFO:     Will watch for changes in these directories: ['/Users/nico/PycharmProjects/OpenEvent-AI']
     ERROR:    [Errno 48] Address already in use
     … +2 lines (ctrl+o to expand)

⏺ Bash(lsof -ti :8000 | xargs kill -9 2>/dev/null || true
      pkill -9 -f "uvicorn backend.main" 2>/dev/null || true…)
  ⎿  (No content)

can daso not

# PROD-001: Add Product Before Offer

**Test ID:** PROD-001
**Category:** Products
**Flow:** 1 -> 2 -> 3 -> Add product -> 4 (product in offer)
**Pass Criteria:** Products added before offer appear in offer

---

## Test Steps

### Start Booking Without Products

```
ACTION: Navigate, reset client
ACTION: Send basic request:
---
Subject: Team Meeting

Simple meeting room for 15 people on 28.03.2026.

test-prod001@example.com
---

WAIT: Response appears
ACTION: Confirm date: "28.03.2026 works"
WAIT: Room options
ACTION: Select room: "Room B"
WAIT: Response
```

### Add Product Before Offer

```
ACTION: Add product before requesting offer:
---
Actually, we'll need background music for the event.
And a projector for presentations.
---

WAIT: Response acknowledges
```

### Verify: Products Captured

```
VERIFY: Response acknowledges products:
  - Background music
  - Projector
VERIFY: Products added to booking
VERIFY: NO fallback message
```

### Get Offer

```
ACTION: Request offer: "Please send the offer now"
WAIT: Offer appears
```

### Verify: Products in Offer

```
VERIFY: Offer includes:
  - [ ] Room B rental
  - [ ] Background music (line item with price)
  - [ ] Projector (line item with price)
  - [ ] Total reflects all items
VERIFY: Products correctly priced
VERIFY: NO fallback message
```

---

## Pass Criteria

- [ ] Products added mid-flow
- [ ] Products acknowledged
- [ ] Products appear in offer
- [ ] Prices correctly calculated
- [ ] Total includes product costs
