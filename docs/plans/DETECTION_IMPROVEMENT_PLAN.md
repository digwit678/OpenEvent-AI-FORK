# Detection System Analysis & Improvement Plan

## Executive Summary

This document provides a comprehensive analysis of the detection system in OpenEvent-AI and outlines a plan to improve detection accuracy, handle client answers more generically, reduce conflicts between detection types, and address low-confidence scenarios.

---

## Part 1: Current System Analysis

### 1.1 Detection Types Overview

| Detection Type | Location | Purpose | Current Approach |
|----------------|----------|---------|------------------|
| **Intent Classification** | `backend/llm/intent_classifier.py` | Route messages to workflow steps | Heuristics + LLM fallback |
| **General Q&A** | `backend/workflows/nlu/general_qna_classifier.py` | Detect vague availability queries | Heuristics first, LLM if borderline |
| **Acceptance/Confirmation** | `backend/workflows/groups/negotiation_close.py` | Detect offer acceptance | Keyword matching (26 keywords) |
| **Change Detection** | `backend/workflows/change_propagation.py` | Detect structural changes | Keyword + verb proximity + field extraction |
| **Post-Offer Reply** | `backend/workflows/groups/offer/llm/client_reply_analysis.py` | Classify post-offer responses | Keyword matching with priority ordering |
| **Manager Request** | `backend/llm/intent_classifier.py` | Escalation requests | Regex patterns |

### 1.2 Identified Conflicts

#### Conflict 1: Accept vs. Room Selection
**Files:** `negotiation_close.py:383-395`, `intent_classifier.py:28`

**Problem:** Messages like "Room A looks good" could match:
- ACCEPT_KEYWORDS: "looks good"
- Room mention: "Room A"

**Current Mitigation:** None explicit. Room choice is checked at Step 3, but if at Step 5, "looks good" wins.

**Risk Level:** Medium

---

#### Conflict 2: Q&A vs. Short Confirmations
**Files:** `general_qna_classifier.py:130-146`, `negotiation_close.py:32-58`

**Problem:** Short messages like "ok" or "yes please" could be:
- General Q&A (if question context assumed)
- Accept confirmation
- Resume continuation

**Current Mitigation:** Q&A classifier uses `heuristic_general` flag which requires:
- Question mark, OR
- Interrogative word start, OR
- Availability patterns

But "ok" doesn't have any of these, so it typically routes to accept/resume correctly.

**Risk Level:** Low (adequately handled)

---

#### Conflict 3: Change Detection vs. Questions
**Files:** `change_propagation.py:400-601`

**Problem:** Messages like "Can we change to a different room?" vs "What if we changed the date?"
- Both have change verbs
- Both are questions
- But the first is a change REQUEST, second might be hypothetical

**Current Mitigation:** `has_change_intent()` function catches both equally.

**Risk Level:** Medium - hypothetical questions may trigger detours

---

#### Conflict 4: Product Updates vs. Descriptions
**Files:** `change_propagation.py:489-508`

**Problem:** "The coffee was great last time" mentions coffee but isn't a change request.

**Current Mitigation:** Requires change verbs near product nouns OR explicit `products_add`/`products_remove` fields.

**Risk Level:** Low-Medium

---

#### Conflict 5: Commercial vs. Price Questions
**Files:** `change_propagation.py:512-542`

**Problem:** "What's the total price?" vs "Could you reduce the price?"
- Both mention price
- Only second is a change

**Current Mitigation:** `has_change_intent()` check - but "what's" is not in change verbs.

**Risk Level:** Low (adequately handled)

---

### 1.3 Low-Confidence Behavior Analysis

**Critical Finding:** The system DOES have fallback behavior, but it may answer even when uncertain.

#### Current Flow:
```
LLM call → validate result → fallback if invalid → return NON_EVENT with confidence=0.0
                                    ↓
                          Heuristic override check
                                    ↓
                          If override fires → confidence boosted to 0.93
```

#### File: `backend/workflows/llm/adapter.py:302-317`
```python
def _fallback_analysis(payload: Dict[str, str]) -> Dict[str, Any]:
    # ... tries stub adapter ...
    _LAST_CALL_METADATA = {"phase": "analysis", "adapter": "fallback"}
    return {
        "intent": IntentLabel.NON_EVENT.value,
        "confidence": 0.0,  # <-- LOW CONFIDENCE
        "fields": {},
    }
```

**Key Issue:** Even with `confidence=0.0`, the workflow continues! There's no explicit "I'm not sure" behavior.

#### What happens with low confidence:

1. **In `classify_intent` (adapter.py:333-347):**
   - Confidence is stored but NOT used to gate responses
   - Heuristic override can boost confidence to 0.93 regardless of LLM result

2. **In Q&A classifier (general_qna_classifier.py:364):**
   - `uncertain: True` flag is returned but NOT acted upon
   - The `is_general` result combines heuristics OR LLM, so heuristics can override uncertain LLM

3. **In post-offer analysis (client_reply_analysis.py:185-196):**
   - Confidence ranges from 0.2 (no text) to 0.85 (strong match)
   - But NO downstream code checks this confidence to defer!

---

## Part 2: Identified Issues & Solutions

### Issue 1: No "I Don't Know" Response Path

**Problem:** System always returns an answer, never says "I'm not confident enough to act."

**Solution:** Add confidence gating at key decision points.

**Implementation Plan:**

1. **Create threshold constants** in `backend/workflows/common/confidence.py`:
```python
# Confidence thresholds
CONFIDENCE_HIGH = 0.85    # Safe to auto-proceed
CONFIDENCE_MEDIUM = 0.65  # Proceed with caution
CONFIDENCE_LOW = 0.40     # Should seek clarification
CONFIDENCE_DEFER = 0.25   # Must ask for clarification
```

2. **Add confidence-based branching** in negotiation_close.py:
```python
classification = _classify_message(message_text)
confidence = _estimate_classification_confidence(message_text, classification)

if confidence < CONFIDENCE_DEFER:
    # Ask clarifying question instead of assuming
    return _ask_clarification(state, event_entry, message_text)
```

3. **Create `_ask_clarification` function** that generates a clarifying question based on detected ambiguity.

---

### Issue 2: Keyword Lists Are Brittle & Require Manual Updates

**Problem:** Every new way a client might say "yes" requires adding to ACCEPT_KEYWORDS.

**Current:** 26 accept keywords hardcoded in `negotiation_close.py:32-58`

**Solution:** Use fuzzy matching + semantic patterns instead of exact keywords.

**Implementation Plan:**

1. **Create semantic pattern matchers** in `backend/workflows/nlu/semantic_matchers.py`:

```python
"""
Semantic pattern matching for client responses.
Uses regex patterns + fuzzy matching instead of exact keyword lists.
"""

import re
from typing import Tuple

# ============================================================================
# ACCEPTANCE PATTERNS (more general than keyword lists)
# ============================================================================

ACCEPTANCE_PATTERNS = [
    # Explicit agreement words
    r"\b(accept|agree|approved?|confirm)\w*\b",

    # "Good" family (looks good, sounds good, all good, good to go)
    r"\b(looks?|sounds?|all|good\s+to)\s+good\b",

    # Affirmative + action (yes please, ok send, sure proceed)
    r"\b(yes|ok|okay|sure|yep|ja|oui)[\s,]*(please|send|go|proceed|do\s+it)?\b",

    # "Fine" family (that's fine, fine for me, fine with that)
    r"\b(that'?s?|i'?m?|fine)\s*fine\b",

    # Imperative acceptance (send it, go ahead, proceed, let's do)
    r"\b(send\s+it|go\s+ahead|proceed|let'?s?\s+(do|go|proceed))\b",

    # Satisfaction indicators (works for us, we're happy, satisfied)
    r"\b(works?\s+for|happy\s+with|satisfied)\b",
]

def matches_acceptance_pattern(text: str) -> Tuple[bool, float, str]:
    """
    Check if text matches acceptance patterns.

    Returns:
        (is_match, confidence, matched_pattern)
    """
    text_lower = text.lower().strip()

    for pattern in ACCEPTANCE_PATTERNS:
        match = re.search(pattern, text_lower)
        if match:
            # Higher confidence for longer/more specific matches
            match_length = len(match.group(0))
            confidence = min(0.95, 0.7 + (match_length * 0.02))
            return True, confidence, match.group(0)

    return False, 0.0, ""
```

2. **Similar patterns for other detection types:**
   - `DECLINE_PATTERNS` - rejection signals
   - `CHANGE_PATTERNS` - modification requests
   - `QUESTION_PATTERNS` - information requests
   - `COUNTER_PATTERNS` - negotiation signals

---

### Issue 3: Change Detection Overly Aggressive with Hypotheticals

**Problem:** "What if we changed the date?" triggers a change detour when it's just a question.

**Solution:** Add hypothetical language detection to suppress false positives.

**Implementation Plan:**

Add to `change_propagation.py`:

```python
# Hypothetical markers that indicate question, not request
HYPOTHETICAL_MARKERS = [
    r"\bwhat\s+if\b",
    r"\bhypothetically\b",
    r"\bin\s+theory\b",
    r"\bwould\s+it\s+be\s+possible\b",
    r"\bcould\s+we\s+potentially\b",
    r"\bjust\s+(curious|wondering|asking)\b",
    r"\bthinking\s+about\b",
    r"\bconsidering\b",
]

def is_hypothetical_question(text: str) -> bool:
    """Check if message is a hypothetical question vs actual change request."""
    text_lower = text.lower()

    # Check for hypothetical markers
    for marker in HYPOTHETICAL_MARKERS:
        if re.search(marker, text_lower):
            # Also check if it ends with question mark (stronger signal)
            if "?" in text:
                return True

    return False
```

Then in `detect_change_type()`, add:
```python
# Before detecting change type, check if it's hypothetical
if is_hypothetical_question(text_lower):
    return None  # Don't trigger change, let Q&A handle it
```

---

### Issue 4: Room Selection vs Accept Collision

**Problem:** "Room A looks good" at Step 5 triggers acceptance instead of room selection.

**Solution:** Add room-mention guard for accept detection.

**Implementation Plan:**

In `negotiation_close.py:383-395`, update `_classify_message`:

```python
def _classify_message(message_text: str) -> str:
    lowered = message_text.lower()

    # NEW: Check if this is a room selection, not acceptance
    room_patterns = [
        r"\broom\s+[a-z]\b",  # "room A", "room B"
        r"\bpunkt\.?null\b",   # "Punkt.Null"
        r"\b(sky\s*loft|garden|terrace)\b",  # Named rooms
    ]
    mentions_room = any(re.search(p, lowered) for p in room_patterns)

    # If room is mentioned with "good"/"prefer"/"choose", it's room selection
    if mentions_room:
        room_selection_signals = ["looks good", "sounds good", "prefer", "choose", "go with", "take"]
        if any(signal in lowered for signal in room_selection_signals):
            return "room_selection"  # NEW classification type

    # Rest of existing logic...
    if any(keyword in lowered for keyword in ACCEPT_KEYWORDS):
        return "accept"
    # ...
```

---

### Issue 5: Overlapping Q&A Keywords

**Problem:** "Can you send a menu?" matches both:
- catering_for (keyword "menu")
- But might be an action request, not Q&A

**Solution:** Distinguish between "asking about X" vs "requesting X action".

**Implementation Plan:**

In `intent_classifier.py`, add action verb detection:

```python
# Action request patterns (not Q&A)
ACTION_PATTERNS = [
    r"\bsend\s+(me\s+)?(a|the)?\s*\b",     # "send me a menu"
    r"\bprovide\s+(me\s+with)?\b",          # "provide me with options"
    r"\bgive\s+(me|us)\b",                   # "give me details"
    r"\bemail\s+(me|us)?\b",                 # "email the quote"
    r"\bforward\s+(me|us)?\b",               # "forward the proposal"
]

def is_action_request(text: str) -> bool:
    """Check if message is requesting an action vs asking a question."""
    text_lower = text.lower()
    return any(re.search(p, text_lower) for p in ACTION_PATTERNS)

# In _detect_qna_types, filter out action requests:
def _detect_qna_types(text: str) -> List[str]:
    if is_action_request(text):
        return []  # Action requests are not Q&A
    # ... existing logic
```

---

## Part 3: Implementation Plan for Junior Developer

### Phase 1: Create Infrastructure (Day 1-2)

#### Task 1.1: Create confidence module
**File:** `backend/workflows/common/confidence.py`

```python
"""
Confidence thresholds and utilities for detection confidence gating.
"""

# Threshold constants
CONFIDENCE_HIGH = 0.85
CONFIDENCE_MEDIUM = 0.65
CONFIDENCE_LOW = 0.40
CONFIDENCE_DEFER = 0.25

def should_defer_to_human(confidence: float) -> bool:
    """Return True if confidence is too low to auto-proceed."""
    return confidence < CONFIDENCE_DEFER

def should_seek_clarification(confidence: float) -> bool:
    """Return True if we should ask a clarifying question."""
    return confidence < CONFIDENCE_LOW

def confidence_level(score: float) -> str:
    """Return human-readable confidence level."""
    if score >= CONFIDENCE_HIGH:
        return "high"
    elif score >= CONFIDENCE_MEDIUM:
        return "medium"
    elif score >= CONFIDENCE_LOW:
        return "low"
    return "very_low"
```

**Tests to write:** `backend/tests/detection/test_confidence.py`
- `test_should_defer_below_threshold()`
- `test_should_not_defer_above_threshold()`
- `test_confidence_level_boundaries()`

---

#### Task 1.2: Create semantic matchers module
**File:** `backend/workflows/nlu/semantic_matchers.py`

Create the patterns as described in Issue 2 above.

**Tests to write:** `backend/tests/detection/test_semantic_matchers.py`
- `test_acceptance_explicit_words()` - "accept", "confirm", "approved"
- `test_acceptance_informal()` - "looks good", "sounds great"
- `test_acceptance_affirmative_action()` - "yes please", "ok send it"
- `test_not_acceptance_question()` - "do you accept credit cards?"
- `test_decline_patterns()` - "cancel", "not interested"
- `test_change_patterns()` - "can we change", "modify the date"

---

### Phase 2: Improve Acceptance Detection (Day 3-4)

#### Task 2.1: Replace keyword list with pattern matching
**File:** `backend/workflows/groups/negotiation_close.py`

1. Import the new semantic matchers
2. Replace `_classify_message` to use patterns instead of keywords
3. Add room-selection guard (Issue 4)
4. Add confidence scoring

**Before:**
```python
def _classify_message(message_text: str) -> str:
    lowered = message_text.lower()
    if any(keyword in lowered for keyword in ACCEPT_KEYWORDS):
        return "accept"
    # ...
```

**After:**
```python
from backend.workflows.nlu.semantic_matchers import (
    matches_acceptance_pattern,
    matches_decline_pattern,
    matches_counter_pattern,
    is_room_selection,
)

def _classify_message(message_text: str) -> Tuple[str, float]:
    """
    Classify message with confidence score.

    Returns:
        (classification, confidence)
    """
    lowered = message_text.lower()

    # Check room selection first (guards against "Room A looks good")
    if is_room_selection(lowered):
        return "room_selection", 0.85

    # Pattern-based acceptance detection
    is_accept, accept_conf, _ = matches_acceptance_pattern(lowered)
    is_decline, decline_conf, _ = matches_decline_pattern(lowered)
    is_counter, counter_conf, _ = matches_counter_pattern(lowered)

    # Return highest-confidence match
    candidates = [
        ("accept", accept_conf if is_accept else 0),
        ("decline", decline_conf if is_decline else 0),
        ("counter", counter_conf if is_counter else 0),
    ]

    best = max(candidates, key=lambda x: x[1])
    if best[1] > 0.4:
        return best

    # Fallback to clarification
    if "?" in lowered:
        return "clarification", 0.6

    return "clarification", 0.3
```

**Tests to update:** `backend/tests/detection/test_negotiation_classification.py`
- Add tests for new semantic patterns
- Add tests for room-selection guard
- Add tests for confidence scores

---

### Phase 3: Add Confidence Gating (Day 5-6)

#### Task 3.1: Add clarification flow
**File:** `backend/workflows/groups/negotiation_close.py`

Add a new function:
```python
def _ask_classification_clarification(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    message_text: str,
    detected_intents: List[Tuple[str, float]],
) -> GroupResult:
    """
    Generate a clarifying question when classification is uncertain.

    This prevents the system from guessing wrong on ambiguous messages.
    """
    # Build clarification options based on detected intents
    options = []
    if any(intent == "accept" for intent, _ in detected_intents):
        options.append("confirm the booking")
    if any(intent == "counter" for intent, _ in detected_intents):
        options.append("discuss pricing")
    if any(intent == "clarification" for intent, _ in detected_intents):
        options.append("ask a question")

    prompt = (
        "I want to make sure I understand correctly. "
        f"Did you mean to {' or '.join(options)}? "
        "Please let me know so I can help you best."
    )

    draft = {
        "body": append_footer(prompt, step=5, next_step=5, thread_state="Awaiting Client"),
        "step": 5,
        "topic": "classification_clarification",
        "requires_approval": False,  # Auto-send clarification
    }
    state.add_draft_message(draft)
    # ... rest of flow
```

#### Task 3.2: Integrate confidence check in process()

In the main `process()` function, add:
```python
classification, confidence = _classify_message(message_text)

# If confidence is too low, ask for clarification
if should_seek_clarification(confidence):
    detected_intents = _get_all_detected_intents(message_text)  # New helper
    return _ask_classification_clarification(
        state, event_entry, message_text, detected_intents
    )
```

**Tests to write:** `backend/tests/detection/test_low_confidence_handling.py`
- `test_low_confidence_triggers_clarification()`
- `test_high_confidence_proceeds_directly()`
- `test_clarification_message_format()`

---

### Phase 4: Improve Change Detection (Day 7-8)

#### Task 4.1: Add hypothetical question filter
**File:** `backend/workflows/change_propagation.py`

Add the `is_hypothetical_question()` function and integrate it into `detect_change_type()`.

#### Task 4.2: Improve verb proximity matching
Replace simple `in` checks with proximity-based matching:

```python
def has_change_intent_near_target(text: str, target_keywords: List[str], max_distance: int = 5) -> bool:
    """
    Check if change verbs appear within max_distance words of target keywords.

    This prevents false positives like "the room was lovely, we loved the setup"
    where "loved" is far from any change context.
    """
    words = text.lower().split()

    # Find positions of change verbs
    change_positions = []
    for i, word in enumerate(words):
        if word in change_verbs:
            change_positions.append(i)

    # Find positions of target keywords
    target_positions = []
    for i, word in enumerate(words):
        if any(kw in word for kw in target_keywords):
            target_positions.append(i)

    # Check if any change verb is within max_distance of any target
    for cp in change_positions:
        for tp in target_positions:
            if abs(cp - tp) <= max_distance:
                return True

    return False
```

**Tests to write:** `backend/tests/detection/test_change_detection.py`
- `test_hypothetical_question_not_change()`
- `test_actual_change_request_detected()`
- `test_verb_proximity_filtering()`
- `test_distant_verb_not_matched()`

---

### Phase 5: Add Generalized Response Patterns (Day 9-10)

#### Task 5.1: Create response normalizer
**File:** `backend/workflows/nlu/response_normalizer.py`

```python
"""
Normalize diverse client responses to canonical forms.

This handles variations like:
- "yep" -> "yes"
- "nope" -> "no"
- "sounds great" -> "positive"
- "I don't think so" -> "negative"
"""

import re
from typing import Optional, Tuple

# Normalization maps
AFFIRMATIVE_VARIANTS = {
    # Direct affirmatives
    r"\b(yes|yep|yeah|yea|yup|aye|oui|ja|si)\b": "yes",
    r"\b(ok|okay|k|kk)\b": "ok",
    r"\b(sure|certainly|absolutely|definitely|of course)\b": "sure",

    # Positive phrases
    r"\b(sounds?\s+)(good|great|fine|perfect|lovely|wonderful)\b": "positive",
    r"\b(looks?\s+)(good|great|fine|perfect|lovely|wonderful)\b": "positive",
    r"\b(that'?s?\s+)(good|great|fine|perfect|lovely|wonderful)\b": "positive",
    r"\b(all\s+)(good|great|fine|set|clear)\b": "positive",

    # Action affirmatives
    r"\b(go\s+ahead|proceed|let'?s?\s+do\s+it|do\s+it)\b": "proceed",
    r"\b(i'?m?\s+)?(happy|satisfied|pleased)\b": "positive",
}

NEGATIVE_VARIANTS = {
    r"\b(no|nope|nah|nay)\b": "no",
    r"\b(i\s+don'?t\s+think\s+so)\b": "no",
    r"\b(not\s+really|not\s+quite|not\s+exactly)\b": "negative",
    r"\b(i'?m?\s+not\s+sure|unsure|uncertain)\b": "uncertain",
    r"\b(cancel|nevermind|forget\s+it)\b": "cancel",
}

def normalize_response(text: str) -> Tuple[Optional[str], float]:
    """
    Normalize a client response to a canonical form.

    Returns:
        (canonical_form, confidence)
        canonical_form is None if no pattern matched
    """
    text_lower = text.lower().strip()

    # Try affirmative patterns
    for pattern, canonical in AFFIRMATIVE_VARIANTS.items():
        if re.search(pattern, text_lower):
            return canonical, 0.85

    # Try negative patterns
    for pattern, canonical in NEGATIVE_VARIANTS.items():
        if re.search(pattern, text_lower):
            return canonical, 0.85

    return None, 0.0
```

---

## Part 4: Test Coverage Requirements

### 4.1 New Test Files to Create

| Test File | Purpose | Priority |
|-----------|---------|----------|
| `test_confidence.py` | Confidence thresholds and gating | High |
| `test_semantic_matchers.py` | Semantic pattern matching | High |
| `test_low_confidence_handling.py` | Clarification flow | High |
| `test_change_detection.py` | Improved change detection | Medium |
| `test_response_normalizer.py` | Response normalization | Medium |

### 4.2 Test Cases Per Module

**test_confidence.py:**
```python
def test_should_defer_below_0_25()
def test_should_not_defer_above_0_25()
def test_confidence_level_high_above_0_85()
def test_confidence_level_medium_0_65_to_0_85()
def test_confidence_level_low_0_40_to_0_65()
def test_confidence_level_very_low_below_0_40()
```

**test_semantic_matchers.py:**
```python
# Acceptance patterns
def test_acceptance_explicit_confirm()
def test_acceptance_explicit_accept()
def test_acceptance_looks_good()
def test_acceptance_sounds_great()
def test_acceptance_yes_please()
def test_acceptance_ok_send()
def test_acceptance_go_ahead()
def test_not_acceptance_credit_card_question()
def test_not_acceptance_room_looks_good()

# Decline patterns
def test_decline_cancel()
def test_decline_not_interested()
def test_decline_pass()

# Change patterns
def test_change_can_we_change()
def test_change_modify_the_date()
def test_change_switch_rooms()
def test_not_change_hypothetical()
```

**test_low_confidence_handling.py:**
```python
def test_low_confidence_triggers_clarification()
def test_clarification_message_contains_options()
def test_high_confidence_skips_clarification()
def test_medium_confidence_proceeds_with_caution()
def test_very_low_confidence_defers_to_human()
```

---

## Part 5: Migration & Rollout Strategy

### Phase 1: Shadow Mode (Week 1)
- Deploy new detection alongside existing
- Log both results for comparison
- No behavior change for users

### Phase 2: Gradual Rollout (Week 2)
- Enable confidence gating for 10% of traffic
- Monitor clarification rate
- Adjust thresholds if needed

### Phase 3: Full Rollout (Week 3)
- Enable for all traffic
- Remove legacy keyword lists
- Monitor for regressions

---

## Part 6: Success Metrics

1. **Reduce false positive rate** for change detection by 30%
2. **Increase acceptance detection coverage** by handling 50+ new variations
3. **Add clarification requests** for <10% of messages (confidence gating)
4. **Zero regressions** on existing test suite
5. **Reduce manual keyword additions** by 90% (patterns cover most cases)

---

## Appendix A: Files to Modify

| File | Changes |
|------|---------|
| `backend/workflows/groups/negotiation_close.py` | Replace keywords with patterns, add confidence gating |
| `backend/workflows/change_propagation.py` | Add hypothetical filter, improve proximity matching |
| `backend/llm/intent_classifier.py` | Add action request detection |
| `backend/workflows/nlu/general_qna_classifier.py` | Filter action requests from Q&A |

## Appendix B: New Files to Create

| File | Purpose |
|------|---------|
| `backend/workflows/common/confidence.py` | Confidence thresholds and utilities |
| `backend/workflows/nlu/semantic_matchers.py` | Semantic pattern matching |
| `backend/workflows/nlu/response_normalizer.py` | Response normalization |
| `backend/tests/detection/test_confidence.py` | Confidence tests |
| `backend/tests/detection/test_semantic_matchers.py` | Pattern matching tests |
| `backend/tests/detection/test_low_confidence_handling.py` | Clarification flow tests |

## Appendix C: Regex Pattern Reference

### Acceptance Patterns (Generalized)
```python
ACCEPTANCE_PATTERNS = [
    # Explicit agreement
    r"\b(accept|agree|approved?|confirm)\w*\b",

    # "Good" family
    r"\b(looks?|sounds?|all|good\s+to)\s+good\b",

    # Affirmative + optional action
    r"\b(yes|ok|okay|sure|yep|ja|oui)[\s,]*(please|send|go|proceed|do\s+it)?\b",

    # "Fine" family
    r"\b(that'?s?|i'?m?|fine)\s*fine\b",

    # Imperative acceptance
    r"\b(send\s+it|go\s+ahead|proceed|let'?s?\s+(do|go|proceed))\b",

    # Satisfaction indicators
    r"\b(works?\s+for|happy\s+with|satisfied)\b",

    # Multi-language basics
    r"\b(d'?accord|einverstanden|va\s+bene)\b",
]
```

### Change Detection Patterns (Generalized)
```python
CHANGE_INTENT_PATTERNS = [
    # Explicit change verbs
    r"\b(change|modify|update|adjust|switch|move|shift|reschedule)\b",

    # Replacement language
    r"\b(instead\s+of|rather\s+than|replace\s+with|swap\s+(out|for))\b",

    # Correction language
    r"\b(actually|correction|i\s+meant|sorry|make\s+(it|that))\b",

    # Request patterns with change
    r"\b(can|could|would)\s+(we|i|you)\s+(please\s+)?(change|modify|update)\b",
]

HYPOTHETICAL_PATTERNS = [
    r"\bwhat\s+if\b",
    r"\bhypothetically\b",
    r"\bjust\s+(curious|wondering|asking)\b",
    r"\bthinking\s+about\b",
]
```

---

*Document generated: 2025-12-01*
*Author: Claude Code Analysis*
*Version: 1.0*

 I've completed a comprehensive analysis and created a detailed implementation plan. Here's the summary:

  Summary

  I've created DETECTION_IMPROVEMENT_PLAN.md with a complete analysis and implementation plan. Here are the key findings:

  Critical Issues Found

  1. No "I Don't Know" Response Path: The system always returns an answer even when confidence is 0.0. The confidence values are tracked but never used to gate responses. This matches the Reddit concern you mentioned.
  2. Keyword Lists Are Brittle:
    - negotiation_close.py has 26 hardcoded ACCEPT_KEYWORDS
    - Every new client phrasing requires manual addition
    - No fuzzy matching or semantic patterns
  3. 5 Conflict Areas Identified:
    - Accept vs Room Selection ("Room A looks good")
    - Q&A vs Short Confirmations
    - Change Detection vs Hypothetical Questions
    - Product Updates vs Descriptive Mentions
    - Commercial Changes vs Price Questions

  Key Solutions Proposed

  1. Confidence Gating: Add thresholds (HIGH=0.85, LOW=0.40, DEFER=0.25) and ask clarifying questions when uncertain instead of guessing.
  2. Semantic Pattern Matching: Replace keyword lists with regex patterns that handle variations automatically:
  # Instead of: "looks good" in ACCEPT_KEYWORDS
  # Use: r"\b(looks?|sounds?|all|good\s+to)\s+good\b"
  3. Hypothetical Question Filter: Prevent "What if we changed..." from triggering change detours.
  4. Room-Selection Guard: Detect "Room A looks good" as room selection, not acceptance.
  5. Response Normalization: Handle variations like "yep", "sounds great", "d'accord" automatically.

  Implementation Timeline

  The plan is structured for a junior developer across 10 days:
  - Days 1-2: Create confidence module and semantic matchers
  - Days 3-4: Replace keyword lists with patterns
  - Days 5-6: Add confidence gating and clarification flow
  - Days 7-8: Improve change detection
  - Days 9-10: Add response normalization

  Test Requirements

  I specified ~30 test cases across 6 test files to ensure no regressions.