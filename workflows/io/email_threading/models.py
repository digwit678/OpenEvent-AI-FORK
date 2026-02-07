"""Data models for email threading.

These models track email message metadata and event signatures for thread resolution.
They are stored in the database to enable deterministic reply linking and
semantic event matching.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class EmailMessage:
    """Represents email metadata for thread linking.

    Stores RFC 5322 message headers for deterministic reply detection:
    - message_id: Unique Message-ID header
    - in_reply_to: Parent message if this is a reply
    - references: Chain of ancestor message IDs

    Also tracks resolution outcome for future lookups.
    """
    message_id: str
    from_address: str
    in_reply_to: Optional[str] = None
    references: List[str] = field(default_factory=list)
    resolved_event_id: Optional[str] = None
    created_at: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EmailMessage":
        """Construct from database dict."""
        return cls(
            message_id=data.get("message_id", ""),
            from_address=data.get("from_address", ""),
            in_reply_to=data.get("in_reply_to"),
            references=data.get("references", []),
            resolved_event_id=data.get("resolved_event_id"),
            created_at=data.get("created_at"),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for database storage."""
        return {
            "message_id": self.message_id,
            "from_address": self.from_address,
            "in_reply_to": self.in_reply_to,
            "references": self.references,
            "resolved_event_id": self.resolved_event_id,
            "created_at": self.created_at or datetime.now(timezone.utc).isoformat(),
        }

    @classmethod
    def from_payload(cls, payload: Dict[str, Any]) -> "EmailMessage":
        """Construct from incoming message payload.

        Extracts email headers from the raw payload format.
        """
        headers = payload.get("headers", {})

        # Handle References header (can be string or list)
        raw_refs = headers.get("References", headers.get("references", []))
        if isinstance(raw_refs, str):
            # Split by whitespace (RFC 5322 format)
            references = [r.strip() for r in raw_refs.split() if r.strip()]
        else:
            references = list(raw_refs) if raw_refs else []

        return cls(
            message_id=headers.get("Message-ID", headers.get("message_id", payload.get("msg_id", ""))),
            from_address=(payload.get("from_email") or "").lower(),
            in_reply_to=headers.get("In-Reply-To", headers.get("in_reply_to")),
            references=references,
        )


@dataclass
class EventSignature:
    """Summary of event characteristics for semantic matching.

    LLM-derived snapshot of key event details used when comparing
    new emails against existing events. Updated when events are
    created or significantly modified.
    """
    event_id: str
    client_email: str
    date_range: Optional[Dict[str, str]] = None  # {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}
    room_or_location: Optional[str] = None
    participant_count: Optional[int] = None
    event_type: Optional[str] = None
    key_details: Optional[str] = None  # LLM-summarized distinguishing features
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EventSignature":
        """Construct from database dict."""
        return cls(
            event_id=data.get("event_id", ""),
            client_email=data.get("client_email", ""),
            date_range=data.get("date_range"),
            room_or_location=data.get("room_or_location"),
            participant_count=data.get("participant_count"),
            event_type=data.get("event_type"),
            key_details=data.get("key_details"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for database storage."""
        now = datetime.now(timezone.utc).isoformat()
        return {
            "event_id": self.event_id,
            "client_email": self.client_email,
            "date_range": self.date_range,
            "room_or_location": self.room_or_location,
            "participant_count": self.participant_count,
            "event_type": self.event_type,
            "key_details": self.key_details,
            "created_at": self.created_at or now,
            "updated_at": now,
        }

    @classmethod
    def from_event(cls, event: Dict[str, Any]) -> "EventSignature":
        """Extract signature from an event entry.

        Pulls key fields from the event record to create a matching signature.
        """
        event_data = event.get("event_data", {})

        # Build date range
        date_range = None
        chosen_date = event.get("chosen_date")
        end_date = event.get("end_date")
        if chosen_date:
            # Normalize to ISO if needed
            start_iso = _normalize_date_to_iso(chosen_date)
            end_iso = _normalize_date_to_iso(end_date) if end_date else start_iso
            if start_iso:
                date_range = {"start": start_iso, "end": end_iso or start_iso}

        # Extract participant count
        participants = event_data.get("Number of Participants")
        participant_count = None
        if participants and participants != "Not specified":
            try:
                participant_count = int(participants)
            except (ValueError, TypeError):
                pass

        return cls(
            event_id=event.get("event_id", ""),
            client_email=(event_data.get("Email") or "").lower(),
            date_range=date_range,
            room_or_location=event.get("locked_room_id") or event.get("selected_room") or event_data.get("Preferred Room"),
            participant_count=participant_count,
            event_type=event_data.get("Type of Event") if event_data.get("Type of Event") != "Not specified" else None,
        )


@dataclass
class ThreadMapping:
    """Maps email thread to event for quick lookup.

    Created when an email is resolved to an event. The email_thread_id
    can be derived from Message-ID or an explicit OE token.
    """
    email_thread_id: str  # Message-ID or OE token
    event_id: str
    created_at: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ThreadMapping":
        """Construct from database dict."""
        return cls(
            email_thread_id=data.get("email_thread_id", ""),
            event_id=data.get("event_id", ""),
            created_at=data.get("created_at"),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for database storage."""
        return {
            "email_thread_id": self.email_thread_id,
            "event_id": self.event_id,
            "created_at": self.created_at or datetime.now(timezone.utc).isoformat(),
        }


@dataclass
class ResolutionResult:
    """Result of thread resolution.

    Contains the decision (attach to existing event or create new) along with
    confidence score and any possible duplicates flagged for review.
    """
    decision: str  # "attach" or "new_event"
    event_id: Optional[str] = None  # Set if decision is "attach"
    confidence: float = 0.0
    possible_duplicates: List[str] = field(default_factory=list)  # Event IDs that might be related
    reason: Optional[str] = None  # Explanation of decision

    def __post_init__(self):
        """Validate decision values."""
        if self.decision not in ("attach", "new_event"):
            raise ValueError(f"Invalid decision: {self.decision}")


def _normalize_date_to_iso(date_str: Optional[str]) -> Optional[str]:
    """Convert DD.MM.YYYY or other formats to YYYY-MM-DD."""
    if not date_str or date_str in ("Not specified", ""):
        return None

    # Already ISO format
    if "-" in date_str and len(date_str) >= 10:
        return date_str[:10]

    # DD.MM.YYYY format
    if "." in date_str:
        try:
            parts = date_str.split(".")
            if len(parts) == 3:
                day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
                return f"{year:04d}-{month:02d}-{day:02d}"
        except (ValueError, IndexError):
            pass

    return None
