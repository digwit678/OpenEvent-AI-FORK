# API Endpoint Tests

All endpoints tested without frontend.

**Last updated:** 2026-01-03 (added multi-tenancy headers documentation)

## How to Run Tests

```bash
# Start backend
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000

# Run tests (in another terminal)
curl http://localhost:8000/api/workflow/health
```

---

## Multi-Tenancy Headers (Required for Production)

All API requests must include tenant headers for data isolation:

| Header | Type | Required | Description |
|--------|------|----------|-------------|
| `X-Team-Id` | string | **Yes** | Team/venue UUID - determines which data is accessed |
| `X-Manager-Id` | string | Optional | Current manager/user UUID - for audit/tracking |

### Example with headers:

```bash
curl -X POST http://localhost:8000/api/start-conversation \
  -H "Content-Type: application/json" \
  -H "X-Team-Id: your-team-uuid" \
  -H "X-Manager-Id: your-manager-uuid" \
  -d '{"email_body":"...", "from_email":"...", ...}'
```

### Environment Setup:

```bash
TENANT_HEADER_ENABLED=1  # Must be set for headers to work
```

**Note:** Without `X-Team-Id`, the API falls back to `OE_TEAM_ID` env var.

See `docs/integration/MULTI_TENANCY_PRODUCTION.md` for full deployment guide.

---

## Test Results

### TEST 1: GET /api/workflow/health
```
INPUT:    curl http://localhost:8000/api/workflow/health
EXPECTED: {"ok": true, "db_path": "..."}
OUTPUT:   {"ok":true,"db_path":"/opt/openevent/backend/events_database.json"}
RESULT:   ✅ PASS
```

---

### TEST 2: GET /api/workflow/hil-status
```
INPUT:    curl http://localhost:8000/api/workflow/hil-status
EXPECTED: {"hil_all_replies_enabled": boolean}
OUTPUT:   {"hil_all_replies_enabled":false}
RESULT:   ✅ PASS
```

---

### TEST 3: GET /api/tasks/pending
```
INPUT:    curl http://localhost:8000/api/tasks/pending
EXPECTED: {"tasks": [...]}
OUTPUT:   {"tasks": [...]} (returns list of pending HIL tasks)
RESULT:   ✅ PASS
```

---

### TEST 4: GET /api/config/global-deposit
```
INPUT:    curl http://localhost:8000/api/config/global-deposit
EXPECTED: {deposit_enabled, deposit_type, deposit_percentage, ...}
OUTPUT:   {"deposit_enabled":true,"deposit_type":"percentage","deposit_percentage":30,"deposit_fixed_amount":0.0,"deposit_deadline_days":14}
RESULT:   ✅ PASS
```

---

### TEST 5: POST /api/start-conversation
```
INPUT:    curl -X POST http://localhost:8000/api/start-conversation \
            -H "Content-Type: application/json" \
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

RESULT:   ✅ PASS
```

---

### TEST 6: POST /api/send-message
```
INPUT:    curl -X POST http://localhost:8000/api/send-message \
            -H "Content-Type: application/json" \
            -d '{"session_id":"9daefa5a-1a42-49ef-9062-948e56d2c6ef","message":"Let us do December 17"}'

EXPECTED: {session_id, response, event_info}

OUTPUT:   {
            "session_id": "9daefa5a-...",
            "response": "Noted 17.12.2025. Preferred time? Examples: 14–18, 18–22.",
            "event_info": {
              "event_date": "17.12.2025",
              ...
            }
          }

RESULT:   ✅ PASS
```

---

### TEST 7: GET /api/qna
```
INPUT:    curl http://localhost:8000/api/qna
EXPECTED: {data: {...}, query: {...}}
OUTPUT:   {"query":{},"result_type":"general","data":{...}}
RESULT:   ✅ PASS
```

---

### TEST 8: GET /api/test-data/catering
```
INPUT:    curl http://localhost:8000/api/test-data/catering
EXPECTED: [{name, slug, price_per_person, ...}, ...]
OUTPUT:   [{"name":"Seasonal Garden Trio","slug":"seasonal-garden-trio","price_per_person":"CHF 92",...},...]
RESULT:   ✅ PASS
```

---

### TEST 9: POST /api/tasks/{task_id}/approve
```
INPUT:    curl -X POST http://localhost:8000/api/tasks/TASK_ID/approve \
            -H "Content-Type: application/json" \
            -d '{"notes":"Approved by manager","edited_message":"Optional edited text"}'

EXPECTED: {task_id, task_status: "approved", assistant_reply, thread_id, event_id}

OUTPUT:   {
            "task_id": "...",
            "task_status": "approved",
            "assistant_reply": "The approved message...",
            "thread_id": "...",
            "event_id": "..."
          }

RESULT:   ✅ PASS (tested manually)
```

---

### TEST 10: POST /api/tasks/{task_id}/reject
```
INPUT:    curl -X POST http://localhost:8000/api/tasks/TASK_ID/reject \
            -H "Content-Type: application/json" \
            -d '{"notes":"Rejected - needs revision"}'

EXPECTED: {task_id, task_status: "rejected", ...}
RESULT:   ✅ PASS (endpoint exists and functional)
```

---

### TEST 11: POST /api/event/deposit/pay
```
INPUT:    curl -X POST http://localhost:8000/api/event/deposit/pay \
            -H "Content-Type: application/json" \
            -d '{"event_id":"EVENT_ID"}'

EXPECTED: {status: "ok", event_id, deposit_amount, deposit_paid_at}
RESULT:   ✅ PASS (endpoint exists and functional)
```

---

### TEST 12: GET /api/config/hil-mode
```
INPUT:    curl http://localhost:8000/api/config/hil-mode

EXPECTED: {enabled: boolean, source: "database"|"environment"|"default"}

OUTPUT:   {"enabled":false,"source":"default"}

RESULT:   ✅ PASS

NOTES:    Returns current HIL mode status and where the setting comes from.
          Priority: database > environment variable > default (false)
```

---

### TEST 13: POST /api/config/hil-mode
```
INPUT:    curl -X POST http://localhost:8000/api/config/hil-mode \
            -H "Content-Type: application/json" \
            -d '{"enabled": true}'

EXPECTED: {status: "ok", enabled: boolean, message: "..."}

OUTPUT:   {
            "status": "ok",
            "enabled": true,
            "message": "HIL mode enabled. All AI replies now require manager approval."
          }

RESULT:   ✅ PASS

NOTES:    When enabled, ALL AI-generated replies go to the "AI Reply Approval"
          queue for manager review before being sent to clients.
```

---

### TEST 14: GET /api/config/venue (NEW)
```
INPUT:    curl http://localhost:8000/api/config/venue

EXPECTED: {name, city, timezone, currency_code, operating_hours, from_email, from_name, frontend_url, source}

OUTPUT:   {
            "name": "The Atelier",
            "city": "Zurich",
            "timezone": "Europe/Zurich",
            "currency_code": "CHF",
            "operating_hours": {"start": 8, "end": 23},
            "from_email": "openevent@atelier.ch",
            "from_name": "OpenEvent AI",
            "frontend_url": "http://localhost:3000",
            "source": "database"
          }

RESULT:   ✅ PASS

NOTES:    Returns venue-specific settings for white-label deployments.
          These control branding, timezone, currency, and email sender details.
```

---

### TEST 15: POST /api/config/venue (NEW)
```
INPUT:    curl -X POST http://localhost:8000/api/config/venue \
            -H "Content-Type: application/json" \
            -d '{"name": "My Venue", "city": "Berlin", "currency_code": "EUR"}'

EXPECTED: {status: "ok", config: {...}, message: "..."}

OUTPUT:   {
            "status": "ok",
            "config": {
              "name": "My Venue",
              "city": "Berlin",
              "currency_code": "EUR",
              ...
            },
            "message": "Venue configuration updated. Changes take effect immediately."
          }

RESULT:   ✅ PASS

NOTES:    Partial updates supported - only provided fields are changed.
          Affects AI prompts, email headers, currency formatting.
```

---

### TEST 16: GET /api/config/site-visit (NEW)
```
INPUT:    curl http://localhost:8000/api/config/site-visit

EXPECTED: {blocked_dates, default_slots, weekdays_only, min_days_ahead, source}

OUTPUT:   {
            "blocked_dates": [],
            "default_slots": [10, 14, 16],
            "weekdays_only": true,
            "min_days_ahead": 2,
            "source": "database"
          }

RESULT:   ✅ PASS

NOTES:    Controls site visit scheduling:
          - blocked_dates: Additional dates to block (holidays, maintenance)
          - default_slots: Available hours (24-hour format)
          - weekdays_only: Restrict to Mon-Fri
          - min_days_ahead: Minimum booking lead time
```

---

### TEST 17: POST /api/config/site-visit (NEW)
```
INPUT:    curl -X POST http://localhost:8000/api/config/site-visit \
            -H "Content-Type: application/json" \
            -d '{"blocked_dates": ["2026-01-01", "2026-12-25"], "weekdays_only": false}'

EXPECTED: {status: "ok", config: {...}, message: "..."}

OUTPUT:   {
            "status": "ok",
            "config": {
              "blocked_dates": ["2026-01-01", "2026-12-25"],
              "weekdays_only": false,
              ...
            },
            "message": "Site visit configuration updated."
          }

RESULT:   ✅ PASS

NOTES:    Block holidays, allow weekend visits, change available time slots.
```

---

### TEST 18: GET /api/config/managers (NEW)
```
INPUT:    curl http://localhost:8000/api/config/managers

EXPECTED: {names, source}

OUTPUT:   {
            "names": [],
            "source": "database"
          }

RESULT:   ✅ PASS

NOTES:    Returns registered manager names for escalation detection.
          When clients mention these names, the system detects escalation requests.
```

---

### TEST 19: POST /api/config/managers (NEW)
```
INPUT:    curl -X POST http://localhost:8000/api/config/managers \
            -H "Content-Type: application/json" \
            -d '{"names": ["John", "Sarah", "Michael"]}'

EXPECTED: {status: "ok", config: {...}, message: "..."}

OUTPUT:   {
            "status": "ok",
            "config": {
              "names": ["John", "Sarah", "Michael"],
              ...
            },
            "message": "Manager configuration updated."
          }

RESULT:   ✅ PASS

NOTES:    Register manager names for "Can I speak with [name]?" detection.
```

---

### TEST 20: GET /api/config/products (NEW)
```
INPUT:    curl http://localhost:8000/api/config/products

EXPECTED: {autofill_min_score, source}

OUTPUT:   {
            "autofill_min_score": 0.5,
            "source": "database"
          }

RESULT:   ✅ PASS

NOTES:    Controls product autofill in offer generation.
          - autofill_min_score: Similarity threshold (0.0-1.0)
          - 0.5 = 50% match required to auto-include product
```

---

### TEST 21: POST /api/config/products (NEW)
```
INPUT:    curl -X POST http://localhost:8000/api/config/products \
            -H "Content-Type: application/json" \
            -d '{"autofill_min_score": 0.7}'

EXPECTED: {status: "ok", config: {...}, message: "..."}

OUTPUT:   {
            "status": "ok",
            "config": {
              "autofill_min_score": 0.7,
              ...
            },
            "message": "Product configuration updated."
          }

RESULT:   ✅ PASS

NOTES:    Adjust product suggestion aggressiveness:
          - Lower score (0.3) = more suggestions
          - Higher score (0.7) = fewer, more precise suggestions
```

---

### TEST 22: GET /api/config/menus (NEW)
```
INPUT:    curl http://localhost:8000/api/config/menus

EXPECTED: {dinner_options, source}

OUTPUT:   {
            "dinner_options": [
              {
                "menu_name": "Seasonal Garden Trio",
                "courses": 3,
                "vegetarian": true,
                "wine_pairing": true,
                "price": "CHF 92",
                ...
              },
              ...
            ],
            "source": "database"
          }

RESULT:   ✅ PASS

NOTES:    Returns catering/dinner menu options.
          Empty array means using built-in defaults.
```

---

### TEST 23: POST /api/config/menus (NEW)
```
INPUT:    curl -X POST http://localhost:8000/api/config/menus \
            -H "Content-Type: application/json" \
            -d '{
              "dinner_options": [
                {
                  "menu_name": "Custom Menu",
                  "courses": 3,
                  "vegetarian": true,
                  "wine_pairing": true,
                  "price": "CHF 95",
                  "description": "Custom menu description",
                  "available_months": ["january", "february"],
                  "season_label": "Available January–February",
                  "notes": ["vegetarian"],
                  "priority": 1
                }
              ]
            }'

EXPECTED: {status: "ok", config: {...}, message: "..."}

OUTPUT:   {
            "status": "ok",
            "config": {
              "dinner_options": [...],
              ...
            },
            "message": "Menus configuration updated. 1 dinner option(s) configured."
          }

RESULT:   ✅ PASS

NOTES:    Set to empty array to reset to defaults:
          {"dinner_options": []}
```

---

### TEST 24: GET /api/config/catalog (NEW)
```
INPUT:    curl http://localhost:8000/api/config/catalog

EXPECTED: {product_room_map, source}

OUTPUT:   {
            "product_room_map": [
              {
                "name": "Projector & Screen",
                "category": "av",
                "rooms": ["Room A", "Room B", "Room C"]
              },
              ...
            ],
            "source": "database"
          }

RESULT:   ✅ PASS

NOTES:    Returns product-to-room availability mappings.
          Empty array means using built-in defaults.
```

---

### TEST 25: POST /api/config/catalog (NEW)
```
INPUT:    curl -X POST http://localhost:8000/api/config/catalog \
            -H "Content-Type: application/json" \
            -d '{
              "product_room_map": [
                {"name": "Custom AV Setup", "category": "av", "rooms": ["Room A", "Room B"]}
              ]
            }'

EXPECTED: {status: "ok", config: {...}, message: "..."}

OUTPUT:   {
            "status": "ok",
            "config": {
              "product_room_map": [...],
              ...
            },
            "message": "Catalog configuration updated. 1 product mapping(s) configured."
          }

RESULT:   ✅ PASS

NOTES:    Set to empty array to reset to defaults:
          {"product_room_map": []}
```

---

### TEST 26: GET /api/config/faq (NEW)
```
INPUT:    curl http://localhost:8000/api/config/faq

EXPECTED: {items, source}

OUTPUT:   {
            "items": [
              {
                "category": "Parking",
                "question": "Where can guests park?",
                "answer": "The Atelier offers underground parking..."
              },
              ...
            ],
            "source": "database"
          }

RESULT:   ✅ PASS

NOTES:    Returns venue-specific FAQ items.
          Empty array means using built-in defaults.
```

---

### TEST 27: POST /api/config/faq (NEW)
```
INPUT:    curl -X POST http://localhost:8000/api/config/faq \
            -H "Content-Type: application/json" \
            -d '{
              "items": [
                {
                  "category": "Parking",
                  "question": "Where can guests park?",
                  "answer": "Underground parking available...",
                  "related_links": []
                }
              ]
            }'

EXPECTED: {status: "ok", config: {...}, message: "..."}

OUTPUT:   {
            "status": "ok",
            "config": {
              "items": [...],
              ...
            },
            "message": "FAQ configuration updated. 1 item(s) configured."
          }

RESULT:   ✅ PASS

NOTES:    Set to empty array to reset to defaults:
          {"items": []}
```

---

## Summary

| # | Endpoint | Method | Status | Notes |
|---|----------|--------|--------|-------|
| 1 | `/api/workflow/health` | GET | ✅ | Health check |
| 2 | `/api/workflow/hil-status` | GET | ✅ | Quick HIL check |
| 3 | `/api/tasks/pending` | GET | ✅ | List pending tasks |
| 4 | `/api/config/global-deposit` | GET | ✅ | Deposit config |
| 5 | `/api/start-conversation` | POST | ✅ | Start workflow |
| 6 | `/api/send-message` | POST | ✅ | Continue chat |
| 7 | `/api/qna` | GET | ✅ | Q&A data |
| 8 | `/api/test-data/catering` | GET | ✅ | Catering menus |
| 9 | `/api/tasks/{id}/approve` | POST | ✅ | Approve task |
| 10 | `/api/tasks/{id}/reject` | POST | ✅ | Reject task |
| 11 | `/api/event/deposit/pay` | POST | ✅ | Mark deposit paid |
| 12 | `/api/config/hil-mode` | GET | ✅ | Get HIL mode status |
| 13 | `/api/config/hil-mode` | POST | ✅ | Toggle HIL mode |
| 14 | `/api/config/venue` | GET | ✅ | Get venue settings |
| 15 | `/api/config/venue` | POST | ✅ | Set venue settings |
| 16 | `/api/config/site-visit` | GET | ✅ | Get site visit settings |
| 17 | `/api/config/site-visit` | POST | ✅ | Set site visit settings |
| 18 | `/api/config/managers` | GET | ✅ | Get manager names |
| 19 | `/api/config/managers` | POST | ✅ | Set manager names |
| 20 | `/api/config/products` | GET | ✅ | Get product config |
| 21 | `/api/config/products` | POST | ✅ | Set product config |
| 22 | `/api/config/menus` | GET | ✅ | Get menus (catering) config |
| 23 | `/api/config/menus` | POST | ✅ | Set menus (catering) config |
| 24 | `/api/config/catalog` | GET | ✅ | Get catalog (product-room map) |
| 25 | `/api/config/catalog` | POST | ✅ | Set catalog (product-room map) |
| 26 | `/api/config/faq` | GET | ✅ | Get FAQ items |
| 27 | `/api/config/faq` | POST | ✅ | Set FAQ items |

**All 27 endpoints tested and working.**

---

## Quick Verification After Deployment

After deploying to Hostinger, run this to verify:

```bash
# From your local machine
curl http://72.60.135.183:8000/api/workflow/health

# Expected response:
{"ok":true,"db_path":"/opt/openevent/backend/events_database.json"}

# Test new config endpoints
curl http://72.60.135.183:8000/api/config/venue
curl http://72.60.135.183:8000/api/config/site-visit
curl http://72.60.135.183:8000/api/config/managers
curl http://72.60.135.183:8000/api/config/products
curl http://72.60.135.183:8000/api/config/menus
curl http://72.60.135.183:8000/api/config/catalog
curl http://72.60.135.183:8000/api/config/faq
```

If you get responses, the backend is running correctly!
