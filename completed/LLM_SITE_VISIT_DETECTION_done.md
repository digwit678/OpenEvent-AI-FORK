# Plan: LLM-Based Site Visit Detection

## Context
Currently, site visit change detection (`is_site_visit_change_request`) relies on a strict regex list (e.g., checking for "site visit", "tour", "change", "move"). This is brittle and prone to false negatives (paraphrasing) or false positives (keyword collisions).

## Objective
Replace regex-based detection in `router.py` with semantic detection from the Unified LLM.

## Proposed Changes

### 1. Update `UnifiedDetectionResult`
Add a new signal flag `is_site_visit_change` to the `UnifiedDetectionResult` dataclass in `detection/unified.py`.

```python
@dataclass
class UnifiedDetectionResult:
    ...
    # Signal flags
    is_site_visit_change: bool = False  # Explicitly wants to reschedule/change site visit
    ...
```

### 2. Update LLM Prompt
Modify `UNIFIED_DETECTION_PROMPT` in `detection/unified.py` to instruct the LLM to detect site visit changes.

```text
"signals": {{
    ...
    "is_site_visit_change": true if client wants to reschedule, move, or change an existing site visit/tour.
    ...
}}
```

### 3. Update `router.py`
Modify `_check_site_visit_intercept` in `workflows/runtime/router.py` to use the new signal.

**Before:**
```python
if is_site_visit_scheduled(event_entry) and is_site_visit_change_request(message_text):
    ...
```

**After:**
```python
if is_site_visit_scheduled(event_entry) and detection.is_site_visit_change:
    ...
```

### 4. Deprecate Regex Logic
Mark `workflows/common/site_visit_state.py:is_site_visit_change_request` as deprecated or remove it if no longer used.

## Codex Review (Self-Correction)

### Architectural Integrity
- **Routing:** Does not change routing logic, only the *trigger* for the route. Safe.
- **State:** No state modification, only reading detection signals. Safe.

### Detection Safety
- **Regex vs LLM:** Replaces regex with LLM. **Compliant.**
- **Hybrid Messages:** The Unified LLM sees the whole message context, so it can distinguish "Change event date" from "Change site visit date" better than regex.

### Root Cause
- Solves the root cause of brittle detection.

### Testability
- **E2E:** Can be tested by scheduling a site visit and then sending "Can we move the tour to Tuesday?".
- **Regression:** Need to ensure normal "event date changes" are NOT misclassified as "site visit changes".

## Verification Plan
1.  Run existing site visit tests.
2.  Add new test cases for site visit changes using natural language (e.g., "The tour time doesn't work anymore").
