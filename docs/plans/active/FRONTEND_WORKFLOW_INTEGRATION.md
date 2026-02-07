# Frontend-Backend Workflow Integration Plan

> **Status:** DRAFT - Pending Review
> **Created:** 2026-02-03
> **Last Updated:** 2026-02-03
> **Codex Review:** REQUEST_CHANGES (5 blockers identified)

## Overview

Enable the OpenEvent workflow engine to react to manager actions performed on the frontend platform (app.openevent.io). When a manager creates, updates, or cancels objects (events, rooms, offers, site visits), the workflow should adapt accordingly—triggering detours, updating state, or notifying clients.

---

## Current State Analysis

### Frontend Objects (from `/Users/nico/Documents/GitHub/OpeneventGithub/src`)

| Entity | Supabase Table | CRUD Hooks | Realtime Sync |
|--------|---------------|------------|---------------|
| Event | `events` | `useEvents.ts` | ✅ GlobalAutoRefresh |
| Offer | `offers` | `useOffers.ts` | ✅ Channel subscription |
| Room | `rooms` | `useRooms.ts` | ✅ GlobalAutoRefresh |
| Client | `clients` | `useClients.ts` | ✅ GlobalAutoRefresh |
| TicketLink | `ticket_links` | `useTicketLinks.ts` | ✅ Channel subscription |
| TableReservation | `table_reservations` | `useTableReservations.ts` | ✅ Channel subscription |
| SiteVisit | (embedded in events) | via `useEvents.ts` | ✅ |

### Backend Capabilities

| Feature | Status | Location |
|---------|--------|----------|
| Detour mechanism | ✅ Works | `workflows/steps/step3_room_availability/trigger/detour_handling.py` |
| Change propagation DAG | ✅ Works | `workflows/change_propagation.py` |
| Hash-based change detection | ✅ Works | `requirements_hash`, `room_eval_hash`, `offer_hash` |
| Deposit payment API | ✅ Works | `POST /api/event/deposit/pay` |
| Event cancellation API | ✅ Works | `POST /api/event/{event_id}/cancel` |
| Supabase adapter | ✅ CRUD | `workflows/io/integration/supabase_adapter.py` |
| Calendar sync | 🔴 Stub | `utils/calendar_events.py` (JSON files only) |
| Webhook receivers | 🔴 None | No incoming handlers |
| Supabase realtime | 🔴 None | No `.on()` listeners |

### Gap Summary

**The workflow engine cannot react to manager actions because:**
1. Frontend updates Supabase directly via hooks
2. Backend has no realtime listeners on Supabase
3. No webhook endpoints exist for manager-initiated changes
4. Existing detour logic only triggers from client email messages

---

## Critical Blockers (from Codex Review)

### BLOCKER 1: Race Condition - Manager + Client Concurrent Actions

**Problem:** No locking mechanism specified for concurrent modifications.

**Scenario:**
```
T0: Client sends "Actually, let's change to March 5th" (triggers detour)
T1: Manager changes date to April 1st via frontend
T2: Step 1 processes client message, sets caller_step=5, current_step=2
T3: Manager action handler sets current_step=2, caller_step=? (collision)
```

**Required Solution:**
```python
# Add to supabase_adapter.py
def update_event_with_lock(event_id, updates, expected_version):
    """Update event only if version matches (optimistic lock)"""
    result = supabase.from_("events") \
        .update({**updates, "version": expected_version + 1}) \
        .eq("id", event_id) \
        .eq("version", expected_version) \
        .execute()
    if not result.data:
        raise ConcurrentModificationError(f"Event {event_id} was modified")
```

### BLOCKER 2: Detour Collision - Caller Step Overwrite

**Problem:** Manager actions could corrupt the `caller_step` return path during active client detours.

**Decision Required:**
- **Option A (MVP):** Block manager actions during active client detours
- **Option B (v2):** Implement detour stack for nested detours

**Recommendation:** Option A for MVP

```python
def process_manager_action(event_id, action_type, payload):
    event_entry = load_event(event_id)

    # BLOCKER 2: Check for active detour
    if event_entry.get("caller_step") is not None:
        raise ActiveDetourError(
            f"Cannot modify event during active detour. "
            f"Current: step {event_entry['current_step']}, "
            f"returning to: step {event_entry['caller_step']}"
        )
```

### BLOCKER 3: Billing Flow Interference

**Problem:** Manager changes during billing capture flow could desync state.

**From BUG-023, BUG-024, BUG-025 in TEAM_GUIDE:**
> When client is in billing flow (awaiting address after offer acceptance), date changes must clear billing state.

**Required Solution:**
```python
def _handle_manager_date_change(event_entry, payload):
    # BLOCKER 3: Clear billing flow if active
    if event_entry.get("awaiting_billing_for_accept"):
        event_entry["awaiting_billing_for_accept"] = False
        event_entry["offer_accepted"] = False
        log_workflow_activity(event_entry, "billing_flow_cancelled_by_manager_action")
```

### BLOCKER 4: State Sync - The `state.current_step` Invariant

**Problem:** Manager actions modify `event_entry` directly. If client message is processing simultaneously, `state` won't reflect changes.

**Required Solution:**
```python
# In workflow_email.py:_finalize_output
if event_entry.get("version") != state.original_version:
    logger.warning("Concurrent modification detected, reloading state")
    # Reload + merge, or abort + retry
    raise StaleStateError("Event was modified during processing")
```

### BLOCKER 5: Frontend Fallback - Silent Desync

**Problem:** If frontend bypasses workflow API, backend won't see changes.

**Required Solution:** Add Supabase trigger for detection:
```sql
CREATE OR REPLACE FUNCTION log_direct_event_update()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.locked_room_id != OLD.locked_room_id
       AND NEW.last_updated_via != 'workflow_api' THEN
        INSERT INTO direct_update_warnings (event_id, field, old_val, new_val, detected_at)
        VALUES (NEW.id, 'locked_room_id', OLD.locked_room_id, NEW.locked_room_id, NOW());
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

---

## Proposed Architecture

### Option A: API-First (Recommended)

Frontend calls dedicated backend endpoints for workflow-affecting actions. Backend updates Supabase AND triggers workflow adaptation.

```
Manager Action → Frontend → Backend API → [Lock + Validate + Update Supabase + Trigger Workflow] → Realtime → Frontend UI
```

**Pros:** Full control, audit trail, validation, locking
**Cons:** Requires frontend changes

### Option B: Supabase Triggers (Backup/Audit)

Use as safety net to detect frontend bypasses, not primary mechanism.

---

## Implementation Plan

### Phase 0: Infrastructure (Blockers)

**Add to:** `workflows/io/database.py`, `supabase_adapter.py`

1. Add `version` field to event entries
2. Implement `update_event_with_lock()` with optimistic locking
3. Add `ConcurrentModificationError` exception
4. Add `ActiveDetourError` exception
5. Add stale state detection in `_finalize_output()`

### Phase 1: Manager Action API Endpoints

**New file:** `api/routes/manager_actions.py`

| Endpoint | Trigger | Workflow Effect |
|----------|---------|-----------------|
| `PUT /api/manager/events/{id}/date` | Manager changes event date | Detour to Step 2 |
| `PUT /api/manager/events/{id}/room` | Manager changes room | Detour to Step 3 |
| `PUT /api/manager/events/{id}/requirements` | Manager updates participants/layout | Invalidate hashes |
| `POST /api/manager/events/{id}/cancel-room` | Manager cancels room reservation | Detour to Step 3, notify client |
| `PUT /api/manager/offers/{id}/update` | Manager modifies offer | Invalidate `offer_hash` |
| `POST /api/manager/site-visit/{id}/reschedule` | Manager reschedules site visit | Update state, notify client |
| `POST /api/manager/hil/{task_id}/approve` | Manager approves HIL task | Send message |
| `POST /api/manager/hil/{task_id}/reject` | Manager rejects HIL task | Log rejection |

**Each endpoint must:**
1. Acquire event lock (version check)
2. Check for active detours (BLOCKER 2)
3. Check billing flow state (BLOCKER 3)
4. Validate business rules
5. Update Supabase via adapter
6. Trigger workflow adaptation
7. Log activity
8. Return updated state

### Phase 2: Workflow Adaptation Logic

**Modify:** `workflows/change_propagation.py`

```python
class ManagerActionType(Enum):
    DATE_CHANGE = "date_change"
    ROOM_CHANGE = "room_change"
    ROOM_CANCELLATION = "room_cancellation"
    REQUIREMENTS_UPDATE = "requirements_update"
    OFFER_UPDATE = "offer_update"
    SITE_VISIT_RESCHEDULE = "site_visit_reschedule"

def process_manager_action(event_id: str, action_type: ManagerActionType, payload: dict) -> WorkflowResult:
    """
    Process manager-initiated action and adapt workflow state.

    Unlike client messages:
    - No LLM detection needed (action is explicit)
    - May override workflow state directly
    - Should generate client notification drafts
    """
    event_entry = load_event(event_id)

    # BLOCKER 1: Acquire lock
    if not acquire_event_lock(event_id, event_entry["version"]):
        raise ConcurrentModificationError()

    # BLOCKER 2: Check active detour
    if event_entry.get("caller_step") is not None:
        raise ActiveDetourError()

    # BLOCKER 3: Handle billing flow
    if event_entry.get("awaiting_billing_for_accept"):
        clear_billing_state(event_entry)

    # Map to existing change routing (reuse DAG logic)
    change_type_map = {
        ManagerActionType.DATE_CHANGE: ChangeType.DATE,
        ManagerActionType.ROOM_CHANGE: ChangeType.ROOM,
        ManagerActionType.ROOM_CANCELLATION: ChangeType.ROOM,
        ManagerActionType.REQUIREMENTS_UPDATE: ChangeType.REQUIREMENTS,
        ManagerActionType.OFFER_UPDATE: ChangeType.COMMERCIAL,
        ManagerActionType.SITE_VISIT_RESCHEDULE: ChangeType.SITE_VISIT,
    }

    change_type = change_type_map[action_type]

    # Reuse existing routing logic
    decision = route_change_on_updated_variable(
        event_entry,
        change_type,
        from_step=event_entry["current_step"]
    )

    # Generate notification draft
    notification = generate_notification_draft(action_type, event_entry, payload)

    return WorkflowResult(
        decision=decision,
        notification_draft=notification,
        event_entry=event_entry
    )
```

### Phase 3: Client Notification Drafts

**New file:** `workflows/notifications/manager_action_drafts.py`

```python
def generate_notification_draft(action_type: ManagerActionType, event_entry: dict, payload: dict) -> str:
    """Generate client-facing message about manager-initiated change."""

    templates = {
        ManagerActionType.DATE_CHANGE: """
We wanted to let you know that your event date has been updated.

Previous date: {old_date}
New date: {new_date}

If you have any questions about this change, please let us know.
""",
        ManagerActionType.ROOM_CANCELLATION: """
We need to inform you about a change to your room reservation.

The {room_name} is no longer available for your event on {event_date}.

We'd like to offer you the following alternatives:
{alternative_rooms}

Please let us know which option works best for you.
""",
        # ... more templates
    }

    return templates[action_type].format(**payload)
```

**Notification policy (from Codex):**
- **Before client confirmation:** Silent OK (manager refining offer)
- **After client confirmation:** MUST notify
- **After deposit paid:** MUST notify + require client re-confirmation

### Phase 4: Frontend Integration Points

**Frontend changes needed** (in `/Users/nico/Documents/GitHub/OpeneventGithub/src`):

1. **`useEvents.ts`**: Add `updateEventViaWorkflow()` for workflow-affecting fields
2. **`useOffers.ts`**: Add `updateOfferViaWorkflow()` for changes needing notification
3. **Event detail pages**: Route saves through workflow API when thread active

**Detection logic:**
```typescript
const shouldUseWorkflowAPI = (event: Event) => {
  // Use workflow API if event has active email thread
  return event.thread_state !== 'closed' && event.thread_state !== null;
};

// Example: changing event date
const updateEventDate = async (eventId: string, newDate: string) => {
  const event = await getEvent(eventId);

  if (shouldUseWorkflowAPI(event)) {
    // Call workflow API - triggers detours, notifications
    return await fetch(`/api/manager/events/${eventId}/date`, {
      method: 'PUT',
      body: JSON.stringify({ new_date: newDate })
    });
  } else {
    // Direct Supabase update - no active workflow
    return await supabase.from('events').update({ event_date: newDate }).eq('id', eventId);
  }
};
```

### Phase 5: Calendar Integration (Deferred)

Replace stub in `utils/calendar_events.py` with real calendar API. Lower priority - independent of core workflow adaptation.

---

## Files to Create/Modify

### New Files
| File | Purpose |
|------|---------|
| `api/routes/manager_actions.py` | Manager action API endpoints |
| `workflows/manager_actions.py` | Action processing + locking |
| `workflows/notifications/manager_action_drafts.py` | Client notification templates |
| `tests/regression/test_manager_actions.py` | Unit tests |
| `tests/regression/test_manager_concurrency.py` | Race condition tests |

### Modified Files
| File | Changes |
|------|---------|
| `workflows/io/database.py` | Add `version` field, locking helpers |
| `workflows/io/integration/supabase_adapter.py` | Add `update_event_with_lock()` |
| `workflows/change_propagation.py` | Add `process_manager_action()` |
| `workflows/runtime/workflow_email.py` | Add stale state detection |
| `activity/persistence.py` | Add manager action activity types |
| `api/main.py` | Register new router |

---

## Verification Plan

### Unit Tests
```bash
pytest tests/regression/test_manager_actions.py -v
```

| Test Case | Validates |
|-----------|-----------|
| `test_manager_date_change_triggers_step2_detour` | Basic routing |
| `test_manager_room_cancellation_triggers_step3` | Room detour |
| `test_manager_requirements_update_invalidates_hashes` | Hash invalidation |
| `test_manager_offer_update_generates_notification` | Notification drafts |
| `test_hil_approval_sends_message` | HIL integration |
| `test_activity_log_records_manager_actions` | Audit trail |

### Concurrency Tests (CRITICAL)
```bash
pytest tests/regression/test_manager_concurrency.py -v
```

| Test Case | Validates |
|-----------|-----------|
| `test_concurrent_client_and_manager_change` | BLOCKER 1: Locking |
| `test_manager_action_during_active_detour_blocked` | BLOCKER 2: Detour collision |
| `test_manager_change_clears_billing_flow` | BLOCKER 3: Billing |
| `test_stale_state_detection` | BLOCKER 4: State sync |
| `test_direct_supabase_update_logged` | BLOCKER 5: Bypass detection |

### E2E Verification
1. Start backend: `./scripts/dev/dev_server.sh`
2. Call manager action endpoints via curl/Postman
3. Verify workflow state in `tmp-debug/` logs
4. Verify Supabase updates via frontend UI

---

## Open Decisions

| ID | Decision | Options | Recommendation |
|----|----------|---------|----------------|
| D1 | Notification strategy | Always notify / Only after confirmation | Only after confirmation |
| D2 | Override permissions | Manager can override confirmed? | Yes with notification; No after deposit without re-confirm |
| D3 | Calendar priority | MVP or deferred? | Deferred |
| D4 | HIL queue for offer changes | Auto-send or queue? | Queue after offer sent to client |
| D5 | Detour collision handling | Block (A) or Stack (B)? | Option A for MVP |

---

## Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| Race conditions | HIGH | Optimistic locking (Phase 0) |
| Detour collision | HIGH | Block during active detours (Phase 2) |
| Billing flow desync | HIGH | Clear billing state on change (Phase 2) |
| Frontend bypass | MEDIUM | Supabase trigger detection |
| Notification spam | LOW | Batch within 5-min window |
| Breaking existing tests | MEDIUM | Run full regression before/after |

---

## Implementation Timeline

| Phase | Description | Depends On |
|-------|-------------|------------|
| 0 | Locking infrastructure | - |
| 1 | API endpoints | Phase 0 |
| 2 | Workflow adaptation | Phase 0, 1 |
| 2.5 | Billing/detour guards | Phase 2 |
| 3 | Notification drafts | Phase 2 |
| 4 | Tests (including concurrency) | Phase 2.5 |
| 5 | Frontend integration | Phase 1-4 complete |
| 6 | Calendar (deferred) | Independent |

---

## Appendix: Feature Interference Matrix

| Feature | Manager Actions Impact | Mitigation |
|---------|------------------------|------------|
| Q&A | LOW - No overlap | None needed |
| Hybrid Messages | MEDIUM - Lock contention | Event-level locking |
| Detours | HIGH - `caller_step` collision | Block during active detours |
| Gatekeeping | HIGH - Gate bypass risk | Check gates in endpoints |
| Confirmations | MEDIUM - State desync | Clear confirmation on change |
| Shortcuts | LOW - State-dependent | Locking handles this |

---

## References

- `docs/architecture/MASTER_ARCHITECTURE_SHEET.md` - Behavioral invariants
- `docs/guides/TEAM_GUIDE.md` - BUG-023 through BUG-025 (billing flow)
- `workflows/change_propagation.py:317-461` - Routing logic to reuse
- `/Users/nico/Documents/GitHub/OpeneventGithub/src/hooks/` - Frontend CRUD patterns
