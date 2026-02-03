"""Tests for authentication middleware."""

from __future__ import annotations

import os
import sys
import pytest
from unittest.mock import patch

# Fix sys.path to prioritize project root over tests/api namespace
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Remove any test paths that might shadow the real api module
sys.path = [p for p in sys.path if 'tests/api' not in p and 'tests\\api' not in p]
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# Now import - this should find the real api module
try:
    from api.middleware.auth import (  # noqa: E402
        AuthMiddleware,
        _extract_bearer_token,
        _validate_api_key,
        _validate_supabase_jwt,
        get_current_user_id,
        get_current_user_role,
        require_admin_role,
        CURRENT_USER_ID,
        CURRENT_USER_ROLE,
        ALLOWLIST_PREFIXES,
        ALLOWLIST_EXACT,
    )
except ImportError as e:
    pytest.skip(f"Auth middleware not available: {e}", allow_module_level=True)


class TestExtractBearerToken:
    """Tests for bearer token extraction."""

    def test_valid_bearer_token(self):
        assert _extract_bearer_token("Bearer abc123") == "abc123"

    def test_bearer_with_spaces(self):
        assert _extract_bearer_token("Bearer   token_with_spaces  ") == "token_with_spaces"

    def test_empty_string(self):
        assert _extract_bearer_token("") is None

    def test_none(self):
        assert _extract_bearer_token(None) is None

    def test_no_bearer_prefix(self):
        assert _extract_bearer_token("abc123") is None

    def test_lowercase_bearer(self):
        # Should not match - Bearer is case-sensitive
        assert _extract_bearer_token("bearer abc123") is None


class TestValidateApiKey:
    """Tests for API key validation."""

    def test_valid_api_key(self):
        with patch.dict(os.environ, {"API_KEY": "secret123"}):
            is_valid, error = _validate_api_key("secret123")
            assert is_valid is True
            assert error == ""

    def test_invalid_api_key(self):
        with patch.dict(os.environ, {"API_KEY": "secret123"}):
            is_valid, error = _validate_api_key("wrong_key")
            assert is_valid is False
            assert error == "invalid_token"

    def test_missing_token(self):
        with patch.dict(os.environ, {"API_KEY": "secret123"}):
            is_valid, error = _validate_api_key(None)
            assert is_valid is False
            assert error == "missing_token"

    def test_empty_token(self):
        with patch.dict(os.environ, {"API_KEY": "secret123"}):
            is_valid, error = _validate_api_key("")
            assert is_valid is False
            assert error == "missing_token"

    def test_no_api_key_configured(self):
        with patch.dict(os.environ, {"API_KEY": ""}):
            is_valid, error = _validate_api_key("any_token")
            assert is_valid is False
            assert error == "server_misconfigured"


class TestAllowlistConfig:
    """Tests for allowlist configuration."""

    def test_health_in_allowlist(self):
        assert any("/health".startswith(prefix) for prefix in ALLOWLIST_PREFIXES)

    def test_docs_in_allowlist(self):
        assert any("/docs".startswith(prefix) for prefix in ALLOWLIST_PREFIXES)

    def test_workflow_health_in_allowlist(self):
        assert any("/api/workflow/health".startswith(prefix) for prefix in ALLOWLIST_PREFIXES)

    def test_qna_in_exact_allowlist(self):
        assert "/api/qna" in ALLOWLIST_EXACT


class TestContextVars:
    """Tests for auth context variables."""

    def test_default_user_id_is_none(self):
        # In a fresh context, should return None
        assert get_current_user_id() is None

    def test_default_user_role_is_none(self):
        assert get_current_user_role() is None


# Integration tests with FastAPI TestClient
@pytest.fixture
def test_client():
    """Create test client with fresh app instance."""
    from fastapi.testclient import TestClient
    from main import app
    return TestClient(app)


class TestAuthMiddlewareIntegration:
    """Integration tests for auth middleware with FastAPI."""

    def test_auth_disabled_passes_through(self, test_client):
        """With AUTH_ENABLED=0, all requests should pass without auth."""
        with patch.dict(os.environ, {"AUTH_ENABLED": "0"}):
            response = test_client.get("/api/workflow/health")
            # Should not be 401
            assert response.status_code != 401

    def test_auth_enabled_blocks_without_token(self, test_client):
        """With AUTH_ENABLED=1, requests without token should be blocked."""
        with patch.dict(os.environ, {"AUTH_ENABLED": "1", "API_KEY": "secret123", "AUTH_MODE": "api_key"}):
            response = test_client.post(
                "/api/start-conversation",
                json={"email_body": "test", "from_email": "test@test.com"}
            )
            assert response.status_code == 401
            assert response.json()["error"] == "unauthorized"

    def test_auth_enabled_allows_with_valid_token(self, test_client):
        """With AUTH_ENABLED=1, requests with valid token should pass."""
        with patch.dict(os.environ, {"AUTH_ENABLED": "1", "API_KEY": "secret123", "AUTH_MODE": "api_key"}):
            response = test_client.get(
                "/api/tasks/pending",
                headers={"Authorization": "Bearer secret123"}
            )
            # Should not be 401 (might be other errors, but not auth)
            assert response.status_code != 401

    def test_auth_enabled_allows_x_api_key_header(self, test_client):
        """X-Api-Key header should work as fallback."""
        with patch.dict(os.environ, {"AUTH_ENABLED": "1", "API_KEY": "secret123", "AUTH_MODE": "api_key"}):
            response = test_client.get(
                "/api/tasks/pending",
                headers={"X-Api-Key": "secret123"}
            )
            assert response.status_code != 401

    def test_health_endpoint_always_allowed(self, test_client):
        """Health endpoint should be accessible without auth."""
        with patch.dict(os.environ, {"AUTH_ENABLED": "1", "API_KEY": "secret123"}):
            response = test_client.get("/api/workflow/health")
            assert response.status_code != 401

    def test_docs_endpoint_always_allowed(self, test_client):
        """Docs endpoint should be accessible without auth."""
        with patch.dict(os.environ, {"AUTH_ENABLED": "1", "API_KEY": "secret123"}):
            response = test_client.get("/docs")
            assert response.status_code != 401

    def test_invalid_auth_mode_returns_500(self, test_client):
        """Invalid AUTH_MODE should return 500."""
        with patch.dict(os.environ, {"AUTH_ENABLED": "1", "API_KEY": "secret", "AUTH_MODE": "invalid_mode"}):
            response = test_client.get(
                "/api/tasks/pending",
                headers={"Authorization": "Bearer secret"}
            )
            assert response.status_code == 500
            assert "invalid_auth_mode" in response.json().get("detail", "")


# =============================================================================
# JWT Validation Tests (Supabase JWT Mode)
# =============================================================================

class TestValidateSupabaseJWT:
    """Tests for Supabase JWT validation."""

    @pytest.fixture
    def jwt_secret(self):
        """Standard test JWT secret."""
        return "test-jwt-secret-for-testing-only"

    def _create_token(self, payload: dict, secret: str, algorithm: str = "HS256") -> str:
        """Helper to create a JWT token."""
        import jwt
        return jwt.encode(payload, secret, algorithm=algorithm)

    def test_missing_token_returns_error(self):
        """Missing token should return error."""
        with patch.dict(os.environ, {"SUPABASE_JWT_SECRET": "secret"}):
            is_valid, error, claims = _validate_supabase_jwt(None)
            assert is_valid is False
            assert error == "missing_token"
            assert claims == {}

    def test_empty_token_returns_error(self):
        """Empty string token should return error."""
        with patch.dict(os.environ, {"SUPABASE_JWT_SECRET": "secret"}):
            is_valid, error, claims = _validate_supabase_jwt("")
            assert is_valid is False
            assert error == "missing_token"
            assert claims == {}

    def test_no_jwt_secret_configured(self):
        """Missing SUPABASE_JWT_SECRET should return misconfigured."""
        with patch.dict(os.environ, {"SUPABASE_JWT_SECRET": ""}):
            is_valid, error, claims = _validate_supabase_jwt("some_token")
            assert is_valid is False
            assert error == "server_misconfigured"

    def test_valid_token_extracts_claims(self, jwt_secret):
        """Valid JWT should extract user_id, team_id, and role from claims."""
        payload = {
            "sub": "user-uuid-123",
            "team_id": "team-abc",
            "role": "admin",
        }
        token = self._create_token(payload, jwt_secret)

        with patch.dict(os.environ, {"SUPABASE_JWT_SECRET": jwt_secret}):
            is_valid, error, claims = _validate_supabase_jwt(token)
            assert is_valid is True
            assert error == ""
            assert claims["user_id"] == "user-uuid-123"
            assert claims["team_id"] == "team-abc"
            assert claims["role"] == "admin"

    def test_app_metadata_claims_preferred(self, jwt_secret):
        """Claims in app_metadata should be used (Supabase convention)."""
        payload = {
            "sub": "user-456",
            "team_id": "top-level-team",  # Should be ignored
            "role": "user",  # Should be ignored
            "app_metadata": {
                "team_id": "app-metadata-team",
                "role": "owner",
            },
        }
        token = self._create_token(payload, jwt_secret)

        with patch.dict(os.environ, {"SUPABASE_JWT_SECRET": jwt_secret}):
            is_valid, error, claims = _validate_supabase_jwt(token)
            assert is_valid is True
            assert claims["team_id"] == "app-metadata-team"
            assert claims["role"] == "owner"

    def test_fallback_to_toplevel_if_no_app_metadata(self, jwt_secret):
        """If no app_metadata, fallback to top-level claims."""
        payload = {
            "sub": "user-789",
            "team_id": "top-level-team",
            "role": "manager",
        }
        token = self._create_token(payload, jwt_secret)

        with patch.dict(os.environ, {"SUPABASE_JWT_SECRET": jwt_secret}):
            is_valid, error, claims = _validate_supabase_jwt(token)
            assert is_valid is True
            assert claims["team_id"] == "top-level-team"
            assert claims["role"] == "manager"

    def test_default_role_is_user(self, jwt_secret):
        """If no role claim, default to 'user'."""
        payload = {"sub": "user-no-role"}
        token = self._create_token(payload, jwt_secret)

        with patch.dict(os.environ, {"SUPABASE_JWT_SECRET": jwt_secret}):
            is_valid, error, claims = _validate_supabase_jwt(token)
            assert is_valid is True
            assert claims["role"] == "user"

    def test_invalid_signature_rejected(self, jwt_secret):
        """Token signed with wrong secret should be rejected."""
        payload = {"sub": "user-123"}
        token = self._create_token(payload, "wrong-secret")

        with patch.dict(os.environ, {"SUPABASE_JWT_SECRET": jwt_secret}):
            is_valid, error, claims = _validate_supabase_jwt(token)
            assert is_valid is False
            assert error == "invalid_token"

    def test_malformed_token_rejected(self):
        """Malformed token should be rejected."""
        with patch.dict(os.environ, {"SUPABASE_JWT_SECRET": "secret"}):
            is_valid, error, claims = _validate_supabase_jwt("not.a.valid.jwt")
            assert is_valid is False
            assert error == "invalid_token"

    def test_expired_token_rejected(self, jwt_secret):
        """Expired token should return token_expired error."""
        import time
        payload = {
            "sub": "user-123",
            "exp": int(time.time()) - 3600,  # Expired 1 hour ago
        }
        token = self._create_token(payload, jwt_secret)

        with patch.dict(os.environ, {"SUPABASE_JWT_SECRET": jwt_secret}):
            is_valid, error, claims = _validate_supabase_jwt(token)
            assert is_valid is False
            assert error == "token_expired"


# =============================================================================
# Admin Role Guard Tests
# =============================================================================

class TestRequireAdminRole:
    """Tests for require_admin_role() guard function."""

    def test_unauthenticated_raises_401(self):
        """If not authenticated (no user_id), should raise 401."""
        from fastapi import HTTPException

        # Reset context vars to default (unauthenticated state)
        CURRENT_USER_ID.set(None)
        CURRENT_USER_ROLE.set(None)

        with pytest.raises(HTTPException) as exc_info:
            require_admin_role()

        assert exc_info.value.status_code == 401
        assert "Authentication required" in exc_info.value.detail

    def test_non_admin_user_raises_403(self):
        """User with role 'user' should get 403."""
        from fastapi import HTTPException

        CURRENT_USER_ID.set("user-123")
        CURRENT_USER_ROLE.set("user")

        with pytest.raises(HTTPException) as exc_info:
            require_admin_role()

        assert exc_info.value.status_code == 403
        assert "Admin role required" in exc_info.value.detail

    def test_manager_role_raises_403(self):
        """User with role 'manager' should get 403 (not admin/owner)."""
        from fastapi import HTTPException

        CURRENT_USER_ID.set("user-456")
        CURRENT_USER_ROLE.set("manager")

        with pytest.raises(HTTPException) as exc_info:
            require_admin_role()

        assert exc_info.value.status_code == 403

    def test_admin_role_allowed(self):
        """User with role 'admin' should pass."""
        CURRENT_USER_ID.set("admin-user-123")
        CURRENT_USER_ROLE.set("admin")

        # Should not raise
        require_admin_role()

    def test_owner_role_allowed(self):
        """User with role 'owner' should pass."""
        CURRENT_USER_ID.set("owner-user-456")
        CURRENT_USER_ROLE.set("owner")

        # Should not raise
        require_admin_role()

    def test_none_role_raises_403(self):
        """User with None role should get 403."""
        from fastapi import HTTPException

        CURRENT_USER_ID.set("user-with-no-role")
        CURRENT_USER_ROLE.set(None)

        with pytest.raises(HTTPException) as exc_info:
            require_admin_role()

        assert exc_info.value.status_code == 403


# =============================================================================
# JWT Mode Integration Tests
# =============================================================================

class TestJWTModeIntegration:
    """Integration tests for Supabase JWT auth mode with config endpoints."""

    @pytest.fixture
    def jwt_secret(self):
        return "integration-test-secret"

    @pytest.fixture
    def admin_token(self, jwt_secret):
        """Generate admin JWT token."""
        import jwt
        return jwt.encode(
            {"sub": "admin-user", "app_metadata": {"team_id": "team-1", "role": "admin"}},
            jwt_secret,
            algorithm="HS256",
        )

    @pytest.fixture
    def user_token(self, jwt_secret):
        """Generate regular user JWT token."""
        import jwt
        return jwt.encode(
            {"sub": "regular-user", "app_metadata": {"team_id": "team-1", "role": "user"}},
            jwt_secret,
            algorithm="HS256",
        )

    @pytest.fixture
    def test_client(self):
        """Create test client with fresh app instance."""
        from fastapi.testclient import TestClient
        from main import app
        return TestClient(app)

    def test_jwt_mode_valid_admin_can_post_config(self, test_client, jwt_secret, admin_token):
        """Admin user with valid JWT can POST to config endpoints."""
        env = {
            "AUTH_ENABLED": "1",
            "AUTH_MODE": "supabase_jwt",
            "SUPABASE_JWT_SECRET": jwt_secret,
        }
        with patch.dict(os.environ, env, clear=False):
            response = test_client.post(
                "/api/config/hil-mode",
                json={"enabled": False},
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            # Should not be 401 or 403
            assert response.status_code not in (401, 403), f"Got {response.status_code}: {response.json()}"

    def test_jwt_mode_regular_user_blocked_from_post(self, test_client, jwt_secret, user_token):
        """Regular user with valid JWT should get 403 on POST config endpoints."""
        env = {
            "AUTH_ENABLED": "1",
            "AUTH_MODE": "supabase_jwt",
            "SUPABASE_JWT_SECRET": jwt_secret,
        }
        with patch.dict(os.environ, env, clear=False):
            response = test_client.post(
                "/api/config/hil-mode",
                json={"enabled": False},
                headers={"Authorization": f"Bearer {user_token}"},
            )
            assert response.status_code == 403
            assert "Admin role required" in response.json().get("detail", "")

    def test_jwt_mode_user_can_read_config(self, test_client, jwt_secret, user_token):
        """Regular user with valid JWT can GET config endpoints."""
        env = {
            "AUTH_ENABLED": "1",
            "AUTH_MODE": "supabase_jwt",
            "SUPABASE_JWT_SECRET": jwt_secret,
        }
        with patch.dict(os.environ, env, clear=False):
            response = test_client.get(
                "/api/config/hil-mode",
                headers={"Authorization": f"Bearer {user_token}"},
            )
            # Should not be 401 (authenticated) and not 403 (reads are allowed)
            assert response.status_code not in (401, 403)

    def test_jwt_mode_no_token_returns_401(self, test_client, jwt_secret):
        """Request without token in JWT mode should return 401."""
        env = {
            "AUTH_ENABLED": "1",
            "AUTH_MODE": "supabase_jwt",
            "SUPABASE_JWT_SECRET": jwt_secret,
        }
        with patch.dict(os.environ, env, clear=False):
            response = test_client.get("/api/config/hil-mode")
            assert response.status_code == 401
            assert "missing_token" in response.json().get("detail", "")

    def test_jwt_mode_invalid_token_returns_401(self, test_client, jwt_secret):
        """Request with invalid token in JWT mode should return 401."""
        env = {
            "AUTH_ENABLED": "1",
            "AUTH_MODE": "supabase_jwt",
            "SUPABASE_JWT_SECRET": jwt_secret,
        }
        with patch.dict(os.environ, env, clear=False):
            response = test_client.get(
                "/api/config/hil-mode",
                headers={"Authorization": "Bearer invalid.token.here"},
            )
            assert response.status_code == 401
            assert "invalid_token" in response.json().get("detail", "")
