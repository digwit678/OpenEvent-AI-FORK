#!/usr/bin/env python3
"""
Test script to verify Supabase connection and configuration.

Usage:
    # Set environment variables first, then:
    python -m backend.workflows.io.integration.test_connection

    # Or run directly:
    python backend/workflows/io/integration/test_connection.py
"""

import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(project_root))


def print_header(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")


def print_check(name: str, passed: bool, detail: str = "") -> None:
    status = "✓" if passed else "✗"
    print(f"  {status} {name}")
    if detail:
        print(f"    → {detail}")


def test_config() -> bool:
    """Test configuration loading."""
    print_header("1. Configuration Check")

    from backend.workflows.io.integration.config import (
        INTEGRATION_CONFIG,
        reload_config,
    )

    # Reload to pick up any env changes
    reload_config()
    from backend.workflows.io.integration.config import INTEGRATION_CONFIG

    print(f"  Mode: {INTEGRATION_CONFIG.mode}")
    print(f"  Supabase URL: {INTEGRATION_CONFIG.supabase_url or '(not set)'}")
    print(f"  Supabase Key: {'***' + INTEGRATION_CONFIG.supabase_key[-8:] if INTEGRATION_CONFIG.supabase_key else '(not set)'}")
    print(f"  Team ID: {INTEGRATION_CONFIG.team_id or '(not set)'}")
    print(f"  System User ID: {INTEGRATION_CONFIG.system_user_id or '(not set)'}")
    print(f"  Email Account ID: {INTEGRATION_CONFIG.email_account_id or '(not set)'}")
    print()

    errors = INTEGRATION_CONFIG.validate()
    if errors:
        print("  Validation errors:")
        for err in errors:
            print(f"    ✗ {err}")
        return False

    print_check("Configuration valid", True)
    return True


def test_supabase_connection() -> bool:
    """Test Supabase client connection."""
    print_header("2. Supabase Connection")

    try:
        from supabase import create_client
        print_check("supabase-py installed", True)
    except ImportError:
        print_check("supabase-py installed", False, "Run: pip install supabase")
        return False

    from backend.workflows.io.integration.config import INTEGRATION_CONFIG

    if not INTEGRATION_CONFIG.supabase_url or not INTEGRATION_CONFIG.supabase_key:
        print_check("Credentials set", False, "Set OE_SUPABASE_URL and OE_SUPABASE_KEY")
        return False

    try:
        client = create_client(
            INTEGRATION_CONFIG.supabase_url,
            INTEGRATION_CONFIG.supabase_key
        )
        print_check("Client created", True)
    except Exception as e:
        print_check("Client created", False, str(e))
        return False

    return True


def test_table_access() -> dict:
    """Test access to required tables."""
    print_header("3. Table Access Check")

    from backend.workflows.io.integration.config import INTEGRATION_CONFIG

    if not INTEGRATION_CONFIG.supabase_url or not INTEGRATION_CONFIG.supabase_key:
        print("  Skipped (no credentials)")
        return {}

    from supabase import create_client
    client = create_client(
        INTEGRATION_CONFIG.supabase_url,
        INTEGRATION_CONFIG.supabase_key
    )

    tables = {
        "teams": False,
        "clients": False,
        "events": False,
        "rooms": False,
        "products": False,
        "offers": False,
        "tasks": False,
        "emails": False,
    }

    team_id = INTEGRATION_CONFIG.team_id

    for table in tables:
        try:
            query = client.table(table).select("id").limit(1)
            if team_id and table not in ["teams"]:
                query = query.eq("team_id", team_id)
            result = query.execute()
            tables[table] = True
            count = len(result.data) if result.data else 0
            print_check(f"Table '{table}'", True, f"accessible ({count} row(s) returned)")
        except Exception as e:
            error_msg = str(e)
            if "does not exist" in error_msg.lower():
                print_check(f"Table '{table}'", False, "table not found")
            elif "permission denied" in error_msg.lower():
                print_check(f"Table '{table}'", False, "permission denied (check RLS)")
            else:
                print_check(f"Table '{table}'", False, error_msg[:50])

    return tables


def test_team_lookup() -> bool:
    """Test team lookup by ID."""
    print_header("4. Team Verification")

    from backend.workflows.io.integration.config import INTEGRATION_CONFIG

    if not INTEGRATION_CONFIG.team_id:
        print("  Skipped (OE_TEAM_ID not set)")
        return False

    if not INTEGRATION_CONFIG.supabase_url or not INTEGRATION_CONFIG.supabase_key:
        print("  Skipped (no credentials)")
        return False

    from supabase import create_client
    client = create_client(
        INTEGRATION_CONFIG.supabase_url,
        INTEGRATION_CONFIG.supabase_key
    )

    try:
        result = client.table("teams") \
            .select("id, name") \
            .eq("id", INTEGRATION_CONFIG.team_id) \
            .maybe_single() \
            .execute()

        if result.data:
            print_check("Team found", True, f"Name: {result.data.get('name', 'N/A')}")
            return True
        else:
            print_check("Team found", False, f"No team with ID {INTEGRATION_CONFIG.team_id}")
            return False
    except Exception as e:
        print_check("Team found", False, str(e))
        return False


def test_schema_columns() -> dict:
    """Check if required integration columns exist."""
    print_header("5. Integration Schema Check")

    from backend.workflows.io.integration.config import INTEGRATION_CONFIG

    if not INTEGRATION_CONFIG.supabase_url or not INTEGRATION_CONFIG.supabase_key:
        print("  Skipped (no credentials)")
        return {}

    from supabase import create_client
    client = create_client(
        INTEGRATION_CONFIG.supabase_url,
        INTEGRATION_CONFIG.supabase_key
    )

    # Required columns per table
    required_columns = {
        "events": ["current_step", "date_confirmed", "caller_step"],
        "rooms": ["deposit_required", "deposit_percent"],
    }

    results = {}

    for table, columns in required_columns.items():
        print(f"\n  Table: {table}")
        for col in columns:
            try:
                # Try to select the column - will fail if doesn't exist
                result = client.table(table).select(col).limit(1).execute()
                print_check(f"Column '{col}'", True, "exists")
                results[f"{table}.{col}"] = True
            except Exception as e:
                if "does not exist" in str(e).lower() or "column" in str(e).lower():
                    print_check(f"Column '{col}'", False, "NEEDS TO BE ADDED")
                    results[f"{table}.{col}"] = False
                else:
                    print_check(f"Column '{col}'", False, str(e)[:40])
                    results[f"{table}.{col}"] = False

    return results


def print_summary(config_ok: bool, connection_ok: bool, tables: dict, schema: dict) -> None:
    """Print final summary."""
    print_header("Summary")

    all_tables_ok = all(tables.values()) if tables else False
    all_schema_ok = all(schema.values()) if schema else False

    print(f"  Configuration:  {'✓ OK' if config_ok else '✗ FAILED'}")
    print(f"  Connection:     {'✓ OK' if connection_ok else '✗ FAILED'}")
    print(f"  Table Access:   {'✓ OK' if all_tables_ok else '✗ Some tables inaccessible'}")
    print(f"  Schema:         {'✓ OK' if all_schema_ok else '✗ Some columns missing'}")

    if not all_schema_ok and schema:
        print("\n  SQL to add missing columns:")
        missing = [k for k, v in schema.items() if not v]
        for col_path in missing:
            table, col = col_path.split(".")
            if col == "current_step":
                print(f"    ALTER TABLE {table} ADD COLUMN {col} INT DEFAULT 1;")
            elif col == "date_confirmed":
                print(f"    ALTER TABLE {table} ADD COLUMN {col} BOOLEAN DEFAULT FALSE;")
            elif col == "caller_step":
                print(f"    ALTER TABLE {table} ADD COLUMN {col} INT;")
            elif col == "deposit_required":
                print(f"    ALTER TABLE {table} ADD COLUMN {col} BOOLEAN DEFAULT FALSE;")
            elif col == "deposit_percent":
                print(f"    ALTER TABLE {table} ADD COLUMN {col} INT;")

    if config_ok and connection_ok:
        print("\n  Ready to test integration mode!")
        print("  Set OE_INTEGRATION_MODE=supabase to enable")
    else:
        print("\n  Fix the issues above before enabling integration mode")


def main():
    print("\n" + "="*60)
    print("  SUPABASE INTEGRATION CONNECTION TEST")
    print("="*60)

    # Show current env vars
    print("\nEnvironment variables detected:")
    print(f"  OE_INTEGRATION_MODE = {os.getenv('OE_INTEGRATION_MODE', '(not set)')}")
    print(f"  OE_SUPABASE_URL     = {os.getenv('OE_SUPABASE_URL', '(not set)')}")
    print(f"  OE_SUPABASE_KEY     = {'***' if os.getenv('OE_SUPABASE_KEY') else '(not set)'}")
    print(f"  OE_TEAM_ID          = {os.getenv('OE_TEAM_ID', '(not set)')}")
    print(f"  OE_SYSTEM_USER_ID   = {os.getenv('OE_SYSTEM_USER_ID', '(not set)')}")

    config_ok = test_config()
    connection_ok = test_supabase_connection() if config_ok else False
    tables = test_table_access() if connection_ok else {}
    team_ok = test_team_lookup() if connection_ok else False
    schema = test_schema_columns() if connection_ok else {}

    print_summary(config_ok, connection_ok, tables, schema)

    return 0 if (config_ok and connection_ok) else 1


if __name__ == "__main__":
    sys.exit(main())