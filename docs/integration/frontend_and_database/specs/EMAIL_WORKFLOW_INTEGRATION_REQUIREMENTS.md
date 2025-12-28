# Email Workflow Integration Requirements

**Generated:** 2025-12-08
**Purpose:** Technical specification for email workflow code changes to integrate with main OpenEvent project

---

## Executive Summary

This document identifies what needs to change **in the email workflow code** for integration with the main OpenEvent project.

**Key Findings:**
1. The main project is **multi-tenant** (team-based) - all operations need `team_id`
2. The deposit system **already exists** on offers - just need room-level config
3. Use existing `emails` table for conversation history (not new messages table)
4. All IDs are **UUIDs** (not string slugs)

---

# CRITICAL MVP REQUIREMENT: Human-in-the-Loop (HIL) for Every Message

**This is non-negotiable for MVP:**

> **Every AI-generated message MUST be approved by an Event Manager before being sent to a client.**

## What This Means

1. **No Auto-Send**: The AI never sends emails directly to clients. Every draft goes to an approval queue.

2. **Event Manager Approval**: Before any AI-generated message reaches a client, an Event Manager (e.g., Shami) must:
   - Review the message
   - Approve it as-is, OR
   - Edit it before approving, OR
   - Reject it entirely

3. **Implementation**: When the workflow generates a client-facing message:
   ```python
   # Create HIL task for every outgoing message
   task = {
       "title": f"Approve message to {client_name}",
       "category": "Email Tasks",  # or "Event Tasks" - see Decision 2
       "team_id": team_id,
       "user_id": system_user_id,
       "event_id": event_id,
       "client_name": client_name,
       "priority": "high",
       "description": "Review and approve AI-generated message before sending to client.",
       "payload": {
           "action": "approve_message",
           "draft_message": draft_text,
           "recipient_email": client_email
       }
   }
   supabase.from_("tasks").insert(task).execute()

   # Message is NOT sent until Event Manager approves via frontend
   ```

4. **Why This Matters**:
   - Prevents AI errors from reaching clients
   - Maintains professional quality
   - Allows Event Manager to add personal touches
   - Builds trust in the system gradually

## Later (Post-MVP)

After the system proves reliable, you may consider:
- Auto-approval for certain message types (e.g., simple acknowledgments)
- Tiered approval (junior staff drafts, senior approves)
- AI confidence thresholds for auto-send

But for MVP: **Every message gets human approval. No exceptions.**

---

# PART A: WORKFLOW CODE CHANGES

These are changes in the email workflow code - **no Supabase changes required**.

---

## A1. Column Name Mappings

| Workflow Uses | Change To | Table | Notes |
|---------------|-----------|-------|-------|
| `organization` | `company` | clients | Different column name |
| `chosen_date` | `event_date` | events | Different column name |
| `number_of_participants` | `attendees` | events | Different column name |
| `capacity_max` | `capacity` | rooms | Different column name |
| Task `type` | Task `category` | tasks | Different column name |
| `resolved_at` | `completed_at` | tasks | Different column name |
| `deposit_paid` (boolean) | `deposit_paid_at` (timestamp) | offers | Check `is not null` |
| `deposit_status` | `payment_status` | offers | Different column name |
| `accepted_at` | `confirmed_at` | offers | Different column name |

---

## A2. ID Format Changes (UUID instead of string)

| Workflow Uses | Change To | Notes |
|---------------|-----------|-------|
| `client_id` = email string | UUID | Lookup client by email, use returned UUID |
| `room_id` = "room-a" string | UUID | Use actual room UUID from database |
| `product_id` = "menu-1" string | UUID | Use actual product UUID from database |

**Example - Client lookup:**
```python
# BEFORE: Using email as client_id
client_id = email.lower()

# AFTER: Lookup by email, use UUID
result = supabase.from_("clients") \
    .select("id") \
    .eq("email", email.lower()) \
    .eq("team_id", team_id) \
    .maybe_single() \
    .execute()

if result.data:
    client_id = result.data["id"]  # UUID
else:
    # Create new client
    new_client = supabase.from_("clients").insert({
        "name": extracted_name,
        "email": email.lower(),
        "company": extracted_company,
        "team_id": team_id,
        "user_id": system_user_id,
        "status": "lead"
    }).execute()
    client_id = new_client.data[0]["id"]
```

---

## A3. Array Format Changes

| Workflow Uses | Change To | Notes |
|---------------|-----------|-------|
| `locked_room_id` (single string) | `room_ids` (string array) | Use `[room_id]` format |
| `features` (JSONB object) | `amenities` (string array) | Flat array of strings |
| `equipment` (JSONB object) | `amenities` (string array) | Merged into same array |

**Example:**
```python
# BEFORE
event["locked_room_id"] = "uuid-here"

# AFTER
event["room_ids"] = ["uuid-here"]
```

**Example - Room features:**
```python
# BEFORE (workflow internal)
room = {
    "features": {"stage": True, "parking": True},
    "equipment": {"projector": True, "flip_chart": 2}
}

# AFTER (main project format)
room = {
    "amenities": ["stage", "parking", "projector", "flip_chart"]
}

# When checking for features:
has_stage = "stage" in room["amenities"]
```

---

## A4. Required Fields for Record Creation

When creating records, these fields are **required** by the main project.

### Clients
```python
{
    "name": str,           # REQUIRED - client name
    "team_id": uuid,       # REQUIRED - from config
    "user_id": uuid,       # REQUIRED - system user ID
    # Optional fields:
    "email": str,
    "phone": str,
    "company": str,
    "status": str,         # default: "lead"
}
```

### Events
```python
{
    "title": str,          # REQUIRED - generate: f"Event booking - {client_name}"
    "event_date": str,     # REQUIRED - format: "2025-02-15"
    "start_time": str,     # REQUIRED - format: "09:00:00"
    "end_time": str,       # REQUIRED - format: "17:00:00"
    "team_id": uuid,       # REQUIRED
    "user_id": uuid,       # REQUIRED
    # Optional fields:
    "status": str,         # default: "lead"
    "attendees": int,
    "room_ids": list[uuid],
    "notes": str,
    "description": str,
}
```

### Offers
```python
{
    "offer_number": str,   # REQUIRED - generate unique (see A5)
    "subject": str,        # REQUIRED - e.g., f"Event Offer - {event_title}"
    "offer_date": str,     # REQUIRED - today's date
    "user_id": uuid,       # REQUIRED
    "event_id": uuid,      # Link to event
    # Deposit fields (from room config):
    "deposit_enabled": bool,
    "deposit_type": str,   # "percentage" or "fixed"
    "deposit_percentage": float,
    "deposit_amount": float,
    "deposit_deadline_days": int,
}
```

### Offer Line Items
```python
{
    "offer_id": uuid,      # REQUIRED - FK to offers
    "name": str,           # REQUIRED - product/room name
    "quantity": int,       # REQUIRED
    "unit_price": float,   # REQUIRED
    "total": float,        # REQUIRED - quantity * unit_price
    # Optional fields:
    "description": str,
    "product_id": uuid,    # FK to products (null for room line)
}
```

### Tasks (for HIL approvals)
```python
{
    "title": str,          # REQUIRED - e.g., "Approve offer for John Smith"
    "category": str,       # REQUIRED - "Event Tasks" or "Email Tasks" (see Decision 2)
    "team_id": uuid,       # REQUIRED
    "user_id": uuid,       # REQUIRED
    # Optional fields:
    "description": str,
    "priority": str,       # "low", "medium", "high"
    "due_date": str,
    "event_id": uuid,
    "client_name": str,
}
```

### Emails (conversation history)
```python
{
    "from_email": str,     # REQUIRED
    "to_email": str,       # REQUIRED
    "subject": str,        # REQUIRED
    "body_text": str,      # REQUIRED
    "team_id": uuid,       # REQUIRED
    "user_id": uuid,       # REQUIRED
    # Optional fields:
    "body_html": str,
    "event_id": uuid,
    "client_id": uuid,
    "is_sent": bool,       # True = outgoing, False = incoming
    "received_at": str,
    "thread_id": str,
}
```

---

## A5. Offer Number Generation

The main project expects unique offer numbers. Generate using:

```python
import datetime
import uuid

def generate_offer_number(team_prefix: str = "OE") -> str:
    """Generate unique offer number: OE-2025-12-XXXX"""
    now = datetime.datetime.now()
    short_id = str(uuid.uuid4())[:4].upper()
    return f"{team_prefix}-{now.year}-{now.month:02d}-{short_id}"

# Example output: "OE-2025-12-A3F7"
```

---

## A6. Room Capacity Mapping

Main project uses layout-specific capacity columns (not JSONB):

| Workflow Uses | Main Project Column |
|---------------|---------------------|
| `layouts["theatre"]` | `theater_capacity` |
| `layouts["cocktail"]` | `cocktail_capacity` |
| `layouts["dinner"]` | `seated_dinner_capacity` |
| `layouts["standing"]` | `standing_capacity` |
| Default max | `capacity` |

**Example - Room capacity check:**
```python
def get_room_capacity(room: dict, layout: str = None) -> int:
    """Get room capacity for a specific layout or default."""
    if layout:
        layout_columns = {
            "theatre": "theater_capacity",
            "theater": "theater_capacity",
            "cocktail": "cocktail_capacity",
            "dinner": "seated_dinner_capacity",
            "seated": "seated_dinner_capacity",
            "standing": "standing_capacity",
        }
        col = layout_columns.get(layout.lower())
        if col and room.get(col):
            return room[col]

    # Fall back to general capacity
    return room.get("capacity", 0)
```

---

## A7. Product Category Handling

Main project uses `category_id` (UUID FK) instead of category string.

**Option 1: Lookup category by name**
```python
# Get category UUID
category = supabase.from_("product_categories") \
    .select("id") \
    .eq("name", "Catering") \
    .eq("team_id", team_id) \
    .maybe_single() \
    .execute()

category_id = category.data["id"] if category.data else None
```

**Option 2: Filter products directly by name pattern**
```python
# Skip category lookup, just get products
products = supabase.from_("products") \
    .select("*") \
    .eq("team_id", team_id) \
    .eq("available", True) \
    .execute()

# Filter in code if needed
catering_products = [p for p in products.data if "menu" in p["name"].lower()]
```

---

## A8. Status Values (Capitalization)

**Important:** Status values may have different capitalization:

| Workflow Uses | Main Project Uses | Notes |
|---------------|-------------------|-------|
| `Lead` | `lead` | Lowercase in Supabase enum |
| `Option` | `option` | Lowercase |
| `Confirmed` | `confirmed` | Lowercase |
| `Cancelled` | `cancelled` | Lowercase |

**Ensure lowercase when writing to Supabase:**
```python
status = event_status.lower()  # "Lead" -> "lead"
```

---

## A9. Timezone Handling

The workflow uses `Europe/Zurich`. The main project may store timestamps in UTC.

**When reading dates:**
```python
from datetime import datetime
import pytz

zurich_tz = pytz.timezone("Europe/Zurich")

# Convert UTC from database to Zurich for display
utc_time = datetime.fromisoformat(db_timestamp.replace("Z", "+00:00"))
zurich_time = utc_time.astimezone(zurich_tz)
```

**When writing dates:**
```python
# Store dates as date strings (no timezone), times as local
event_date = "2025-02-15"  # Date only, no TZ
start_time = "09:00:00"    # Time only, assumed local
```

**For timestamps (created_at, etc.):**
```python
# Supabase handles this automatically with DEFAULT NOW()
# No conversion needed for audit fields
```

---

# PART B: SUPABASE CHANGES REQUIRED

These columns/tables **must** be added to Supabase.

---

## B1. Add to `rooms` Table (MVP)

| Column | Type | Purpose |
|--------|------|---------|
| `deposit_required` | BOOLEAN | Whether room requires deposit |
| `deposit_percent` | INT | Deposit percentage (e.g., 30 for 30%) |

```sql
ALTER TABLE rooms ADD COLUMN deposit_required BOOLEAN DEFAULT FALSE;
ALTER TABLE rooms ADD COLUMN deposit_percent INT;
```

---

## B2. Add to `events` Table (If Using Option A for State Storage)

| Column | Type | Purpose | MVP? |
|--------|------|---------|------|
| `current_step` | INT | Workflow step 1-7 | Yes |
| `date_confirmed` | BOOLEAN | Is date locked | Yes |
| `caller_step` | INT | For detour tracking | Yes |
| `requirements_hash` | TEXT | Caching | Optional |
| `room_eval_hash` | TEXT | Caching | Optional |
| `offer_hash` | TEXT | Caching | Optional |

```sql
ALTER TABLE events ADD COLUMN current_step INT DEFAULT 1;
ALTER TABLE events ADD COLUMN date_confirmed BOOLEAN DEFAULT FALSE;
ALTER TABLE events ADD COLUMN caller_step INT;
-- Optional:
ALTER TABLE events ADD COLUMN requirements_hash TEXT;
ALTER TABLE events ADD COLUMN room_eval_hash TEXT;
ALTER TABLE events ADD COLUMN offer_hash TEXT;
```

---

## B3. Add to `events` Table (LATER)

| Column | Type | Purpose |
|--------|------|---------|
| `seating_layout` | TEXT | Theatre, U-shape, etc. |
| `preferred_room` | TEXT | Client's room preference |

```sql
ALTER TABLE events ADD COLUMN seating_layout TEXT;
ALTER TABLE events ADD COLUMN preferred_room TEXT;
```

---

## B4. New Tables (LATER)

### `site_visits` (for venue tours)
```sql
CREATE TABLE site_visits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID REFERENCES events(id),
    team_id UUID REFERENCES teams(id),
    user_id UUID NOT NULL,
    status TEXT DEFAULT 'idle',  -- idle, proposed, scheduled, completed, cancelled
    requested_date DATE,
    confirmed_date DATE,
    confirmed_time TIME,
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_site_visits_event ON site_visits(event_id);
CREATE INDEX idx_site_visits_team ON site_visits(team_id);
```

### `page_snapshots` (for info page links)
```sql
CREATE TABLE page_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type TEXT NOT NULL,  -- 'rooms', 'qa', 'offer', 'availability'
    data JSONB NOT NULL,
    event_id UUID REFERENCES events(id),
    team_id UUID REFERENCES teams(id),
    created_at TIMESTAMP DEFAULT NOW()
    -- NOTE: No expires_at - links are permanent
);

CREATE INDEX idx_snapshots_event ON page_snapshots(event_id);
CREATE INDEX idx_snapshots_team ON page_snapshots(team_id);
```

### `client_preference_history` (for personalization)
```sql
CREATE TABLE client_preference_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id UUID REFERENCES clients(id),
    team_id UUID REFERENCES teams(id),
    extracted_at TIMESTAMP DEFAULT NOW(),
    preferences JSONB NOT NULL,
    source_email_id UUID REFERENCES emails(id),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_client_prefs ON client_preference_history(client_id, extracted_at DESC);
```

---

# PART C: EXISTING FEATURES (No Changes Needed)

## C1. Deposit System Already Exists

The `offers` table already has all deposit fields:

| Column | Type | Use |
|--------|------|-----|
| `deposit_enabled` | boolean | Whether deposit required |
| `deposit_type` | string | "percentage" or "fixed" |
| `deposit_percentage` | number | e.g., 30 for 30% |
| `deposit_fixed_amount` | number | Fixed CHF amount |
| `deposit_amount` | number | Calculated deposit |
| `deposit_paid_at` | timestamp | When paid (null = unpaid) |
| `deposit_deadline_days` | number | Days until due |

**No need to create a deposits table!**

## C2. Use `emails` Table for Conversation History

Main project has an `emails` table with:
- `event_id`, `client_id` (can link to workflow)
- `body_text`, `body_html`
- `is_sent` (true = outgoing, false = incoming)
- `from_email`, `to_email`
- `thread_id` (for native email threading)

**Use this instead of creating a separate `messages` table.**

---

# PART D: CONFIGURATION

## D1. Required Configuration Values

| Config Key | Value Type | Purpose |
|------------|------------|---------|
| `TEAM_ID` | UUID | Which team's data to access |
| `SYSTEM_USER_ID` | UUID | Identity for DB writes |
| `EMAIL_ACCOUNT_ID` | UUID | Email account for sending |

## D2. Example Configuration

```python
# config.py
SUPABASE_CONFIG = {
    "team_id": "your-team-uuid-here",
    "system_user_id": "your-system-user-uuid-here",
    "email_account_id": "your-email-account-uuid-here",
}

# Usage in workflow
from config import SUPABASE_CONFIG

event = {
    "title": f"Event booking - {client_name}",
    "event_date": chosen_date,
    "team_id": SUPABASE_CONFIG["team_id"],
    "user_id": SUPABASE_CONFIG["system_user_id"],
    # ...
}
```

---

# PART E: CHECKLIST

## Critical MVP Requirements
- [ ] **HIL for every message**: All AI drafts create approval tasks before sending
- [ ] No auto-send to clients - every message requires Event Manager approval

## Workflow Code Changes (Do First)
- [ ] Column renames applied (organization→company, etc.)
- [ ] Using UUIDs for all IDs (not string slugs)
- [ ] Using `room_ids` array (not `locked_room_id` string)
- [ ] Using `amenities` array (not features/equipment JSONB)
- [ ] Adding `team_id` to all operations
- [ ] Adding `user_id` to all operations
- [ ] Generating `title` for events
- [ ] Generating `offer_number` for offers
- [ ] Providing `start_time`/`end_time` for events
- [ ] Using lowercase status values
- [ ] Checking `deposit_paid_at is not null` (not boolean)
- [ ] Layout capacity column mapping

## Supabase Additions (Manager Does)
- [ ] `deposit_required` on rooms
- [ ] `deposit_percent` on rooms
- [ ] Workflow state columns on events (if Option A)
- [ ] Site visits table (LATER)
- [ ] Page snapshots table (LATER)

## Configuration
- [ ] `team_id` documented
- [ ] `system_user_id` documented
- [ ] `email_account_id` documented

---

*Document version: 2.1 | Last updated: 2025-12-09*