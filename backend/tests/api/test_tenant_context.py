"""Tests for tenant context middleware."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.api.middleware.tenant_context import (
    CURRENT_TEAM_ID,
    CURRENT_MANAGER_ID,
    get_request_team_id,
    get_request_manager_id,
)


class TestTenantContextMiddleware:
    """Test tenant header extraction."""

    def test_headers_ignored_when_disabled(self):
        """Headers should be ignored when TENANT_HEADER_ENABLED != 1."""
        with patch.dict(os.environ, {"TENANT_HEADER_ENABLED": "0"}, clear=False):
            client = TestClient(app)
            response = client.get(
                "/",
                headers={"X-Team-Id": "test-team", "X-Manager-Id": "test-manager"},
            )
            assert response.status_code == 200

    def test_headers_parsed_when_enabled(self):
        """Headers should be parsed when TENANT_HEADER_ENABLED=1."""
        with patch.dict(os.environ, {"TENANT_HEADER_ENABLED": "1"}, clear=False):
            client = TestClient(app)
            response = client.get(
                "/",
                headers={"X-Team-Id": "team-123", "X-Manager-Id": "manager-456"},
            )
            assert response.status_code == 200

    def test_no_headers_still_works(self):
        """Requests without tenant headers should work normally."""
        client = TestClient(app)
        response = client.get("/")
        assert response.status_code == 200

    def test_partial_headers_work(self):
        """Only X-Team-Id without X-Manager-Id should work."""
        with patch.dict(os.environ, {"TENANT_HEADER_ENABLED": "1"}, clear=False):
            client = TestClient(app)
            response = client.get(
                "/",
                headers={"X-Team-Id": "team-only"},
            )
            assert response.status_code == 200


class TestContextvarHelpers:
    """Test contextvar helper functions."""

    def test_get_request_team_id_returns_none_by_default(self):
        """Helper should return None when no context is set."""
        # Reset contextvar to default
        CURRENT_TEAM_ID.set(None)
        assert get_request_team_id() is None

    def test_get_request_manager_id_returns_none_by_default(self):
        """Helper should return None when no context is set."""
        CURRENT_MANAGER_ID.set(None)
        assert get_request_manager_id() is None

    def test_contextvars_can_be_set_and_read(self):
        """Verify contextvars work as expected."""
        CURRENT_TEAM_ID.set("test-team-id")
        CURRENT_MANAGER_ID.set("test-manager-id")

        assert get_request_team_id() == "test-team-id"
        assert get_request_manager_id() == "test-manager-id"

        # Clean up
        CURRENT_TEAM_ID.set(None)
        CURRENT_MANAGER_ID.set(None)
