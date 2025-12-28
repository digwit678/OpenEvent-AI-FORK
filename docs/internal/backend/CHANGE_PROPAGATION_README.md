# Change Propagation System

## Overview

The change propagation system provides **deterministic routing** when clients revise confirmed variables during the booking workflow. It implements DAG-based detours that preserve caller context and use hash guards to prevent redundant re-runs.

**Key Principles:**
1. **Change detection runs BEFORE Q&A dispatch** to prevent clients from being bypassed
2. **Precise pattern recognition** requires: confirmed variable mention + change intent signal + new value
3. **All gatekeeping variables are changeable** (date, room, attendees, products, deposit, site visit, etc.)
4. **Hash guards prevent redundant re-evaluation** when dependencies haven't changed

## Architecture

### Execution Order

```
Incoming Message
    │
    ▼
[Change Detection] ←─── RUNS FIRST
    │
    ├─ Change Detected? ──► Route to owner step → Detour & Return
    │
    └─ No Change ──► [Q&A Detection]
                          │
                          ├─ General Q&A? ──► Handle via general_room_qna
                          │
                          └─ No Q&A ──► [Step-Specific Business Logic]
```

### Change Types & Routing

| Change Type | Owner Step | Description | Example Phrases |
|-------------|-----------|-------------|-----------------|
| **DATE** | Step 2 | Event date change | "move to March 15", "change date to Friday" |
| **ROOM** | Step 3 | Room size/preference change | "switch to larger room", "boardroom instead" |
| **REQUIREMENTS** | Step 3 | Attendees, layout, duration, special needs | "60 attendees now", "U-shape seating", "add projector" |
| **PRODUCTS** | Step 4 | Catering, add-ons, equipment | "upgrade coffee setup", "add lunch package" |
| **COMMERCIAL** | Step 5 | Pricing, terms, discounts | "lower rate to 120/head", "adjust budget" |
| **DEPOSIT** | Step 7 | Payment terms, deposit amount | "30% deposit instead", "split payment" |
| **SITE_VISIT** | Step 7 | Site visit scheduling | "move site visit to Tuesday", "reschedule tour" |
| **CLIENT_INFO** | In-place | Billing, contact, company details | "update invoice address", "new phone number" |

### Routing Decision Matrix

**From Step 4 (Offer):**

| Change Type | Next Step | Caller Preserved? | Hash Update |
|-------------|-----------|-------------------|-------------|
| DATE | 2 | ✅ caller=4 | `date_confirmed` reset |
| ROOM | 3 | ✅ caller=4 | `room_eval_hash` refreshed |
| REQUIREMENTS | 3 | ✅ caller=4 | `requirements_hash` → `room_eval_hash` |
| PRODUCTS | 4 | ❌ (same step) | None (in-place update) |

**From Step 5 (Negotiation):**

| Change Type | Next Step | Caller Preserved? | Hash Update |
|-------------|-----------|-------------------|-------------|
| DATE | 2 | ✅ caller=5 | `date_confirmed` reset |
| ROOM | 3 | ✅ caller=5 | `room_eval_hash` refreshed |
| REQUIREMENTS | 3 | ✅ caller=5 | `requirements_hash` → `room_eval_hash` |
| PRODUCTS | 4 | ✅ caller=5 | None |
| COMMERCIAL | 5 | ❌ (same step) | None (in-place loop) |

**From Step 7 (Confirmation):**

| Change Type | Next Step | Caller Preserved? | Hash Update |
|-------------|-----------|-------------------|-------------|
| DATE | 2 | ✅ caller=7 | `date_confirmed` reset |
| ROOM | 3 | ✅ caller=7 | `room_eval_hash` refreshed |
| REQUIREMENTS | 3 | ✅ caller=7 | `requirements_hash` → `room_eval_hash` |
| DEPOSIT | 7 | ❌ (same step) | None (in-place update) |
| SITE_VISIT | 7 | ❌ (same step) | None (in-place update) |

## Change Detection Heuristics

### Three-Part Pattern Recognition

Change detection requires **all three components**:

1. **Confirmed Variable Mention** - The variable must already exist in event state
2. **Change Intent Signal** - Verb or marker indicating modification
3. **New Value Present** - User provides replacement value or asks to change

### Intent Signal Keywords

**Change Verbs (14):**
```python
change, switch, modify, update, adjust, move to, shift,
upgrade, downgrade, swap, replace, amend, revise, alter
```

**Redefinition Markers (12):**
```python
actually, instead, rather, correction, make it, make that,
in fact, no wait, sorry, i meant, to be clear, let me correct
```

### Domain-Specific Keywords

**PRODUCTS (28 keywords):**
```python
catering, coffee, lunch, dinner, breakfast, snacks, beverages,
menu, food, drinks, equipment, setup, services,
projector, screen, whiteboard, microphone, sound system,
upgrade, package, premium, deluxe, standard, basic,
add-ons, extras, amenities, refreshments
```

**COMMERCIAL (19 keywords):**
```python
price, pricing, cost, total, budget, discount, negotiate,
rate, fee, charge, quote, estimate, affordable,
cheaper, expensive, payment terms, installment, financing, rebate
```

**DEPOSIT (14 keywords):**
```python
deposit, payment, reserve, option, hold, upfront,
prepayment, advance payment, down payment, installment,
reservation fee, booking fee, retainer, security deposit
```

**REQUIREMENTS (participants, layout, duration):**
```python
# Participants: attendees, participants, guests, people, headcount, capacity
# Layout: seating, layout, arrangement, boardroom, U-shape, theater, classroom
# Duration: hours, duration, start time, end time, until, from-to
# Special: projector, whiteboard, catering notes, accessibility
```

### Regex-Based Proximity Matching

The system uses regex to detect change verbs near target nouns:

```python
# Pattern: (change_verb) .{0,50} (target_noun)
# Allows up to ~10 words between verb and noun

extract_change_verbs_near_noun(
    message_text="Could we upgrade the coffee setup to premium?",
    target_nouns=["coffee", "catering", "menu"]
)
# Returns: True (verb "upgrade" within 50 chars of "coffee")
```

### Helper Functions

**Requirement Update Detection:**
```python
has_requirement_update(event_state, user_info) -> bool
```
Checks if `user_info` contains any of: `participants`, `seating_layout`, `start_time`, `end_time`, `duration`, `special_requirements`, etc.

**Product Update Detection:**
```python
has_product_update(event_state, user_info) -> bool
```
Checks if `user_info` contains `selected_products` or product-related fields.

**Change Intent Detection:**
```python
has_change_intent(message_text) -> bool
```
Scans for change verbs or redefinition markers using case-insensitive matching.

## Hash Guard Behavior

### Hash Types

1. **`requirements_hash`** - SHA256 of `{participants, seating_layout, duration, special_requirements}`
2. **`room_eval_hash`** - Snapshot of `requirements_hash` when room was last evaluated
3. **`offer_hash`** - Snapshot of commercial terms when offer was accepted

### Fast-Skip Conditions

**Skip Step 3 (Room Re-evaluation):**
```python
if requirements_hash == room_eval_hash:
    # Requirements haven't changed since last room check
    # Return to caller_step without re-running Step 3
    skip_reason = "requirements_hash_match"
    needs_reeval = False
```

**Example Flow:**
```
Step 5 → Client updates billing address (CLIENT_INFO change)
→ requirements_hash UNCHANGED
→ room_eval_hash MATCHES
→ Skip Step 3, stay in Step 5 ✅
```

### Hash Invalidation Triggers

| Change Type | Invalidates | Effect |
|-------------|------------|--------|
| DATE | `date_confirmed` flag | Forces Step 2 re-run |
| ROOM (explicit) | `locked_room_id`, `room_eval_hash` | Forces Step 3 re-run |
| REQUIREMENTS | `requirements_hash` | Triggers Step 3 if `requirements_hash ≠ room_eval_hash` |
| PRODUCTS | None | In-place update, no upstream invalidation |
| COMMERCIAL | None | Step 5 loop, no hash invalidation |

## Integration Points

### Step-Specific Trigger Files

**Step 3 (Room Availability):**
`backend/workflows/groups/room_availability/trigger/process.py:107-204`

```python
# [CHANGE DETECTION + Q&A] Tap incoming stream BEFORE room evaluation
change_type = detect_change_type(event_entry, user_info, message_text=message_text)

if change_type is not None:
    decision = route_change_on_updated_variable(event_entry, change_type, from_step=3)
    # ... handle detour ...
    return GroupResult(action="change_detour", payload=payload, halt=False)
```

**Step 4 (Offer):**
`backend/workflows/groups/offer/trigger/process.py:50-145`

**Step 5 (Negotiation):**
`backend/workflows/groups/negotiation_close.py:57-82`

**Step 7 (Confirmation):**
`backend/workflows/groups/event_confirmation/trigger/process.py:57-85`

### Core Change Propagation Module

`backend/workflows/change_propagation.py` provides:

- `ChangeType` enum (8 types)
- `NextStepDecision` dataclass (routing result)
- `detect_change_type(event_state, user_info, message_text)` - Main detection entry point
- `route_change_on_updated_variable(event_state, change_type, from_step)` - Routing logic
- Helper functions for requirement/product updates

## Test Coverage

### Unit Tests (Routing Logic)

`tests/workflows/test_change_routing_steps4_7.py` - 324 lines

**Test Classes:**
- `TestStep4RoutingLogic` - PRODUCTS, DATE, ROOM, REQUIREMENTS routing from Step 4
- `TestStep5RoutingLogic` - COMMERCIAL, DATE, ROOM, PRODUCTS routing from Step 5
- `TestStep7RoutingLogic` - DEPOSIT, SITE_VISIT, DATE, ROOM, REQUIREMENTS routing from Step 7
- `TestClientInfoRouting` - CLIENT_INFO stays in current step
- `TestCallerStepPreservation` - Caller context preserved during detours
- `TestHashGuardLogic` - Hash match/mismatch scenarios
- `TestComplexDetourScenarios` - Multi-step cascades

**Example Test:**
```python
def test_requirements_change_hash_match_skips_step3(self):
    """REQUIREMENTS change with hash match → fast-skip, return to caller."""
    event_state = {
        "current_step": 4,
        "caller_step": 5,
        "requirements_hash": "abc123",
        "room_eval_hash": "abc123",  # MATCH
    }
    decision = route_change_on_updated_variable(
        event_state, ChangeType.REQUIREMENTS, from_step=4
    )
    assert decision.next_step == 5  # Return to caller
    assert decision.skip_reason == "requirements_hash_match"
    assert decision.needs_reeval is False
```

### Heuristic Tests (Pattern Matching)

`tests/workflows/test_change_detection_heuristics.py` - 478 lines

**Test Classes:**
- `TestDateChangeDetection` - Date pattern recognition
- `TestRoomChangeDetection` - Room preference changes
- `TestRequirementsChangeDetection` - Attendees, layout, duration
- `TestProductsChangeDetection` - Catering, add-ons, equipment
- `TestCommercialChangeDetection` - Pricing, budget, discounts
- `TestDepositChangeDetection` - Payment terms, deposit amount
- `TestSiteVisitChangeDetection` - Site visit scheduling
- `TestClientInfoChangeDetection` - Billing, contact updates
- `TestExpandedHeuristics` - Natural phrasing (upgrade, adjust, etc.)
- `TestFalsePositiveAvoidance` - Questions vs. change requests
- `TestEdgeCases` - Ambiguous inputs

**Example Tests:**
```python
def test_upgrade_package_triggers_products_change(self):
    """'Could we upgrade to the premium coffee setup?' → PRODUCTS change."""
    message_text = "Could we upgrade to the premium coffee setup?"
    change_type = detect_change_type(event_state, user_info, message_text)
    assert change_type == ChangeType.PRODUCTS

def test_question_about_price_no_change(self):
    """'What's the total price?' → None (no change intent)."""
    message_text = "What's the total price?"
    change_type = detect_change_type(event_state, {}, message_text)
    assert change_type is None  # Question, not change request
```

### E2E Tests (Integration Scenarios)

`tests/workflows/test_change_integration_e2e.py` - 721 lines

**Helper Builders:**
- `build_base_event(step, **kwargs)` - Base event factory
- `build_confirmed_event_at_step4(**kwargs)` - Step 4 with date/room confirmed
- `build_negotiation_event_at_step5(**kwargs)` - Step 5 with offer sent
- `build_confirmation_event_at_step7(**kwargs)` - Step 7 with offer accepted

**Scenario Tests:**
- `TestQnATriggeredRequirementChange` - Q&A → Step 3 detour → return to Step 4
- `TestOfferStageProductSwap` - Multiple product changes stay in Step 4
- `TestNegotiationStageBudgetAdjustment` - Budget change loops in Step 5
- `TestConfirmationStageMultiChange` - Deposit + date multi-change precedence
- `TestHashGuardPreventingRedundantReruns` - Hash guards skip redundant reruns
- `TestComplexDetourReturnFlow` - Step 7 → Step 2 → Step 3 → Step 7 cascade

**Example E2E Flow:**
```python
def test_qna_triggers_requirement_increase_then_detour(self):
    """
    Client asks Q&A about capacity → capacity increases from 30 to 60
    → triggers REQUIREMENTS change → detours to Step 3 → returns to Step 4.
    """
    event = build_confirmed_event_at_step4(
        requirements={"number_of_participants": 30, "seating_layout": "boardroom"}
    )
    user_info = {"number_of_participants": 60}  # Capacity increase

    change_type = detect_change_type(event, user_info, message_text="Actually 60 attendees now")
    assert change_type == ChangeType.REQUIREMENTS

    decision = route_change_on_updated_variable(event, change_type, from_step=4)
    assert decision.next_step == 3  # Detour to Step 3
    assert decision.updated_caller_step == 4  # Preserve caller
    assert decision.needs_reeval is True
```

## Developer Usage Examples

### Example 1: Detecting Change in Step Trigger

```python
from backend.workflows.change_propagation import (
    detect_change_type,
    route_change_on_updated_variable,
)

# In your step trigger (e.g., Step 4 offer/trigger/process.py)
def process(state: GroupState) -> GroupResult:
    event_entry = state.event_entry
    user_info = state.user_info or {}
    message_text = _message_text(state)

    # [1] Detect change BEFORE business logic
    change_type = detect_change_type(event_entry, user_info, message_text=message_text)

    if change_type is not None:
        # [2] Route change to owner step
        decision = route_change_on_updated_variable(event_entry, change_type, from_step=4)

        # [3] Build detour payload
        payload = {
            "trace": "CHANGE_DETECTED",
            "change_type": change_type.value,
            "next_step": decision.next_step,
            "caller_step": decision.updated_caller_step,
            "skip_reason": decision.skip_reason,
            "needs_reeval": decision.needs_reeval,
        }

        # [4] Return detour action
        return GroupResult(action="change_detour", payload=payload, halt=False)

    # [5] No change detected → continue with step logic
    # ... (Q&A detection, business logic, etc.)
```

### Example 2: Testing Change Detection

```python
from backend.workflows.change_propagation import detect_change_type, ChangeType

# Build test event
event = {
    "event_id": "evt_001",
    "current_step": 5,
    "chosen_date": "2025-03-15",
    "locked_room_id": "room_a",
    "requirements": {"number_of_participants": 30, "seating_layout": "boardroom"},
}

# Simulate user input
user_info = {"number_of_participants": 60}  # Capacity increase
message_text = "Actually we need space for 60 people now"

# Detect change
change_type = detect_change_type(event, user_info, message_text=message_text)

assert change_type == ChangeType.REQUIREMENTS  # ✅ Detected correctly
```

### Example 3: Handling Hash Guards

```python
from backend.workflows.change_propagation import route_change_on_updated_variable, ChangeType
from backend.workflows.utils.hashing import requirements_hash

# Build event with matching hashes
requirements = {"number_of_participants": 30, "seating_layout": "boardroom"}
req_hash = requirements_hash(requirements)

event = {
    "current_step": 5,
    "caller_step": None,
    "requirements": requirements,
    "requirements_hash": req_hash,
    "room_eval_hash": req_hash,  # MATCH → skip Step 3
}

# Route REQUIREMENTS change
decision = route_change_on_updated_variable(event, ChangeType.REQUIREMENTS, from_step=5)

# Hash match triggers fast-skip
assert decision.skip_reason == "requirements_hash_match"
assert decision.needs_reeval is False
assert decision.next_step == 5  # Stay in Step 5 (no detour)
```

## Debugging & Tracing

### Trace Markers

**CHANGE_DETECTED:**
```json
{
  "trace": "CHANGE_DETECTED",
  "change_type": "REQUIREMENTS",
  "next_step": 3,
  "caller_step": 4,
  "skip_reason": null,
  "needs_reeval": true
}
```

**QNA_CLASSIFY:**
```json
{
  "trace": "QNA_CLASSIFY",
  "is_general": true,
  "confidence": 0.85,
  "topic": "availability"
}
```

### Logging

Enable debug mode to see state transitions:
```bash
export WF_DEBUG_STATE=1
uvicorn backend.main:app --reload --port 8000
```

### Test with Verbose Output

```bash
pytest tests/workflows/test_change_integration_e2e.py::TestQnATriggeredRequirementChange::test_qna_triggers_requirement_increase_then_detour -v
```

## Common Patterns & Anti-Patterns

### ✅ DO

1. **Always run change detection before Q&A:**
   ```python
   change_type = detect_change_type(...)
   if change_type is not None:
       # Handle change detour

   qna_result = detect_general_room_query(...)
   if qna_result.get("is_general"):
       # Handle Q&A
   ```

2. **Preserve caller_step during detours:**
   ```python
   decision = route_change_on_updated_variable(event, change_type, from_step=4)
   if decision.updated_caller_step:
       event["caller_step"] = decision.updated_caller_step
   ```

3. **Check hash guards before re-running Step 3:**
   ```python
   if decision.skip_reason == "requirements_hash_match":
       # Fast-skip Step 3, return to caller
       return GroupResult(action="return_to_caller", ...)
   ```

### ❌ DON'T

1. **Don't run Q&A before change detection:**
   ```python
   # WRONG: Client gets Q&A response, change is missed
   qna_result = detect_general_room_query(...)
   change_type = detect_change_type(...)  # Too late!
   ```

2. **Don't skip hash computation:**
   ```python
   # WRONG: Missing hash leads to redundant reruns
   event["requirements_hash"] = None  # Should be computed!
   ```

3. **Don't ignore skip_reason:**
   ```python
   # WRONG: Re-runs Step 3 even when hash matches
   if change_type == ChangeType.REQUIREMENTS:
       run_step3()  # Should check decision.skip_reason first!
   ```

## Performance Considerations

### Hash Computation Caching

Hash computation is **deterministic** and should be **cached** in event state:

```python
from backend.workflows.utils.hashing import requirements_hash

# Compute once when requirements change
requirements = {"number_of_participants": 60, "seating_layout": "U-shape"}
event["requirements_hash"] = requirements_hash(requirements)

# Reuse cached hash for future comparisons
if event["requirements_hash"] == event["room_eval_hash"]:
    # Fast-skip Step 3
```

### Change Detection Complexity

- **Keyword matching:** O(n) where n = message length
- **Regex matching:** O(m * n) where m = number of patterns, n = message length
- **Overall:** Sub-millisecond for typical message lengths (<500 chars)

### Test Execution Times

```bash
# Unit tests (routing logic): ~0.5s
pytest tests/workflows/test_change_routing_steps4_7.py

# Heuristic tests (pattern matching): ~1.2s
pytest tests/workflows/test_change_detection_heuristics.py

# E2E tests (integration scenarios): ~2.5s
pytest tests/workflows/test_change_integration_e2e.py
```

## Future Enhancements

### Planned Features

1. **Multi-change detection** - Handle multiple changes in single message
2. **Confidence scoring** - Return confidence level for each change type
3. **Change history tracking** - Audit log of all detected changes
4. **LLM-assisted disambiguation** - Use LLM for ambiguous cases (e.g., "upgrade" could be PRODUCTS or COMMERCIAL)
5. **User confirmation prompts** - "Did you mean to change X to Y?" for high-impact changes

### Extensibility

To add a new change type:

1. Add to `ChangeType` enum in `backend/workflows/change_propagation.py`
2. Add routing logic in `route_change_on_updated_variable()`
3. Add keywords/patterns to `detect_change_type()`
4. Add unit tests in `tests/workflows/test_change_routing_steps4_7.py`
5. Add heuristic tests in `tests/workflows/test_change_detection_heuristics.py`
6. Add E2E scenarios in `tests/workflows/test_change_integration_e2e.py`
7. Update this README with new change type documentation

## References

### Related Documentation

- `backend/workflow/specs/v4_dag_and_change_rules.md` - Dependency DAG and minimal re-run matrix
- `backend/workflow/specs/no_shortcut_way_v4.md` - Complete state machine with entry guards
- `backend/workflow/specs/v4_shortcuts_and_ux.md` - Shortcut capture policy
- `CLAUDE.md` - Project overview and development guide

### Key Files

- `backend/workflows/change_propagation.py` - Core change detection logic (517 lines)
- `tests/workflows/test_change_routing_steps4_7.py` - Routing unit tests (324 lines)
- `tests/workflows/test_change_detection_heuristics.py` - Heuristic tests (478 lines)
- `tests/workflows/test_change_integration_e2e.py` - E2E integration tests (721 lines)

### Test Commands

```bash
# Run all change propagation tests
pytest tests/workflows/test_change*.py -v

# Run specific test class
pytest tests/workflows/test_change_routing_steps4_7.py::TestHashGuardLogic -v

# Run with coverage
pytest tests/workflows/ --cov=backend/workflows/change_propagation --cov-report=html
```

---

**Last Updated:** 2025-11-15
**Version:** v4 (DAG-based change propagation with hash guards)
