"""
OpenWandb v0.2 — Authentication module
Supports JWT (Web UI) + API Key (wandb SDK) dual-mode authentication
"""
import base64
import datetime
import logging
from functools import wraps
from typing import Optional

import jwt
from fastapi import Request, HTTPException, Response

from openwandb import database as db
from openwandb.config import JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRE_HOURS, DEFAULT_TEAM_NAME

logger = logging.getLogger("openwandb.auth")


# ─────────────────────────────────────────────
# JWT utility functions
# ─────────────────────────────────────────────

def create_jwt(user: dict) -> str:
    """Create JWT token (for Web UI cookie authentication)"""
    teams = db.list_teams_for_user(user["id"])
    default_team = None
    if user.get("default_team_id"):
        t = db.get_team_by_id(user["default_team_id"])
        if t:
            default_team = t["name"]
    if not default_team and teams:
        default_team = teams[0]["name"]

    payload = {
        "user_id": user["id"],
        "username": user["username"],
        "default_team": default_team or DEFAULT_TEAM_NAME,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=JWT_EXPIRE_HOURS),
        "iat": datetime.datetime.utcnow(),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_jwt(token: str) -> Optional[dict]:
    """Decode and verify JWT token"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        logger.debug("JWT expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.debug(f"Invalid JWT: {e}")
        return None


# ─────────────────────────────────────────────
# API Key extraction (compatible with wandb SDK)
# ─────────────────────────────────────────────

def extract_api_key(request: Request) -> Optional[str]:
    """
    Extract API Key from request.
    wandb SDK uses the following authentication methods:
    1. Authorization: Basic base64(api:KEY)
    2. Authorization: Bearer KEY
    3. X-WANDB-API-KEY: KEY
    4. Query param ?api_key=KEY
    """
    # Method 1 & 2: Authorization header
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
            if ":" in decoded:
                return decoded.split(":", 1)[1]
        except Exception:
            pass
    elif auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        # Distinguish JWT (contains '.') from API Key
        if token and "." not in token:
            return token

    # Method 3: Custom header
    api_key = request.headers.get("x-wandb-api-key")
    if api_key:
        return api_key

    # Method 4: Query parameter
    api_key = request.query_params.get("api_key")
    if api_key:
        return api_key

    return None


def extract_jwt_token(request: Request) -> Optional[str]:
    """
    Extract JWT token from request.
    Priority: Cookie > Authorization Bearer (containing '.')
    """
    # Get from cookie (used by Web UI)
    token = request.cookies.get("openwandb_token")
    if token:
        return token

    # Get from Authorization Bearer (tokens containing '.' are JWT)
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        if token and "." in token:
            return token

    return None


# ─────────────────────────────────────────────
# Unified authentication: return current user (or None)
# ─────────────────────────────────────────────

def get_current_user(request: Request) -> Optional[dict]:
    """
    Identify current user from request (automatically handles JWT and API Key).

    Returns user dict (with id, username, default_team_id, etc.), or None (unauthenticated).
    Also injects 'entity' field (= default team name) into user dict for backward compatibility.
    """
    # 1. Try API Key (wandb SDK takes priority)
    api_key = extract_api_key(request)
    if api_key:
        user = db.verify_api_key(api_key)
        if user:
            user = _enrich_user(user)
            logger.debug(f"Authenticated via API Key: {user['username']}")
            return user

    # 2. Try JWT (Web UI)
    jwt_token = extract_jwt_token(request)
    if jwt_token:
        payload = decode_jwt(jwt_token)
        if payload:
            user = db.get_user_by_id(payload["user_id"])
            if user:
                user = _enrich_user(user)
                logger.debug(f"Authenticated via JWT: {user['username']}")
                return user

    return None


def _enrich_user(user: dict) -> dict:
    """Add convenience fields to user dict"""
    # Get default team name (= entity)
    if user.get("default_team_id"):
        team = db.get_team_by_id(user["default_team_id"])
        if team:
            user["entity"] = team["name"]
            user["default_team_name"] = team["name"]
        else:
            user["entity"] = DEFAULT_TEAM_NAME
            user["default_team_name"] = DEFAULT_TEAM_NAME
    else:
        user["entity"] = DEFAULT_TEAM_NAME
        user["default_team_name"] = DEFAULT_TEAM_NAME

    # Get list of teams the user belongs to
    teams = db.list_teams_for_user(user["id"])
    user["teams"] = [t["name"] for t in teams]

    return user


# ─────────────────────────────────────────────
# Authentication middleware / decorators
# ─────────────────────────────────────────────

def authenticate(request: Request) -> dict:
    """
    Backward-compatible interface: authenticate request and return user info.
    If unauthenticated, returns default admin (permissive mode for SDK backward compatibility).
    """
    user = get_current_user(request)
    if user:
        return user

    # Return default admin when unauthenticated (maintain wandb SDK compatibility)
    admin = db.get_user_by_username("admin")
    if admin:
        return _enrich_user(admin)

    # Absolute fallback
    return {
        "id": 1,
        "username": "admin",
        "entity": DEFAULT_TEAM_NAME,
        "default_team_name": DEFAULT_TEAM_NAME,
        "teams": [DEFAULT_TEAM_NAME],
    }


def require_auth(request: Request) -> dict:
    """
    Strict authentication: must be logged in, otherwise 401.
    Used for API endpoints that require access control.
    """
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def require_team_role(request: Request, team_id: int, min_role: str = "member") -> dict:
    """
    Require user to have a minimum role in the specified team.
    Role hierarchy: owner > admin > member > viewer
    """
    user = require_auth(request)
    role = db.get_user_team_role(user["id"], team_id)
    if not role:
        raise HTTPException(status_code=403, detail="Not a team member")

    role_hierarchy = {"viewer": 0, "member": 1, "admin": 2, "owner": 3}
    if role_hierarchy.get(role, 0) < role_hierarchy.get(min_role, 0):
        raise HTTPException(status_code=403, detail=f"Requires {min_role} role or above")

    user["team_role"] = role
    return user


def require_project_access(request: Request, project_id: int) -> dict:
    """Require user to have project read access"""
    user = require_auth(request)
    if not db.user_can_access_project(user["id"], project_id):
        raise HTTPException(status_code=403, detail="No access to this project")
    return user


def require_project_write(request: Request, project_id: int) -> dict:
    """Require user to have project write access"""
    user = require_auth(request)
    if not db.user_can_write_project(user["id"], project_id):
        raise HTTPException(status_code=403, detail="No write access to this project")
    return user


# ─────────────────────────────────────────────
# Share link authentication
# ─────────────────────────────────────────────

def check_share_access(request: Request, resource_type: str, resource_id: int) -> bool:
    """
    Check if access is via a share link.
    Query parameter ?share_token=xxx or cookie.
    """
    token = request.query_params.get("share_token") or request.cookies.get("share_token")
    if not token:
        return False

    link = db.get_share_link(token)
    if not link:
        return False

    return link["resource_type"] == resource_type and link["resource_id"] == resource_id


def get_optional_user(request: Request) -> Optional[dict]:
    """
    Optional authentication: return user or None (no exception raised).
    Used for public pages (need to know login status for navigation bar, etc.).
    """
    return get_current_user(request)


# ─────────────────────────────────────────────
# Cookie utilities
# ─────────────────────────────────────────────

def set_auth_cookie(response: Response, token: str):
    """Set authentication cookie"""
    response.set_cookie(
        key="openwandb_token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=JWT_EXPIRE_HOURS * 3600,
        path="/",
    )


def clear_auth_cookie(response: Response):
    """Clear authentication cookie"""
    response.delete_cookie(
        key="openwandb_token",
        path="/",
    )
