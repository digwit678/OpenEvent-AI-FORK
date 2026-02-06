# Activity Log - Frontend Specification

> **Purpose:** Help managers see how AI-generated messages were created (transparency).

---

# PART 1: WHAT TO BUILD

---

## Component 1: Progress Bar

A **5-step progress indicator** showing where the booking is in the workflow.

### API Call
```
GET /api/events/{event_id}/progress
```

### What You Receive
```json
{
  "current_stage": "room",
  "percentage": 40,
  "stages": [
    {"id": "date", "label": "Date", "status": "completed", "icon": "📅"},
    {"id": "room", "label": "Room", "status": "active", "icon": "🏢"},
    {"id": "offer", "label": "Offer", "status": "pending", "icon": "📄"},
    {"id": "deposit", "label": "Deposit", "status": "pending", "icon": "💳"},
    {"id": "confirmed", "label": "Confirmed", "status": "pending", "icon": "✅"}
  ]
}
```

### Visual Design

```
         40% Complete
   ━━━━━━━━━━━━━━━░░░░░░░░░░░░░░░

   📅 ────── 🏢 ────── 📄 ────── 💳 ────── ✅
   ✓         ●         ○         ○         ○
  Date      Room     Offer    Deposit  Confirmed
```

### Stage Status Colors
| Status | Meaning | Color |
|--------|---------|-------|
| `completed` | Done | Green |
| `active` | Current step | Blue |
| `pending` | Not started | Gray |

---

## Component 2: Activity Timeline

A **scrollable list** of activities showing what happened and when.

### API Call
```
GET /api/events/{event_id}/activity?granularity=high&limit=50
```

### What You Receive
```json
{
  "activities": [
    {
      "id": "act_1706450000123",
      "timestamp": "2025-01-28T10:30:00",
      "icon": "📅",
      "title": "Date Confirmed",
      "detail": "March 15, 2025",
      "granularity": "high"
    },
    {
      "id": "act_1706449900456",
      "timestamp": "2025-01-28T10:28:00",
      "icon": "✅",
      "title": "Manager Approved",
      "detail": "Sent to client",
      "granularity": "high"
    }
  ],
  "has_more": false
}
```

### Visual Design

```
┌─────────────────────────────────────────────┐
│  📋 Activity Log                            │
├─────────────────────────────────────────────┤
│                                             │
│  📅  Date Confirmed                         │
│      March 15, 2025                         │
│      ─ Today at 10:30 AM                    │
│                                             │
│  ───────────────────────────────────────    │
│                                             │
│  ✅  Manager Approved                       │
│      Sent to client                         │
│      ─ Today at 10:28 AM                    │
│                                             │
│  ───────────────────────────────────────    │
│                                             │
│  👤  Client Saved                           │
│      John Smith                             │
│      ─ Today at 10:15 AM                    │
│                                             │
└─────────────────────────────────────────────┘
```

### Display Rules

| Field | How to Display |
|-------|----------------|
| `icon` | Show as-is (emoji) |
| `title` | Bold, main text |
| `detail` | Smaller text below title. **If empty, hide this line.** |
| `timestamp` | Format as relative time ("2 min ago") or date ("Jan 28 at 10:30 AM") |

### Sorting
- **Newest first** (the API already returns them in this order)

---

# PART 2: COMPLETE LIST OF ACTIVITIES

> **Every activity the system can log is listed below.**
> The frontend should be able to display ALL of these.

---

## Category 1: Booking Milestones

These mark key steps in the booking process.

| Icon | Title | Detail Shows | What Triggered It |
|------|-------|--------------|-------------------|
| 👤 | **Client Saved** | Client name | New client added to CRM |
| 📅 | **Event Created** | Event type | New booking inquiry started |
| 📅 | **Date Confirmed** | The confirmed date | Client agreed to a specific date |
| 🏢 | **Room Selected** | Room name | Room was chosen and reserved |
| 📄 | **Offer Sent** | Price amount | Quote was sent to client |
| ✅ | **Offer Accepted** | Price amount | Client accepted the quote |
| ❌ | **Offer Rejected** | Rejection reason | Client declined the quote |
| 💳 | **Deposit Required** | Amount + percentage | Deposit was requested |
| 💳 | **Deposit Paid** | Amount paid | Client paid the deposit |
| 💳 | **Deposit Set** | New amount | Deposit amount was set |
| 💳 | **Deposit Updated** | Old → New amount | Deposit amount was changed |
| 💳 | **Billing Updated** | Updated fields | Billing info was modified |
| ✅ | **Booking Confirmed** | Room + Date summary | Booking was finalized |

---

## Category 2: Booking Status Changes

These show the booking's overall status.

| Icon | Title | Detail Shows | What It Means |
|------|-------|--------------|---------------|
| 🔵 | **Status: Lead** | (empty) | Initial inquiry, nothing confirmed |
| 🟡 | **Status: Option** | Hold expiry date | Room is temporarily held |
| 🟢 | **Status: Confirmed** | (empty) | Booking is fully confirmed |
| ⚫ | **Status: Cancelled** | Cancellation reason | Booking was cancelled |

---

## Category 3: Client Changes (Detours)

These appear when a client changes their requirements mid-booking.

| Icon | Title | Detail Shows | What Happened |
|------|-------|--------------|---------------|
| 📅 | **Date Changed** | "Old date → New date" | Client requested a different date |
| 🏢 | **Room Changed** | "Old room → New room" | Client requested a different room |
| 👥 | **Participants Changed** | "Old count → New count" | Guest count was updated |
| 🍽️ | **Products Changed** | What was added/removed | Services or products changed |
| ✨ | **Special Request** | The request text | Client made a special request |

---

## Category 4: Manager Actions

These appear when a manager manually changes something.

| Icon | Title | Detail Shows | What Manager Did |
|------|-------|--------------|------------------|
| 👔 | **Manager: Date Changed** | "Old → New date" | Manager changed the event date |
| 👔 | **Manager: Room Changed** | New room name | Manager changed the room |
| 👔 | **Manager: Room Cancelled** | Cancelled room | Manager cancelled a room |
| 👔 | **Manager: Requirements Updated** | What changed | Manager updated requirements |
| 👔 | **Manager: Offer Updated** | "Old → New price" | Manager adjusted pricing |
| 👔 | **Manager: Site Visit Rescheduled** | New date/time | Manager rescheduled the tour |

---

## Category 5: Manager Approvals (Human-in-the-Loop)

These show manager decisions on AI-generated responses.

| Icon | Title | Detail Shows | What Manager Did |
|------|-------|--------------|------------------|
| ✅ | **Manager Approved** | "Sent to client" | Approved the AI response as-is |
| ❌ | **Manager Rejected** | Rejection reason | Rejected the AI response |
| ✏️ | **Manager Modified** | "Adjusted wording" | Edited then approved |
| 📦 | **Product Sourced** | Vendor/product info | Confirmed product availability |

---

## Category 6: Verification Failures

These appear when something couldn't be done.

| Icon | Title | Detail Shows | What Went Wrong |
|------|-------|--------------|-----------------|
| ❌ | **Date Denied** | "Date - Reason" | Requested date not available |
| ❌ | **Room Denied** | "Room - Reason" | Requested room not available |
| ⚠️ | **Date Conflict** | Conflict description | Date has a scheduling conflict |
| ⚠️ | **Room Conflict** | Conflict description | Room has a scheduling conflict |
| ⚠️ | **Capacity Exceeded** | "X guests, max Y" | Too many guests for the room |

---

## Category 7: Site Visits

These track venue tour scheduling.

| Icon | Title | Detail Shows | What Happened |
|------|-------|--------------|---------------|
| 🚶 | **Site Visit Booked** | Date and time | Tour was scheduled |
| ✅ | **Site Visit Completed** | (empty) | Tour was completed |

---

# PART 3: EXAMPLES

---

## Example 1: Simple Successful Booking

A straightforward booking with no changes.

```
Timeline (newest first):

✅  Booking Confirmed
    Grand Ballroom - March 15, 2025
    ─ Jan 28 at 11:00 AM

💳  Deposit Paid
    €500
    ─ Jan 28 at 10:55 AM

💳  Deposit Required
    €500 (20%)
    ─ Jan 28 at 10:50 AM

✅  Offer Accepted
    €2,500
    ─ Jan 28 at 10:45 AM

📄  Offer Sent
    €2,500
    ─ Jan 28 at 10:40 AM

🏢  Room Selected
    Grand Ballroom
    ─ Jan 28 at 10:35 AM

📅  Date Confirmed
    March 15, 2025
    ─ Jan 28 at 10:30 AM

📅  Event Created
    Wedding Reception
    ─ Jan 28 at 10:20 AM

👤  Client Saved
    John Smith
    ─ Jan 28 at 10:15 AM
```

**Progress Bar:** ✅ 100% - Confirmed

---

## Example 2: Client Changes Date Mid-Booking

Client originally wanted March 10, then changed to March 20.

```
Timeline (newest first):

📄  Offer Sent
    €2,500
    ─ Jan 28 at 11:15 AM

🏢  Room Selected
    Grand Ballroom
    ─ Jan 28 at 11:10 AM

📅  Date Changed                    ← CLIENT CHANGED THEIR MIND
    March 10 → March 20
    ─ Jan 28 at 11:00 AM

🏢  Room Selected
    Grand Ballroom
    ─ Jan 28 at 10:40 AM

📅  Date Confirmed
    March 10, 2025
    ─ Jan 28 at 10:30 AM

📅  Event Created
    Corporate Event
    ─ Jan 28 at 10:20 AM

👤  Client Saved
    Jane Doe
    ─ Jan 28 at 10:15 AM
```

**Progress Bar:** 📄 60% - Offer stage

---

## Example 3: Manager Intervenes After Rejection

Client rejected initial offer, manager adjusted price.

```
Timeline (newest first):

✅  Offer Accepted
    €2,000
    ─ Jan 28 at 2:30 PM

📄  Offer Sent
    €2,000
    ─ Jan 28 at 2:25 PM

👔  Manager: Offer Updated          ← MANAGER STEPPED IN
    €2,500 → €2,000
    ─ Jan 28 at 2:20 PM

❌  Offer Rejected                  ← CLIENT SAID NO
    Price too high
    ─ Jan 28 at 2:00 PM

📄  Offer Sent
    €2,500
    ─ Jan 28 at 11:00 AM

🏢  Room Selected
    Meeting Room A
    ─ Jan 28 at 10:45 AM

📅  Date Confirmed
    March 15, 2025
    ─ Jan 28 at 10:30 AM
```

**Progress Bar:** 📄 60% - Offer stage (waiting for deposit)

---

## Example 4: Date Not Available

Client requested a date that wasn't available.

```
Timeline (newest first):

📅  Date Confirmed
    March 20, 2025
    ─ Jan 28 at 11:00 AM

❌  Date Denied                     ← FIRST DATE DIDN'T WORK
    March 15, 2025 - Already booked
    ─ Jan 28 at 10:45 AM

📅  Event Created
    Birthday Party
    ─ Jan 28 at 10:30 AM

👤  Client Saved
    Bob Wilson
    ─ Jan 28 at 10:25 AM
```

**Progress Bar:** 📅 20% - Date stage

---

## Example 5: Manager Approval Flow

Shows the human-in-the-loop approval process.

```
Timeline (newest first):

📄  Offer Sent
    €1,500
    ─ Jan 28 at 3:00 PM

✅  Manager Approved                ← MANAGER APPROVED AI RESPONSE
    Sent to client
    ─ Jan 28 at 2:55 PM

🏢  Room Selected
    Conference Room B
    ─ Jan 28 at 2:30 PM

✏️  Manager Modified               ← MANAGER EDITED AI RESPONSE
    Adjusted availability details
    ─ Jan 28 at 2:25 PM

📅  Date Confirmed
    April 5, 2025
    ─ Jan 28 at 2:00 PM
```

---

# PART 4: IMPLEMENTATION CHECKLIST

---

## Must Have

- [ ] Progress bar component showing 5 stages
- [ ] Activity timeline component (scrollable list)
- [ ] Display all activity types from Part 2
- [ ] Handle empty `detail` field (don't show detail line)
- [ ] Format timestamps as relative time or readable date
- [ ] Newest activities at top

## Nice to Have

- [ ] Color coding by activity category
- [ ] Filter by category (show only Manager Actions, etc.)
- [ ] "Show detailed view" toggle (changes `granularity` param to `detailed`)
- [ ] Animation when new activity appears
- [ ] Click to expand activity for more context

## Color Suggestions

| Category | Suggested Color |
|----------|-----------------|
| Milestones (confirmations, completions) | Green |
| Information (selections, created) | Blue |
| Warnings (conflicts, capacity) | Orange |
| Failures (denied, rejected, cancelled) | Red |
| Manager Actions | Purple |

---

# PART 5: API REFERENCE

---

## Endpoint 1: Get Progress

```
GET /api/events/{event_id}/progress
```

**Response:**
```json
{
  "current_stage": "room",
  "percentage": 40,
  "stages": [
    {"id": "date", "label": "Date", "status": "completed", "icon": "📅"},
    {"id": "room", "label": "Room", "status": "active", "icon": "🏢"},
    {"id": "offer", "label": "Offer", "status": "pending", "icon": "📄"},
    {"id": "deposit", "label": "Deposit", "status": "pending", "icon": "💳"},
    {"id": "confirmed", "label": "Confirmed", "status": "pending", "icon": "✅"}
  ]
}
```

---

## Endpoint 2: Get Activities

```
GET /api/events/{event_id}/activity?granularity=high&limit=50
```

**Parameters:**
| Parameter | Default | Description |
|-----------|---------|-------------|
| `granularity` | `high` | `high` = manager view, `detailed` = debug view |
| `limit` | `50` | Max activities to return (max 200) |

**Response:**
```json
{
  "activities": [
    {
      "id": "act_1706450000123",
      "timestamp": "2025-01-28T10:30:00",
      "icon": "📅",
      "title": "Date Confirmed",
      "detail": "March 15, 2025",
      "granularity": "high"
    }
  ],
  "has_more": false,
  "event_id": "event_123",
  "granularity": "high"
}
```

**Activity Object:**
| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique ID like `"act_1706450000123"` |
| `timestamp` | string | ISO format: `"2025-01-28T10:30:00"` |
| `icon` | string | Emoji: `"📅"`, `"🏢"`, `"✅"`, etc. |
| `title` | string | Short action name |
| `detail` | string | Extra context (can be empty `""`) |
| `granularity` | string | `"high"` or `"detailed"` |

---

# Questions?

Contact the backend team if you need:
- Additional activity types
- Different information in the `detail` field
- Changes to the API response format
