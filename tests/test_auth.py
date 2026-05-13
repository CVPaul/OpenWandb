"""
Tests for openwandb.auth — JWT, API key extraction, permission checks.
"""
import base64
import datetime
import pytest

from openwandb import auth
from openwandb import database as db
from tests.conftest import make_request


# ═══════════════════════════════════════════════
# JWT operations
# ═══════════════════════════════════════════════

class TestJWT:
    def test_create_and_decode_jwt(self, admin_user):
        token = auth.create_jwt(admin_user)
        assert isinstance(token, str)
        payload = auth.decode_jwt(token)
        assert payload is not None
        assert payload["user_id"] == admin_user["id"]
        assert payload["username"] == "admin"
        assert "default_team" in payload

    def test_decode_jwt_invalid_token(self, tmp_data_dir):
        result = auth.decode_jwt("not.a.valid.jwt.token")
        assert result is None

    def test_decode_jwt_expired(self, admin_user, monkeypatch):
        import jwt as pyjwt
        from openwandb.config import JWT_SECRET, JWT_ALGORITHM
        # Create a token that expired 1 hour ago
        payload = {
            "user_id": admin_user["id"],
            "username": "admin",
            "default_team": "default",
            "exp": datetime.datetime.utcnow() - datetime.timedelta(hours=1),
            "iat": datetime.datetime.utcnow() - datetime.timedelta(hours=2),
        }
        expired_token = pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
        result = auth.decode_jwt(expired_token)
        assert result is None


# ═══════════════════════════════════════════════
# API Key extraction from request
# ═══════════════════════════════════════════════

class TestExtractAPIKey:
    def test_basic_auth(self, tmp_data_dir):
        api_key = "local-test-key-1234567890"
        encoded = base64.b64encode(f"api:{api_key}".encode()).decode()
        req = make_request(headers={"authorization": f"Basic {encoded}"})
        result = auth.extract_api_key(req)
        assert result == api_key

    def test_bearer_token_no_dots(self, tmp_data_dir):
        api_key = "local-abcdef1234567890abcdef"
        req = make_request(headers={"authorization": f"Bearer {api_key}"})
        result = auth.extract_api_key(req)
        assert result == api_key

    def test_bearer_token_with_dots_is_jwt(self, tmp_data_dir):
        """Bearer tokens with dots are JWT, not API keys."""
        jwt_token = "eyJ0.payload.sig"
        req = make_request(headers={"authorization": f"Bearer {jwt_token}"})
        result = auth.extract_api_key(req)
        assert result is None  # Should not extract as API key

    def test_x_wandb_api_key_header(self, tmp_data_dir):
        api_key = "local-header-key"
        req = make_request(headers={"x-wandb-api-key": api_key})
        result = auth.extract_api_key(req)
        assert result == api_key

    def test_query_param(self, tmp_data_dir):
        api_key = "local-query-key"
        req = make_request(query_params={"api_key": api_key})
        result = auth.extract_api_key(req)
        assert result == api_key

    def test_no_credentials(self, tmp_data_dir):
        req = make_request()
        result = auth.extract_api_key(req)
        assert result is None


# ═══════════════════════════════════════════════
# JWT token extraction from request
# ═══════════════════════════════════════════════

class TestExtractJWT:
    def test_from_cookie(self, tmp_data_dir):
        req = make_request(cookies={"openwandb_token": "my.jwt.token"})
        result = auth.extract_jwt_token(req)
        assert result == "my.jwt.token"

    def test_from_bearer_with_dots(self, tmp_data_dir):
        req = make_request(headers={"authorization": "Bearer header.payload.signature"})
        result = auth.extract_jwt_token(req)
        assert result == "header.payload.signature"

    def test_bearer_without_dots_returns_none(self, tmp_data_dir):
        req = make_request(headers={"authorization": "Bearer no-dots-api-key"})
        result = auth.extract_jwt_token(req)
        assert result is None

    def test_no_token(self, tmp_data_dir):
        req = make_request()
        result = auth.extract_jwt_token(req)
        assert result is None


# ═══════════════════════════════════════════════
# get_current_user (combines API Key + JWT)
# ═══════════════════════════════════════════════

class TestGetCurrentUser:
    def test_via_api_key(self, admin_user):
        # Use the default API key
        api_key = "local0000000000000000000000000000000000000000"
        encoded = base64.b64encode(f"api:{api_key}".encode()).decode()
        req = make_request(headers={"authorization": f"Basic {encoded}"})
        user = auth.get_current_user(req)
        assert user is not None
        assert user["username"] == "admin"
        assert "entity" in user

    def test_via_jwt(self, admin_user):
        token = auth.create_jwt(admin_user)
        req = make_request(cookies={"openwandb_token": token})
        user = auth.get_current_user(req)
        assert user is not None
        assert user["username"] == "admin"
        assert "entity" in user
        assert "teams" in user

    def test_no_credentials_returns_none(self, tmp_data_dir):
        req = make_request()
        user = auth.get_current_user(req)
        assert user is None


# ═══════════════════════════════════════════════
# authenticate (soft auth — fallback to admin)
# ═══════════════════════════════════════════════

class TestAuthenticate:
    def test_authenticated_user(self, admin_user):
        token = auth.create_jwt(admin_user)
        req = make_request(cookies={"openwandb_token": token})
        user = auth.authenticate(req)
        assert user["username"] == "admin"

    def test_fallback_to_admin(self, admin_user):
        """No credentials => returns default admin for backward compatibility."""
        req = make_request()
        user = auth.authenticate(req)
        assert user is not None
        assert user["username"] == "admin"
        assert "entity" in user


# ═══════════════════════════════════════════════
# require_auth (strict — raises 401)
# ═══════════════════════════════════════════════

class TestRequireAuth:
    def test_raises_401_when_no_credentials(self, tmp_data_dir):
        from fastapi import HTTPException
        req = make_request()
        with pytest.raises(HTTPException) as exc_info:
            auth.require_auth(req)
        assert exc_info.value.status_code == 401

    def test_returns_user_when_authenticated(self, admin_user):
        token = auth.create_jwt(admin_user)
        req = make_request(cookies={"openwandb_token": token})
        user = auth.require_auth(req)
        assert user["username"] == "admin"


# ═══════════════════════════════════════════════
# require_team_role (role hierarchy)
# ═══════════════════════════════════════════════

class TestRequireTeamRole:
    def test_owner_has_all_roles(self, admin_user):
        team = db.get_team_by_name("default")
        token = auth.create_jwt(admin_user)
        req = make_request(cookies={"openwandb_token": token})
        # Owner should satisfy all role requirements
        for role in ("viewer", "member", "admin", "owner"):
            user = auth.require_team_role(req, team["id"], min_role=role)
            assert user["team_role"] == "owner"

    def test_member_cannot_satisfy_admin(self, tmp_data_dir):
        from fastapi import HTTPException
        owner = db.create_user("role-owner", "pass")
        member = db.create_user("role-member", "pass")
        team = db.create_team("roleteam", "RoleTeam", owner["id"])
        db.add_team_member(team["id"], member["id"], "member")
        token = auth.create_jwt(member)
        req = make_request(cookies={"openwandb_token": token})
        with pytest.raises(HTTPException) as exc_info:
            auth.require_team_role(req, team["id"], min_role="admin")
        assert exc_info.value.status_code == 403

    def test_nonmember_raises_403(self, tmp_data_dir):
        from fastapi import HTTPException
        owner = db.create_user("nonm-owner", "pass")
        outsider = db.create_user("nonm-outsider", "pass")
        team = db.create_team("nonmteam", "NonMTeam", owner["id"])
        token = auth.create_jwt(outsider)
        req = make_request(cookies={"openwandb_token": token})
        with pytest.raises(HTTPException) as exc_info:
            auth.require_team_role(req, team["id"], min_role="viewer")
        assert exc_info.value.status_code == 403


# ═══════════════════════════════════════════════
# Share access
# ═══════════════════════════════════════════════

class TestShareAccess:
    def test_valid_share_token(self, test_project, admin_user):
        link = db.create_share_link("project", test_project["id"], admin_user["id"])
        req = make_request(query_params={"share_token": link["token"]})
        assert auth.check_share_access(req, "project", test_project["id"]) is True

    def test_wrong_resource_type(self, test_project, admin_user):
        link = db.create_share_link("project", test_project["id"], admin_user["id"])
        req = make_request(query_params={"share_token": link["token"]})
        assert auth.check_share_access(req, "run", test_project["id"]) is False

    def test_no_token(self, test_project, admin_user):
        req = make_request()
        assert auth.check_share_access(req, "project", test_project["id"]) is False
