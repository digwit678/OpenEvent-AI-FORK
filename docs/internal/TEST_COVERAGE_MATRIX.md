# OpenEvent Test Coverage Matrix

## Overview

This document tracks all testable scenarios for detection, detours, shortcuts, Q&A, and HIL flows.
Organized by category with test file references and coverage status.

---

## 1. DETOUR DETECTION (Change Detection)

### 1.1 Change Types by Variable

| Variable | From Step | Change Type | Mode | Tested | Test ID |
|----------|-----------|-------------|------|--------|---------|
| **DATE** | Step 3 | Simple change | FAST | ✅ | `DET_DETOUR_EN_DATE_001` |
| DATE | Step 3 | Sorry correction | FAST | ✅ | `DET_DETOUR_EN_DATE_002` |
| DATE | Step 3 | Reschedule | FAST | ✅ | `DET_DETOUR_EN_DATE_003` |
| DATE | Step 3 | Conflict (no new date) | LONG | ✅ | `DET_DETOUR_EN_DATE_004` |
| DATE | Step 3 | Double-booked | LONG | ✅ | `DET_DETOUR_EN_DATE_005` |
| DATE | Step 3 | Push back | FAST | ✅ | `DET_DETOUR_EN_DATE_006` |
| DATE | Step 3 | No longer works | LONG | ✅ | `DET_DETOUR_EN_DATE_007` |
| DATE | Step 3 | DE: Termin verschieben | FAST | ✅ | `DET_DETOUR_DE_DATE_001` |
| DATE | Step 3 | DE: klappt doch nicht | LONG | ✅ | `DET_DETOUR_DE_DATE_002` |
| DATE | Step 3 | DE: stattdessen | FAST | ✅ | `DET_DETOUR_DE_DATE_003` |
| DATE | Step 3 | DE: doch lieber | FAST | ✅ | `DET_DETOUR_DE_DATE_004` |
| DATE | Step 4 | Change at offer | - | ⚠️ NEEDS | - |
| DATE | Step 5 | Change during negotiation | - | ⚠️ NEEDS | - |
| **ROOM** | Step 3 | Switch room | FAST | ✅ | `DET_DETOUR_EN_ROOM_001` |
| ROOM | Step 3 | Bigger room (no specific) | LONG | ✅ | `DET_DETOUR_EN_ROOM_002` |
| ROOM | Step 3 | Prefer different | FAST | ✅ | `DET_DETOUR_EN_ROOM_003` |
| ROOM | Step 3 | DE: Raum wechseln | FAST | ✅ | `DET_DETOUR_DE_ROOM_001` |
| ROOM | Step 4 | Change after offer | - | ⚠️ NEEDS | - |
| **REQUIREMENTS** | Step 3 | More people | FAST | ✅ | `DET_DETOUR_EN_REQ_001` |
| REQUIREMENTS | Step 3 | Numbers up | FAST | ✅ | `DET_DETOUR_EN_REQ_002` |
| REQUIREMENTS | Step 3 | Layout change | FAST | ✅ | `DET_DETOUR_EN_REQ_003` |
| REQUIREMENTS | Step 3 | DE: mehr Personen | FAST | ✅ | `DET_DETOUR_DE_REQ_001` |
| REQUIREMENTS | Step 4 | Capacity at offer | - | ⚠️ NEEDS | - |
| REQUIREMENTS | Step 5 | Capacity during negotiation | - | ⚠️ NEEDS | - |
| **PRODUCTS** | Step 4 | Add product | FAST | ✅ | `DET_DETOUR_EN_PROD_001` |
| PRODUCTS | Step 4 | Upgrade package | FAST | ✅ | `DET_DETOUR_EN_PROD_002` |
| PRODUCTS | Step 5 | Add during negotiation | - | ⚠️ NEEDS | - |

### 1.2 Detour Mode Detection

| Mode | Condition | Tested | Test ID |
|------|-----------|--------|---------|
| LONG | No new value provided | ✅ | `DET_DETOUR_MODE_001` |
| FAST | New value provided | ✅ | `DET_DETOUR_MODE_002` |
| EXPLICIT | Old and new mentioned | ✅ | `DET_DETOUR_MODE_003` |

### 1.3 Dual Condition Logic

| Scenario | Expected | Tested | Test ID |
|----------|----------|--------|---------|
| Revision signal + bound target | DETOUR | ✅ | `DET_DETOUR_DUAL_001` |
| Revision signal only (no target) | NO DETOUR | ✅ | `DET_DETOUR_DUAL_002` |
| Target only (no revision) | NO DETOUR | ✅ | `DET_DETOUR_DUAL_003` |
| Pure Q&A question | NO DETOUR | ✅ | `DET_DETOUR_DUAL_004` |

### 1.4 Q&A Negative Filter (Change Detection)

| Input | Expected | Tested | Test ID |
|-------|----------|--------|---------|
| "What rooms are free?" | NO DETOUR | ✅ | `DET_DETOUR_QA_001` |
| "Do you have parking?" | NO DETOUR | ✅ | `DET_DETOUR_QA_002` |
| "What's the total price?" | NO DETOUR | ✅ | `DET_DETOUR_QA_003` |
| "Which room fits 30 people?" | NO DETOUR | ✅ | `DET_DETOUR_QA_004` |
| DE: "Gibt es freien Termin?" | NO DETOUR | ✅ | `DET_DETOUR_QA_005` |
| "What menu options?" | NO DETOUR | ✅ | `DET_DETOUR_QA_006` |

### 1.5 Confirmation vs Change

| Input | Expected | Tested | Test ID |
|-------|----------|--------|---------|
| "That sounds good, proceed" | CONFIRMATION | ✅ | `DET_DETOUR_CONF_001` |
| "Yes, proceed with that date" | CONFIRMATION | ✅ | `DET_DETOUR_CONF_002` |
| Same value mentioned | CONFIRMATION | ✅ | `DET_DETOUR_CONF_003` |

### 1.6 Hypothetical Questions

| Input | Expected | Tested | Test ID |
|-------|----------|--------|---------|
| "What if we changed?" | NO CHANGE | ✅ | `DET_DETOUR_HYPO_001` |
| "Hypothetically, could we?" | NO CHANGE | ✅ | `DET_DETOUR_HYPO_002` |
| "Just wondering, would it?" | NO CHANGE | ✅ | `DET_DETOUR_HYPO_003` |

### 1.7 Ambiguous Target Resolution

| Scenario | Expected | Tested | Test ID |
|----------|----------|--------|---------|
| Value without type, single variable | Auto-infer | ✅ | `DET_DETOUR_AMBIG_002` |
| Value without type, multiple variables | Disambiguation | ✅ | `DET_DETOUR_AMBIG_003` |
| Recency-based inference | Use most recent | ✅ | `DET_DETOUR_AMBIG_004` |
| Explicit type mention | No disambiguation | ✅ | `DET_DETOUR_AMBIG_005` |

---

## 2. Q&A DETECTION

### 2.1 Q&A Type Classification

| Q&A Type | Example Input | Tested | Test ID |
|----------|---------------|--------|---------|
| rooms_by_feature | "Do your rooms have HDMI?" | ✅ | `DET_QNA_001` |
| rooms_by_feature | "Which rooms have projector?" | ✅ | `DET_QNA_001_variant` |
| availability_general | "Rooms free Saturdays in Feb?" | ✅ | `DET_QNA_002` |
| availability_general | "Saturday evenings in March?" | ✅ | `DET_QNA_002_variant` |
| catering_for | "What menus do you offer?" | ✅ | `DET_QNA_003` |
| catering_for | "Do you provide coffee breaks?" | ✅ | `DET_QNA_003_variant` |
| site_visit_overview | "Can we arrange a tour?" | ✅ | `DET_QNA_005` |
| parking_policy | "Where can guests park?" | ✅ | `DET_QNA_006` |

### 2.2 Mixed Step + Q&A

| Input | Expected | Tested | Test ID |
|-------|----------|--------|---------|
| "Dec 10-11 for 22. Do rooms have HDMI?" | primary=date, secondary=rooms_by_feature | ✅ | `DET_QNA_004` |

### 2.3 Q&A Fallback Prevention

| Scenario | Expected | Tested | Test ID |
|----------|----------|--------|---------|
| General Q&A returns stub | FAIL | ✅ | `DET_QNA_FALLBACK_001` |
| Product request not Q&A | is_general=False | ✅ | `DET_QNA_FALLBACK_002` |
| Room features query | Returns data | ✅ | `DET_QNA_FALLBACK_003` |

### 2.4 Q&A Context Filtering

| Context | Input | Expected | Tested | Test ID |
|---------|-------|----------|--------|---------|
| Step 3 first entry | "What catering options?" | Q&A ALLOWED | ✅ (Manual E2E) | - |
| Step 3 first entry | "Do you have parking?" | Q&A ALLOWED | ⚠️ NEEDS | - |
| After detour | Q&A question | Q&A ALLOWED | ⚠️ NEEDS | - |
| Billing flow | Q&A question | BYPASS | ⚠️ NEEDS | - |
| Deposit flow | Q&A question | BYPASS | ⚠️ NEEDS | - |

---

## 3. SHORTCUTS (Entity Capture)

### 3.1 Shortcut Extraction

| Entity | Example Input | Expected | Tested | Test ID |
|--------|---------------|----------|--------|---------|
| capacity | "Event for 30 people" | 30 | ✅ | `DET_SHORT_001` |
| capacity | "about 25 guests" | 25 | ✅ | `DET_SHORT_001_variants` |
| capacity | "~50 participants" | 50 | ✅ | `DET_SHORT_001_variants` |
| date | "Thinking December 10" | 2025-12-10 | ✅ | `DET_SHORT_002` |
| date | "2025-12-10" (ISO) | 2025-12-10 | ✅ | `DET_SHORT_002_iso` |
| date | "10.12.2025" (EU) | 2025-12-10 | ✅ | `DET_SHORT_002_european` |
| products | "We'll need a projector" | [projector] | ✅ | `DET_SHORT_003` |
| products | "projector, coffee, mic" | [projector, coffee, mic] | ✅ | `DET_SHORT_003_multiple` |

### 3.2 Multiple Shortcuts

| Input | Expected | Tested | Test ID |
|-------|----------|--------|---------|
| "30 people on Dec 10 with projector" | All captured | ✅ | `DET_SHORT_004` |

### 3.3 Invalid Shortcut Rejection

| Input | Expected | Tested | Test ID |
|-------|----------|--------|---------|
| "Negative -5 people" | NOT captured | ✅ | `DET_SHORT_005_negative` |
| "for 0 people" | NOT captured | ✅ | `DET_SHORT_005_zero` |
| "sometime next week" (vague) | NOT captured | ✅ | `DET_SHORT_005_vague` |

### 3.4 Shortcut Reuse (No Re-ask)

| Scenario | Expected | Tested | Test ID |
|----------|----------|--------|---------|
| Valid shortcut exists, unchanged | Reuse silently | ✅ | `DET_SHORT_006` |

### 3.5 Shortcut Edge Cases (Multi-Variable)

| Scenario | Expected | Tested | Test ID |
|----------|----------|--------|---------|
| Date + capacity confirmed, room fails | Return to Step 3 | ✅ (Manual E2E) | - |
| Date confirmed, capacity exceeds all rooms | Prompt for new date/capacity | ⚠️ NEEDS | - |

---

## 4. HIL (Human-in-the-Loop)

### 4.1 HIL Task Creation

| Trigger | Expected | Tested | Test ID |
|---------|----------|--------|---------|
| Offer draft at Step 4 | HIL task created | ✅ | `test_turn_7_offer_draft_hil` |
| Deposit paid | HIL task created | ✅ | `test_deposit_payment_triggers_hil` |
| Room conflict (hard) | HIL task created | ✅ | `test_hard_conflict_with_reason_creates_hil` |
| Low confidence classification | HIL fallback | ✅ | `test_off_topic_borderline_goes_to_hil` |

### 4.2 HIL Approval Flow

| Action | Expected | Tested | Test ID |
|--------|----------|--------|---------|
| Approve task | Status → APPROVED | ✅ | `test_approve_task_updates_status_to_approved` |
| Approve task | Remove from pending | ✅ | `test_approve_task_removes_from_pending` |
| Approve task | Record in hil_history | ✅ | `test_approve_task_records_hil_history` |
| Approve with notes | Notes saved | ✅ | `test_approve_with_manager_notes` |
| Approve negotiation | offer_status=Accepted | ✅ | `test_negotiation_approval_sets_offer_accepted` |
| Approve negotiation | Advance to Step 6+ | ✅ | `test_negotiation_approval_advances_step` |

### 4.3 HIL Rejection Flow

| Action | Expected | Tested | Test ID |
|--------|----------|--------|---------|
| Reject task | Remove from pending | ✅ | `test_reject_task_removes_from_pending` |
| Reject task | Record decision=rejected | ✅ | `test_reject_task_records_hil_history` |
| Reject with notes | Notes saved | ✅ | `test_reject_with_manager_notes` |

### 4.4 HIL Error Handling

| Scenario | Expected | Tested | Test ID |
|----------|----------|--------|---------|
| Approve nonexistent task | ValueError | ✅ | `test_approve_nonexistent_task_raises` |
| Reject nonexistent task | ValueError | ✅ | `test_reject_nonexistent_task_raises` |

### 4.5 HIL Deduplication

| Scenario | Expected | Tested | Test ID |
|----------|----------|--------|---------|
| Skip if pending exists | No duplicate | ✅ | `test_REG_HIL_DUP_001_skip_if_pending` |
| Skip if task exists | No duplicate | ✅ | `test_REG_HIL_DUP_001_skip_if_task_exists` |
| Create if none | Create new | ✅ | `test_REG_HIL_DUP_001_create_if_none` |

### 4.6 Billing → Deposit → HIL Flow

| Step | Expected | Tested | Test ID |
|------|----------|--------|---------|
| Billing provided | awaiting_billing=False | ✅ | `test_billing_provided_then_deposit_paid_sends_to_hil` |
| Deposit paid | HIL task created | ✅ | `test_full_flow_billing_then_deposit_to_hil` |
| Full E2E flow | Complete chain | ✅ | Manual Playwright E2E |

---

## 5. WORKFLOW FLOW TESTS

### 5.1 Happy Path (Steps 1-4)

| Turn | Action | Expected | Tested | Test ID |
|------|--------|----------|--------|---------|
| 1 | Initial inquiry | Intake, Step 1 | ✅ | `test_turn_1_intake_*` |
| 2 | Reply with email | Email captured | ✅ | `test_turn_2_*` |
| 3 | Date confirmation | Step 2 complete | ✅ | `test_turn_3_*` |
| 4 | Room selection | Step 3 complete | ✅ | `test_turn_4_*` |
| 5 | Room confirmation | locked_room_id set | ✅ | `test_turn_5_*` |
| 6 | Catering selection | Products captured | ✅ | `test_turn_6_*` |
| 7 | Offer draft | HIL task created | ✅ | `test_turn_7_offer_draft_hil` |
| 8 | HIL approve | Offer sent | ✅ | `test_turn_8_hil_approve_offer_sent` |

### 5.2 Hash Validation

| Scenario | Expected | Tested | Test ID |
|----------|----------|--------|---------|
| Requirements change | Hash invalidated | ✅ | `test_requirements_change_invalidates_hash` |
| Hash unchanged by verbalization | Pass | ✅ | `test_hashes_unchanged_by_verbalization` |

---

## 6. PRODUCTION HIL ROUTING (Email Environment)

### 6.1 Current Implementation

HIL tasks are stored in `pending_hil_requests` array in the event entry. When a task requires approval:

1. Task created with `task_id`, `type`, `draft`, `step`
2. Frontend polls `/api/tasks/pending` to show in Manager Tasks panel
3. Manager clicks Approve/Reject
4. `/api/tasks/{task_id}/approve` or `/api/tasks/{task_id}/reject` called

### 6.2 Production Email Integration (TO BE IMPLEMENTED)

For production, HIL notifications should be sent to the event manager's email:

```
Required Configuration:
- EVENT_MANAGER_EMAIL: Email address of the manager (e.g., manager@atelier.ch)
- SMTP settings for sending HIL notification emails

Flow:
1. HIL task created
2. Email sent to EVENT_MANAGER_EMAIL with:
   - Task summary
   - Client details
   - Approve/Reject links (one-click tokens)
3. Manager clicks link → API endpoint → approve/reject action
4. Confirmation email sent back

Implementation Notes:
- One-click approval tokens should be time-limited (e.g., 24h)
- Tokens should be single-use to prevent replay attacks
- Include task context in email for quick decision
```

### 6.3 HIL Routing Test Checklist

| Scenario | In Tests | E2E Verified | Prod Ready |
|----------|----------|--------------|------------|
| Task creation | ✅ | ✅ | ✅ |
| Task listing API | ✅ | ✅ | ✅ |
| Approve via API | ✅ | ✅ | ✅ |
| Reject via API | ✅ | ✅ | ✅ |
| Email notification | ✅ | ⚠️ SMTP | ✅ (code ready) |
| One-click approval links | ❌ | ❌ | ⚠️ LATER |
| Token expiry handling | ❌ | ❌ | ⚠️ LATER |

**Email Notification Implementation:**
- Service: `backend/services/hil_email_notification.py`
- Config: `POST /api/config/hil-email`
- Test: `POST /api/config/hil-email/test`
- Needs SMTP credentials for actual sending (simulates without)

---

## 7. SUMMARY: COVERAGE GAPS

### High Priority (Needs Testing)

| Category | Scenario | Priority |
|----------|----------|----------|
| DETOUR | Date change at Step 4 (offer) | HIGH |
| DETOUR | Date change at Step 5 (negotiation) | HIGH |
| DETOUR | Room change at Step 4 | HIGH |
| DETOUR | Capacity change at Step 4/5 | HIGH |
| DETOUR | Product add during negotiation | MEDIUM |
| Q&A | Q&A during billing flow bypass | HIGH |
| Q&A | Q&A during deposit flow bypass | HIGH |
| SHORTCUT | Capacity exceeds all rooms scenario | MEDIUM |
| HIL | One-click approval tokens | MEDIUM |

### Recently Implemented

| Category | Scenario | Status |
|----------|----------|--------|
| HIL | Email notification for prod | ✅ DONE (needs SMTP config) |

### Already Well Covered

- ✅ All detour modes (LONG/FAST/EXPLICIT)
- ✅ English and German change detection
- ✅ Q&A type classification
- ✅ Shortcut extraction for all entity types
- ✅ HIL approval/rejection flows
- ✅ Billing → Deposit → HIL chain
- ✅ Hash validation and invalidation
- ✅ Confirmation vs change detection
- ✅ Hypothetical question filtering

---

## Test File References

| Category | File |
|----------|------|
| Detour Detection | `backend/tests/detection/test_detour_detection.py` |
| Detour Changes | `backend/tests/detection/test_detour_changes.py` |
| Q&A Detection | `backend/tests/detection/test_qna_detection.py` |
| Shortcuts | `backend/tests/detection/test_shortcuts.py` |
| HIL Approval | `backend/tests/agents/test_manager_approve_path.py` |
| Deposit→HIL | `backend/tests/regression/test_deposit_hil_integration.py` |
| Billing→HIL | `backend/tests/regression/test_deposit_to_hil_flow.py` |
| Happy Path | `backend/tests/flow/test_happy_path_step1_to_4.py` |
| Room Conflict | `backend/tests/flow/test_room_conflict.py` |
| Semantic Matchers | `backend/tests/detection/test_semantic_matchers.py` |

---

*Last Updated: 2025-12-29*
