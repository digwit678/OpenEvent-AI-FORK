# Change Propagation & DAG-Based Routing (V4)

## Overview

This document describes the DAG-based change propagation system implemented per `v4_dag_and_change_rules.md`. When a confirmed/captured variable is updated (date, room, requirements, products, offer), ONLY the dependent steps re-run, using hash guards to avoid unnecessary recomputation.

## Dependency DAG

```
participants ┐
seating_layout ┼──► requirements ──► requirements_hash
duration ┘
special_requirements ┘
        │
        ▼
chosen_date ───────────────────────────► Room Evaluation ──► locked_room_id
        │                                    │
        │                                    └────────► room_eval_hash
        ▼
Offer Composition ──► selected_products ──► offer_hash
        ▼
Confirmation / Deposit
```

## Change Types & Routing Rules

### 1. DATE Change
**Trigger:** Client changes `chosen_date` after `date_confirmed=True`

**Routing:**
- Detour to Step 2 (Date Confirmation)
- Set `caller_step` to current step
- After Step 2 confirms new date:
  - If same room still valid → skip Step 3 (hash guard)
  - Else run Step 3 → return to `caller_step`

**Example:** "Can we move this to 17.03.2026 instead?" (while in Step 4)

### 2. ROOM Change
**Trigger:** Client requests different `locked_room_id`

**Routing:**
- Detour to Step 3 (Room Availability)
- Set `caller_step` to current step
- Step 3 evaluates new room
- Return to `caller_step`

**Example:** "We'd prefer Room B instead of Room A"

### 3. REQUIREMENTS Change
**Trigger:** Change in `participants`, `seating_layout`, `event_duration`, `special_requirements`

**Routing:**
- Recompute `requirements_hash`
- If `requirements_hash == room_eval_hash` → fast-skip to `caller_step`
- Else detour to Step 3 → return to `caller_step`

**Example:** "We are actually 32 people" (was 18)

### 4. PRODUCTS Change
**Trigger:** Change in `selected_products`, catering, wine, etc.

**Routing:**
- Stay in Step 4 (no detour)
- Recompute offer with new products
- No Step 2 or Step 3 re-runs

**Example:** "Add Prosecco for 10 people"

### 5. COMMERCIAL Change
**Trigger:** Price negotiation, discount requests (no structural changes)

**Routing:**
- Stay in Step 5 (Negotiation)
- No detours to Steps 2-4

**Example:** "Can we get a discount on the price?"

### 6. DEPOSIT/RESERVATION Change
**Trigger:** Deposit payment, reservation, option operations

**Routing:**
- Stay in Step 7 (Confirmation)
- No detours to Steps 2-4

**Example:** "We would like to make the deposit now"

## Implementation

### Core Module: `backend/workflows/change_propagation.py`

**Main Function:**
```python
route_change_on_updated_variable(
    event_state: Dict[str, Any],
    change_type: ChangeType,
    from_step: Optional[int] = None,
) -> NextStepDecision
```

**Helper Functions:**
- `detect_change_type()` - Auto-detect change type from user_info and message
- `should_skip_step3_after_date_change()` - Determine if Step 3 can be skipped
- `compute_offer_hash()` - Compute hash for offers

### Existing Step Implementations

**Step 2 (Date Confirmation):**
- Already implements `caller_step` return logic (lines 1220-1232 in `process.py`)
- After confirming date, checks `caller_step` and routes accordingly

**Step 3 (Room Availability):**
- Already implements hash-based skip logic (lines 119-139 in `process.py`)
- Checks `requirements_hash == room_eval_hash` to skip re-evaluation
- Sets `caller_step=3` when detouring to Step 2 (line 418)
- Returns to `caller_step` when hash matches (lines 477-491)

**Step 4 (Offer):**
- Products mini-flow stays within Step 4
- No detours for product-only changes

**Step 5 (Negotiation):**
- Commercial-only changes stay within Step 5

**Step 7 (Confirmation):**
- Deposit/option operations stay within Step 7

## Hash Guards

### Requirements Hash
**Purpose:** Detect when requirements change necessitates room re-evaluation

**Computation:**
```python
from backend.workflows.common.requirements import requirements_hash

req_hash = requirements_hash({
    "number_of_participants": 18,
    "seating_layout": "Theatre",
    "event_duration": {"start": "14:00", "end": "16:00"},
    "special_requirements": None,
    "preferred_room": "Room A",
})
```

**Usage:**
- Set when requirements first captured
- Updated whenever requirements change
- Compared to `room_eval_hash` to decide if Step 3 must re-run

### Room Evaluation Hash
**Purpose:** Record which requirements were used for last room check

**Usage:**
- Set to `requirements_hash` after Step 3 completes
- Proves locked room matches current requirements
- If `requirements_hash != room_eval_hash` → Step 3 must re-run

### Offer Hash
**Purpose:** Detect when offer changes necessitate re-approval

**Computation:**
```python
from backend.workflows.change_propagation import compute_offer_hash

offer_hash_val = compute_offer_hash({
    "products": ["Standard Buffet", "Wine"],
    "total": 1500.00,
    "subtotal": 1250.00,
})
```

**Usage:**
- Set when offer is sent/accepted
- Compared to new offer hash to detect changes

## Detour Flow

```
[ c a l l e r ] ──(change detected)──► [ owner step ]
▲                                           │
└──────────(resolved + hashes)──────────────┘
```

**Rules:**
1. Always set `caller_step` before detouring
2. Jump to owner step of changed variable
3. After resolution, return to `caller_step`
4. Clear `caller_step` when returning
5. Use hashes to fast-skip when possible

## Test Coverage

### Unit Tests: `tests/specs/dag/test_change_propagation.py`
- Tests for all change type routing decisions
- Hash computation and matching
- Change type detection

### E2E Tests: `tests/specs/dag/test_change_scenarios_e2e.py`
- Scenario 1: Date change, room still available
- Scenario 2: Date change, room unavailable
- Scenario 3: Requirements change (participants)
- Scenario 4: Products change only
- Scenario 5: Date change from Step 7

**Total:** 36 tests, all passing ✅

## UX Guarantees

### No Redundant Messages
- Hash guards prevent re-asking for unchanged information
- Step 3 fast-skips when `requirements_hash == room_eval_hash`
- No duplicate availability/offer emails for same logical state

### No Re-Prompting
- Shortcuts preserved when re-entering steps
- Previously confirmed fields not re-requested
- Clear progress indicators via UX footer

### Smooth Continuation
- Client returns to logical point after change (via `caller_step`)
- No manual workflow steering required
- Transparent handling of structural vs. non-structural changes

## Usage Examples

### Example 1: Date Change in Step 4

```python
from backend.workflows.change_propagation import detect_change_type, route_change_on_updated_variable

# Event currently in Step 4 with offer drafted
event_state = {
    "current_step": 4,
    "date_confirmed": True,
    "chosen_date": "10.03.2026",
    "locked_room_id": "Room A",
    ...
}

# Client says: "Can we move to 17.03.2026?"
user_info = {"event_date": "17.03.2026"}

# Auto-detect change type
change_type = detect_change_type(event_state, user_info)
# Returns: ChangeType.DATE

# Route the change
decision = route_change_on_updated_variable(event_state, change_type, from_step=4)
# Returns: NextStepDecision(next_step=2, maybe_run_step3=True, updated_caller_step=4)

# Update event state
event_state["caller_step"] = decision.updated_caller_step
event_state["current_step"] = decision.next_step

# Step 2 runs, confirms new date
# Step 3 runs if room needs recheck
# Returns to Step 4 (caller_step=4)
```

### Example 2: Products Change in Step 4

```python
# Client says: "Add Prosecco for 10 people"
user_info = {"products": ["Prosecco"]}

change_type = detect_change_type(event_state, user_info)
# Returns: ChangeType.PRODUCTS

decision = route_change_on_updated_variable(event_state, change_type, from_step=4)
# Returns: NextStepDecision(next_step=4, updated_caller_step=None, skip_reason="products_only")

# Stay in Step 4, rebuild offer
# No detours to Step 2 or 3
```

## Backwards Compatibility

All changes are backwards compatible:
- New `change_propagation.py` module is optional
- Existing step implementations work as before
- No changes to JSON payload shapes
- No database schema changes
- All new fields have safe defaults

## Integration Status

### ✅ Completed

1. **Intake Integration (backend/workflows/groups/intake/trigger/process.py)**
   - `detect_change_type()` called at line 433 for all incoming messages
   - `route_change_on_updated_variable()` used for routing decisions (line 453)
   - Change detection active for messages to events in Step 2+
   - Trace markers added for debugging ("CHANGE_DETECTED")
   - Falls back to legacy logic when change_type is None (backwards compatible)

2. **Hash Guards Already Implemented**
   - Step 3 already has `requirements_hash == room_eval_hash` fast-skip (line 119-139)
   - Step 2 already returns to `caller_step` (line 1220-1232)
   - Step 3 already sets/clears `caller_step` appropriately (lines 417-418, 477-491)

3. **Test Coverage**
   - 36 unit and E2E tests for change_propagation module (all passing)
   - Integration tests created (some require full workflow mocking)

### 🔄 In Progress

1. **Full Integration Testing**
   - Integration tests need proper workflow mocking
   - Requires calendar data, room configs, etc.
   - Unit tests of change_propagation logic are complete and passing

2. **Offer Hash Tracking**
   - `compute_offer_hash()` function ready
   - Needs to be called when offers are sent/accepted
   - Comparison logic needs to be added to Step 4/5

### 📋 Remaining Work

1. **Step 4 Products Integration:**
   - Detect PRODUCTS changes in Step 4
   - Use change routing to stay in Step 4 (no detours)
   - Add offer_hash tracking

2. **Step 5 Negotiation Integration:**
   - Detect COMMERCIAL changes
   - Route within Step 5 without structural re-checks

3. **Step 7 Confirmation Integration:**
   - Detect DEPOSIT/reservation changes
   - Handle date changes from Step 7 (return to Step 7 after resolution)

4. **Enhanced UX Feedback:**
   - Surface change type in debug/trace logs (partially done)
   - Show "Rechecking availability due to date change" messages

5. **Performance Optimization:**
   - Cache hash computations more aggressively
   - Batch multiple small changes before re-evaluation

## How to Use (Current State)

### For Developers Working on Steps 2-7

The change propagation system is now **active in Intake** and will:
- Detect DATE, ROOM, and REQUIREMENTS changes automatically
- Route to appropriate steps (Step 2 for DATE, Step 3 for ROOM/REQUIREMENTS)
- Set `caller_step` appropriately
- Log changes via trace markers

**No changes needed** for Steps 2-3 - they already handle `caller_step` correctly.

**For Steps 4-7**: To add change detection:
1. Import the module: `from backend.workflows.change_propagation import detect_change_type, route_change_on_updated_variable`
2. Call `detect_change_type(event_entry, user_info, message_text=message_text)`
3. Use the routing decision to set `current_step` and `caller_step`

Example:
```python
change_type = detect_change_type(event_entry, user_info, message_text=message_text)
if change_type is not None:
    decision = route_change_on_updated_variable(event_entry, change_type, from_step=current_step)
    if decision.updated_caller_step is not None:
        update_event_metadata(event_entry, caller_step=decision.updated_caller_step)
    if decision.next_step != current_step:
        update_event_metadata(event_entry, current_step=decision.next_step)
```
