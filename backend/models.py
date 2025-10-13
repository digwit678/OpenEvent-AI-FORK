from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, EmailStr
from enum import Enum

class EventStatus(str, Enum):
    LEAD = "Lead"
    OPTION = "Option"
    CONFIRMED = "Confirmed"
    CANCELLED = "Cancelled"

class RoomStatus(str, Enum):
    AVAILABLE = "Available"
    OPTION = "Option"
    CONFIRMED = "Confirmed"

class EventInformation(BaseModel):
    """28 Fields for Event Information"""
    
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
        """Returns list of fields that are still 'Not specified'"""
        important_fields = [
            "event_date", "name", "start_time", "end_time",
            "preferred_room", "number_of_participants", "type_of_event"
        ]
        missing = []
        for field in important_fields:
            value = getattr(self, field)
            if value == "Not specified" or value is None:
                missing.append(field)
        return missing
    
    def is_complete(self) -> bool:
        """Check if all essential fields are filled"""
        # MINIMUM required fields - be less strict
        critical_fields = [
            "event_date", "name", "email", "phone", 
            "preferred_room", "number_of_participants", 
            "billing_address"
        ]
        
        print(f"\n=== IS_COMPLETE CHECK (RELAXED) ===")
        for field in critical_fields:
            value = getattr(self, field)
            is_valid = not (value == "Not specified" or value is None or value == "")
            print(f"{field}: '{value}' → {'✅' if is_valid else '❌'}")
        
        # Check critical fields only
        for field in critical_fields:
            value = getattr(self, field)
            if value == "Not specified" or value is None or value == "":
                print(f"❌ FAILED: {field}")
                print(f"===================================\n")
                return False
        
        # Relaxed catering check - just needs something
        if (self.catering_preference == "Not specified" or 
            self.catering_preference is None or 
            len(self.catering_preference) < 5):
            print(f"❌ FAILED: catering_preference")
            print(f"===================================\n")
            return False
        
        print(f"✅ ALL CRITICAL CHECKS PASSED!")
        print(f"===================================\n")
        return True
        
    def to_dict(self):
        """Convert to dictionary for JSON export - exclude room status fields"""
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
            # Room status fields removed - only preferred room is saved
            "Billing Amount": self.billing_amount,
            "Deposit": self.deposit,
            "Language": self.language,
            "Additional Info": self.additional_info
    }

class ConversationState(BaseModel):
    """Tracks the conversation state"""
    session_id: str
    event_info: EventInformation
    conversation_history: list[dict]  # [{"role": "user/assistant", "content": "..."}]
    workflow_type: Optional[str] = None  # 'new_event', 'update', 'follow_up', 'other'
    is_complete: bool = False
    created_at: datetime = datetime.now()