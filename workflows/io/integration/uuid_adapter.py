"""
UUID adapter utilities for Supabase integration.

The main project uses UUIDs for all entity IDs, while the current
workflow uses email strings as client_id and string slugs for rooms/products.

This module provides utilities to:
1. Look up clients by email and return UUIDs
2. Generate valid UUIDs for new entities
3. Validate UUID format

Based on EMAIL_WORKFLOW_INTEGRATION_REQUIREMENTS.md Section A2.
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Dict, Optional, Callable

# UUID v4 regex pattern
UUID_PATTERN = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$',
    re.IGNORECASE
)


def is_valid_uuid(value: str) -> bool:
    """
    Check if a string is a valid UUID v4.

    Args:
        value: String to check

    Returns:
        True if valid UUID v4

    Example:
        >>> is_valid_uuid("550e8400-e29b-41d4-a716-446655440000")
        True
        >>> is_valid_uuid("client@example.com")
        False
    """
    if not value or not isinstance(value, str):
        return False
    return bool(UUID_PATTERN.match(value))


def generate_uuid() -> str:
    """
    Generate a new UUID v4 string.

    Returns:
        New UUID string

    Example:
        >>> uuid_str = generate_uuid()
        >>> is_valid_uuid(uuid_str)
        True
    """
    return str(uuid.uuid4())


def normalize_email(email: str) -> str:
    """
    Normalize email for consistent lookups.

    Args:
        email: Email address

    Returns:
        Lowercase, stripped email

    Example:
        >>> normalize_email("  User@Example.COM  ")
        'user@example.com'
    """
    if not email:
        return ""
    return email.strip().lower()


class ClientUUIDCache:
    """
    In-memory cache for email -> UUID mappings.

    Used to avoid repeated database lookups during a single workflow run.
    Cache is cleared between sessions.
    """

    def __init__(self):
        self._cache: Dict[str, str] = {}

    def get(self, email: str) -> Optional[str]:
        """Get cached UUID for email, or None if not cached."""
        return self._cache.get(normalize_email(email))

    def set(self, email: str, uuid_str: str) -> None:
        """Cache a UUID for an email."""
        self._cache[normalize_email(email)] = uuid_str

    def clear(self) -> None:
        """Clear all cached mappings."""
        self._cache.clear()


# Global cache instance
_client_uuid_cache = ClientUUIDCache()


def get_client_uuid_cache() -> ClientUUIDCache:
    """Get the global client UUID cache."""
    return _client_uuid_cache


def clear_uuid_cache() -> None:
    """Clear the global UUID cache (for testing)."""
    _client_uuid_cache.clear()


# =============================================================================
# Supabase Client Lookup (placeholder - implemented in supabase_adapter.py)
# =============================================================================

# Type hint for the lookup function
ClientLookupFn = Callable[[str, str], Optional[str]]

# Will be set by supabase_adapter when initialized
_supabase_client_lookup: Optional[ClientLookupFn] = None


def register_client_lookup(fn: ClientLookupFn) -> None:
    """
    Register the Supabase client lookup function.

    Called by supabase_adapter during initialization.
    """
    global _supabase_client_lookup
    _supabase_client_lookup = fn


def lookup_client_uuid(email: str, team_id: str) -> Optional[str]:
    """
    Look up client UUID by email.

    First checks cache, then queries Supabase if registered.

    Args:
        email: Client email address
        team_id: Team UUID for multi-tenant lookup

    Returns:
        Client UUID or None if not found
    """
    email_normalized = normalize_email(email)

    # Check cache first
    cached = _client_uuid_cache.get(email_normalized)
    if cached:
        return cached

    # Query Supabase if lookup function is registered
    if _supabase_client_lookup:
        result = _supabase_client_lookup(email_normalized, team_id)
        if result:
            _client_uuid_cache.set(email_normalized, result)
        return result

    return None


# =============================================================================
# ID Conversion Utilities
# =============================================================================

def ensure_uuid_format(
    id_value: str,
    entity_type: str = "unknown",
    lookup_fn: Optional[Callable[[str], Optional[str]]] = None
) -> str:
    """
    Ensure an ID is in UUID format.

    If already a UUID, returns as-is.
    If not, attempts lookup via provided function, or generates new UUID.

    Args:
        id_value: Current ID value (may be email, slug, or UUID)
        entity_type: Entity type for logging (client, room, product)
        lookup_fn: Optional function to look up UUID by current value

    Returns:
        UUID string

    Example:
        >>> ensure_uuid_format("550e8400-e29b-41d4-a716-446655440000")
        '550e8400-e29b-41d4-a716-446655440000'
    """
    if is_valid_uuid(id_value):
        return id_value

    if lookup_fn:
        looked_up = lookup_fn(id_value)
        if looked_up and is_valid_uuid(looked_up):
            return looked_up

    # Generate new UUID as fallback (should log warning in production)
    return generate_uuid()


def client_id_to_uuid(
    client_id: str,
    team_id: Optional[str] = None,
    create_if_missing: bool = False,
    client_data: Optional[Dict[str, Any]] = None
) -> Optional[str]:
    """
    Convert a client_id (email) to UUID.

    Args:
        client_id: Client ID (typically email in current system)
        team_id: Team UUID for lookup
        create_if_missing: If True, create new client if not found
        client_data: Data for creating new client (name, company, etc.)

    Returns:
        Client UUID or None if not found and create_if_missing=False

    Note:
        In JSON mode, returns the email as-is.
        In Supabase mode, performs lookup/creation.
    """
    from .config import is_integration_mode

    # In JSON mode, just return the email (current behavior)
    if not is_integration_mode():
        return client_id

    # Already a UUID
    if is_valid_uuid(client_id):
        return client_id

    # Normalize email
    email = normalize_email(client_id)
    if not email:
        return None

    # Look up existing
    if team_id:
        existing = lookup_client_uuid(email, team_id)
        if existing:
            return existing

    # Create new client if requested
    if create_if_missing and client_data:
        # This will be implemented in supabase_adapter
        # For now, return None to indicate not found
        pass

    return None


# =============================================================================
# Room/Product ID Utilities
# =============================================================================

class EntityUUIDRegistry:
    """
    Registry for mapping string slugs to UUIDs.

    Used for rooms and products which may be referenced by name/slug
    in the current system but need UUIDs for Supabase.
    """

    def __init__(self):
        self._rooms: Dict[str, str] = {}
        self._products: Dict[str, str] = {}

    def register_room(self, slug: str, uuid_str: str) -> None:
        """Register a room slug -> UUID mapping."""
        self._rooms[slug.lower()] = uuid_str

    def register_product(self, slug: str, uuid_str: str) -> None:
        """Register a product slug -> UUID mapping."""
        self._products[slug.lower()] = uuid_str

    def get_room_uuid(self, slug_or_uuid: str) -> Optional[str]:
        """Get room UUID from slug or return if already UUID."""
        if is_valid_uuid(slug_or_uuid):
            return slug_or_uuid
        return self._rooms.get(slug_or_uuid.lower())

    def get_product_uuid(self, slug_or_uuid: str) -> Optional[str]:
        """Get product UUID from slug or return if already UUID."""
        if is_valid_uuid(slug_or_uuid):
            return slug_or_uuid
        return self._products.get(slug_or_uuid.lower())

    def load_from_supabase(self, rooms: list, products: list) -> None:
        """
        Load mappings from Supabase query results.

        Args:
            rooms: List of room records with 'id' and 'name' fields
            products: List of product records with 'id' and 'name' fields
        """
        for room in rooms:
            if room.get("id") and room.get("name"):
                self._rooms[room["name"].lower()] = room["id"]

        for product in products:
            if product.get("id") and product.get("name"):
                self._products[product["name"].lower()] = product["id"]

    def clear(self) -> None:
        """Clear all registries."""
        self._rooms.clear()
        self._products.clear()


# Global registry instance
_entity_registry = EntityUUIDRegistry()


def get_entity_registry() -> EntityUUIDRegistry:
    """Get the global entity UUID registry."""
    return _entity_registry


def room_id_to_uuid(room_id: str) -> Optional[str]:
    """
    Convert a room ID (slug or UUID) to UUID.

    Args:
        room_id: Room identifier (slug like "room-a" or UUID)

    Returns:
        Room UUID or None if not found
    """
    return _entity_registry.get_room_uuid(room_id)


def product_id_to_uuid(product_id: str) -> Optional[str]:
    """
    Convert a product ID (slug or UUID) to UUID.

    Args:
        product_id: Product identifier (slug like "menu-1" or UUID)

    Returns:
        Product UUID or None if not found
    """
    return _entity_registry.get_product_uuid(product_id)