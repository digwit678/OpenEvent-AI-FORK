# Follow-up Tasks for Junior Developer

Good work on the initial implementation! I've reviewed your code and found the following items that need attention:

## ✅ What You Did Well
- Created all the basic backend utilities and endpoints
- Set up the frontend pages structure correctly
- Added room details link in Step 3 (room availability)
- Implemented calendar event logging
- Added month abbreviation formatting
- Set up Q&A shortcut threshold detection

## ❌ Missing/Incorrect Items

### 1. Room Data Not Using Manager Configuration ⚠️
**Issue**: Your `test_data_providers.py` is using hardcoded room data instead of loading from the manager's room configuration.

**Fix needed**:
- Import and use `load_rooms_config()` from `backend.workflows.groups.room_availability.db_pers`
- The rooms should show actual manager-configured features and services
- Currently showing placeholder data

### 2. Room Prices Missing
**Issue**: Manager-configured rooms don't have prices in the DB, but you need to show them.

**Fix needed**:
- Add a fallback pricing map for rooms
- Show both the room price AND all manager-configured items

### 3. Catering Menus Not Linked to Rooms
**Issue**: The room page should show which catering menus are available for that specific room.

**Fix needed**:
- Add a `menus` field to room data
- For now, show all menus on all rooms (as a placeholder)
- Display menus on the room detail page with links

### 4. Q&A Page Not Showing Full Menu Details
**Issue**: When Q&A responses are shortened due to length, the full menu details should appear on the Q&A page.

**Fix needed**:
- Add menu details to the Q&A page data structure
- Display full catering menus at the bottom of Q&A page
- These should show when catering Q&A exceeds the threshold

### 5. Verbalizer Instructions Missing
**Issue**: The TODO comment is added but the verbalizer isn't getting proper instructions.

**Fix needed**:
- The `state.extras["qna_shortcut"]` is set but needs to be passed to verbalizer
- Add clear instructions in the message for the verbalizer to summarize

### 6. Date Formatting Inconsistent
**Issue**: Dates should use month abbreviations consistently (Jan, Feb, Mar, Apr, May, Jun, Jul, Aug, Sept, Oct, Nov, Dec)

**Fix needed**:
- Update date formatting in rooms page (currently showing full date)
- Apply to menu availability windows too

### 7. Links in Wrong Place
**Issue**: You removed the room link from offer summary but the requirement was to keep it ONLY in room availability.

**Correct placement**:
- Room link: ONLY in Step 3 (room availability) ✓ You did this correctly
- Catering links: In Step 4 (offer) when showing menu options ✓ You did this correctly

## 🔧 Specific Code Changes Needed

### 1. Update `backend/utils/test_data_providers.py`:

```python
# Add this import at top
from backend.workflows.groups.room_availability.db_pers import load_rooms_config

def get_rooms_for_display(date: Optional[str] = None, capacity: Optional[int] = None) -> List[Dict[str, Any]]:
    """Get detailed room information for display, combining manager config with defaults."""
    rooms = []

    # Load actual room configurations
    config_rooms = load_rooms_config() or []

    # Default prices since DB doesn't have them
    default_prices = {
        "Room A": 500,
        "Room B": 800,
        "Room C": 1200,
        "Punkt.Null": 1500,
    }

    for room_config in config_rooms:
        room_name = room_config.get("name", "")

        # Build room info from manager config
        room_info = {
            "name": room_name,
            "capacity": room_config.get("capacity_max", 0),
            "status": "Available",  # Simplified for now
            "price": default_prices.get(room_name, 0),
            "features": room_config.get("features", []),
            "equipment": room_config.get("services", []),  # Manager items
            "layout_options": list(room_config.get("capacity_by_layout", {}).keys()),
            "description": f"Manager-configured room with {len(room_config.get('features', []))} features",
            "menus": _get_menus_for_room(room_name),  # Add this
        }

        # Apply capacity filter
        if capacity and room_info["capacity"] < int(capacity):
            continue

        rooms.append(room_info)

    return sorted(rooms, key=lambda x: x["capacity"])

def _get_menus_for_room(room_name: str) -> List[Dict[str, Any]]:
    """Get menus available for a specific room (placeholder - all menus for now)."""
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
```

### 2. Update Q&A data to include full menus:

In `get_qna_items()`, add a new return field:
```python
return {
    "items": items,
    "categories": categories,
    "menus": _get_full_menu_details() if category == "Catering" else []
}

def _get_full_menu_details() -> List[Dict[str, Any]]:
    """Get full menu details for Q&A page display."""
    menus = []
    for menu in DINNER_MENU_OPTIONS:
        # Build complete menu info including courses
        # Similar to get_catering_menu_details but for all menus
    return menus
```

### 3. Update Room Page to Show Menus:

Add menus to the Room interface and display them:
```typescript
interface Room {
  // ... existing fields ...
  menus?: Array<{
    name: string
    slug: string
    price_per_person: number
    summary: string
    dietary_options: string[]
  }>
}

// In the room detail card, add after equipment section:
{room.menus && room.menus.length > 0 && (
  <div className="mt-6 border-t pt-6">
    <h4 className="font-semibold text-gray-900 mb-3">Available Catering Menus</h4>
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {room.menus.map(menu => (
        <a
          key={menu.slug}
          href={`/info/catering/${menu.slug}?room=${encodeURIComponent(room.name)}`}
          className="border rounded p-4 hover:shadow-md transition-shadow"
        >
          <div className="font-semibold">{menu.name}</div>
          <div className="text-blue-600">CHF {menu.price_per_person} pp</div>
          <div className="text-sm text-gray-600 mt-1">{menu.summary}</div>
        </a>
      ))}
    </div>
  </div>
)}
```

### 4. Add Date Formatting Helper:

Create a consistent date formatter:
```typescript
const formatDate = (dateStr: string) => {
  const date = new Date(dateStr);
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sept', 'Oct', 'Nov', 'Dec'];
  return `${date.getDate()} ${months[date.getMonth()]} ${date.getFullYear()}`;
}
```

## 📋 Testing Checklist

After making these changes:

1. [ ] Verify rooms page shows manager-configured features/services
2. [ ] Check that room prices display correctly
3. [ ] Confirm menus appear on room detail pages
4. [ ] Test that clicking menu links passes room parameter
5. [ ] Verify Q&A page shows full menu details when category=Catering
6. [ ] Check all dates use month abbreviations
7. [ ] Confirm the verbalizer shortcut TODO is visible in logs
8. [ ] Test that long Q&A responses show the shortcut link

## 🎯 Priority Order

1. Fix room data to use manager configuration (HIGH)
2. Add menus to rooms page (HIGH)
3. Add full menu details to Q&A page (MEDIUM)
4. Fix date formatting consistently (LOW)

Please make these changes and test thoroughly. The main goal is to ensure:
- Room pages show real manager data + menus
- Q&A page can display full menu details when messages are shortened
- All dates use consistent abbreviations

Good luck! Let me know if you need clarification on any of these items.