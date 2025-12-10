# Open Decisions Log

This file tracks open design decisions and questions that need to be revisited later.
When a decision is made, move it to the "Resolved" section with the decision and rationale.

---

## Open Questions

### DECISION-001: Deposit Changes After Payment

**Date Raised:** 2025-12-08
**Context:** Deposit integration with offer workflow
**Status:** Open

**Question:** What should happen if the event changes (detour to Step 2/3) AFTER the client has already paid a deposit, and the new event configuration results in a different deposit amount?

**Scenarios:**
1. **Deposit increases** (e.g., added catering increases total, 30% deposit goes up)
   - Option A: Request additional payment for the difference
   - Option B: Honor the original deposit amount (absorb the difference)
   - Option C: Cancel old deposit, request new full deposit

2. **Deposit decreases** (e.g., removed items, total goes down)
   - Option A: Refund the difference immediately
   - Option B: Apply excess as credit toward final payment
   - Option C: Honor original deposit (no refund)

3. **Event cancelled after deposit paid**
   - Option A: Full refund
   - Option B: Partial refund (keep admin fee)
   - Option C: Apply to future booking

**Current Implementation:** On detour, deposit payment status is reset (greyed out). The system does NOT handle the money side - that's external. The workflow just tracks whether the deposit requirement is met.

**Dependencies:** Payment gateway integration, refund policy, legal/finance team input

---

### DECISION-002: LLM vs Template for Deposit Reminders

**Date Raised:** 2025-12-08
**Context:** Client tries to confirm offer without paying deposit
**Status:** Decided (Template)

**Question:** Should we use LLM verbalization for deposit payment reminders, or use a generic template?

**Options:**
- **Option A (LLM):** Warm, personalized reminder via verbalizer
  - Pro: Consistent UX with rest of conversation
  - Con: ~$0.01-0.02 per reminder, adds up if client repeatedly tries

- **Option B (Template):** Static, professional message
  - Pro: Zero cost, instant response, deterministic
  - Con: Slightly less "human" feel

**Decision:** Use **Template** (Option B)
- Deposit reminder is a transactional/compliance message, not relationship-building
- Cost savings are meaningful at scale
- Message content is simple and doesn't benefit from LLM creativity

**Template used:**
```
To confirm your booking, please complete the deposit payment first.
Once your deposit of {amount} is received, you can proceed with the confirmation.

If you have any questions about the payment process, please let me know.
```

---

### DECISION-003: Deposit Payment Verification

**Date Raised:** 2025-12-08
**Context:** Mock payment flow in test GUI
**Status:** Open (for production)

**Question:** In production, how do we verify that a deposit has actually been paid?

**Options:**
1. **Trust client click** (current test implementation)
   - Client clicks "Pay Deposit" → we mark it paid
   - Suitable for testing only

2. **Payment gateway callback**
   - Integrate with Stripe/PayPal webhook
   - Payment confirmed → auto-update event status

3. **Manual verification by manager**
   - Manager reviews bank statement → approves deposit in HIL queue
   - More work but no integration needed

4. **Invoice-based**
   - Generate invoice with payment reference
   - Client pays via bank transfer
   - Manager or automation matches payment

**Current Implementation:** Option 1 (mock button for testing)

**Production Recommendation:** Option 2 or 4, depending on payment infrastructure

---

### DECISION-004: Deposit Display in Offer Message

**Date Raised:** 2025-12-08
**Context:** How to show deposit requirements in the offer sent to client
**Status:** Decided

**Question:** Should deposit info be in the main offer body or separate section?

**Decision:** Separate section at the bottom of offer, after total:
```
---
**Payment Terms:**
- Deposit required: CHF X.XX (30% of total)
- Deposit due: [date, X days from offer]
- Balance due: Upon event completion
```

**Rationale:**
- Clear separation of pricing vs. payment terms
- Matches real-world invoice/offer structure
- Easy to update independently

---

## Resolved Decisions

(Move decisions here once resolved, with date and rationale)

---

## How to Use This File

1. **Raising a new question:**
   - Add under "Open Questions" with DECISION-XXX ID
   - Include: Date, Context, Status, Question, Options (if known)

2. **Making a decision:**
   - Update Status to "Decided"
   - Add "Decision:" and "Rationale:" sections
   - If implementation-relevant, note where it's implemented

3. **Closing a decision:**
   - Move entire block to "Resolved Decisions" section
   - Add resolution date

4. **Referencing in code:**
   - Use `// See OPEN_DECISIONS.md DECISION-XXX` in comments