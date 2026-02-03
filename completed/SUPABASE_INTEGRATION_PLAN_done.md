# Supabase Integration Plan

**Date:** January 12, 2026
**Status:** Ready for Implementation

## 1. Executive Summary

The application is currently running on a local JSON file database (`events_team-shami.json`) but has a nearly complete Supabase adapter (`supabase_adapter.py`) ready to be enabled.

**Current State:**
- **Configuration:** Environment variables (`OE_SUPABASE_URL`, `OE_SUPABASE_KEY`, `OE_TEAM_ID`, `OE_SYSTEM_USER_ID`) are set up in `.env` (git-ignored).
- **Connectivity:** Confirmed. We can successfully fetch data from `events`, `clients`, `offers`, etc.
- **Schema Alignment:** The Supabase schema largely mirrors the internal domain models, but there is one critical discrepancy regarding Offer Line Items that requires code adjustment.

## 2. Critical Discrepancy: Offer Line Items

**Issue:**
- **Backend Code:** The `supabase_adapter.py` attempts to write line items to a relational table named `offer_line_items`.
- **Database State:** The `offer_line_items` table exists but is **empty**.
- **Existing Data:** The `offers` table contains a `products` column (JSONB) that is populated with line item data in existing records.

**Implication:**
If we switch to Supabase now without changes, the backend will write items to the empty `offer_line_items` table, but the frontend (likely reading the `products` JSONB column) will show empty offers.

**Recommendation:**
**Modify `supabase_adapter.py`** to write to the `products` JSONB column in the `offers` table instead of (or in addition to) the `offer_line_items` table, until the frontend is confirmed to support the relational table.

## 3. Schema Mapping & Changes

### A. Events Table
| Internal Field (`EventInformation`) | Supabase Column | Action Required |
| :--- | :--- | :--- |
| `event_id` | `id` | Direct Map |
| `status` (e.g. "Lead") | `status` (e.g. "lead") | **Fix Casing:** Internal uses Title Case, Supabase uses lowercase. `status_utils.py` handles this, but verify. |
| `event_date` ("DD.MM.YYYY") | `event_date` (YYYY-MM-DD) | **Format Conversion:** Adapter must convert format. |
| `name` | (Derived from `clients`) | Logic exists to link/create client. |
| `email` | (Derived from `clients`) | Logic exists. |
| `number_of_participants` | `attendees` | **Rename:** Map `number_of_participants` -> `attendees`. |
| `start_time` | `start_time` | Direct Map |
| `end_time` | `end_time` | Direct Map |
| `additional_info` | `notes` | Direct Map |
| `team_id` | `team_id` | **Inject:** Must inject from `.env` / Context. |

### B. Clients Table
| Internal Field | Supabase Column | Action Required |
| :--- | :--- | :--- |
| `email` | `email` | Lookup Key. |
| `name` | `name` | Direct Map |
| `phone` | `phone` | Direct Map |
| `company` | `company` | Direct Map |
| N/A | `user_id` | **Inject:** Must inject `OE_SYSTEM_USER_ID` for created records. |

### C. Offers Table
| Internal Field | Supabase Column | Action Required |
| :--- | :--- | :--- |
| `offer_id` | `id` | Direct Map |
| `total` | `total_amount` | Direct Map |
| `line_items` (List) | `products` (JSONB) | **CRITICAL FIX:** Adapter writes to `offer_line_items` table. Need to populate `products` column. |
| `status` | `status` | Defaults to "draft". |

## 4. Integration Steps

### Step 1: Fix Adapter Logic (Priority High)
Modify `workflows/io/integration/supabase_adapter.py`:
- In `create_offer`, update the `offer` dictionary to include the `products` key.
- Populate `products` with the `line_items` list (ensure keys match JSONB expectations).
- Keep the `offer_line_items` insert for future-proofing (optional, but safe).

### Step 2: Data Migration (Optional but Recommended)
Create a script (`scripts/migrate_json_to_supabase.py`) to:
1. Load `events_team-shami.json`.
2. Iterate through events.
3. Check if event exists in Supabase (by Email + Date).
4. If not, insert Event + Client + Link them.
5. *Note: This ensures the AI has history to work with.*

### Step 3: Switch Mode
1. Ensure `.env` has `OE_INTEGRATION_MODE=supabase`.
2. Restart backend.

### Step 4: Verification
1. **Create Lead:** Send a booking request via the chat/email interface.
2. **Verify DB:** Check Supabase dashboard -> `events` table.
3. **Verify Client:** Check `clients` table.
4. **Generate Offer:** Trigger offer generation flow.
5. **Verify Offer:** Check `offers` table, specifically the `products` column to ensure line items are present.

## 5. Security Note
- **RLS:** Row Level Security is enabled on Supabase.
- **Service Role Key:** The backend uses the Service Role Key (`OE_SUPABASE_KEY` in `.env`). This bypasses RLS, which is correct for the backend system acting as an admin.
- **Team Isolation:** The backend MUST explicitly include `team_id` in all inserts/queries (which the adapter seems to do) to respect multi-tenancy logic manually.

## 6. Required Code Change (Snippet)

**File:** `workflows/io/integration/supabase_adapter.py`
**Function:** `create_offer`

```python
    # ... existing code ...
    
    # Prepare line items for JSONB storage
    products_json = []
    for item in line_items:
        # Transform item if necessary to match "products" JSONB schema
        # Based on schema fetching, it expects: id, name, price, total, quantity, etc.
        p = {
            "id": item.get("product_id") or str(uuid.uuid4()), # Fallback if custom item
            "name": item.get("name"),
            "price": item.get("unit_price"),
            "quantity": item.get("quantity"),
            "total": item.get("total"),
            "description": item.get("description", "")
        }
        products_json.append(p)

    offer = {
        "team_id": team_id,
        # ... other fields ...
        "products": products_json, # <--- ADD THIS
    }

    result = client.table("offers").insert(offer).execute()
    
    # ... existing code ...
```
