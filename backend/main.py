from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uuid
import json
from datetime import datetime
from models import EventInformation, ConversationState
from conversation_manager import (
    classify_email, generate_response, create_summary,
    active_conversations
)
from pathlib import Path

app = FastAPI(title="AI Event Manager")

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# CENTRALIZED EVENTS DATABASE
EVENTS_FILE = "events_database.json"

def load_events_database():
    """Load all events from the database file"""
    if Path(EVENTS_FILE).exists():
        with open(EVENTS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"events": []}

def save_events_database(database):
    """Save all events to the database file"""
    with open(EVENTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(database, f, indent=2, ensure_ascii=False)

# REQUEST/RESPONSE MODELS
class StartConversationRequest(BaseModel):
    email_body: str
    client_email: str

class SendMessageRequest(BaseModel):
    session_id: str
    message: str

class ConversationResponse(BaseModel):
    session_id: str
    workflow_type: str
    response: str
    is_complete: bool
    event_info: dict

# ENDPOINTS

@app.post("/api/start-conversation")
async def start_conversation(request: StartConversationRequest):
    """
    Start a new conversation - classify email and generate first response
    """
    
    # Classify the email
    workflow_type = classify_email(request.email_body)
    
    # Handle different workflow types
    if workflow_type == "update":
        return {
            "session_id": None,
            "workflow_type": workflow_type,
            "response": "This appears to be a request to update an existing booking. This feature is coming soon! For now, please contact us directly at info@theatelier.ch to modify your booking.",
            "is_complete": False,
            "event_info": None
        }
    
    elif workflow_type == "follow_up":
        return {
            "session_id": None,
            "workflow_type": workflow_type,
            "response": "Thank you for your follow-up message! This feature is under development. For immediate assistance, please email us at info@theatelier.ch",
            "is_complete": False,
            "event_info": None
        }
    
    elif workflow_type == "other":
        return {
            "session_id": None,
            "workflow_type": workflow_type,
            "response": "Thank you for your message. However, this doesn't appear to be a new event booking request. I specialize in processing new venue bookings. For other inquiries, please contact our team at info@theatelier.ch",
            "is_complete": False,
            "event_info": None
        }
    
    # Only proceed if it's a new event
    if workflow_type != "new_event":
        return {
            "session_id": None,
            "workflow_type": workflow_type,
            "response": "I apologize, but I can only process new event booking requests at this time. For other matters, please reach out to info@theatelier.ch",
            "is_complete": False,
            "event_info": None
        }
    
    # Create new conversation for new_event
    session_id = str(uuid.uuid4())
    
    event_info = EventInformation(
        date_email_received=datetime.now().strftime("%d.%m.%Y"),
        email=request.client_email
    )
    
    conversation_state = ConversationState(
        session_id=session_id,
        event_info=event_info,
        conversation_history=[],
        workflow_type=workflow_type
    )
    
    # Generate first response
    response_text = generate_response(conversation_state, request.email_body)
    
    # Store in memory
    active_conversations[session_id] = conversation_state
    
    return {
        "session_id": session_id,
        "workflow_type": workflow_type,
        "response": response_text,
        "is_complete": conversation_state.is_complete,
        "event_info": conversation_state.event_info.model_dump()
    }

@app.post("/api/send-message")
async def send_message(request: SendMessageRequest):
    """
    Continue conversation - send user message and get AI response
    """
    
    # Get conversation state
    if request.session_id not in active_conversations:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    conversation_state = active_conversations[request.session_id]
    
    # Generate response (handles all logic internally)
    response_text = generate_response(conversation_state, request.message)
    
    # DEBUG LOGGING
    print(f"\n=== DEBUG INFO ===")
    print(f"User message: {request.message}")
    print(f"Is complete: {conversation_state.is_complete}")
    print(f"Event info complete: {conversation_state.event_info.is_complete()}")
    print(f"==================\n")
    
    # Return response
    return {
        "session_id": request.session_id,
        "workflow_type": conversation_state.workflow_type,
        "response": response_text,
        "is_complete": conversation_state.is_complete,  # This MUST be True when client accepts
        "event_info": conversation_state.event_info.dict()
    }

@app.post("/api/accept-booking/{session_id}")
async def accept_booking(session_id: str):
    """
    User accepts the collected information - save to centralized JSON database
    """
    
    if session_id not in active_conversations:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    conversation_state = active_conversations[session_id]
    
    # Load existing database
    database = load_events_database()
    
    # Add new event with unique ID and timestamp
    event_entry = {
        "event_id": session_id,
        "created_at": datetime.now().isoformat(),
        "event_data": conversation_state.event_info.to_dict()
    }
    
    database["events"].append(event_entry)
    
    # Save back to file
    save_events_database(database)
    
    # Clean up conversation
    del active_conversations[session_id]
    
    return {
        "message": "Booking accepted and saved",
        "filename": EVENTS_FILE,
        "event_id": session_id,
        "total_events": len(database["events"]),
        "event_info": conversation_state.event_info.to_dict()
    }

@app.post("/api/reject-booking/{session_id}")
async def reject_booking(session_id: str):
    """
    User rejects - discard conversation without saving
    """
    
    if session_id not in active_conversations:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    # Just remove from memory
    del active_conversations[session_id]
    
    return {"message": "Booking rejected and discarded"}

@app.get("/api/conversation/{session_id}")
async def get_conversation(session_id: str):
    """
    Get current conversation state
    """
    
    if session_id not in active_conversations:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    conversation_state = active_conversations[session_id]
    
    return {
        "session_id": session_id,
        "conversation_history": conversation_state.conversation_history,
        "event_info": conversation_state.event_info.dict(),
        "is_complete": conversation_state.is_complete
    }

@app.get("/api/events")
async def get_all_events():
    """
    Get all saved events from database
    """
    database = load_events_database()
    return {
        "total_events": len(database["events"]),
        "events": database["events"]
    }

@app.get("/api/events/{event_id}")
async def get_event_by_id(event_id: str):
    """
    Get a specific event by ID
    """
    database = load_events_database()
    
    for event in database["events"]:
        if event["event_id"] == event_id:
            return event
    
    raise HTTPException(status_code=404, detail="Event not found")

@app.get("/")
async def root():
    database = load_events_database()
    return {
        "status": "AI Event Manager Running",
        "active_conversations": len(active_conversations),
        "total_saved_events": len(database["events"])
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)