"""Pydantic models and enums for event workflows."""

from __future__ import annotations

import os
from datetime import datetime
from enum import Enum
from typing import Literal, Optional

# Debug flag - set WF_DEBUG_STATE=1 to enable verbose workflow prints
WF_DEBUG = os.getenv("WF_DEBUG_STATE") == "1"

try:  # pragma: no cover - optional dependency for CLI environments
    from pydantic import BaseModel, EmailStr, Field
except Exception:  # pragma: no cover - fallback when Pydantic is absent
    class BaseModel:  # type: ignore[override]
        """Lightweight stand-in mirroring the subset of Pydantic we rely on."""

        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

        def dict(self, *_, **__):  # noqa: D401 - documented via class docstring
            """Return the stored attributes as a dictionary."""

            return self.__dict__

        def model_dump(self, *_, **__):
            """Mimic Pydantic's model_dump behaviour."""

            return self.dict()

    EmailStr = str  # type: ignore[assignment]

    def Field(*args, default_factory=None, **kwargs):  # type: ignore[no-redef]
        """Stub for Pydantic Field when Pydantic is absent."""
        if default_factory is not None:
            return default_factory()
        return None


class EventStatus(str, Enum):
    """Event lifecycle states stored in the workflow database."""

    LEAD = "Lead"
    OPTION = "Option"
    CONFIRMED = "Confirmed"
    CANCELLED = "Cancelled"


class RoomStatus(str, Enum):
    """Availability markers for rooms within the venue."""

    AVAILABLE = "Available"
    OPTION = "Option"
    CONFIRMED = "Confirmed"


class EventInformation(BaseModel):
    """Pydantic schema mirroring the legacy intake form."""

    # Core Information (always required)
    date_email_received: str  # DD.MM.YYYY
    status: str = "Lead"
    event_date: Optional[str] = "Not specified"  # DD.MM.YYYY
    name: Optional[str] = "Not specified"
    email: EmailStr
    phone: Optional[str] = "Not specified"
    company: Optional[str] = "Not specified"
    billing_address: Optional[str] = "Not specified"

    # Event Details
    start_time: Optional[str] = "Not specified"  # HH:mm
    end_time: Optional[str] = "Not specified"  # HH:mm
    preferred_room: Optional[str] = "Not specified"  # Room A, Room B, Room C
    number_of_participants: Optional[str] = "Not specified"
    type_of_event: Optional[str] = "Not specified"
    catering_preference: Optional[str] = "Not specified"

    # Room Availability (filled after calendar check)
    room_a_status: str = "Available"
    room_b_status: str = "Available"
    room_c_status: str = "Available"

    # Billing
    billing_amount: Optional[str] = "none"
    deposit: Optional[str] = "none"

    # Meta
    language: Optional[str] = "Not specified"  # de, en, fr, it

    # Additional fields for tracking
    additional_info: Optional[str] = "Not specified"

    def get_missing_fields(self) -> list[str]:
        """Return the subset of important fields still marked as unspecified."""

        important_fields = [
            "event_date",
            "name",
            "start_time",
            "end_time",
            "preferred_room",
            "number_of_participants",
            "type_of_event",
        ]
        missing = []
        for field in important_fields:
            value = getattr(self, field)
            if value == "Not specified" or value is None:
                missing.append(field)
        return missing

    def is_complete(self) -> bool:
        """Assess whether the minimum booking details are present."""

        critical_fields = [
            "event_date",
            "name",
            "email",
            "phone",
            "preferred_room",
            "number_of_participants",
            "billing_address",
        ]

        if WF_DEBUG:
            print("\n=== IS_COMPLETE CHECK (RELAXED) ===")
            for field in critical_fields:
                value = getattr(self, field)
                is_valid = not (value == "Not specified" or value is None or value == "")
                print(f"{field}: '{value}' → {'✅' if is_valid else '❌'}")

        for field in critical_fields:
            value = getattr(self, field)
            if value == "Not specified" or value is None or value == "":
                if WF_DEBUG:
                    print(f"❌ FAILED: {field}")
                    print("===================================\n")
                return False

        if (
            self.catering_preference == "Not specified"
            or self.catering_preference is None
            or len(self.catering_preference) < 5
        ):
            if WF_DEBUG:
                print("❌ FAILED: catering_preference")
                print("===================================\n")
            return False

        if WF_DEBUG:
            print("✅ ALL CRITICAL CHECKS PASSED!")
            print("===================================\n")
        return True

    def to_dict(self) -> dict[str, str | Literal["Not specified"]]:
        """Convert the model into the legacy JSON structure."""

        return {
            "Date Email Received": self.date_email_received,
            "Status": self.status,
            "Event Date": self.event_date,
            "Name": self.name,
            "Email": self.email,
            "Phone": self.phone,
            "Company": self.company,
            "Billing Address": self.billing_address,
            "Start Time": self.start_time,
            "End Time": self.end_time,
            "Preferred Room": self.preferred_room,
            "Number of Participants": self.number_of_participants,
            "Type of Event": self.type_of_event,
            "Catering Preference": self.catering_preference,
            "Billing Amount": self.billing_amount,
            "Deposit": self.deposit,
            "Language": self.language,
            "Additional Info": self.additional_info,
        }


class ConversationState(BaseModel):
    """UI helper model for the legacy conversation manager."""

    session_id: str
    event_info: EventInformation
    conversation_history: list[dict]
    event_id: Optional[str] = None
    workflow_type: Optional[str] = None
    is_complete: bool = False
    created_at: datetime = Field(default_factory=datetime.now)
