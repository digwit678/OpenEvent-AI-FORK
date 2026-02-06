# Lovable: Update Activity Log Content

> The Activity Log UI exists. This tells Lovable what content/entities to populate.

---

## Prompt for Lovable

```
Update the Activity Log component to display these activity types. The UI structure exists - just populate it with this content.

## Progress Bar Stages (5 fixed stages)

Always show these 5 stages in order:
1. 📅 Date
2. 🏢 Room
3. 📄 Offer
4. 💳 Deposit
5. ✅ Confirmed

Each stage has status: "completed" (green), "active" (blue), or "pending" (gray).
Show percentage (0-100) from the API.

## Activity Types to Display

The activity timeline shows these entries. Each has: icon, title, detail, timestamp.

BOOKING MILESTONES:
- 👤 Client Saved → detail: client name
- 📅 Event Created → detail: event type
- 📅 Date Confirmed → detail: the date
- 🏢 Room Selected → detail: room name
- 📄 Offer Sent → detail: price
- ✅ Offer Accepted → detail: price
- ❌ Offer Rejected → detail: reason
- 💳 Deposit Required → detail: amount (%)
- 💳 Deposit Paid → detail: amount
- 💳 Deposit Set → detail: amount
- 💳 Deposit Updated → detail: old → new
- 💳 Billing Updated → detail: what changed
- ✅ Booking Confirmed → detail: room + date

STATUS CHANGES:
- 🔵 Status: Lead → detail: (empty)
- 🟡 Status: Option → detail: hold expiry
- 🟢 Status: Confirmed → detail: (empty)
- ⚫ Status: Cancelled → detail: reason

CLIENT CHANGES:
- 📅 Date Changed → detail: old → new
- 🏢 Room Changed → detail: old → new
- 👥 Participants Changed → detail: old → new count
- 🍽️ Products Changed → detail: what changed
- ✨ Special Request → detail: request text

MANAGER ACTIONS:
- 👔 Manager: Date Changed → detail: old → new
- 👔 Manager: Room Changed → detail: new room
- 👔 Manager: Room Cancelled → detail: room name
- 👔 Manager: Requirements Updated → detail: what changed
- 👔 Manager: Offer Updated → detail: old → new price
- 👔 Manager: Site Visit Rescheduled → detail: new date/time

MANAGER APPROVALS:
- ✅ Manager Approved → detail: "Sent to client"
- ❌ Manager Rejected → detail: reason
- ✏️ Manager Modified → detail: "Adjusted wording"
- 📦 Product Sourced → detail: vendor/product

VERIFICATION FAILURES:
- ❌ Date Denied → detail: date - reason
- ❌ Room Denied → detail: room - reason
- ⚠️ Date Conflict → detail: conflict info
- ⚠️ Room Conflict → detail: conflict info
- ⚠️ Capacity Exceeded → detail: "X guests, max Y"

SITE VISITS:
- 🚶 Site Visit Booked → detail: date and time
- ✅ Site Visit Completed → detail: (empty)

## Display Rules

1. If detail is empty, hide the detail line
2. Show newest activities first
3. Format timestamp as "X min ago" or "Jan 28 at 10:30 AM"

## Colors by Icon

Green: ✅ 🟢
Blue: 📅 🏢 👤 📄 🔵 📦
Orange: ⚠️ 🟡
Red: ❌ ⚫
Purple: 👔 ✏️
Teal: 💳
Gray: 🍽️ ✨ 👥 🚶
```

---

## Test Data

Use this to verify all activity types render correctly:

```json
[
  {"icon": "👤", "title": "Client Saved", "detail": "John Smith", "timestamp": "2025-01-28T10:15:00"},
  {"icon": "📅", "title": "Event Created", "detail": "Wedding Reception", "timestamp": "2025-01-28T10:20:00"},
  {"icon": "📅", "title": "Date Confirmed", "detail": "March 15, 2025", "timestamp": "2025-01-28T10:30:00"},
  {"icon": "🏢", "title": "Room Selected", "detail": "Grand Ballroom", "timestamp": "2025-01-28T10:35:00"},
  {"icon": "📄", "title": "Offer Sent", "detail": "€2,500", "timestamp": "2025-01-28T10:40:00"},
  {"icon": "✅", "title": "Offer Accepted", "detail": "€2,500", "timestamp": "2025-01-28T10:45:00"},
  {"icon": "❌", "title": "Offer Rejected", "detail": "Price too high", "timestamp": "2025-01-28T10:46:00"},
  {"icon": "💳", "title": "Deposit Required", "detail": "€500 (20%)", "timestamp": "2025-01-28T10:50:00"},
  {"icon": "💳", "title": "Deposit Paid", "detail": "€500", "timestamp": "2025-01-28T10:55:00"},
  {"icon": "💳", "title": "Deposit Set", "detail": "€500", "timestamp": "2025-01-28T10:56:00"},
  {"icon": "💳", "title": "Deposit Updated", "detail": "€500 → €600", "timestamp": "2025-01-28T10:57:00"},
  {"icon": "💳", "title": "Billing Updated", "detail": "Address added", "timestamp": "2025-01-28T10:58:00"},
  {"icon": "✅", "title": "Booking Confirmed", "detail": "Grand Ballroom - March 15", "timestamp": "2025-01-28T11:00:00"},
  {"icon": "🔵", "title": "Status: Lead", "detail": "", "timestamp": "2025-01-28T10:15:00"},
  {"icon": "🟡", "title": "Status: Option", "detail": "Until March 1", "timestamp": "2025-01-28T10:35:00"},
  {"icon": "🟢", "title": "Status: Confirmed", "detail": "", "timestamp": "2025-01-28T11:00:00"},
  {"icon": "⚫", "title": "Status: Cancelled", "detail": "Client request", "timestamp": "2025-01-28T12:00:00"},
  {"icon": "📅", "title": "Date Changed", "detail": "March 10 → March 15", "timestamp": "2025-01-28T10:32:00"},
  {"icon": "🏢", "title": "Room Changed", "detail": "Room A → Grand Ballroom", "timestamp": "2025-01-28T10:36:00"},
  {"icon": "👥", "title": "Participants Changed", "detail": "50 → 75 guests", "timestamp": "2025-01-28T10:37:00"},
  {"icon": "🍽️", "title": "Products Changed", "detail": "Added: Catering", "timestamp": "2025-01-28T10:38:00"},
  {"icon": "✨", "title": "Special Request", "detail": "Wheelchair access needed", "timestamp": "2025-01-28T10:39:00"},
  {"icon": "👔", "title": "Manager: Date Changed", "detail": "March 15 → March 20", "timestamp": "2025-01-28T11:30:00"},
  {"icon": "👔", "title": "Manager: Room Changed", "detail": "Moved to Ballroom B", "timestamp": "2025-01-28T11:31:00"},
  {"icon": "👔", "title": "Manager: Room Cancelled", "detail": "Meeting Room A", "timestamp": "2025-01-28T11:32:00"},
  {"icon": "👔", "title": "Manager: Requirements Updated", "detail": "Added AV equipment", "timestamp": "2025-01-28T11:33:00"},
  {"icon": "👔", "title": "Manager: Offer Updated", "detail": "€2,500 → €2,200", "timestamp": "2025-01-28T11:34:00"},
  {"icon": "👔", "title": "Manager: Site Visit Rescheduled", "detail": "March 5 at 2pm", "timestamp": "2025-01-28T11:35:00"},
  {"icon": "✅", "title": "Manager Approved", "detail": "Sent to client", "timestamp": "2025-01-28T10:29:00"},
  {"icon": "❌", "title": "Manager Rejected", "detail": "Needs revision", "timestamp": "2025-01-28T10:28:00"},
  {"icon": "✏️", "title": "Manager Modified", "detail": "Adjusted wording", "timestamp": "2025-01-28T10:27:00"},
  {"icon": "📦", "title": "Product Sourced", "detail": "Catering from Vendor X", "timestamp": "2025-01-28T10:40:00"},
  {"icon": "❌", "title": "Date Denied", "detail": "March 10 - No availability", "timestamp": "2025-01-28T10:25:00"},
  {"icon": "❌", "title": "Room Denied", "detail": "Ballroom - Already booked", "timestamp": "2025-01-28T10:26:00"},
  {"icon": "⚠️", "title": "Date Conflict", "detail": "Conflicts with maintenance", "timestamp": "2025-01-28T10:24:00"},
  {"icon": "⚠️", "title": "Room Conflict", "detail": "Double booking detected", "timestamp": "2025-01-28T10:23:00"},
  {"icon": "⚠️", "title": "Capacity Exceeded", "detail": "100 guests, max 80", "timestamp": "2025-01-28T10:22:00"},
  {"icon": "🚶", "title": "Site Visit Booked", "detail": "March 5, 2025 at 2:00 PM", "timestamp": "2025-01-28T10:50:00"},
  {"icon": "✅", "title": "Site Visit Completed", "detail": "", "timestamp": "2025-03-05T15:00:00"}
]
```

---

## Quick Reference Table

| Category | Count | Icons |
|----------|-------|-------|
| Booking Milestones | 13 | 👤 📅 🏢 📄 ✅ ❌ 💳 |
| Status Changes | 4 | 🔵 🟡 🟢 ⚫ |
| Client Changes | 5 | 📅 🏢 👥 🍽️ ✨ |
| Manager Actions | 6 | 👔 |
| Manager Approvals | 4 | ✅ ❌ ✏️ 📦 |
| Verification Failures | 5 | ❌ ⚠️ |
| Site Visits | 2 | 🚶 ✅ |
| **Total** | **39** | |
