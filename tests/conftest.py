"""
OpenWandb Test Fixtures
Every test gets a fresh SQLite DB in a temp directory — zero test pollution.
"""
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import pytest_asyncio


# ---------------------------------------------------------------------------
# Core fixture: isolated data directory with a fresh DB
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_data_dir(tmp_path, monkeypatch):
    """
    Monkeypatch openwandb.config paths to use tmp_path, then init_db().
    Returns the tmp_path for manual inspection if needed.
    """
    import openwandb.config as cfg

    db_path = tmp_path / "openwandb.db"
    files_dir = tmp_path / "files"
    artifacts_dir = tmp_path / "artifacts"
    files_dir.mkdir()
    artifacts_dir.mkdir()

    # Patch config module attributes
    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cfg, "DB_PATH", db_path)
    monkeypatch.setattr(cfg, "FILES_DIR", files_dir)
    monkeypatch.setattr(cfg, "ARTIFACTS_DIR", artifacts_dir)

    # Also patch _db_sqlite which imports DB_PATH at module level
    import openwandb._db_sqlite as _sqlite
    monkeypatch.setattr(_sqlite, "DB_PATH", db_path)

    # Patch storage module's references
    import openwandb.storage as _storage
    monkeypatch.setattr(_storage, "FILES_DIR", files_dir)
    monkeypatch.setattr(_storage, "ARTIFACTS_DIR", artifacts_dir)

    # Initialize the database
    from openwandb._db_sqlite import init_db
    init_db()

    return tmp_path


# ---------------------------------------------------------------------------
# User / Team / Project / Run fixtures (build on tmp_data_dir)
# ---------------------------------------------------------------------------

@pytest.fixture()
def admin_user(tmp_data_dir):
    """Returns the default admin user dict."""
    from openwandb import database as db
    user = db.get_user_by_username("admin")
    assert user is not None
    return user


@pytest.fixture()
def test_user(tmp_data_dir):
    """Creates a second user 'testuser' and returns the dict."""
    from openwandb import database as db
    user = db.create_user("testuser", "testpass123", display_name="Test User", email="test@example.com")
    assert user is not None
    return user


@pytest.fixture()
def test_team(tmp_data_dir, test_user):
    """Creates a team 'myteam' owned by test_user."""
    from openwandb import database as db
    team = db.create_team("myteam", "My Team", test_user["id"])
    assert team is not None
    return team


@pytest.fixture()
def test_project(tmp_data_dir, admin_user):
    """Creates a project 'test-project' under default team."""
    from openwandb import database as db
    proj = db.get_or_create_project("default", "test-project", owner_id=admin_user["id"])
    assert proj is not None
    return proj


@pytest.fixture()
def test_run(tmp_data_dir, test_project, admin_user):
    """Creates a run under test_project."""
    from openwandb import database as db
    run = db.upsert_run(
        project_id=test_project["id"],
        run_id="run-abc123",
        display_name="Test Run",
        config={"lr": 0.001, "batch_size": 32},
        tags=["test"],
        notes="a test run",
        state="running",
        owner_id=admin_user["id"],
    )
    assert run is not None
    return run


# ---------------------------------------------------------------------------
# Mock Request helpers for auth tests
# ---------------------------------------------------------------------------

def make_request(
    headers: dict = None,
    cookies: dict = None,
    query_params: dict = None,
):
    """Create a mock Starlette/FastAPI Request object."""
    req = MagicMock()
    req.headers = headers or {}
    req.cookies = cookies or {}
    req.query_params = query_params or {}
    return req


# ---------------------------------------------------------------------------
# Async HTTP client fixture for integration tests
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture()
async def app_client(tmp_data_dir):
    """
    httpx.AsyncClient wrapping the FastAPI app.
    Requires pytest-asyncio.
    """
    import httpx
    from openwandb.server import app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client
