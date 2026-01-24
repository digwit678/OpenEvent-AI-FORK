"""Billing address detection module.

This module contains pure functions for detecting and extracting billing
addresses from message text. No side effects, no state mutation.

Extracted from step1_handler.py for maintainability.
"""
from __future__ import annotations

import re
from typing import Optional

from .gate_confirmation import looks_like_billing_fragment as _looks_like_billing_fragment


def extract_billing_from_body(body: str) -> Optional[str]:
    """Extract billing address from message body if it contains billing info.

    Handles cases where billing is embedded in a larger message (e.g., event request
    that also includes billing address).

    Detection strategies:
    1. Explicit billing section markers ("Our billing address is:", "Invoice to:", etc.)
    2. Multi-line address blocks with postal codes, street numbers, company names

    Args:
        body: The message body text

    Returns:
        The extracted billing portion, or None if no billing info found
    """
    if not body or not body.strip():
        return None

    # Check for explicit billing section markers
    billing_markers = [
        r"(?:our\s+)?billing\s+address(?:\s+is)?[:\s]*",
        r"(?:our\s+)?address(?:\s+is)?[:\s]*",
        r"invoice\s+(?:to|address)[:\s]*",
        r"send\s+invoice\s+to[:\s]*",
    ]

    for pattern in billing_markers:
        match = re.search(pattern + r"(.+?)(?:\n\n|Best|Kind|Thank|Regards|$)", body, re.IGNORECASE | re.DOTALL)
        if match:
            billing_text = match.group(1).strip()
            # Validate it looks like an address (has street/postal)
            if _looks_like_billing_fragment(billing_text):
                return billing_text

    # Fallback: check if message contains billing keywords but no explicit marker
    # Only extract if it looks like a complete address
    if _looks_like_billing_fragment(body):
        address_block = _extract_address_block(body)
        if address_block:
            return address_block

    return None


def _extract_address_block(body: str) -> Optional[str]:
    """Try to find a multi-line address block in the message.

    Looks for lines that contain:
    - Postal codes (4-6 digit numbers)
    - Street numbers
    - Company names (GmbH, AG, Ltd, etc.)
    - City/country names (Zurich, Switzerland, etc.)

    Args:
        body: The message body text

    Returns:
        The extracted address block or None
    """
    lines = body.split("\n")
    address_lines = []
    in_address = False

    for line in lines:
        line = line.strip()
        if not line:
            if in_address and len(address_lines) >= 2:
                break  # End of address block
            continue

        # Check if line looks like address part
        has_postal = re.search(r"\b\d{4,6}\b", line)
        has_street_num = re.search(r"\d+\w*\s*$|\s\d+\s", line)
        is_company = bool(re.search(r"\b(gmbh|ag|ltd|inc|corp|llc|sarl|sa)\b", line, re.IGNORECASE))
        is_city_country = bool(re.search(
            r"\b(zurich|zürich|geneva|bern|basel|switzerland|schweiz)\b",
            line, re.IGNORECASE
        ))

        if has_postal or has_street_num or is_company or is_city_country:
            in_address = True
            address_lines.append(line)
        elif in_address:
            # Continue adding lines until we hit something that's clearly not address
            if len(line) < 50 and not re.search(
                r"\b(hello|hi|dear|please|thank|we|i am|looking)\b",
                line, re.IGNORECASE
            ):
                address_lines.append(line)
            else:
                break

    if len(address_lines) >= 2:
        return "\n".join(address_lines)

    return None
