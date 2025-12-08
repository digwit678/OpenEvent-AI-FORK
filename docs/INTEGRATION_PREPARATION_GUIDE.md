# OpenEvent.io Integration Preparation Guide

**Last Updated:** 2025-12-07
**Audience:** CO/Manager (Frontend + Supabase via Lovable)
**Purpose:** Prepare for frontend web app and Supabase database integration

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [What's Already Working (Backend)](#2-whats-already-working-backend)
3. [What's New Since Original Plan](#3-whats-new-since-original-plan)
4. [Supabase Schema Requirements](#4-supabase-schema-requirements)
5. [Frontend Requirements](#5-frontend-requirements)
6. [Manager Configuration Data Needed](#6-manager-configuration-data-needed)
7. [Implementation Plan: Deposits (Next Week)](#7-implementation-plan-deposits-next-week)
8. [Open Questions to Decide](#8-open-questions-to-decide)
9. [Quick Reference: TODO Checklist](#9-quick-reference-todo-checklist)

---

## 1. Executive Summary

### Current State
The backend email workflow is **fully functional** for Steps 1-7:
- Email intake with intent classification
- Date confirmation with calendar constraints
- Room availability with ranking
- Offer composition with products
- Negotiation with change detection
- Manager approval (HIL) queue
- Event confirmation

### What This Guide Covers
1. **Supabase schema additions** required for new features
2. **Frontend pages/components** needed for the web app
3. **Configuration data** the manager must provide
4. **Deposit workflow** implementation plan for next week
5. **Clear TODO lists** with priority levels

### Integration Architecture
```
┌─────────────────────────────────────────────────────────────────┐
│                      OpenEvent.io Platform                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   ┌──────────────┐     ┌──────────────┐     ┌──────────────┐   │
│   │   Frontend   │────▶│   Backend    │────▶│   Supabase   │   │
│   │   (Lovable)  │◀────│   (Python)   │◀────│   (Postgres) │   │
│   └──────────────┘     └──────────────┘     └──────────────┘   │
│         │                     │                     │           │
│         ▼                     ▼                     ▼           │
│   ┌──────────────┐     ┌──────────────┐     ┌──────────────┐   │
│   │  Chat UI     │     │  Workflow    │     │  Events      │   │
│   │  Info Pages  │     │  Email Proc. │     │  Rooms       │   │
│   │  Manager     │     │  LLM Calls   │     │  Products    │   │
│   │  Panel       │     │  HIL Queue   │     │  Tasks       │   │
│   └──────────────┘     └──────────────┘     └──────────────┘   │
│                                                                  │
│   ┌──────────────────────────────────────────────────────────┐  │
│   │                    Mail Section                           │  │
│   │   (For platform customers' clients - email workflow)      │  │
│   └──────────────────────────────────────────────────────────┘  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. What's Already Working (Backend)

### Step 1: Intake ✅
- [x] Email parsing (name, email, company, participants, date, room)
- [x] Intent classification (event request vs Q&A vs off-topic)
- [x] German + English keyword detection
- [x] Low-confidence → manager manual review
- [x] Shortcut capture (full info in one message)

### Step 2: Date Confirmation ✅
- [x] Propose up to 5 available dates
- [x] Weekend/weekday preference handling
- [x] Relative date parsing ("next Friday", "first week of February")
- [x] Europe/Zurich timezone
- [x] Confirmation by click or text

### Step 3: Room Availability ✅
- [x] Capacity-based room filtering
- [x] Equipment/feature matching (projector, sound, parking)
- [x] Status display (Available/Option/Unavailable)
- [x] Alternative room suggestions
- [x] Layout compatibility (theatre, u-shape, boardroom, etc.)

### Step 4: Offer ✅
- [x] Line item composition (room + products)
- [x] Per-person and per-event pricing
- [x] Add/remove products by client request
- [x] Total offer price calculation (room items/additions + catering/coffee/food + room price ( + deposit ) )
- [x] Manager approval before sending

### Step 5: Negotiation ✅
- [x] Accept/decline/counter detection
- [x] Structural change routing (date → Step 2, room → Step 3)
- [x] Counter limit (3 rounds failed → manager/HIL escalation)
- [x] Acceptance → Step 6

(
### Step 6: Transition Checkpoint ✅
- [x] Prerequisite validation
- [x] `transition_ready` flag
  )

### Step 7: Confirmation ✅
- [x] Final confirmation messaging
- [x] Status transition (Lead → Option → Confirmed)
- [x] Site visit scheduling (planned)
- [x] Deposit handling (⚠️ needs completion - see Section 7)

### Cross-Cutting Features ✅
- [x] Q&A at any step (parking, catering, features)
- [x] Detour/return pattern with `caller_step`
- [x] Hash-based caching (requirements_hash, room_eval_hash)
- [x] Dual-condition change detection (EN + DE)
- [x] Nonsense/gibberish silent ignore
- [x] LLM verbalization with safety sandwich

---

## 3. What's New Since Original Management Plan

### Executive Summary

**The original management plan was a high-level enterprise architecture document.** It described generic AI platform components (email ingestion, intent classification, workflow engine, HIL approvals) but not the specific booking workflow.

**What the developer built:**
- The specific **7-step booking workflow** (Intake → Date → Room → Offer → Negotiation → Transition → Confirmation)
- The **hash-based caching system** (requirements_hash, room_eval_hash, offer_hash)
- The **caller_step detour pattern** (jump to earlier step, return when done)
- **Snapshot-based persistent links** (old links in chat show historical data)
- **Universal LLM Verbalizer** with safety sandwich fact verification
- **Dual-condition change detection** (revision signal + bound target)
- **Nonsense/gibberish silent ignore** pattern
- **Site visit sub-flow** with change management: Site-visits can be booked now from anywhere in the workflow. 

**Bottom line:** The original plan gave architectural direction. The specific workflow logic and UX features were designed during development. This means more of the integration work is "net-new" than you might expect from the original plan.

---

### How to Read This Section

This section compares the **original "AI-Powered Event Management Platform" management plan** (the PDF you gave to the developer) against **what was actually built**. This helps identify what might need extra attention during integration.

| Symbol | Meaning |
|--------|---------|
| ✅ **IN ORIGINAL PLAN** | Was in the management plan PDF - high-level concept existed |
| 🆕 **DEVELOPED** | Built during development - specific implementation details |
| 🔧 **ENHANCED** | Original concept significantly extended beyond plan |

---

### What Was IN the Original Management Plan

These concepts were in the original PDF. The **high-level architecture** was specified, but the detailed implementation was developed later:

| Concept from Original Plan | Implementation Status | Notes |
|---------------------------|----------------------|-------|
| Email ingestion pipeline | ✅ Implemented | Backend parses incoming emails |
| Intent classification (5+ categories) | ✅ Implemented | event_request, qna, accept, decline, counter, off_topic |
| Entity extraction (NER) | ✅ Implemented | Regex→NER→LLM cascade |
| Workflow orchestration engine | ✅ Implemented | Generic concept → became 7-step workflow |
| Human-in-the-loop (HIL) approval | ✅ Implemented | `tasks` table with approve/reject |
| Task generation & queue | ✅ Implemented | Manager approval queue |
| Auto-approval rules (confidence) | ✅ Implemented | High-confidence messages auto-proceed |
| Confidence scoring (0.0-1.0) | ✅ Implemented | Each classification returns confidence |
| Thread state management | ✅ Implemented | `thread_state` column on events |
| Calendar integration | ✅ Implemented | Availability checking |
| Payment/invoicing integration | 🟡 Partial | Offer line items done, payment pending |
| Multi-model LLM strategy | ✅ Implemented | GPT-4 primary, configurable fallback |
| Database schema (threads, tasks) | ✅ Implemented | `events`, `tasks`, `messages` tables |

**Note:** The original plan described a **generic AI platform architecture**. The specific booking workflow (7 steps, detours, hashes) was **designed during development**.

---

### What Was DEVELOPED Beyond the Original Plan

These are features that were **designed and built during development**. They weren't in the original management plan PDF, so they represent **net-new work** that integration must account for:

---

#### 3.0 The 7-Step Workflow Itself 🆕

**Status:** DEVELOPED (not in original plan)

The original plan described a "workflow orchestration engine" as a generic concept. The **specific 7-step structure** was designed during development:

| Step | Name | Purpose |
|------|------|---------|
| 1 | Intake | Parse email, classify intent, extract entities |
| 2 | Date Confirmation | Propose dates, confirm selection |
| 3 | Room Availability | Check rooms, handle options/conflicts |
| 4 | Offer | Compose line items, get approval |
| 5 | Negotiation | Handle accept/decline/counter |
| 6 | Transition | Prerequisites check |
| 7 | Confirmation | Finalize booking |

**Supabase Required:** `current_step` column (INT, 1-7)

---

#### 3.0.1 Hash-Based Caching System 🆕

**Status:** DEVELOPED

The original plan mentioned "context persistence" generically. The **hash guard system** was designed during development to prevent redundant re-checks:

- `requirements_hash` - SHA256 of (participants, seating, duration, special_requirements)
- `room_eval_hash` - Snapshot of requirements_hash when room was last evaluated
- `offer_hash` - Snapshot of accepted commercial terms

**Why it matters:** If requirements_hash hasn't changed since room_eval_hash was set, skip room re-evaluation.

**Supabase Required:** 3 TEXT columns on events table

---

#### 3.0.2 caller_step Detour Pattern 🆕

**Status:** DEVELOPED

Not in original plan. This enables "detour and return" behavior:

1. Client at Step 4 says "actually, change date to Feb 28"
2. System sets `caller_step = 4`, jumps to Step 2
3. After date confirmed, returns to Step 4

**Supabase Required:** `caller_step` INT column on events

---

#### 3.0.3 Gatekeeping (P1-P4 Prerequisites) 🆕

**Status:** DEVELOPED

Step 4 has explicit prerequisites that must pass before proceeding:
- P1: Date confirmed
- P2: Room locked
- P3: Requirements hash matches room eval hash
- P4: Offer hash valid (if returning from change)

**Supabase Required:** `gatekeeper_passed` JSONB column (optional, for debugging)

---

### What's Actually NEW (Requires Schema/Frontend Extensions)

These features were **added during development** and need additions to your Supabase schema and frontend:

---

### 3.1 Snapshot-Based Info Page Links 🆕

**Added:** 2025-12-02
**NOT in original plan:** Links used to be query-param based (live data)

**What changed:** When chat shows room options, the link captures data at that moment. Old links in the conversation show historical data, not current data.

**Why it matters:** Clients can revisit earlier options in the conversation.

**Supabase Required:** 🔴 NEW TABLE
```sql
CREATE TABLE page_snapshots (
    snapshot_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type TEXT NOT NULL,              -- 'rooms', 'catering', 'qna'
    data JSONB NOT NULL,             -- Full payload captured
    event_id UUID REFERENCES events(event_id),
    params JSONB,                    -- Query params at creation
    created_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP DEFAULT (NOW() + INTERVAL '7 days')
);

CREATE INDEX idx_snapshots_event ON page_snapshots(event_id);
CREATE INDEX idx_snapshots_expires ON page_snapshots(expires_at);
```

**Frontend Required:**
- [ ] `/info/rooms` page that checks for `snapshot_id` query param first
- [ ] `/info/catering` page with menu details and snapshot support
- [ ] `/info/qna` page with FAQ categories
- [ ] API call to `/api/snapshots/{id}` when snapshot_id present

---

### 3.2 Universal LLM Verbalizer with Safety Sandwich 🆕

**Added:** 2025-11-27
**NOT in original plan:** Original plan used deterministic templates only

**What changed:** All client messages go through an LLM that makes them warm and human-like. A "safety sandwich" pattern verifies facts (dates, prices, room names) aren't altered. If verification fails, falls back to deterministic text.

**Why it matters:** Better UX (warm, empathetic tone) without sacrificing accuracy.

**Supabase Required:** 🟡 OPTIONAL (for debugging only)
```sql
CREATE TABLE verbalization_logs (
    log_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID REFERENCES events(event_id),
    step INT,
    topic TEXT,
    original_text TEXT,
    verbalized_text TEXT,
    facts_verified BOOLEAN,
    patched BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);
```

**Frontend Required:**
- [ ] Messages should render markdown formatting
- [ ] No other changes needed

**Config:**
- `VERBALIZER_TONE=empathetic` (default) or `plain` (for testing)

---

### 3.3 Enhanced Dual-Condition Change Detection 🆕

**Added:** 2025-12-02
**Enhancement of:** Original detour detection

**What changed:** Detects changes only when BOTH:
1. A revision signal ("change", "actually", "instead", German: "ändern", "stattdessen")
2. A specific target ("date", "room", "participants")

Also adds disambiguation when target is ambiguous (e.g., "change to February 14" - event date or site visit date?).

**Why it matters:** Prevents false positives where Q&A ("what rooms are available?") was mistaken for change requests.

**Supabase Required:** 🟢 NONE (logic only)

**Frontend Required:**
- [ ] Disambiguation UI when target is ambiguous
- [ ] Show: "Did you mean the event date or the site visit date?"
- [ ] Two buttons to clarify

---

### 3.4 Nonsense/Off-Topic Silent Ignore 🆕

**Added:** 2025-12-03
**NOT in original plan:** No handling for gibberish

**What changed:** Two-layer detection:
1. Regex gate catches gibberish ("asdfghjkl") immediately - no LLM call
2. Low-confidence messages without workflow signals are silently ignored

**Decision Matrix:**
| Confidence | Workflow Signal | Action |
|------------|-----------------|--------|
| Any        | YES             | Proceed normally |
| < 15%      | NO              | IGNORE (silent, no reply) |
| 15-25%     | NO              | Defer to HIL |
| >= 25%     | NO              | Proceed |

**Why it matters:** Saves LLM costs, doesn't confuse clients with error messages.

**Supabase Required:** 🟡 OPTIONAL (for analytics)
```sql
ALTER TABLE messages ADD COLUMN IF NOT EXISTS ignored BOOLEAN DEFAULT FALSE;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS ignore_reason TEXT;
```

**Frontend Required:**
- [ ] Optional: subtle indicator for ignored messages (or just hide them)

---

### 3.5 Cross-Step Date Change Detours 🔧

**Added:** 2025-12-03
**Enhancement of:** Original detour system

**What changed:** Originally, date changes were only handled when explicitly at Step 2. Now, date change requests from Steps 3, 4, or 5 are detected and routed back to Step 2, then return to the caller step.

**Example:** Client is at Step 4 (offer shown), says "sorry, I meant February 28 instead" → system detours to Step 2, confirms new date, returns to Step 4.

**Supabase Required:** 🟢 ALREADY IN PLAN
```sql
-- Just ensure this column exists (should already be there):
ALTER TABLE events ADD COLUMN IF NOT EXISTS caller_step INT;
```

**Frontend Required:**
- [ ] Progress indicator should show "detour" state when `caller_step` is set
- [ ] Visual: "Returning to confirm your date change..."

---

### 3.6 Site Visit Change Management 🔧

**Added:** 2025-12-02
**Enhancement of:** Original site visit concept

**What changed:** Original plan had basic site visit branching. Now includes:
- Change detection for "reschedule site visit", "cancel site visit"
- Date/room dependency validation
- Change history tracking
- Fallback suggestions when requested change is invalid

**Supabase Required:** 🔴 NEW TABLE
```sql
CREATE TABLE site_visits (
    visit_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID REFERENCES events(event_id),
    status TEXT DEFAULT 'idle',      -- idle, proposed, scheduled, completed, cancelled
    requested_room TEXT,
    requested_date DATE,
    confirmed_room TEXT,
    confirmed_date DATE,
    confirmed_time TIME,
    calendar_event_id TEXT,
    return_to_step INT,
    change_history JSONB DEFAULT '[]',  -- 🆕 Track changes
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_site_visits_event ON site_visits(event_id);
CREATE INDEX idx_site_visits_status ON site_visits(status);
```

**Frontend Required:**
- [ ] `/info/site-visits` page with available time slots
- [ ] Site visit status in event info panel
- [ ] Confirmation/reschedule UI in chat

---

### 3.7 Dynamic Content Abbreviation 🆕

**Added:** 2025-12-02
**NOT in original plan:** No content length handling

**What changed:** When catering/menu descriptions exceed 400 characters, the chat shows abbreviated version with a "View full menu" link. Full data available on info page.

**Why it matters:** Keeps chat readable while preserving access to full information.

**Supabase Required:** 🟢 NONE (logic only)

**Frontend Required:**
- [ ] Info pages must show full data when linked
- [ ] Links use snapshot_id for consistency

---

### 3.8 Manager Approval Queue Improvements 🔧

**Added:** Throughout development
**Enhancement of:** Original HIL task structure

**What changed:** Tasks now have structured payloads with event summary, and the manager can approve/reject with notes. Approval/rejection is tracked.

**Supabase Required:** 🟡 ADD COLUMNS
```sql
-- Ensure tasks table has these columns:
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS payload JSONB;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMP;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS resolved_by TEXT;
```

**Frontend Required:**
- [ ] Tasks panel with approve/reject buttons
- [ ] Task detail view showing event summary, offer line items
- [ ] Notes input field for manager decision

---

### 3.9 Client Reset Endpoint 🆕 (Development Only)

**Added:** 2025-12-03
**Purpose:** Testing/development only

**What it is:** Button to clear all data for a client's email (for re-running test scenarios).

**API:** `POST /api/client/reset` with `email` parameter

**Frontend Required:**
- [ ] "Reset Client" button in Tasks panel (already implemented)
- [ ] Confirmation dialog before deleting

**Note:** This is for development/testing only, not for production.

---

## 4. Supabase Schema Requirements

### Quick Reference: What Needs to Change

| Change Type | Table | Action |
|-------------|-------|--------|
| 🟢 Check Exists | `events` | Verify columns from original plan |
| 🟢 Check Exists | `clients`, `rooms`, `products`, `offers`, `tasks` | Verify structure |
| 🔴 **NEW TABLE** | `page_snapshots` | Create for snapshot links |
| 🔴 **NEW TABLE** | `site_visits` | Create for venue tours |
| 🔴 **NEW TABLE** | `deposits` | Create for deposit tracking |
| 🟡 Add Columns | `rooms` | `deposit_required`, `deposit_percent` |
| 🟡 Add Columns | `offers` | `deposit_amount`, `deposit_status`, `deposit_paid_at` |
| 🟡 Add Columns | `tasks` | `payload`, `resolved_at`, `resolved_by` |
| 🟡 Optional | `messages` | `ignored`, `ignore_reason` |
| 🟡 Optional | `verbalization_logs` | For debugging LLM rewrites |

---

### 4.1 Core Tables (Likely Already Exist - Verify)

#### `events`
| Column | Type | Required | Notes |
|--------|------|----------|-------|
| event_id | UUID | PK | Auto-generated |
| created_at | TIMESTAMP | Yes | |
| status | TEXT | Yes | Lead, Option, Confirmed, Cancelled |
| current_step | INT | Yes | 1-7 |
| caller_step | INT | No | 🆕 For detour tracking |
| thread_state | TEXT | No | Awaiting Client, Waiting on HIL, In Progress |
| chosen_date | DATE | No | |
| date_confirmed | BOOLEAN | Yes | Default false |
| locked_room_id | TEXT | No | FK to rooms |
| requirements_hash | TEXT | No | 🆕 For caching |
| room_eval_hash | TEXT | No | 🆕 For caching |
| offer_id | UUID | No | FK to offers |
| offer_hash | TEXT | No | 🆕 For caching |
| transition_ready | BOOLEAN | Yes | Default false |
| decision | TEXT | No | pending, confirmed, declined |
| calendar_event_id | TEXT | No | External calendar |

#### `event_requirements`
| Column | Type | Required | Notes |
|--------|------|----------|-------|
| event_id | UUID | FK | |
| number_of_participants | INT | No | |
| seating_layout | TEXT | No | theatre, u_shape, boardroom, etc. |
| start_time | TIME | No | |
| end_time | TIME | No | |
| special_requirements | TEXT | No | |
| preferred_room | TEXT | No | |

#### `clients`
| Column | Type | Required | Notes |
|--------|------|----------|-------|
| client_id | TEXT | PK | Lowercased email |
| name | TEXT | No | |
| organization | TEXT | No | |
| phone | TEXT | No | |
| created_at | TIMESTAMP | Yes | |

#### `rooms` (Reference Data)
| Column | Type | Required | Notes |
|--------|------|----------|-------|
| room_id | TEXT | PK | e.g., "atelier-room-a" |
| name | TEXT | Yes | Display name |
| capacity_max | INT | Yes | |
| capacity_min | INT | No | |
| base_price | DECIMAL | No | |
| features | JSONB | No | ["stage", "screen", "parking"] |
| equipment | JSONB | No | ["projector", "flip_chart"] |
| layouts | JSONB | No | {"theatre": 100, "u_shape": 40} |
| deposit_required | BOOLEAN | No | 🆕 |
| deposit_percent | INT | No | 🆕 e.g., 30 = 30% |
| deposit_flat | DECIMAL | No | 🆕 Alternative: flat amount |

#### `products` (Reference Data)
| Column | Type | Required | Notes |
|--------|------|----------|-------|
| product_id | TEXT | PK | |
| name | TEXT | Yes | |
| category | TEXT | No | catering, equipment, service |
| unit | TEXT | No | per_person, per_event, pieces |
| base_price | DECIMAL | Yes | |
| description | TEXT | No | |
| dietary_options | JSONB | No | ["vegetarian", "vegan"] |

#### `offers`
| Column | Type | Required | Notes |
|--------|------|----------|-------|
| offer_id | UUID | PK | |
| event_id | UUID | FK | |
| created_at | TIMESTAMP | Yes | |
| status | TEXT | Yes | Lead, Option, Confirmed |
| total_amount | DECIMAL | No | |
| deposit_amount | DECIMAL | No | 🆕 Calculated from room policy |
| deposit_paid | BOOLEAN | No | 🆕 |
| deposit_paid_at | TIMESTAMP | No | 🆕 |
| sequence | INT | Yes | Version number |
| accepted_at | TIMESTAMP | No | |

#### `offer_line_items`
| Column | Type | Required | Notes |
|--------|------|----------|-------|
| line_item_id | UUID | PK | |
| offer_id | UUID | FK | |
| product_id | TEXT | No | FK, null for room |
| name | TEXT | Yes | |
| quantity | INT | Yes | |
| unit | TEXT | No | per_person, per_event |
| unit_price | DECIMAL | Yes | |
| total_price | DECIMAL | Yes | |

#### `tasks` (HIL Queue)
| Column | Type | Required | Notes |
|--------|------|----------|-------|
| task_id | UUID | PK | |
| created_at | TIMESTAMP | Yes | |
| type | TEXT | Yes | manual_review, date_confirmation, etc. |
| status | TEXT | Yes | pending, approved, rejected, done |
| client_id | TEXT | No | |
| event_id | UUID | No | FK |
| payload | JSONB | No | 🆕 Event summary, line items |
| notes | TEXT | No | Manager decision notes |
| resolved_at | TIMESTAMP | No | 🆕 |
| resolved_by | TEXT | No | 🆕 Manager ID |

### 4.2 New Tables Required

```sql
-- Page Snapshots (for persistent info links)
CREATE TABLE page_snapshots (
    snapshot_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type TEXT NOT NULL,
    data JSONB NOT NULL,
    event_id UUID REFERENCES events(event_id),
    params JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP DEFAULT (NOW() + INTERVAL '7 days')
);

-- Site Visits
CREATE TABLE site_visits (
    visit_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID REFERENCES events(event_id),
    status TEXT DEFAULT 'idle',
    requested_room TEXT,
    requested_date DATE,
    confirmed_room TEXT,
    confirmed_date DATE,
    confirmed_time TIME,
    calendar_event_id TEXT,
    return_to_step INT,
    change_history JSONB DEFAULT '[]',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Messages (conversation history)
CREATE TABLE messages (
    message_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID REFERENCES events(event_id),
    client_id TEXT,
    role TEXT NOT NULL,  -- 'user' or 'assistant'
    content TEXT NOT NULL,
    timestamp TIMESTAMP DEFAULT NOW(),
    intent TEXT,
    confidence DECIMAL,
    ignored BOOLEAN DEFAULT FALSE,
    ignore_reason TEXT
);

-- Audit Log
CREATE TABLE audit_log (
    audit_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID REFERENCES events(event_id),
    timestamp TIMESTAMP DEFAULT NOW(),
    actor TEXT NOT NULL,  -- 'system', 'user', 'manager'
    from_step INT,
    to_step INT,
    reason TEXT,
    fields_changed JSONB
);

-- Deposits (tracking)
CREATE TABLE deposits (
    deposit_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID REFERENCES events(event_id),
    offer_id UUID REFERENCES offers(offer_id),
    amount DECIMAL NOT NULL,
    status TEXT DEFAULT 'pending',  -- pending, paid, refunded
    due_date DATE,
    paid_at TIMESTAMP,
    payment_reference TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

## 5. Frontend Requirements

### 5.1 Main Chat Interface

**Page:** `/` or `/chat`

**Components Needed:**
- [ ] Message list with user/assistant bubbles
- [ ] Markdown rendering for assistant messages
- [ ] Action buttons (Confirm Date, Select Room, etc.)
- [ ] Typing indicator
- [ ] Message input with Enter to send
- [ ] Link handling (open info pages in new tab)

**API Integration:**
- `POST /api/send-message` - Send user message
- `GET /api/messages/{event_id}` - Get conversation history
- WebSocket (optional) for real-time updates

---

### 5.2 Manager Panel

**Page:** `/manager` or `/tasks`

**Components Needed:**
- [ ] Task list with filtering (pending, resolved)
- [ ] Task card showing:
  - Client name, email
  - Event summary (date, room, participants)
  - Offer line items (if applicable)
  - Task type badge
- [ ] Approve / Reject buttons
- [ ] Notes input field
- [ ] "Reset Client" button (for testing)

**API Integration:**
- `GET /api/tasks` - List pending tasks
- `POST /api/tasks/{task_id}/approve` - Approve task
- `POST /api/tasks/{task_id}/reject` - Reject task

---

### 5.3 Info Pages

**Page:** `/info/rooms`
- [ ] Room table with columns: Name, Capacity, Status, Features, Price
- [ ] Status badges (Available = green, Option = yellow, Unavailable = red)
- [ ] Room details expandable section
- [ ] Fetch by `snapshot_id` if present, else by query params

**Page:** `/info/catering`
- [ ] Menu list with prices
- [ ] Menu detail pages (courses, dietary info)
- [ ] Filter by dietary options

**Page:** `/info/qna`
- [ ] Category sidebar (Parking, Catering, Booking, etc.)
- [ ] Q&A cards with question/answer
- [ ] Related links section

**Page:** `/info/site-visits`
- [ ] Available time slots calendar/list
- [ ] Room selection (if multiple)
- [ ] Booking policy info

---

### 5.4 Event Progress Indicator

**Component:** Progress bar or stepper

**States to show:**
1. Intake (completed when event created)
2. Date Confirmation (completed when date_confirmed = true)
3. Room Selection (completed when locked_room_id set)
4. Offer (completed when offer_id set)
5. Negotiation (current when at Step 5)
6. Transition (current when at Step 6)
7. Confirmation (completed when status = Confirmed)

**Special states:**
- [ ] "Detour" indicator when `caller_step` is set
- [ ] "Waiting on Manager" when there's a pending task
- [ ] "Deposit Required" when deposit is pending

---

### 5.5 Event Info Panel

**Component:** Sidebar or expandable section

**Fields to display:**
- Client name, email, company
- Event date (or "Not confirmed")
- Time window
- Number of participants
- Room (or "Not selected")
- Special requirements
- Billing address
- Total amount (if offer exists)
- Deposit status (🆕)
- Site visit status (🆕)

---

## 6. Manager Configuration Data Needed

### 6.1 Room Reference Data

**Format:** JSON or Supabase table

**Example:**
```json
{
  "room_id": "atelier-room-a",
  "name": "Room A",
  "capacity_max": 100,
  "capacity_min": 20,
  "base_price": 1500.00,
  "features": ["stage", "natural_light", "terrace_access"],
  "equipment": ["projector", "screen", "sound_system", "2x flip_charts"],
  "layouts": {
    "theatre": 100,
    "u_shape": 40,
    "boardroom": 30,
    "banquet": 60,
    "classroom": 50
  },
  "deposit_required": true,
  "deposit_percent": 30
}
```

**TODO for Manager:**
- [ ] List all rooms with capacities
- [ ] Define equipment for each room
- [ ] Define layout capacities for each room
- [ ] Set base prices
- [ ] Define deposit policy per room (see Section 7)

---

### 6.2 Product/Catering Catalog

**Format:** JSON or Supabase table

**Example:**
```json
{
  "product_id": "seasonal-garden-trio",
  "name": "Seasonal Garden Trio",
  "category": "catering",
  "unit": "per_person",
  "base_price": 92.00,
  "description": "Three-course vegetarian menu with seasonal ingredients",
  "dietary_options": ["vegetarian", "can_be_vegan"]
}
```

**TODO for Manager:**
- [ ] List all catering packages with prices
- [ ] List beverages with pricing (per person / per bottle)
- [ ] List equipment rentals (microphone, flip chart, etc.)
- [ ] Define which products are available in which rooms

---

### 6.3 Business Rules

**TODO for Manager:**
- [ ] Define blackout dates (holidays, closures)
- [ ] Define buffer times between events (default: 30 min before, 30 min after)
- [ ] Define option hold duration (default: 7 days)
- [ ] Define maximum date changes allowed (default: unlimited)
- [ ] Define maximum negotiation rounds (default: 3)
- [ ] Define business hours for site visits
- [ ] Define timezone (default: Europe/Zurich)

---

### 6.4 Message Templates

**TODO for Manager (can refine later):**
- [ ] Review and approve date confirmation messages (EN + DE)
- [ ] Review and approve room availability messages (EN + DE)
- [ ] Review and approve offer messages (EN + DE)
- [ ] Review and approve confirmation messages (EN + DE)
- [ ] Define email subject lines
- [ ] Define signature/footer

---

## 7. Implementation Plan: Deposits (Next Week)

### 7.1 Overview

**Goal:** Client cannot complete booking without paying deposit. Once paid, room status changes to "Confirmed" and is reserved.

**Configuration Options:**
- **Per-room deposit:** Each room can have its own deposit policy
- **Global deposit:** One policy for all rooms (simpler)
- **Recommendation:** Start with per-room (more flexible for premium rooms)

### 7.2 Deposit Configuration (Manager Task)

**Option A: Per-Room Deposit**
```
Room A: 30% deposit required
Room B: 20% deposit required
Room C: No deposit (smaller room)
```

**Option B: Global Deposit**
```
All rooms: 30% deposit required for events over CHF 5,000
```

**Decision Needed:** Which approach? (Per-room recommended)

### 7.3 Supabase Schema for Deposits

```sql
-- Add deposit columns to rooms table
ALTER TABLE rooms ADD COLUMN deposit_required BOOLEAN DEFAULT FALSE;
ALTER TABLE rooms ADD COLUMN deposit_percent INT;  -- e.g., 30 = 30%
ALTER TABLE rooms ADD COLUMN deposit_flat DECIMAL;  -- alternative: flat amount

-- Add deposit columns to offers table
ALTER TABLE offers ADD COLUMN deposit_amount DECIMAL;
ALTER TABLE offers ADD COLUMN deposit_status TEXT DEFAULT 'not_required';
  -- Values: not_required, pending, paid, refunded
ALTER TABLE offers ADD COLUMN deposit_paid_at TIMESTAMP;
ALTER TABLE offers ADD COLUMN deposit_due_date DATE;

-- Create deposits table for tracking
CREATE TABLE deposits (
    deposit_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID REFERENCES events(event_id),
    offer_id UUID REFERENCES offers(offer_id),
    amount DECIMAL NOT NULL,
    status TEXT DEFAULT 'pending',
    due_date DATE,
    paid_at TIMESTAMP,
    payment_reference TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### 7.4 Backend Changes Needed

**File:** `backend/workflows/groups/event_confirmation/trigger/process.py`

1. Check if room requires deposit
2. Calculate deposit amount from offer total
3. Add deposit to offer line items (or separate line)
4. Block confirmation until deposit marked as paid
5. When paid, update event status to Confirmed

**Flow:**
```
Client accepts offer
    ↓
Check room.deposit_required
    ↓
If deposit required:
    ├── Calculate deposit amount
    ├── Add deposit line item to offer
    ├── Send deposit payment instructions
    ├── Wait for payment confirmation
    ├── (Manager marks deposit as paid)
    ├── Update offer.deposit_status = 'paid'
    └── Event status → Confirmed
Else:
    └── Event status → Confirmed directly
```

### 7.5 Frontend Changes Needed

**Manager Panel:**
- [ ] "Mark Deposit Paid" button on pending deposits
- [ ] Payment reference input field
- [ ] Deposit status badge on event cards

**Client Chat:**
- [ ] Deposit payment instructions message
- [ ] "Your deposit of CHF X is pending" status
- [ ] "Deposit received, your booking is confirmed!" message

**Info/Offer Display:**
- [ ] Deposit line item showing amount due
- [ ] Payment deadline
- [ ] Payment instructions (bank details, etc.)

### 7.6 Implementation TODO (Next Week)

**Day 1-2: Supabase Schema**
- [ ] Add deposit columns to rooms table
- [ ] Add deposit columns to offers table
- [ ] Create deposits table
- [ ] Populate test rooms with deposit policies

**Day 3: Backend Logic**
- [ ] Calculate deposit in offer composition
- [ ] Add deposit to offer line items
- [ ] Block confirmation until deposit paid
- [ ] Add "mark deposit paid" endpoint

**Day 4: Frontend**
- [ ] Add deposit display to offer view
- [ ] Add "Mark Deposit Paid" button in manager panel
- [ ] Add deposit status badges

**Day 5: Testing**
- [ ] Test offer with deposit required
- [ ] Test deposit payment flow
- [ ] Test confirmation after payment
- [ ] Test room without deposit

---

## 8. Open Questions to Decide

### Urgent (Before Integration)

1. **Deposit policy type?**
   - Per-room (each room has its own %) ← Recommended
   - Global (one policy for all)

2. **Deposit percentage?**
   - 30% is typical
   - Or flat amount per room?

3. **Deposit due date?**
   - X days after offer acceptance?
   - Fixed date before event?

4. **Payment method?**
   - Bank transfer (most common for B2B)
   - Online payment integration (Stripe)?
   - Manual confirmation by manager?

5. **Refund policy?**
   - When is deposit refundable?
   - Who processes refunds?

### Important (Can Decide Later)

6. **Maximum date changes?**
   - Currently unlimited
   - Should there be a limit?

7. **Option hold duration?**
   - Currently not enforced
   - Auto-release after X days?

8. **Site visit scheduling?**
   - Which days/times available?
   - Who conducts the visit?

9. **Multi-language**
   - Currently EN + DE
   - Need French? Italian?

10. **Email vs Chat**
    - When client starts via email, continues via chat?
    - Unified thread history?

---

## 9. Quick Reference: TODO Checklist

### How to Use This Checklist

| Symbol | Meaning |
|--------|---------|
| 🟢 | Should already exist if you followed V4 spec - just verify |
| 🔴 | NEW - must be created |
| 🟡 | May need adding/updating |

---

### Priority 1: Core Schema (Create or Verify)

Some of these are from the original plan (generic concepts), others are new (developed during implementation). Create/verify all:

#### Events Table
- [ ] `event_id` (UUID, PK) - ✅ IN PLAN
- [ ] `current_step` (INT, 1-7) - 🆕 DEVELOPED (7-step workflow)
- [ ] `caller_step` (INT, nullable) - 🆕 DEVELOPED (detour pattern)
- [ ] `status` (TEXT: Lead/Option/Confirmed/Cancelled) - ✅ IN PLAN
- [ ] `chosen_date`, `date_confirmed` - 🆕 DEVELOPED
- [ ] `locked_room_id` - 🆕 DEVELOPED
- [ ] `requirements_hash`, `room_eval_hash`, `offer_hash` - 🆕 DEVELOPED (hash caching)
- [ ] `captured`, `verified` (JSONB) - 🆕 DEVELOPED (shortcut capture)
- [ ] `gatekeeper_passed` (JSONB) - 🆕 DEVELOPED (optional, debugging)
- [ ] `thread_state` (TEXT) - ✅ IN PLAN

#### Other Core Tables
- [ ] `clients` table with email as key - ✅ IN PLAN (generic concept)
- [ ] `rooms` table with capacity, features, layouts - 🆕 DEVELOPED (specific schema)
- [ ] `products` table with category, unit, price - 🆕 DEVELOPED (specific schema)
- [ ] `offers` table with event_id FK - ✅ IN PLAN (generic concept)
- [ ] `offer_line_items` table - 🆕 DEVELOPED
- [ ] `tasks` table for HIL queue - ✅ IN PLAN (task system)

---

### Priority 2: Create NEW Tables & Columns (This Week)

These are NEW and must be created:

#### 🔴 NEW: `page_snapshots` table
```sql
CREATE TABLE page_snapshots (
    snapshot_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type TEXT NOT NULL,
    data JSONB NOT NULL,
    event_id UUID REFERENCES events(event_id),
    params JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP DEFAULT (NOW() + INTERVAL '7 days')
);
```

#### 🔴 NEW: `site_visits` table
```sql
CREATE TABLE site_visits (
    visit_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID REFERENCES events(event_id),
    status TEXT DEFAULT 'idle',
    requested_room TEXT,
    requested_date DATE,
    confirmed_room TEXT,
    confirmed_date DATE,
    confirmed_time TIME,
    calendar_event_id TEXT,
    return_to_step INT,
    change_history JSONB DEFAULT '[]',
    created_at TIMESTAMP DEFAULT NOW()
);
```

#### 🔴 NEW: `deposits` table
```sql
CREATE TABLE deposits (
    deposit_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID REFERENCES events(event_id),
    offer_id UUID REFERENCES offers(offer_id),
    amount DECIMAL NOT NULL,
    status TEXT DEFAULT 'pending',
    due_date DATE,
    paid_at TIMESTAMP,
    payment_reference TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
```

#### 🟡 ADD COLUMNS to existing tables
```sql
-- Rooms table: add deposit policy
ALTER TABLE rooms ADD COLUMN deposit_required BOOLEAN DEFAULT FALSE;
ALTER TABLE rooms ADD COLUMN deposit_percent INT;

-- Offers table: add deposit tracking
ALTER TABLE offers ADD COLUMN deposit_amount DECIMAL;
ALTER TABLE offers ADD COLUMN deposit_status TEXT DEFAULT 'not_required';
ALTER TABLE offers ADD COLUMN deposit_paid_at TIMESTAMP;

-- Tasks table: add payload and resolution tracking
ALTER TABLE tasks ADD COLUMN payload JSONB;
ALTER TABLE tasks ADD COLUMN resolved_at TIMESTAMP;
ALTER TABLE tasks ADD COLUMN resolved_by TEXT;
```

---

### Priority 3: Manager Configuration

#### Room Data (enter into Supabase or provide JSON)
- [ ] List all rooms with: name, capacity_min, capacity_max
- [ ] Define features per room (stage, screen, parking, etc.)
- [ ] Define equipment per room (projector, flip chart, etc.)
- [ ] Define layout capacities (theatre: 100, u_shape: 40, etc.)
- [ ] Set base prices per room
- [ ] **NEW:** Set deposit policy per room (required? what %?)

#### Product Data (enter into Supabase or provide JSON)
- [ ] List all catering packages with prices (per person)
- [ ] List beverages with prices
- [ ] List equipment rentals with prices
- [ ] Define which products available in which rooms

#### Business Rules (decide and document)
- [ ] Deposit policy: per-room or global?
- [ ] Deposit percentage (e.g., 30%)
- [ ] Deposit due date rule (e.g., 7 days after acceptance)
- [ ] Option hold duration (e.g., 7 days)
- [ ] Max negotiation rounds (default: 3)
- [ ] Blackout dates (holidays)
- [ ] Buffer times between events

---

### Priority 4: Frontend Development

#### Core Chat Interface
- [ ] Message list with user/assistant bubbles
- [ ] Markdown rendering for messages
- [ ] Action buttons in messages (Confirm Date, Select Room)
- [ ] Message input with Enter to send
- [ ] Link handling (open in new tab)

#### Manager Panel
- [ ] Task list (pending tasks)
- [ ] Task detail view (event summary, offer items)
- [ ] Approve / Reject buttons
- [ ] Notes input field
- [ ] **NEW:** "Mark Deposit Paid" button

#### Progress & Status
- [ ] Step progress indicator (Steps 1-7)
- [ ] Detour indication (when `caller_step` is set)
- [ ] Deposit status display
- [ ] Site visit status display

#### Info Pages
- [ ] `/info/rooms` - room availability (with snapshot support)
- [ ] `/info/catering` - menu details
- [ ] `/info/qna` - FAQ categories
- [ ] `/info/site-visits` - available slots

---

### Priority 5: Deposit Implementation (Next Week)

Backend (developer task):
- [ ] Calculate deposit from room policy
- [ ] Add deposit line to offer
- [ ] Block confirmation until deposit paid
- [ ] Add `/api/deposits/{id}/mark-paid` endpoint

Frontend:
- [ ] Show deposit amount in offer
- [ ] Show "Pending Deposit" status
- [ ] "Mark Deposit Paid" button for manager
- [ ] "Deposit Received" confirmation message

---

### Priority 6: Mail Section Integration (For OpenEvent.io)

The Mail Section of OpenEvent.io platform will run this workflow for your customers' clients:

- [ ] Email webhook endpoint to receive incoming emails
- [ ] Email parsing to extract sender, subject, body
- [ ] Thread tracking by email address
- [ ] Outbound email sending (after HIL approval)
- [ ] Email templates per step (EN + DE)

**Note:** The backend workflow is the same - the Mail Section just provides the email transport layer.

---

### Priority 7: Later Enhancements

- [ ] Real-time updates (WebSocket)
- [ ] Calendar sync (Google Calendar)
- [ ] Analytics dashboard
- [ ] Mobile responsiveness
- [ ] French/Italian language support

---

## Appendix: API Endpoints Reference

### Existing Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/start-conversation` | Start new conversation |
| POST | `/api/send-message` | Send message to workflow |
| GET | `/api/tasks` | List pending HIL tasks |
| POST | `/api/tasks/{id}/approve` | Approve task |
| POST | `/api/tasks/{id}/reject` | Reject task |
| GET | `/api/test-data/rooms` | Room availability data |
| GET | `/api/test-data/catering` | Catering catalog |
| GET | `/api/test-data/qna` | Q&A data |
| GET | `/api/snapshots/{id}` | Get snapshot by ID |
| POST | `/api/client/reset` | Reset client data (testing) |

### Endpoints Needed for Deposits

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/deposits/{id}/mark-paid` | Mark deposit as paid |
| GET | `/api/deposits/pending` | List pending deposits |
| GET | `/api/events/{id}/deposit-status` | Get deposit status for event |

---

*This guide will be updated as integration progresses.*
