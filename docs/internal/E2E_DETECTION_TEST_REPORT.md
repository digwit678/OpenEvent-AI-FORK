# E2E Detection Test Report

**Date:** 2025-12-29
**Mode:** Hybrid (Gemini detection + OpenAI verbalization)
**Tester:** Claude Code

## Test Configuration

- Backend: `AGENT_MODE=gemini`, `DETECTION_MODE=unified`
- Frontend: Next.js dev server
- Browser: Playwright MCP

---

## Test Cases

### 1. Initial Booking Request
**Input:** New booking with date + participants
**Expected:** Date and participant extraction, room availability response

| Field | Expected | Actual | Status |
|-------|----------|--------|--------|
| Date extraction | YYYY-MM-DD | | |
| Participants | integer | | |
| Response type | Room availability | | |

---

### 2. Confirmation Signal
**Input:** "Yes, Room B works for me"
**Expected:** is_confirmation=True, proceed to offer

| Signal | Expected | Actual | Status |
|--------|----------|--------|--------|
| is_confirmation | True | | |
| Workflow step | Offer | | |

---

### 3. Change Request Mid-Flow
**Input:** "Actually, can we change to 50 people instead?"
**Expected:** is_change_request=True, recalculate room options

| Signal | Expected | Actual | Status |
|--------|----------|--------|--------|
| is_change_request | True | | |
| New participants | 50 | | |

---

### 4. Question/Q&A Detection
**Input:** "Do you have parking available?"
**Expected:** is_question=True, Q&A response about parking

| Signal | Expected | Actual | Status |
|--------|----------|--------|--------|
| is_question | True | | |
| qna_types | ["parking"] | | |

---

### 5. Manager Escalation Request
**Input:** "Can I speak to someone in charge?"
**Expected:** is_manager_request=True, escalation response

| Signal | Expected | Actual | Status |
|--------|----------|--------|--------|
| is_manager_request | True | | |
| Response | Escalation message | | |

---

### 6. Manager Job Title (No Escalation)
**Input:** "Hi, I'm the Event Manager at XYZ Corp, looking to book."
**Expected:** is_manager_request=False, normal booking flow

| Signal | Expected | Actual | Status |
|--------|----------|--------|--------|
| is_manager_request | False | | |
| Response | Booking flow | | |

---

### 7. Offer Acceptance
**Input:** "I accept the offer, please proceed"
**Expected:** is_acceptance=True, billing request

| Signal | Expected | Actual | Status |
|--------|----------|--------|--------|
| is_acceptance | True | | |
| Response | Billing request | | |

---

### 8. Conditional Response (Not Confirmation)
**Input:** "Yes, but I need to check with my team first"
**Expected:** is_confirmation=False (conditional)

| Signal | Expected | Actual | Status |
|--------|----------|--------|--------|
| is_confirmation | False | | |

---

### 9. Language Detection (German)
**Input:** "Ich möchte einen Raum für 20 Personen am 15.02.2026 buchen"
**Expected:** language=de, German response

| Signal | Expected | Actual | Status |
|--------|----------|--------|--------|
| language | de | | |
| Response language | German | | |

---

## Summary

| Category | Passed | Failed | Total |
|----------|--------|--------|-------|
| Entity Extraction | | | |
| Signal Detection | | | |
| Workflow Flow | | | |
| Language | | | |
| **Total** | | | |

---

## Notes

(Add observations during testing)
