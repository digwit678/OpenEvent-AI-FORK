# Test Pages & Links Integration Implementation Plan

## Overview
This document outlines the implementation of actual test pages for displaying detailed information about rooms, catering menus, and Q&A topics. These pages will serve raw data that the LLM verbalizer can reference, summarize, and reason about in chat messages.

## Architecture Overview

### Data Flow
1. **Chat shows LLM reasoning**: The verbalizer summarizes and compares options
2. **Links provide raw data**: Test pages display complete tables and detailed information
3. **User experience**: Users get concise summaries in chat with links to full details

### Key Benefits
- Test the complete user experience before platform integration
- Verify the verbalizer properly summarizes detailed information
- Easy to replace test pages with production URLs later
- Clear separation between raw data (pages) and reasoning (chat)

## Implementation Tasks

### Task 1: Create Backend API Endpoints for Test Data
**Location**: `/backend/main.py` (add new endpoints)

```python
@app.get("/api/test-data/rooms")
async def get_rooms_data(date: Optional[str] = None, capacity: Optional[int] = None):
    """Serve room availability data for test pages."""
    # Load room data from ROOM_CATALOG
    # Apply date/capacity filters if provided
    # Return detailed room information

@app.get("/api/test-data/catering")
async def get_catering_data(room: Optional[str] = None, date: Optional[str] = None):
    """Serve catering menu data for test pages."""
    # Load catering options from DINNER_MENU_OPTIONS
    # Filter by room compatibility if provided
    # Return detailed menu information

@app.get("/api/test-data/qna")
async def get_qna_data(category: Optional[str] = None):
    """Serve Q&A data for test pages."""
    # Load Q&A responses from knowledge base
    # Filter by category if provided
    # Return structured Q&A information
```

### Task 2: Create Test Pages in Frontend
**Location**: `/atelier-ai-frontend/app/info/` (new directory)

#### a) Room Availability Page
**File**: `/atelier-ai-frontend/app/info/rooms/page.tsx`

```tsx
'use client'

import { useSearchParams } from 'next/navigation'
import { useEffect, useState } from 'react'

interface Room {
  name: string
  capacity: number
  features: string[]
  status: 'Available' | 'Option' | 'Unavailable'
  price: number
  description: string
  equipment: string[]
  layout_options: string[]
}

export default function RoomsPage() {
  const searchParams = useSearchParams()
  const date = searchParams.get('date')
  const capacity = searchParams.get('capacity')
  const [rooms, setRooms] = useState<Room[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch(`/api/test-data/rooms?date=${date || ''}&capacity=${capacity || ''}`)
      .then(res => res.json())
      .then(data => {
        setRooms(data)
        setLoading(false)
      })
  }, [date, capacity])

  return (
    <div className="container mx-auto p-8">
      <h1 className="text-3xl font-bold mb-6">Room Availability</h1>

      {date && (
        <div className="mb-4 text-gray-600">
          Showing rooms available on: <strong>{date}</strong>
        </div>
      )}

      {capacity && (
        <div className="mb-4 text-gray-600">
          For <strong>{capacity}</strong> participants
        </div>
      )}

      {loading ? (
        <div>Loading...</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full bg-white border border-gray-200">
            <thead className="bg-gray-100">
              <tr>
                <th className="px-6 py-3 text-left">Room</th>
                <th className="px-6 py-3 text-left">Capacity</th>
                <th className="px-6 py-3 text-left">Status</th>
                <th className="px-6 py-3 text-left">Features</th>
                <th className="px-6 py-3 text-left">Equipment</th>
                <th className="px-6 py-3 text-left">Layout Options</th>
                <th className="px-6 py-3 text-right">Price (CHF)</th>
              </tr>
            </thead>
            <tbody>
              {rooms.map((room, idx) => (
                <tr key={idx} className="border-t">
                  <td className="px-6 py-4 font-medium">{room.name}</td>
                  <td className="px-6 py-4">{room.capacity}</td>
                  <td className="px-6 py-4">
                    <span className={`px-2 py-1 rounded text-sm ${
                      room.status === 'Available' ? 'bg-green-100 text-green-800' :
                      room.status === 'Option' ? 'bg-yellow-100 text-yellow-800' :
                      'bg-red-100 text-red-800'
                    }`}>
                      {room.status}
                    </span>
                  </td>
                  <td className="px-6 py-4">{room.features.join(', ')}</td>
                  <td className="px-6 py-4">{room.equipment.join(', ')}</td>
                  <td className="px-6 py-4">{room.layout_options.join(', ')}</td>
                  <td className="px-6 py-4 text-right">{room.price.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className="mt-8 space-y-4">
            <h2 className="text-2xl font-semibold">Room Details</h2>
            {rooms.map((room, idx) => (
              <div key={idx} className="border rounded-lg p-6">
                <h3 className="text-xl font-semibold mb-2">{room.name}</h3>
                <p className="text-gray-700">{room.description}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
```

#### b) Catering Menus Page
**File**: `/atelier-ai-frontend/app/info/catering/[menu]/page.tsx`

```tsx
'use client'

import { useParams, useSearchParams } from 'next/navigation'
import { useEffect, useState } from 'react'

interface MenuItem {
  course: string
  description: string
  dietary: string[]
  allergens: string[]
}

interface Menu {
  name: string
  price_per_person: number
  courses: MenuItem[]
  beverages_included: string[]
  minimum_order: number
  description: string
}

export default function CateringMenuPage() {
  const params = useParams()
  const searchParams = useSearchParams()
  const menuSlug = params.menu as string
  const room = searchParams.get('room')
  const date = searchParams.get('date')
  const [menu, setMenu] = useState<Menu | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch(`/api/test-data/catering/${menuSlug}?room=${room || ''}&date=${date || ''}`)
      .then(res => res.json())
      .then(data => {
        setMenu(data)
        setLoading(false)
      })
  }, [menuSlug, room, date])

  if (loading) return <div className="p-8">Loading...</div>
  if (!menu) return <div className="p-8">Menu not found</div>

  return (
    <div className="container mx-auto p-8">
      <h1 className="text-3xl font-bold mb-2">{menu.name}</h1>
      <div className="text-xl text-gray-600 mb-6">
        CHF {menu.price_per_person} per person
        {menu.minimum_order > 1 && ` (minimum ${menu.minimum_order} persons)`}
      </div>

      {(room || date) && (
        <div className="mb-6 p-4 bg-blue-50 rounded">
          {room && <div>Selected room: <strong>{room}</strong></div>}
          {date && <div>Event date: <strong>{date}</strong></div>}
        </div>
      )}

      <div className="prose max-w-none mb-8">
        <p>{menu.description}</p>
      </div>

      <div className="space-y-8">
        <div>
          <h2 className="text-2xl font-semibold mb-4">Menu Courses</h2>
          <div className="space-y-4">
            {menu.courses.map((course, idx) => (
              <div key={idx} className="border rounded-lg p-4">
                <h3 className="font-semibold text-lg mb-2">{course.course}</h3>
                <p className="text-gray-700 mb-2">{course.description}</p>
                <div className="flex gap-4 text-sm">
                  {course.dietary.length > 0 && (
                    <div>
                      <span className="text-gray-500">Dietary: </span>
                      {course.dietary.map(d => (
                        <span key={d} className="inline-block px-2 py-1 bg-green-100 text-green-700 rounded mr-1">
                          {d}
                        </span>
                      ))}
                    </div>
                  )}
                  {course.allergens.length > 0 && (
                    <div>
                      <span className="text-gray-500">Allergens: </span>
                      {course.allergens.map(a => (
                        <span key={a} className="inline-block px-2 py-1 bg-orange-100 text-orange-700 rounded mr-1">
                          {a}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div>
          <h2 className="text-2xl font-semibold mb-4">Beverages Included</h2>
          <ul className="list-disc list-inside space-y-1">
            {menu.beverages_included.map((beverage, idx) => (
              <li key={idx}>{beverage}</li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  )
}
```

#### c) Q&A Information Page
**File**: `/atelier-ai-frontend/app/info/qna/page.tsx`

```tsx
'use client'

import { useSearchParams } from 'next/navigation'
import { useEffect, useState } from 'react'

interface QnAItem {
  category: string
  question: string
  answer: string
  related_links: { title: string; url: string }[]
}

export default function QnAPage() {
  const searchParams = useSearchParams()
  const category = searchParams.get('category')
  const [items, setItems] = useState<QnAItem[]>([])
  const [categories, setCategories] = useState<string[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch(`/api/test-data/qna${category ? `?category=${category}` : ''}`)
      .then(res => res.json())
      .then(data => {
        setItems(data.items)
        setCategories(data.categories)
        setLoading(false)
      })
  }, [category])

  return (
    <div className="container mx-auto p-8">
      <h1 className="text-3xl font-bold mb-6">Frequently Asked Questions</h1>

      <div className="flex gap-8">
        <aside className="w-64">
          <h2 className="text-xl font-semibold mb-4">Categories</h2>
          <ul className="space-y-2">
            <li>
              <a
                href="/info/qna"
                className={`block p-2 rounded ${!category ? 'bg-blue-100' : 'hover:bg-gray-100'}`}
              >
                All Questions
              </a>
            </li>
            {categories.map(cat => (
              <li key={cat}>
                <a
                  href={`/info/qna?category=${cat}`}
                  className={`block p-2 rounded ${category === cat ? 'bg-blue-100' : 'hover:bg-gray-100'}`}
                >
                  {cat}
                </a>
              </li>
            ))}
          </ul>
        </aside>

        <main className="flex-1">
          {loading ? (
            <div>Loading...</div>
          ) : (
            <div className="space-y-6">
              {items.map((item, idx) => (
                <div key={idx} className="border rounded-lg p-6">
                  <div className="text-sm text-gray-500 mb-2">{item.category}</div>
                  <h3 className="text-xl font-semibold mb-3">{item.question}</h3>
                  <div className="prose max-w-none mb-4">
                    <p>{item.answer}</p>
                  </div>
                  {item.related_links.length > 0 && (
                    <div className="mt-4 pt-4 border-t">
                      <h4 className="text-sm font-semibold text-gray-600 mb-2">Related Information</h4>
                      <ul className="space-y-1">
                        {item.related_links.map((link, linkIdx) => (
                          <li key={linkIdx}>
                            <a href={link.url} className="text-blue-600 hover:underline">
                              {link.title}
                            </a>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </main>
      </div>
    </div>
  )
}
```

### Task 3: Update Link Generation to Use Test Pages
**Location**: Update `/backend/utils/pseudolinks.py`

```python
"""
Link generator for room and catering options.
Now generates real links to test pages during development.
"""

import os
from urllib.parse import urlencode

# Get base URL from environment or use localhost
BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://localhost:3000")

def generate_room_details_link(room_name: str, date: str, participants: int = None) -> str:
    """Generate link to room availability page."""
    params = {"date": date}
    if participants:
        params["capacity"] = str(participants)
    query_string = urlencode(params)
    return f"[View all available rooms]({BASE_URL}/info/rooms?{query_string})"

def generate_catering_menu_link(menu_name: str, room: str = None, date: str = None) -> str:
    """Generate link to specific catering menu page."""
    params = {}
    if room:
        params["room"] = room
    if date:
        params["date"] = date

    menu_slug = menu_name.lower().replace(' ', '-')
    query_string = urlencode(params) if params else ""
    url = f"{BASE_URL}/info/catering/{menu_slug}"
    if query_string:
        url += f"?{query_string}"

    return f"[View {menu_name} details]({url})"

def generate_catering_catalog_link() -> str:
    """Generate link to catering catalog."""
    return f"[Browse all catering options]({BASE_URL}/info/catering)"

def generate_qna_link(category: str = None) -> str:
    """Generate link to Q&A page."""
    if category:
        params = urlencode({"category": category})
        return f"[View {category} information]({BASE_URL}/info/qna?{params})"
    return f"[View frequently asked questions]({BASE_URL}/info/qna)"

def generate_offer_preview_link(offer_id: str) -> str:
    """Generate link for offer preview."""
    # This could later be a PDF download or preview page
    return f"[Download offer PDF]({BASE_URL}/api/offers/{offer_id}/pdf)"
```

### Task 4: Create Backend Data Providers
**Location**: `/backend/utils/test_data_providers.py` (new file)

```python
"""
Data providers for test pages.
Serves structured data that test pages can display.
"""

from typing import Dict, Any, List, Optional
from backend.workflows.groups.room_availability.db_pers.constants import ROOM_CATALOG
from backend.workflows.groups.offer.db_pers.common.menu_options import DINNER_MENU_OPTIONS
from backend.workflows.io.database import load_db
import json

def get_rooms_for_display(date: Optional[str] = None, capacity: Optional[int] = None) -> List[Dict[str, Any]]:
    """Get detailed room information for display."""
    rooms = []

    # Load current database to check actual availability
    db = load_db()

    for room_name, room_data in ROOM_CATALOG.items():
        # Check availability if date provided
        status = "Available"
        if date:
            # Check calendar data for this room/date
            # This would integrate with existing room availability logic
            pass

        room_info = {
            "name": room_name,
            "capacity": room_data.get("capacity", 0),
            "status": status,
            "price": room_data.get("base_price", 0),
            "features": room_data.get("features", []),
            "equipment": room_data.get("equipment", []),
            "layout_options": room_data.get("layouts", []),
            "description": room_data.get("description", ""),
        }

        # Filter by capacity if provided
        if capacity and room_info["capacity"] < capacity:
            continue

        rooms.append(room_info)

    # Sort by capacity
    rooms.sort(key=lambda x: x["capacity"])
    return rooms

def get_catering_menu_details(menu_slug: str) -> Optional[Dict[str, Any]]:
    """Get detailed menu information."""
    # Convert slug back to menu name
    menu_name = menu_slug.replace('-', ' ').title()

    for menu in DINNER_MENU_OPTIONS:
        if menu.get("menu_name", "").lower().replace(' ', '-') == menu_slug:
            return {
                "name": menu.get("menu_name"),
                "price_per_person": menu.get("price"),
                "courses": [
                    {
                        "course": "Starter",
                        "description": menu.get("starter", ""),
                        "dietary": _extract_dietary_info(menu.get("starter", "")),
                        "allergens": _extract_allergens(menu.get("starter", "")),
                    },
                    {
                        "course": "Main Course",
                        "description": menu.get("main", ""),
                        "dietary": _extract_dietary_info(menu.get("main", "")),
                        "allergens": _extract_allergens(menu.get("main", "")),
                    },
                    {
                        "course": "Dessert",
                        "description": menu.get("dessert", ""),
                        "dietary": _extract_dietary_info(menu.get("dessert", "")),
                        "allergens": _extract_allergens(menu.get("dessert", "")),
                    }
                ],
                "beverages_included": menu.get("beverages", []),
                "minimum_order": menu.get("min_order", 10),
                "description": menu.get("description", ""),
            }
    return None

def get_qna_items(category: Optional[str] = None) -> Dict[str, Any]:
    """Get Q&A items, optionally filtered by category."""
    # This would load from a Q&A knowledge base
    # For now, return sample data
    all_items = [
        {
            "category": "Parking",
            "question": "Where can guests park?",
            "answer": "The Atelier offers underground parking with 50 spaces available for event guests. Additional street parking is available nearby. Parking vouchers can be arranged for your guests at CHF 5 per vehicle.",
            "related_links": [
                {"title": "Parking map", "url": "/info/parking-map"},
                {"title": "Public transport options", "url": "/info/transport"},
            ]
        },
        {
            "category": "Parking",
            "question": "Is there disabled parking available?",
            "answer": "Yes, we have 3 designated disabled parking spaces near the main entrance with level access to all event spaces.",
            "related_links": []
        },
        {
            "category": "Catering",
            "question": "Can you accommodate dietary restrictions?",
            "answer": "Absolutely! All our menus can be adapted for vegetarian, vegan, gluten-free, and other dietary requirements. Please inform us of any restrictions when booking.",
            "related_links": [
                {"title": "View catering options", "url": "/info/catering"},
            ]
        },
        {
            "category": "Booking",
            "question": "How far in advance should I book?",
            "answer": "We recommend booking at least 4 weeks in advance for the best availability. For peak seasons (May-June, September-October), 6-8 weeks advance booking is advisable.",
            "related_links": [
                {"title": "Check availability", "url": "/info/rooms"},
            ]
        },
    ]

    categories = sorted(list(set(item["category"] for item in all_items)))

    if category:
        items = [item for item in all_items if item["category"] == category]
    else:
        items = all_items

    return {
        "items": items,
        "categories": categories,
    }

def _extract_dietary_info(text: str) -> List[str]:
    """Extract dietary information from menu text."""
    dietary = []
    if "vegetarian" in text.lower():
        dietary.append("Vegetarian")
    if "vegan" in text.lower():
        dietary.append("Vegan")
    if "gluten-free" in text.lower():
        dietary.append("Gluten-Free")
    return dietary

def _extract_allergens(text: str) -> List[str]:
    """Extract allergen information from menu text."""
    # This would use more sophisticated parsing in production
    return []
```

### Task 5: Integration with Workflow Messages

Update the verbalizer messages to include the working links:

#### Step 3 - Room Availability
```python
# In room availability message composition:
room_link = generate_room_details_link(
    room_name="all",  # Show all rooms
    date=event_entry.get("chosen_date"),
    participants=event_entry.get("number_of_participants")
)

message = f"""
I've checked room availability for your event on {date}.

{room_link}

Based on your requirements for {participants} guests, I'd recommend **Room A** - it's perfectly sized
and includes the projector you need. Room B is also available if you'd prefer more space.

Would you like me to reserve Room A for you?
"""
```

#### Step 4 - Offer Composition
```python
# In offer summary:
catering_catalog_link = generate_catering_catalog_link()
room_link = generate_room_details_link(
    room_name=locked_room,
    date=chosen_date,
    participants=participants
)

message = f"""
Here's your offer for {date}:

**Venue**: {locked_room} ({participants} guests)
{room_link}

**Catering Options**:
{catering_catalog_link}

We have several menus that would work beautifully for your event:
- Seasonal Garden Trio (vegetarian) - CHF 92 pp
- Swiss Alpine Experience - CHF 110 pp
- Mediterranean Feast - CHF 98 pp

Would you like me to include one of these in your offer?
"""
```

## Testing Instructions

### Local Development Testing

1. **Start the backend**:
   ```bash
   cd /Users/nico/PycharmProjects/OpenEvent-AI
   uvicorn backend.main:app --reload --port 8000
   ```

2. **Start the frontend**:
   ```bash
   cd atelier-ai-frontend
   npm run dev
   ```

3. **Test the pages directly**:
   - Room availability: http://localhost:3000/info/rooms?date=2025-12-15&capacity=30
   - Catering menu: http://localhost:3000/info/catering/seasonal-garden-trio?room=Room+A
   - Q&A: http://localhost:3000/info/qna?category=Parking

4. **Test through workflow**:
   - Start a new conversation
   - Confirm a date
   - When room options are presented, click the link
   - Verify the test page shows correct data
   - Return to chat and select a room
   - When offer is presented, click catering links
   - Verify menu details are shown correctly

### What to Verify

1. **Links are generated correctly** with proper parameters
2. **Test pages load** and display data based on parameters
3. **Data matches** between chat summary and detailed pages
4. **Navigation works** - users can go to pages and return to chat
5. **Verbalizer properly summarizes** the detailed information

## Migration to Production

When ready for production:

1. **Replace test page routes** with actual platform URLs
2. **Update API endpoints** to use production data sources
3. **Add authentication** to protect data endpoints
4. **Style pages** to match OpenEvent platform design
5. **Add caching** for frequently accessed data

## Benefits of This Approach

1. **Complete testing**: Test the full user experience with working links
2. **Clear separation**: Raw data (pages) vs. reasoning (chat)
3. **Easy migration**: Just update URLs when platform is ready
4. **Better UX**: Users can see both summary and details
5. **Verbalizer validation**: Ensure LLM properly summarizes complex data

## Implementation Priority

1. **High Priority**:
   - Create test data provider functions
   - Build room availability page
   - Update Step 3 messages with working links

2. **Medium Priority**:
   - Build catering menu pages
   - Update Step 4 messages with links
   - Add Q&A page for common questions

3. **Low Priority**:
   - Style test pages nicely
   - Add more sophisticated filtering
   - Create PDF preview functionality