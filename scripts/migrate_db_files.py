#!/usr/bin/env python3
"""
Database Consolidation Migration Script

Merges:
- backend/rooms.json + backend/room_info.json -> backend/data/rooms.json
- backend/catering_menu.json + backend/data/catalog/catering.json -> backend/data/products.json

ID Mapping: room_a -> atelier-room-a (uses operational ID as canonical)
"""
from __future__ import annotations

import json
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"


def load_json(path: Path) -> dict:
    """Load JSON file with error handling."""
    if not path.exists():
        print(f"  [WARN] File not found: {path}")
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict | list) -> None:
    """Save JSON with consistent formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  [OK] Saved: {path}")


def room_id_mapping() -> dict[str, str]:
    """Map short IDs to operational IDs."""
    return {
        "room_a": "atelier-room-a",
        "room_b": "atelier-room-b",
        "room_c": "atelier-room-c",
        "room_d": "atelier-room-d",
        "room_e": "atelier-room-e",
        "room_f": "atelier-room-f",
    }


def merge_rooms() -> list[dict]:
    """Merge rooms.json (operational) with room_info.json (descriptive).

    Output format preserves backwards compatibility with existing adapters:
    - capacity_min, capacity_max, capacity_by_layout (flat)
    - buffer_before_min, buffer_after_min (flat)
    Plus enriched data for new features.
    """
    print("\n[ROOMS] Merging room data...")

    # Load operational data (source of truth for capacity/calendar)
    operational = load_json(BACKEND_ROOT / "rooms.json")
    rooms_op = {r["id"]: r for r in operational.get("rooms", [])}

    # Load descriptive data (pricing/marketing)
    descriptive = load_json(BACKEND_ROOT / "room_info.json")
    rooms_desc = {}
    id_map = room_id_mapping()
    for r in descriptive.get("rooms", []):
        canonical_id = id_map.get(r["id"], r["id"])
        rooms_desc[canonical_id] = r

    # Merge
    merged = []
    for room_id, op in rooms_op.items():
        desc = rooms_desc.get(room_id, {})

        # Backwards-compatible flat structure for existing adapters
        merged_room = {
            "id": room_id,
            "name": op.get("name") or desc.get("name", f"Room {room_id[-1].upper()}"),
            "calendar_id": op.get("calendar_id", room_id),
            # Flat capacity fields (backwards compatible)
            "capacity_min": op.get("capacity_min") or desc.get("capacity", {}).get("min", 10),
            "capacity_max": op.get("capacity_max") or desc.get("capacity", {}).get("max", 50),
            "capacity_optimal": desc.get("capacity", {}).get("optimal"),
            "capacity_by_layout": op.get("capacity_by_layout", {}),
            # Flat buffer fields (backwards compatible)
            "buffer_before_min": op.get("buffer_before_min", 30),
            "buffer_after_min": op.get("buffer_after_min", 30),
            "max_parallel_events": op.get("max_parallel_events", 1),
            # Features merged from both sources
            "features": list(set(op.get("features", []) + desc.get("features", []))),
            "services": op.get("services", []),
            # Enriched data from descriptive source
            "equipment": desc.get("equipment", []),
            "setup_options": desc.get("setup_options", []),
            "best_for": desc.get("best_for", []),
            "size_sqm": desc.get("size_sqm"),
            # Pricing from descriptive
            "hourly_rate": desc.get("hourly_rate"),
            "half_day_rate": desc.get("half_day_rate"),
            "full_day_rate": desc.get("full_day_rate"),
        }

        # Clean up None values
        merged_room = {k: v for k, v in merged_room.items() if v is not None}
        merged.append(merged_room)

    print(f"  Merged {len(merged)} rooms")
    return merged


def merge_products() -> list[dict]:
    """Merge catering_menu.json (details) with catalog/catering.json (logic).

    Output preserves backwards compatibility:
    - unit_price (flat, for existing adapters)
    - unavailable_in (flat, for existing adapters)
    Plus enriched details field for new features.
    """
    print("\n[PRODUCTS] Merging product data...")

    # Load catalog data (pricing/logic)
    catalog = load_json(BACKEND_ROOT / "data" / "catalog" / "catering.json")
    products_catalog = {p["id"]: p for p in catalog.get("products", [])}

    # Load menu data (details)
    menu = load_json(BACKEND_ROOT / "catering_menu.json")

    merged = []

    # Add catalog products first (these have IDs and pricing)
    for prod_id, prod in products_catalog.items():
        merged_prod = {
            "id": prod["id"],
            "name": prod["name"],
            "category": prod.get("category", "Catering"),
            "unit": prod.get("unit", "per_person"),
            # Flat price (backwards compatible)
            "unit_price": prod.get("unit_price", 0),
            # Flat unavailable_in (backwards compatible)
            "unavailable_in": prod.get("unavailable_in", []),
            "synonyms": prod.get("synonyms", []),
        }
        merged.append(merged_prod)

    # Add catering packages from menu (with generated IDs)
    for pkg in menu.get("catering_packages", []):
        prod_id = f"catering-{pkg['id'].replace('_', '-')}"
        # Skip if already in catalog
        if any(p["id"] == prod_id for p in merged):
            continue

        merged_prod = {
            "id": prod_id,
            "name": pkg["name"],
            "category": "Catering",
            "unit": "per_person",
            "unit_price": pkg.get("price_per_person", 0),
            "unavailable_in": [],
            "synonyms": [],
            # Enriched details
            "description": pkg.get("description", ""),
            "includes": pkg.get("includes", []),
            "dietary_options": pkg.get("dietary_options", []),
        }
        merged.append(merged_prod)

    # Add beverages
    for bev_type in ["non_alcoholic", "alcoholic"]:
        for bev in menu.get("beverages", {}).get(bev_type, []):
            prod_id = f"beverage-{bev['name'].lower().replace(' ', '-').replace('&', 'and')}"
            if any(p["id"] == prod_id for p in merged):
                continue

            price = bev.get("price_per_person") or bev.get("price_per_glass") or bev.get("price_per_bottle", 0)
            unit = "per_person" if bev.get("price_per_person") else "per_glass" if bev.get("price_per_glass") else "per_bottle"

            merged_prod = {
                "id": prod_id,
                "name": bev["name"],
                "category": "Beverages",
                "unit": unit,
                "unit_price": price,
                "unavailable_in": [],
                "synonyms": [],
                # Enriched details
                "options": bev.get("options", []),
            }
            merged.append(merged_prod)

    # Add add-ons
    for addon in menu.get("add_ons", []):
        prod_id = f"addon-{addon['name'].lower().replace(' ', '-')}"
        if any(p["id"] == prod_id for p in merged):
            continue

        merged_prod = {
            "id": prod_id,
            "name": addon["name"],
            "category": "Add-ons",
            "unit": "per_event",
            "unit_price": addon.get("price", 0),
            "unavailable_in": [],
            "synonyms": [],
            # Enriched details
            "description": addon.get("description", ""),
        }
        merged.append(merged_prod)

    print(f"  Merged {len(merged)} products")
    return merged


def main() -> None:
    """Run the database consolidation migration."""
    print("=" * 60)
    print("DATABASE CONSOLIDATION MIGRATION")
    print("=" * 60)

    # Merge rooms
    rooms = merge_rooms()
    save_json(BACKEND_ROOT / "data" / "rooms.json", {"rooms": rooms})

    # Merge products
    products = merge_products()
    save_json(BACKEND_ROOT / "data" / "products.json", {"products": products})

    print("\n" + "=" * 60)
    print("MIGRATION COMPLETE")
    print("=" * 60)
    print("\nNext steps:")
    print("  1. Update adapters to use new paths")
    print("  2. Run tests to verify no regressions")
    print("  3. Archive old JSON files")


if __name__ == "__main__":
    main()
