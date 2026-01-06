# Pseudolinks & Calendar Integration Implementation Plan

## Overview
This document outlines the implementation of pseudolinks for room and catering options in agent messages, and the creation of calendar events when status transitions occur. The implementation is designed to be easily replaceable with real links when integrating with the OpenEvent platform.

## Requirements
1. Add pseudolinks to agent replies for room and catering options
2. Prepare infrastructure for quick integration with real links
3. Pass necessary parameters (date, room, etc.) to links
4. Create calendar events when status transitions occur (Lead → Option → Confirmed)
5. Keep long messages in replies for testing, with pseudolinks appearing before them

## Implementation Tasks

### Task 1: Create Pseudolink Generator Utility
**Location**: `/backend/utils/pseudolinks.py` (new file)

```python
"""
Pseudolink generator for room and catering options.
Easily replaceable with real link generation when platform integration is ready.
"""

def generate_room_details_link(room_name: str, date: str, participants: int = None) -> str:
    """Generate pseudolink for room details page."""
    # For now: return formatted pseudolink
    # Future: return actual platform URL
    params = f"?date={date}"
    if participants:
        params += f"&capacity={participants}"
    return f"[View {room_name} details](https://atelier.openevent.ch/rooms/{room_name.lower().replace(' ', '-')}{params})"

def generate_catering_menu_link(menu_name: str, room: str = None, date: str = None) -> str:
    """Generate pseudolink for catering menu details."""
    params = []
    if room:
        params.append(f"room={room.lower().replace(' ', '-')}")
    if date:
        params.append(f"date={date}")
    param_str = "?" + "&".join(params) if params else ""
    menu_slug = menu_name.lower().replace(' ', '-')
    return f"[View {menu_name} menu](https://atelier.openevent.ch/catering/{menu_slug}{param_str})"

def generate_room_availability_link(date_range: str = None) -> str:
    """Generate pseudolink for room availability calendar."""
    params = f"?dates={date_range}" if date_range else ""
    return f"[Check room availability](https://atelier.openevent.ch/availability{params})"

def generate_product_catalog_link(category: str = None) -> str:
    """Generate pseudolink for product catalog."""
    if category:
        return f"[Browse {category} options](https://atelier.openevent.ch/products/{category.lower()})"
    return "[Browse all add-on options](https://atelier.openevent.ch/products)"

def generate_offer_preview_link(offer_id: str) -> str:
    """Generate pseudolink for offer preview/PDF."""
    return f"[Preview offer PDF](https://atelier.openevent.ch/offers/{offer_id}/preview)"
```

### Task 2: Update Room Availability Messages (Step 3)
**Location**: `/backend/workflows/groups/room_availability/trigger/process.py`

**Changes needed**:
1. Import pseudolink generator at top of file
2. Modify room presentation logic to include pseudolinks

**In the room availability message composition** (around where room options are presented):
```python
from backend.utils.pseudolinks import generate_room_details_link

# When building room options message:
for room in available_rooms:
    room_name = room.get("name")
    # Add pseudolink before room description
    room_link = generate_room_details_link(
        room_name=room_name,
        date=event_entry.get("chosen_date"),
        participants=event_entry.get("number_of_participants")
    )
    # Include link in the message before the detailed description
```

### Task 3: Update Offer Composition Messages (Step 4)
**Location**: `/backend/workflows/groups/offer/trigger/process.py`

**Changes needed**:
1. Import pseudolink generators
2. Update `_compose_offer_summary` function (lines 1012-1177)

**Specific locations to add links**:

a) **Room information section** (around line 1037):
```python
from backend.utils.pseudolinks import generate_room_details_link

room_link = generate_room_details_link(
    room_name=room,
    date=chosen_date,
    participants=_infer_participant_count(event_entry)
)
lines.append(room_link)
lines.append(f"**{room}** for your event on {format_iso_date_to_ddmmyyyy(chosen_date)}")
```

b) **Catering alternatives section** (around lines 1111-1119):
```python
from backend.utils.pseudolinks import generate_catering_menu_link

if not selected_catering and catering_alternatives:
    catalog_link = generate_product_catalog_link("catering")
    lines.append("")
    lines.append(catalog_link)
    lines.append("Menu options you can add:")
    for entry in catering_alternatives:
        name = entry.get("name") or "Catering option"
        menu_link = generate_catering_menu_link(
            menu_name=name,
            room=event_entry.get("locked_room_id"),
            date=event_entry.get("chosen_date")
        )
        lines.append(menu_link)
        # Keep existing detailed line
        lines.append(f"- {name} · CHF {unit_price:,.2f} {unit_label}")
```

c) **Product alternatives section** (around lines 1127-1146):
```python
if product_alternatives:
    product_link = generate_product_catalog_link("add-ons")
    lines.append(product_link)
    lines.append("*Other close matches you can add:*")
    # ... existing code ...
```

d) **Offer preview link** (at the end of offer composition):
```python
from backend.utils.pseudolinks import generate_offer_preview_link

if offer_id:
    preview_link = generate_offer_preview_link(offer_id)
    lines.append("")
    lines.append(preview_link)
```

### Task 4: Create Calendar Event Manager
**Location**: `/backend/utils/calendar_events.py` (new file)

```python
"""
Calendar event creation for workflow status transitions.
Placeholder implementation - to be replaced with actual calendar API integration.
"""

import json
import os
from datetime import datetime
from typing import Dict, Any, Optional

def create_calendar_event(event_entry: Dict[str, Any], event_type: str) -> Dict[str, Any]:
    """
    Create a calendar event for the booking.

    Args:
        event_entry: The event data from the database
        event_type: Type of calendar event (lead, option, confirmed)

    Returns:
        Calendar event data that would be sent to calendar API
    """
    event_id = event_entry.get("event_id")
    chosen_date = event_entry.get("chosen_date")
    room = event_entry.get("locked_room_id", "TBD")
    client_name = event_entry.get("event_data", {}).get("Name", "Unknown Client")
    participants = event_entry.get("number_of_participants", 0)

    # Build calendar event data
    calendar_event = {
        "id": f"openevent-{event_id}",
        "title": f"[{event_type.upper()}] {client_name} - {room}",
        "date": chosen_date,
        "room": room,
        "participants": participants,
        "status": event_type,
        "description": f"Event booking for {client_name}\nParticipants: {participants}\nStatus: {event_type}",
        "created_at": datetime.utcnow().isoformat(),
    }

    # In production: send to calendar API
    # For now: log to file for testing
    _log_calendar_event(calendar_event)

    return calendar_event

def update_calendar_event_status(event_id: str, old_status: str, new_status: str) -> bool:
    """Update existing calendar event when status changes."""
    # In production: call calendar API to update event
    # For now: log the update
    update_data = {
        "event_id": f"openevent-{event_id}",
        "old_status": old_status,
        "new_status": new_status,
        "updated_at": datetime.utcnow().isoformat(),
    }
    _log_calendar_event(update_data, action="update")
    return True

def _log_calendar_event(event_data: Dict[str, Any], action: str = "create") -> None:
    """Log calendar events to file for testing."""
    log_dir = "tmp-cache/calendar_events"
    os.makedirs(log_dir, exist_ok=True)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"{log_dir}/calendar_{action}_{timestamp}.json"

    with open(filename, 'w') as f:
        json.dump(event_data, f, indent=2)
```

### Task 5: Integrate Calendar Events with Workflow

**a) Event Creation (Step 1)**
**Location**: `/backend/workflows/io/database.py` - in `create_event_entry` function (line 239)

```python
from backend.utils.calendar_events import create_calendar_event

def create_event_entry(db: Dict[str, Any], event_data: Dict[str, Any]) -> str:
    # ... existing code ...
    db.setdefault("events", []).append(entry)

    # Create calendar event with Lead status
    try:
        calendar_event = create_calendar_event(entry, "lead")
        entry["calendar_event_id"] = calendar_event.get("id")
    except Exception as e:
        logger.warning(f"Failed to create calendar event: {e}")

    return event_id
```

**b) Date Confirmation (Step 2)**
**Location**: `/backend/workflows/groups/date_confirmation/trigger/process.py` - in date confirmation logic (around line 2158)

```python
from backend.utils.calendar_events import update_calendar_event_status

# After date_confirmed=True is set:
if event_entry.get("calendar_event_id"):
    # Update existing calendar event with confirmed date
    update_calendar_event_status(
        event_entry.get("event_id"),
        "lead",
        "lead"  # Status stays Lead but now has confirmed date
    )
```

**c) Status Transitions (Steps 5 & 7)**
**Location**: Add to relevant workflow steps where status changes occur

For Option status (typically in negotiation/acceptance):
```python
if new_status == "Option":
    update_calendar_event_status(
        event_entry.get("event_id"),
        event_entry.get("status", "Lead"),
        "Option"
    )
    event_entry["status"] = "Option"
```

For Confirmed status (in final confirmation):
```python
if new_status == "Confirmed":
    update_calendar_event_status(
        event_entry.get("event_id"),
        event_entry.get("status", "Option"),
        "Confirmed"
    )
    event_entry["status"] = "Confirmed"
```

### Task 6: Update Universal Verbalizer
**Location**: `/backend/ux/universal_verbalizer.py`

Add pseudolink integration to the message context:
```python
from backend.utils.pseudolinks import (
    generate_room_details_link,
    generate_catering_menu_link,
    generate_room_availability_link
)

# In MessageContext class, add:
pseudolinks: Dict[str, str] = field(default_factory=dict)

# In verbalization logic, populate pseudolinks based on context
```

## Testing Plan

1. **Unit Tests for Pseudolink Generator**
   - Create `/backend/tests/utils/test_pseudolinks.py`
   - Test all link generation functions with various parameters
   - Ensure proper URL encoding and parameter handling

2. **Integration Tests for Calendar Events**
   - Create `/backend/tests/utils/test_calendar_events.py`
   - Test event creation at each status
   - Verify status transitions update calendar

3. **Workflow Tests**
   - Update existing workflow tests to check for pseudolinks in messages
   - Verify calendar events are created/updated at correct points

4. **Manual Testing Checklist**
   - [ ] Create new event inquiry - verify Lead calendar event created
   - [ ] Confirm date - verify calendar event updated with date
   - [ ] View room options - verify room detail links appear
   - [ ] View offer - verify catering/product links appear
   - [ ] Accept offer - verify status changes to Option/Confirmed

## Migration to Production

When ready to integrate with the actual platform:

1. **Replace Pseudolink Functions**
   - Update `backend/utils/pseudolinks.py` to generate real URLs
   - Add authentication/API keys as needed
   - Update URL patterns to match platform routes

2. **Replace Calendar Integration**
   - Update `backend/utils/calendar_events.py` to use real calendar API
   - Add proper error handling and retry logic
   - Implement webhook handlers for calendar sync

3. **Configuration**
   - Add environment variables for:
     - `OPENEVENT_PLATFORM_URL`
     - `CALENDAR_API_ENDPOINT`
     - `CALENDAR_API_KEY`
   - Update `backend/config.py` to read these values

4. **Remove Test Messages**
   - Search for pseudolink insertions
   - Remove long descriptive text after links
   - Keep only links and essential information

## Implementation Priority

1. **High Priority** (implement first):
   - Pseudolink generator utility
   - Update Step 4 offer messages with links
   - Calendar event creation on Lead status

2. **Medium Priority**:
   - Update Step 3 room messages with links
   - Calendar event updates on status transitions
   - Unit tests for new utilities

3. **Low Priority** (can be deferred):
   - Universal verbalizer integration
   - Comprehensive integration tests
   - Additional link types (Q&A, policies, etc.)

## Notes for Junior Developer

1. **Start with the utility files** - they're standalone and easier to test
2. **Use the existing patterns** - look at how other utilities are structured
3. **Test incrementally** - don't wait until everything is done to test
4. **Keep the pseudolinks obvious** - they should clearly indicate they're not real links
5. **Log everything** - add debug logging for calendar operations
6. **Ask questions** - if unsure about workflow integration points

## Code Style Guidelines

- Follow existing code patterns in the codebase
- Use type hints for all function parameters and returns
- Add docstrings to all new functions
- Keep functions focused and single-purpose
- Use descriptive variable names
- Add comments for complex logic