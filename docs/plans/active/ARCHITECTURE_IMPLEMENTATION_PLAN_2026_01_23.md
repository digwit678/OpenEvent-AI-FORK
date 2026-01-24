# Architecture Implementation Plan (2026-01-23)

## Executive Summary

Based on the 2026-01-19 architecture review and E2E verification on 2026-01-23, this plan prioritizes remaining high-impact items. The step3 refactoring has been verified working via Playwright E2E (date change → room conflict → room selection → deposit → confirmation).

## Current State vs. Architecture Review

| File | Jan 19 (LOC) | Current (LOC) | Change | Status |
|------|--------------|---------------|--------|--------|
| step3_handler.py | 2924 | 1789 | **-39%** | ✅ Refactored |
| step4_handler.py | 1605 | 1121 | **-30%** | ✅ Refactored |
| main.py | 575 | 58 | **-90%** | ✅ Refactored |
| step2_handler.py | 2124 | **1292** | **-39%** | ✅ Refactored |
| step1_handler.py | 1916 | **799** | **-58%** | ✅ Refactored |
| change_propagation.py | 1460 | 1567 | +7% | ⚠️ Needs work |
| step5_handler.py | 1316 | 1314 | stable | 🔶 Lower priority |
| universal_verbalizer.py | 1313 | 1307 | stable | 🔶 Lower priority |
| llm/adapter.py | 822 | 822 | unchanged | 🔶 Lower priority |

### Issues Resolved Since Review

1. ✅ **BUG-045**: Cross-client room conflict detection (status field duality fixed)
2. ✅ **LLM-first detection**: Signal merging implemented (`_merge_signal_flags()`)
3. ✅ **QNA_GUARD bypass**: Detours now correctly bypass Q&A guards
4. ✅ **Hybrid message handling**: Acceptance + Q&A in same message works
5. ✅ **Step 3 extraction**: 8 modules extracted (conflict_resolution, room_ranking, etc.)

### Step 2 Extraction Progress (2026-01-24)

| Commit | Module | Lines | Functions Extracted |
|--------|--------|-------|---------------------|
| 1830137 | `candidate_presentation.py` | 313 | 11 presentation functions |
| 6660bdd | `date_context.py` | 186 | 6 context resolution functions |
| 629c930 | D-COLL: collection/prioritization | -90 | Uses existing candidate_dates.py functions |
| beaf328 | `prioritize_by_day_hints` | +45 | 1 dedup helper in candidate_dates.py |
| **NEW** | `confirmation_flow.py` | **772** | 6 confirmation flow functions |

**Extracted modules summary:**
- `confirmation_flow.py` (772 lines): `resolve_confirmation_window`, `handle_partial_confirmation`, `prompt_confirmation`, `finalize_confirmation`, `clear_step2_hil_tasks`, `apply_step2_hil_decision`
- `candidate_dates.py` (771 lines): Collection, prioritization, candidate generation
- `candidate_presentation.py` (310 lines): Display formatting
- `date_context.py` (186 lines): Context resolution

**Total step2_handler.py reduction**: 2124 → **1292 lines** (**-832 lines, -39%**)

---

## Implementation Plan (Prioritized)

### Priority 1: Step 2 God File Reduction ✅ COMPLETE

**Status:** 2124 → **1292 lines** (-39%)
**Target:** < 1000 lines *(Close - 292 lines over target)*

**Extracted Modules:**
```
step2_date_confirmation/
├── trigger/
│   ├── step2_handler.py       (1292 lines - routing + presentation)
│   ├── confirmation_flow.py   (772 lines - state transitions + HIL)
│   ├── candidate_dates.py     (771 lines - collection/prioritization)
│   ├── candidate_presentation.py (310 lines - formatting)
│   ├── date_context.py        (186 lines - context resolution)
│   ├── confirmation.py        (290 lines - pure helpers)
│   └── ... other modules
```

**Verification:**
- ✅ 44/46 DAG tests passing
- ✅ Date confirmation tests passing (3/3)
- ⚠️ 2 failures unrelated to extraction (step3 import, routing issue)

---

### Priority 2: Step 1 God File Reduction ✅ COMPLETE

**Current State:** 1916 → **799 lines** (-58%, **EXCEEDED TARGET**)
**Target:** < 900 lines in main handler ✅

**Extracted Modules:**
```
step1_intake/
├── trigger/
│   ├── step1_handler.py (799 lines - orchestration only)
│   ├── classification_extraction.py (340 lines - LLM classification + entity extraction)
│   ├── change_application.py (280 lines - DAG routing + room lock management)
│   └── requirements_fallback.py (180 lines - requirements processing with fallback)
```

**Why High Priority:**
- Entry point for all workflows
- Complex intent routing with many branches
- Detour initiation lives here

**Extraction Completed (2026-01-24):**
1. ✅ Extracted `classification_extraction.py` (LLM calls + tracing)
2. ✅ Extracted `change_application.py` (DAG routing decisions)
3. ✅ Extracted `requirements_fallback.py` (requirements merge logic)
4. ✅ Verified: new intake → smart shortcut → offer path (Full E2E Playwright passed)

**Verification:**
- ✅ 30/30 intake tests passing
- ✅ 75/76 DAG tests passing (1 pre-existing failure)
- ✅ Full E2E Playwright test passed (hybrid acceptance, date-change detour, billing, deposit, site visit)

---

### Priority 3: Change Propagation Modularization (MEDIUM-HIGH)

**Current State:** 1567 lines, 23 defs
**Target:** < 800 lines in main module

**Extraction Targets:**
```
workflows/
├── change_propagation.py (routing decisions only, ~500 lines)
├── change_detection/
│   ├── detector.py (intent + target detection)
│   ├── normalizer.py (date/room normalization)
│   └── disambiguator.py (clarification prompts)
```

**Why Medium-High Priority:**
- All detour logic flows through here
- Heuristic-heavy with sparse error handling
- Refactoring risk: detour regressions

**Approach:**
1. Add invariant tests from `tests/specs/dag/test_change_scenarios_e2e.py`
2. Extract detection logic as pure functions
3. Keep routing decisions in main module
4. Verify: date change, room change, requirements change flows

---

### Priority 4: LLM Gateway Consolidation (MEDIUM)

**Current State:** Multiple LLM call paths scattered across:
- `workflows/llm/adapter.py` (822 lines)
- `ux/universal_verbalizer.py` (1307 lines)
- Direct SDK calls in step handlers

**Target:** Single gateway interface for all LLM calls

**Plan:**
1. Create `workflows/llm/gateway.py` with unified interface
2. Consolidate retry/timeout logic
3. Move heuristic overrides to separate `heuristics.py`
4. Route all LLM calls through gateway

**Why Medium Priority:**
- Improves testability (mock single point)
- Centralizes fallback behavior
- Lower regression risk (read path, not state changes)

---

### Priority 5: Step 5 Negotiation Cleanup (LOWER)

**Current State:** 1314 lines, 17 defs
**Target:** < 800 lines

**Notes:** Stable since review. Defer unless touching billing/negotiation flow.

---

### Priority 6: Universal Verbalizer Refactor (LOWER)

**Current State:** 1307 lines
**Target:** Split prompt building from verification

**Notes:** Core safety logic (hard-facts). High risk, defer unless adding new fact types.

---

## PR Sequence (Recommended)

| PR | Feature | Risk | Verification |
|----|---------|------|--------------|
| 1 | Step 2 date_resolution.py extraction | Medium | E2E: date change detour |
| 2 | Step 2 confirmation_flow.py extraction | Medium | E2E: date confirmation |
| 3 | Step 1 event_bootstrap.py extraction | Medium | E2E: new event intake |
| 4 | Step 1 intent_routing.py extraction | High | Full regression suite |
| 5 | Change propagation detector.py | Medium | Detour test matrix |
| 6 | LLM gateway consolidation | Low | LLM fallback tests |

---

## E2E Verification Checkpoints

Before each PR merge, verify these flows still work:

1. **Smart Shortcut**: Full event details → direct offer
2. **Date Change Detour**: Offer → date change → room check → new offer
3. **Room Conflict**: Date change to blocked date → alternatives shown
4. **Hybrid Message**: Acceptance + Q&A → advance step + answer
5. **Billing Flow**: Accept → billing capture → deposit → confirmation
6. **Site Visit**: Post-deposit → site visit prompt

---

## Notes

- Each extraction should follow the step3 pattern: thin re-export shims for public imports
- Add characterization tests BEFORE extracting
- Atomic commits per extraction
- Update `DEV_CHANGELOG.md` after each PR

---

## Open Questions

1. Should `change_propagation.py` move under `workflows/routing/`?
2. Is the `workflow/` vs `workflows/` package duality worth fixing now?
3. Should we create a shared `workflows/common/qna_bridge.py` for all steps?

---

*Created: 2026-01-23*
*Based on: ARCHITECTURE_REVIEW_AND_PLAN_2026_01_19.md*
*Verified: E2E Playwright test for room change detour flow*
