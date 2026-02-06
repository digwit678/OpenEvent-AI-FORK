# Activity Log - Content Specification

> The UI exists. This document specifies **what content** to display.

---

## API Endpoints

| What | Endpoint |
|------|----------|
| Progress | `GET /api/events/{event_id}/progress` |
| Activities | `GET /api/events/{event_id}/activity?granularity=high` |

---

## Progress Bar Content

**5 stages, always in this order:**

| Position | Icon | Label | ID |
|----------|------|-------|-----|
| 1 | 📅 | Date | `date` |
| 2 | 🏢 | Room | `room` |
| 3 | 📄 | Offer | `offer` |
| 4 | 💳 | Deposit | `deposit` |
| 5 | ✅ | Confirmed | `confirmed` |

**Each stage has a `status`:**
- `completed` → Show as done (green/checkmark)
- `active` → Show as current (blue/highlighted)
- `pending` → Show as upcoming (gray/empty)

**Also display:** `percentage` (0-100)

---

## Activity Content

Each activity from the API has:

```
icon      →  Display as-is (emoji)
title     →  Main text (bold)
detail    →  Secondary text (if not empty)
timestamp →  Format as relative time or date
```

**Rule:** If `detail` is empty string `""`, hide the detail line entirely.

---

## Complete Activity List

### Booking Milestones

| Icon | Title | Detail Contains |
|------|-------|-----------------|
| 👤 | Client Saved | Client name |
| 📅 | Event Created | Event type |
| 📅 | Date Confirmed | The date (e.g., "March 15, 2025") |
| 🏢 | Room Selected | Room name |
| 📄 | Offer Sent | Price (e.g., "€2,500") |
| ✅ | Offer Accepted | Price |
| ❌ | Offer Rejected | Rejection reason |
| 💳 | Deposit Required | Amount and % (e.g., "€500 (20%)") |
| 💳 | Deposit Paid | Amount paid |
| 💳 | Deposit Set | Amount |
| 💳 | Deposit Updated | "Old → New" (e.g., "€500 → €600") |
| 💳 | Billing Updated | What changed |
| ✅ | Booking Confirmed | Room + Date summary |

### Status Changes

| Icon | Title | Detail Contains |
|------|-------|-----------------|
| 🔵 | Status: Lead | *(empty)* |
| 🟡 | Status: Option | Hold expiry (e.g., "Until March 1") |
| 🟢 | Status: Confirmed | *(empty)* |
| ⚫ | Status: Cancelled | Reason |

### Client Changes

| Icon | Title | Detail Contains |
|------|-------|-----------------|
| 📅 | Date Changed | "Old → New" (e.g., "March 10 → March 15") |
| 🏢 | Room Changed | "Old → New" |
| 👥 | Participants Changed | "Old → New" (e.g., "50 → 75 guests") |
| 🍽️ | Products Changed | What changed (e.g., "Added: Catering") |
| ✨ | Special Request | The request text |

### Manager Actions

| Icon | Title | Detail Contains |
|------|-------|-----------------|
| 👔 | Manager: Date Changed | "Old → New" |
| 👔 | Manager: Room Changed | New room name |
| 👔 | Manager: Room Cancelled | Cancelled room name |
| 👔 | Manager: Requirements Updated | What changed |
| 👔 | Manager: Offer Updated | "Old → New" price |
| 👔 | Manager: Site Visit Rescheduled | New date/time |

### Manager Approvals

| Icon | Title | Detail Contains |
|------|-------|-----------------|
| ✅ | Manager Approved | "Sent to client" |
| ❌ | Manager Rejected | Reason |
| ✏️ | Manager Modified | "Adjusted wording" or similar |
| 📦 | Product Sourced | Vendor/product info |

### Verification Failures

| Icon | Title | Detail Contains |
|------|-------|-----------------|
| ❌ | Date Denied | "Date - Reason" |
| ❌ | Room Denied | "Room - Reason" |
| ⚠️ | Date Conflict | Conflict description |
| ⚠️ | Room Conflict | Conflict description |
| ⚠️ | Capacity Exceeded | "X guests, max Y" |

### Site Visits

| Icon | Title | Detail Contains |
|------|-------|-----------------|
| 🚶 | Site Visit Booked | Date and time |
| ✅ | Site Visit Completed | *(empty)* |

---

## Color by Icon

| Icons | Color |
|-------|-------|
| ✅ 🟢 | Green |
| 📅 🏢 👤 📄 🔵 📦 | Blue |
| ⚠️ 🟡 | Orange |
| ❌ ⚫ | Red |
| 👔 ✏️ | Purple |
| 💳 | Teal |
| 🍽️ ✨ 👥 🚶 | Gray |

---

## Timestamp Display

The API returns: `"2025-01-28T10:30:00"`

Display as:
- **< 1 hour:** "X min ago"
- **Today:** "Today at 10:30 AM"
- **Yesterday:** "Yesterday at 10:30 AM"
- **Older:** "Jan 28 at 10:30 AM"

---

## Summary: 35 Activity Types

**Count by category:**
- Booking Milestones: 13
- Status Changes: 4
- Client Changes: 5
- Manager Actions: 6
- Manager Approvals: 4
- Verification Failures: 5
- Site Visits: 2

**Total: 39 unique title/icon combinations**

All are returned from the API with `granularity: "high"`.
