"""
OpenWandb — PostgreSQL 数据库后端
API 与 _db_sqlite.py 完全一致, 通过 database.py dispatcher 自动切换

用法:
    export OPENWANDB_DB_BACKEND=postgres
    export OPENWANDB_PG_URL=postgresql://user:pass@host:5432/openwandb
    openwandb serve
"""
import json
import logging
import secrets
import time
from contextlib import contextmanager
from typing import Optional

import psycopg2
import psycopg2.extras
import psycopg2.pool

from openwandb.config import PG_URL, PG_POOL_MIN, PG_POOL_MAX

logger = logging.getLogger("openwandb.db.postgres")

# ─────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────

def _now_iso() -> str:
    import datetime
    return datetime.datetime.utcnow().isoformat() + "Z"


def _now() -> float:
    return time.time()


def _gen_token(n: int = 32) -> str:
    return secrets.token_urlsafe(n)


# ─────────────────────────────────────────────
# 数据库 Schema (PostgreSQL)
# ─────────────────────────────────────────────

_SCHEMA_PG = """
-- 用户
CREATE TABLE IF NOT EXISTS users (
    id              SERIAL PRIMARY KEY,
    username        TEXT    NOT NULL UNIQUE,
    password_hash   TEXT    NOT NULL,
    display_name    TEXT    DEFAULT '',
    email           TEXT    DEFAULT '',
    default_team_id INTEGER,
    created_at      TEXT    NOT NULL
);

-- 团队
CREATE TABLE IF NOT EXISTS teams (
    id              SERIAL PRIMARY KEY,
    name            TEXT    NOT NULL UNIQUE,
    display_name    TEXT    DEFAULT '',
    created_at      TEXT    NOT NULL
);

-- 团队成员
CREATE TABLE IF NOT EXISTS team_members (
    id          SERIAL PRIMARY KEY,
    team_id     INTEGER NOT NULL REFERENCES teams(id),
    user_id     INTEGER NOT NULL REFERENCES users(id),
    role        TEXT    NOT NULL DEFAULT 'member',
    joined_at   TEXT    NOT NULL,
    UNIQUE(team_id, user_id)
);

-- API Keys
CREATE TABLE IF NOT EXISTS api_keys (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    name        TEXT    DEFAULT 'default',
    key_hash    TEXT    NOT NULL,
    key_prefix  TEXT    NOT NULL,
    created_at  TEXT    NOT NULL,
    last_used   TEXT
);

-- 项目
CREATE TABLE IF NOT EXISTS projects (
    id          SERIAL PRIMARY KEY,
    team_id     INTEGER NOT NULL REFERENCES teams(id),
    owner_id    INTEGER NOT NULL REFERENCES users(id),
    name        TEXT    NOT NULL,
    description TEXT    DEFAULT '',
    visibility  TEXT    DEFAULT 'team',
    created_at  TEXT    NOT NULL,
    UNIQUE(team_id, name)
);

-- 运行
CREATE TABLE IF NOT EXISTS runs (
    id              SERIAL PRIMARY KEY,
    project_id      INTEGER NOT NULL REFERENCES projects(id),
    owner_id        INTEGER,
    run_id          TEXT    NOT NULL UNIQUE,
    display_name    TEXT    DEFAULT '',
    state           TEXT    DEFAULT 'running',
    config_json     TEXT    DEFAULT '{}',
    summary_json    TEXT    DEFAULT '{}',
    tags_json       TEXT    DEFAULT '[]',
    notes           TEXT    DEFAULT '',
    program         TEXT    DEFAULT '',
    host            TEXT    DEFAULT '',
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL,
    heartbeat_at    TEXT    NOT NULL
);

-- 指标
CREATE TABLE IF NOT EXISTS metrics (
    id          SERIAL PRIMARY KEY,
    run_id      TEXT    NOT NULL,
    key         TEXT    NOT NULL,
    step        INTEGER NOT NULL,
    value       DOUBLE PRECISION,
    wall_time   DOUBLE PRECISION NOT NULL
);

-- 系统指标
CREATE TABLE IF NOT EXISTS system_metrics (
    id          SERIAL PRIMARY KEY,
    run_id      TEXT    NOT NULL,
    key         TEXT    NOT NULL,
    step        INTEGER DEFAULT 0,
    value       DOUBLE PRECISION,
    wall_time   DOUBLE PRECISION NOT NULL
);

-- Artifact
CREATE TABLE IF NOT EXISTS artifacts (
    id              SERIAL PRIMARY KEY,
    run_id          TEXT    NOT NULL,
    name            TEXT    NOT NULL,
    artifact_type   TEXT    DEFAULT 'dataset',
    size            INTEGER DEFAULT 0,
    path            TEXT    DEFAULT '',
    metadata_json   TEXT    DEFAULT '{}',
    created_at      TEXT    NOT NULL
);

-- 文件
CREATE TABLE IF NOT EXISTS files (
    id          SERIAL PRIMARY KEY,
    run_id      TEXT    NOT NULL,
    name        TEXT    NOT NULL,
    path        TEXT    NOT NULL,
    size        INTEGER DEFAULT 0,
    md5         TEXT    DEFAULT '',
    created_at  TEXT    NOT NULL
);

-- 分享链接
CREATE TABLE IF NOT EXISTS share_links (
    id              SERIAL PRIMARY KEY,
    token           TEXT    NOT NULL UNIQUE,
    resource_type   TEXT    NOT NULL,
    resource_id     INTEGER NOT NULL,
    created_by      INTEGER NOT NULL REFERENCES users(id),
    expires_at      TEXT,
    created_at      TEXT    NOT NULL
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_metrics_run_key ON metrics(run_id, key);
CREATE INDEX IF NOT EXISTS idx_metrics_run_step ON metrics(run_id, step);
CREATE INDEX IF NOT EXISTS idx_system_metrics_run ON system_metrics(run_id);
CREATE INDEX IF NOT EXISTS idx_runs_project ON runs(project_id);
CREATE INDEX IF NOT EXISTS idx_runs_state ON runs(state);
CREATE INDEX IF NOT EXISTS idx_team_members_user ON team_members(user_id);
CREATE INDEX IF NOT EXISTS idx_team_members_team ON team_members(team_id);
CREATE INDEX IF NOT EXISTS idx_projects_team ON projects(team_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_prefix ON api_keys(key_prefix);
CREATE INDEX IF NOT EXISTS idx_share_links_token ON share_links(token);
"""


# ─────────────────────────────────────────────
# 连接池
# ─────────────────────────────────────────────

_pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _pool
    if _pool is None:
        logger.info(f"Creating PostgreSQL connection pool ({PG_POOL_MIN}-{PG_POOL_MAX} connections)")
        _pool = psycopg2.pool.ThreadedConnectionPool(PG_POOL_MIN, PG_POOL_MAX, PG_URL)
    return _pool


@contextmanager
def get_db():
    """获取 PostgreSQL 连接 (从连接池), 自动提交/回滚"""
    pool = _get_pool()
    conn = pool.getconn()
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        pool.putconn(conn)


def _fetchone(cur) -> Optional[dict]:
    """fetchone 并转为 dict (兼容 sqlite3.Row 行为)"""
    row = cur.fetchone()
    return dict(row) if row else None


def _fetchall(cur) -> list[dict]:
    """fetchall 并转为 dict list"""
    return [dict(r) for r in cur.fetchall()]


# ─────────────────────────────────────────────
# 初始化
# ─────────────────────────────────────────────

def init_db():
    """初始化数据库并创建默认管理员和团队"""
    import bcrypt
    from openwandb.config import DEFAULT_ADMIN_USERNAME, DEFAULT_ADMIN_PASSWORD, DEFAULT_TEAM_NAME

    pool = _get_pool()
    conn = pool.getconn()
    try:
        conn.autocommit = False
        cur = conn.cursor()
        cur.execute(_SCHEMA_PG)
        conn.commit()

        # 创建默认团队
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "INSERT INTO teams (name, display_name, created_at) VALUES (%s, %s, %s) ON CONFLICT (name) DO NOTHING",
            (DEFAULT_TEAM_NAME, DEFAULT_TEAM_NAME, _now_iso())
        )
        conn.commit()

        cur.execute("SELECT id FROM teams WHERE name = %s", (DEFAULT_TEAM_NAME,))
        team = cur.fetchone()
        team_id = team["id"] if team else 1

        # 创建默认管理员
        cur.execute("SELECT id FROM users WHERE username = %s", (DEFAULT_ADMIN_USERNAME,))
        if not cur.fetchone():
            pw_hash = bcrypt.hashpw(DEFAULT_ADMIN_PASSWORD.encode(), bcrypt.gensalt()).decode()
            cur.execute(
                "INSERT INTO users (username, password_hash, display_name, default_team_id, created_at) VALUES (%s, %s, %s, %s, %s)",
                (DEFAULT_ADMIN_USERNAME, pw_hash, "Admin", team_id, _now_iso())
            )
            conn.commit()

            cur.execute("SELECT id FROM users WHERE username = %s", (DEFAULT_ADMIN_USERNAME,))
            admin = cur.fetchone()
            if admin:
                cur.execute(
                    "INSERT INTO team_members (team_id, user_id, role, joined_at) VALUES (%s, %s, 'owner', %s) ON CONFLICT DO NOTHING",
                    (team_id, admin["id"], _now_iso())
                )
                raw_key = "local0000000000000000000000000000000000000000"
                key_hash = bcrypt.hashpw(raw_key.encode(), bcrypt.gensalt()).decode()
                cur.execute(
                    "INSERT INTO api_keys (user_id, name, key_hash, key_prefix, created_at) VALUES (%s, 'default', %s, %s, %s)",
                    (admin["id"], key_hash, raw_key[:8], _now_iso())
                )
                conn.commit()
        else:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


# ─────────────────────────────────────────────
# User 操作
# ─────────────────────────────────────────────

def create_user(username: str, password: str, display_name: str = "", email: str = "") -> Optional[dict]:
    import bcrypt
    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    now = _now_iso()
    with get_db() as cur:
        try:
            cur.execute(
                "INSERT INTO users (username, password_hash, display_name, email, created_at) VALUES (%s,%s,%s,%s,%s) RETURNING *",
                (username, pw_hash, display_name or username, email, now)
            )
            user_dict = _fetchone(cur)
            if user_dict:
                team_name = username
                cur.execute(
                    "INSERT INTO teams (name, display_name, created_at) VALUES (%s,%s,%s) ON CONFLICT (name) DO NOTHING",
                    (team_name, display_name or username, now)
                )
                cur.execute("SELECT id FROM teams WHERE name = %s", (team_name,))
                team = _fetchone(cur)
                if team:
                    cur.execute(
                        "INSERT INTO team_members (team_id, user_id, role, joined_at) VALUES (%s,%s,'owner',%s) ON CONFLICT DO NOTHING",
                        (team["id"], user_dict["id"], now)
                    )
                    cur.execute(
                        "UPDATE users SET default_team_id = %s WHERE id = %s",
                        (team["id"], user_dict["id"])
                    )
                    user_dict["default_team_id"] = team["id"]
                return user_dict
        except psycopg2.IntegrityError:
            # username 已存在, 回滚当前事务以恢复连接状态
            cur.connection.rollback()
            return None
    return None


def verify_user(username: str, password: str) -> Optional[dict]:
    import bcrypt
    with get_db() as cur:
        cur.execute("SELECT * FROM users WHERE username = %s", (username,))
        row = _fetchone(cur)
        if row and bcrypt.checkpw(password.encode(), row["password_hash"].encode()):
            return row
    return None


def get_user_by_id(user_id: int) -> Optional[dict]:
    with get_db() as cur:
        cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        return _fetchone(cur)


def get_user_by_username(username: str) -> Optional[dict]:
    with get_db() as cur:
        cur.execute("SELECT * FROM users WHERE username = %s", (username,))
        return _fetchone(cur)


# ─────────────────────────────────────────────
# API Key 操作
# ─────────────────────────────────────────────

def create_api_key(user_id: int, name: str = "default") -> dict:
    """创建 API Key, 返回含明文 key (仅此一次)"""
    import bcrypt
    raw_key = "local-" + secrets.token_hex(20)
    key_hash = bcrypt.hashpw(raw_key.encode(), bcrypt.gensalt()).decode()
    prefix = raw_key[:8]
    now = _now_iso()
    with get_db() as cur:
        cur.execute(
            "INSERT INTO api_keys (user_id, name, key_hash, key_prefix, created_at) VALUES (%s,%s,%s,%s,%s) RETURNING *",
            (user_id, name, key_hash, prefix, now)
        )
        result = _fetchone(cur)
        result["raw_key"] = raw_key
        return result


def verify_api_key(raw_key: str) -> Optional[dict]:
    """验证 API Key 并返回关联的用户"""
    import bcrypt
    prefix = raw_key[:8]
    with get_db() as cur:
        cur.execute("SELECT * FROM api_keys WHERE key_prefix = %s", (prefix,))
        rows = _fetchall(cur)
        for row in rows:
            if bcrypt.checkpw(raw_key.encode(), row["key_hash"].encode()):
                cur.execute("UPDATE api_keys SET last_used = %s WHERE id = %s", (_now_iso(), row["id"]))
                cur.execute("SELECT * FROM users WHERE id = %s", (row["user_id"],))
                return _fetchone(cur)
    # 兼容旧默认 key
    if raw_key == "local0000000000000000000000000000000000000000":
        with get_db() as cur:
            cur.execute("SELECT * FROM users ORDER BY id LIMIT 1")
            return _fetchone(cur)
    return None


def list_api_keys(user_id: int) -> list:
    with get_db() as cur:
        cur.execute(
            "SELECT id, name, key_prefix, created_at, last_used FROM api_keys WHERE user_id = %s ORDER BY id DESC",
            (user_id,)
        )
        return _fetchall(cur)


def delete_api_key(key_id: int, user_id: int) -> bool:
    with get_db() as cur:
        cur.execute("DELETE FROM api_keys WHERE id = %s AND user_id = %s", (key_id, user_id))
        return cur.rowcount > 0


# ─────────────────────────────────────────────
# Team 操作
# ─────────────────────────────────────────────

def create_team(name: str, display_name: str, owner_id: int) -> Optional[dict]:
    now = _now_iso()
    with get_db() as cur:
        try:
            cur.execute(
                "INSERT INTO teams (name, display_name, created_at) VALUES (%s,%s,%s) RETURNING *",
                (name, display_name, now)
            )
            team = _fetchone(cur)
            if team:
                cur.execute(
                    "INSERT INTO team_members (team_id, user_id, role, joined_at) VALUES (%s,%s,'owner',%s)",
                    (team["id"], owner_id, now)
                )
                return team
        except psycopg2.IntegrityError:
            cur.connection.rollback()
            return None
    return None


def get_team_by_name(name: str) -> Optional[dict]:
    with get_db() as cur:
        cur.execute("SELECT * FROM teams WHERE name = %s", (name,))
        return _fetchone(cur)


def get_team_by_id(team_id: int) -> Optional[dict]:
    with get_db() as cur:
        cur.execute("SELECT * FROM teams WHERE id = %s", (team_id,))
        return _fetchone(cur)


def list_teams_for_user(user_id: int) -> list:
    with get_db() as cur:
        cur.execute(
            """SELECT t.*, tm.role FROM teams t
               JOIN team_members tm ON t.id = tm.team_id
               WHERE tm.user_id = %s ORDER BY t.name""",
            (user_id,)
        )
        return _fetchall(cur)


def get_user_team_role(user_id: int, team_id: int) -> Optional[str]:
    with get_db() as cur:
        cur.execute(
            "SELECT role FROM team_members WHERE team_id = %s AND user_id = %s",
            (team_id, user_id)
        )
        row = _fetchone(cur)
        return row["role"] if row else None


def list_team_members(team_id: int) -> list:
    with get_db() as cur:
        cur.execute(
            """SELECT u.id, u.username, u.display_name, u.email, tm.role, tm.joined_at
               FROM users u JOIN team_members tm ON u.id = tm.user_id
               WHERE tm.team_id = %s ORDER BY tm.role, u.username""",
            (team_id,)
        )
        return _fetchall(cur)


def add_team_member(team_id: int, user_id: int, role: str = "member") -> bool:
    with get_db() as cur:
        try:
            cur.execute(
                "INSERT INTO team_members (team_id, user_id, role, joined_at) VALUES (%s,%s,%s,%s)",
                (team_id, user_id, role, _now_iso())
            )
            return True
        except psycopg2.IntegrityError:
            cur.connection.rollback()
            return False


def update_team_member_role(team_id: int, user_id: int, role: str) -> bool:
    with get_db() as cur:
        cur.execute(
            "UPDATE team_members SET role = %s WHERE team_id = %s AND user_id = %s",
            (role, team_id, user_id)
        )
        return cur.rowcount > 0


def remove_team_member(team_id: int, user_id: int) -> bool:
    with get_db() as cur:
        cur.execute(
            "DELETE FROM team_members WHERE team_id = %s AND user_id = %s",
            (team_id, user_id)
        )
        return cur.rowcount > 0


# ─────────────────────────────────────────────
# 权限检查
# ─────────────────────────────────────────────

def user_can_access_project(user_id: int, project_id: int) -> bool:
    with get_db() as cur:
        cur.execute("SELECT * FROM projects WHERE id = %s", (project_id,))
        proj = _fetchone(cur)
        if not proj:
            return False
        if proj["visibility"] == "public":
            return True
        if proj["owner_id"] == user_id:
            return True
        if proj["visibility"] == "team":
            cur.execute(
                "SELECT role FROM team_members WHERE team_id = %s AND user_id = %s",
                (proj["team_id"], user_id)
            )
            return cur.fetchone() is not None
    return False


def user_can_write_project(user_id: int, project_id: int) -> bool:
    with get_db() as cur:
        cur.execute("SELECT * FROM projects WHERE id = %s", (project_id,))
        proj = _fetchone(cur)
        if not proj:
            return False
        if proj["owner_id"] == user_id:
            return True
        cur.execute(
            "SELECT role FROM team_members WHERE team_id = %s AND user_id = %s",
            (proj["team_id"], user_id)
        )
        row = _fetchone(cur)
        if row and row["role"] in ("owner", "admin", "member"):
            return True
    return False


def user_can_access_run(user_id: int, run_id) -> bool:
    with get_db() as cur:
        cur.execute(
            "SELECT project_id FROM runs WHERE id = %s OR run_id = %s",
            (run_id, str(run_id))
        )
        run = _fetchone(cur)
        if not run:
            return False
        return user_can_access_project(user_id, run["project_id"])


# ─────────────────────────────────────────────
# Project 操作
# ─────────────────────────────────────────────

def get_or_create_project(team_name: str, project_name: str, owner_id: int = None) -> dict:
    with get_db() as cur:
        cur.execute("SELECT * FROM teams WHERE name = %s", (team_name,))
        team = _fetchone(cur)
        if not team:
            cur.execute(
                "INSERT INTO teams (name, display_name, created_at) VALUES (%s,%s,%s) RETURNING *",
                (team_name, team_name, _now_iso())
            )
            team = _fetchone(cur)
            if owner_id:
                cur.execute(
                    "INSERT INTO team_members (team_id, user_id, role, joined_at) VALUES (%s,%s,'owner',%s) ON CONFLICT DO NOTHING",
                    (team["id"], owner_id, _now_iso())
                )

        cur.execute(
            "SELECT * FROM projects WHERE team_id = %s AND name = %s",
            (team["id"], project_name)
        )
        row = _fetchone(cur)
        if row:
            return row

        oid = owner_id or 1
        cur.execute(
            "INSERT INTO projects (team_id, owner_id, name, visibility, created_at) VALUES (%s,%s,%s,'team',%s) RETURNING *",
            (team["id"], oid, project_name, _now_iso())
        )
        return _fetchone(cur)


def list_projects_for_user(user_id: int, team_id: int = None) -> list:
    with get_db() as cur:
        if team_id:
            cur.execute(
                """SELECT p.* FROM projects p
                   WHERE p.team_id = %s AND (
                       p.visibility = 'public'
                       OR p.owner_id = %s
                       OR (p.visibility = 'team' AND EXISTS (
                           SELECT 1 FROM team_members tm WHERE tm.team_id = p.team_id AND tm.user_id = %s
                       ))
                   ) ORDER BY p.created_at DESC""",
                (team_id, user_id, user_id)
            )
        else:
            cur.execute(
                """SELECT p.* FROM projects p
                   WHERE p.visibility = 'public'
                      OR p.owner_id = %s
                      OR (p.visibility = 'team' AND EXISTS (
                          SELECT 1 FROM team_members tm WHERE tm.team_id = p.team_id AND tm.user_id = %s
                      ))
                   ORDER BY p.created_at DESC""",
                (user_id, user_id)
            )
        return _fetchall(cur)


def get_project(team_name: str, project_name: str) -> Optional[dict]:
    with get_db() as cur:
        cur.execute(
            """SELECT p.* FROM projects p
               JOIN teams t ON p.team_id = t.id
               WHERE t.name = %s AND p.name = %s""",
            (team_name, project_name)
        )
        return _fetchone(cur)


def get_project_by_id(project_id: int) -> Optional[dict]:
    with get_db() as cur:
        cur.execute("SELECT * FROM projects WHERE id = %s", (project_id,))
        return _fetchone(cur)


def update_project_visibility(project_id: int, visibility: str) -> bool:
    with get_db() as cur:
        cur.execute(
            "UPDATE projects SET visibility = %s WHERE id = %s",
            (visibility, project_id)
        )
        return cur.rowcount > 0


def get_project_run_count(project_id: int) -> int:
    with get_db() as cur:
        cur.execute("SELECT COUNT(*) as cnt FROM runs WHERE project_id = %s", (project_id,))
        row = _fetchone(cur)
        return row["cnt"] if row else 0


def get_project_team(project_id: int) -> Optional[dict]:
    with get_db() as cur:
        cur.execute(
            "SELECT t.* FROM teams t JOIN projects p ON t.id = p.team_id WHERE p.id = %s",
            (project_id,)
        )
        return _fetchone(cur)


# ─────────────────────────────────────────────
# Run 操作
# ─────────────────────────────────────────────

def upsert_run(project_id: int, run_id: str, display_name: str = "",
               config: dict = None, tags: list = None, notes: str = "",
               program: str = "", host: str = "", state: str = "running",
               owner_id: int = None) -> dict:
    now = _now_iso()
    config_json = json.dumps(config or {})
    tags_json = json.dumps(tags or [])

    with get_db() as cur:
        cur.execute("SELECT * FROM runs WHERE run_id = %s", (run_id,))
        existing = _fetchone(cur)
        if existing:
            updates, params = [], []
            if display_name:
                updates.append("display_name = %s"); params.append(display_name)
            if config:
                old_config = json.loads(existing["config_json"])
                old_config.update(config)
                updates.append("config_json = %s"); params.append(json.dumps(old_config))
            if tags:
                updates.append("tags_json = %s"); params.append(tags_json)
            if notes:
                updates.append("notes = %s"); params.append(notes)
            if state:
                updates.append("state = %s"); params.append(state)
            updates.append("updated_at = %s"); params.append(now)
            updates.append("heartbeat_at = %s"); params.append(now)
            params.append(run_id)
            cur.execute(f"UPDATE runs SET {', '.join(updates)} WHERE run_id = %s", params)
        else:
            if not display_name:
                display_name = f"run-{run_id[:8]}"
            cur.execute(
                """INSERT INTO runs (project_id, owner_id, run_id, display_name, state,
                   config_json, tags_json, notes, program, host, created_at, updated_at, heartbeat_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (project_id, owner_id, run_id, display_name, state, config_json,
                 tags_json, notes, program, host, now, now, now)
            )
        cur.execute("SELECT * FROM runs WHERE run_id = %s", (run_id,))
        return _fetchone(cur)


def get_run(run_id: str) -> Optional[dict]:
    with get_db() as cur:
        cur.execute("SELECT * FROM runs WHERE run_id = %s", (run_id,))
        return _fetchone(cur)


def list_runs(project_id: int, state: str = None, limit: int = 100, offset: int = 0) -> list:
    with get_db() as cur:
        if state:
            cur.execute(
                "SELECT * FROM runs WHERE project_id = %s AND state = %s ORDER BY created_at DESC LIMIT %s OFFSET %s",
                (project_id, state, limit, offset)
            )
        else:
            cur.execute(
                "SELECT * FROM runs WHERE project_id = %s ORDER BY created_at DESC LIMIT %s OFFSET %s",
                (project_id, limit, offset)
            )
        return _fetchall(cur)


def update_run_state(run_id: str, state: str):
    with get_db() as cur:
        cur.execute("UPDATE runs SET state = %s, updated_at = %s WHERE run_id = %s", (state, _now_iso(), run_id))


def update_run_summary(run_id: str, summary: dict):
    with get_db() as cur:
        cur.execute("SELECT summary_json FROM runs WHERE run_id = %s", (run_id,))
        existing = _fetchone(cur)
        if existing:
            old = json.loads(existing["summary_json"])
            old.update(summary)
            cur.execute("UPDATE runs SET summary_json = %s, updated_at = %s WHERE run_id = %s",
                        (json.dumps(old), _now_iso(), run_id))


def update_run_config(run_id: str, config: dict):
    with get_db() as cur:
        cur.execute("SELECT config_json FROM runs WHERE run_id = %s", (run_id,))
        existing = _fetchone(cur)
        if existing:
            old = json.loads(existing["config_json"])
            old.update(config)
            cur.execute("UPDATE runs SET config_json = %s, updated_at = %s WHERE run_id = %s",
                        (json.dumps(old), _now_iso(), run_id))


def update_run_heartbeat(run_id: str):
    with get_db() as cur:
        cur.execute("UPDATE runs SET heartbeat_at = %s WHERE run_id = %s", (_now_iso(), run_id))


# ─────────────────────────────────────────────
# Metrics
# ─────────────────────────────────────────────

def insert_metrics(run_id: str, metrics_list: list[dict]):
    with get_db() as cur:
        data = [(run_id, m["key"], m["step"], m["value"], m.get("wall_time", _now())) for m in metrics_list]
        psycopg2.extras.execute_values(
            cur,
            "INSERT INTO metrics (run_id, key, step, value, wall_time) VALUES %s",
            data
        )


def get_metrics(run_id: str, key: str = None, limit: int = 10000) -> list:
    with get_db() as cur:
        if key:
            cur.execute(
                "SELECT * FROM metrics WHERE run_id = %s AND key = %s ORDER BY step ASC LIMIT %s",
                (run_id, key, limit)
            )
        else:
            cur.execute(
                "SELECT * FROM metrics WHERE run_id = %s ORDER BY step ASC LIMIT %s",
                (run_id, limit)
            )
        return _fetchall(cur)


def get_metric_keys(run_id: str) -> list[str]:
    with get_db() as cur:
        cur.execute("SELECT DISTINCT key FROM metrics WHERE run_id = %s ORDER BY key", (run_id,))
        return [r["key"] for r in _fetchall(cur)]


def get_latest_metrics(run_id: str) -> dict:
    with get_db() as cur:
        # 用 DISTINCT ON 代替 SQLite 的 GROUP BY + 子查询, 更高效
        cur.execute(
            """SELECT DISTINCT ON (key) key, value, step
               FROM metrics WHERE run_id = %s
               ORDER BY key, step DESC""",
            (run_id,)
        )
        rows = _fetchall(cur)
        return {r["key"]: {"value": r["value"], "step": r["step"]} for r in rows}


def insert_system_metrics(run_id: str, metrics_list: list[dict]):
    with get_db() as cur:
        data = [(run_id, m["key"], m.get("step", 0), m["value"], m.get("wall_time", _now())) for m in metrics_list]
        psycopg2.extras.execute_values(
            cur,
            "INSERT INTO system_metrics (run_id, key, step, value, wall_time) VALUES %s",
            data
        )


def get_system_metrics(run_id: str) -> list:
    with get_db() as cur:
        cur.execute(
            "SELECT * FROM system_metrics WHERE run_id = %s ORDER BY wall_time ASC", (run_id,)
        )
        return _fetchall(cur)


# ─────────────────────────────────────────────
# Artifact + File
# ─────────────────────────────────────────────

def create_artifact(run_id: str, name: str, artifact_type: str = "dataset", metadata: dict = None) -> dict:
    with get_db() as cur:
        cur.execute(
            "INSERT INTO artifacts (run_id, name, artifact_type, metadata_json, created_at) VALUES (%s,%s,%s,%s,%s) RETURNING *",
            (run_id, name, artifact_type, json.dumps(metadata or {}), _now_iso())
        )
        return _fetchone(cur)


def register_file(run_id: str, name: str, path: str, size: int = 0, md5: str = "") -> dict:
    with get_db() as cur:
        cur.execute(
            "INSERT INTO files (run_id, name, path, size, md5, created_at) VALUES (%s,%s,%s,%s,%s,%s) RETURNING *",
            (run_id, name, path, size, md5, _now_iso())
        )
        return _fetchone(cur)


def list_files(run_id: str) -> list:
    with get_db() as cur:
        cur.execute("SELECT * FROM files WHERE run_id = %s ORDER BY name", (run_id,))
        return _fetchall(cur)


def list_artifacts(run_id: str) -> list:
    with get_db() as cur:
        cur.execute(
            "SELECT * FROM artifacts WHERE run_id = %s ORDER BY created_at DESC",
            (run_id,)
        )
        result = []
        for d in _fetchall(cur):
            try:
                d["metadata"] = json.loads(d.get("metadata_json", "{}"))
            except (json.JSONDecodeError, TypeError):
                d["metadata"] = {}
            result.append(d)
        return result


# ─────────────────────────────────────────────
# Share Links
# ─────────────────────────────────────────────

def create_share_link(resource_type: str, resource_id: int, created_by: int,
                      expires_at: str = None) -> dict:
    token = _gen_token()
    with get_db() as cur:
        cur.execute(
            "INSERT INTO share_links (token, resource_type, resource_id, created_by, expires_at, created_at) VALUES (%s,%s,%s,%s,%s,%s) RETURNING *",
            (token, resource_type, resource_id, created_by, expires_at, _now_iso())
        )
        return _fetchone(cur)


def get_share_link(token: str) -> Optional[dict]:
    with get_db() as cur:
        cur.execute("SELECT * FROM share_links WHERE token = %s", (token,))
        row = _fetchone(cur)
        if row:
            if row.get("expires_at"):
                from datetime import datetime
                try:
                    exp = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
                    if datetime.utcnow().replace(tzinfo=exp.tzinfo) > exp:
                        return None
                except Exception:
                    pass
            return row
    return None


def list_share_links(user_id: int) -> list:
    with get_db() as cur:
        cur.execute(
            "SELECT * FROM share_links WHERE created_by = %s ORDER BY created_at DESC",
            (user_id,)
        )
        return _fetchall(cur)


def delete_share_link(link_id: int, user_id: int) -> bool:
    with get_db() as cur:
        cur.execute("DELETE FROM share_links WHERE id = %s AND created_by = %s", (link_id, user_id))
        return cur.rowcount > 0
