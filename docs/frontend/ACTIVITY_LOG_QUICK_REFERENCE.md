# Activity Log - Quick Reference

> Condensed version of ACTIVITY_LOG_SPEC.md. Nothing excluded.

---

## API Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /api/events/{event_id}/progress` | Progress bar (5 stages) |
| `GET /api/events/{event_id}/activity?granularity=high&limit=50` | Activity timeline |

---

## Progress Bar Response

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

**Stage statuses:** `completed` (green) → `active` (blue) → `pending` (gray)

---

## Activity Response

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
  "has_more": false
}
```

**Display:** icon + title (bold) + detail (if not empty) + formatted timestamp. Newest first.

---

## All Activity Types

### Booking Milestones
| Icon | Title | Detail |
|------|-------|--------|
| 👤 | Client Saved | Client name |
| 📅 | Event Created | Event type |
| 📅 | Date Confirmed | Confirmed date |
| 🏢 | Room Selected | Room name |
| 📄 | Offer Sent | Price |
| ✅ | Offer Accepted | Price |
| ❌ | Offer Rejected | Reason |
| 💳 | Deposit Required | Amount (%) |
| 💳 | Deposit Paid | Amount |
| 💳 | Deposit Set | Amount |
| 💳 | Deposit Updated | Old → New |
| 💳 | Billing Updated | Fields changed |
| ✅ | Booking Confirmed | Room + Date |

### Status Changes
| Icon | Title | Detail |
|------|-------|--------|
| 🔵 | Status: Lead | (empty) |
| 🟡 | Status: Option | Hold expiry |
| 🟢 | Status: Confirmed | (empty) |
| ⚫ | Status: Cancelled | Reason |

### Client Changes (Detours)
| Icon | Title | Detail |
|------|-------|--------|
| 📅 | Date Changed | Old → New |
| 🏢 | Room Changed | Old → New |
| 👥 | Participants Changed | Old → New count |
| 🍽️ | Products Changed | Added/removed |
| ✨ | Special Request | Request text |

### Manager Actions
| Icon | Title | Detail |
|------|-------|--------|
| 👔 | Manager: Date Changed | Old → New |
| 👔 | Manager: Room Changed | New room |
| 👔 | Manager: Room Cancelled | Room name |
| 👔 | Manager: Requirements Updated | What changed |
| 👔 | Manager: Offer Updated | Old → New price |
| 👔 | Manager: Site Visit Rescheduled | New date/time |

### Manager Approvals (HIL)
| Icon | Title | Detail |
|------|-------|--------|
| ✅ | Manager Approved | "Sent to client" |
| ❌ | Manager Rejected | Reason |
| ✏️ | Manager Modified | "Adjusted wording" |
| 📦 | Product Sourced | Vendor/product |

### Verification Failures
| Icon | Title | Detail |
|------|-------|--------|
| ❌ | Date Denied | Date - Reason |
| ❌ | Room Denied | Room - Reason |
| ⚠️ | Date Conflict | Description |
| ⚠️ | Room Conflict | Description |
| ⚠️ | Capacity Exceeded | X guests, max Y |

### Site Visits
| Icon | Title | Detail |
|------|-------|--------|
| 🚶 | Site Visit Booked | Date and time |
| ✅ | Site Visit Completed | (empty) |

---

## Example: Complete Booking

```
✅ Booking Confirmed      Grand Ballroom - March 15     11:00 AM
💳 Deposit Paid           €500                          10:55 AM
💳 Deposit Required       €500 (20%)                    10:50 AM
✅ Offer Accepted         €2,500                        10:45 AM
📄 Offer Sent             €2,500                        10:40 AM
🏢 Room Selected          Grand Ballroom                10:35 AM
📅 Date Confirmed         March 15, 2025                10:30 AM
📅 Event Created          Wedding Reception             10:20 AM
👤 Client Saved           John Smith                    10:15 AM
```

## Example: Date Change Mid-Flow

```
📄 Offer Sent             €2,500                        11:15 AM
🏢 Room Selected          Grand Ballroom                11:10 AM
📅 Date Changed           March 10 → March 20           11:00 AM  ← CHANGE
🏢 Room Selected          Grand Ballroom                10:40 AM
📅 Date Confirmed         March 10, 2025                10:30 AM
📅 Event Created          Corporate Event               10:20 AM
👤 Client Saved           Jane Doe                      10:15 AM
```

## Example: Manager Intervention

```
✅ Offer Accepted         €2,000                        2:30 PM
📄 Offer Sent             €2,000                        2:25 PM
👔 Manager: Offer Updated €2,500 → €2,000               2:20 PM   ← MANAGER
❌ Offer Rejected         Price too high                2:00 PM   ← REJECTED
📄 Offer Sent             €2,500                        11:00 AM
```

## Example: Date Unavailable

```
📅 Date Confirmed         March 20, 2025                11:00 AM
❌ Date Denied            March 15 - Already booked     10:45 AM  ← DENIED
📅 Event Created          Birthday Party                10:30 AM
👤 Client Saved           Bob Wilson                    10:25 AM
```

## Example: Manager Approval Flow

```
📄 Offer Sent             €1,500                        3:00 PM
✅ Manager Approved       Sent to client                2:55 PM   ← APPROVED
🏢 Room Selected          Conference Room B             2:30 PM
✏️ Manager Modified       Adjusted availability         2:25 PM   ← EDITED
📅 Date Confirmed         April 5, 2025                 2:00 PM
```

---

## Implementation Checklist

**Must Have:**
- [ ] Progress bar (5 stages, 3 statuses)
- [ ] Activity timeline (scrollable, newest first)
- [ ] All 35 activity types above
- [ ] Hide detail line if empty
- [ ] Format timestamps (relative or date)

**Nice to Have:**
- [ ] Color by category (green=success, red=failure, purple=manager)
- [ ] Category filter
- [ ] "Detailed view" toggle (`granularity=detailed`)

---

## Color Guide

| Type | Color |
|------|-------|
| Success (✅, 🟢) | Green |
| Info (📅, 🏢, 👤) | Blue |
| Warning (⚠️, 🟡) | Orange |
| Failure (❌, ⚫) | Red |
| Manager (👔, ✏️) | Purple |
