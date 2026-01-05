# Test Suite Reorganization Plan

**Generated:** 2025-11-27
**Purpose:** Propose a clear directory structure for tests aligned with Workflow v3/v4 and identify migration actions.

---

## Proposed Directory Structure

```
tests/
├── unit/                           # Fast, isolated unit tests
│   ├── step1_intake/               # Step 1 - Intake & Data Capture
│   ├── step2_date/                 # Step 2 - Date Confirmation
│   ├── step3_room/                 # Step 3 - Room Availability
│   ├── step4_offer/                # Step 4 - Offer Preparation
│   ├── step5_negotiation/          # Step 5 - Negotiation Close
│   ├── step6_transition/           # Step 6 - Transition Checkpoint
│   ├── step7_confirmation/         # Step 7 - Event Confirmation
│   ├── nlu/                        # Intent classification, entity extraction
│   ├── qna/                        # General Q&A handling
│   ├── common/                     # Shared utilities (datetime, hashes, etc.)
│   └── providers/                  # LLM provider tests
│
├── integration/                    # Tests involving multiple components
│   ├── detours/                    # Detour and caller_step logic
│   ├── change_propagation/         # DAG-based change routing
│   ├── gatekeeping/                # HIL gates, P1-P4 prerequisites
│   └── flows/                      # Multi-step flow integration
│
├── e2e/                            # End-to-end tests
│   ├── stubbed/                    # Stubbed LLM e2e tests
│   └── live/                       # Live OpenAI e2e tests (CI skip)
│
├── regression/                     # Regression tests for known bugs
│
├── ux/                             # UX/frontend-related tests
│   └── debug/                      # Debug panel, trace contract tests
│
├── _legacy/                        # Legacy v3 tests (xfail, reference only)
│   ├── smoke/
│   └── workflows/
│
├── fixtures/                       # Test data fixtures (JSON)
├── stubs/                          # Stubbed adapters and responses
├── utils/                          # Test utilities
└── specs/                          # YAML flow specifications
    └── flows/
```

---

## Migration Actions

### Phase 1: Keep in Place (No Change Needed)

These files are well-organized and should remain:

| Current Location | Reason |
|------------------|--------|
| `tests/specs/intake/` | Already organized by step |
| `tests/specs/date/` | Already organized by step |
| `tests/specs/room/` | Already organized by step |
| `tests/specs/products_offer/` | Already organized by step |
| `tests/specs/detours/` | Clear purpose |
| `tests/specs/gatekeeping/` | Clear purpose |
| `tests/specs/nlu/` | Clear purpose |
| `tests/specs/determinism/` | Clear purpose |
| `tests/specs/providers/` | Clear purpose |
| `tests/specs/ux/` | Clear purpose |
| `tests/specs/dag/` | Clear purpose |
| `tests/_legacy/` | Already isolated |
| `tests/fixtures/` | Already organized |
| `tests/stubs/` | Already organized |
| `tests/utils/` | Already organized |

### Phase 2: Recommended Moves

| Current Location | Proposed Location | Reason |
|------------------|-------------------|--------|
| `tests/gatekeeping/test_room_marked_selected_only_after_action.py` | `tests/specs/room/` | Room-related gatekeeping |
| `tests/gatekeeping/test_room_selection_advances_to_step4.py` | `tests/specs/room/` | Room-related gatekeeping |
| `tests/room/test_rank_rooms_by_prefs.py` | `tests/specs/room/` | Room-related unit test |
| `tests/flows/test_flow_specs.py` | Keep but fix | YAML flow tests are valuable |
| `tests/e2e_v4/test_full_flow_stubbed.py` | `tests/e2e/stubbed/` | Better organization |
| `tests/regression/test_matrix_param_loader.py` | Keep | Clear purpose |
| `tests/ux/test_step3_no_catering_in_body_before_room.py` | DELETE or populate | Empty file |
| `tests/e2e/test_live_smoke.py` | DELETE or populate | Empty file |

### Phase 3: Consolidate Workflow Tests

| Current Location | Proposed Location | Reason |
|------------------|-------------------|--------|
| `tests/workflows/qna/` | `tests/specs/qna/` | Align with specs structure |
| `tests/workflows/intake/` | `tests/specs/intake/` | Align with specs structure |
| `tests/workflows/date/` | `tests/specs/date/` | Align with specs structure |
| `tests/workflows/common/` | `tests/specs/common/` | Align with specs structure |
| `tests/workflows/test_change_detection_heuristics.py` | `tests/specs/dag/` | Change detection belongs with DAG |
| `tests/workflows/test_change_routing_steps4_7.py` | `tests/specs/dag/` | Change routing belongs with DAG |
| `tests/workflows/test_change_integration_e2e.py` | `tests/specs/dag/` | Change integration belongs with DAG |
| `tests/workflows/test_offer_product_operations.py` | `tests/specs/products_offer/` | Offer operations |
| `tests/workflows/test_offer_menu_pricing.py` | `tests/specs/products_offer/` | Offer pricing |
| `tests/workflows/test_hil_progression.py` | `tests/specs/gatekeeping/` | HIL-related |

### Phase 4: Backend Tests

| Current Location | Proposed Location | Reason |
|------------------|-------------------|--------|
| `backend/tests/smoke/test_workflow_v3_agent.py` | Keep | Backend smoke test |
| `backend/tests_integration/` | Keep | Live integration tests |

---

## Immediate Cleanup Actions (Safe Now)

### 1. Delete Empty Placeholder Files

```bash
# These files are empty (1 line each) and serve no purpose
rm tests/ux/test_step3_no_catering_in_body_before_room.py
rm tests/e2e/test_live_smoke.py
```

### 2. Legacy Tests Already Isolated

The `tests/_legacy/` directory is properly marked with `pytest.mark.legacy` and `xfail`. No action needed.

### 3. Create Missing `__init__.py` Files

Ensure all test directories have proper `__init__.py` files for import resolution.

---

## Test Naming Conventions (Proposed)

### File Naming
- `test_<feature>_<scenario>.py` - Specific feature tests
- `test_<step>_<behavior>.py` - Step-specific tests

### Test Function Naming
- `test_<action>_<expected_outcome>` - Clear cause/effect
- `test_<scenario>_when_<condition>` - Conditional scenarios

### Examples
```python
# Good
test_intake_captures_email_from_signature()
test_date_confirmation_sets_flag_when_single_feasible()
test_room_lock_requires_hil_approval()
test_detour_returns_to_caller_step_after_resolution()

# Avoid
test_1()
test_it_works()
test_stuff()
```

---

## Test Coverage Goals (Steps 1-4 Focus)

### Step 1 - Intake (Current: Good)
- [x] Entity capture (email, date, capacity)
- [x] Shortcut capture and reuse
- [x] Intent classification routing
- [ ] Low-confidence → manual review escalation
- [ ] Product detection in intake messages

### Step 2 - Date Confirmation (Current: Good)
- [x] next5 classifications (none/one/many)
- [x] Blackout and buffer rules
- [x] Vague date handling (month + weekday)
- [ ] Relative date parsing ("next Friday")
- [ ] Quoted confirmation handling (regression)

### Step 3 - Room Availability (Current: Good)
- [x] Room search classification (available/option/unavailable)
- [x] Hash guards for re-evaluation
- [x] Room status progression
- [ ] Calendar conflict detection
- [ ] Buffer violation handling

### Step 4 - Offer (Current: Fair)
- [x] Offer compose with footer
- [x] Products mini-flow paths
- [x] Special request HIL loop
- [ ] Product add/remove/update operations (1 failing)
- [ ] Menu pricing calculations
- [ ] Billing address validation

### Detours (Current: Good)
- [x] Only dependent steps re-run
- [x] No redundant asks with shortcuts
- [ ] Cross-step recovery scenarios

### Change Propagation (Current: Needs Work)
- [ ] Date change routing (4 failing)
- [ ] Room change routing (failing)
- [ ] Requirements change routing (failing)
- [ ] Products change routing (failing)

---

## Failing Tests Triage

### Priority 1: Fix These First (Core Functionality)

| Test | Issue | Action |
|------|-------|--------|
| `test_change_propagation.py` (4 failures) | Change detection API evolved | Update test expectations or fix API |
| `test_change_scenarios_e2e.py` (5 failures) | State transition expectations | Align with v4 behavior |
| `test_change_integration_e2e.py` (5 failures) | Integration expectations | Align with v4 behavior |

### Priority 2: Update Expectations

| Test | Issue | Action |
|------|-------|--------|
| `test_general_room_qna_*.py` (7 failures) | Q&A path expectations outdated | Update fixtures/assertions |
| `test_flow_specs.py` (5 failures) | YAML fixtures need update | Align YAML with v4 |

### Priority 3: Minor Fixes

| Test | Issue | Action |
|------|-------|--------|
| `test_offer_product_operations.py` (1 failure) | Quantity update logic | Fix assertion or logic |
| `test_verbalizer.py` (1 failure) | Fallback format | Update expected format |
| `test_confirmation_window_recovery.py` (1 failure) | Relative date edge case | Fix parsing or expectation |

---

## Next Steps

1. **Immediate:** Delete empty placeholder files
2. **Short-term:** Consolidate `tests/workflows/` into `tests/specs/` structure
3. **Medium-term:** Fix failing change propagation tests (core v4 functionality)
4. **Ongoing:** Add missing coverage for Steps 5-7 and edge cases
5. **Maintenance:** Keep `tests/_legacy/` for regression reference, remove if v3 fully deprecated

---

## References

- `CLAUDE.md` - Project guidance and workflow documentation
- `docs/guides/TEAM_GUIDE.md` - Known issues and fixes
- `backend/workflow/specs/` - V4 workflow specifications
- `tests/TEST_INVENTORY.md` - Current test inventory
