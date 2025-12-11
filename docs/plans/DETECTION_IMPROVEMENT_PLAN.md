# Detection Improvement Plan: Advanced Room Search & Booking Intents

## 1. Executive Summary
This plan outlines the strategy to enhance the Natural Language Understanding (NLU) capabilities of the OpenEvent-AI platform. By integrating industry best practices and specific keyword findings, we aim to transition from simple "availability checking" to a nuanced system that distinguishes between **casual inquiries**, **tentative options**, **capacity constraints**, and **firm commitments**.

## 2. Current State Analysis

### Existing Components
*   **`backend/llm/intent_classifier.py`:**
    *   **Method:** Simple substring matching against static lists (`_QNA_KEYWORDS`).
    *   **Limitation:** Lacks granularity. "Can I book?" and "Is it free?" are often treated identically or routed to generic Q&A.
*   **`backend/workflows/nlu/general_qna_classifier.py`:**
    *   **Method:** Regex + LLM for vague date queries.
    *   **Limitation:** Focuses primarily on *when* (dates), not *how* (booking status/options).
*   **`backend/workflows/nlu/room_search_keywords.py` (New):**
    *   **Method:** Advanced Regex patterns categorized by specific user intent (Option, Capacity, Alternatives).
    *   **Status:** Created but not yet integrated into the main classification pipeline.

### Weaknesses Identified
1.  **Ambiguity:** No distinction between "checking availability" vs. "requesting a hold" (Option).
2.  **Missing Signals:** Strong booking confirmation signals (e.g., "green light", "lock it in") are not explicitly boosted over generic "yes".
3.  **Capacity Gaps:** Questions about room fit ("fits 60?") are not treated as structural constraints.
4.  **Waitlist/Alternatives:** No specific logic to detect when a user is asking for "next available" or "waitlist".

## 3. Industry Best Practices & Web Search Findings

### Key Concepts
*   **Hybrid Intent Classification:** Combine fast, precise Regex (for known phrases) with LLMs (for ambiguity).
*   **Granular Intent Buckets:** Successful booking bots distinguish between:
    *   *Availability Search* ("Is X free?")
    *   *Option Request* ("Hold X for me")
    *   *Booking Confirmation* ("Book X")
*   **Faithful Planning:** Extracting constraints (capacity, layout) *before* checking availability.

### Specific Keyword Insights
Based on web research, we have identified robust keyword sets for these missing categories:

| Category | Intent | Key Phrases (New/Enhanced) |
| :--- | :--- | :--- |
| **Tentative** | `REQUEST_OPTION` | "provisional booking", "soft hold", "tentative option", "subject to release", "put on hold" |
| **Confirmed** | `CONFIRM_BOOKING` | "green light", "lock it in", "secure the date", "sign me up", "binding booking", "firm commitment" |
| **Capacity** | `CHECK_CAPACITY` | "fits X people", "standing capacity", "theater style for X", "max guests", "sufficient space" |
| **Alternatives** | `CHECK_ALTERNATIVES` | "waitlist", "if not available", "next opening", "nearest date", "backup option" |

## 4. Implementation Plan

### Phase 1: Integration of `room_search_keywords.py`
**Objective:** Replace/Augment simple keyword lists in `intent_classifier.py` with the new regex-based module.

1.  **Update `backend/llm/intent_classifier.py`:**
    *   Import `detect_room_search_intent` from the new module.
    *   Modify `_detect_qna_types` to prioritize the new intents.
    *   **Mapping:**
        *   `RoomSearchIntent.REQUEST_OPTION` -> `request_option` (New Q&A type)
        *   `RoomSearchIntent.CHECK_CAPACITY` -> `check_capacity` (New Q&A type)
        *   `RoomSearchIntent.CONFIRM_BOOKING` -> `booking_confirmation` (New Q&A type)

2.  **Enhance `classify_intent` Routing:**
    *   If `booking_confirmation` is detected, force routing to **Offer Review** (or relevant confirmation step), overriding generic Q&A.
    *   If `request_option` is detected, route to **Room Availability** but set a context flag `wants_option=True` to prompt the agent to offer a tentative hold.

### Phase 2: Workflow Handling (Future)
**Objective:** Ensure the *Workflow* actually reacts to these new signals.

1.  **Room Availability Step:**
    *   Handle `check_capacity`: Check room metadata before checking calendar availability.
    *   Handle `check_alternatives`: If requested room is full, automatically search +/- 3 days.
    *   Handle `request_option`: Call "Tentative Hold" API instead of just showing "Available".

2.  **Offer Review Step:**
    *   Handle `booking_confirmation`: Trigger contract generation immediately.

## 5. Next Steps
1.  **Approve** this plan.
2.  **Execute Phase 1:** Modify `backend/llm/intent_classifier.py` to wire in the new detection logic.
3.  **Verify:** Run `tests/fixtures/room_search_cases.json` (to be created) against the new classifier.
