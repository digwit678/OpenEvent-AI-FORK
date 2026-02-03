# Open Tasks (Updated 2026-02-03)

> Verified against current codebase. Most historical tasks have been completed.

---

## Active Tasks

### LLM Gateway Consolidation
**Status:** Not started
**Priority:** Medium (nice-to-have, not blocking)
**Context:** LLM calls go through `workflows/llm/adapter.py` but retry/timeout logic could be more centralized.
**Proposed:** Create `workflows/llm/gateway.py` as single entry point for all LLM calls.
**Note:** Current setup works fine - this is architectural cleanup, not a bug fix.

### God Files Remaining Extractions
**Status:** Low priority - defer until touching these files
**Still Pending:**
- Step 4 Offer: Extract preconditions, pricing assembly, offer composition
- Step 5 Negotiation: Extract billing capture, response assembly
- Universal Verbalizer: Split prompt building from verification
- Change Propagation: Extract detection, normalization, routing as pure functions

**Note:** Step 2 & Step 3 extractions are complete. Remaining extractions should happen opportunistically when modifying these files.

---

## Future Roadmap (Mar 2026+)

*No high-priority items remaining - site visit and time slot features completed.*

---

## Low Priority / Verify Later

### Multi-Tenant Expansion
**Status:** Not started - future expansion
**Tasks:** `team_id` columns, RLS policies, email routing
**Priority:** Low

### Supabase Offer Line Items
**Status:** Verify during next Supabase integration work
**File:** `workflows/io/integration/supabase_adapter.py`
**Priority:** Low

---

## Completed (Removed from Active List)

The following were verified as complete:

**Recent Session (Feb 2026):**
- ✅ Site Visit LLM Detection (`is_site_visit_change` signal in unified detection + router uses it)
- ✅ Capacity Limit Handling (`handle_capacity_exceeded` in `detour_handling.py`)
- ✅ Data Path Consolidation (all services use `data/rooms.json`, `data/products.json`)
- ✅ Routing Pipeline Consolidation (`pre_route.py` unifies guards, shortcuts, billing, detours)
- ✅ **On-Demand Site Visit Scheduling** (site visits at any step 2-7, `confirm_pending` state)
- ✅ **Mandatory Time Slot Booking** (`use_time_range_mode`, configurable `range_start_hour`/`range_end_hour`/`slot_duration_minutes`)
- ✅ **Duration-Aware Overlap Detection** (`duration_minutes` stored per booking for accurate conflict detection)

**Previous Sessions:**
- ✅ Activity Logger Integration (all hooks implemented)
- ✅ Global Field Capture System (`capture_fields_anytime`)
- ✅ Hybrid Prompt Injection Defense (`has_injection_attempt` signal)
- ✅ Time Validation for Event Times (`time_validation.py`)
- ✅ Production Entrypoint Split (`app.py`)
- ✅ Prompt Customization Guardrails (feature-flagged)
- ✅ JWT Auth + Admin Role Guards
- ✅ Site Visit Time Extraction (separate field handling)
- ✅ QNA_GUARD LLM-first fixes
- ✅ Step 2 date confirmation refactoring extractions
- ✅ Step 3 room availability refactoring extractions
- ✅ Detour Date Confirmation Regression fix
- ✅ Hybrid Messages (Acceptance + Q&A) fix
