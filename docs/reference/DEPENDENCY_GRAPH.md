# OpenEvent Dependency Graph

This document maps the dependencies between modules to help AI agents and developers understand the codebase structure and avoid missing related files when making changes.

## Quick Reference: Where to Find Things

| What you need | Where to find it |
|---------------|------------------|
| Intent classification | `backend/detection/intent/classifier.py` |
| All keyword patterns | `backend/detection/keywords/buckets.py` |
| Acceptance/decline detection | `backend/detection/response/` |
| Detour detection | `backend/detection/change/detour.py` |
| Q&A detection | `backend/detection/qna/` |
| Manager request detection | `backend/detection/special/manager_request.py` |
| Room conflict detection | `backend/detection/special/room_conflict.py` |
| Fallback message wrapping | `backend/core/fallback.py` |
| Error handling utilities | `backend/core/errors.py` |

---

## Detection Module Dependencies

```
backend/detection/keywords/buckets.py  (SOURCE OF TRUTH - all patterns)
│
├── backend/detection/intent/classifier.py
│   ├── Uses: WORKFLOW_SIGNALS, _detect_qna_types patterns
│   └── Called by: All workflow steps for message classification
│
├── backend/detection/intent/confidence.py
│   ├── Uses: WORKFLOW_SIGNALS for has_workflow_signal()
│   └── Called by: All workflow steps for confidence gating
│
├── backend/detection/response/acceptance.py
│   ├── Uses: ACCEPTANCE_PATTERNS, CONFIRMATION_SIGNALS_*
│   └── Called by: Steps 2, 3, 4, 5, 7
│
├── backend/detection/response/decline.py
│   ├── Uses: DECLINE_SIGNALS_*, DECLINE_PATTERNS
│   └── Called by: Steps 4, 5, 7
│
├── backend/detection/response/counter.py
│   ├── Uses: COUNTER_PATTERNS
│   └── Called by: Steps 4, 5
│
├── backend/detection/response/confirmation.py
│   ├── Uses: CONFIRMATION_SIGNALS_*, ENHANCED_CONFIRMATION_KEYWORDS
│   └── Called by: Steps 2, 3, 4, 5, 7
│
├── backend/detection/change/detour.py
│   ├── Uses: CHANGE_VERBS_*, REVISION_MARKERS_*, TARGET_PATTERNS
│   └── Called by: Steps 2, 3, 4, 5
│
├── backend/detection/qna/general_qna.py
│   ├── Uses: PURE_QA_SIGNALS_*, ACTION_REQUEST_PATTERNS
│   └── Called by: Steps 2, 3, 4
│
├── backend/detection/qna/sequential_workflow.py
│   ├── Uses: Step action patterns, next step question patterns
│   └── Called by: Steps 2, 3, 4
│
├── backend/detection/special/manager_request.py
│   ├── Uses: Manager request patterns
│   └── Called by: Step 1, all steps
│
└── backend/detection/special/nonsense.py
    ├── Uses: is_gibberish patterns, WORKFLOW_SIGNALS
    └── Called by: All workflow steps (early gate)
```

---

## Workflow Step Dependencies

### Step 1: Intake
```
backend/workflows/steps/step1_intake/
│
├── DEPENDS ON:
│   ├── backend/detection/intent/classifier.py     # classify_intent()
│   ├── backend/detection/special/manager_request.py
│   ├── backend/detection/special/nonsense.py      # gibberish gate
│   └── backend/workflows/io/database.py           # event creation
│
└── CALLED BY:
    └── backend/workflow_email.py                  # Main orchestrator
```

### Step 2: Date Confirmation
```
backend/workflows/steps/step2_date_confirmation/
│
├── DEPENDS ON:
│   ├── backend/detection/response/confirmation.py # is_confirmation()
│   ├── backend/detection/change/detour.py        # detect_change_type()
│   ├── backend/detection/qna/general_qna.py      # detect_general_room_query()
│   ├── backend/detection/qna/sequential_workflow.py
│   ├── backend/workflows/shared/datetime/        # date parsing
│   └── backend/workflows/io/database.py
│
└── CALLED BY:
    └── backend/workflow_email.py
```

### Step 3: Room Availability
```
backend/workflows/steps/step3_room_availability/
│
├── DEPENDS ON:
│   ├── backend/detection/response/acceptance.py
│   ├── backend/detection/change/detour.py
│   ├── backend/detection/qna/general_qna.py
│   ├── backend/detection/special/room_conflict.py
│   ├── backend/workflows/shared/qna/             # Q&A composition
│   └── backend/workflows/io/database.py
│
└── CALLED BY:
    └── backend/workflow_email.py
```

### Step 4: Offer
```
backend/workflows/steps/step4_offer/
│
├── DEPENDS ON:
│   ├── backend/detection/response/acceptance.py
│   ├── backend/detection/response/decline.py
│   ├── backend/detection/response/counter.py
│   ├── backend/detection/change/detour.py
│   ├── backend/workflows/shared/pricing/
│   ├── backend/ux/universal_verbalizer.py
│   └── backend/workflows/io/database.py
│
└── CALLED BY:
    └── backend/workflow_email.py
```

### Step 5: Negotiation
```
backend/workflows/steps/step5_negotiation/
│
├── DEPENDS ON:
│   ├── backend/detection/response/*              # All response patterns
│   ├── backend/detection/change/detour.py
│   └── backend/workflows/io/database.py
│
└── CALLED BY:
    └── backend/workflow_email.py
```

### Step 7: Confirmation
```
backend/workflows/steps/step7_confirmation/
│
├── DEPENDS ON:
│   ├── backend/detection/response/acceptance.py
│   ├── backend/detection/response/decline.py
│   ├── backend/detection/special/room_conflict.py
│   └── backend/workflows/io/database.py
│
└── CALLED BY:
    └── backend/workflow_email.py
```

---

## LLM Integration Dependencies

```
backend/llm/
│
├── providers/
│   ├── openai_provider.py                    # OpenAI API calls
│   └── base.py                               # Provider interface
│
├── provider_registry.py                      # Provider selection
│   └── Uses: AGENT_MODE env var
│
├── intent_classifier.py                      # BEING MOVED to detection/intent/
│   └── TO BE: backend/detection/intent/classifier.py
│
└── verbalizer_agent.py
    ├── Uses: backend/ux/universal_verbalizer.py
    └── Called by: All steps for draft composition
```

---

## Error/Fallback Dependencies

```
backend/core/
│
├── errors.py
│   ├── OpenEventError, DetectionError, WorkflowError, LLMError
│   ├── safe_operation() context manager
│   └── USED BY: All modules that need error handling
│
└── fallback.py
    ├── FallbackContext, wrap_fallback()
    ├── USED BY:
    │   ├── backend/workflows/llm/adapter.py
    │   ├── backend/workflows/qna/verbalizer.py
    │   ├── backend/workflows/common/general_qna.py
    │   └── All step trigger files
    └── ENV: OE_FALLBACK_DIAGNOSTICS=true/false
```

---

## Database Dependencies

```
backend/workflows/io/database.py
│
├── PROVIDES:
│   ├── load_db(), save_db()                  # File-based JSON store
│   ├── db.events.*, db.clients.*, db.tasks.* # Entity operations
│   └── FileLock protection
│
├── USED BY:
│   ├── All workflow steps
│   ├── backend/main.py (API endpoints)
│   └── backend/workflow_email.py
│
└── STORAGE:
    └── backend/events_database.json
```

---

## Test Dependencies

```
backend/tests/detection/                      # Detection-specific tests
├── test_acceptance.py                        # Tests acceptance patterns
├── test_decline.py                           # Tests decline patterns
├── test_detour_detection.py                  # Tests detour detection
├── test_change_detection.py                  # Tests change type detection
├── test_qna_detection.py                     # Tests Q&A detection
├── test_sequential_workflow.py               # Tests sequential workflow
├── test_manager_request.py                   # Tests manager request detection
├── test_low_confidence_handling.py           # Tests nonsense gate
├── test_semantic_matchers.py                 # Tests pattern matching
└── test_confidence.py                        # Tests confidence scoring

backend/tests/flow/                           # End-to-end workflow tests
├── test_happy_path_step1_to_4.py
└── test_room_conflict.py

backend/tests/regression/                     # Regression tests
├── test_team_guide_bugs.py
└── test_security_prompt_injection.py
```

---

## Change Impact Matrix

When you change these files, also check these related files:

| If you change... | Also check... |
|------------------|---------------|
| `detection/keywords/buckets.py` | ALL detection modules, ALL tests |
| `detection/intent/classifier.py` | All step handlers, workflow_email.py |
| `detection/response/*.py` | Steps 2-7 handlers |
| `detection/change/detour.py` | Steps 2-5 handlers, change_propagation tests |
| `detection/qna/*.py` | Steps 2-4 handlers, Q&A tests |
| `core/fallback.py` | All fallback paths in workflow steps |
| `core/errors.py` | All error handling code |
| `workflows/io/database.py` | All steps, main.py, integration tests |

---

## File Location Quick Reference (After Refactoring)

### Current → New Location

| Current Path | New Path |
|--------------|----------|
| `llm/intent_classifier.py` | `detection/intent/classifier.py` |
| `workflows/nlu/keyword_buckets.py` | `detection/keywords/buckets.py` |
| `workflows/nlu/semantic_matchers.py` | `detection/response/*.py` |
| `workflows/nlu/general_qna_classifier.py` | `detection/qna/general_qna.py` |
| `workflows/nlu/sequential_workflow.py` | `detection/qna/sequential_workflow.py` |
| `workflows/change_propagation.py` | `detection/change/detour.py` |
| `workflows/common/confidence.py` | `detection/intent/confidence.py` |
| `workflows/common/conflict.py` | `detection/special/room_conflict.py` |
| `workflows/groups/intake/` | `workflows/steps/step1_intake/` |
| `workflows/groups/date_confirmation/` | `workflows/steps/step2_date_confirmation/` |
| `workflows/groups/room_availability/` | `workflows/steps/step3_room_availability/` |
| `workflows/groups/offer/` | `workflows/steps/step4_offer/` |
| `workflows/groups/negotiation_close.py` | `workflows/steps/step5_negotiation/` |
| `workflows/groups/transition_checkpoint.py` | `workflows/steps/step6_transition/` |
| `workflows/groups/event_confirmation/` | `workflows/steps/step7_confirmation/` |
| `workflows/common/` | `workflows/shared/` |
| `workflows/planner/` | `workflows/orchestration/` |
