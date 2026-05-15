"""
OpenWandb v0.2 — Database module
Multi-tenant isolation: Team → Project → Run three-level permission hierarchy
"""
import json
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from typing import Optional

from openwandb.config import DB_PATH


# ─────────────────────────────────────────────
# Utility functions
# ─────────────────────────────────────────────

def _now_iso() -> str:
    import datetime
    return datetime.datetime.utcnow().isoformat() + "Z"


def _now() -> float:
    return time.time()


def _gen_token(n: int = 32) -> str:
    return secrets.token_urlsafe(n)


# ─────────────────────────────────────────────
# Database Schema
# ─────────────────────────────────────────────

_SCHEMA = """
-- Users
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT    NOT NULL UNIQUE,
    password_hash   TEXT    NOT NULL,
    display_name    TEXT    DEFAULT '',
    email           TEXT    DEFAULT '',
    default_team_id INTEGER,
    created_at      TEXT    NOT NULL
);

-- Teams (corresponds to wandb entity, multi-tenant isolation unit)
CREATE TABLE IF NOT EXISTS teams (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL UNIQUE,
    display_name    TEXT    DEFAULT '',
    created_at      TEXT    NOT NULL
);

-- Team members (many-to-many, with roles)
CREATE TABLE IF NOT EXISTS team_members (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id     INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    role        TEXT    NOT NULL DEFAULT 'member',
    joined_at   TEXT    NOT NULL,
    FOREIGN KEY (team_id) REFERENCES teams(id),
    FOREIGN KEY (user_id) REFERENCES users(id),
    UNIQUE(team_id, user_id)
);

-- API Keys (user-level, supports wandb SDK authentication)
CREATE TABLE IF NOT EXISTS api_keys (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    name        TEXT    DEFAULT 'default',
    key_hash    TEXT    NOT NULL,
    key_prefix  TEXT    NOT NULL,
    created_at  TEXT    NOT NULL,
    last_used   TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Projects
CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id     INTEGER NOT NULL,
    owner_id    INTEGER NOT NULL,
    name        TEXT    NOT NULL,
    description TEXT    DEFAULT '',
    visibility  TEXT    DEFAULT 'team',
    created_at  TEXT    NOT NULL,
    FOREIGN KEY (team_id) REFERENCES teams(id),
    FOREIGN KEY (owner_id) REFERENCES users(id),
    UNIQUE(team_id, name)
);

-- Runs
CREATE TABLE IF NOT EXISTS runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      INTEGER NOT NULL,
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
    heartbeat_at    TEXT    NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

-- Metrics
CREATE TABLE IF NOT EXISTS metrics (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT    NOT NULL,
    key         TEXT    NOT NULL,
    step        INTEGER NOT NULL,
    value       REAL,
    wall_time   REAL    NOT NULL
);

-- System metrics
CREATE TABLE IF NOT EXISTS system_metrics (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT    NOT NULL,
    key         TEXT    NOT NULL,
    step        INTEGER DEFAULT 0,
    value       REAL,
    wall_time   REAL    NOT NULL
);

-- Artifact
CREATE TABLE IF NOT EXISTS artifacts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT    NOT NULL,
    name            TEXT    NOT NULL,
    artifact_type   TEXT    DEFAULT 'dataset',
    size            INTEGER DEFAULT 0,
    path            TEXT    DEFAULT '',
    metadata_json   TEXT    DEFAULT '{}',
    created_at      TEXT    NOT NULL
);

-- Files
CREATE TABLE IF NOT EXISTS files (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT    NOT NULL,
    name        TEXT    NOT NULL,
    path        TEXT    NOT NULL,
    size        INTEGER DEFAULT 0,
    md5         TEXT    DEFAULT '',
    created_at  TEXT    NOT NULL
);

-- Share links
CREATE TABLE IF NOT EXISTS share_links (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    token           TEXT    NOT NULL UNIQUE,
    resource_type   TEXT    NOT NULL,
    resource_id     INTEGER NOT NULL,
    created_by      INTEGER NOT NULL,
    expires_at      TEXT,
    created_at      TEXT    NOT NULL,
    FOREIGN KEY (created_by) REFERENCES users(id)
);

-- Indexes
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
# Database connection
# ─────────────────────────────────────────────

def init_db():
    """Initialize database and create default admin user and team"""
    import bcrypt
    from openwandb.config import DEFAULT_ADMIN_USERNAME, DEFAULT_ADMIN_PASSWORD, DEFAULT_TEAM_NAME

    conn = sqlite3.connect(str(DB_PATH))
    conn.executescript(_SCHEMA)

    # Create default team
    try:
        conn.execute(
            "INSERT INTO teams (name, display_name, created_at) VALUES (?, ?, ?)",
            (DEFAULT_TEAM_NAME, DEFAULT_TEAM_NAME, _now_iso())
        )
    except sqlite3.IntegrityError:
        pass

    team = conn.execute("SELECT id FROM teams WHERE name = ?", (DEFAULT_TEAM_NAME,)).fetchone()
    team_id = team[0] if team else 1

    # Create default admin
    try:
        pw_hash = bcrypt.hashpw(DEFAULT_ADMIN_PASSWORD.encode(), bcrypt.gensalt()).decode()
        conn.execute(
            "INSERT INTO users (username, password_hash, display_name, default_team_id, created_at) VALUES (?, ?, ?, ?, ?)",
            (DEFAULT_ADMIN_USERNAME, pw_hash, "Admin", team_id, _now_iso())
        )
        admin = conn.execute("SELECT id FROM users WHERE username = ?", (DEFAULT_ADMIN_USERNAME,)).fetchone()
        if admin:
            # Add admin to default team (owner)
            conn.execute(
                "INSERT OR IGNORE INTO team_members (team_id, user_id, role, joined_at) VALUES (?, ?, 'owner', ?)",
                (team_id, admin[0], _now_iso())
            )
            # Create default API Key
            raw_key = "local0000000000000000000000000000000000000000"
            key_hash = bcrypt.hashpw(raw_key.encode(), bcrypt.gensalt()).decode()
            conn.execute(
                "INSERT INTO api_keys (user_id, name, key_hash, key_prefix, created_at) VALUES (?, 'default', ?, ?, ?)",
                (admin[0], key_hash, raw_key[:8], _now_iso())
            )
    except sqlite3.IntegrityError:
        pass

    conn.commit()
    conn.close()


@contextmanager
def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ─────────────────────────────────────────────
# User operations
# ─────────────────────────────────────────────

def create_user(username: str, password: str, display_name: str = "", email: str = "") -> Optional[dict]:
    import bcrypt
    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    now = _now_iso()
    with get_db() as conn:
        try:
            conn.execute(
                "INSERT INTO users (username, password_hash, display_name, email, created_at) VALUES (?,?,?,?,?)",
                (username, pw_hash, display_name or username, email, now)
            )
            user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
            if user:
                user_dict = dict(user)
                # Automatically create personal team
                team_name = username
                try:
                    conn.execute(
                        "INSERT INTO teams (name, display_name, created_at) VALUES (?,?,?)",
                        (team_name, display_name or username, now)
                    )
                except sqlite3.IntegrityError:
                    pass
                team = conn.execute("SELECT id FROM teams WHERE name = ?", (team_name,)).fetchone()
                if team:
                    conn.execute(
                        "INSERT OR IGNORE INTO team_members (team_id, user_id, role, joined_at) VALUES (?,?,'owner',?)",
                        (team[0], user_dict["id"], now)
                    )
                    conn.execute(
                        "UPDATE users SET default_team_id = ? WHERE id = ?",
                        (team[0], user_dict["id"])
                    )
                    user_dict["default_team_id"] = team[0]
                return user_dict
        except sqlite3.IntegrityError:
            return None
    return None


def verify_user(username: str, password: str) -> Optional[dict]:
    import bcrypt
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if row and bcrypt.checkpw(password.encode(), row["password_hash"].encode()):
            return dict(row)
    return None


def get_user_by_id(user_id: int) -> Optional[dict]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


def get_user_by_username(username: str) -> Optional[dict]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return dict(row) if row else None


# ─────────────────────────────────────────────
# API Key operations
# ─────────────────────────────────────────────

def create_api_key(user_id: int, name: str = "default") -> dict:
    """Create API Key, returns the raw key in plaintext (only this once)"""
    import bcrypt
    raw_key = "local-" + secrets.token_hex(20)  # 46 chars, meets wandb >=40 requirement
    key_hash = bcrypt.hashpw(raw_key.encode(), bcrypt.gensalt()).decode()
    prefix = raw_key[:8]
    now = _now_iso()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO api_keys (user_id, name, key_hash, key_prefix, created_at) VALUES (?,?,?,?,?)",
            (user_id, name, key_hash, prefix, now)
        )
        row = conn.execute(
            "SELECT * FROM api_keys WHERE user_id = ? AND key_prefix = ? ORDER BY id DESC LIMIT 1",
            (user_id, prefix)
        ).fetchone()
        result = dict(row)
        result["raw_key"] = raw_key  # Only returned at creation time
        return result


def verify_api_key(raw_key: str) -> Optional[dict]:
    """Verify API Key and return the associated user"""
    import bcrypt
    prefix = raw_key[:8]
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM api_keys WHERE key_prefix = ?", (prefix,)).fetchall()
        for row in rows:
            if bcrypt.checkpw(raw_key.encode(), row["key_hash"].encode()):
                # Update last_used
                conn.execute("UPDATE api_keys SET last_used = ? WHERE id = ?", (_now_iso(), row["id"]))
                user = conn.execute("SELECT * FROM users WHERE id = ?", (row["user_id"],)).fetchone()
                return dict(user) if user else None
    # Compatible with legacy default key
    if raw_key == "local0000000000000000000000000000000000000000":
        user = conn.execute("SELECT * FROM users LIMIT 1").fetchone() if False else None
        with get_db() as conn:
            user = conn.execute("SELECT * FROM users ORDER BY id LIMIT 1").fetchone()
            return dict(user) if user else None
    return None


def list_api_keys(user_id: int) -> list:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, name, key_prefix, created_at, last_used FROM api_keys WHERE user_id = ? ORDER BY id DESC",
            (user_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def delete_api_key(key_id: int, user_id: int) -> bool:
    with get_db() as conn:
        cur = conn.execute("DELETE FROM api_keys WHERE id = ? AND user_id = ?", (key_id, user_id))
        return cur.rowcount > 0


# ─────────────────────────────────────────────
# Team operations
# ─────────────────────────────────────────────

def create_team(name: str, display_name: str, owner_id: int) -> Optional[dict]:
    now = _now_iso()
    with get_db() as conn:
        try:
            conn.execute(
                "INSERT INTO teams (name, display_name, created_at) VALUES (?,?,?)",
                (name, display_name, now)
            )
            team = conn.execute("SELECT * FROM teams WHERE name = ?", (name,)).fetchone()
            if team:
                conn.execute(
                    "INSERT INTO team_members (team_id, user_id, role, joined_at) VALUES (?,?,'owner',?)",
                    (team["id"], owner_id, now)
                )
                return dict(team)
        except sqlite3.IntegrityError:
            return None
    return None


def get_team_by_name(name: str) -> Optional[dict]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM teams WHERE name = ?", (name,)).fetchone()
        return dict(row) if row else None


def get_team_by_id(team_id: int) -> Optional[dict]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM teams WHERE id = ?", (team_id,)).fetchone()
        return dict(row) if row else None


def list_teams_for_user(user_id: int) -> list:
    with get_db() as conn:
        rows = conn.execute(
            """SELECT t.*, tm.role FROM teams t
               JOIN team_members tm ON t.id = tm.team_id
               WHERE tm.user_id = ? ORDER BY t.name""",
            (user_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_user_team_role(user_id: int, team_id: int) -> Optional[str]:
    with get_db() as conn:
        row = conn.execute(
            "SELECT role FROM team_members WHERE team_id = ? AND user_id = ?",
            (team_id, user_id)
        ).fetchone()
        return row["role"] if row else None


def list_team_members(team_id: int) -> list:
    with get_db() as conn:
        rows = conn.execute(
            """SELECT u.id, u.username, u.display_name, u.email, tm.role, tm.joined_at
               FROM users u JOIN team_members tm ON u.id = tm.user_id
               WHERE tm.team_id = ? ORDER BY tm.role, u.username""",
            (team_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def add_team_member(team_id: int, user_id: int, role: str = "member") -> bool:
    with get_db() as conn:
        try:
            conn.execute(
                "INSERT INTO team_members (team_id, user_id, role, joined_at) VALUES (?,?,?,?)",
                (team_id, user_id, role, _now_iso())
            )
            return True
        except sqlite3.IntegrityError:
            return False


def update_team_member_role(team_id: int, user_id: int, role: str) -> bool:
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE team_members SET role = ? WHERE team_id = ? AND user_id = ?",
            (role, team_id, user_id)
        )
        return cur.rowcount > 0


def remove_team_member(team_id: int, user_id: int) -> bool:
    with get_db() as conn:
        cur = conn.execute(
            "DELETE FROM team_members WHERE team_id = ? AND user_id = ?",
            (team_id, user_id)
        )
        return cur.rowcount > 0


# ─────────────────────────────────────────────
# Permission checks
# ─────────────────────────────────────────────

def user_can_access_project(user_id: int, project_id: int) -> bool:
    """Check if a user can view a project"""
    with get_db() as conn:
        proj = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not proj:
            return False
        if proj["visibility"] == "public":
            return True
        if proj["owner_id"] == user_id:
            return True
        if proj["visibility"] == "team":
            role = conn.execute(
                "SELECT role FROM team_members WHERE team_id = ? AND user_id = ?",
                (proj["team_id"], user_id)
            ).fetchone()
            return role is not None
    return False


def user_can_write_project(user_id: int, project_id: int) -> bool:
    """Check if a user can write data to a project"""
    with get_db() as conn:
        proj = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not proj:
            return False
        if proj["owner_id"] == user_id:
            return True
        role = conn.execute(
            "SELECT role FROM team_members WHERE team_id = ? AND user_id = ?",
            (proj["team_id"], user_id)
        ).fetchone()
        if role and role["role"] in ("owner", "admin", "member"):
            return True
    return False


def user_can_access_run(user_id: int, run_id) -> bool:
    """Check if a user can access a run (supports run_id string or database id integer)"""
    with get_db() as conn:
        run = conn.execute(
            "SELECT project_id FROM runs WHERE id = ? OR run_id = ?",
            (run_id, str(run_id))
        ).fetchone()
        if not run:
            return False
        return user_can_access_project(user_id, run["project_id"])


# ─────────────────────────────────────────────
# Project operations (with tenant isolation)
# ─────────────────────────────────────────────

def get_or_create_project(team_name: str, project_name: str, owner_id: int = None) -> dict:
    with get_db() as conn:
        team = conn.execute("SELECT * FROM teams WHERE name = ?", (team_name,)).fetchone()
        if not team:
            # Automatically create team
            conn.execute(
                "INSERT INTO teams (name, display_name, created_at) VALUES (?,?,?)",
                (team_name, team_name, _now_iso())
            )
            team = conn.execute("SELECT * FROM teams WHERE name = ?", (team_name,)).fetchone()
            if owner_id:
                conn.execute(
                    "INSERT OR IGNORE INTO team_members (team_id, user_id, role, joined_at) VALUES (?,?,'owner',?)",
                    (team["id"], owner_id, _now_iso())
                )

        row = conn.execute(
            "SELECT * FROM projects WHERE team_id = ? AND name = ?",
            (team["id"], project_name)
        ).fetchone()
        if row:
            return dict(row)

        oid = owner_id or 1
        conn.execute(
            "INSERT INTO projects (team_id, owner_id, name, visibility, created_at) VALUES (?,?,?,'team',?)",
            (team["id"], oid, project_name, _now_iso())
        )
        row = conn.execute(
            "SELECT * FROM projects WHERE team_id = ? AND name = ?",
            (team["id"], project_name)
        ).fetchone()
        return dict(row)


def list_projects_for_user(user_id: int, team_id: int = None) -> list:
    """List projects visible to the user"""
    with get_db() as conn:
        if team_id:
            rows = conn.execute(
                """SELECT p.* FROM projects p
                   WHERE p.team_id = ? AND (
                       p.visibility = 'public'
                       OR p.owner_id = ?
                       OR (p.visibility = 'team' AND EXISTS (
                           SELECT 1 FROM team_members tm WHERE tm.team_id = p.team_id AND tm.user_id = ?
                       ))
                   ) ORDER BY p.created_at DESC""",
                (team_id, user_id, user_id)
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT p.* FROM projects p
                   WHERE p.visibility = 'public'
                      OR p.owner_id = ?
                      OR (p.visibility = 'team' AND EXISTS (
                          SELECT 1 FROM team_members tm WHERE tm.team_id = p.team_id AND tm.user_id = ?
                      ))
                   ORDER BY p.created_at DESC""",
                (user_id, user_id)
            ).fetchall()
        return [dict(r) for r in rows]


def get_project(team_name: str, project_name: str) -> Optional[dict]:
    with get_db() as conn:
        row = conn.execute(
            """SELECT p.* FROM projects p
               JOIN teams t ON p.team_id = t.id
               WHERE t.name = ? AND p.name = ?""",
            (team_name, project_name)
        ).fetchone()
        return dict(row) if row else None


def get_project_by_id(project_id: int) -> Optional[dict]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return dict(row) if row else None


def update_project_visibility(project_id: int, visibility: str) -> bool:
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE projects SET visibility = ? WHERE id = ?",
            (visibility, project_id)
        )
        return cur.rowcount > 0


def get_project_run_count(project_id: int) -> int:
    with get_db() as conn:
        row = conn.execute("SELECT COUNT(*) as cnt FROM runs WHERE project_id = ?", (project_id,)).fetchone()
        return row["cnt"] if row else 0


def get_project_team(project_id: int) -> Optional[dict]:
    with get_db() as conn:
        row = conn.execute(
            "SELECT t.* FROM teams t JOIN projects p ON t.id = p.team_id WHERE p.id = ?",
            (project_id,)
        ).fetchone()
        return dict(row) if row else None


# ─────────────────────────────────────────────
# Run operations
# ─────────────────────────────────────────────

def upsert_run(project_id: int, run_id: str, display_name: str = "",
               config: dict = None, tags: list = None, notes: str = "",
               program: str = "", host: str = "", state: str = "running",
               owner_id: int = None) -> dict:
    now = _now_iso()
    config_json = json.dumps(config or {})
    tags_json = json.dumps(tags or [])

    with get_db() as conn:
        existing = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if existing:
            updates, params = [], []
            if display_name:
                updates.append("display_name = ?"); params.append(display_name)
            if config:
                old_config = json.loads(existing["config_json"])
                old_config.update(config)
                updates.append("config_json = ?"); params.append(json.dumps(old_config))
            if tags:
                updates.append("tags_json = ?"); params.append(tags_json)
            if notes:
                updates.append("notes = ?"); params.append(notes)
            if state:
                updates.append("state = ?"); params.append(state)
            updates.append("updated_at = ?"); params.append(now)
            updates.append("heartbeat_at = ?"); params.append(now)
            params.append(run_id)
            conn.execute(f"UPDATE runs SET {', '.join(updates)} WHERE run_id = ?", params)
        else:
            if not display_name:
                display_name = f"run-{run_id[:8]}"
            conn.execute(
                """INSERT INTO runs (project_id, owner_id, run_id, display_name, state,
                   config_json, tags_json, notes, program, host, created_at, updated_at, heartbeat_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (project_id, owner_id, run_id, display_name, state, config_json,
                 tags_json, notes, program, host, now, now, now)
            )
        row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return dict(row)


def get_run(run_id: str) -> Optional[dict]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return dict(row) if row else None


def list_runs(project_id: int, state: str = None, limit: int = 100, offset: int = 0) -> list:
    with get_db() as conn:
        if state:
            rows = conn.execute(
                "SELECT * FROM runs WHERE project_id = ? AND state = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (project_id, state, limit, offset)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM runs WHERE project_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (project_id, limit, offset)
            ).fetchall()
        return [dict(r) for r in rows]


def update_run_state(run_id: str, state: str):
    with get_db() as conn:
        conn.execute("UPDATE runs SET state = ?, updated_at = ? WHERE run_id = ?", (state, _now_iso(), run_id))


def update_run_summary(run_id: str, summary: dict):
    with get_db() as conn:
        existing = conn.execute("SELECT summary_json FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if existing:
            old = json.loads(existing["summary_json"])
            old.update(summary)
            conn.execute("UPDATE runs SET summary_json = ?, updated_at = ? WHERE run_id = ?",
                         (json.dumps(old), _now_iso(), run_id))


def update_run_config(run_id: str, config: dict):
    with get_db() as conn:
        existing = conn.execute("SELECT config_json FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if existing:
            old = json.loads(existing["config_json"])
            old.update(config)
            conn.execute("UPDATE runs SET config_json = ?, updated_at = ? WHERE run_id = ?",
                         (json.dumps(old), _now_iso(), run_id))


def update_run_heartbeat(run_id: str):
    with get_db() as conn:
        conn.execute("UPDATE runs SET heartbeat_at = ? WHERE run_id = ?", (_now_iso(), run_id))


# ─────────────────────────────────────────────
# Metrics
# ─────────────────────────────────────────────

def insert_metrics(run_id: str, metrics_list: list[dict]):
    with get_db() as conn:
        conn.executemany(
            "INSERT INTO metrics (run_id, key, step, value, wall_time) VALUES (?,?,?,?,?)",
            [(run_id, m["key"], m["step"], m["value"], m.get("wall_time", _now())) for m in metrics_list]
        )


def get_metrics(run_id: str, key: str = None, limit: int = 10000) -> list:
    with get_db() as conn:
        if key:
            rows = conn.execute(
                "SELECT * FROM metrics WHERE run_id = ? AND key = ? ORDER BY step ASC LIMIT ?",
                (run_id, key, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM metrics WHERE run_id = ? ORDER BY step ASC LIMIT ?",
                (run_id, limit)
            ).fetchall()
        return [dict(r) for r in rows]


def get_metric_keys(run_id: str) -> list[str]:
    with get_db() as conn:
        rows = conn.execute("SELECT DISTINCT key FROM metrics WHERE run_id = ? ORDER BY key", (run_id,)).fetchall()
        return [r["key"] for r in rows]


def get_latest_metrics(run_id: str) -> dict:
    with get_db() as conn:
        rows = conn.execute(
            """SELECT key, value, step FROM metrics
               WHERE run_id = ? AND step = (
                   SELECT MAX(step) FROM metrics m2 WHERE m2.run_id = metrics.run_id AND m2.key = metrics.key
               ) GROUP BY key""",
            (run_id,)
        ).fetchall()
        return {r["key"]: {"value": r["value"], "step": r["step"]} for r in rows}


def insert_system_metrics(run_id: str, metrics_list: list[dict]):
    with get_db() as conn:
        conn.executemany(
            "INSERT INTO system_metrics (run_id, key, step, value, wall_time) VALUES (?,?,?,?,?)",
            [(run_id, m["key"], m.get("step", 0), m["value"], m.get("wall_time", _now())) for m in metrics_list]
        )


def get_system_metrics(run_id: str) -> list:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM system_metrics WHERE run_id = ? ORDER BY wall_time ASC", (run_id,)
        ).fetchall()
        return [dict(r) for r in rows]


# ─────────────────────────────────────────────
# Artifact + File
# ─────────────────────────────────────────────

def create_artifact(run_id: str, name: str, artifact_type: str = "dataset", metadata: dict = None) -> dict:
    with get_db() as conn:
        conn.execute(
            "INSERT INTO artifacts (run_id, name, artifact_type, metadata_json, created_at) VALUES (?,?,?,?,?)",
            (run_id, name, artifact_type, json.dumps(metadata or {}), _now_iso())
        )
        row = conn.execute(
            "SELECT * FROM artifacts WHERE run_id = ? AND name = ? ORDER BY id DESC LIMIT 1",
            (run_id, name)
        ).fetchone()
        return dict(row)


def register_file(run_id: str, name: str, path: str, size: int = 0, md5: str = "") -> dict:
    with get_db() as conn:
        # Idempotent: keep only one record per filename per run, update when new data is available
        existing = conn.execute(
            "SELECT id, size FROM files WHERE run_id = ? AND name = ?",
            (run_id, name)
        ).fetchone()
        if existing:
            # File already registered — only update when more complete info is available (size>0 or md5 non-empty)
            if size > 0 or md5:
                conn.execute(
                    "UPDATE files SET path = ?, size = ?, md5 = ? WHERE id = ?",
                    (path, size, md5, existing["id"])
                )
        else:
            conn.execute(
                "INSERT INTO files (run_id, name, path, size, md5, created_at) VALUES (?,?,?,?,?,?)",
                (run_id, name, path, size, md5, _now_iso())
            )
        row = conn.execute(
            "SELECT * FROM files WHERE run_id = ? AND name = ? ORDER BY id DESC LIMIT 1",
            (run_id, name)
        ).fetchone()
        return dict(row)


def list_files(run_id: str) -> list:
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM files WHERE run_id = ? ORDER BY name", (run_id,)).fetchall()
        return [dict(r) for r in rows]


def get_artifact_by_id(artifact_id: int) -> dict | None:
    """Get a single artifact by ID"""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
        return dict(row) if row else None


def list_artifacts(run_id: str) -> list:
    """List all artifacts for a run"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM artifacts WHERE run_id = ? ORDER BY created_at DESC",
            (run_id,)
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["metadata"] = json.loads(d.get("metadata_json", "{}"))
            except (json.JSONDecodeError, TypeError):
                d["metadata"] = {}
            result.append(d)
        return result


def update_artifact_path(artifact_key: str, path: str, size: int = 0):
    """Update the file path of the most recent artifact based on an upload path keyword"""
    with get_db() as conn:
        # Try to match the most recently created artifact (in reverse chronological order)
        row = conn.execute(
            "SELECT id FROM artifacts ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE artifacts SET path = ?, size = ? WHERE id = ?",
                (path, size, row["id"])
            )


# ─────────────────────────────────────────────
# Share Links
# ─────────────────────────────────────────────

def create_share_link(resource_type: str, resource_id: int, created_by: int,
                      expires_at: str = None) -> dict:
    token = _gen_token()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO share_links (token, resource_type, resource_id, created_by, expires_at, created_at) VALUES (?,?,?,?,?,?)",
            (token, resource_type, resource_id, created_by, expires_at, _now_iso())
        )
        row = conn.execute("SELECT * FROM share_links WHERE token = ?", (token,)).fetchone()
        return dict(row)


def get_share_link(token: str) -> Optional[dict]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM share_links WHERE token = ?", (token,)).fetchone()
        if row:
            link = dict(row)
            if link.get("expires_at"):
                from datetime import datetime
                try:
                    exp = datetime.fromisoformat(link["expires_at"].replace("Z", "+00:00"))
                    if datetime.utcnow().replace(tzinfo=exp.tzinfo) > exp:
                        return None  # Expired
                except Exception:
                    pass
            return link
    return None


def list_share_links(user_id: int) -> list:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM share_links WHERE created_by = ? ORDER BY created_at DESC",
            (user_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def delete_share_link(link_id: int, user_id: int) -> bool:
    with get_db() as conn:
        cur = conn.execute("DELETE FROM share_links WHERE id = ? AND created_by = ?", (link_id, user_id))
        return cur.rowcount > 0
