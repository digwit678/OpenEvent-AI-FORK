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

### DECISION-005: Pre-existing Test Failures

**Date Raised:** 2025-12-17
**Context:** Discovered during Phase B migration (detection module reorganization)
**Status:** Open

**Question:** Two pre-existing test failures need investigation and fixing.

**Failures:**

1. **test_clarification_message_contains_options** (`backend/tests/detection/test_low_confidence_handling.py:72`)
   - **Issue:** Test expects "discuss pricing" in clarification message body, but the LLM-generated message is truncated or uses different wording
   - **Assertion:** `assert "discuss pricing" in body`
   - **Actual:** Body contains "...are you looking to confirm the booking or would you like t..." (truncated)
   - **Root cause:** Likely LLM response variation or message length limit

2. **test_room_selection_uses_catalog** (`backend/tests/detection/test_semantic_matchers.py:125`)
   - **Issue:** Test expects "Panorama Hall" to be recognized as a room from the catalog
   - **Assertion:** `assert is_room_selection("Panorama Hall looks good")`
   - **Actual:** Returns `False`
   - **Root cause:** Room catalog only contains ['Room A', 'Room B', 'Room C', 'Room D', 'Room E', 'Room F'] - "Panorama Hall" is not in the catalog

**Options:**
1. **Fix test data** - Add "Panorama Hall" to room catalog or update test to use existing room names
2. **Fix test expectations** - Update assertions to match actual system behavior
3. **Fix underlying code** - If the behavior is wrong, fix the implementation

**Priority:** Low (not blocking, found during refactoring)

---

### DECISION-006: Phase C Large File Splitting Deferred

**Date Raised:** 2025-12-17
**Context:** Refactoring plan Phase C - splitting files >1000 lines
**Status:** Decided (Deferred)

**Question:** Should we split these large files as planned?
- `date_confirmation/trigger/process.py` (3664 lines)
- `main.py` (2188 lines)
- `smart_shortcuts.py` (2196 lines)
- `general_qna.py` (1490 lines)

**Analysis:**
After detailed review, these files have:
1. **Heavy interdependencies** - Private functions call each other extensively
2. **Shared state** - Global variables like `active_conversations`, `GUI_ADAPTER`
3. **Conditional logic** - Debug routes registered conditionally based on settings
4. **No clear boundaries** - Functions are tightly coupled within logical groupings

**Risk Assessment:**
- High probability of introducing bugs
- Significant testing effort required
- Limited immediate benefit vs. risk

**Decision:** **Defer to future iteration**

**Rationale:**
1. Phase B (detection migration) achieved the primary goal of consolidating detection logic
2. Phase D (error handling) provides higher value with lower risk
3. File splitting can be done incrementally later when specific files need modification
4. The codebase is now navigable with the detection module reorganization

**Alternative Approach:**
Instead of splitting, future improvements can:
- Extract constants to dedicated modules when needed
- Create thin wrappers for testing when needed
- Split incrementally during feature development

---

### DECISION-007: Phase E & F Folder/File Renaming Deferred

**Date Raised:** 2025-12-17
**Context:** Refactoring plan Phase E (folder renaming) and Phase F (file renaming)
**Status:** Decided (Deferred)

**Question:** Should we rename folders and files as planned?
- Phase E: `groups/` → `steps/`, `common/` → `shared/`
- Phase F: `process.py` → `step2_orchestrator.py`, etc.

**Impact Analysis:**
- `backend.workflows.groups` imports: 37 files
- `backend.workflows.common` imports: 138 files
- Total import statements to update: 175+

**Decision:** **Defer to future iteration**

**Rationale:**
1. Phase B already achieved the primary goal (detection logic consolidation)
2. 175+ import changes carries significant regression risk
3. Current folder names are functional, even if not ideal
4. Renaming can be done incrementally when files need other changes

**Future Approach:**
When renaming becomes necessary:
1. Create new locations with proper `__init__.py` re-exports
2. Update imports in batches with full test runs
3. Keep deprecation shims temporarily for external consumers

---

### DECISION-008: Database Cleanup Strategy

**Date Raised:** 2026-01-05
**Context:** Production readiness audit - data retention and cleanup
**Status:** Open

**Question:** What should our general strategy be for cleaning up old/stale data across all storage layers?

**Current State (ad-hoc):**
| Data Type | Storage | Current Cleanup | TTL | Notes |
|-----------|---------|-----------------|-----|-------|
| Snapshots (info pages) | JSON / Supabase | TTL + max count | 7d (event) / 365d (Q&A) | ✅ Implemented |
| LLM analysis cache | In-memory | LRU eviction | Bounded to 500 | ✅ Implemented |
| Events | JSON / Supabase | None | Indefinite | Keep for reporting |
| Clients | JSON / Supabase | None | Indefinite | **DO NOT DELETE** - needed for memory/personalization |
| Client Memory | JSON / Supabase | None | Indefinite | See CLIENT_MEMORY_PLAN_2026_01_03.md |
| HIL Tasks | JSON / Supabase | None | Indefinite | Keep for audit trail |
| Conversation state | In-memory dict | None | Until server restart | Needs timeout |
| Debug traces | Files | None | Indefinite | Disable in prod |

**Important:** Client data must be retained for personalization features. See `docs/reports/CLIENT_MEMORY_PLAN_2026_01_03.md` for the client memory/history plan.

**Questions to Resolve:**

1. **Events lifecycle:**
   - When should completed/cancelled events be archived or deleted?
   - Should we keep them for analytics/reporting?
   - GDPR implications for client data in events?

2. **Snapshot cleanup triggers:**
   - Current: TTL-based (7 days event-specific, 365 days Q&A)
   - Should we also cleanup when event reaches terminal status?
   - Hook location: Step 7 confirmation flow?

3. **Conversation state:**
   - `active_conversations` dict grows unbounded
   - Should we expire inactive conversations?
   - What timeout is reasonable? (30 min? 24h?)

4. **Debug traces:**
   - Currently stored indefinitely in files
   - Should be cleaned up in production
   - Retain how long for debugging?

5. **HIL Tasks:**
   - Resolved tasks accumulate forever
   - Archive after X days?
   - Keep for audit trail?

**Options for General Strategy:**

**Option A: Event-driven cleanup**
- Cleanup associated data when event reaches terminal status
- Pro: Data removed when no longer needed
- Con: Complex to implement, need to track all related data

**Option B: TTL-based cleanup (cron job)**
- Daily/weekly job removes data older than X days
- Pro: Simple, predictable
- Con: May delete data still being referenced

**Option C: Tiered retention**
- Hot: Last 7 days (full data)
- Warm: 7-90 days (archived, queryable)
- Cold: 90+ days (deleted or anonymized)
- Pro: Balances performance and compliance
- Con: More complex infrastructure

**Option D: Manual cleanup**
- Admin triggers cleanup when needed
- Pro: Full control
- Con: Relies on human action, may forget

**Recommendation:** Combination of A + B
- Event-driven: Clean snapshots when booking completes
- TTL-based: Cron job for expired sessions, old debug traces
- Keep events/clients longer for business reporting

**Implementation Needed:**
1. Hook `delete_snapshots_for_event()` into Step 7 terminal states
2. Add session expiration to `active_conversations`
3. Add debug trace cleanup job (or disable in prod)
4. Document retention policy for compliance

**Dependencies:** Business requirements, GDPR compliance review, ops infrastructure

---

### DECISION-009: Client Memory - What to Extract and Store

**Date Raised:** 2026-01-05
**Context:** Client memory service implemented, but extraction strategy TBD
**Status:** Open

**Question:** What information should we extract from conversations and store in client memory for personalization?

**Current Implementation:**
- Basic message history (client + assistant, truncated to 500 chars)
- Profile fields: name, company, language, preferences[], notes[]
- Simple rule-based summary (placeholder for LLM)

**Open Questions:**

1. **What to extract automatically:**
   - Preferred communication style (formal/informal)?
   - Recurring event patterns (annual conferences, quarterly meetings)?
   - Room/catering preferences from past bookings?
   - Budget sensitivity signals?
   - Decision-making patterns (quick vs. deliberate)?

2. **How to extract:**
   - Rule-based keyword matching (fast, deterministic)?
   - LLM extraction after each conversation (accurate but costly)?
   - Batch processing overnight (delayed but efficient)?
   - Hybrid: rules for obvious signals, LLM for nuance?

3. **Summary generation:**
   - When to generate/refresh summaries?
   - LLM prompt design for personalization summaries?
   - Max summary length for prompt injection?

4. **Privacy considerations:**
   - What's appropriate to remember vs. creepy?
   - Should clients be able to see/edit their memory?
   - GDPR right to erasure - already have `clear_memory()`

**Extraction Candidates:**

| Signal | Source | Extraction Method | Value |
|--------|--------|-------------------|-------|
| Preferred language | user_info.language | Already captured | High |
| Company size hints | Message content | LLM | Medium |
| Budget sensitivity | Negotiation patterns | LLM | High |
| Recurring events | Booking history | Rule-based | High |
| Room preferences | Past bookings | Rule-based | High |
| Catering preferences | Past bookings | Rule-based | Medium |
| Communication style | Message tone | LLM | Low |
| Decision speed | Response timing | Rule-based | Low |

**Options:**

**Option A: Minimal (Current)**
- Store messages only
- No automatic extraction
- Manual profile updates
- Pro: Simple, no cost
- Con: Limited personalization

**Option B: Rule-based extraction**
- Extract obvious signals (language, room prefs from bookings)
- Pattern matching for recurring events
- Pro: Fast, deterministic, no LLM cost
- Con: Misses nuanced signals

**Option C: LLM extraction**
- Run extraction prompt after each conversation
- Generate rich client profiles
- Pro: Captures nuance, better personalization
- Con: Cost (~$0.01-0.02 per extraction), latency

**Option D: Hybrid (Recommended)**
- Rule-based for structured data (prefs from bookings)
- LLM for summaries (batch, not real-time)
- Refresh summaries weekly or after N messages
- Pro: Balance of cost and quality
- Con: More complex implementation

**Implementation Notes:**
- Current `generate_summary()` is a placeholder for LLM version
- `CLIENT_MEMORY_SUMMARY_INTERVAL` controls refresh frequency
- Memory stored in client dict, persists with database

**Dependencies:** UX research on what personalization is valuable, cost analysis for LLM extraction

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