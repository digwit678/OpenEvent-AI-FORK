# Site Visit Implementation Plan

## Overview
This document outlines the implementation of site visit functionality as a Q&A-like thread that allows clients to book venue visits at any step in the workflow. Site visits work similarly to Q&A threads but with specific gatekeeping requirements and integration with the main booking flow.

## Requirements Summary

### From Lindy Workflow
1. **Trigger**: Client explicitly asks for a site visit/viewing of the venue
2. **Gatekeeping Requirements**:
   - Must have a valid room (either specified or from main flow)
   - Must have a valid date (either specified or proposed)
3. **Date Constraints**:
   - If main event date is confirmed → site visit must be BEFORE event date
   - If no main event date → site visit can be any date from today onwards
4. **Room Defaults**:
   - If room locked in main flow → use that room for site visit
   - Client can override by explicitly mentioning different room
5. **Calendar Integration**:
   - Create calendar entry with status = "Option" for site visit
   - Separate from main event calendar entry

### Key Design Decisions
1. **Thread-like behavior**: Site visits are handled like Q&A - they branch off, complete, then return to main flow
2. **No disruption**: After site visit confirmation, continue with current main flow step
3. **Clear separation**: Never confuse site visit dates/rooms with main event dates/rooms
4. **Shortcuts allowed**: After showing available dates/rooms, client can confirm directly

## Architecture

### Site Visit Flow States
```
IDLE → DETECTING → GATEKEEPING → PROPOSING → CONFIRMING → SCHEDULED
                        ↓              ↓           ↓
                    (missing info)  (client      (client
                     ask for it)    selects)    confirms)
```

### Data Structure
```python
event_entry["site_visit_state"] = {
    "status": "idle" | "detecting" | "gatekeeping" | "proposing" | "confirming" | "scheduled",
    "requested_room": str | None,      # Room client asked for
    "requested_date": str | None,      # Date client asked for
    "proposed_dates": List[str],       # Dates we offered
    "proposed_rooms": List[str],       # Rooms we offered (if needed)
    "confirmed_room": str | None,      # Final room for visit
    "confirmed_date": str | None,      # Final date for visit
    "calendar_event_id": str | None,   # Calendar entry for visit
    "return_to_step": int,             # Which step to return to
}
```

## Implementation Tasks

### Phase 1: Site Visit Detection

#### Task 1.1: Create Site Visit Detector
**Location**: `/backend/workflows/nlu/site_visit_detector.py` (new file)

```python
"""
Site visit detection for client messages.
Detects explicit requests for venue visits, viewings, or tours.
"""

import re
from typing import Dict, Any, Tuple, List

# Site visit patterns
SITE_VISIT_PATTERNS = [
    # Direct visit requests
    r"\b(site\s+visit|venue\s+visit|room\s+visit)\b",
    r"\b(view|viewing|tour)\s+(the\s+)?(venue|room|space|location)\b",
    r"\b(visit\s+the\s+)(venue|room|space|location)\b",

    # See/look at patterns
    r"\b(see|look\s+at)\s+the\s+(room|venue|space)\b",
    r"\bshow\s+me\s+the\s+(room|venue|space)\b",

    # Come by/check out patterns
    r"\b(come\s+by|stop\s+by|check\s+out)\s+(the\s+)?(venue|room|space)\b",

    # Tour patterns
    r"\b(tour|walk[\s-]?through)\s+(of\s+)?(the\s+)?(venue|room|facility)\b",

    # Schedule viewing patterns
    r"\b(schedule|arrange|book)\s+a?\s*(site\s+)?visit\b",
    r"\b(schedule|arrange|book)\s+a?\s*viewing\b",
]

# Q&A patterns that might look like site visit but aren't
QNA_PATTERNS = [
    r"\bhow\s+(do|does|can)\s+(i|we)\s+visit\b",  # "How do I visit?"
    r"\bwhen\s+(can|could)\s+(i|we)\s+visit\b",   # "When can we visit?"
    r"\bare\s+visits\s+(allowed|possible)\b",      # "Are visits allowed?"
    r"\bdo\s+you\s+offer\s+site\s+visits\b",      # "Do you offer site visits?"
]

def detect_site_visit_request(message_text: str) -> Tuple[bool, float, Dict[str, Any]]:
    """
    Detect if message contains a site visit request.

    Returns:
        (is_site_visit, confidence, extracted_info)
    """
    text_lower = message_text.lower().strip()

    # First check if it's a Q&A about visits (not an actual request)
    for pattern in QNA_PATTERNS:
        if re.search(pattern, text_lower):
            return False, 0.0, {"reason": "qna_about_visits"}

    # Check for site visit patterns
    for pattern in SITE_VISIT_PATTERNS:
        match = re.search(pattern, text_lower)
        if match:
            # Extract additional context
            extracted = _extract_visit_details(text_lower)

            # Higher confidence if room/date mentioned
            base_confidence = 0.8
            if extracted.get("room") or extracted.get("date"):
                base_confidence = 0.9

            return True, base_confidence, extracted

    return False, 0.0, {}

def _extract_visit_details(text: str) -> Dict[str, Any]:
    """Extract room and date information from site visit request."""
    details = {}

    # Extract room mentions
    room_patterns = [
        r"\b(room\s+[a-z])\b",
        r"\b(punkt\.?null)\b",
        r"\b(sky\s*loft|garden|terrace)\b",
    ]
    for pattern in room_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            details["room"] = match.group(1)
            break

    # Extract date mentions (basic - would integrate with existing date extraction)
    date_patterns = [
        r"\b(\d{1,2}[./]\d{1,2}[./]\d{2,4})\b",  # DD/MM/YYYY
        r"\b(tomorrow|today|next\s+week|this\s+week)\b",
        r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    ]
    for pattern in date_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            details["date_text"] = match.group(1)
            break

    return details

def is_site_visit_confirmation(text: str, context: Dict[str, Any]) -> bool:
    """
    Check if message is confirming a site visit after we proposed dates/times.

    Args:
        text: Client message
        context: Current site visit state with proposed options

    Returns:
        True if this is confirming a proposed site visit option
    """
    if not context.get("proposed_dates"):
        return False

    text_lower = text.lower()

    # Direct date selection
    for date in context["proposed_dates"]:
        if date in text or _fuzzy_date_match(date, text):
            return True

    # Position selection ("first one", "second option")
    position_patterns = [
        r"\b(first|1st|option\s+1)\b",
        r"\b(second|2nd|option\s+2)\b",
        r"\b(third|3rd|option\s+3)\b",
    ]
    for i, pattern in enumerate(position_patterns):
        if re.search(pattern, text_lower) and i < len(context["proposed_dates"]):
            return True

    # General acceptance after site visit proposal
    if context.get("status") == "proposing":
        acceptance_patterns = [
            r"\b(yes|ok|sure|fine|good|works|perfect)\b",
            r"\b(that\s+works|sounds\s+good|let'?s\s+do)\b",
        ]
        for pattern in acceptance_patterns:
            if re.search(pattern, text_lower):
                return True

    return False

def _fuzzy_date_match(proposed_date: str, text: str) -> bool:
    """Check if text contains a fuzzy match for the proposed date."""
    # This would use the existing date extraction logic
    # For now, simple substring match
    date_parts = proposed_date.split("-")  # 2025-12-15
    if len(date_parts) == 3:
        # Check for DD.MM format at minimum
        day_month = f"{date_parts[2]}.{date_parts[1]}"
        if day_month in text:
            return True
    return False
```

#### Task 1.2: Integration with Intent Classifier
**Location**: `/backend/llm/intent_classifier.py`

Add to the `_detect_qna_types` function:

```python
def _detect_qna_types(text: str) -> List[str]:
    """Detect which Q&A categories apply to the message."""
    qna_types = []
    text_lower = text.lower()

    # Check for site visit requests FIRST (before other Q&A)
    from backend.workflows.nlu.site_visit_detector import detect_site_visit_request
    is_visit, confidence, _ = detect_site_visit_request(text)
    if is_visit and confidence > 0.7:
        qna_types.append("site_visit")
        # Site visit is exclusive - don't check other Q&A types
        return qna_types

    # ... existing Q&A detection logic ...
```

### Phase 2: Site Visit Thread Handler

#### Task 2.1: Create Site Visit Thread Manager
**Location**: `/backend/workflows/threads/site_visit_thread.py` (new file)

```python
"""
Site visit thread management.
Handles the sub-flow for scheduling venue visits.
"""

from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, date, timedelta

from backend.workflows.common.types import WorkflowState, GroupResult
from backend.workflows.common.prompts import append_footer
from backend.workflows.io.database import update_event_metadata
from backend.utils.calendar_events import create_calendar_event

class SiteVisitThread:
    """Manages site visit sub-flow."""

    def __init__(self, state: WorkflowState):
        self.state = state
        self.event_entry = state.event_entry
        self.visit_state = self._init_visit_state()

    def _init_visit_state(self) -> Dict[str, Any]:
        """Initialize or get existing site visit state."""
        if "site_visit_state" not in self.event_entry:
            self.event_entry["site_visit_state"] = {
                "status": "idle",
                "requested_room": None,
                "requested_date": None,
                "proposed_dates": [],
                "proposed_rooms": [],
                "confirmed_room": None,
                "confirmed_date": None,
                "calendar_event_id": None,
                "return_to_step": self.event_entry.get("current_step", 1),
            }
        return self.event_entry["site_visit_state"]

    def process_visit_request(self, message_text: str, extracted_info: Dict[str, Any]) -> GroupResult:
        """Process initial site visit request."""
        self.visit_state["status"] = "gatekeeping"
        self.visit_state["return_to_step"] = self.event_entry.get("current_step", 1)

        # Extract room and date from request
        self.visit_state["requested_room"] = extracted_info.get("room")
        self.visit_state["requested_date"] = extracted_info.get("date_text")

        # Apply defaults from main flow
        defaults = self._apply_defaults()

        # Check what's missing
        missing = self._check_gatekeeping()

        if missing:
            return self._ask_for_missing_info(missing)
        else:
            return self._propose_visit_options()

    def _apply_defaults(self) -> Dict[str, str]:
        """Apply defaults from main event flow."""
        defaults = {}

        # Default room from main flow
        if not self.visit_state["requested_room"]:
            locked_room = self.event_entry.get("locked_room_id")
            if locked_room:
                self.visit_state["requested_room"] = locked_room
                defaults["room"] = locked_room

        # No default date - must be explicitly provided or proposed

        return defaults

    def _check_gatekeeping(self) -> List[str]:
        """Check what information is missing for site visit."""
        missing = []

        # Must have a room (from request or default)
        if not self.visit_state["requested_room"]:
            missing.append("room")

        # Must have a date (from request)
        if not self.visit_state["requested_date"]:
            missing.append("date")

        return missing

    def _ask_for_missing_info(self, missing: List[str]) -> GroupResult:
        """Ask client for missing information."""
        prompts = []

        if "room" in missing:
            prompts.append("Which room would you like to visit?")
            # If we have rooms from main flow, list them
            if self.event_entry.get("available_rooms"):
                rooms = self.event_entry["available_rooms"]
                prompts.append("Available rooms: " + ", ".join(rooms))

        if "date" in missing:
            prompts.append("When would you like to visit? Please suggest a few dates that work for you.")

        message = " ".join(prompts)

        draft = {
            "body": append_footer(
                message,
                step=self.visit_state["return_to_step"],
                topic="site_visit_gatekeeping",
                next_step="Provide visit details",
                thread_state="Awaiting Client",
            ),
            "requires_approval": False,
        }

        self.state.add_draft_message(draft)
        return GroupResult(action="site_visit_gatekeeping", payload={}, halt=True)

    def _propose_visit_options(self) -> GroupResult:
        """Propose site visit times."""
        self.visit_state["status"] = "proposing"

        # Get available slots
        slots = self._generate_visit_slots()
        self.visit_state["proposed_dates"] = slots

        # Build message
        lines = [
            f"I'd be happy to arrange a site visit of {self.visit_state['requested_room']}.",
            "",
            "Here are some available times:",
        ]

        for i, slot in enumerate(slots, 1):
            lines.append(f"{i}. {slot}")

        lines.extend([
            "",
            "Which time works best for you? You can also suggest a different time if these don't suit.",
        ])

        draft = {
            "body": append_footer(
                "\n".join(lines),
                step=self.visit_state["return_to_step"],
                topic="site_visit_proposal",
                next_step="Select visit time",
                thread_state="Awaiting Client",
            ),
            "requires_approval": False,
        }

        self.state.add_draft_message(draft)
        return GroupResult(action="site_visit_proposed", payload=self.visit_state, halt=True)

    def process_visit_confirmation(self, message_text: str) -> GroupResult:
        """Process confirmation of site visit."""
        # Extract which option was selected
        selected_date = self._extract_selected_date(message_text)

        if not selected_date:
            # Ask for clarification
            return self._ask_date_clarification()

        # Confirm the visit
        self.visit_state["confirmed_date"] = selected_date
        self.visit_state["confirmed_room"] = self.visit_state["requested_room"]
        self.visit_state["status"] = "scheduled"

        # Create calendar event
        calendar_event = self._create_visit_calendar_event()
        self.visit_state["calendar_event_id"] = calendar_event.get("id")

        # Build confirmation message
        lines = [
            f"✓ Site visit confirmed!",
            "",
            f"**Date**: {self._format_date(selected_date)}",
            f"**Room**: {self.visit_state['confirmed_room']}",
            f"**Time**: 10:00 - 11:00 (1 hour tour)",
            "",
            "We'll meet you at the main entrance. Looking forward to showing you around!",
        ]

        # Add note about continuing main flow
        main_step = self.visit_state["return_to_step"]
        lines.extend([
            "",
            f"---",
            f"Let's continue with your event planning...",
        ])

        draft = {
            "body": "\n".join(lines),  # Don't use append_footer here - handle in main flow return
            "topic": "site_visit_confirmed",
            "requires_approval": False,
            "continue_main_flow": True,  # Signal to continue main flow
        }

        self.state.add_draft_message(draft)

        # Return control to main flow
        return GroupResult(
            action="site_visit_complete",
            payload={
                "site_visit_state": self.visit_state,
                "return_to_step": main_step,
            },
            halt=False,  # Don't halt - continue main flow
        )

    def _generate_visit_slots(self) -> List[str]:
        """Generate available visit slots based on constraints."""
        slots = []

        # Get constraints
        main_event_date = self.event_entry.get("chosen_date")
        today = datetime.now().date()

        # Determine date range
        if main_event_date:
            # Site visit must be before main event
            event_date = datetime.strptime(main_event_date, "%Y-%m-%d").date()
            end_date = event_date - timedelta(days=1)
        else:
            # No main event date - can be anytime in next 30 days
            end_date = today + timedelta(days=30)

        # Generate slots (simplified - would check actual calendar)
        current = today + timedelta(days=1)  # Start tomorrow
        while current <= end_date and len(slots) < 5:
            # Skip weekends for site visits
            if current.weekday() < 5:  # Monday = 0, Friday = 4
                date_str = current.strftime("%A, %B %d at 10:00 AM")
                slots.append(date_str)
            current += timedelta(days=1)

        return slots

    def _extract_selected_date(self, text: str) -> Optional[str]:
        """Extract which proposed date was selected."""
        text_lower = text.lower()

        # Check for position selection
        positions = ["first", "1st", "1", "second", "2nd", "2", "third", "3rd", "3"]
        for i, pos in enumerate(positions[::3]):  # Every third item
            if any(p in text_lower for p in positions[i*3:(i+1)*3]):
                if i < len(self.visit_state["proposed_dates"]):
                    # Convert display format back to ISO
                    return self._parse_display_date(self.visit_state["proposed_dates"][i])

        # Check for date mention
        # This would use proper date extraction
        return None

    def _parse_display_date(self, display_date: str) -> str:
        """Parse display date back to ISO format."""
        # Example: "Monday, December 2 at 10:00 AM" -> "2025-12-02"
        # Simplified - would use proper parsing
        import calendar

        parts = display_date.split()
        month_name = parts[1].rstrip(",")
        day = int(parts[2])
        year = datetime.now().year

        month = list(calendar.month_name).index(month_name)
        return f"{year}-{month:02d}-{day:02d}"

    def _format_date(self, iso_date: str) -> str:
        """Format ISO date for display."""
        dt = datetime.strptime(iso_date, "%Y-%m-%d")
        return dt.strftime("%A, %B %d, %Y")

    def _create_visit_calendar_event(self) -> Dict[str, Any]:
        """Create calendar event for site visit."""
        visit_event = {
            "event_id": self.event_entry.get("event_id"),
            "event_type": "site_visit",
            "status": "Option",
            "date": self.visit_state["confirmed_date"],
            "time": "10:00-11:00",
            "room": self.visit_state["confirmed_room"],
            "client_name": self.event_entry.get("event_data", {}).get("Name", "Client"),
            "description": f"Site visit for {self.visit_state['confirmed_room']}",
        }

        # This would integrate with the calendar system
        return create_calendar_event(visit_event, "site_visit")

    def _ask_date_clarification(self) -> GroupResult:
        """Ask for clarification on date selection."""
        message = (
            "I'm not sure which time you selected. Could you please specify:\n"
            "- The number (1, 2, 3...) of your preferred option, or\n"
            "- The specific date and time you'd prefer"
        )

        draft = {
            "body": append_footer(
                message,
                step=self.visit_state["return_to_step"],
                topic="site_visit_clarification",
                next_step="Clarify visit time",
                thread_state="Awaiting Client",
            ),
            "requires_approval": False,
        }

        self.state.add_draft_message(draft)
        return GroupResult(action="site_visit_clarification", payload={}, halt=True)
```

### Phase 3: Integration with Main Workflow

#### Task 3.1: Update Workflow Router
**Location**: `/backend/workflow_email.py`

Add site visit detection to the workflow router:

```python
def route_client_message(state: WorkflowState, message_text: str) -> str:
    """Route client messages to appropriate handlers."""

    # Check for site visit request first (before other Q&A)
    from backend.workflows.nlu.site_visit_detector import detect_site_visit_request
    is_visit, confidence, extracted_info = detect_site_visit_request(message_text)

    if is_visit and confidence > 0.7:
        # Check if we're already in site visit flow
        visit_state = state.event_entry.get("site_visit_state", {})
        if visit_state.get("status") == "proposing":
            # This might be a confirmation
            from backend.workflows.nlu.site_visit_detector import is_site_visit_confirmation
            if is_site_visit_confirmation(message_text, visit_state):
                return "site_visit_confirmation"

        return "site_visit_request"

    # ... existing routing logic ...
```

#### Task 3.2: Add Site Visit Handler to Each Step
**Location**: Each workflow step file needs to handle site visits

Example for Step 3 (Room Availability):
```python
def process(state: WorkflowState) -> GroupResult:
    """Process room availability step."""

    # Check if this is a site visit request
    if state.extras.get("route") == "site_visit_request":
        from backend.workflows.threads.site_visit_thread import SiteVisitThread
        thread = SiteVisitThread(state)
        extracted = state.extras.get("site_visit_extracted", {})
        return thread.process_visit_request(state.last_email_content, extracted)

    # Check if returning from site visit
    if state.extras.get("site_visit_complete"):
        # Continue with normal flow but prepend site visit confirmation
        site_visit_msg = state.extras.get("site_visit_confirmation_message")
        # ... continue normal step 3 processing ...

    # ... existing step 3 logic ...
```

### Phase 4: Site Visit Information Page

#### Task 4.1: Create Site Visit Info Page
**Location**: `/atelier-ai-frontend/app/info/site-visits/page.tsx`

```tsx
'use client'

import { useSearchParams } from 'next/navigation'
import { useEffect, useState } from 'react'

interface VisitSlot {
  date: string
  time: string
  available: boolean
  room?: string
}

interface VisitInfo {
  title: string
  duration: string
  includes: string[]
  meeting_point: string
  what_to_expect: string[]
  booking_policy: string
}

export default function SiteVisitsPage() {
  const searchParams = useSearchParams()
  const room = searchParams.get('room')
  const dateRange = searchParams.get('dates')
  const [visitInfo, setVisitInfo] = useState<VisitInfo | null>(null)
  const [availableSlots, setAvailableSlots] = useState<VisitSlot[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    // Load visit information
    const info: VisitInfo = {
      title: "Site Visit at The Atelier",
      duration: "60 minutes",
      includes: [
        "Guided tour of all event spaces",
        "Room setup demonstrations",
        "Technical capabilities overview",
        "Catering tasting options (if requested)",
        "Q&A with event coordinator",
      ],
      meeting_point: "Main reception - Bahnhofstrasse 10, 8001 Zürich",
      what_to_expect: [
        "Meet your dedicated event coordinator",
        "Tour the requested room(s) and alternatives",
        "See different layout configurations",
        "Review technical equipment and capabilities",
        "Discuss your specific event requirements",
        "Get answers to all your questions",
      ],
      booking_policy: "Site visits are complimentary and can be scheduled Monday-Friday, 9:00-17:00. Weekend visits may be arranged for confirmed bookings.",
    }
    setVisitInfo(info)

    // Generate available slots (mock data)
    const slots: VisitSlot[] = []
    const today = new Date()
    for (let i = 1; i <= 14; i++) {
      const date = new Date(today)
      date.setDate(today.getDate() + i)

      // Skip weekends
      if (date.getDay() === 0 || date.getDay() === 6) continue

      // Morning and afternoon slots
      slots.push({
        date: date.toISOString().split('T')[0],
        time: "10:00-11:00",
        available: true,
        room: room || undefined,
      })
      slots.push({
        date: date.toISOString().split('T')[0],
        time: "14:00-15:00",
        available: Math.random() > 0.3, // Some slots unavailable
        room: room || undefined,
      })
    }

    setAvailableSlots(slots)
    setLoading(false)
  }, [room, dateRange])

  if (loading || !visitInfo) {
    return (
      <div className="container mx-auto p-8">
        <div className="text-center">Loading site visit information...</div>
      </div>
    )
  }

  return (
    <div className="container mx-auto p-8 max-w-6xl">
      <h1 className="text-3xl font-bold mb-8">{visitInfo.title}</h1>

      {room && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-6">
          <span className="font-semibold">Viewing:</span> {room}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-8 mb-12">
        {/* Visit Information */}
        <div className="space-y-6">
          <div>
            <h2 className="text-2xl font-semibold mb-4">What's Included</h2>
            <ul className="space-y-2">
              {visitInfo.includes.map((item, idx) => (
                <li key={idx} className="flex items-start">
                  <span className="text-green-500 mr-2 mt-1">✓</span>
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>

          <div>
            <h2 className="text-2xl font-semibold mb-4">What to Expect</h2>
            <ol className="space-y-2">
              {visitInfo.what_to_expect.map((item, idx) => (
                <li key={idx} className="flex items-start">
                  <span className="font-semibold mr-2">{idx + 1}.</span>
                  <span>{item}</span>
                </li>
              ))}
            </ol>
          </div>

          <div className="bg-gray-50 rounded-lg p-6">
            <h3 className="font-semibold mb-2">Duration</h3>
            <p>{visitInfo.duration}</p>

            <h3 className="font-semibold mb-2 mt-4">Meeting Point</h3>
            <p>{visitInfo.meeting_point}</p>

            <h3 className="font-semibold mb-2 mt-4">Booking Policy</h3>
            <p className="text-sm text-gray-600">{visitInfo.booking_policy}</p>
          </div>
        </div>

        {/* Available Time Slots */}
        <div>
          <h2 className="text-2xl font-semibold mb-4">Available Time Slots</h2>
          <div className="bg-white border rounded-lg shadow-sm overflow-hidden">
            <div className="max-h-96 overflow-y-auto">
              {availableSlots.map((slot, idx) => {
                const date = new Date(slot.date)
                const dateStr = date.toLocaleDateString('en-US', {
                  weekday: 'long',
                  month: 'long',
                  day: 'numeric',
                })

                return (
                  <div
                    key={idx}
                    className={`p-4 border-b hover:bg-gray-50 ${
                      !slot.available ? 'opacity-50' : ''
                    }`}
                  >
                    <div className="flex justify-between items-center">
                      <div>
                        <div className="font-medium">{dateStr}</div>
                        <div className="text-gray-600">{slot.time}</div>
                      </div>
                      <div>
                        {slot.available ? (
                          <span className="px-3 py-1 bg-green-100 text-green-700 rounded-full text-sm">
                            Available
                          </span>
                        ) : (
                          <span className="px-3 py-1 bg-gray-100 text-gray-500 rounded-full text-sm">
                            Unavailable
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      </div>

      {/* How to Book */}
      <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-6">
        <h2 className="text-xl font-semibold mb-3">How to Book Your Visit</h2>
        <p>
          Simply return to your booking conversation and let us know which time slot works best for you.
          You can say something like "I'd like to visit on Tuesday at 10:00" or select from the options
          we've proposed.
        </p>
      </div>
    </div>
  )
}
```

#### Task 4.2: Update Link Generator
**Location**: Add to `/backend/utils/pseudolinks.py`

```python
def generate_site_visit_info_link(room: str = None) -> str:
    """Generate link to site visit information page."""
    params = {}
    if room:
        params["room"] = room

    query_string = urlencode(params) if params else ""
    url = f"{BASE_URL}/info/site-visits"
    if query_string:
        url += f"?{query_string}"

    return f"[Learn more about site visits]({url})"

def generate_site_visit_calendar_link(date_range: str = None) -> str:
    """Generate link to available site visit slots."""
    params = {}
    if date_range:
        params["dates"] = date_range

    query_string = urlencode(params) if params else ""
    url = f"{BASE_URL}/info/site-visits"
    if query_string:
        url += f"?{query_string}"

    return f"[View available site visit times]({url})"
```

### Phase 5: Testing

#### Task 5.1: Create Site Visit Tests
**Location**: `/backend/tests/detection/test_site_visit_detection.py`

```python
"""Tests for site visit detection."""

import pytest
from backend.workflows.nlu.site_visit_detector import (
    detect_site_visit_request,
    is_site_visit_confirmation,
)

class TestSiteVisitDetection:
    """Test site visit request detection."""

    def test_direct_site_visit_request(self):
        """Test direct site visit mentions."""
        messages = [
            "I'd like to schedule a site visit",
            "Can we arrange a venue visit?",
            "I want to see the room before booking",
            "Could we tour the facility?",
            "Let's book a viewing",
        ]

        for msg in messages:
            is_visit, confidence, _ = detect_site_visit_request(msg)
            assert is_visit is True
            assert confidence >= 0.8

    def test_site_visit_with_details(self):
        """Test site visit with room/date details."""
        is_visit, confidence, details = detect_site_visit_request(
            "Can I visit Room A next Tuesday?"
        )

        assert is_visit is True
        assert confidence >= 0.9  # Higher with details
        assert details.get("room") == "Room A"
        assert "tuesday" in details.get("date_text", "").lower()

    def test_not_site_visit_qna(self):
        """Test Q&A about visits (not actual requests)."""
        messages = [
            "How do I schedule a site visit?",
            "Do you offer site visits?",
            "When can we visit?",
            "Are site visits free?",
        ]

        for msg in messages:
            is_visit, confidence, info = detect_site_visit_request(msg)
            assert is_visit is False
            assert info.get("reason") == "qna_about_visits"

    def test_not_site_visit_other(self):
        """Test messages that aren't site visits."""
        messages = [
            "The room looks great",
            "I visited your website",
            "We'll visit Zurich in December",
            "Please send the contract",
        ]

        for msg in messages:
            is_visit, confidence, _ = detect_site_visit_request(msg)
            assert is_visit is False

class TestSiteVisitConfirmation:
    """Test site visit confirmation detection."""

    def test_confirmation_by_number(self):
        """Test confirming by option number."""
        context = {
            "proposed_dates": [
                "Monday, December 2 at 10:00 AM",
                "Tuesday, December 3 at 2:00 PM",
                "Thursday, December 5 at 10:00 AM",
            ],
            "status": "proposing",
        }

        messages = [
            ("the first one", True),
            ("I'll take option 2", True),
            ("3rd option please", True),
            ("number 4", False),  # Out of range
        ]

        for msg, expected in messages:
            result = is_site_visit_confirmation(msg, context)
            assert result is expected

    def test_confirmation_by_acceptance(self):
        """Test general acceptance after proposal."""
        context = {"status": "proposing", "proposed_dates": ["Monday at 10:00"]}

        messages = [
            ("Yes that works", True),
            ("Sounds good", True),
            ("Perfect", True),
            ("Actually, can we change the date?", False),
        ]

        for msg, expected in messages:
            result = is_site_visit_confirmation(msg, context)
            assert result is expected
```

### Phase 6: Implementation Checklist

1. **Detection & Classification** ✓
   - [ ] Create site visit detector with patterns
   - [ ] Integrate with intent classifier
   - [ ] Add tests for detection accuracy

2. **Thread Management** ✓
   - [ ] Create SiteVisitThread class
   - [ ] Handle gatekeeping logic
   - [ ] Implement date/room defaults
   - [ ] Create calendar events

3. **Workflow Integration** ✓
   - [ ] Update workflow router
   - [ ] Add handlers to each step
   - [ ] Handle return from site visit
   - [ ] Maintain main flow state

4. **Frontend Pages** ✓
   - [ ] Create site visit info page
   - [ ] Show available time slots
   - [ ] Display visit details
   - [ ] Add booking instructions

5. **Testing** ✓
   - [ ] Unit tests for detection
   - [ ] Integration tests for flow
   - [ ] Calendar event creation
   - [ ] Main flow continuation

## Key Considerations

### 1. No Conflicts with Q&A
- Site visit detection happens BEFORE general Q&A
- Exclusive detection - if site visit detected, skip other Q&A
- Clear patterns that don't overlap with questions ABOUT visits

### 2. Clear Date/Room Separation
- Always prefix with "Site visit:" in confirmations
- Use different variable names (site_visit_date vs chosen_date)
- Show both in messages when relevant

### 3. Smooth Flow Integration
- Store return step before branching
- Prepend site visit confirmation to next message
- Don't duplicate messages or leave gaps

### 4. Calendar Integration
- Separate calendar events for site visits (type: "site_visit")
- Status = "Option" for site visits
- Don't affect main event status

### 5. User-Friendly Defaults
- Use locked room from main flow
- Propose dates based on constraints
- Allow overrides with explicit mentions

## Future Enhancements (TODO)

1. **Better UX for Return**
   - Visual indicator that site visit is booked
   - Option to add multiple site visits
   - Cancel/reschedule site visits

2. **Enhanced Detection**
   - **LLM-based detection**: Transition from regex/keyword matching in `router.py` to LLM-based intent detection to handle nuanced requests and avoid false positives from emails/URLs.
   - Multi-language support
   - Handle "can I see it first?" type requests
   - Detect site visit changes/cancellations

3. **Calendar Integration**
   - Real calendar availability checking
   - Automated confirmation emails
   - iCal invites for site visits

4. **Reporting**
   - Track site visit → booking conversion
   - Popular visit times analytics
   - No-show tracking

### Phase 7: Site Visit Updates/Changes (Detours)

#### Task 7.1: Add Site Visit Change Detection
**Location**: Update `/backend/workflows/nlu/site_visit_detector.py`

```python
# Add to existing patterns
SITE_VISIT_CHANGE_PATTERNS = [
    # Change/update patterns
    r"\b(change|update|modify|reschedule)\s+(the\s+)?site\s+visit\b",
    r"\b(different|another|new)\s+(date|time|room)\s+for\s+(the\s+)?visit\b",
    r"\bsite\s+visit\s+(on|to|at)\s+[a-z]+\s+instead\b",

    # Cancellation patterns
    r"\bcancel\s+(the\s+)?site\s+visit\b",
    r"\b(don'?t|no\s+longer)\s+need\s+(the\s+)?site\s+visit\b",
]

def detect_site_visit_change(message_text: str, has_scheduled_visit: bool) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Detect if message contains a site visit change request.

    Returns:
        (is_change, change_type, extracted_info)
        change_type: "date" | "room" | "both" | "cancel"
    """
    if not has_scheduled_visit:
        return False, "", {}

    text_lower = message_text.lower().strip()

    # Check for change patterns
    for pattern in SITE_VISIT_CHANGE_PATTERNS:
        if re.search(pattern, text_lower):
            # Determine what's being changed
            change_type = _determine_change_type(text_lower)
            extracted = _extract_new_visit_details(text_lower)

            return True, change_type, extracted

    return False, "", {}

def _determine_change_type(text: str) -> str:
    """Determine what aspect of site visit is being changed."""
    has_date = bool(re.search(r"\b(date|time|day|when)\b", text))
    has_room = bool(re.search(r"\b(room|space|venue)\b", text))
    has_cancel = bool(re.search(r"\b(cancel|don'?t\s+need|no\s+longer)\b", text))

    if has_cancel:
        return "cancel"
    elif has_date and has_room:
        return "both"
    elif has_date:
        return "date"
    elif has_room:
        return "room"
    else:
        return "unknown"
```

#### Task 7.2: Add Dependency Checking for Site Visit Changes
**Location**: Update `/backend/workflows/threads/site_visit_thread.py`

```python
def process_visit_change(self, message_text: str, change_type: str, new_details: Dict[str, Any]) -> GroupResult:
    """Process site visit change request with dependency checking."""

    current_room = self.visit_state["confirmed_room"]
    current_date = self.visit_state["confirmed_date"]

    if change_type == "cancel":
        return self._cancel_site_visit()

    # Extract requested changes
    new_room = new_details.get("room") or current_room
    new_date = new_details.get("date_text") or current_date

    # Dependency validation
    validation_result = self._validate_visit_change(
        current_room, current_date, new_room, new_date, change_type
    )

    if not validation_result["valid"]:
        return self._handle_invalid_change(validation_result)

    # Apply the change
    return self._apply_visit_change(new_room, new_date, change_type)

def _validate_visit_change(
    self,
    current_room: str,
    current_date: str,
    new_room: str,
    new_date: str,
    change_type: str
) -> Dict[str, Any]:
    """
    Validate site visit change based on dependencies.

    Rules:
    1. If changing room -> check if new room is available on current date
    2. If changing date -> check if current room is available on new date
    3. If changing both -> check new room on new date
    4. New date must still be before main event (if set)
    """
    result = {"valid": True, "issues": [], "suggestions": []}

    # Check main event constraint
    main_event_date = self.event_entry.get("chosen_date")
    if main_event_date and new_date:
        if new_date >= main_event_date:
            result["valid"] = False
            result["issues"].append("Site visit must be before your main event")
            result["suggestions"].append(f"Choose a date before {main_event_date}")
            return result

    # Check room availability based on change type
    if change_type == "room":
        # Check if new room is available on current date
        if not self._check_room_available(new_room, current_date):
            result["valid"] = False
            result["issues"].append(f"{new_room} is not available on {current_date}")
            # Find alternative dates for this room
            alt_dates = self._find_available_dates_for_room(new_room)
            result["suggestions"].extend([f"{new_room} is available on: {', '.join(alt_dates[:3])}"])

    elif change_type == "date":
        # Check if current room is available on new date
        if not self._check_room_available(current_room, new_date):
            result["valid"] = False
            result["issues"].append(f"{current_room} is not available on {new_date}")
            # Find alternative rooms for this date
            alt_rooms = self._find_available_rooms_for_date(new_date)
            result["suggestions"].extend([f"On {new_date}, these rooms are available: {', '.join(alt_rooms)}"])

    elif change_type == "both":
        # Check if new room is available on new date
        if not self._check_room_available(new_room, new_date):
            result["valid"] = False
            result["issues"].append(f"{new_room} is not available on {new_date}")
            result["suggestions"].extend([
                "Try changing just the date or just the room first",
                "Or let me show you what combinations are available"
            ])

    return result

def _handle_invalid_change(self, validation_result: Dict[str, Any]) -> GroupResult:
    """Handle case where requested change violates dependencies."""
    lines = [
        "I'm unable to make that change:",
        "",
    ]

    for issue in validation_result["issues"]:
        lines.append(f"• {issue}")

    if validation_result["suggestions"]:
        lines.extend(["", "Here are some alternatives:"])
        for suggestion in validation_result["suggestions"]:
            lines.append(f"• {suggestion}")

    lines.append("")
    lines.append("Would you like to try a different change, or keep your current site visit?")

    draft = {
        "body": append_footer(
            "\n".join(lines),
            step=self.visit_state["return_to_step"],
            topic="site_visit_change_invalid",
            next_step="Resolve visit change",
            thread_state="Awaiting Client",
        ),
        "requires_approval": False,
    }

    self.state.add_draft_message(draft)
    return GroupResult(action="site_visit_change_blocked", payload=validation_result, halt=True)

def _apply_visit_change(self, new_room: str, new_date: str, change_type: str) -> GroupResult:
    """Apply validated site visit change."""
    old_room = self.visit_state["confirmed_room"]
    old_date = self.visit_state["confirmed_date"]

    # Update state
    self.visit_state["confirmed_room"] = new_room
    self.visit_state["confirmed_date"] = new_date
    self.visit_state["change_history"] = self.visit_state.get("change_history", [])
    self.visit_state["change_history"].append({
        "timestamp": datetime.utcnow().isoformat(),
        "type": change_type,
        "from": {"room": old_room, "date": old_date},
        "to": {"room": new_room, "date": new_date},
    })

    # Update calendar event
    if self.visit_state.get("calendar_event_id"):
        self._update_visit_calendar_event()

    # Build confirmation message
    lines = ["✓ Site visit updated!"]

    if change_type == "date":
        lines.append(f"**New date**: {self._format_date(new_date)}")
        lines.append(f"**Room**: {new_room} (unchanged)")
    elif change_type == "room":
        lines.append(f"**Date**: {self._format_date(new_date)} (unchanged)")
        lines.append(f"**New room**: {new_room}")
    else:  # both
        lines.append(f"**New date**: {self._format_date(new_date)}")
        lines.append(f"**New room**: {new_room}")

    lines.extend([
        "",
        "Your updated site visit is confirmed. See you then!",
        "",
        "---",
        "Continuing with your event planning...",
    ])

    draft = {
        "body": "\n".join(lines),
        "topic": "site_visit_updated",
        "requires_approval": False,
        "continue_main_flow": True,
    }

    self.state.add_draft_message(draft)

    return GroupResult(
        action="site_visit_updated",
        payload={
            "site_visit_state": self.visit_state,
            "change_type": change_type,
            "return_to_step": self.visit_state["return_to_step"],
        },
        halt=False,  # Continue main flow
    )

def _cancel_site_visit(self) -> GroupResult:
    """Cancel the site visit."""
    self.visit_state["status"] = "cancelled"
    self.visit_state["cancelled_at"] = datetime.utcnow().isoformat()

    # Cancel calendar event
    if self.visit_state.get("calendar_event_id"):
        # Would call calendar API to cancel
        pass

    lines = [
        "✓ Site visit cancelled",
        "",
        "Your site visit has been cancelled. You can always schedule a new one later if needed.",
        "",
        "---",
        "Let's continue with your event planning...",
    ]

    draft = {
        "body": "\n".join(lines),
        "topic": "site_visit_cancelled",
        "requires_approval": False,
        "continue_main_flow": True,
    }

    self.state.add_draft_message(draft)

    return GroupResult(
        action="site_visit_cancelled",
        payload={"site_visit_state": self.visit_state},
        halt=False,
    )
```

#### Task 7.3: Update Workflow Router for Changes
**Location**: Update `/backend/workflow_email.py`

```python
def route_client_message(state: WorkflowState, message_text: str) -> str:
    """Route client messages to appropriate handlers."""

    # Check if we have a scheduled site visit
    visit_state = state.event_entry.get("site_visit_state", {})
    has_scheduled_visit = visit_state.get("status") == "scheduled"

    if has_scheduled_visit:
        # Check for site visit changes BEFORE new requests
        from backend.workflows.nlu.site_visit_detector import detect_site_visit_change
        is_change, change_type, details = detect_site_visit_change(message_text, True)

        if is_change:
            state.extras["site_visit_change_type"] = change_type
            state.extras["site_visit_change_details"] = details
            return "site_visit_change"

    # ... rest of existing routing logic ...
```

### Phase 8: DAG Documentation Update

#### Task 8.1: Create Site Visit DAG Documentation
**Location**: Create `/backend/workflows/specs/site_visit_dag.md` (new file)

```markdown
# Site Visit Dependency Graph

## Overview

Site visits are a special type of sub-flow that can be initiated from any step in the main workflow. They have their own dependency constraints that interact with the main event dependencies.

## Site Visit State Variables

```
site_visit_room     ─┐
                     ├─► site_visit_confirmation
site_visit_date     ─┘
        │
        ▼
[Calendar Check: Is room available on date?]
        │
        ▼
site_visit_calendar_event (status: "Option")
```

## Dependency Rules

### 1. Initial Site Visit Booking

**Constraints:**
- `site_visit_room` must be from ROOM_CATALOG
- If `locked_room_id` exists in main flow → default to this room
- `site_visit_date` must be:
  - Future date (>= today)
  - If `chosen_date` exists → must be BEFORE main event
  - Weekday (Monday-Friday) for business hours

### 2. Site Visit Changes (Detours)

**Change Room Only:**
```
Current: site_visit_room = "Room A", site_visit_date = "2025-12-10"
Request: Change to "Room B"
Check: Is Room B available on 2025-12-10?
  ├─ Yes → Update site_visit_room, keep date
  └─ No → Offer alternative dates for Room B
```

**Change Date Only:**
```
Current: site_visit_room = "Room A", site_visit_date = "2025-12-10"
Request: Change to "2025-12-15"
Check: Is Room A available on 2025-12-15?
  ├─ Yes → Update site_visit_date, keep room
  └─ No → Offer alternative rooms for 2025-12-15
```

**Change Both Room and Date:**
```
Current: site_visit_room = "Room A", site_visit_date = "2025-12-10"
Request: Change to "Room B" on "2025-12-15"
Check: Is Room B available on 2025-12-15?
  ├─ Yes → Update both
  └─ No → Suggest changing one at a time
```

## Interaction with Main Event Flow

### Date Dependencies

```
Main Event Date (chosen_date) ────┐
                                  ▼
                           [Constraint Check]
                                  │
Site Visit Date ─────────────────┘
                                  │
                                  ▼
                    Must be: visit_date < event_date
```

### Room Dependencies

Site visit room is independent of main event room, BUT:
- Defaults to `locked_room_id` if available
- Can be different from main event room
- Must be available on the site visit date

## Change Propagation Matrix

| Changed Variable | Affects | Action Required |
|-----------------|---------|-----------------|
| site_visit_date | Calendar availability | Re-check room on new date |
| site_visit_room | Calendar availability | Re-check date for new room |
| main chosen_date | Site visit constraint | Ensure visit < new event date |
| main locked_room_id | Site visit default | No change to existing visit |

## State Transitions

```
IDLE → DETECTING → GATEKEEPING → PROPOSING → SCHEDULED
         │                           │           │
         └─(change request)──────────┴───────────┤
                                                 ▼
                                          CHANGE_VALIDATION
                                                 │
                                     ┌───────────┴───────────┐
                                     ▼                       ▼
                                  UPDATED               CHANGE_BLOCKED
                                     │                       │
                                     └───────────┬───────────┘
                                                 ▼
                                          (return to main flow)
```

## Hash Guards

Unlike main event changes, site visits don't use hash guards because:
1. They're simpler (just room + date)
2. They don't cascade to other steps
3. They're independent of main event state

## Calendar Integration

Site visits create separate calendar entries:
- Type: "site_visit"
- Status: "Option" (never "Confirmed")
- Linked to main event_id
- Updated/cancelled independently

## Example Scenarios

### Scenario 1: Simple Site Visit
```
Step 2: "I'd like to visit the venue"
→ Use locked_room_id if available (e.g., "Room A")
→ Propose dates before main event
→ Create calendar entry
→ Return to Step 2
```

### Scenario 2: Site Visit with Room Override
```
Step 3: "Can I tour Room B next week?"
→ Override default room
→ Check Room B availability
→ Create calendar entry for Room B
→ Return to Step 3
```

### Scenario 3: Site Visit Change with Conflict
```
Scheduled: Room A on Dec 10
Step 4: "Change site visit to Dec 15"
→ Check Room A on Dec 15
→ Not available
→ Offer: "Room B and C are available on Dec 15"
→ Or: "Room A is available on Dec 14, 16"
→ Client chooses
→ Update and return to Step 4
```
```

### Phase 9: Testing Site Visit Changes

#### Task 9.1: Add Change Detection Tests
**Location**: Update `/backend/tests/detection/test_site_visit_detection.py`

```python
class TestSiteVisitChangeDetection:
    """Test site visit change request detection."""

    def test_change_date_detection(self):
        """Test detecting date change requests."""
        messages = [
            "Can we change the site visit to next Friday?",
            "I need to reschedule the venue tour",
            "Different date for the visit please",
        ]

        for msg in messages:
            is_change, change_type, _ = detect_site_visit_change(msg, has_scheduled_visit=True)
            assert is_change is True
            assert change_type == "date"

    def test_change_room_detection(self):
        """Test detecting room change requests."""
        messages = [
            "Can we visit Room B instead?",
            "I'd like to see a different room",
            "Change the site visit to Punkt.Null",
        ]

        for msg in messages:
            is_change, change_type, _ = detect_site_visit_change(msg, has_scheduled_visit=True)
            assert is_change is True
            assert change_type == "room"

    def test_cancel_detection(self):
        """Test detecting cancellation requests."""
        messages = [
            "Cancel the site visit",
            "We don't need the venue tour anymore",
            "Skip the site visit",
        ]

        for msg in messages:
            is_change, change_type, _ = detect_site_visit_change(msg, has_scheduled_visit=True)
            assert is_change is True
            assert change_type == "cancel"

    def test_dependency_validation(self):
        """Test dependency checking for changes."""
        thread = SiteVisitThread(mock_state)

        # Test 1: Valid change
        result = thread._validate_visit_change(
            current_room="Room A",
            current_date="2025-12-10",
            new_room="Room A",
            new_date="2025-12-12",
            change_type="date"
        )
        assert result["valid"] is True

        # Test 2: Invalid - after main event
        thread.event_entry["chosen_date"] = "2025-12-11"
        result = thread._validate_visit_change(
            current_room="Room A",
            current_date="2025-12-10",
            new_room="Room A",
            new_date="2025-12-12",
            change_type="date"
        )
        assert result["valid"] is False
        assert "before your main event" in result["issues"][0]
```

## Summary

This implementation creates a seamless site visit booking experience that:
- Works from any workflow step
- Maintains context and returns properly
- Uses smart defaults while allowing flexibility
- Keeps site visits clearly separated from main events
- Provides clear information via test pages
- **Supports updates/changes with proper dependency validation**
- **Enforces business rules (visit before event, room availability)**

The junior developer should start with Phase 1 (detection) and work through sequentially. Each phase builds on the previous one, and the test suite ensures nothing breaks as features are added.

The site visit change functionality (Phase 7) ensures that updates respect the same constraints as initial bookings, with helpful suggestions when conflicts arise.