# Database Consolidation Plan

## Problem Statement
The project currently suffers from "split brain" data management for static resources (rooms and products). There are multiple JSON files serving overlapping purposes, leading to potential data inconsistency and confusion for both developers and the AI system.

### Current State

| Domain | File | Purpose | Key Data |
| :--- | :--- | :--- | :--- |
| **Catering** | `backend/catering_menu.json` | Descriptive/Menu details | Ingredients, detailed "includes" lists, dietary options. |
| **Catering** | `backend/data/catalog/catering.json` | Pricing/Logic | Flat list of products, unit prices, synonyms, `unavailable_in`. |
| **Rooms** | `backend/room_info.json` | Descriptive/Pricing | Hourly/day rates, "best_for", marketing descriptions. IDs: `room_a` |
| **Rooms** | `backend/rooms.json` | Operational/Logic | Capacities, layouts, calendar IDs, buffer times. IDs: `atelier-room-a` |
| **Transactional** | `backend/events_database.json` | Runtime State | Live events, clients, tasks. (Keep as is) |

### Issues
1.  **ID Mismatch:** Rooms use `room_a` in one file and `atelier-room-a` in another.
2.  **Price Duplication:** Prices might exist in both catering files (risk of sync errors).
3.  **Scatter:** Files are in root `backend/`, `backend/data/`, etc.
4.  **Schema Confusion:** The LLM might be receiving partial context depending on which file is loaded by a specific tool.

## Proposed Solution

Consolidate all static reference data into a single `backend/data/` directory with unified schemas.

### 1. Unified Directory Structure
```
backend/
  data/
    products.json       # Merged catering + equipment + add-ons
    rooms.json          # Merged operational + descriptive room data
    rules/              # (Optional) Business logic rules
```

### 2. Schema Mergers

#### A. Unified Rooms (`backend/data/rooms.json`)
Merge `backend/rooms.json` (operational) and `backend/room_info.json` (descriptive).
*   **Primary ID:** Use the operational ID (`atelier-room-a`) as the canonical key.
*   **Structure:**
    ```json
    [
      {
        "id": "atelier-room-a",
        "name": "Room A",
        "type": "meeting_room",
        "calendar_id": "atelier-room-a",
        "capacities": {
          "min": 12,
          "max": 40,
          "optimal": 15,
          "layouts": { "theatre": 40, "u_shape": 22 }
        },
        "pricing": {
          "hourly": 80,
          "half_day": 300,
          "full_day": 500
        },
        "features": ["Natural daylight", "Projector"],
        "marketing": {
          "description": "...",
          "best_for": ["Workshops", "Small meetings"]
        },
        "operations": {
          "buffer_before": 30,
          "buffer_after": 30
        }
      }
    ]
    ```

#### B. Unified Products (`backend/data/products.json`)
Merge `backend/data/catalog/catering.json` (logic) and `backend/catering_menu.json` (details).
*   **Structure:**
    ```json
    [
      {
        "id": "catering-lunch-standard",
        "name": "Lunch Package",
        "category": "Catering",
        "unit": "per_person",
        "price": {
          "amount": 28.00,
          "currency": "CHF"
        },
        "synonyms": ["lunch", "mittagessen"],
        "details": {
          "description": "Full lunch service",
          "includes": ["Main course", "Salad bar"],
          "dietary": ["Vegetarian", "Vegan"]
        },
        "rules": {
          "unavailable_in": []
        }
      }
    ]
    ```

## Implementation Steps

1.  **Data Migration Script:**
    *   Create a script `scripts/migrate_db_files.py` to read the old 4 files and generate the new 2 files.
    *   Handle ID mapping (`room_a` -> `atelier-room-a`).
2.  **Update Adapters:**
    *   Modify `backend/services/products.py` to read from the new `products.json`.
    *   Modify `backend/workflows/common/room_rules.py` and `backend/workflows/io/database.py` to read from the new `rooms.json`.
3.  **Update LLM Context:**
    *   Ensure the "Safety Sandwich" and "Verbalizer" context builders pull from the merged fields (e.g., using `marketing.description` for verbalization).
4.  **Cleanup:**
    *   Archive/Delete old JSON files.
    *   Update `backend/README.md` to reflect new data sources.

## Benefits
*   **Single Source of Truth:** Prices and descriptions live in one place.
*   **Simplified Code:** Loaders only need to check one path.
*   **Better LLM Context:** Agents can see both the "operational constraints" and "marketing descriptions" of a room in a single lookup.
