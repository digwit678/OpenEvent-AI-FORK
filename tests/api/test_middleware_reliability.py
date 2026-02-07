"""Reliability-focused middleware tests (context isolation + deterministic limits)."""

from __future__ import annotations

import os
import sys
import pytest
from unittest.mock import patch

# Fix sys.path to prioritize project root over tests/api namespace
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path = [p for p in sys.path if 'tests/api' not in p and 'tests\\api' not in p]
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

try:
    import jwt
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient

    from api.middleware.auth import (
        AuthMiddleware,
        get_current_user_id,
        get_current_user_role,
    )
    from api.middleware.request_limits import RequestSizeLimitMiddleware
    from api.middleware.tenant_context import (
        TenantContextMiddleware,
        get_request_manager_id,
        get_request_team_id,
    )
except ImportError as e:
    pytest.skip(f"Middleware dependencies not available: {e}", allow_module_level=True)


def _jwt_token(secret: str, *, user_id: str, team_id: str, role: str) -> str:
    return jwt.encode(
        {
            "sub": user_id,
            "app_metadata": {"team_id": team_id, "role": role},
        },
        secret,
        algorithm="HS256",
    )


def _build_auth_tenant_app() -> FastAPI:
    app = FastAPI()

    # Mirror production order: tenant added first, auth added after.
    app.add_middleware(TenantContextMiddleware)
    app.add_middleware(AuthMiddleware)

    @app.get("/whoami")
    async def whoami():
        return {
            "user_id": get_current_user_id(),
            "role": get_current_user_role(),
            "team_id": get_request_team_id(),
        }

    return app


def _build_tenant_only_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(TenantContextMiddleware)

    @app.get("/tenant")
    async def tenant():
        return {
            "team_id": get_request_team_id(),
            "manager_id": get_request_manager_id(),
        }

    return app


def _build_request_limit_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestSizeLimitMiddleware)

    @app.post("/echo")
    async def echo(request: Request):
        body = await request.body()
        return {"size": len(body)}

    return app


def test_auth_context_is_cleared_after_request():
    secret = "test-secret"
    token = _jwt_token(secret, user_id="user-1", team_id="team-a", role="admin")
    app = _build_auth_tenant_app()
    client = TestClient(app)

    env = {
        "AUTH_ENABLED": "1",
        "AUTH_MODE": "supabase_jwt",
        "SUPABASE_JWT_SECRET": secret,
        "TENANT_HEADER_ENABLED": "0",
    }
    with patch.dict(os.environ, env, clear=False):
        response = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert response.json() == {
            "user_id": "user-1",
            "role": "admin",
            "team_id": "team-a",
        }

    # Outside request scope, auth context must be clean.
    assert get_current_user_id() is None
    assert get_current_user_role() is None
    assert get_request_team_id() is None


def test_jwt_team_claim_wins_when_header_override_disabled():
    secret = "test-secret"
    token = _jwt_token(secret, user_id="user-1", team_id="team-from-jwt", role="admin")
    app = _build_auth_tenant_app()
    client = TestClient(app)

    env = {
        "AUTH_ENABLED": "1",
        "AUTH_MODE": "supabase_jwt",
        "SUPABASE_JWT_SECRET": secret,
        "TENANT_HEADER_ENABLED": "0",
    }
    with patch.dict(os.environ, env, clear=False):
        response = client.get(
            "/whoami",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Team-Id": "team-from-header",
            },
        )
        assert response.status_code == 200
        assert response.json()["team_id"] == "team-from-jwt"


def test_header_override_allowed_when_explicitly_enabled():
    secret = "test-secret"
    token = _jwt_token(secret, user_id="user-1", team_id="team-from-jwt", role="admin")
    app = _build_auth_tenant_app()
    client = TestClient(app)

    env = {
        "AUTH_ENABLED": "1",
        "AUTH_MODE": "supabase_jwt",
        "SUPABASE_JWT_SECRET": secret,
        "TENANT_HEADER_ENABLED": "1",
    }
    with patch.dict(os.environ, env, clear=False):
        response = client.get(
            "/whoami",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Team-Id": "team-from-header",
            },
        )
        assert response.status_code == 200
        assert response.json()["team_id"] == "team-from-header"


def test_tenant_context_does_not_leak_between_requests():
    app = _build_tenant_only_app()
    client = TestClient(app)

    env = {
        "AUTH_MODE": "api_key",
        "TENANT_HEADER_ENABLED": "1",
    }
    with patch.dict(os.environ, env, clear=False):
        first = client.get(
            "/tenant",
            headers={"X-Team-Id": "team-1", "X-Manager-Id": "mgr-1"},
        )
        second = client.get("/tenant")

    assert first.status_code == 200
    assert first.json() == {"team_id": "team-1", "manager_id": "mgr-1"}
    assert second.status_code == 200
    assert second.json() == {"team_id": None, "manager_id": None}


def test_request_size_limit_rejects_large_payload():
    app = _build_request_limit_app()
    client = TestClient(app)

    with patch.dict(os.environ, {"REQUEST_SIZE_LIMIT_KB": "1"}, clear=False):
        response = client.post("/echo", content=(b"x" * 2048))

    assert response.status_code == 413
    assert response.json()["error"] == "request_too_large"


def test_request_size_limit_allows_small_payload_and_preserves_body():
    app = _build_request_limit_app()
    client = TestClient(app)

    with patch.dict(os.environ, {"REQUEST_SIZE_LIMIT_KB": "1"}, clear=False):
        response = client.post("/echo", content=b"ok")

    assert response.status_code == 200
    assert response.json() == {"size": 2}
