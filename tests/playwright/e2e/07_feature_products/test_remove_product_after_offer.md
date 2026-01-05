# PROD-002: Remove Product After Offer

**Test ID:** PROD-002
**Category:** Products
**Flow:** 4 (with products) -> Remove product -> Updated offer
**Pass Criteria:** Product removal updates offer correctly

---

## Test Steps

### Get Offer with Products

```
ACTION: Navigate, reset client
ACTION: Send request with products:
---
Subject: Corporate Lunch

Luncheon for 25 people on 12.04.2026.
Need catering, projector, and microphone.

test-prod002@example.com
---

WAIT: Response
ACTION: Complete date and room selection
WAIT: Offer appears with products
```

### Verify Initial Offer

```
VERIFY: Offer includes:
  - Catering
  - Projector
  - Microphone
VERIFY: Total reflects all items
```

### Remove Product

```
ACTION: Remove a product:
---
Actually, skip the catering - we'll handle food ourselves.
---

WAIT: Updated response
```

### Verify: Product Removed

```
VERIFY: Response acknowledges removal
VERIFY: Updated offer shows:
  - Catering REMOVED
  - Projector still included
  - Microphone still included
  - Total reduced
VERIFY: Price difference makes sense
VERIFY: NO fallback message
```

---

### Test: Multiple Removals

```
ACTION: Remove another product:
---
Also remove the microphone.
---

WAIT: Response
```

### Verify: Multiple Removals Work

```
VERIFY: Only projector remains
VERIFY: Total updated correctly
VERIFY: Flow still at Step 4 (offer)
VERIFY: NO fallback message
```

---

### Test: Add Back Removed Product

```
ACTION: Re-add product:
---
On second thought, add the catering back.
---

WAIT: Response
```

### Verify: Re-addition Works

```
VERIFY: Catering back in offer
VERIFY: Price updated
VERIFY: NO fallback message
```

---

## Pass Criteria

- [ ] Single product removal works
- [ ] Multiple removals work
- [ ] Re-adding works
- [ ] Prices update correctly
- [ ] Offer regenerated properly
- [ ] No fallback messages
