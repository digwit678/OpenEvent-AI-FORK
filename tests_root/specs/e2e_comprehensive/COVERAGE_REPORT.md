# E2E Comprehensive Test Coverage Report

## Overview

This test suite provides systematic coverage for:
- **Detours** from all workflow steps with DAG verification
- **Q&A** from all steps without workflow interference
- **Hybrid messages** combining actions with Q&A
- **Site visits** from all steps with isolation guarantees

## Test File Summary

| File | Tests | Focus |
|------|-------|-------|
| `test_detours_from_all_steps.py` | ~30 | Detour routing + DAG verification |
| `test_qna_from_all_steps.py` | ~40 | Q&A detection without step changes |
| `test_hybrid_from_all_steps.py` | ~25 | Combined action + Q&A handling |
| `test_site_visit_from_all_steps.py` | ~20 | Site visit flow + isolation |
| **Total** | **~115** | |

---

## Detour Matrix

| Variable | Step 2 | Step 3 | Step 4 | Step 5 | Step 6 | Step 7 |
|----------|--------|--------|--------|--------|--------|--------|
| **Date** | N/A | [ ] | [ ] | [ ] | [ ] | [ ] |
| **Room** | [ ] | N/A | [ ] | [ ] | [ ] | [ ] |
| **Participants** | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| **Billing** | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| **Products** | N/A | N/A | [ ] | [ ] | [ ] | [ ] |

**Legend:** ✓ = Passed | ✗ = Failed | - = N/A | [ ] = Not yet run

### Routing Rules (from DAG)

- **DATE** → Step 2 (maybe_run_step3=True)
- **ROOM** → Step 3
- **PARTICIPANTS** → Step 3 (if hash mismatch) or fast-skip
- **BILLING** → In-place (no routing)
- **PRODUCTS** → Stay in Step 4 or route to Step 4

---

## Q&A Matrix

| Q&A Type | Step 2 | Step 3 | Step 4 | Step 5 | Step 6 | Step 7 |
|----------|--------|--------|--------|--------|--------|--------|
| **rooms_by_feature** | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| **catering_for** | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| **parking_policy** | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| **free_dates** | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| **site_visit_overview** | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| **room_features** | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |

### Q&A Invariants

- Q&A detected without routing/step changes
- No fallback/stub responses
- Workflow continues normally after Q&A

---

## Hybrid Matrix

| Combination | Steps Tested | Status |
|-------------|--------------|--------|
| Confirm + parking Q&A | 2, 3 | [ ] |
| Accept + catering Q&A | 4, 5 | [ ] |
| Date detour + Q&A | 4, 5, 6, 7 | [ ] |
| Room detour + Q&A | 4, 5, 6, 7 | [ ] |
| Participant change + Q&A | 4, 5, 6, 7 | [ ] |
| Billing + Q&A | 4, 5, 6, 7 | [ ] |

### Hybrid Requirements

- Both action AND Q&A processed in same turn
- Q&A section appears when Q&A present
- Q&A section absent when no Q&A
- Detour priority: action routes first, Q&A answered in response

---

## Site Visit Matrix

| Operation | Step 2 | Step 3 | Step 4 | Step 5 | Step 6 | Step 7 |
|-----------|--------|--------|--------|--------|--------|--------|
| **Initiation** | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| **Date Selection** | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| **Time Selection** | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |
| **Isolation** | [ ] | [ ] | [ ] | [ ] | [ ] | [ ] |

### Site Visit Invariants

- Can be initiated from any step (2-7)
- State isolated from main workflow
- Does not affect chosen_date or locked_room_id
- Scheduled visits acknowledged in final confirmation

---

## DAG Verification

| Test | Status |
|------|--------|
| Date change routes to Step 2 | [ ] |
| Room change routes to Step 3 | [ ] |
| Requirements hash match fast-skip | [ ] |
| Requirements hash mismatch re-runs Step 3 | [ ] |
| Products change stays/returns to Step 4 | [ ] |
| caller_step preserved across detours | [ ] |
| Offer regenerated after structural changes | [ ] |

---

## Running Tests

```bash
# Run all comprehensive E2E tests
pytest tests_root/specs/e2e_comprehensive/ -v

# Run specific categories
pytest tests_root/specs/e2e_comprehensive/test_detours_from_all_steps.py -v
pytest tests_root/specs/e2e_comprehensive/test_qna_from_all_steps.py -v
pytest tests_root/specs/e2e_comprehensive/test_hybrid_from_all_steps.py -v
pytest tests_root/specs/e2e_comprehensive/test_site_visit_from_all_steps.py -v

# Run with markers
pytest -m "v4" tests_root/specs/e2e_comprehensive/
```

---

## Bugs Found

| Bug ID | Test ID | Description | Status |
|--------|---------|-------------|--------|
| | | | |

---

## Notes

- Tests use stub mode by default (`AGENT_MODE=stub`)
- For live LLM tests: `AGENT_MODE=openai pytest ...`
- Coverage report should be updated after each test run
