import json
import os
import asyncio
import uuid
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client
import sys
from pathlib import Path

# Add project root to path to import modules
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from workflows.io.integration.status_utils import event_status_to_supabase

load_dotenv()

# Configuration
JSON_DB_PATH = "events_team-shami.json"
SUPABASE_URL = os.getenv("OE_SUPABASE_URL")
SUPABASE_KEY = os.getenv("OE_SUPABASE_KEY")
TEAM_ID = os.getenv("OE_TEAM_ID")
SYSTEM_USER_ID = os.getenv("OE_SYSTEM_USER_ID")

if not all([SUPABASE_URL, SUPABASE_KEY, TEAM_ID, SYSTEM_USER_ID]):
    print("Error: Missing required environment variables (OE_SUPABASE_URL, OE_SUPABASE_KEY, OE_TEAM_ID, OE_SYSTEM_USER_ID)")
    exit(1)

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def load_json_db():
    try:
        with open(JSON_DB_PATH, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: Database file '{JSON_DB_PATH}' not found.")
        exit(1)

def get_or_create_client(client_data):
    email = client_data.get("Email")
    if not email or email == "Not specified":
        print(f"Skipping client with no email: {client_data.get('Name')}")
        return None

    # Check if exists
    res = supabase.table("clients").select("id").eq("email", email).eq("team_id", TEAM_ID).execute()
    if res.data:
        return res.data[0]["id"]

    # Create new
    print(f"Creating client: {email}")
    new_client = {
        "team_id": TEAM_ID,
        "user_id": SYSTEM_USER_ID,
        "email": email,
        "name": client_data.get("Name", "Unknown"),
        "company": client_data.get("Company"),
        "phone": client_data.get("Phone"),
        "status": "lead",
        "created_at": datetime.now().isoformat()
    }
    
    # Remove None/Empty values
    new_client = {k: v for k, v in new_client.items() if v}

    try:
        res = supabase.table("clients").insert(new_client).execute()
        return res.data[0]["id"]
    except Exception as e:
        print(f"Error creating client {email}: {e}")
        return None

def migrate_event(event_record):
    event_data = event_record.get("event_data", {})
    email = event_data.get("Email")
    
    if not email:
        print("Skipping event with no email")
        return

    # 1. Get/Create Client
    client_id = get_or_create_client(event_data)
    if not client_id:
        return

    # 2. Check if event exists (by client + date)
    event_date_str = event_data.get("Event Date")
    event_date_iso = None
    if event_date_str and event_date_str != "Not specified":
        try:
            # Try DD.MM.YYYY
            dt = datetime.strptime(event_date_str, "%d.%m.%Y")
            event_date_iso = dt.strftime("%Y-%m-%d")
        except ValueError:
            pass

    if event_date_iso:
        # Check for existing event on this date for this client
        res = supabase.table("events")\
            .select("id")\
            .eq("client_id", client_id)\
            .eq("event_date", event_date_iso)\
            .eq("team_id", TEAM_ID)\
            .execute()
        
        if res.data:
            print(f"Event already exists for {email} on {event_date_iso}. Skipping.")
            return

    # 3. Create Event
    print(f"Creating event for {email} on {event_date_iso or 'TBD'}")
    
    status = event_status_to_supabase(event_record.get("status", "Lead"))
    
    new_event = {
        "team_id": TEAM_ID,
        "user_id": SYSTEM_USER_ID,
        "client_id": client_id,
        "status": status,
        "title": event_data.get("Type of Event") or "Untitled Event",
        "description": event_data.get("Additional Info"),
        "event_date": event_date_iso,
        "start_time": event_data.get("Start Time") if event_data.get("Start Time") != "Not specified" else None,
        "end_time": event_data.get("End Time") if event_data.get("End Time") != "Not specified" else None,
        "attendees": int(event_data.get("Number of Participants")) if str(event_data.get("Number of Participants")).isdigit() else None,
        "created_at": event_record.get("created_at") or datetime.now().isoformat()
    }

    # Remove None values
    new_event = {k: v for k, v in new_event.items() if v is not None}

    try:
        supabase.table("events").insert(new_event).execute()
        print(" -> Event created successfully")
    except Exception as e:
        print(f" -> Error creating event: {e}")

def main():
    print("Starting migration...")
    db = load_json_db()
    events = db.get("events", [])
    print(f"Found {len(events)} events in JSON.")

    for event in events:
        migrate_event(event)

    print("Migration complete.")

if __name__ == "__main__":
    main()
