"""
Integration layer for Supabase/Frontend connectivity.

This module provides a clean separation between the current JSON-based
storage and future Supabase integration. Use the toggle in config.py
to switch between modes.

Structure:
- config.py: Toggle and configuration for integration mode
- field_mapping.py: Column name translations between internal and Supabase schema
- uuid_adapter.py: UUID handling and client lookup utilities
- offer_utils.py: Offer number generation and formatting
- status_utils.py: Status normalization (Lead -> lead)
- supabase_adapter.py: Supabase-compatible database operations
- adapter.py: Main entry point that routes to JSON or Supabase based on config
"""

from .config import INTEGRATION_CONFIG, is_integration_mode