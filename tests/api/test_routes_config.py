"""Tests for api/routes/config.py endpoints."""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

# All config GET endpoints to smoke-test
CONFIG_GET_ENDPOINTS = [
    "/api/config/global-deposit",
    "/api/config/hil-mode",
    "/api/config/email-format",
    "/api/config/llm-provider",
    "/api/config/pre-filter",
    "/api/config/detection-mode",
    "/api/config/venue",
    "/api/config/site-visit",
    "/api/config/managers",
    "/api/config/products",
    "/api/config/menus",
    "/api/config/catalog",
    "/api/config/faq",
    "/api/config/assistant",
    "/api/config/response-style",
    "/api/config/hybrid-enforcement",
    "/api/config/product-availability",
]


def _empty_db():
    return {"events": [], "tasks": [], "config": {}}


# ---------------------------------------------------------------------------
# Parametrized GET smoke test — every config endpoint returns 200
# ---------------------------------------------------------------------------

class TestConfigGetSmoke:

    @pytest.mark.parametrize("endpoint", CONFIG_GET_ENDPOINTS)
    def test_get_returns_200(self, client, endpoint):
        """All config GET endpoints should return 200 with an empty db."""
        with patch("api.routes.config.wf_load_db", return_value=_empty_db()):
            resp = client.get(endpoint)
        assert resp.status_code == 200, f"{endpoint} returned {resp.status_code}: {resp.text}"


# ---------------------------------------------------------------------------
# GET/SET /api/config/global-deposit (thorough)
# ---------------------------------------------------------------------------

class TestGlobalDepositConfig:

    def test_get_defaults(self, client):
        with patch("api.routes.config.wf_load_db", return_value=_empty_db()):
            resp = client.get("/api/config/global-deposit")
        assert resp.status_code == 200
        data = resp.json()
        assert data["deposit_enabled"] is False
        assert data["deposit_type"] == "percentage"
        assert data["deposit_percentage"] == 30

    def test_get_from_db(self, client):
        db = {
            "events": [],
            "tasks": [],
            "config": {
                "global_deposit": {
                    "deposit_enabled": True,
                    "deposit_type": "fixed",
                    "deposit_percentage": 50,
                    "deposit_fixed_amount": 1000.0,
                    "deposit_deadline_days": 7,
                }
            },
        }
        with patch("api.routes.config.wf_load_db", return_value=db):
            resp = client.get("/api/config/global-deposit")
        assert resp.status_code == 200
        assert resp.json()["deposit_enabled"] is True
        assert resp.json()["deposit_type"] == "fixed"

    def test_set_success(self, client, admin_ctx):
        db = _empty_db()
        with patch("api.routes.config.wf_load_db", return_value=db), \
             patch("api.routes.config.wf_save_db") as mock_save:
            resp = client.post(
                "/api/config/global-deposit",
                json={
                    "deposit_enabled": True,
                    "deposit_type": "fixed",
                    "deposit_percentage": 30,
                    "deposit_fixed_amount": 750.0,
                    "deposit_deadline_days": 5,
                },
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        mock_save.assert_called_once()


# ---------------------------------------------------------------------------
# POST admin guard: non-admin should get 401
# ---------------------------------------------------------------------------

class TestConfigAdminGuard:

    CONFIG_POST_ENDPOINTS = [
        ("/api/config/global-deposit", {"deposit_enabled": False}),
        ("/api/config/hil-mode", {"enabled": False}),
        ("/api/config/llm-provider", {"intent_provider": "stub", "entity_provider": "stub", "verbalization_provider": "stub"}),
        ("/api/config/pre-filter", {"mode": "legacy"}),
        ("/api/config/detection-mode", {"mode": "unified"}),
    ]

    @pytest.mark.parametrize("endpoint,body", CONFIG_POST_ENDPOINTS)
    def test_post_requires_auth(self, client, endpoint, body):
        """POST to admin-guarded config endpoints should fail without admin context."""
        with patch("api.routes.config.wf_load_db", return_value=_empty_db()), \
             patch("api.routes.config.wf_save_db"):
            resp = client.post(endpoint, json=body)
        # Should be 401 (no user) because we didn't set admin_ctx
        assert resp.status_code == 401, f"{endpoint} returned {resp.status_code}"
