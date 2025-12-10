from __future__ import annotations

"""
Link generator for room and catering options.
Generates real links to test pages during development.

Supports snapshot-based links for persistent data:
- If snapshot_id is provided, the page will fetch from /api/snapshots/{id}
- If not, the page will fetch fresh data based on query params
"""

import os
from urllib.parse import urlencode

# Get base URL from environment or use localhost
BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://localhost:3000")


def _make_link(label: str, url: str) -> str:
    """Return an HTML anchor that opens in a new tab."""
    return f'<a href="{url}" target="_blank" rel="noopener noreferrer">{label}</a>'


def generate_room_details_link(
    room_name: str,
    date: str,
    participants: int | None = None,
    snapshot_id: str | None = None,
) -> str:
    """Generate link to room availability page.

    If snapshot_id is provided, the page will fetch from the snapshot.
    Otherwise, it will fetch fresh data based on date/capacity params.
    """
    params = {}

    if snapshot_id:
        params["snapshot_id"] = snapshot_id
    else:
        params["date"] = date
        if participants:
            params["capacity"] = str(participants)

    query_string = urlencode(params)
    return _make_link("View all available rooms", f"{BASE_URL}/info/rooms?{query_string}")


def generate_catering_menu_link(
    menu_name: str,
    room: str | None = None,
    date: str | None = None,
    snapshot_id: str | None = None,
) -> str:
    """Generate link to specific catering menu page.

    If snapshot_id is provided, the page will fetch from the snapshot.
    Otherwise, it will use room/date params.
    """
    params = {}

    if snapshot_id:
        params["snapshot_id"] = snapshot_id
    else:
        if room:
            params["room"] = room
        if date:
            params["date"] = date

    menu_slug = menu_name.lower().replace(" ", "-")
    query_string = urlencode(params) if params else ""
    url = f"{BASE_URL}/info/catering/{menu_slug}"
    if query_string:
        url += f"?{query_string}"

    return _make_link(f"View {menu_name} details", url)


def generate_catering_catalog_link(
    query_params: dict | None = None,
    snapshot_id: str | None = None,
) -> str:
    """Generate link to catering catalog with dynamic query parameters.

    Now uses unified Q&A page instead of separate catering page.
    """
    # Use unified Q&A link with category=Catering
    return generate_qna_link(category="Catering", query_params=query_params, snapshot_id=snapshot_id)


def generate_qna_link(
    category: str | None = None,
    query_params: dict | None = None,
    snapshot_id: str | None = None,
) -> str:
    """Generate link to Q&A page with dynamic query parameters.

    If snapshot_id is provided, the page will fetch from the snapshot.
    Otherwise, it will fetch fresh data based on query params.
    """
    params = {}

    if snapshot_id:
        params["snapshot_id"] = snapshot_id
    else:
        if category:
            params["category"] = category
        # Add all extracted query parameters (month, dietary preferences, etc.)
        if query_params:
            params.update(query_params)

    if params:
        query_string = urlencode(params)
        label = f"View {category} information" if category else "View information"
        return _make_link(label, f"{BASE_URL}/info/qna?{query_string}")

    return _make_link("View frequently asked questions", f"{BASE_URL}/info/qna")


def generate_offer_preview_link(offer_id: str) -> str:
    """Generate link for offer preview."""
    return _make_link("Download offer PDF", f"{BASE_URL}/api/offers/{offer_id}/pdf")


def generate_site_visit_info_link(room: str | None = None) -> str:
    """Generate link to site visit information page."""
    params = {}
    if room:
        params["room"] = room

    query_string = urlencode(params) if params else ""
    url = f"{BASE_URL}/info/site-visits"
    if query_string:
        url += f"?{query_string}"

    return _make_link("Learn more about site visits", url)


def generate_site_visit_calendar_link(date_range: str | None = None) -> str:
    """Generate link to available site visit slots."""
    params = {}
    if date_range:
        params["dates"] = date_range

    query_string = urlencode(params) if params else ""
    url = f"{BASE_URL}/info/site-visits"
    if query_string:
        url += f"?{query_string}"

    return _make_link("View available site visit times", url)
