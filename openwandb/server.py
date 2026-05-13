"""
OpenWandb v0.3 — FastAPI 主服务
多租户隔离 + 分享 + 完整 API

路由组:
1. wandb SDK 兼容端点 (GraphQL, File Stream, Files)
2. 认证 API (登录/注册/登出)
3. 团队管理 API
4. API Key 管理 API
5. 分享 API
6. 内部 REST API (供 Web 前端)
7. Web UI 页面路由
"""
import json
import logging
import mimetypes
import os
from typing import Optional

from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from strawberry.fastapi import GraphQLRouter

from openwandb import auth
from openwandb import database as db
from openwandb import file_stream
from openwandb import storage
from openwandb.config import (HOST, PORT, DEFAULT_TEAM_NAME, ALLOW_REGISTRATION,
                              DEFAULT_ADMIN_USERNAME, DEFAULT_ADMIN_PASSWORD,
                              TEMPLATES_DIR, STATIC_DIR, ROOT_PATH)
from openwandb.graphql_schema import schema

# ─────────────────────────────────────────────
# 日志配置
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("openwandb")

# ─────────────────────────────────────────────
# FastAPI 应用
# ─────────────────────────────────────────────
app = FastAPI(
    title="OpenWandb",
    description="开源 WandB 兼容服务器 — 多租户版",
    version="0.3.6",
)

# 静态文件与模板 (从包内资源路径加载)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _tpl(request: Request, template_name: str, context: dict = None) -> templates.TemplateResponse:
    """渲染模板, 自动注入 base_path (反向代理路径前缀)"""
    ctx = context or {}
    ctx["request"] = request
    ctx["base_path"] = ROOT_PATH  # 模板中所有 URL 都要加这个前缀
    return templates.TemplateResponse(request, template_name, ctx)


# ─────────────────────────────────────────────
# GraphQL 端点 (wandb SDK 核心)
# ─────────────────────────────────────────────

async def get_context(request: Request) -> dict:
    user = auth.authenticate(request)
    return {"user": user, "request": request}

graphql_app = GraphQLRouter(schema, context_getter=get_context)
app.include_router(graphql_app, prefix="/graphql")


# ═════════════════════════════════════════════
# 1. wandb SDK 兼容端点
# ═════════════════════════════════════════════

@app.post("/api/v1/file_stream")
async def file_stream_v1(request: Request):
    """通用 file_stream 端点"""
    user = auth.authenticate(request)
    body = await request.json()
    run_id = body.get("run_id", "")
    entity = body.get("entity", user.get("entity", DEFAULT_TEAM_NAME))
    project = body.get("project", "default")
    result = file_stream.process_file_stream(entity, project, run_id, body,
                                             user_id=user.get("id"))
    return JSONResponse(result)


@app.post("/files/{entity}/{project}/{run_id}/file_stream")
async def file_stream_endpoint(entity: str, project: str, run_id: str, request: Request):
    """wandb SDK 的核心指标上传端点"""
    user = auth.authenticate(request)
    body = await request.json()
    logger.info(f"file_stream: {entity}/{project}/{run_id}, files={list(body.get('files', {}).keys())}")
    result = file_stream.process_file_stream(entity, project, run_id, body,
                                             user_id=user.get("id"))
    return JSONResponse(result)


@app.get("/files/{entity}/{project}/{run_id}/{filename:path}")
async def get_file(entity: str, project: str, run_id: str, filename: str,
                   request: Request):
    """下载运行的文件 — 带权限校验"""
    user = auth.get_optional_user(request)
    # 权限检查: 公开项目或已认证用户有权访问
    run = db.get_run(run_id)
    if run and user:
        if not db.user_can_access_project(user["id"], run["project_id"]):
            # 检查分享链接
            if not auth.check_share_access(request, "run", run["id"]):
                raise HTTPException(status_code=403, detail="Access denied")

    content = storage.read_file(entity, project, run_id, filename)
    if content is None:
        raise HTTPException(status_code=404, detail="File not found")
    # Detect MIME type (critical for images to display in browser)
    content_type, _ = mimetypes.guess_type(filename)
    return Response(content=content, media_type=content_type or "application/octet-stream")


@app.put("/files/{entity}/{project}/{run_id}/{filename:path}")
async def upload_file(entity: str, project: str, run_id: str, filename: str,
                      request: Request):
    """上传文件 — 带写权限校验"""
    user = auth.authenticate(request)
    content = await request.body()
    info = storage.save_file(entity, project, run_id, filename, content)
    db.register_file(run_id, filename, info["path"], info["size"], info["md5"])
    return JSONResponse({"success": True, "file": info})


# ═════════════════════════════════════════════
# 2. 认证 API
# ═════════════════════════════════════════════

@app.post("/api/v2/auth/register")
async def api_register(request: Request):
    """用户注册"""
    if not ALLOW_REGISTRATION:
        raise HTTPException(status_code=403, detail="Registration is disabled")

    body = await request.json()
    username = body.get("username", "").strip()
    password = body.get("password", "")
    display_name = body.get("display_name", "")
    email = body.get("email", "")

    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password are required")
    if len(username) < 2 or len(username) > 50:
        raise HTTPException(status_code=400, detail="Username must be 2-50 characters")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    user = db.create_user(username, password, display_name, email)
    if not user:
        raise HTTPException(status_code=409, detail="Username already exists")

    # 将新用户加入默认团队
    default_team = db.get_team_by_name(DEFAULT_TEAM_NAME)
    if default_team:
        db.add_team_member(default_team["id"], user["id"], "member")

    token = auth.create_jwt(user)
    response = JSONResponse({
        "success": True,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "display_name": user.get("display_name", ""),
        },
        "token": token,
    })
    auth.set_auth_cookie(response, token)
    return response


@app.post("/api/v2/auth/login")
async def api_login(request: Request):
    """用户登录"""
    body = await request.json()
    username = body.get("username", "").strip()
    password = body.get("password", "")

    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password are required")

    user = db.verify_user(username, password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = auth.create_jwt(user)
    response = JSONResponse({
        "success": True,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "display_name": user.get("display_name", ""),
        },
        "token": token,
    })
    auth.set_auth_cookie(response, token)
    return response


@app.post("/api/v2/auth/logout")
async def api_logout():
    """用户登出"""
    response = JSONResponse({"success": True})
    auth.clear_auth_cookie(response)
    return response


@app.get("/api/v2/auth/me")
async def api_me(request: Request):
    """获取当前登录用户信息"""
    user = auth.get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    teams = db.list_teams_for_user(user["id"])
    return {
        "user": {
            "id": user["id"],
            "username": user["username"],
            "display_name": user.get("display_name", ""),
            "email": user.get("email", ""),
            "default_team": user.get("entity", DEFAULT_TEAM_NAME),
        },
        "teams": [{"id": t["id"], "name": t["name"], "role": t.get("role", "member")} for t in teams],
    }


# ═════════════════════════════════════════════
# 3. 团队管理 API
# ═════════════════════════════════════════════

@app.get("/api/v2/teams")
async def api_list_teams(request: Request):
    """列出我的团队"""
    user = auth.require_auth(request)
    teams = db.list_teams_for_user(user["id"])
    return {"teams": teams}


@app.post("/api/v2/teams")
async def api_create_team(request: Request):
    """创建团队"""
    user = auth.require_auth(request)
    body = await request.json()
    name = body.get("name", "").strip().lower()
    display_name = body.get("display_name", name)

    if not name or len(name) < 2:
        raise HTTPException(status_code=400, detail="Team name must be at least 2 characters")

    team = db.create_team(name, display_name, user["id"])
    if not team:
        raise HTTPException(status_code=409, detail="Team name already exists")
    return {"success": True, "team": team}


@app.get("/api/v2/teams/{team_name}/members")
async def api_list_members(team_name: str, request: Request):
    """列出团队成员"""
    user = auth.require_auth(request)
    team = db.get_team_by_name(team_name)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    role = db.get_user_team_role(user["id"], team["id"])
    if not role:
        raise HTTPException(status_code=403, detail="Not a team member")

    members = db.list_team_members(team["id"])
    return {"members": members, "my_role": role}


@app.post("/api/v2/teams/{team_name}/members")
async def api_invite_member(team_name: str, request: Request):
    """邀请成员加入团队"""
    user = auth.require_auth(request)
    team = db.get_team_by_name(team_name)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    # 需要 admin 以上权限
    auth.require_team_role(request, team["id"], "admin")

    body = await request.json()
    target_username = body.get("username", "").strip()
    role = body.get("role", "member")

    if role not in ("viewer", "member", "admin"):
        raise HTTPException(status_code=400, detail="Invalid role")

    target_user = db.get_user_by_username(target_username)
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    ok = db.add_team_member(team["id"], target_user["id"], role)
    if not ok:
        raise HTTPException(status_code=409, detail="User is already a team member")
    return {"success": True}


@app.put("/api/v2/teams/{team_name}/members/{uid}")
async def api_update_member_role(team_name: str, uid: int, request: Request):
    """修改成员角色"""
    user = auth.require_auth(request)
    team = db.get_team_by_name(team_name)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    auth.require_team_role(request, team["id"], "admin")

    body = await request.json()
    new_role = body.get("role", "member")
    if new_role not in ("viewer", "member", "admin"):
        raise HTTPException(status_code=400, detail="Invalid role")

    db.update_team_member_role(team["id"], uid, new_role)
    return {"success": True}


@app.delete("/api/v2/teams/{team_name}/members/{uid}")
async def api_remove_member(team_name: str, uid: int, request: Request):
    """移除团队成员"""
    user = auth.require_auth(request)
    team = db.get_team_by_name(team_name)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    auth.require_team_role(request, team["id"], "admin")

    db.remove_team_member(team["id"], uid)
    return {"success": True}


# ═════════════════════════════════════════════
# 4. API Key 管理
# ═════════════════════════════════════════════

@app.get("/api/v2/settings/api-keys")
async def api_list_keys(request: Request):
    """列出我的 API Key"""
    user = auth.require_auth(request)
    keys = db.list_api_keys(user["id"])
    return {"api_keys": keys}


@app.post("/api/v2/settings/api-keys")
async def api_create_key(request: Request):
    """创建新 API Key (返回明文, 仅此一次)"""
    user = auth.require_auth(request)
    body = await request.json()
    name = body.get("name", "default")
    key_info = db.create_api_key(user["id"], name)
    return {
        "success": True,
        "api_key": {
            "id": key_info["id"],
            "name": key_info["name"],
            "key": key_info["raw_key"],  # 仅此一次返回明文
            "key_prefix": key_info["key_prefix"],
            "created_at": key_info["created_at"],
        }
    }


@app.delete("/api/v2/settings/api-keys/{key_id}")
async def api_delete_key(key_id: int, request: Request):
    """删除 API Key"""
    user = auth.require_auth(request)
    ok = db.delete_api_key(key_id, user["id"])
    if not ok:
        raise HTTPException(status_code=404, detail="API Key not found")
    return {"success": True}


# ═════════════════════════════════════════════
# 5. 分享 API
# ═════════════════════════════════════════════

@app.post("/api/v2/share")
async def api_create_share(request: Request):
    """创建分享链接"""
    user = auth.require_auth(request)
    body = await request.json()
    resource_type = body.get("resource_type")  # "project" or "run"
    resource_id = body.get("resource_id")
    expires_at = body.get("expires_at")  # ISO format or None

    if resource_type not in ("project", "run"):
        raise HTTPException(status_code=400, detail="resource_type must be 'project' or 'run'")
    if not resource_id:
        raise HTTPException(status_code=400, detail="resource_id is required")

    # 权限校验: 用户需要有资源访问权
    if resource_type == "project":
        if not db.user_can_access_project(user["id"], resource_id):
            raise HTTPException(status_code=403, detail="No access to this project")
    elif resource_type == "run":
        if not db.user_can_access_run(user["id"], str(resource_id)):
            raise HTTPException(status_code=403, detail="No access to this run")

    link = db.create_share_link(resource_type, resource_id, user["id"], expires_at)
    return {"success": True, "share_link": link}


@app.get("/api/v2/share/{token}")
async def api_get_share(token: str):
    """通过 token 获取分享资源"""
    link = db.get_share_link(token)
    if not link:
        raise HTTPException(status_code=404, detail="Share link not found or expired")

    if link["resource_type"] == "project":
        proj = db.get_project_by_id(link["resource_id"])
        if not proj:
            raise HTTPException(status_code=404, detail="Project not found")
        team = db.get_team_by_id(proj["team_id"])
        return {"resource_type": "project", "project": proj,
                "entity": team["name"] if team else DEFAULT_TEAM_NAME}
    elif link["resource_type"] == "run":
        # resource_id 在这里可能存的是 run table id 或 run_id string
        with db.get_db() as conn:
            run_row = conn.execute("SELECT * FROM runs WHERE id = ? OR run_id = ?",
                                   (link["resource_id"], str(link["resource_id"]))).fetchone()
        if not run_row:
            raise HTTPException(status_code=404, detail="Run not found")
        run = dict(run_row)
        run["config"] = json.loads(run.get("config_json", "{}"))
        run["summary"] = json.loads(run.get("summary_json", "{}"))
        return {"resource_type": "run", "run": run}

    raise HTTPException(status_code=400, detail="Unknown resource type")


@app.delete("/api/v2/share/{link_id}")
async def api_delete_share(link_id: int, request: Request):
    """撤销分享链接"""
    user = auth.require_auth(request)
    ok = db.delete_share_link(link_id, user["id"])
    if not ok:
        raise HTTPException(status_code=404, detail="Share link not found")
    return {"success": True}


@app.get("/api/v2/my-shares")
async def api_my_shares(request: Request):
    """列出我创建的分享链接"""
    user = auth.require_auth(request)
    links = db.list_share_links(user["id"])
    return {"share_links": links}


# ═════════════════════════════════════════════
# 6. 内部 REST API (供 Web 前端, 带权限过滤)
# ═════════════════════════════════════════════

@app.get("/api/v1/viewer")
async def api_viewer(request: Request):
    """兼容 wandb 的 viewer API"""
    user = auth.authenticate(request)
    return {
        "username": user.get("username", "local-user"),
        "entity": user.get("entity", DEFAULT_TEAM_NAME),
        "teams": user.get("teams", [DEFAULT_TEAM_NAME]),
        "flags": {}
    }


@app.post("/api/v1/runs/{run_id}/finish")
async def finish_run(run_id: str):
    """标记运行结束"""
    db.update_run_state(run_id, "finished")
    return {"success": True}


@app.post("/api/v1/runs/{run_id}/heartbeat")
async def heartbeat(run_id: str):
    """心跳"""
    db.update_run_heartbeat(run_id)
    return {"success": True}


@app.get("/api/v1/runs/{run_id}/files")
async def list_run_files_api(run_id: str):
    """获取运行的文件列表"""
    files = db.list_files(run_id)
    return {"files": files}


@app.get("/api/v2/projects")
async def api_list_projects(request: Request, team: Optional[str] = None):
    """获取项目列表 — 按权限过滤"""
    user = auth.get_optional_user(request)

    if user:
        team_id = None
        if team:
            t = db.get_team_by_name(team)
            team_id = t["id"] if t else None
        projects = db.list_projects_for_user(user["id"], team_id)
    else:
        # 未登录: 只看公开项目
        with db.get_db() as conn:
            cur = conn.execute(
                "SELECT * FROM projects WHERE visibility = 'public' ORDER BY created_at DESC"
            )
            rows = (cur or conn).fetchall()
            projects = [dict(r) for r in rows]

    for p in projects:
        p["run_count"] = db.get_project_run_count(p["id"])
        # 附加 team name
        team_obj = db.get_team_by_id(p["team_id"]) if p.get("team_id") else None
        p["entity"] = team_obj["name"] if team_obj else DEFAULT_TEAM_NAME
    return {"projects": projects}


@app.get("/api/v2/projects/{entity}/{project_name}/runs")
async def api_list_runs(entity: str, project_name: str, request: Request,
                        state: Optional[str] = None,
                        limit: int = 100, offset: int = 0):
    """获取项目下的运行列表"""
    project = db.get_project(entity, project_name)
    if not project:
        return {"runs": []}
    runs = db.list_runs(project["id"], state=state, limit=limit, offset=offset)
    for run in runs:
        run["config"] = json.loads(run.get("config_json", "{}"))
        run["summary"] = json.loads(run.get("summary_json", "{}"))
        run["tags"] = json.loads(run.get("tags_json", "[]"))
        latest = db.get_latest_metrics(run["run_id"])
        run["latest_metrics"] = latest
    return {"runs": runs}


@app.get("/api/v2/runs/{run_id}")
async def api_get_run(run_id: str):
    """获取运行详情"""
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    run["config"] = json.loads(run.get("config_json", "{}"))
    run["summary"] = json.loads(run.get("summary_json", "{}"))
    run["tags"] = json.loads(run.get("tags_json", "[]"))
    return {"run": run}


@app.get("/api/v2/runs/{run_id}/metrics")
async def api_get_metrics(run_id: str, key: Optional[str] = None):
    """获取运行的指标数据"""
    keys = db.get_metric_keys(run_id)
    if key:
        metrics = db.get_metrics(run_id, key=key)
        return {"keys": keys, "metrics": metrics}
    else:
        grouped = {}
        for k in keys:
            grouped[k] = db.get_metrics(run_id, key=k)
        return {"keys": keys, "metrics_by_key": grouped}


@app.get("/api/v2/runs/{run_id}/system_metrics")
async def api_get_system_metrics(run_id: str):
    """获取系统指标"""
    metrics = db.get_system_metrics(run_id)
    grouped = {}
    for m in metrics:
        k = m["key"]
        if k not in grouped:
            grouped[k] = []
        grouped[k].append(m)
    return {"system_metrics": grouped}


@app.get("/api/v2/runs/{run_id}/config")
async def api_get_config(run_id: str):
    """获取运行配置"""
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"config": json.loads(run.get("config_json", "{}"))}


@app.put("/api/v2/projects/{project_id}/visibility")
async def api_update_visibility(project_id: int, request: Request):
    """修改项目可见性"""
    user = auth.require_auth(request)
    proj = db.get_project_by_id(project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")

    # 需要项目写权限
    if not db.user_can_write_project(user["id"], project_id):
        raise HTTPException(status_code=403, detail="No write access")

    body = await request.json()
    visibility = body.get("visibility", "team")
    if visibility not in ("private", "team", "public"):
        raise HTTPException(status_code=400, detail="Invalid visibility")

    db.update_project_visibility(project_id, visibility)
    return {"success": True}


# ═════════════════════════════════════════════
# 7. Web UI 页面路由
# ═════════════════════════════════════════════

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """登录/注册页"""
    user = auth.get_optional_user(request)
    if user:
        return RedirectResponse(url=f"{ROOT_PATH}/", status_code=302)
    return _tpl(request, "login.html", {
        "allow_registration": ALLOW_REGISTRATION,
    })


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """用户设置页"""
    user = auth.get_current_user(request)
    if not user:
        return RedirectResponse(url=f"{ROOT_PATH}/login", status_code=302)
    api_keys = db.list_api_keys(user["id"])
    teams = db.list_teams_for_user(user["id"])
    return _tpl(request, "settings.html", {
        "user": user,
        "api_keys": api_keys,
        "teams": teams,
    })


@app.get("/teams/{team_name}", response_class=HTMLResponse)
async def team_page(request: Request, team_name: str):
    """团队管理页"""
    user = auth.get_current_user(request)
    if not user:
        return RedirectResponse(url=f"{ROOT_PATH}/login", status_code=302)

    team = db.get_team_by_name(team_name)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    role = db.get_user_team_role(user["id"], team["id"])
    if not role:
        raise HTTPException(status_code=403, detail="Not a team member")

    members = db.list_team_members(team["id"])
    projects = db.list_projects_for_user(user["id"], team["id"])
    for p in projects:
        p["run_count"] = db.get_project_run_count(p["id"])

    return _tpl(request, "team.html", {
        "user": user,
        "team": team,
        "my_role": role,
        "members": members,
        "projects": projects,
    })


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """仪表盘首页 — 项目列表"""
    user = auth.get_optional_user(request)

    if user:
        teams = db.list_teams_for_user(user["id"])
        # 默认显示用户的默认团队的项目
        team_id = user.get("default_team_id")
        projects = db.list_projects_for_user(user["id"], team_id)
    else:
        teams = []
        with db.get_db() as conn:
            cur = conn.execute(
                "SELECT * FROM projects WHERE visibility = 'public' ORDER BY created_at DESC"
            )
            rows = (cur or conn).fetchall()
            projects = [dict(r) for r in rows]

    for p in projects:
        p["run_count"] = db.get_project_run_count(p["id"])
        team_obj = db.get_team_by_id(p["team_id"]) if p.get("team_id") else None
        p["entity"] = team_obj["name"] if team_obj else DEFAULT_TEAM_NAME

    return _tpl(request, "index.html", {
        "user": user,
        "teams": teams,
        "projects": projects,
        "current_team": user.get("entity", DEFAULT_TEAM_NAME) if user else None,
    })


@app.get("/projects/{entity}/{project_name}", response_class=HTMLResponse)
async def project_page(request: Request, entity: str, project_name: str):
    """项目详情页 — 运行列表"""
    user = auth.get_optional_user(request)
    project = db.get_project(entity, project_name)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # 权限校验
    if project["visibility"] != "public":
        if not user:
            return RedirectResponse(url=f"{ROOT_PATH}/login", status_code=302)
        if not db.user_can_access_project(user["id"], project["id"]):
            # 检查分享链接
            if not auth.check_share_access(request, "project", project["id"]):
                raise HTTPException(status_code=403, detail="Access denied")

    runs = db.list_runs(project["id"])
    for run in runs:
        run["config"] = json.loads(run.get("config_json", "{}"))
        run["summary"] = json.loads(run.get("summary_json", "{}"))
        run["tags"] = json.loads(run.get("tags_json", "[]"))
        run["latest_metrics"] = db.get_latest_metrics(run["run_id"])

    # 检查用户是否有写权限 (决定是否显示分享/设置按钮)
    can_write = user and db.user_can_write_project(user["id"], project["id"]) if user else False

    return _tpl(request, "project.html", {
        "user": user,
        "project": project,
        "runs": runs,
        "entity": entity,
        "can_write": can_write,
    })


@app.get("/runs/{entity}/{project_name}/{run_id}", response_class=HTMLResponse)
async def run_page(request: Request, entity: str, project_name: str, run_id: str):
    """运行详情页 — 指标图表"""
    user = auth.get_optional_user(request)
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    # 权限校验
    project = db.get_project_by_id(run["project_id"])
    if project and project["visibility"] != "public":
        if not user:
            return RedirectResponse(url=f"{ROOT_PATH}/login", status_code=302)
        if not db.user_can_access_project(user["id"], project["id"]):
            if not auth.check_share_access(request, "run", run["id"]):
                raise HTTPException(status_code=403, detail="Access denied")

    run["config"] = json.loads(run.get("config_json", "{}"))
    run["summary"] = json.loads(run.get("summary_json", "{}"))
    run["tags"] = json.loads(run.get("tags_json", "[]"))
    metric_keys = db.get_metric_keys(run_id)

    return _tpl(request, "run.html", {
        "user": user,
        "run": run,
        "entity": entity,
        "project_name": project_name,
        "metric_keys": metric_keys,
    })


@app.get("/compare/{entity}/{project_name}", response_class=HTMLResponse)
async def compare_page(request: Request, entity: str, project_name: str,
                       runs: Optional[str] = None):
    """运行对比页"""
    user = auth.get_optional_user(request)
    project = db.get_project(entity, project_name)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    all_runs = db.list_runs(project["id"])
    for r in all_runs:
        r["config"] = json.loads(r.get("config_json", "{}"))
        r["summary"] = json.loads(r.get("summary_json", "{}"))
        r["tags"] = json.loads(r.get("tags_json", "[]"))
    selected_ids = runs.split(",") if runs else []

    return _tpl(request, "compare.html", {
        "user": user,
        "project": project,
        "runs": all_runs,
        "entity": entity,
        "selected_ids": selected_ids,
    })


# 分享链接入口页
@app.get("/s/{token}", response_class=HTMLResponse)
async def share_page(request: Request, token: str):
    """通过分享链接访问资源"""
    link = db.get_share_link(token)
    if not link:
        raise HTTPException(status_code=404, detail="Share link not found or expired")

    if link["resource_type"] == "project":
        proj = db.get_project_by_id(link["resource_id"])
        if proj:
            team = db.get_team_by_id(proj["team_id"])
            entity = team["name"] if team else DEFAULT_TEAM_NAME
            return RedirectResponse(
                url=f"{ROOT_PATH}/projects/{entity}/{proj['name']}?share_token={token}",
                status_code=302
            )
    elif link["resource_type"] == "run":
        with db.get_db() as conn:
            run_row = conn.execute("SELECT * FROM runs WHERE id = ? OR run_id = ?",
                                   (link["resource_id"], str(link["resource_id"]))).fetchone()
        if run_row:
            run = dict(run_row)
            proj = db.get_project_by_id(run["project_id"])
            if proj:
                team = db.get_team_by_id(proj["team_id"])
                entity = team["name"] if team else DEFAULT_TEAM_NAME
                return RedirectResponse(
                    url=f"{ROOT_PATH}/runs/{entity}/{proj['name']}/{run['run_id']}?share_token={token}",
                    status_code=302
                )

    raise HTTPException(status_code=404, detail="Shared resource not found")


# ─────────────────────────────────────────────
# 启动事件
# ─────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    logger.info("=" * 60)
    logger.info("  OpenWandb v0.3 Server starting...")
    logger.info("=" * 60)
    db.init_db()
    logger.info(f"  Database initialized at {db.DB_PATH}")
    logger.info(f"  Web UI:     http://{HOST}:{PORT}")
    logger.info(f"  GraphQL:    http://{HOST}:{PORT}/graphql")
    logger.info(f"  Login:      http://{HOST}:{PORT}/login")
    logger.info(f"  Default admin: {DEFAULT_ADMIN_USERNAME} / {DEFAULT_ADMIN_PASSWORD}")
    logger.info("")
    logger.info("  wandb SDK usage:")
    logger.info(f"    export WANDB_BASE_URL=http://localhost:{PORT}")
    logger.info("    export WANDB_API_KEY=local0000000000000000000000000000000000000000")
    logger.info("=" * 60)
