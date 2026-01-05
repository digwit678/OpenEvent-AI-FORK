# To-Do Next Session

This file tracks active implementation goals and planned roadmap items. **Check this file at the start of every session.**

## 🎯 Primary Focus for Tomorrow
1.  **Finalize Phase 1 Stability:** Ensure all 7 steps pass happy-path and edge-case regression tests.
2.  ~~**Begin Database Consolidation:**~~ ✅ **DONE** - See `DEV_CHANGELOG.md` for 2025-12-29.
3.  **Initiate Gemini Strategy:** Start implementing the dual-engine LLM provider.

---

## 1. Active Implementation Phase (Current Session / Immediate)
*Must be stabilized before moving to full roadmap implementation.*

| Date Identified | Task | Goal | Priority |
| :--- | :--- | :--- | :--- |
| 2025-12-24 | **System Resilience** | Handle diverse client inputs (languages, edge cases) | **Urgent** |
| 2025-12-24 | **Production Stability** | Verified via zero-failure regression runs | **Urgent** |
| 2025-12-24 | **Circular Bug Elimination** | Audit routing loops and special flow guards | **Urgent** |
| 2025-12-24 | **Integration Completion** | Supabase/Hostinger production readiness | **High** |
| 2025-12-24 | **Billing Flow Robustness** | Frontend/Backend session sync stability | **High** |
| ~~2025-12-28~~ | ~~**Documentation Hygiene**~~ | ✅ **DONE 2025-12-28** - Refreshed `tests/TEST_INVENTORY.md`, closed stale checklist items, and updated this roadmap. | ~~**Medium**~~ |
| ~~2025-12-28~~ | ~~**DCON1 – Detection Import Cleanup**~~ | ✅ **DONE 2025-12-28** - Updated tests to import from stable detection/workflow surfaces; verified pytest collect-only and targeted suites. | ~~**High**~~ |
| ~~2025-12-27~~ | ~~**Product Change Mid-Flow (WF0.1)**~~ | ✅ **FIXED 2025-12-28** - Added empty reply safety net in `workflow_email.py` after routing loop. When routing completes with no drafts, a context-aware fallback message is added. | ~~**Medium**~~ |
| ~~2025-12-27~~ | ~~**Billing Address Capture Failure**~~ | ✅ **FIXED 2025-12-28** - Root cause was step corruption (step=3 instead of step=5) due to missing `offer_accepted=True` in step5_handler + guards forcing step during billing flow. See `test_billing_step_preservation.py`. | ~~**High**~~ |
| ~~2025-12-28~~ | ~~**WF0.1: Empty Detour Replies**~~ | ✅ **FIXED 2025-12-28** - Same as above: empty reply safety net in `workflow_email.py`. See `DEV_CHANGELOG.md`. | ~~**High**~~ |

---

## 2. Planned Roadmap (Pending Implementations)
*Detailed plans located in `docs/plans/`.*

| Date Added | Task / Plan | Reference | Priority |
| :--- | :--- | :--- | :--- |
| ~~2025-12-24~~ | ~~**Database Consolidation**~~ | ✅ **DONE 2025-12-29** - Merged 4 JSON files into 2 unified files (`backend/data/rooms.json`, `backend/data/products.json`). Updated 12 adapters. See `DEV_CHANGELOG.md`. | ~~Medium~~ |
| 2025-12-22 | **Dual-Engine (Gemini)** | `docs/plans/active/MIGRATION_TO_GEMINI_STRATEGY.md` | Medium |
| 2025-12-20 | **Detection Improvement** | `docs/plans/completed/DONE__DETECTION_IMPROVEMENT_PLAN.md` | Medium |
| 2025-12-18 | **Multi-Variable Q&A** | `docs/plans/active/MULTI_VARIABLE_QNA_PLAN.md` | Medium |
| 2025-12-15 | **Site Visit Sub-flow** | `docs/plans/active/site_visit_implementation_plan.md` | Medium |
| 2025-12-12 | **Junior Dev Links** | `docs/plans/completed/DONE__JUNIOR_DEV_LINKS_IMPLEMENTATION_GUIDE.md` | Low |
| 2025-12-10 | **Multi-Tenant Expansion** | `docs/plans/active/MULTI_TENANT_EXPANSION_PLAN.md` | Low |
| 2025-12-08 | **Test Pages/Links** | `docs/plans/active/test_pages_and_links_integration.md` | Low |
| 2025-12-05 | **Pseudo-links Calendar** | `docs/plans/active/pseudolinks_calendar_integration.md` | Low |
| 2025-12-01 | **Hostinger Logic Update** | `docs/plans/active/HOSTINGER_UPDATE_PLAN.md` | Medium |
| 2026-01-05 | **Dual-LLM Verification Backup** | See below | Low |

---

## 🔮 Future: Dual-LLM Verification Backup (2026-01-05)

**Status:** PLANNED - Backup mechanism if rule-based sandwich fails too often

**Concept:** Replace or supplement rule-based fact verification with a second LLM call:
1. First LLM generates verbalized text
2. Second LLM (same or different model) verifies: "Given these facts, is this text accurate?"
3. If NO → use fallback text

**Implementation Approach:**
```python
# In universal_verbalizer.py - disabled by default
DUAL_LLM_VERIFICATION = os.getenv("DUAL_LLM_VERIFICATION", "false").lower() == "true"

async def _verify_with_llm(text: str, facts: Dict[str, List[str]]) -> Tuple[bool, str]:
    """Second LLM call to verify first LLM's output."""
    prompt = f"""Given these facts:
    - Dates: {facts.get('dates', [])}
    - Amounts: {facts.get('amounts', [])}
    - Rooms: {facts.get('room_names', [])}
    - Capacities: {facts.get('room_capacities', [])}

    Does this text accurately represent them? Answer YES or NO with explanation.

    Text: {text}"""
    # Call verification LLM...
```

**Trade-offs:**
- ✅ More robust than regex patterns
- ✅ Can catch nuanced hallucinations
- ❌ 2x API cost per message
- ❌ Added latency

**Trigger Criteria:** Enable if rule-based sandwich has >5% false negative rate (misses hallucinations that reach users)

## ✅ FIXED: Verbalizer Text/Data Inconsistency (2026-01-05)

**Status:** FIXED - Room status verification added to `_verify_facts()`

**Issue:** The verbalized response contradicted the structured room data:
- Text said: "Room F **isn't available** that day"
- Structured data showed: "Room F - Status: **available**"

**Fix Applied:**
1. Added `room_statuses` to `extract_hard_facts()` in `MessageContext`
2. Added room availability consistency check in `_verify_facts()`:
   - If LLM claims room "isn't available", verify it matches actual status
   - If status is actually "available"/"option", flag as invented fact
3. When inconsistency detected, fallback text is used instead of hallucinated LLM output

**Files Modified:**
- `backend/ux/universal_verbalizer.py` - Added room status tracking and verification

## ✅ ADDED: Room Capacity Verification (2026-01-05)

**Status:** ADDED - Prevents LLM from claiming rooms fit more people than they can

**Issue Prevented:** LLM could hallucinate capacity claims like "Room A fits 100 people" when actual max is 40.

**Fix Applied:**
1. Added `room_capacities` to `extract_hard_facts()` - extracts `name:capacity_max` pairs
2. Added capacity consistency check in `_verify_facts()`:
   - Detects patterns: "fits X", "holds X", "accommodates X", "X people/guests"
   - If claimed capacity > actual max, flags as invented fact
3. When overclaim detected, fallback text is used

**Test Coverage:**
- 7 new tests in `TestRoomCapacityVerification` class
- Tests cover: extraction, overclaims, "holds up to", "accommodates", exact max, below max, guests pattern

**Files Modified:**
- `backend/ux/universal_verbalizer.py` - Added capacity tracking and verification
- `backend/tests/unit/test_verbalizer_sandwich.py` - Added Section 10 with 7 tests

