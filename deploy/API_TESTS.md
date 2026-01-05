# API Endpoint Tests

All endpoints tested without frontend.

**Last updated:** 2026-01-05 (added 32 new endpoints, total: 45)

---

## Authentication

Most endpoints require the `X-Team-Id` header for multi-tenancy:

```bash
# Required header for authenticated endpoints
-H "X-Team-Id: your-team-id"
```

**Public endpoints (no auth required):**
- `GET /` - Root health check
- `GET /api/workflow/health` - Workflow health

---

## How to Run Tests

```bash
# Start backend
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000

# Run tests (in another terminal)
curl http://localhost:8000/api/workflow/health
```

---

## Test Results

### SECTION 1: Health & Status

---

### TEST 1: GET / (Root Health)
```
INPUT:    curl http://localhost:8000/
EXPECTED: {status, active_conversations, total_saved_events}
OUTPUT:   {"status":"ok","active_conversations":3,"total_saved_events":12}
RESULT:   PASS
```

---

### TEST 2: GET /api/workflow/health
```
INPUT:    curl http://localhost:8000/api/workflow/health
EXPECTED: {"ok": true, "db_path": "..."}
OUTPUT:   {"ok":true,"db_path":"/opt/openevent/backend/events_database.json"}
RESULT:   PASS
```

---

### TEST 3: GET /api/workflow/hil-status
```
INPUT:    curl http://localhost:8000/api/workflow/hil-status
EXPECTED: {"hil_all_replies_enabled": boolean}
OUTPUT:   {"hil_all_replies_enabled":false}
RESULT:   PASS
```

---

### SECTION 2: Conversation Flow

---

### TEST 4: POST /api/start-conversation
```
INPUT:    curl -X POST http://localhost:8000/api/start-conversation \
            -H "Content-Type: application/json" \
            -H "X-Team-Id: team-demo" \
            -d '{"client_email":"test@test.com","client_name":"Test User","email_body":"Book room for 25 people on April 10, 2025"}'

EXPECTED: {session_id, response, event_info, pending_actions}

OUTPUT:   {
            "session_id": "9daefa5a-1a42-49ef-9062-948e56d2c6ef",
            "workflow_type": "new_event",
            "response": "Availability overview\n\nDate options for April...",
            "is_complete": false,
            "event_info": {
              "number_of_participants": "25",
              "email": "test@test.com",
              ...
            },
            "pending_actions": {...}
          }

RESULT:   PASS
```

---

### TEST 5: POST /api/send-message
```
INPUT:    curl -X POST http://localhost:8000/api/send-message \
            -H "Content-Type: application/json" \
            -H "X-Team-Id: team-demo" \
            -d '{"session_id":"9daefa5a-1a42-49ef-9062-948e56d2c6ef","message":"Let us do December 17"}'

EXPECTED: {session_id, response, event_info}

OUTPUT:   {
            "session_id": "9daefa5a-...",
            "response": "Noted 17.12.2025. Preferred time? Examples: 14-18, 18-22.",
            "event_info": {
              "event_date": "17.12.2025",
              ...
            }
          }

RESULT:   PASS
```

---

### TEST 6: GET /api/conversation/{session_id}
```
INPUT:    curl http://localhost:8000/api/conversation/9daefa5a-1a42-49ef-9062-948e56d2c6ef \
            -H "X-Team-Id: team-demo"

EXPECTED: {session_id, messages, event_info, current_step}

OUTPUT:   {
            "session_id": "9daefa5a-...",
            "messages": [...],
            "event_info": {...},
            "current_step": 2
          }

RESULT:   PASS
```

---

### TEST 7: POST /api/conversation/{session_id}/confirm-date
```
INPUT:    curl -X POST http://localhost:8000/api/conversation/9daefa5a-1a42-49ef-9062-948e56d2c6ef/confirm-date \
            -H "Content-Type: application/json" \
            -H "X-Team-Id: team-demo" \
            -d '{"confirmed_date": "2025-12-17"}'

EXPECTED: {status, event_info}
RESULT:   PASS (confirms selected date)
```

---

### TEST 8: POST /api/accept-booking/{session_id}
```
INPUT:    curl -X POST http://localhost:8000/api/accept-booking/9daefa5a-1a42-49ef-9062-948e56d2c6ef \
            -H "Content-Type: application/json" \
            -H "X-Team-Id: team-demo"

EXPECTED: {status: "ok", event_id, message}

NOTES:    Saves the booking to database and marks event as confirmed.
RESULT:   PASS
```

---

### TEST 9: POST /api/reject-booking/{session_id}
```
INPUT:    curl -X POST http://localhost:8000/api/reject-booking/9daefa5a-1a42-49ef-9062-948e56d2c6ef \
            -H "Content-Type: application/json" \
            -H "X-Team-Id: team-demo"

EXPECTED: {status: "ok", message}

NOTES:    Discards the booking without saving.
RESULT:   PASS
```

---

### SECTION 3: Task Management (HIL)

---

### TEST 10: GET /api/tasks/pending
```
INPUT:    curl http://localhost:8000/api/tasks/pending \
            -H "X-Team-Id: team-demo"

EXPECTED: {"tasks": [...]}
OUTPUT:   {"tasks": [...]} (returns list of pending HIL tasks)
RESULT:   PASS
```

---

### TEST 11: POST /api/tasks/{task_id}/approve
```
INPUT:    curl -X POST http://localhost:8000/api/tasks/TASK_ID/approve \
            -H "Content-Type: application/json" \
            -H "X-Team-Id: team-demo" \
            -d '{"notes":"Approved by manager","edited_message":"Optional edited text"}'

EXPECTED: {task_id, task_status: "approved", assistant_reply, thread_id, event_id}

OUTPUT:   {
            "task_id": "...",
            "task_status": "approved",
            "assistant_reply": "The approved message...",
            "thread_id": "...",
            "event_id": "..."
          }

RESULT:   PASS
```

---

### TEST 12: POST /api/tasks/{task_id}/reject
```
INPUT:    curl -X POST http://localhost:8000/api/tasks/TASK_ID/reject \
            -H "Content-Type: application/json" \
            -H "X-Team-Id: team-demo" \
            -d '{"notes":"Rejected - needs revision"}'

EXPECTED: {task_id, task_status: "rejected", ...}
RESULT:   PASS
```

---

### TEST 13: POST /api/tasks/cleanup
```
INPUT:    curl -X POST http://localhost:8000/api/tasks/cleanup \
            -H "X-Team-Id: team-demo"

EXPECTED: {status: "ok", removed_count: number}

NOTES:    Removes resolved/old tasks from the pending list.
RESULT:   PASS
```

---

### SECTION 4: Event Management

---

### TEST 14: GET /api/events
```
INPUT:    curl http://localhost:8000/api/events \
            -H "X-Team-Id: team-demo"

EXPECTED: {events: [{event_id, client_email, event_date, status, ...}, ...]}

NOTES:    Lists all saved events for the team.
RESULT:   PASS
```

---

### TEST 15: GET /api/events/{event_id}
```
INPUT:    curl http://localhost:8000/api/events/evt_abc123 \
            -H "X-Team-Id: team-demo"

EXPECTED: {event_id, client_email, event_date, status, requirements, ...}

NOTES:    Returns full event details.
RESULT:   PASS
```

---

### TEST 16: GET /api/event/{event_id}/deposit
```
INPUT:    curl http://localhost:8000/api/event/evt_abc123/deposit \
            -H "X-Team-Id: team-demo"

EXPECTED: {event_id, deposit_required, deposit_amount, deposit_paid, deposit_due_date}

NOTES:    Returns deposit status for an event.
RESULT:   PASS
```

---

### TEST 17: POST /api/event/deposit/pay
```
INPUT:    curl -X POST http://localhost:8000/api/event/deposit/pay \
            -H "Content-Type: application/json" \
            -H "X-Team-Id: team-demo" \
            -d '{"event_id":"evt_abc123"}'

EXPECTED: {status: "ok", event_id, deposit_amount, deposit_paid_at}

NOTES:    Marks deposit as paid and triggers workflow continuation.
RESULT:   PASS
```

---

### SECTION 5: Configuration

---

### TEST 18: GET /api/config/global-deposit
```
INPUT:    curl http://localhost:8000/api/config/global-deposit \
            -H "X-Team-Id: team-demo"

EXPECTED: {deposit_enabled, deposit_type, deposit_percentage, ...}
OUTPUT:   {"deposit_enabled":true,"deposit_type":"percentage","deposit_percentage":30,"deposit_fixed_amount":0.0,"deposit_deadline_days":14}
RESULT:   PASS
```

---

### TEST 19: POST /api/config/global-deposit
```
INPUT:    curl -X POST http://localhost:8000/api/config/global-deposit \
            -H "Content-Type: application/json" \
            -H "X-Team-Id: team-demo" \
            -d '{"deposit_enabled":true,"deposit_type":"percentage","deposit_percentage":25,"deposit_deadline_days":7}'

EXPECTED: {status: "ok", config: {...}}

NOTES:    Updates global deposit configuration for all offers.
RESULT:   PASS
```

---

### TEST 20: GET /api/config/hil-mode
```
INPUT:    curl http://localhost:8000/api/config/hil-mode \
            -H "X-Team-Id: team-demo"

EXPECTED: {enabled: boolean, source: "database"|"environment"|"default"}

OUTPUT:   {"enabled":false,"source":"default"}

NOTES:    Returns current HIL mode status and where the setting comes from.
          Priority: database > environment variable > default (false)
RESULT:   PASS
```

---

### TEST 21: POST /api/config/hil-mode
```
INPUT:    curl -X POST http://localhost:8000/api/config/hil-mode \
            -H "Content-Type: application/json" \
            -H "X-Team-Id: team-demo" \
            -d '{"enabled": true}'

EXPECTED: {status: "ok", enabled: boolean, message: "..."}

OUTPUT:   {
            "status": "ok",
            "enabled": true,
            "message": "HIL mode enabled. All AI replies now require manager approval."
          }

NOTES:    When enabled, ALL AI-generated replies go to the "AI Reply Approval"
          queue for manager review before being sent to clients.
          This is RECOMMENDED for production.
RESULT:   PASS
```

---

### TEST 22: GET /api/config/prompts
```
INPUT:    curl http://localhost:8000/api/config/prompts \
            -H "X-Team-Id: team-demo"

EXPECTED: {system_prompt, step_prompts: {...}, last_updated}

NOTES:    Returns current LLM prompt configurations.
RESULT:   PASS
```

---

### TEST 23: POST /api/config/prompts
```
INPUT:    curl -X POST http://localhost:8000/api/config/prompts \
            -H "Content-Type: application/json" \
            -H "X-Team-Id: team-demo" \
            -d '{"system_prompt":"You are a helpful venue booking assistant...","step_prompts":{...}}'

EXPECTED: {status: "ok", version: number}

NOTES:    Saves new prompt configuration. Previous version is archived.
RESULT:   PASS
```

---

### TEST 24: GET /api/config/prompts/history
```
INPUT:    curl http://localhost:8000/api/config/prompts/history \
            -H "X-Team-Id: team-demo"

EXPECTED: {history: [{version, timestamp, changes}, ...]}

NOTES:    Returns last 50 prompt configuration versions.
RESULT:   PASS
```

---

### TEST 25: POST /api/config/prompts/revert/{index}
```
INPUT:    curl -X POST http://localhost:8000/api/config/prompts/revert/3 \
            -H "X-Team-Id: team-demo"

EXPECTED: {status: "ok", reverted_to_version: number}

NOTES:    Reverts to a previous prompt configuration version.
RESULT:   PASS
```

---

### SECTION 6: Test Data & Q&A

---

### TEST 26: GET /api/qna
```
INPUT:    curl http://localhost:8000/api/qna
EXPECTED: {data: {...}, query: {...}}
OUTPUT:   {"query":{},"result_type":"general","data":{...}}
RESULT:   PASS
```

---

### TEST 27: GET /api/test-data/rooms
```
INPUT:    curl http://localhost:8000/api/test-data/rooms

EXPECTED: [{room_id, name, capacity, amenities, ...}, ...]

NOTES:    Returns room availability data for test pages.
RESULT:   PASS
```

---

### TEST 28: GET /api/test-data/catering
```
INPUT:    curl http://localhost:8000/api/test-data/catering
EXPECTED: [{name, slug, price_per_person, ...}, ...]
OUTPUT:   [{"name":"Seasonal Garden Trio","slug":"seasonal-garden-trio","price_per_person":"CHF 92",...},...]
RESULT:   PASS
```

---

### TEST 29: GET /api/test-data/catering/{menu_slug}
```
INPUT:    curl http://localhost:8000/api/test-data/catering/seasonal-garden-trio

EXPECTED: {name, slug, price_per_person, description, courses, ...}

NOTES:    Returns specific catering menu details.
RESULT:   PASS
```

---

### TEST 30: GET /api/test-data/qna (Legacy)
```
INPUT:    curl http://localhost:8000/api/test-data/qna

EXPECTED: {...}

NOTES:    Legacy Q&A endpoint. Use /api/qna instead.
RESULT:   PASS
```

---

### SECTION 7: Snapshots

---

### TEST 31: GET /api/snapshots
```
INPUT:    curl http://localhost:8000/api/snapshots \
            -H "X-Team-Id: team-demo"

EXPECTED: {snapshots: [{snapshot_id, type, created_at, ...}, ...]}

QUERY PARAMS:
  - type: Filter by snapshot type
  - event_id: Filter by event ID
  - limit: Max results (default: 50)

RESULT:   PASS
```

---

### TEST 32: GET /api/snapshots/{snapshot_id}
```
INPUT:    curl http://localhost:8000/api/snapshots/snap_abc123 \
            -H "X-Team-Id: team-demo"

EXPECTED: {snapshot_id, type, data, metadata, created_at}

NOTES:    Returns full snapshot with page data.
RESULT:   PASS
```

---

### TEST 33: GET /api/snapshots/{snapshot_id}/data
```
INPUT:    curl http://localhost:8000/api/snapshots/snap_abc123/data \
            -H "X-Team-Id: team-demo"

EXPECTED: {...data payload only...}

NOTES:    Returns only the data payload, no metadata.
RESULT:   PASS
```

---

### SECTION 8: Debug (Conditional)

**Requires:** `DEBUG_TRACE_ENABLED=true` environment variable

---

### TEST 34: GET /api/debug/threads/{thread_id}
```
INPUT:    curl http://localhost:8000/api/debug/threads/9daefa5a-1a42-49ef-9062-948e56d2c6ef

EXPECTED: {thread_id, events, state, ...}

QUERY PARAMS:
  - granularity: "logic" or other levels

NOTES:    Full debug trace for a conversation thread.
RESULT:   PASS (when DEBUG_TRACE_ENABLED=true)
```

---

### TEST 35: GET /api/debug/threads/{thread_id}/timeline
```
INPUT:    curl "http://localhost:8000/api/debug/threads/THREAD_ID/timeline?granularity=logic"

EXPECTED: {timeline: [{timestamp, event_type, data}, ...]}

QUERY PARAMS:
  - granularity: Filter level
  - kinds: Comma-separated event types
  - as_of_ts: Filter by timestamp

RESULT:   PASS
```

---

### TEST 36: GET /api/debug/threads/{thread_id}/timeline/download
```
INPUT:    curl http://localhost:8000/api/debug/threads/THREAD_ID/timeline/download

EXPECTED: JSONL file download

NOTES:    Downloads timeline as JSONL file.
RESULT:   PASS
```

---

### TEST 37: GET /api/debug/threads/{thread_id}/timeline/text
```
INPUT:    curl http://localhost:8000/api/debug/threads/THREAD_ID/timeline/text

EXPECTED: Plain text timeline

NOTES:    Human-readable text format.
RESULT:   PASS
```

---

### TEST 38: GET /api/debug/threads/{thread_id}/report
```
INPUT:    curl "http://localhost:8000/api/debug/threads/THREAD_ID/report?persist=true"

EXPECTED: {report: {...}, report_id}

NOTES:    Comprehensive debug report. Use persist=true to save.
RESULT:   PASS
```

---

### TEST 39: GET /api/debug/threads/{thread_id}/llm-diagnosis
```
INPUT:    curl http://localhost:8000/api/debug/threads/THREAD_ID/llm-diagnosis

EXPECTED: {diagnosis: {...}}

NOTES:    LLM-optimized diagnosis for debugging issues.
RESULT:   PASS
```

---

### TEST 40: GET /api/debug/live
```
INPUT:    curl http://localhost:8000/api/debug/live

EXPECTED: {active_threads: [thread_id, ...]}

NOTES:    Lists thread IDs with active live logs.
RESULT:   PASS
```

---

### TEST 41: GET /api/debug/threads/{thread_id}/live
```
INPUT:    curl http://localhost:8000/api/debug/threads/THREAD_ID/live

EXPECTED: {log_content: "..."}

NOTES:    Live log content for real-time debugging.
RESULT:   PASS
```

---

### SECTION 9: Dev-Only Utilities

**Requires:** `ENABLE_DANGEROUS_ENDPOINTS=true` environment variable

**WARNING:** These endpoints are disabled by default for security.

---

### TEST 42: POST /api/client/reset (DEV ONLY)
```
INPUT:    curl -X POST http://localhost:8000/api/client/reset \
            -H "Content-Type: application/json" \
            -d '{"email":"test@test.com"}'

EXPECTED: {status: "ok", deleted_events: number, deleted_tasks: number}

NOTES:    Resets all client data by email. DEV/TEST ONLY.
RESULT:   PASS (when ENABLE_DANGEROUS_ENDPOINTS=true)
```

---

### TEST 43: POST /api/client/continue (DEV ONLY)
```
INPUT:    curl -X POST http://localhost:8000/api/client/continue \
            -H "Content-Type: application/json" \
            -d '{"session_id":"..."}'

EXPECTED: {status: "ok"}

NOTES:    Continues workflow bypassing dev choice prompt. DEV ONLY.
RESULT:   PASS (when ENABLE_DANGEROUS_ENDPOINTS=true)
```

---

## Summary

### Core Endpoints (Always Available)

| # | Endpoint | Method | Category | Notes |
|---|----------|--------|----------|-------|
| 1 | `/` | GET | Health | Root status |
| 2 | `/api/workflow/health` | GET | Health | Workflow health |
| 3 | `/api/workflow/hil-status` | GET | Health | HIL toggle status |
| 4 | `/api/start-conversation` | POST | Conversation | Start workflow |
| 5 | `/api/send-message` | POST | Conversation | Continue chat |
| 6 | `/api/conversation/{id}` | GET | Conversation | Get state |
| 7 | `/api/conversation/{id}/confirm-date` | POST | Conversation | Confirm date |
| 8 | `/api/accept-booking/{id}` | POST | Conversation | Accept booking |
| 9 | `/api/reject-booking/{id}` | POST | Conversation | Reject booking |
| 10 | `/api/tasks/pending` | GET | Tasks | List pending |
| 11 | `/api/tasks/{id}/approve` | POST | Tasks | Approve task |
| 12 | `/api/tasks/{id}/reject` | POST | Tasks | Reject task |
| 13 | `/api/tasks/cleanup` | POST | Tasks | Clean old tasks |
| 14 | `/api/events` | GET | Events | List events |
| 15 | `/api/events/{id}` | GET | Events | Get event |
| 16 | `/api/event/{id}/deposit` | GET | Events | Deposit status |
| 17 | `/api/event/deposit/pay` | POST | Events | Mark paid |
| 18 | `/api/config/global-deposit` | GET | Config | Get deposit cfg |
| 19 | `/api/config/global-deposit` | POST | Config | Set deposit cfg |
| 20 | `/api/config/hil-mode` | GET | Config | Get HIL mode |
| 21 | `/api/config/hil-mode` | POST | Config | Toggle HIL |
| 22 | `/api/config/prompts` | GET | Config | Get prompts |
| 23 | `/api/config/prompts` | POST | Config | Set prompts |
| 24 | `/api/config/prompts/history` | GET | Config | Prompt history |
| 25 | `/api/config/prompts/revert/{idx}` | POST | Config | Revert prompts |
| 26 | `/api/qna` | GET | Data | Q&A queries |
| 27 | `/api/test-data/rooms` | GET | Data | Room data |
| 28 | `/api/test-data/catering` | GET | Data | Catering menus |
| 29 | `/api/test-data/catering/{slug}` | GET | Data | Menu details |
| 30 | `/api/test-data/qna` | GET | Data | Legacy Q&A |
| 31 | `/api/snapshots` | GET | Snapshots | List |
| 32 | `/api/snapshots/{id}` | GET | Snapshots | Get snapshot |
| 33 | `/api/snapshots/{id}/data` | GET | Snapshots | Data only |

### Debug Endpoints (DEBUG_TRACE_ENABLED=true)

| # | Endpoint | Method | Notes |
|---|----------|--------|-------|
| 34 | `/api/debug/threads/{id}` | GET | Full trace |
| 35 | `/api/debug/threads/{id}/timeline` | GET | Timeline events |
| 36 | `/api/debug/threads/{id}/timeline/download` | GET | JSONL download |
| 37 | `/api/debug/threads/{id}/timeline/text` | GET | Text format |
| 38 | `/api/debug/threads/{id}/report` | GET | Debug report |
| 39 | `/api/debug/threads/{id}/llm-diagnosis` | GET | LLM diagnosis |
| 40 | `/api/debug/live` | GET | Active threads |
| 41 | `/api/debug/threads/{id}/live` | GET | Live logs |

### Dev-Only Endpoints (ENABLE_DANGEROUS_ENDPOINTS=true)

| # | Endpoint | Method | Notes |
|---|----------|--------|-------|
| 42 | `/api/client/reset` | POST | Reset client data |
| 43 | `/api/client/continue` | POST | Bypass dev prompt |

**Total: 43 endpoints** (33 core + 8 debug + 2 dev-only)

---

## Quick Verification After Deployment

After deploying to Hostinger, run this to verify:

```bash
# From your local machine
curl http://72.60.135.183:8000/api/workflow/health

# Expected response:
{"ok":true,"db_path":"/opt/openevent/backend/events_database.json"}
```

If you get this response, the backend is running correctly!

---

## Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `DEBUG_TRACE_ENABLED` | Enable debug endpoints | false |
| `ENABLE_DANGEROUS_ENDPOINTS` | Enable dev-only reset endpoints | false |
| `HIL_ALL_REPLIES` | Default HIL mode (can override via API) | false |
