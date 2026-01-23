# Architecture Implementation Plan (2026-01-23)

## Executive Summary

Based on the 2026-01-19 architecture review and E2E verification on 2026-01-23, this plan prioritizes remaining high-impact items. The step3 refactoring has been verified working via Playwright E2E (date change → room conflict → room selection → deposit → confirmation).

## Current State vs. Architecture Review

| File | Jan 19 (LOC) | Jan 23 (LOC) | Change | Status |
|------|--------------|--------------|--------|--------|
| step3_handler.py | 2924 | 1789 | **-39%** | ✅ Refactored |
| step4_handler.py | 1605 | 1121 | **-30%** | ✅ Refactored |
| main.py | 575 | 58 | **-90%** | ✅ Refactored |
| step2_handler.py | 2043 | 2124 | +4% | ⚠️ Needs work |
| step1_handler.py | 1840 | 1916 | +4% | ⚠️ Needs work |
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

---

## Implementation Plan (Prioritized)

### Priority 1: Step 2 God File Reduction (HIGH IMPACT)

**Current State:** 2124 lines, 16 top-level defs
**Target:** < 1000 lines in main handler

**Extraction Targets:**
```
step2_date_confirmation/
├── trigger/
│   ├── step2_handler.py (core routing only, ~800 lines)
│   ├── date_resolution.py (parse, normalize, candidates)
│   ├── confirmation_flow.py (state transitions + HIL)
│   ├── message_formatting.py (greeting assembly)
│   └── qna_bridge.py (Q&A injection)
```

**Why High Priority:**
- Largest handler file (2124 lines)
- Critical path for date changes (core feature)
- Detour source - must remain stable

**Approach:**
1. Add characterization tests for date resolution
2. Extract `date_resolution.py` (ISO normalization, candidate generation)
3. Extract `confirmation_flow.py` (state transitions)
4. Verify E2E: date change detour still works

---

### Priority 2: Step 1 God File Reduction (HIGH IMPACT)

**Current State:** 1916 lines, 8 top-level defs (few functions = large nested blocks)
**Target:** < 900 lines in main handler

**Extraction Targets:**
```
step1_intake/
├── trigger/
│   ├── step1_handler.py (routing only, ~700 lines)
│   ├── event_bootstrap.py (client/event creation)
│   ├── intent_routing.py (classification + guards)
│   ├── entity_merge.py (extraction + profile updates)
│   └── detour_handling.py (date/room/requirements)
```

**Why High Priority:**
- Entry point for all workflows
- Complex intent routing with many branches
- Detour initiation lives here

**Approach:**
1. Map all entry/exit paths with test coverage
2. Extract `event_bootstrap.py` (isolated side effects)
3. Extract `intent_routing.py` (pure function possible)
4. Verify: new intake → smart shortcut → offer path

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
