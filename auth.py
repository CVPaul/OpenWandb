"""
OpenWandb v0.2 — 认证模块
支持 JWT (Web UI) + API Key (wandb SDK) 双模认证
"""
import base64
import datetime
import logging
from functools import wraps
from typing import Optional

import jwt
from fastapi import Request, HTTPException, Response

import database as db
from config import JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRE_HOURS, DEFAULT_TEAM_NAME

logger = logging.getLogger("openwandb.auth")


# ─────────────────────────────────────────────
# JWT 工具函数
# ─────────────────────────────────────────────

def create_jwt(user: dict) -> str:
    """创建 JWT token (用于 Web UI cookie 认证)"""
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
    """解码并验证 JWT token"""
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
# API Key 提取 (兼容 wandb SDK)
# ─────────────────────────────────────────────

def extract_api_key(request: Request) -> Optional[str]:
    """
    从请求中提取 API Key
    wandb SDK 使用以下认证方式:
    1. Authorization: Basic base64(api:KEY)
    2. Authorization: Bearer KEY
    3. X-WANDB-API-KEY: KEY
    4. Query param ?api_key=KEY
    """
    # 方式 1 & 2: Authorization header
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
        # 区分 JWT (包含 '.') 和 API Key
        if token and "." not in token:
            return token

    # 方式 3: 自定义 header
    api_key = request.headers.get("x-wandb-api-key")
    if api_key:
        return api_key

    # 方式 4: Query parameter
    api_key = request.query_params.get("api_key")
    if api_key:
        return api_key

    return None


def extract_jwt_token(request: Request) -> Optional[str]:
    """
    从请求中提取 JWT token
    来源优先级: Cookie > Authorization Bearer (含 '.')
    """
    # 从 cookie 获取 (Web UI 使用)
    token = request.cookies.get("openwandb_token")
    if token:
        return token

    # 从 Authorization Bearer 获取 (含 '.' 的是 JWT)
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        if token and "." in token:
            return token

    return None


# ─────────────────────────────────────────────
# 统一认证: 返回当前用户 (or None)
# ─────────────────────────────────────────────

def get_current_user(request: Request) -> Optional[dict]:
    """
    从请求中识别当前用户 (自动处理 JWT 和 API Key)

    返回用户 dict (含 id, username, default_team_id 等), 或 None (未认证)
    同时向 user dict 注入 'entity' 字段 (= default team name) 以兼容旧逻辑
    """
    # 1. 尝试 API Key (wandb SDK 优先)
    api_key = extract_api_key(request)
    if api_key:
        user = db.verify_api_key(api_key)
        if user:
            user = _enrich_user(user)
            logger.debug(f"Authenticated via API Key: {user['username']}")
            return user

    # 2. 尝试 JWT (Web UI)
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
    """为用户 dict 添加便捷字段"""
    # 获取默认团队名 (= entity)
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

    # 获取用户所属团队列表
    teams = db.list_teams_for_user(user["id"])
    user["teams"] = [t["name"] for t in teams]

    return user


# ─────────────────────────────────────────────
# 认证中间件 / 装饰器
# ─────────────────────────────────────────────

def authenticate(request: Request) -> dict:
    """
    兼容旧接口: 认证请求并返回用户信息
    如果未认证, 返回默认管理员 (宽松模式, 保证 SDK 向后兼容)
    """
    user = get_current_user(request)
    if user:
        return user

    # 未认证时返回默认管理员 (保持 wandb SDK 兼容性)
    admin = db.get_user_by_username("admin")
    if admin:
        return _enrich_user(admin)

    # 绝对后备
    return {
        "id": 1,
        "username": "admin",
        "entity": DEFAULT_TEAM_NAME,
        "default_team_name": DEFAULT_TEAM_NAME,
        "teams": [DEFAULT_TEAM_NAME],
    }


def require_auth(request: Request) -> dict:
    """
    严格认证: 必须登录, 否则 401
    用于需要权限控制的 API 端点
    """
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def require_team_role(request: Request, team_id: int, min_role: str = "member") -> dict:
    """
    要求用户拥有指定团队中的最低角色
    角色层级: owner > admin > member > viewer
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
    """要求用户有项目读权限"""
    user = require_auth(request)
    if not db.user_can_access_project(user["id"], project_id):
        raise HTTPException(status_code=403, detail="No access to this project")
    return user


def require_project_write(request: Request, project_id: int) -> dict:
    """要求用户有项目写权限"""
    user = require_auth(request)
    if not db.user_can_write_project(user["id"], project_id):
        raise HTTPException(status_code=403, detail="No write access to this project")
    return user


# ─────────────────────────────────────────────
# 分享链接认证
# ─────────────────────────────────────────────

def check_share_access(request: Request, resource_type: str, resource_id: int) -> bool:
    """
    检查是否通过分享链接访问
    查询参数 ?share_token=xxx 或 cookie
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
    可选认证: 返回用户或 None (不抛异常)
    用于公开页面 (需要知道是否登录来显示导航栏等)
    """
    return get_current_user(request)


# ─────────────────────────────────────────────
# Cookie 工具
# ─────────────────────────────────────────────

def set_auth_cookie(response: Response, token: str):
    """设置认证 cookie"""
    response.set_cookie(
        key="openwandb_token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=JWT_EXPIRE_HOURS * 3600,
        path="/",
    )


def clear_auth_cookie(response: Response):
    """清除认证 cookie"""
    response.delete_cookie(
        key="openwandb_token",
        path="/",
    )
