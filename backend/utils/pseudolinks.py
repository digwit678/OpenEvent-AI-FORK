from __future__ import annotations

"""
Link generator for room and catering options.
Generates real links to test pages during development.
"""

import os
from urllib.parse import urlencode

# Get base URL from environment or use localhost
BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://localhost:3000")


def _make_link(label: str, url: str) -> str:
    """Return an HTML anchor that opens in a new tab."""
    return f'<a href="{url}" target="_blank" rel="noopener noreferrer">{label}</a>'


def generate_room_details_link(room_name: str, date: str, participants: int | None = None) -> str:
    """Generate link to room availability page."""
    params = {"date": date}
    if participants:
        params["capacity"] = str(participants)
    query_string = urlencode(params)
    return _make_link("View all available rooms", f"{BASE_URL}/info/rooms?{query_string}")


def generate_catering_menu_link(menu_name: str, room: str | None = None, date: str | None = None) -> str:
    """Generate link to specific catering menu page."""
    params = {}
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


def generate_catering_catalog_link() -> str:
    """Generate link to catering catalog."""
    return _make_link("Browse all catering options", f"{BASE_URL}/info/catering")


def generate_qna_link(category: str | None = None) -> str:
    """Generate link to Q&A page."""
    if category:
        params = urlencode({"category": category})
        return _make_link(f"View {category} information", f"{BASE_URL}/info/qna?{params}")
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
