# Implementation Guide for Junior Developer

## Your Mission
Implement working test pages and calendar event integration for the OpenEvent-AI system. This will allow users to click links in chat messages to see detailed information about rooms, catering options, and Q&A topics.

## Overview of What You're Building

### The User Experience Flow
1. User chats with the AI assistant about booking an event
2. AI provides summaries with links like "View all available rooms"
3. User clicks the link → Opens a new tab with detailed room information
4. User returns to chat and makes their selection
5. Behind the scenes, calendar events are created/updated as the booking progresses

### Two Main Features to Implement

1. **Test Pages with Working Links**
   - Create web pages that show detailed room/catering/Q&A data
   - Update chat messages to include working links to these pages
   - Links pass parameters (date, capacity, room) to filter the data

2. **Calendar Event Integration**
   - Create calendar events when a new booking starts (Lead status)
   - Update events when dates are confirmed
   - Track status changes (Lead → Option → Confirmed)

## Step-by-Step Implementation Guide

### Phase 1: Backend Setup (Start Here)

#### Step 1.1: Create the Link Generator Utility
Create new file: `/backend/utils/pseudolinks.py`

```python
"""
Link generator for room and catering options.
Generates real links to test pages during development.
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
    return f"[Download offer PDF]({BASE_URL}/api/offers/{offer_id}/pdf)"
```

#### Step 1.2: Create Test Data Provider
Create new file: `/backend/utils/test_data_providers.py`

```python
"""
Data providers for test pages.
Serves structured data that test pages can display.
"""

from typing import Dict, Any, List, Optional
from backend.workflows.groups.room_availability.db_pers.constants import ROOM_CATALOG
from backend.workflows.groups.offer.db_pers.common.menu_options import DINNER_MENU_OPTIONS

def get_rooms_for_display(date: Optional[str] = None, capacity: Optional[int] = None) -> List[Dict[str, Any]]:
    """Get detailed room information for display."""
    rooms = []

    # Define room details (extend ROOM_CATALOG data)
    room_details = {
        "Room A": {
            "capacity": 40,
            "price": 500,
            "features": ["Natural light", "Projector", "Sound system", "Whiteboard"],
            "equipment": ["WiFi", "Video conferencing", "Flipchart", "Markers"],
            "layout_options": ["Boardroom", "U-shape", "Theater", "Classroom"],
            "description": "Our intimate Room A is perfect for focused meetings and workshops. With abundant natural light and state-of-the-art presentation equipment, it creates an ideal environment for groups up to 40 participants.",
        },
        "Room B": {
            "capacity": 80,
            "price": 800,
            "features": ["Stage area", "Projector", "Professional lighting", "Sound system"],
            "equipment": ["WiFi", "Video conferencing", "Microphones", "Recording capability"],
            "layout_options": ["Theater", "Banquet", "Cocktail", "Classroom"],
            "description": "Room B offers a spacious setting with a built-in stage, perfect for presentations, seminars, and social events. The flexible layout accommodates up to 80 guests in various configurations.",
        },
        "Room C": {
            "capacity": 120,
            "price": 1200,
            "features": ["Divisible space", "Multiple projectors", "Surround sound", "Bar area"],
            "equipment": ["WiFi", "Video walls", "Wireless mics", "Live streaming"],
            "layout_options": ["Theater", "Banquet", "Exhibition", "Mixed zones"],
            "description": "Our flagship Room C is a versatile space that can be divided into smaller sections or used as one grand venue. With premium audiovisual capabilities and an integrated bar, it's ideal for conferences, galas, and large gatherings.",
        },
        "Punkt.Null": {
            "capacity": 150,
            "price": 1500,
            "features": ["Industrial design", "High ceilings", "Natural light", "Outdoor terrace"],
            "equipment": ["WiFi", "Modular stage", "Concert-grade sound", "Lighting rig"],
            "layout_options": ["Standing reception", "Mixed seating", "Lounge style", "Dance floor"],
            "description": "Punkt.Null is our unique industrial-chic space featuring soaring ceilings, exposed beams, and direct terrace access. This atmospheric venue is perfect for creative events, product launches, and memorable celebrations.",
        }
    }

    for room_name, details in room_details.items():
        # For now, all rooms are available (in production, check calendar)
        status = "Available"

        room_info = {
            "name": room_name,
            "capacity": details["capacity"],
            "status": status,
            "price": details["price"],
            "features": details["features"],
            "equipment": details["equipment"],
            "layout_options": details["layout_options"],
            "description": details["description"],
        }

        # Filter by capacity if provided
        if capacity and room_info["capacity"] < int(capacity):
            continue

        rooms.append(room_info)

    # Sort by capacity
    rooms.sort(key=lambda x: x["capacity"])
    return rooms

def get_all_catering_menus() -> List[Dict[str, Any]]:
    """Get all catering menus for catalog display."""
    menus = []
    for menu in DINNER_MENU_OPTIONS:
        menu_slug = menu.get("menu_name", "").lower().replace(' ', '-')
        menus.append({
            "name": menu.get("menu_name"),
            "slug": menu_slug,
            "price_per_person": menu.get("price"),
            "summary": menu.get("description", ""),
            "dietary_options": _extract_dietary_info(str(menu)),
        })
    return menus

def get_catering_menu_details(menu_slug: str) -> Optional[Dict[str, Any]]:
    """Get detailed menu information."""
    # Find the menu by slug
    for menu in DINNER_MENU_OPTIONS:
        if menu.get("menu_name", "").lower().replace(' ', '-') == menu_slug:
            return {
                "name": menu.get("menu_name"),
                "slug": menu_slug,
                "price_per_person": menu.get("price"),
                "courses": [
                    {
                        "course": "Starter",
                        "description": menu.get("starter", ""),
                        "dietary": _extract_dietary_info(menu.get("starter", "")),
                        "allergens": [],  # Would extract in production
                    },
                    {
                        "course": "Main Course",
                        "description": menu.get("main", ""),
                        "dietary": _extract_dietary_info(menu.get("main", "")),
                        "allergens": [],
                    },
                    {
                        "course": "Dessert",
                        "description": menu.get("dessert", ""),
                        "dietary": _extract_dietary_info(menu.get("dessert", "")),
                        "allergens": [],
                    }
                ],
                "beverages_included": menu.get("beverages", ["House wine selection", "Soft drinks", "Coffee & tea"]),
                "minimum_order": menu.get("min_order", 10),
                "description": menu.get("description", "A delightful culinary experience for your event."),
            }
    return None

def get_qna_items(category: Optional[str] = None) -> Dict[str, Any]:
    """Get Q&A items, optionally filtered by category."""
    all_items = [
        {
            "category": "Parking",
            "question": "Where can guests park?",
            "answer": "The Atelier offers underground parking with 50 spaces available for event guests. Additional street parking is available nearby. Parking vouchers can be arranged for your guests at CHF 5 per vehicle for the full event duration.",
            "related_links": []
        },
        {
            "category": "Parking",
            "question": "Is there disabled parking available?",
            "answer": "Yes, we have 3 designated disabled parking spaces directly at the main entrance with level access to all event spaces. These spaces are wider than standard spots and connect to our accessible routes throughout the venue.",
            "related_links": []
        },
        {
            "category": "Parking",
            "question": "Can we reserve parking spaces for VIP guests?",
            "answer": "Absolutely! We can reserve specific parking spaces closest to the entrance for your VIP guests. Please let us know how many VIP spaces you need when finalizing your booking.",
            "related_links": []
        },
        {
            "category": "Catering",
            "question": "Can you accommodate dietary restrictions?",
            "answer": "Absolutely! All our menus can be adapted for vegetarian, vegan, gluten-free, and other dietary requirements. Our chef team is experienced in handling allergies and religious dietary needs. Please inform us of any restrictions when booking, and we'll create appropriate alternatives.",
            "related_links": []
        },
        {
            "category": "Catering",
            "question": "Can we bring our own catering?",
            "answer": "While we prefer to use our in-house catering team who know our facilities best, we can accommodate external catering for special circumstances. A kitchen usage fee of CHF 500 applies, and external caterers must provide food safety certification.",
            "related_links": []
        },
        {
            "category": "Booking",
            "question": "How far in advance should I book?",
            "answer": "We recommend booking at least 4 weeks in advance for the best availability. For peak seasons (May-June, September-October, and December), 6-8 weeks advance booking is advisable. We can sometimes accommodate last-minute requests, so always feel free to ask!",
            "related_links": []
        },
        {
            "category": "Booking",
            "question": "What's your cancellation policy?",
            "answer": "Cancellations made more than 30 days before the event: Full refund minus CHF 200 admin fee. 14-30 days: 50% refund. Less than 14 days: No refund, but we'll try to reschedule if possible. We strongly recommend event insurance for large bookings.",
            "related_links": []
        },
        {
            "category": "Equipment",
            "question": "What AV equipment is included?",
            "answer": "All rooms include: HD projector or LED screen, wireless microphones, sound system, WiFi, and basic lighting. Additional equipment like recording devices, live streaming setup, or special lighting can be arranged for an extra fee.",
            "related_links": []
        },
        {
            "category": "Equipment",
            "question": "Can we live stream our event?",
            "answer": "Yes! Rooms B, C, and Punkt.Null are equipped with live streaming capabilities. We provide the technical setup and can assign a technician to manage the stream. Streaming to up to 500 viewers is included; larger audiences require upgraded bandwidth.",
            "related_links": []
        },
        {
            "category": "Access",
            "question": "Is the venue wheelchair accessible?",
            "answer": "Yes, The Atelier is fully wheelchair accessible. We have ramps to all entrances, an elevator to all floors, accessible restrooms on each level, and adjustable-height presentation equipment. Please let us know about any specific accessibility needs.",
            "related_links": []
        },
        {
            "category": "Access",
            "question": "How early can we access the venue for setup?",
            "answer": "Standard bookings include 1 hour setup time. For elaborate setups, we can arrange early access from 2-4 hours before your event start time for an additional CHF 100 per hour. Our team can also assist with setup if needed.",
            "related_links": []
        }
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
    """Extract dietary information from text."""
    dietary = []
    text_lower = text.lower()
    if "vegetarian" in text_lower:
        dietary.append("Vegetarian")
    if "vegan" in text_lower:
        dietary.append("Vegan")
    if "gluten-free" in text_lower or "gluten free" in text_lower:
        dietary.append("Gluten-Free")
    return dietary
```

#### Step 1.3: Add API Endpoints
Add to `/backend/main.py` (after the existing endpoints, around line 950):

```python
from backend.utils.test_data_providers import (
    get_rooms_for_display,
    get_all_catering_menus,
    get_catering_menu_details,
    get_qna_items
)

# Test data endpoints for development pages
@app.get("/api/test-data/rooms")
async def get_rooms_data(date: Optional[str] = None, capacity: Optional[str] = None):
    """Serve room availability data for test pages."""
    rooms = get_rooms_for_display(date, capacity)
    return rooms

@app.get("/api/test-data/catering")
async def get_catering_catalog():
    """Serve all catering menus for catalog page."""
    menus = get_all_catering_menus()
    return menus

@app.get("/api/test-data/catering/{menu_slug}")
async def get_catering_data(menu_slug: str, room: Optional[str] = None, date: Optional[str] = None):
    """Serve specific catering menu data for test pages."""
    menu = get_catering_menu_details(menu_slug)
    if not menu:
        raise HTTPException(status_code=404, detail="Menu not found")

    # Add context if room/date provided
    menu["context"] = {
        "room": room,
        "date": date
    }
    return menu

@app.get("/api/test-data/qna")
async def get_qna_data(category: Optional[str] = None):
    """Serve Q&A data for test pages."""
    return get_qna_items(category)
```

### Phase 2: Frontend Pages

#### Step 2.1: Create Info Directory Structure
Create these directories:
```
atelier-ai-frontend/
  app/
    info/
      rooms/
        page.tsx
      catering/
        page.tsx
        [menu]/
          page.tsx
      qna/
        page.tsx
```

#### Step 2.2: Create Room Availability Page
Create `/atelier-ai-frontend/app/info/rooms/page.tsx`:

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
    const params = new URLSearchParams()
    if (date) params.append('date', date)
    if (capacity) params.append('capacity', capacity)

    fetch(`http://localhost:8000/api/test-data/rooms?${params}`)
      .then(res => res.json())
      .then(data => {
        setRooms(data)
        setLoading(false)
      })
      .catch(err => {
        console.error('Failed to load rooms:', err)
        setLoading(false)
      })
  }, [date, capacity])

  if (loading) {
    return (
      <div className="container mx-auto p-8">
        <div className="text-center">Loading room information...</div>
      </div>
    )
  }

  return (
    <div className="container mx-auto p-8 max-w-7xl">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold mb-4">Room Availability at The Atelier</h1>

        {/* Context display */}
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-6">
          {date && (
            <div className="text-gray-700">
              <span className="font-semibold">Event Date:</span> {date}
            </div>
          )}
          {capacity && (
            <div className="text-gray-700">
              <span className="font-semibold">Required Capacity:</span> {capacity} participants
            </div>
          )}
          {!date && !capacity && (
            <div className="text-gray-700">Showing all available rooms</div>
          )}
        </div>
      </div>

      {/* Quick comparison table */}
      <div className="mb-12">
        <h2 className="text-2xl font-semibold mb-4">Quick Comparison</h2>
        <div className="overflow-x-auto shadow-lg rounded-lg">
          <table className="min-w-full bg-white">
            <thead className="bg-gray-100 border-b">
              <tr>
                <th className="px-6 py-4 text-left font-semibold">Room</th>
                <th className="px-6 py-4 text-center font-semibold">Capacity</th>
                <th className="px-6 py-4 text-center font-semibold">Status</th>
                <th className="px-6 py-4 text-left font-semibold">Key Features</th>
                <th className="px-6 py-4 text-left font-semibold">Layouts</th>
                <th className="px-6 py-4 text-right font-semibold">Price/Day</th>
              </tr>
            </thead>
            <tbody>
              {rooms.map((room, idx) => (
                <tr key={idx} className="border-b hover:bg-gray-50 transition-colors">
                  <td className="px-6 py-4 font-medium text-lg">{room.name}</td>
                  <td className="px-6 py-4 text-center">{room.capacity}</td>
                  <td className="px-6 py-4 text-center">
                    <span className={`inline-flex px-3 py-1 rounded-full text-sm font-medium ${
                      room.status === 'Available'
                        ? 'bg-green-100 text-green-800'
                        : room.status === 'Option'
                        ? 'bg-yellow-100 text-yellow-800'
                        : 'bg-red-100 text-red-800'
                    }`}>
                      {room.status}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-sm">
                    {room.features.slice(0, 3).join(' • ')}
                  </td>
                  <td className="px-6 py-4 text-sm text-gray-600">
                    {room.layout_options.slice(0, 2).join(', ')}
                    {room.layout_options.length > 2 && ' ...'}
                  </td>
                  <td className="px-6 py-4 text-right font-semibold">
                    CHF {room.price.toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Detailed room cards */}
      <div>
        <h2 className="text-2xl font-semibold mb-6">Detailed Room Information</h2>
        <div className="space-y-6">
          {rooms.map((room, idx) => (
            <div
              key={idx}
              className="border rounded-lg shadow-md hover:shadow-lg transition-shadow bg-white"
            >
              {/* Room header */}
              <div className="bg-gray-50 px-6 py-4 border-b">
                <div className="flex justify-between items-center">
                  <h3 className="text-xl font-bold">{room.name}</h3>
                  <div className="text-lg font-semibold text-gray-700">
                    CHF {room.price.toLocaleString()} per day
                  </div>
                </div>
              </div>

              {/* Room content */}
              <div className="p-6">
                <p className="text-gray-700 mb-6 leading-relaxed">
                  {room.description}
                </p>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                  {/* Features */}
                  <div>
                    <h4 className="font-semibold text-gray-900 mb-3">Features</h4>
                    <ul className="space-y-2">
                      {room.features.map((feature, fIdx) => (
                        <li key={fIdx} className="flex items-start">
                          <span className="text-green-500 mr-2">✓</span>
                          <span className="text-gray-700">{feature}</span>
                        </li>
                      ))}
                    </ul>
                  </div>

                  {/* Equipment */}
                  <div>
                    <h4 className="font-semibold text-gray-900 mb-3">Equipment</h4>
                    <ul className="space-y-2">
                      {room.equipment.map((item, eIdx) => (
                        <li key={eIdx} className="flex items-start">
                          <span className="text-blue-500 mr-2">•</span>
                          <span className="text-gray-700">{item}</span>
                        </li>
                      ))}
                    </ul>
                  </div>

                  {/* Layout Options */}
                  <div>
                    <h4 className="font-semibold text-gray-900 mb-3">Layout Options</h4>
                    <div className="space-y-2">
                      {room.layout_options.map((layout, lIdx) => (
                        <div
                          key={lIdx}
                          className="bg-gray-100 px-3 py-2 rounded text-gray-700"
                        >
                          {layout}
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Footer */}
      <div className="mt-12 text-center text-gray-600">
        <p>Return to your booking conversation to select a room</p>
      </div>
    </div>
  )
}
```

#### Step 2.3: Create Catering Catalog Page
Create `/atelier-ai-frontend/app/info/catering/page.tsx`:

```tsx
'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'

interface MenuSummary {
  name: string
  slug: string
  price_per_person: number
  summary: string
  dietary_options: string[]
}

export default function CateringCatalogPage() {
  const [menus, setMenus] = useState<MenuSummary[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch('http://localhost:8000/api/test-data/catering')
      .then(res => res.json())
      .then(data => {
        setMenus(data)
        setLoading(false)
      })
      .catch(err => {
        console.error('Failed to load menus:', err)
        setLoading(false)
      })
  }, [])

  if (loading) {
    return (
      <div className="container mx-auto p-8">
        <div className="text-center">Loading catering options...</div>
      </div>
    )
  }

  return (
    <div className="container mx-auto p-8 max-w-6xl">
      <h1 className="text-3xl font-bold mb-8">Catering Menu Options</h1>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {menus.map((menu) => (
          <Link
            key={menu.slug}
            href={`/info/catering/${menu.slug}`}
            className="block border rounded-lg p-6 hover:shadow-lg transition-shadow bg-white"
          >
            <h2 className="text-xl font-semibold mb-2">{menu.name}</h2>
            <div className="text-2xl font-bold text-blue-600 mb-3">
              CHF {menu.price_per_person} per person
            </div>
            <p className="text-gray-700 mb-4">{menu.summary}</p>
            {menu.dietary_options.length > 0 && (
              <div className="flex gap-2">
                {menu.dietary_options.map((diet) => (
                  <span
                    key={diet}
                    className="px-3 py-1 bg-green-100 text-green-700 rounded-full text-sm"
                  >
                    {diet}
                  </span>
                ))}
              </div>
            )}
          </Link>
        ))}
      </div>
    </div>
  )
}
```

#### Step 2.4: Create Catering Detail Page
Create `/atelier-ai-frontend/app/info/catering/[menu]/page.tsx`:

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
  context?: {
    room?: string
    date?: string
  }
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
    const queryParams = new URLSearchParams()
    if (room) queryParams.append('room', room)
    if (date) queryParams.append('date', date)

    fetch(`http://localhost:8000/api/test-data/catering/${menuSlug}?${queryParams}`)
      .then(res => {
        if (!res.ok) throw new Error('Menu not found')
        return res.json()
      })
      .then(data => {
        setMenu(data)
        setLoading(false)
      })
      .catch(err => {
        console.error('Failed to load menu:', err)
        setLoading(false)
      })
  }, [menuSlug, room, date])

  if (loading) {
    return (
      <div className="container mx-auto p-8">
        <div className="text-center">Loading menu details...</div>
      </div>
    )
  }

  if (!menu) {
    return (
      <div className="container mx-auto p-8">
        <div className="text-center">Menu not found</div>
      </div>
    )
  }

  return (
    <div className="container mx-auto p-8 max-w-4xl">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold mb-2">{menu.name}</h1>
        <div className="text-2xl text-blue-600 font-semibold mb-4">
          CHF {menu.price_per_person} per person
          {menu.minimum_order > 1 && (
            <span className="text-lg text-gray-600 ml-2">
              (minimum {menu.minimum_order} guests)
            </span>
          )}
        </div>

        {/* Context if provided */}
        {(room || date) && (
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-6">
            {room && (
              <div className="text-gray-700">
                <span className="font-semibold">Selected room:</span> {room}
              </div>
            )}
            {date && (
              <div className="text-gray-700">
                <span className="font-semibold">Event date:</span> {date}
              </div>
            )}
          </div>
        )}

        <p className="text-lg text-gray-700">{menu.description}</p>
      </div>

      {/* Menu Courses */}
      <div className="mb-8">
        <h2 className="text-2xl font-semibold mb-6">Menu Courses</h2>
        <div className="space-y-6">
          {menu.courses.map((course, idx) => (
            <div key={idx} className="bg-white border rounded-lg p-6 shadow-sm">
              <h3 className="text-xl font-semibold mb-3 text-gray-900">
                {course.course}
              </h3>
              <p className="text-gray-700 mb-4 leading-relaxed">
                {course.description}
              </p>

              {/* Dietary tags */}
              {course.dietary.length > 0 && (
                <div className="flex gap-2 flex-wrap">
                  {course.dietary.map((diet) => (
                    <span
                      key={diet}
                      className="px-3 py-1 bg-green-100 text-green-700 rounded-full text-sm font-medium"
                    >
                      {diet}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Beverages */}
      <div className="mb-8">
        <h2 className="text-2xl font-semibold mb-4">Beverages Included</h2>
        <div className="bg-gray-50 rounded-lg p-6">
          <ul className="space-y-2">
            {menu.beverages_included.map((beverage, idx) => (
              <li key={idx} className="flex items-start">
                <span className="text-blue-500 mr-3 mt-1">•</span>
                <span className="text-gray-700">{beverage}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      {/* Footer */}
      <div className="mt-12 text-center">
        <p className="text-gray-600 mb-4">
          Return to your booking conversation to select this menu
        </p>
        <a
          href="/info/catering"
          className="text-blue-600 hover:underline"
        >
          ← View all catering options
        </a>
      </div>
    </div>
  )
}
```

#### Step 2.5: Create Q&A Page
Create `/atelier-ai-frontend/app/info/qna/page.tsx`:

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

interface QnAData {
  items: QnAItem[]
  categories: string[]
}

export default function QnAPage() {
  const searchParams = useSearchParams()
  const selectedCategory = searchParams.get('category')
  const [data, setData] = useState<QnAData>({ items: [], categories: [] })
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const url = selectedCategory
      ? `http://localhost:8000/api/test-data/qna?category=${selectedCategory}`
      : 'http://localhost:8000/api/test-data/qna'

    fetch(url)
      .then(res => res.json())
      .then(data => {
        setData(data)
        setLoading(false)
      })
      .catch(err => {
        console.error('Failed to load Q&A:', err)
        setLoading(false)
      })
  }, [selectedCategory])

  if (loading) {
    return (
      <div className="container mx-auto p-8">
        <div className="text-center">Loading information...</div>
      </div>
    )
  }

  return (
    <div className="container mx-auto p-8 max-w-7xl">
      <h1 className="text-3xl font-bold mb-8">Frequently Asked Questions</h1>

      <div className="flex gap-8">
        {/* Sidebar with categories */}
        <aside className="w-64 flex-shrink-0">
          <h2 className="text-lg font-semibold mb-4 text-gray-700">Categories</h2>
          <ul className="space-y-2">
            <li>
              <a
                href="/info/qna"
                className={`block px-4 py-2 rounded-lg transition-colors ${
                  !selectedCategory
                    ? 'bg-blue-100 text-blue-800 font-medium'
                    : 'hover:bg-gray-100 text-gray-700'
                }`}
              >
                All Questions
              </a>
            </li>
            {data.categories.map(cat => (
              <li key={cat}>
                <a
                  href={`/info/qna?category=${encodeURIComponent(cat)}`}
                  className={`block px-4 py-2 rounded-lg transition-colors ${
                    selectedCategory === cat
                      ? 'bg-blue-100 text-blue-800 font-medium'
                      : 'hover:bg-gray-100 text-gray-700'
                  }`}
                >
                  {cat}
                </a>
              </li>
            ))}
          </ul>
        </aside>

        {/* Main content */}
        <main className="flex-1">
          {selectedCategory && (
            <div className="mb-6 text-gray-600">
              Showing questions about: <span className="font-semibold">{selectedCategory}</span>
            </div>
          )}

          <div className="space-y-6">
            {data.items.map((item, idx) => (
              <div
                key={idx}
                className="bg-white border rounded-lg p-6 shadow-sm hover:shadow-md transition-shadow"
              >
                <div className="text-sm text-gray-500 mb-2">
                  {item.category}
                </div>
                <h3 className="text-xl font-semibold mb-3 text-gray-900">
                  {item.question}
                </h3>
                <div className="text-gray-700 leading-relaxed">
                  {item.answer}
                </div>

                {item.related_links.length > 0 && (
                  <div className="mt-4 pt-4 border-t">
                    <h4 className="text-sm font-semibold text-gray-600 mb-2">
                      Related Information
                    </h4>
                    <ul className="space-y-1">
                      {item.related_links.map((link, linkIdx) => (
                        <li key={linkIdx}>
                          <a
                            href={link.url}
                            className="text-blue-600 hover:underline text-sm"
                          >
                            {link.title} →
                          </a>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            ))}
          </div>
        </main>
      </div>

      {/* Footer */}
      <div className="mt-12 text-center text-gray-600">
        <p>Still have questions? Return to your booking conversation for personalized assistance.</p>
      </div>
    </div>
  )
}
```

### Phase 3: Integration with Workflow

#### Step 3.1: Update Step 3 (Room Availability)
Edit `/backend/workflows/groups/room_availability/trigger/process.py`:

1. Add import at the top:
```python
from backend.utils.pseudolinks import generate_room_details_link
```

2. Find where room options are presented to the client (look for where the message is composed with room information) and add the link before the room details. The exact location will vary, but look for patterns like:
- Where room availability results are formatted
- Where messages about available rooms are created
- Functions that build room option messages

Example integration:
```python
# In the function that builds room availability messages
room_link = generate_room_details_link(
    room_name="all",  # Show all rooms
    date=event_entry.get("chosen_date"),
    participants=event_entry.get("number_of_participants", 0)
)

# Add link to the message
message_lines = [room_link, ""]  # Empty line after link
# ... then add the rest of the message
```

#### Step 3.2: Update Step 4 (Offer Composition)
Edit `/backend/workflows/groups/offer/trigger/process.py`:

1. Add imports at the top:
```python
from backend.utils.pseudolinks import (
    generate_room_details_link,
    generate_catering_catalog_link,
    generate_catering_menu_link
)
```

2. In the `_compose_offer_summary` function (around line 1012-1177), add links:

```python
# After room information (around line 1037)
room_link = generate_room_details_link(
    room_name=room,
    date=chosen_date,
    participants=_infer_participant_count(event_entry)
)
lines.insert(0, room_link)  # Add at beginning
lines.insert(1, "")  # Empty line

# Before catering alternatives section (around line 1111)
if not selected_catering and catering_alternatives:
    catalog_link = generate_catering_catalog_link()
    lines.append("")
    lines.append(catalog_link)
    lines.append("Menu options you can add:")
    # ... rest of catering code
```

### Phase 4: Calendar Integration

#### Step 4.1: Create Calendar Event Manager
Create `/backend/utils/calendar_events.py`:

```python
"""
Calendar event creation for workflow status transitions.
Placeholder implementation - to be replaced with actual calendar API integration.
"""

import json
import os
from datetime import datetime
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

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

    # Extract client info
    event_data = event_entry.get("event_data", {})
    client_name = event_data.get("Name", "Unknown Client")
    company = event_data.get("Company", "")

    participants = event_entry.get("number_of_participants", 0)
    if isinstance(participants, str):
        try:
            participants = int(participants)
        except:
            participants = 0

    # Build calendar event data
    title_parts = [f"[{event_type.upper()}]", client_name]
    if company:
        title_parts.append(f"({company})")
    title_parts.append(f"- {room}")

    calendar_event = {
        "id": f"openevent-{event_id}",
        "title": " ".join(title_parts),
        "date": chosen_date,
        "room": room,
        "participants": participants,
        "status": event_type,
        "client": {
            "name": client_name,
            "company": company,
            "email": event_data.get("Email", ""),
            "phone": event_data.get("Phone", "")
        },
        "description": f"Event booking for {client_name}\nParticipants: {participants}\nStatus: {event_type}\nRoom: {room}",
        "created_at": datetime.utcnow().isoformat(),
        "event_id": event_id
    }

    # Log the event creation
    logger.info(f"Created calendar event: {event_type} for event {event_id}")

    # In production: send to calendar API
    # For now: log to file for testing
    _log_calendar_event(calendar_event)

    return calendar_event

def update_calendar_event_status(event_id: str, old_status: str, new_status: str) -> bool:
    """Update existing calendar event when status changes."""
    try:
        update_data = {
            "event_id": f"openevent-{event_id}",
            "old_status": old_status,
            "new_status": new_status,
            "updated_at": datetime.utcnow().isoformat(),
        }

        logger.info(f"Updated calendar event: {event_id} from {old_status} to {new_status}")
        _log_calendar_event(update_data, action="update")
        return True
    except Exception as e:
        logger.error(f"Failed to update calendar event: {e}")
        return False

def _log_calendar_event(event_data: Dict[str, Any], action: str = "create") -> None:
    """Log calendar events to file for testing."""
    log_dir = "tmp-cache/calendar_events"
    os.makedirs(log_dir, exist_ok=True)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    event_id = event_data.get("event_id", "unknown")
    filename = f"{log_dir}/calendar_{action}_{event_id}_{timestamp}.json"

    try:
        with open(filename, 'w') as f:
            json.dump(event_data, f, indent=2)
        logger.debug(f"Logged calendar event to {filename}")
    except Exception as e:
        logger.error(f"Failed to log calendar event: {e}")
```

#### Step 4.2: Integrate Calendar with Event Creation
Edit `/backend/workflows/io/database.py`:

1. Add import at the top (around line 15):
```python
from backend.utils.calendar_events import create_calendar_event
```

2. In the `create_event_entry` function (around line 239-271), add after the event is appended:
```python
# After line 270: db.setdefault("events", []).append(entry)

# Create calendar event with Lead status
try:
    calendar_event = create_calendar_event(entry, "lead")
    entry["calendar_event_id"] = calendar_event.get("id")
    logger.info(f"Created calendar event for new booking: {event_id}")
except Exception as e:
    logger.warning(f"Failed to create calendar event: {e}")
    # Don't fail the booking if calendar creation fails

return event_id
```

#### Step 4.3: Update Calendar on Date Confirmation
Edit `/backend/workflows/groups/date_confirmation/trigger/process.py`:

1. Add import at top:
```python
from backend.utils.calendar_events import update_calendar_event_status
```

2. After date is confirmed (around line 2158 where `date_confirmed=True`), add:
```python
# After the update_event_metadata call
if event_entry.get("calendar_event_id"):
    # Calendar event exists, update it with confirmed date
    try:
        # Re-create with updated info since date is now confirmed
        from backend.utils.calendar_events import create_calendar_event
        create_calendar_event(event_entry, "lead")  # Still Lead status but with date
    except Exception as e:
        logger.warning(f"Failed to update calendar event: {e}")
```

### Phase 5: Testing

#### Testing Checklist

1. **Start the services**:
```bash
# Terminal 1 - Backend
cd /Users/nico/PycharmProjects/OpenEvent-AI
uvicorn backend.main:app --reload --port 8000

# Terminal 2 - Frontend
cd atelier-ai-frontend
npm run dev
```

2. **Test the pages directly**:
   - [ ] Open http://localhost:3000/info/rooms
   - [ ] Open http://localhost:3000/info/rooms?date=2025-12-15&capacity=30
   - [ ] Open http://localhost:3000/info/catering
   - [ ] Open http://localhost:3000/info/catering/seasonal-garden-trio
   - [ ] Open http://localhost:3000/info/qna
   - [ ] Open http://localhost:3000/info/qna?category=Parking

3. **Test through workflow**:
   - [ ] Start a new conversation at http://localhost:3000
   - [ ] Submit an inquiry for an event
   - [ ] Check that calendar event file is created in `tmp-cache/calendar_events/`
   - [ ] Confirm a date when prompted
   - [ ] When room options appear, click the link
   - [ ] Verify room page shows with correct date parameter
   - [ ] Return to chat and select a room
   - [ ] When offer appears, click catering links
   - [ ] Verify catering pages work correctly

4. **Verify calendar events**:
   - [ ] Check `tmp-cache/calendar_events/` directory
   - [ ] Verify JSON files are created for each event
   - [ ] Check that events have correct status and information

### Common Issues & Solutions

1. **CORS errors when fetching from backend**:
   - Make sure backend is running on port 8000
   - Check that frontend is using correct URL (http://localhost:8000)

2. **Pages not found (404)**:
   - Verify directory structure in `atelier-ai-frontend/app/info/`
   - Make sure file names are exactly as specified

3. **Links not appearing in chat**:
   - Check that imports are added correctly
   - Verify link functions are called in the right places
   - Look for the generated links in the message composition

4. **Calendar events not created**:
   - Check logs for error messages
   - Verify `tmp-cache/` directory exists and is writable
   - Make sure imports are correct

## Summary

You're implementing:
1. **Test pages** that display room, catering, and Q&A information
2. **Working links** in chat messages that open these pages
3. **Calendar events** that track booking status

The key is to:
- Start with backend (data providers and endpoints)
- Build frontend pages that consume this data
- Update workflow messages to include links
- Add calendar event tracking

Test frequently as you go, and don't hesitate to add console.log or logger statements to debug issues. Good luck!