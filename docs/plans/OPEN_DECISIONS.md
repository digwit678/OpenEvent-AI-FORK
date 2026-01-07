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

### DECISION-010: Missing Product Handling & HIL UX

**Date Raised:** 2026-01-06
**Context:** E2E testing revealed poor UX when client requests unavailable items
**Status:** Open

**Problem Statement:**
When a client requests a product/equipment that isn't available in the room:
1. System incorrectly claims it's included (bug: conflates features vs. equipment)
2. No HIL notification to manager about special requests
3. No way for manager to source items and add to offer
4. Client thinks they're talking to manager, shouldn't need to "address manager by name"

**Example Scenario (from E2E):**
- Client: "Room B for workshop, need projector and flipchart"
- System: "Room B meets requirements with projector and flipchart" ❌
- Reality: Room B has projector (equipment) but flipchart is only listed as "feature" (not included by default)

**Expected Behavior:**

1. **Detection Phase:**
   - Parse client requirements vs. room equipment
   - Identify missing items clearly

2. **Response to Client:**
   > "Room B has a projector but unfortunately the flipchart is not included. Would you like me to check if I can source one? If I find one, I'll add it to your offer."

3. **If Client Confirms:**
   - Create HIL task: "Special Request: Flipchart for Event X"
   - Manager sees task in queue (client doesn't see this)
   - Manager can:
     - **Found it**: Add product to offer with price, send confirmation to client
     - **Not found**: Notify client, client decides to continue or cancel

4. **Product Addition Flow:**
   ```
   Client confirms interest → Manager finds product →
   Manager sends: "I found a flipchart at CHF X. Add to your offer?" →
   Client confirms → Product added to offer →
   If already at Step 4/5: Resend updated offer
   If before Step 4: Add to pending products for offer generation
   ```

**Implementation Considerations:**

1. **Data Model:**
   - Clear distinction: `equipment` (included) vs. `features` (available but separate)
   - Track `requested_items[]` and `missing_items[]` in event state
   - Add `sourced_products[]` for manager-added items

2. **HIL Task Type:**
   - New type: `PRODUCT_SOURCING_REQUEST`
   - Fields: product name, client request context, event_id

3. **Offer Modification:**
   - API for manager to add products to pending/active offers
   - Re-trigger offer generation if already sent

**Related: Client Cancellation Flow** (see DECISION-012)

**Dependencies:**
- Room data cleanup (features vs. equipment)
- HIL task system extension
- Offer modification capability

---

### DECISION-012: Client Event Cancellation Flow

**Date Raised:** 2026-01-06
**Context:** E2E testing - no way for client to cancel an event via email
**Status:** Open

**Problem Statement:**
Clients cannot cancel events via email. This is a critical UX gap:
- Client says "I need to cancel the booking" → System doesn't handle this
- No cancellation intent detection
- No cancellation confirmation flow
- No handling of related site visits

**Expected Behavior:**

1. **Detection:**
   - Detect cancellation intent: "cancel", "abort", "withdraw", "nevermind"
   - Multilingual support (EN/DE/FR/IT/ES)

2. **Cancellation Flow:**
   ```
   Client: "I need to cancel the booking"
   System: "I understand you'd like to cancel. To confirm:
            - Event: [date] at [room]
            - Site visit scheduled: [date] (will be kept unless you want to cancel this too)

            Please confirm: Cancel the event? (Site visit will remain scheduled)"
   Client: "Yes, cancel"
   System: "Your booking has been cancelled. [Site visit info if applicable]"
   ```

3. **Site Visit Handling:**
   - **Site visit BEFORE event date**: Keep by default (client might want to see venue for future booking)
   - **Site visit AFTER event date**: Auto-cancel (makes no sense without the event)
   - **Explicit request to cancel site visit**: Respect client's wish

4. **Event State:**
   ```python
   event_entry["thread_state"] = "Cancelled"
   event_entry["cancellation_reason"] = "Client request"
   event_entry["cancelled_at"] = timestamp
   event_entry["cancelled_by"] = "client"  # vs "manager"
   ```

5. **Notifications:**
   - HIL task: "Event Cancelled by Client: [event summary]"
   - Manager can see cancellation in dashboard

**Implementation Considerations:**

1. **New Intent:**
   - `IntentLabel.CANCEL_EVENT`
   - Add to unified detection and step handlers

2. **Cancellation Detection Patterns:**
   ```python
   CANCELLATION_SIGNALS = {
       "en": ["cancel", "abort", "withdraw", "nevermind", "don't need"],
       "de": ["stornieren", "absagen", "abbrechen", "zurückziehen"],
       "fr": ["annuler", "abandonner", "renoncer"],
       "it": ["annullare", "cancellare", "rinunciare"],
       "es": ["cancelar", "anular", "desistir"],
   }
   ```

3. **Confirmation Required:**
   - Don't auto-cancel on first mention
   - Require explicit confirmation (prevents accidents)

4. **Deposit Handling:**
   - If deposit paid → HIL task for refund decision
   - Reference DECISION-001 for deposit change scenarios

**Dependencies:**
- Cancellation intent detection
- Site visit linkage to main event
- Deposit refund workflow

---

### DECISION-011: Free Local LLMs for Detection Tasks

**Date Raised:** 2026-01-06
**Context:** Multilingual confirmation detection - pattern-based vs. LLM sentiment
**Status:** Open

**Question:** Should we use free local LLMs (e.g., Ollama/Llama 3) for detection tasks that don't require instant responses?

**Background:**
Currently, detection tasks use:
1. **Pattern-based regex** - Fast, free, but needs explicit patterns per language
2. **Cloud LLMs (Claude/Gemini)** - Universal understanding, but API costs

Since the system will implement response timers to appear more human-like (not instant replies), speed is less critical.

**Options:**

| Option | Cost | Speed | Languages | Setup |
|--------|------|-------|-----------|-------|
| **A: Pattern-based** (current) | Free | Instant | Explicit only | None |
| **B: Cloud LLM fallback** | $0.001-0.01/msg | ~1-2s | Any | Already integrated |
| **C: Local LLM (Ollama)** | Free | ~2-5s | Any | Server setup |
| **D: Hugging Face models** | Free | ~0.5-1s | Model-dependent | Python package |

**Use Cases for Local LLM:**
1. **Confirmation detection** - "Is this a yes/no/negotiation?"
2. **Sentiment fallback** - When patterns don't match
3. **Language detection** - More accurate than regex
4. **Intent disambiguation** - Low-confidence cases

**Considerations:**
- Response timers mean 2-5s LLM latency is acceptable
- Ollama requires ~4-8GB RAM for small models
- Can run alongside main server or on separate machine
- Zero marginal cost after setup

**Current Implementation:**
- Pattern-based for confirmation detection (EN/DE/FR/IT/ES)
- Cloud LLM for complex intent classification
- No local LLM integration

**Dependencies:**
- Hardware resources for local LLM
- Ollama or similar runtime setup
- Evaluation of model accuracy vs. cloud LLMs

---

### DECISION-013: Site Visit Timing in Workflow

**Date Raised:** 2026-01-07
**Context:** Site visit scheduling is currently offered in Step 7 (after offer acceptance), but this may not be optimal
**Status:** Open

**Question:** When should the site visit be offered in the workflow?

**Current Implementation:**
- Site visit is offered in Step 7, after the client accepts the offer
- Workflow: Intake → Dates → Room → Offer → Negotiation → **Confirmation (Site Visit here)** → Done

**Problem:**
- Site visit is semi-independent of the main booking flow
- Asking about site visit AFTER offer acceptance feels backwards
- Client might want to see the venue BEFORE committing to the final offer
- Site visit date confirmation could be confused with event date confirmation (both involve date selection)

**Options:**

**Option A: Before Offer (Recommended)**
```
Intake → Dates → Room → [Site Visit?] → Offer → Negotiation → Confirmation
```
- Pro: Client can see venue before final commitment
- Pro: Offer can include "site visit scheduled" as added value
- Pro: More natural flow - see venue → confirm booking
- Con: Extends workflow length

**Option B: Current (After Acceptance)**
```
Intake → Dates → Room → Offer → Negotiation → Confirmation → [Site Visit?]
```
- Pro: Doesn't delay the offer
- Pro: Only engaged clients reach this point
- Con: Feels like an afterthought
- Con: Client already committed before seeing venue

**Option C: Parallel/Any-Time**
```
Site visit can be requested/offered at any step
```
- Pro: Maximum flexibility
- Pro: Client can ask "can I see the room?" at any point
- Con: Complex to implement - needs cross-step detection
- Con: Site visit date might conflict with event date confirmation detection

**Option D: Before Room Selection**
```
Intake → Dates → [Site Visit?] → Room → Offer → ...
```
- Pro: Client sees venue before choosing room
- Con: Too early - haven't even discussed rooms yet
- Con: Delays the main flow significantly

**Implementation Considerations:**

1. **Detection Challenge:**
   - "Site visit date" vs "Event date" confirmation
   - Need clear context markers to distinguish
   - `INTENT_VALID_STEPS` restrictions help prevent confusion

2. **State Management:**
   - `site_visit_scheduled` already tracked
   - Need to ensure it doesn't interfere with main flow state

3. **Manager Coordination:**
   - Site visit requires manager availability
   - HIL task for site visit scheduling already exists

**Recommendation:** Option A (Before Offer) or Option C (Any-Time with smart detection)

**Dependencies:**
- Step handler modifications
- Site visit detection scope review
- E2E testing of new flow position

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