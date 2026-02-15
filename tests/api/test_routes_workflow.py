"""Tests for api/routes/workflow.py endpoints."""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest


class TestWorkflowHealth:
    """GET /api/workflow/health"""

    def test_health_prod_mode(self, client):
        """In production mode, returns ok without db_path."""
        with patch.dict(os.environ, {"ENV": "prod"}, clear=False):
            # _IS_DEV is set at import time, so we patch it directly
            with patch("api.routes.workflow._IS_DEV", False):
                resp = client.get("/api/workflow/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "db_path" not in data

    def test_health_dev_mode(self, client):
        """In dev mode, returns ok AND db_path."""
        with patch("api.routes.workflow._IS_DEV", True):
            resp = client.get("/api/workflow/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "db_path" in data


class TestHILStatus:
    """GET /api/workflow/hil-status"""

    def test_hil_status_returns_boolean(self, client):
        """Should return hil_all_replies_enabled as a boolean."""
        with patch("api.routes.workflow.is_hil_all_replies_enabled", return_value=False):
            resp = client.get("/api/workflow/hil-status")
        assert resp.status_code == 200
        data = resp.json()
        assert "hil_all_replies_enabled" in data
        assert data["hil_all_replies_enabled"] is False

    def test_hil_status_enabled(self, client):
        with patch("api.routes.workflow.is_hil_all_replies_enabled", return_value=True):
            resp = client.get("/api/workflow/hil-status")
        assert resp.status_code == 200
        assert resp.json()["hil_all_replies_enabled"] is True
