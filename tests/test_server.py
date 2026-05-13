"""
Tests for openwandb.server — REST API integration tests.
Uses httpx.AsyncClient with the FastAPI app.
"""
import json
import pytest
import httpx

# asyncio_mode = "auto" in pyproject.toml handles async test discovery


# ═══════════════════════════════════════════════
# Auth endpoints
# ═══════════════════════════════════════════════

class TestAuthEndpoints:
    async def test_register_and_login(self, app_client: httpx.AsyncClient):
        # Register
        resp = await app_client.post("/api/v2/auth/register", json={
            "username": "newuser",
            "password": "newpass123",
            "display_name": "New User",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["user"]["username"] == "newuser"
        assert "token" in data

        # Login
        resp = await app_client.post("/api/v2/auth/login", json={
            "username": "newuser",
            "password": "newpass123",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "token" in data
        assert data["user"]["username"] == "newuser"

    async def test_login_wrong_password(self, app_client: httpx.AsyncClient):
        resp = await app_client.post("/api/v2/auth/login", json={
            "username": "admin",
            "password": "wrongpassword",
        })
        assert resp.status_code == 401

    async def test_register_duplicate(self, app_client: httpx.AsyncClient):
        await app_client.post("/api/v2/auth/register", json={
            "username": "dupuser", "password": "pass123456",
        })
        resp = await app_client.post("/api/v2/auth/register", json={
            "username": "dupuser", "password": "pass234567",
        })
        # API returns 409 for duplicate username
        assert resp.status_code in (400, 409)

    async def test_me_authenticated(self, app_client: httpx.AsyncClient):
        # Login first
        login_resp = await app_client.post("/api/v2/auth/login", json={
            "username": "admin", "password": "admin123",
        })
        token = login_resp.json()["token"]

        resp = await app_client.get("/api/v2/auth/me",
                                    cookies={"openwandb_token": token})
        assert resp.status_code == 200
        data = resp.json()
        # Response format: {"user": {"id":..., "username":...}, "teams": [...]}
        assert data["user"]["username"] == "admin"

    async def test_me_unauthenticated(self, app_client: httpx.AsyncClient):
        resp = await app_client.get("/api/v2/auth/me")
        assert resp.status_code == 401

    async def test_logout(self, app_client: httpx.AsyncClient):
        login_resp = await app_client.post("/api/v2/auth/login", json={
            "username": "admin", "password": "admin123",
        })
        token = login_resp.json()["token"]
        resp = await app_client.post("/api/v2/auth/logout",
                                     cookies={"openwandb_token": token})
        assert resp.status_code == 200


# ═══════════════════════════════════════════════
# API Key endpoints
# ═══════════════════════════════════════════════

class TestAPIKeyEndpoints:
    async def _get_token(self, client: httpx.AsyncClient) -> str:
        resp = await client.post("/api/v2/auth/login", json={
            "username": "admin", "password": "admin123",
        })
        return resp.json()["token"]

    async def test_create_and_list_api_keys(self, app_client: httpx.AsyncClient):
        token = await self._get_token(app_client)
        cookies = {"openwandb_token": token}

        # Create — response: {"success": true, "api_key": {"id":..., "key":"local-...", ...}}
        resp = await app_client.post("/api/v2/settings/api-keys",
                                     json={"name": "test-key"},
                                     cookies=cookies)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "api_key" in data
        assert "key" in data["api_key"]
        assert data["api_key"]["key"].startswith("local-")

        # List — response: {"api_keys": [...]}
        resp = await app_client.get("/api/v2/settings/api-keys", cookies=cookies)
        assert resp.status_code == 200
        data = resp.json()
        assert "api_keys" in data
        assert isinstance(data["api_keys"], list)
        assert len(data["api_keys"]) >= 1

    async def test_delete_api_key(self, app_client: httpx.AsyncClient):
        token = await self._get_token(app_client)
        cookies = {"openwandb_token": token}

        # Create key to delete
        resp = await app_client.post("/api/v2/settings/api-keys",
                                     json={"name": "to-delete"},
                                     cookies=cookies)
        key_id = resp.json().get("api_key", {}).get("id")
        if key_id:
            resp = await app_client.delete(f"/api/v2/settings/api-keys/{key_id}",
                                           cookies=cookies)
            assert resp.status_code == 200


# ═══════════════════════════════════════════════
# Team endpoints
# ═══════════════════════════════════════════════

class TestTeamEndpoints:
    async def _get_token(self, client: httpx.AsyncClient) -> str:
        resp = await client.post("/api/v2/auth/login", json={
            "username": "admin", "password": "admin123",
        })
        return resp.json()["token"]

    async def test_list_teams(self, app_client: httpx.AsyncClient):
        token = await self._get_token(app_client)
        resp = await app_client.get("/api/v2/teams",
                                    cookies={"openwandb_token": token})
        assert resp.status_code == 200
        data = resp.json()
        # Response format: {"teams": [...]}
        assert "teams" in data
        teams = data["teams"]
        assert isinstance(teams, list)
        names = [t["name"] for t in teams]
        assert "default" in names

    async def test_create_team(self, app_client: httpx.AsyncClient):
        token = await self._get_token(app_client)
        resp = await app_client.post("/api/v2/teams",
                                     json={"name": "api-team", "display_name": "API Team"},
                                     cookies={"openwandb_token": token})
        assert resp.status_code == 200
        data = resp.json()
        # Response format: {"success": true, "team": {"name": "api-team", ...}}
        assert data["success"] is True
        assert data["team"]["name"] == "api-team"


# ═══════════════════════════════════════════════
# Project & Run REST API
# ═══════════════════════════════════════════════

class TestProjectRunAPI:
    async def _get_token(self, client: httpx.AsyncClient) -> str:
        resp = await client.post("/api/v2/auth/login", json={
            "username": "admin", "password": "admin123",
        })
        return resp.json()["token"]

    async def test_list_projects(self, app_client: httpx.AsyncClient):
        token = await self._get_token(app_client)
        resp = await app_client.get("/api/v2/projects",
                                    cookies={"openwandb_token": token})
        assert resp.status_code == 200
        data = resp.json()
        # Response format: {"projects": [...]}
        assert "projects" in data
        assert isinstance(data["projects"], list)

    async def test_viewer_api(self, app_client: httpx.AsyncClient):
        """wandb viewer API returns entity and username."""
        api_key = "local0000000000000000000000000000000000000000"
        resp = await app_client.get("/api/v1/viewer",
                                    headers={"x-wandb-api-key": api_key})
        assert resp.status_code == 200
        data = resp.json()
        assert "entity" in data
        assert "username" in data


# ═══════════════════════════════════════════════
# File Stream endpoint
# ═══════════════════════════════════════════════

class TestFileStreamEndpoint:
    async def test_file_stream(self, app_client: httpx.AsyncClient):
        """POST metrics via file_stream endpoint."""
        from openwandb import database as db
        # First create a run via GraphQL (upsert_bucket)
        api_key = "local0000000000000000000000000000000000000000"
        headers = {"x-wandb-api-key": api_key}

        # Use upsert_bucket mutation to create a run
        gql = {
            "query": """mutation UpsertBucket($entity: String, $project: String, $name: String) {
                upsertBucket(entity: $entity, project: $project, name: $name) {
                    bucket { name }
                }
            }""",
            "variables": {"entity": "default", "project": "stream-test", "name": "stream-run-1"}
        }
        resp = await app_client.post("/graphql", json=gql, headers=headers)
        assert resp.status_code == 200

        # Now stream metrics
        payload = {
            "files": {
                "wandb-history.jsonl": {
                    "offset": 0,
                    "content": [json.dumps({"loss": 0.5, "_step": 1, "_timestamp": 100.0})]
                }
            }
        }
        resp = await app_client.post(
            "/files/default/stream-test/stream-run-1/file_stream",
            json=payload, headers=headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("exitcode") is None

        # Verify metrics stored
        metrics = db.get_metrics("stream-run-1")
        assert len(metrics) >= 1


# ═══════════════════════════════════════════════
# File upload/download
# ═══════════════════════════════════════════════

class TestFileUploadDownload:
    async def test_upload_and_download(self, app_client: httpx.AsyncClient):
        api_key = "local0000000000000000000000000000000000000000"
        headers = {"x-wandb-api-key": api_key}

        # Create run first
        gql = {
            "query": """mutation UpsertBucket($entity: String, $project: String, $name: String) {
                upsertBucket(entity: $entity, project: $project, name: $name) {
                    bucket { name }
                }
            }""",
            "variables": {"entity": "default", "project": "file-test", "name": "file-run-1"}
        }
        await app_client.post("/graphql", json=gql, headers=headers)

        # Upload file
        content = b"model weights data here"
        resp = await app_client.put(
            "/files/default/file-test/file-run-1/model.pt",
            content=content,
            headers={**headers, "content-type": "application/octet-stream"},
        )
        assert resp.status_code == 200

        # Download file
        resp = await app_client.get(
            "/files/default/file-test/file-run-1/model.pt",
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.content == content
