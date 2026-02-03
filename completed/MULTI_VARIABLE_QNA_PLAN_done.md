# Multi-Variable Q&A and Hybrid Question Detection Plan

## Problem Statement

The current system handles single-variable Q&A (e.g., "what dates are available?") but fails when clients ask multi-variable informative questions that span multiple workflow steps in a single sentence:

**Example:** "Could you please let us know if you have availability for those dates and what package options you recommend?"
- Dates/Rooms → Step 2 (Date Confirmation)
- Packages/Products → Step 4 (Offer)

Current behavior: Only addresses Step 2 question, ignores package inquiry.

---

## Key Insight: Leverage Existing LLM Calls

Every incoming message at every step **already runs through some processing** that can extract requirements. The solution must be **general** - it must work regardless of which step the user is at (Step 1, 2, 3, 4, 5, 6, or 7).

### Where Extraction Currently Happens

1. **Step 1 (Intake):** `extract_user_information()` via LLM → extracts all fields
2. **Steps 2-7:** `capture_user_fields()` reads from `state.user_info` - but user_info must be populated somewhere

**Gap:** At Steps 2+, the system relies on regex/keyword matching or re-uses intake data, NOT fresh LLM extraction on each message.

### Proposed Solution: Unified Extraction Hook

Add a **single extraction point** that runs on EVERY incoming client message, regardless of step:

```python
# backend/workflows/common/qna_extraction.py

def extract_qna_context(text: str, stored_requirements: Dict[str, Any]) -> QnAContext:
    """
    Extract Q&A variables and any new requirements from client message.

    This runs on EVERY incoming message at ANY step.

    Returns:
        QnAContext with:
        - qna_variables: List[str]  # ["dates", "packages", "rooms", etc.]
        - new_requirements: Dict[str, Any]  # Any requirements mentioned in Q&A
        - conflicts: List[Conflict]  # Detected conflicts with stored requirements
        - is_informative: bool  # True if just asking, not confirming
        - has_confirmation_intent: bool  # True if confirming something
        - has_hil_intent: bool  # True if special manager request
        - has_detour_intent: bool  # True if requesting change
    """
```

---

## Solution Architecture

### Phase 1: Q&A Variable Detection (Regex + Keywords)

Detect which gatekeeping variables the question touches using existing keyword buckets:

```python
# backend/workflows/nlu/qna_variable_detector.py

QNA_VARIABLE_KEYWORDS = {
    "dates": ["available dates", "free dates", "which days", "when", "availability"],
    "rooms": ["room", "rooms", "space", "venue", "capacity"],
    "packages": ["package", "packages", "options", "offers", "pricing", "cost"],
    "products": ["catering", "menu", "equipment", "add-ons", "products"],
    "features": ["features", "equipment", "projector", "screen", "whiteboard"],
}

QNA_VARIABLE_TO_STEP = {
    "dates": 2,
    "rooms": 3,
    "packages": 4,
    "products": 4,
    "features": 3,
}

def detect_qna_variables(text: str) -> List[str]:
    """Detect which workflow variables the question asks about."""
    variables = []
    lowered = text.lower()
    for var_name, keywords in QNA_VARIABLE_KEYWORDS.items():
        if any(kw in lowered for kw in keywords):
            variables.append(var_name)
    return variables

def spans_multiple_steps(variables: List[str]) -> bool:
    """Check if Q&A variables span different workflow steps."""
    steps = {QNA_VARIABLE_TO_STEP.get(v, 0) for v in variables}
    return len(steps) > 1
```

### Phase 2: Intent Classification Enhancement

Extend the existing intent classification (at ANY step) to detect hybrid patterns:

```python
# backend/workflows/nlu/hybrid_detector.py

def detect_hybrid_question(text: str) -> HybridResult:
    """
    Detect conjuncted questions with mixed intents.

    Handles cases like:
    - "Confirm date X and tell me what packages are available" (confirmation + Q&A)
    - "We need to change the room, also what menus do you have?" (detour + Q&A)
    - "Please ask the manager about the discount, and what rooms fit 50 people?" (HIL + Q&A)

    Returns:
        HybridResult:
            is_hybrid: bool
            workflow_part: Optional[str]  # confirmation/detour/hil/none
            qna_part: Optional[str]  # the informative question part
            qna_variables: List[str]  # variables in Q&A part
    """

    # Look for conjunctors that split sentences
    CONJUNCTORS = [" and ", " also ", ", and ", ", also ", ". Also", ". And"]

    # Check for confirmation/detour/HIL signals in first part
    confirmation_signals = _has_confirmation_intent(text)
    detour_signals = _has_detour_intent(text)
    hil_signals = _has_hil_intent(text)

    # If any workflow signal exists, try to split into parts
    if confirmation_signals or detour_signals or hil_signals:
        for conj in CONJUNCTORS:
            if conj.lower() in text.lower():
                parts = _split_on_conjunctor(text, conj)
                # Analyze each part
                ...

    # If no workflow signal but spans multiple steps → pure multi-variable Q&A
    qna_vars = detect_qna_variables(text)
    if spans_multiple_steps(qna_vars):
        return HybridResult(
            is_hybrid=False,
            workflow_part=None,
            qna_part=text,
            qna_variables=qna_vars,
            treat_as_pure_qna=True
        )
```

### Phase 3: Requirements Conflict Detection (NO additional LLM cost)

When Q&A mentions requirements different from stored ones, detect conflicts using **comparison logic only**:

```python
# backend/workflows/nlu/requirement_conflict.py

COMPARABLE_REQUIREMENTS = {
    "number_of_participants": {"type": "int", "aliases": ["attendees", "guests", "people", "visitors"]},
    "seating_layout": {"type": "enum", "aliases": ["setup", "arrangement", "layout"]},
    "duration": {"type": "time", "aliases": ["hours", "time", "start", "end"]},
}

def detect_requirement_conflicts(
    new_requirements: Dict[str, Any],
    stored_requirements: Dict[str, Any]
) -> List[Conflict]:
    """
    Compare newly extracted requirements against stored ones.

    NO LLM call - pure comparison logic.

    Returns list of conflicts like:
        [Conflict(field="number_of_participants", stored=25, new=40, type="override")]
    """
    conflicts = []
    for field, spec in COMPARABLE_REQUIREMENTS.items():
        stored_val = stored_requirements.get(field)
        new_val = new_requirements.get(field)
        if stored_val is not None and new_val is not None and stored_val != new_val:
            conflicts.append(Conflict(
                field=field,
                stored=stored_val,
                new=new_val,
                type="override"
            ))
    return conflicts
```

**How to get `new_requirements` without extra LLM call:**

Option A: **Regex extraction** (cheapest, works for most cases)
- Already have patterns for attendees: `r"\b(\d+)\s*(guests|people|attendees|visitors)\b"`
- Already have patterns for layout: `_LAYOUT_KEYWORDS` in adapter.py
- Already have patterns for catering: `_QNA_KEYWORDS["catering_for"]`

Option B: **Piggyback on existing LLM call** (if step already does LLM)
- Expand the prompt to also return any requirements mentioned
- No additional API call, just slightly larger response

**Recommendation:** Use Option A (regex) first. It catches 90%+ of cases. If regex finds nothing, assume no new requirements mentioned.

### Phase 4: Unified Response Composition

When a multi-variable or hybrid question is detected, compose response accordingly:

```python
# backend/workflows/common/qna_composer.py

def compose_multi_variable_response(
    qna_context: QnAContext,
    stored_requirements: Dict[str, Any],
    state: WorkflowState
) -> Dict[str, Any]:
    """
    Compose response for multi-variable Q&A.

    1. If hybrid (workflow + Q&A):
       - First address workflow part (confirmation/detour/HIL)
       - Then append Q&A response

    2. If pure multi-variable Q&A:
       - Address each variable in order
       - Use stored requirements (or overridden if conflict)
       - Route ALL through verbalizer
       - Add info links
    """

    response_parts = []

    # If hybrid, handle workflow part first
    if qna_context.has_confirmation_intent:
        workflow_response = _handle_confirmation(state)
        response_parts.append(workflow_response)
    elif qna_context.has_detour_intent:
        workflow_response = _handle_detour(state)
        response_parts.append(workflow_response)
    elif qna_context.has_hil_intent:
        workflow_response = _handle_hil_request(state)
        response_parts.append(workflow_response)

    # Handle Q&A parts
    for variable in qna_context.qna_variables:
        # Use new requirement if conflict detected, else stored
        effective_reqs = _apply_conflict_overrides(
            stored_requirements,
            qna_context.new_requirements,
            qna_context.conflicts
        )

        qna_response = _generate_variable_response(variable, effective_reqs, state)
        response_parts.append(qna_response)

    # Compose final response
    combined = _combine_response_parts(response_parts)

    # ALWAYS route through verbalizer
    verbalized = universal_verbalizer.verbalize(combined, state)

    # Add info links
    links = _get_info_links(qna_context.qna_variables)
    verbalized["info_links"] = links

    return verbalized
```

### Phase 5: Integration Points

The solution integrates at these points:

1. **Entry point (any step):** Before step-specific processing, run `extract_qna_context()`

2. **Routing decision:**
   ```python
   qna_ctx = extract_qna_context(text, stored_reqs)

   if qna_ctx.treat_as_pure_qna:
       # Multi-variable informative → General Q&A handler
       return handle_general_qna(qna_ctx, state)

   if qna_ctx.is_hybrid:
       # Mixed intent → Process workflow first, append Q&A
       return handle_hybrid(qna_ctx, state)

   # Normal workflow processing
   return normal_step_process(state)
   ```

3. **Conflict messaging:**
   ```python
   if qna_ctx.conflicts:
       # Add disambiguation to response
       msg = f"For your question, I'm using {new_val} {field} "
       msg += f"(different from your earlier {stored_val})..."
   ```

4. **Verbalizer + Links:**
   ```python
   INFO_LINKS = {
       "dates": "/info/availability",
       "rooms": "/info/rooms",
       "packages": "/info/packages",
       "products": "/info/products",
       "catering": "/info/menus",
   }
   ```

---

## Detection Rules Summary

### Pure Multi-Variable Q&A (not hybrid)
- **Trigger:** Single question asking about 2+ gatekeeping variables
- **Condition:** No confirmation/detour/HIL intent detected
- **Example:** "What dates are available and what packages do you offer?"
- **Response:** Combined Q&A response for all variables, via verbalizer, with links

### Hybrid Question
- **Trigger:** Conjuncted question with both workflow intent + informative Q&A
- **Types:**
  - Confirmation + Q&A: "Confirm date X and tell me about packages"
  - Detour + Q&A: "Change to 30 people, and what rooms fit that?"
  - HIL + Q&A: "Ask manager about discount, also what catering options?"
- **Response:** Process workflow part first, append Q&A response

### Requirement Conflict Override
- **Trigger:** Q&A mentions a requirement value different from stored
- **Example:** Stored 25 attendees, Q&A asks "would it work for 40?"
- **Response:** Use new value FOR THIS QUERY ONLY, add disambiguation message
- **Detection method:** Regex extraction + simple comparison (no LLM)

---

## Files to Create/Modify

### New Files
1. `backend/workflows/nlu/qna_variable_detector.py` - Variable detection
2. `backend/workflows/nlu/hybrid_detector.py` - Hybrid question detection
3. `backend/workflows/nlu/requirement_conflict.py` - Conflict detection (regex-based)
4. `backend/workflows/common/qna_composer.py` - Multi-variable response composition

### Modified Files
1. `backend/workflows/qna/router.py` - Integrate new detection at entry
2. `backend/workflows/common/general_qna.py` - Use composer for responses
3. `backend/ux/universal_verbalizer.py` - Add info links support
4. `backend/workflows/groups/date_confirmation/trigger/process.py` - Integrate hybrid handling
5. `backend/workflows/groups/room_availability/trigger/process.py` - Same
6. `backend/workflows/groups/offer/trigger/process.py` - Same
7. `backend/workflows/groups/negotiation_close.py` - Same

### Tests
1. `tests/specs/ux/test_multi_variable_qna.py` - Multi-variable detection tests
2. `tests/specs/ux/test_hybrid_questions.py` - Hybrid question tests
3. `tests/specs/ux/test_requirement_conflicts.py` - Conflict detection tests
4. `tests/regression/test_training_workshop_scenario.py` - Original scenario

---

## Implementation Order

1. **Phase 1:** Q&A Variable Detection (`qna_variable_detector.py`)
   - Tests for detection logic
   - Integration test with training workshop scenario

2. **Phase 2:** Hybrid Detection (`hybrid_detector.py`)
   - Confirmation + Q&A
   - Detour + Q&A
   - HIL + Q&A

3. **Phase 3:** Requirement Conflict Detection (`requirement_conflict.py`)
   - Regex extraction for requirements in Q&A
   - Comparison logic
   - Override behavior

4. **Phase 4:** Response Composition (`qna_composer.py`)
   - Multi-variable response assembly
   - Verbalizer integration
   - Info links

5. **Phase 5:** Integration into all workflow steps
   - Entry point in router.py
   - Propagate to step-specific processors

---

## Cost Analysis

| Component | LLM Calls | Notes |
|-----------|-----------|-------|
| Variable detection | 0 | Regex/keywords |
| Hybrid detection | 0 | Regex/keywords |
| Requirement extraction from Q&A | 0 | Regex patterns |
| Conflict detection | 0 | Simple comparison |
| Response verbalization | 1* | *Already required, not additional |

**Total additional LLM cost: 0**

All detection is done via regex/keyword matching. The only LLM call is verbalization, which is already required for all Q&A responses.

---

## Open Questions

1. Should we limit the number of Q&A variables we address in one response (e.g., max 3)?
2. Should conflict override apply only to the current Q&A or persist?
3. For hybrid questions, should the Q&A part always come AFTER the workflow part?