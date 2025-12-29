# LLM & Extraction Architecture

This document provides a complete overview of which extraction/classification methods are used where in the OpenEvent-AI system.

## Quick Reference

| Operation | Default Provider | Alternatives | Cost/Call |
|-----------|-----------------|--------------|-----------|
| Intent Classification | Gemini | OpenAI, Stub | $0.00125 |
| Entity Extraction | Gemini | OpenAI, Stub | $0.002 |
| Verbalization | OpenAI | Gemini, Stub | $0.015 |

**Estimated cost per event:** ~$0.08 (hybrid) vs ~$0.10 (full OpenAI)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        CLIENT MESSAGE                                │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  LAYER 1: REGEX PATTERNS (Always runs first - zero cost)            │
│  ─────────────────────────────────────────────────────────────────  │
│  • Date patterns: \d{1,2}\.\d{1,2}\.\d{4}, "March 15th, 2026"       │
│  • Participant counts: \d+ (people|participants|guests|Personen)    │
│  • Time patterns: \d{1,2}(:\d{2})?\s?(am|pm|Uhr)?                   │
│  • Email extraction: standard email regex                           │
│  • Room names: "Room A", "Saal B", etc.                             │
│  • Keywords: acceptance, rejection, question indicators             │
│                                                                      │
│  Files: backend/workflows/steps/step1_intake/trigger/               │
│         - keyword_matching.py                                        │
│         - room_detection.py                                          │
│         - date_fallback.py                                           │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  LAYER 2: INTENT CLASSIFICATION (Configurable: Gemini/OpenAI)       │
│  ─────────────────────────────────────────────────────────────────  │
│  Purpose: Determine what the client wants                           │
│  Default: Gemini (75% cheaper, good accuracy)                       │
│                                                                      │
│  Intents detected:                                                   │
│  • event_request - New booking inquiry                              │
│  • acceptance - Offer/date/room acceptance                          │
│  • counter_offer - Price negotiation                                │
│  • clarification - Question about offer                             │
│  • change_request - Modify date/room/requirements                   │
│  • cancellation - Cancel booking                                    │
│  • general_question - Q&A (not booking related)                     │
│                                                                      │
│  Files: backend/workflows/llm/adapter.py                            │
│         backend/llm/providers/gemini_adapter.py                     │
│         backend/llm/providers/openai_adapter.py                     │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  LAYER 3: ENTITY EXTRACTION (Configurable: Gemini/OpenAI)           │
│  ─────────────────────────────────────────────────────────────────  │
│  Purpose: Extract structured data from message                      │
│  Default: Gemini (75% cheaper, good structured extraction)          │
│                                                                      │
│  Pipeline: Regex → NER → LLM (progressive refinement)               │
│                                                                      │
│  Entities extracted:                                                 │
│  • Dates (converted to ISO format)                                  │
│  • Participant count (integer)                                      │
│  • Duration (start_time, end_time)                                  │
│  • Room preferences                                                  │
│  • Product/catering preferences                                     │
│  • Billing address components                                       │
│  • Special requirements (free text)                                 │
│                                                                      │
│  Files: backend/workflows/steps/step1_intake/trigger/               │
│         - entity_extraction.py (coordinates pipeline)               │
│         - normalization.py (date/time normalization)                │
│         backend/workflows/llm/adapter.py (LLM layer)                │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  LAYER 4: VERBALIZATION (Configurable: OpenAI/Gemini)               │
│  ─────────────────────────────────────────────────────────────────  │
│  Purpose: Compose professional client-facing messages               │
│  Default: OpenAI (best quality for client communication)            │
│                                                                      │
│  Use cases:                                                          │
│  • Room availability summaries                                      │
│  • Offer composition                                                │
│  • Date confirmation messages                                       │
│  • Negotiation responses                                            │
│  • Site visit scheduling                                            │
│  • General Q&A answers                                              │
│                                                                      │
│  Safety: All verbalized output goes through "safety sandwich"       │
│  (fact-checking against database before sending)                    │
│                                                                      │
│  Files: backend/ux/verbalizer.py                                    │
│         backend/ux/verbalizer_safety.py                             │
│         backend/workflows/llm/adapter.py                            │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Detailed Layer Breakdown

### Layer 1: Regex Patterns (Zero Cost)

These patterns ALWAYS run first before any LLM call:

| Pattern Type | Example Input | Regex/Heuristic | Output |
|-------------|---------------|-----------------|--------|
| Date (EU format) | "14.02.2026" | `\d{1,2}\.\d{1,2}\.\d{4}` | 2026-02-14 |
| Date (text) | "February 14th" | Month name + day + year | 2026-02-14 |
| Participants | "25 people" | `(\d+)\s*(people\|participants\|guests\|Personen)` | 25 |
| Time | "9am - 5pm" | `\d{1,2}(:\d{2})?\s?(am\|pm)?` | 09:00, 17:00 |
| Email | "test@example.com" | Standard email regex | test@example.com |
| Room | "Room A" | Room name dictionary | Room A |

**Files:**
- `backend/workflows/steps/step1_intake/trigger/keyword_matching.py` - Acceptance/rejection keywords
- `backend/workflows/steps/step1_intake/trigger/room_detection.py` - Room name patterns
- `backend/workflows/steps/step1_intake/trigger/date_fallback.py` - Date pattern matching
- `backend/workflows/steps/step1_intake/trigger/product_detection.py` - Product keywords

### Layer 2: Intent Classification (LLM)

**When it runs:** After regex layer, for every incoming message

**Provider selection:**
```python
# Configured via admin UI or environment
intent_provider: 'gemini' | 'openai' | 'stub'
```

**Classification categories:**

| Intent | Description | Triggers |
|--------|-------------|----------|
| `event_request` | New booking inquiry | First message, contains date/participants |
| `acceptance` | Confirms offer/date/room | "yes", "I accept", "einverstanden" |
| `counter_offer` | Price negotiation | "too expensive", "can you reduce" |
| `change_request` | Modify booking | "change the date", "different room" |
| `clarification` | Question about offer | "what's included", "parking?" |
| `cancellation` | Cancel booking | "cancel", "never mind" |
| `general_question` | Non-booking question | "opening hours", "location" |

**Cost comparison:**
- Gemini: ~$0.00125/call
- OpenAI: ~$0.005/call
- Stub: $0 (heuristics only, for testing)

### Layer 3: Entity Extraction (Hybrid Pipeline)

**Pipeline order:** Regex → NER → LLM

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│    REGEX     │───▶│     NER      │───▶│     LLM      │
│  (Pattern)   │    │  (SpaCy)     │    │ (Refinement) │
│   $0.00      │    │   $0.00      │    │   $0.002     │
└──────────────┘    └──────────────┘    └──────────────┘
       │                   │                   │
       ▼                   ▼                   ▼
  Simple dates       Named entities      Complex cases
  "14.02.2026"       Person names        "next Friday"
  Participant #      Company names       Ambiguous dates
  Time patterns      Locations           Product matching
```

**LLM layer handles:**
- Ambiguous dates ("next Friday" → ISO date)
- Natural language quantities ("about twenty" → 20)
- Product preference matching ("something for lunch" → Lunch Package)
- Billing address parsing (free text → structured fields)

### Layer 4: Verbalization (LLM)

**When it runs:** When composing client-facing messages

**Quality matters here:** This is what the client sees, so OpenAI is recommended for:
- Professional tone
- Correct formatting
- Multilingual support (German/English)

**Safety Sandwich Pattern:**
```python
# 1. Build facts from database (deterministic)
facts = build_room_offer_facts(event_entry)

# 2. Generate LLM draft
draft = llm_verbalize(facts)

# 3. Verify/correct the draft (catches hallucinations)
verified = correct_output(facts, draft)

# 4. HIL approval before sending
```

---

## All Detection Mechanisms (Complete Inventory)

Beyond the main 4 layers, the system has specialized detectors for different scenarios. Here's the complete inventory:

### Detection Summary Table

| Mechanism | Method | Cost | Confidence | Risk Level |
|-----------|--------|------|------------|------------|
| **Confirmation** | Regex + Keywords | $0 | High | ⚠️ Medium |
| **Detour/Change** | Keywords + Semantic | $0 | Variable | ⚠️ Medium |
| **Duplicate Message** | String Match | $0 | Very High | ✅ Low |
| **Shortcut Capture** | Heuristics + Flags | $0 | Variable | ⚠️ Medium |
| **Site Visit** | Regex + Keywords | $0 | Medium | ⚠️ Medium |
| **Q&A Detection** | Heuristics + LLM | $0-0.002 | Variable | ⚠️ Medium |
| **Billing Address** | Regex Parsing | $0 | Medium | 🔴 High |
| **Product/Catering** | Catalog + Regex | $0 | Medium-High | ⚠️ Medium |

---

### 1. Confirmation Detection (Regex)

**Purpose:** Detect when client confirms a date, room, or offer

**Method:** Pure regex + keyword matching (no LLM)

**File:** `backend/workflows/steps/step1_intake/trigger/confirmation_parsing.py`

```python
# Patterns used:
DATE_TOKEN = r'\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\b'
AFFIRMATIVE_TOKENS = ("ok", "okay", "great", "sounds good", "let's do", "works",
                       "perfect", "ja", "einverstanden", "passt")
MONTH_TOKENS = ("january", "february", ..., "januar", "februar", ...)
```

**Detection Logic:**
1. Check for date token presence
2. Check for affirmative token presence
3. Check for plain date formats (e.g., "07.02.2026")
4. Short confirmation replies (<6 words + date)

**⚠️ False Positive Risks:**
- Dates mentioned in questions: "Is 14.02.2026 available?" → May trigger confirmation
- Month names in context: "We had a great January meeting" → May false-match

**⚠️ False Negative Risks:**
- Non-standard confirmations: "That works for us" without date → May miss
- Implicit confirmations: "Proceed with the booking" → Depends on context

---

### 2. Detour/Change Detection (Keywords + Semantic)

**Purpose:** Detect when client wants to change date, room, or requirements mid-flow

**Method:** Dual-condition logic (revision signal + target match)

**File:** `backend/workflows/change_propagation.py`

```python
# Revision signals (must have one):
CHANGE_VERBS = ["change", "modify", "update", "switch", "move", "reschedule",
                "ändern", "wechseln", "verschieben"]
REVISION_MARKERS = ["actually", "correction", "i meant", "sorry", "wait",
                    "eigentlich", "korrektur", "ich meinte"]

# Target patterns (must match one):
- DATE: date patterns, day names, month names
- ROOM: room names ("Room A", "Saal B")
- REQUIREMENTS: "participants", "people", "capacity", "Teilnehmer"
```

**Detection Modes:**
| Mode | Condition | Action |
|------|-----------|--------|
| LONG | Revision signal, no new value | Ask: "What would you like to change to?" |
| FAST | Revision signal + new value | Validate & proceed |
| EXPLICIT | Old value + new value both mentioned | Validate & proceed |

**⚠️ False Positive Risks:**
- Hypothetical questions: "What if we changed the date?" → May trigger detour
- Past tense: "We changed our plans last week" → May false-match

**⚠️ False Negative Risks:**
- Subtle changes: "Actually, make it 30 people" without explicit "change" → Depends on markers

---

### 3. Duplicate Message Detection (String Match)

**Purpose:** Prevent re-processing identical messages

**Method:** Exact string comparison (normalized)

**File:** `backend/workflows/runtime/pre_route.py`

```python
def check_duplicate_message(msg, event_entry):
    normalized_current = msg.strip().lower()
    normalized_last = (event_entry.get("last_client_message") or "").strip().lower()
    return normalized_current == normalized_last
```

**Bypass Conditions:**
- During detour flows (`caller_step` is not None)
- During billing flow (`offer_accepted` + `awaiting_billing_for_accept`)
- Before Step 2 (`current_step < 2`)

**✅ Very reliable** - Exact match means low false positive rate

**⚠️ False Negative Risk:**
- Paraphrased duplicates: "Yes please" vs "Yes, please!" → Not caught (different strings)

---

### 4. Shortcut Capture (Heuristics + Flags)

**Purpose:** Capture multiple entities in one message (date + room + products)

**Method:** Flag-controlled heuristics with DAG guards

**Files:**
- `backend/workflows/planner/smart_shortcuts.py`
- `backend/workflows/planner/shortcuts_flags.py`

```python
# Feature flags:
SMART_SHORTCUTS = True       # Enable multi-intent parsing
MAX_COMBINED = 3             # Max entities per turn
PRODUCT_FLOW_ENABLED = True  # Allow product capture in shortcuts
```

**Shortcut Types:**
| Type | Example | Captured |
|------|---------|----------|
| Date + Participants | "25 people on Feb 14" | date, capacity |
| Room + Products | "Room A with lunch" | room, products |
| Full bundle | "Room A, 25 people, Feb 14, lunch" | all |

**⚠️ False Positive Risks:**
- Unintentional product capture: "We'll discuss lunch later" → May capture "lunch"
- Budget mention: "Our budget is 5000" → May capture as constraint

**Prevention:** DAG guards prevent skipping prerequisites

---

### 5. Site Visit Detection (Regex + Keywords)

**Purpose:** Handle site visit scheduling after deposit

**Method:** Time/day regex + keyword matching

**File:** `backend/workflows/steps/step7_confirmation/trigger/site_visit.py`

```python
# Time patterns:
TIME_PATTERN = r'(\d{1,2})\s*(?:pm|am|:00|h|uhr)?'

# Day keywords:
WEEKDAYS_EN = ["monday", "tuesday", "wednesday", "thursday", "friday"]
WEEKDAYS_DE = ["montag", "dienstag", "mittwoch", "donnerstag", "freitag"]

# Slot selection:
ORDINALS = ["first", "1st", "second", "2nd", "third", "3rd"]
CONFIRMATIONS = ["yes", "proceed", "ok", "confirm", "ja", "bitte"]
```

**State Machine:**
```
idle → proposed (slots offered) → scheduled (slot confirmed)
```

**⚠️ False Positive Risks:**
- Time in other context: "We close at 5pm" → May interpret as preference
- Day mention: "Monday works" in general context → May trigger scheduling

**⚠️ False Negative Risks:**
- Complex preferences: "Late afternoon any day except Thursday" → May not parse fully

---

### 6. Q&A Detection (Heuristics + LLM Fallback)

**Purpose:** Distinguish general questions from booking requests

**Method:** Fast heuristic scan → LLM only if uncertain

**Files:**
- `backend/detection/qna/general_qna.py`
- `backend/workflows/common/general_qna.py`

```python
# Heuristic patterns (checked first - $0):
QUESTION_WORDS = ["which", "what", "when", "can", "could", "do you have"]
BORDERLINE_HINTS = ["need rooms", "looking for rooms", "room availability"]
ACTION_PATTERNS = ["book", "reserve", "confirm", "proceed"]

# LLM fallback (only if heuristics uncertain - $0.002):
if confidence < 0.6:
    qna_type = llm_detect_qna_type(message)
```

**Q&A Types Detected:**
| Type | Example | Response |
|------|---------|----------|
| `rooms_by_feature` | "Do you have rooms with projectors?" | Feature list |
| `free_dates` | "What dates are free in March?" | Calendar view |
| `parking_policy` | "Is there parking?" | FAQ answer |
| `catering_for` | "What lunch options do you have?" | Menu |

**⚠️ False Positive Risks:**
- Booking disguised as question: "Do you have Room A free on Feb 14?" → May route to Q&A instead of booking

**⚠️ False Negative Risks:**
- Complex questions requiring LLM: "Can you accommodate a workshop with breakout sessions?" → May miss nuance

---

### 7. Billing Address Detection (Regex Parsing)

**Purpose:** Extract structured billing info from free text

**Method:** Multi-pattern regex with labeled field extraction

**File:** `backend/workflows/nlu/parse_billing.py`

```python
# Patterns:
POSTAL_CITY = r'^(?:CH[-\s])?(?P<postal>\d{4,6})[\s,]+(?P<city>[A-Za-zÀ-ÖØ-öø-ÿ\' \-]+)$'
STREET = r'^\s*(?P<street>.+?\d+\w*(?:[ /-]\w+)*)\s*$'
VAT = r'CHE[-.]?\d{3}[.-]?\d{3}[.-]?\d{3}\s*(?:MWST|TVA|IVA)?'
LABELED_FIELD = r'^\s*(?P<label>[A-Za-z ]{3,})\s*[:=\-]\s*(?P<value>.+?)\s*$'
```

**Required Fields:**
- `name_or_company` ✓
- `street` ✓
- `postal_code` ✓
- `city` ✓
- `country` (defaults to Switzerland)

**🔴 High Risk - Known Issues:**
- **Multi-line parsing fragile:** Order of lines matters
- **Street detection:** Requires house number to match
- **German umlauts:** May not parse correctly in some encodings
- **Country variants:** Must handle "Switzerland", "Schweiz", "CH", "Suisse"

**Example that works:**
```
TechCorp AG
Bahnhofstrasse 10
8001 Zurich
Switzerland
```

**Example that may fail:**
```
Please bill to our Zurich office
TechCorp on Bahnhofstrasse
```

---

### 8. Product/Catering Detection (Catalog + Regex)

**Purpose:** Match product mentions to catalog items

**Method:** Token matching with context window + quantity extraction

**Files:**
- `backend/workflows/steps/step1_intake/trigger/product_detection.py`
- `backend/workflows/steps/step1_intake/trigger/step1_handler.py`

```python
# Add/Remove keywords:
PRODUCT_ADD = ["add", "include", "plus", "extra", "another", "also", "upgrade"]
PRODUCT_REMOVE = ["remove", "without", "drop", "exclude", "skip", "no", "minus"]

# Quantity extraction:
QUANTITY_PATTERN = r'(\d{1,3})\s*(?:x|times|pcs|pieces|units)?\s*(?:of\s+)?'

# Matching:
1. Load product catalog
2. For each product: check tokens (name, plurals, synonyms)
3. Score matches within 80-char context window
4. Skip matches in parentheses (explanatory fragments)
```

**Token Variants Generated:**
| Product | Tokens |
|---------|--------|
| "Lunch Package" | lunch, package, lunches, packages |
| "Coffee Service" | coffee, service, coffees |

**⚠️ False Positive Risks:**
- Context bleeding: "We discussed lunch plans" → May match "Lunch Package"
- Parenthetical mentions: "(lunch not included)" → May match despite skip logic

**⚠️ False Negative Risks:**
- Far quantities: "For the 30 of us, we need lunch" → Quantity too far from product
- Synonyms not in catalog: "midday meal" for "Lunch Package" → May miss

---

## Resilience Assessment

### What's "Resilient in Diversity"? ✅

These mechanisms handle multilingual input and edge cases well:

| Mechanism | EN | DE | Edge Cases |
|-----------|----|----|------------|
| Intent Classification (LLM) | ✅ | ✅ | ✅ Handles ambiguity |
| Entity Extraction (LLM) | ✅ | ✅ | ✅ "next Friday" works |
| Verbalization (LLM) | ✅ | ✅ | ✅ Adapts tone |
| Duplicate Detection | ✅ | ✅ | ✅ Language-agnostic |

### What Needs Improvement? ⚠️

These mechanisms have known gaps:

| Mechanism | Gap | Risk | Mitigation |
|-----------|-----|------|------------|
| **Billing Parsing** | Fragile multi-line | 🔴 High | Add LLM fallback |
| **Confirmation Detection** | Date-in-question false positives | ⚠️ Medium | Add intent context |
| **Product Detection** | Context window too narrow | ⚠️ Medium | Expand to full message |
| **Site Visit Parsing** | Complex time preferences | ⚠️ Medium | Add LLM for ambiguous |

### Recommended Improvements

1. **Billing Address:** Add LLM fallback when regex confidence < 0.7
2. **Confirmation:** Check intent classification first, then regex
3. **Products:** Use LLM for ambiguous matches (e.g., "something for lunch")
4. **Site Visit:** Add LLM parsing for complex scheduling preferences

---

## Per-Message Detection Pipeline (Optimized)

Every incoming message goes through this pipeline. The goal is to **minimize LLM calls while maximizing detection accuracy**.

### Current vs Improved Architecture

```
CURRENT PIPELINE (2-3 LLM calls/message):
┌─────────────────────────────────────────────────────────────────────┐
│  Message Input                                                       │
└─────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────┐
│  LAYER 0: Quick Keyword Scan ($0)                                   │
│  • General QNA heuristics                                           │
│  • Duplicate detection                                              │
└─────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────┐
│  LLM CALL #1: Intent Classification ($0.00125)                      │
│  • Event request / Question / Acceptance / Change                   │
└─────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────┐
│  LLM CALL #2: Entity Extraction ($0.002)                            │
│  • Dates, participants, products, billing, etc.                     │
└─────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Scattered Regex Checks (no central coordination)                   │
│  • Confirmation, room choice, product, billing fragment...          │
└─────────────────────────────────────────────────────────────────────┘


IMPROVED PIPELINE (1-2 LLM calls/message):
┌─────────────────────────────────────────────────────────────────────┐
│  Message Input                                                       │
└─────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────┐
│  LAYER 0: Unified Keyword Pre-Filter ($0)                           │
│  ─────────────────────────────────────────────────────────────────  │
│  ALWAYS runs, sets flags for downstream:                            │
│                                                                      │
│  ✓ Duplicate detection (exact match)                                │
│  ✓ Language detection (DE/EN keywords)                              │
│  ✓ Billing presence (address-like patterns)                         │
│  ✓ Manager/escalation signals ("ask manager", "speak to Tom")       │
│  ✓ Urgency signals ("urgent", "asap", "dringend")                   │
│  ✓ Confirmation signals ("yes", "ok", "agreed")                     │
│  ✓ Change signals ("change", "actually", "instead")                 │
│  ✓ Question signals ("?", "what", "which", "how")                   │
│                                                                      │
│  Output: PreFilterResult with boolean flags                         │
└─────────────────────────────────────────────────────────────────────┘
        │
        ├── [EARLY RETURN] if duplicate → return duplicate response
        │
        ▼
┌─────────────────────────────────────────────────────────────────────┐
│  LLM CALL #1: Unified Message Analysis ($0.00125)                   │
│  ─────────────────────────────────────────────────────────────────  │
│  Single call that returns MULTIPLE classifications:                 │
│                                                                      │
│  {                                                                   │
│    "intent": "event_request|question|acceptance|change|escalate",   │
│    "intent_confidence": 0.95,                                       │
│    "is_manager_request": true/false,                                │
│    "change_type": "date|room|requirements|null",                    │
│    "has_billing_address": true/false,                               │
│    "language": "en|de",                                             │
│    "urgency": "normal|high"                                         │
│  }                                                                   │
│                                                                      │
│  Skips if: Pre-filter shows clear simple case (pure confirmation)   │
└─────────────────────────────────────────────────────────────────────┘
        │
        ├── [EARLY RETURN] if is_manager_request → route to HIL
        │
        ▼
┌─────────────────────────────────────────────────────────────────────┐
│  LLM CALL #2: Entity Extraction ($0.002) - CONDITIONAL              │
│  ─────────────────────────────────────────────────────────────────  │
│  Only runs if intent requires entities:                             │
│                                                                      │
│  • event_request → extract date, participants, products             │
│  • change → extract new values                                      │
│  • has_billing_address → extract billing fields                     │
│                                                                      │
│  Skips if: acceptance, simple question, escalation                  │
└─────────────────────────────────────────────────────────────────────┘
```

### Checks That MUST Run Every Message

| Check | Method | Cost | Can Skip? | Location |
|-------|--------|------|-----------|----------|
| **Duplicate Detection** | Exact string match | $0 | ❌ Never | `pre_route.py` |
| **Language Detection** | Keyword scan | $0 | ❌ Never | NEW: `pre_filter.py` |
| **Special Flow Guard** | State check | $0 | ❌ Never | `pre_route.py` |
| **Intent Classification** | LLM | $0.00125 | ⚠️ If pure confirmation | `adapter.py` |
| **Manager Escalation** | Keywords + LLM | $0-0.00125 | ⚠️ If no signals | NEW: unified call |
| **Urgency Detection** | Keywords | $0 | ✅ Optional | NEW: `pre_filter.py` |

### Checks That Run Conditionally

| Check | Trigger | Method | Cost |
|-------|---------|--------|------|
| **Entity Extraction** | Intent needs entities | LLM | $0.002 |
| **Billing Extraction** | has_billing_address flag | LLM | $0 (in entity call) |
| **Change Detection** | change_signal flag | LLM | $0 (in unified call) |
| **Product Detection** | Intent is event_request | Catalog + regex | $0 |

### Missing Detections (To Add)

| Detection | Purpose | Method | Where |
|-----------|---------|--------|-------|
| **Manager Escalation** | "Ask Tom" / "speak to manager" | Keywords → LLM | Pre-filter + unified call |
| **Urgency Signals** | "urgent" / "asap" / "dringend" | Keywords | Pre-filter |
| **Billing Presence** | Address-like patterns anywhere | Regex | Pre-filter |
| **Language Tag** | DE vs EN for response | Keywords | Pre-filter |

---

## Cost Optimization Summary

### Cost Comparison: All Approaches

| Approach | LLM Calls/Msg | Cost/Event | vs Baseline |
|----------|---------------|------------|-------------|
| **Full OpenAI (baseline)** | 2-3 | ~$0.100 | — |
| **Current Hybrid (Gemini I/E, OpenAI V)** | 2-3 | ~$0.078 | **-22%** |
| **Improved Hybrid (unified call)** | 1-2 | ~$0.065 | **-35%** |
| **With Gemini fallbacks (billing, etc.)** | 2-3 | ~$0.090 | **-10%** |
| **Full Gemini** | 2-3 | ~$0.023 | **-77%** |

### Key Insight

**We are still better off than OpenAI-only in ALL scenarios:**

```
OpenAI-only:     $0.100/event  ████████████████████ 100%
Improved Hybrid: $0.065/event  █████████████        65%  ← BEST ACCURACY/COST
Current Hybrid:  $0.078/event  ████████████████     78%  ← CURRENT
With Fallbacks:  $0.090/event  ██████████████████   90%  ← SAFEST
Full Gemini:     $0.023/event  █████                23%  ← CHEAPEST
```

Even with ALL Gemini fallbacks added (billing, confirmation, products, site visit), we're still **10% cheaper than OpenAI-only** while being **more accurate**.

---

## Unified Pre-Filter Design

### Pre-Filter Keywords (Run on EVERY message - $0)

```python
# backend/detection/pre_filter.py (NEW)

class PreFilterResult:
    is_duplicate: bool
    language: str  # "en" | "de"

    # Signal flags (trigger LLM checks)
    has_question_signal: bool      # "?", "what", "which"
    has_confirmation_signal: bool  # "yes", "ok", "agree"
    has_change_signal: bool        # "change", "actually", "instead"
    has_manager_signal: bool       # "manager", "Tom", "escalate"
    has_urgency_signal: bool       # "urgent", "asap", "dringend"
    has_billing_signal: bool       # postal codes, street patterns

    # Confidence boosters
    confidence_boost: float        # 0.0-0.3 to add to LLM confidence

# Keyword buckets
MANAGER_SIGNALS = [
    # English
    "manager", "speak to", "talk to", "escalate", "human", "real person",
    "someone else", "supervisor", "person in charge",
    # German
    "Geschäftsführer", "Vorgesetzten", "jemand anderen", "echte Person"
]

URGENCY_SIGNALS = [
    "urgent", "asap", "immediately", "rush", "priority", "time-sensitive",
    "dringend", "sofort", "eilig", "schnell"
]

BILLING_PATTERNS = [
    r'\d{4,5}\s+\w+',           # Postal code + city
    r'\w+strasse\s+\d+',        # German street
    r'\w+street\s+\d+',         # English street
    r'CH[-\s]?\d{3}',           # Swiss postal prefix
]
```

### Unified LLM Call Prompt

```python
# Single prompt that extracts multiple classifications

UNIFIED_ANALYSIS_PROMPT = """
Analyze this client message and return a JSON object with:

Message: "{message}"
Context: Step {step}, {event_status}

Return:
{
  "intent": "event_request|acceptance|question|change|escalation|other",
  "intent_confidence": 0.0-1.0,
  "is_manager_request": true if client wants to speak to a human/manager,
  "change_type": "date|room|requirements|products|null",
  "has_billing_info": true if message contains address/billing details,
  "language": "en|de",
  "urgency": "normal|high"
}
"""
```

### When to Skip LLM Calls

| Scenario | Pre-Filter Result | LLM Call #1 | LLM Call #2 |
|----------|------------------|-------------|-------------|
| Duplicate message | `is_duplicate=True` | ❌ Skip | ❌ Skip |
| Pure "yes" confirmation | `confirmation_signal` only | ❌ Skip* | ❌ Skip |
| Manager request | `manager_signal=True` | ✅ Verify | ❌ Skip |
| Simple question | `question_signal` + no entities | ✅ Classify | ❌ Skip |
| Event request | No shortcuts | ✅ Classify | ✅ Extract |

*Pure confirmation skips LLM if no ambiguity detected

---

## Gemini Free Tier Budget

With the improved architecture:

| Scenario | Calls/Message | Daily Messages (Free) |
|----------|---------------|----------------------|
| Current (2 calls) | 2 | 750 |
| Improved (1.5 avg) | 1.5 | 1,000 |
| With fallbacks (2.5 avg) | 2.5 | 600 |

**Conclusion:** Even with all safety fallbacks, Gemini free tier supports **~600 messages/day** (~20 events with ~30 messages each).

---

## Configuration

### Admin UI (Recommended)

Access at `http://localhost:3000` → LLM Settings panel

Shows: `I:gemini E:gemini V:openai` (Intent, Entity, Verbalization)

### Environment Variables

```bash
# Global provider override (legacy)
AGENT_MODE=openai|gemini|stub

# Per-operation (set via admin UI, stored in database)
# Falls back to AGENT_MODE if not configured
```

### Database Storage

Provider settings persist in `backend/events_database.json`:
```json
{
  "llm_config": {
    "intent_provider": "gemini",
    "entity_provider": "gemini",
    "verbalization_provider": "openai",
    "updated_at": "2025-12-29T12:00:00Z"
  }
}
```

---

## Cost Analysis

### Per-Message Breakdown

| Operation | Gemini | OpenAI | Typical |
|-----------|--------|--------|---------|
| Intent | $0.00125 | $0.005 | 1x |
| Entity | $0.002 | $0.008 | 1x |
| Verbalization | $0.004 | $0.015 | ~5x/event |

### Per-Event Estimates

| Config | Intent | Entity | Verbal (5x) | Total |
|--------|--------|--------|-------------|-------|
| Full OpenAI | $0.005 | $0.008 | $0.075 | **$0.088** |
| Hybrid (recommended) | $0.00125 | $0.002 | $0.075 | **$0.078** |
| Full Gemini | $0.00125 | $0.002 | $0.020 | **$0.023** |
| Stub | $0 | $0 | $0 | **$0** |

### Gemini Free Tier

| Limit | Value | Implication |
|-------|-------|-------------|
| RPM | 15 | Max 15 requests/minute |
| TPD | 1M tokens | ~500 events/day |
| RPD | 1500 | ~750 messages/day |

Calculation: Each message = 1 intent + 1 entity = 2 API calls → 750 messages/day

---

## File Reference

### LLM Adapters
- `backend/workflows/llm/adapter.py` - Main adapter routing
- `backend/llm/providers/gemini_adapter.py` - Gemini implementation
- `backend/llm/providers/openai_adapter.py` - OpenAI implementation
- `backend/llm/providers/stub_adapter.py` - Testing stub

### Extraction Pipeline
- `backend/workflows/steps/step1_intake/trigger/entity_extraction.py` - Pipeline coordinator
- `backend/workflows/steps/step1_intake/trigger/keyword_matching.py` - Regex patterns
- `backend/workflows/steps/step1_intake/trigger/normalization.py` - Date/time normalization

### Verbalization
- `backend/ux/verbalizer.py` - Draft composition
- `backend/ux/verbalizer_safety.py` - Fact-checking layer

### Configuration
- `backend/api/routes/config.py` - API endpoints for provider config
- `atelier-ai-frontend/app/components/LLMSettings.tsx` - Admin UI

---

## Recommended Configuration

For production, use **Hybrid Mode** (default):

```
Intent:        Gemini  (cheap, good accuracy)
Entity:        Gemini  (cheap, good structured extraction)
Verbalization: OpenAI  (quality for client-facing messages)
```

This provides:
- ~20% cost savings vs full OpenAI
- High-quality client communication
- Reliable entity extraction
- Gemini free tier sufficient for ~750 messages/day
