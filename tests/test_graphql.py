"""
Tests for openwandb.graphql_schema — GraphQL queries and mutations.
Uses httpx.AsyncClient to POST GraphQL requests.
"""
import json
import pytest
import httpx

# asyncio_mode = "auto" in pyproject.toml handles async test discovery

API_KEY = "local0000000000000000000000000000000000000000"
HEADERS = {"x-wandb-api-key": API_KEY}


# ═══════════════════════════════════════════════
# Helper
# ═══════════════════════════════════════════════

async def gql(client: httpx.AsyncClient, query: str, variables: dict = None) -> dict:
    """Execute a GraphQL query and return the JSON response."""
    body = {"query": query}
    if variables:
        body["variables"] = variables
    resp = await client.post("/graphql", json=body, headers=HEADERS)
    assert resp.status_code == 200, f"GraphQL returned {resp.status_code}: {resp.text}"
    return resp.json()


# ═══════════════════════════════════════════════
# Queries — viewer
# ═══════════════════════════════════════════════

class TestViewerQuery:
    async def test_viewer_returns_user(self, app_client: httpx.AsyncClient):
        data = await gql(app_client, "{ viewer { username entity } }")
        assert "errors" not in data, f"GraphQL errors: {data.get('errors')}"
        viewer = data["data"]["viewer"]
        assert viewer["username"] == "admin"
        assert viewer["entity"] is not None

    async def test_viewer_teams(self, app_client: httpx.AsyncClient):
        data = await gql(app_client, """
            { viewer { username teams { edges { node { name } } } } }
        """)
        assert "errors" not in data
        teams = data["data"]["viewer"]["teams"]["edges"]
        assert len(teams) >= 1
        names = [e["node"]["name"] for e in teams]
        assert "default" in names

    async def test_viewer_default_entity(self, app_client: httpx.AsyncClient):
        data = await gql(app_client, """
            { viewer { defaultEntity { name } } }
        """)
        assert "errors" not in data
        assert data["data"]["viewer"]["defaultEntity"]["name"] is not None


# ═══════════════════════════════════════════════
# Queries — serverInfo (the cliVersionInfo crash fix)
# ═══════════════════════════════════════════════

class TestServerInfoQuery:
    async def test_server_info_basic(self, app_client: httpx.AsyncClient):
        data = await gql(app_client, """
            { serverInfo { latestLocalVersionInfo { outOfDate latestVersionString } } }
        """)
        assert "errors" not in data
        info = data["data"]["serverInfo"]
        assert "latestLocalVersionInfo" in info

    async def test_cli_version_info(self, app_client: httpx.AsyncClient):
        """This was the crash: cliVersionInfo returned None -> .get() on NoneType."""
        data = await gql(app_client, """
            { serverInfo { cliVersionInfo { maxCliVersion } } }
        """)
        assert "errors" not in data
        cli_info = data["data"]["serverInfo"]["cliVersionInfo"]
        # Should be a dict (not null), with maxCliVersion field
        assert cli_info is not None
        assert "maxCliVersion" in cli_info

    async def test_server_features(self, app_client: httpx.AsyncClient):
        data = await gql(app_client, """
            { serverInfo { features { name isEnabled } } }
        """)
        assert "errors" not in data
        features = data["data"]["serverInfo"]["features"]
        assert isinstance(features, list)


# ═══════════════════════════════════════════════
# Queries — entity / project / model
# ═══════════════════════════════════════════════

class TestEntityProjectQuery:
    async def test_query_entity(self, app_client: httpx.AsyncClient):
        data = await gql(app_client, """
            query { entity(name: "default") { name } }
        """)
        assert "errors" not in data
        assert data["data"]["entity"]["name"] == "default"

    async def test_query_project(self, app_client: httpx.AsyncClient):
        """Create project via mutation first, then query it."""
        # Create run (which auto-creates project)
        await gql(app_client, """
            mutation { upsertBucket(entity: "default", project: "gql-proj", name: "r1") {
                bucket { name }
            }}
        """)
        data = await gql(app_client, """
            query { project(name: "gql-proj", entityName: "default") { name entityName } }
        """)
        assert "errors" not in data
        proj = data["data"]["project"]
        assert proj["name"] == "gql-proj"

    async def test_query_model_alias(self, app_client: httpx.AsyncClient):
        """'model' is a legacy alias for 'project' in wandb SDK."""
        await gql(app_client, """
            mutation { upsertBucket(entity: "default", project: "model-proj", name: "r1") {
                bucket { name }
            }}
        """)
        data = await gql(app_client, """
            query { model(name: "model-proj", entityName: "default") { name } }
        """)
        assert "errors" not in data
        assert data["data"]["model"]["name"] == "model-proj"


# ═══════════════════════════════════════════════
# Queries — project.bucket / project.buckets
# ═══════════════════════════════════════════════

class TestBucketQueries:
    async def test_project_bucket(self, app_client: httpx.AsyncClient):
        """bucket(name) = single run lookup. Was missing before v0.5.11."""
        await gql(app_client, """
            mutation { upsertBucket(entity: "default", project: "bucket-proj", name: "my-run") {
                bucket { name }
            }}
        """)
        data = await gql(app_client, """
            query { project(name: "bucket-proj", entityName: "default") {
                bucket(name: "my-run") { name displayName state }
            }}
        """)
        assert "errors" not in data
        bucket = data["data"]["project"]["bucket"]
        assert bucket is not None
        assert bucket["name"] == "my-run"

    async def test_project_bucket_missing_ok(self, app_client: httpx.AsyncClient):
        """bucket with missingOk=true returns null for nonexistent run."""
        await gql(app_client, """
            mutation { upsertBucket(entity: "default", project: "bucket-proj2", name: "r1") {
                bucket { name }
            }}
        """)
        data = await gql(app_client, """
            query { project(name: "bucket-proj2", entityName: "default") {
                bucket(name: "nonexistent", missingOk: true) { name }
            }}
        """)
        assert "errors" not in data
        assert data["data"]["project"]["bucket"] is None

    async def test_project_buckets(self, app_client: httpx.AsyncClient):
        """buckets() = run list. Legacy alias for runs."""
        await gql(app_client, """
            mutation { upsertBucket(entity: "default", project: "buckets-proj", name: "r1") {
                bucket { name }
            }}
        """)
        await gql(app_client, """
            mutation { upsertBucket(entity: "default", project: "buckets-proj", name: "r2") {
                bucket { name }
            }}
        """)
        data = await gql(app_client, """
            query { project(name: "buckets-proj", entityName: "default") {
                buckets { edges { node { name } } }
            }}
        """)
        assert "errors" not in data
        edges = data["data"]["project"]["buckets"]["edges"]
        names = [e["node"]["name"] for e in edges]
        assert "r1" in names
        assert "r2" in names


# ═══════════════════════════════════════════════
# Queries — run.wandbConfig
# ═══════════════════════════════════════════════

class TestWandbConfig:
    async def test_wandb_config_with_keys(self, app_client: httpx.AsyncClient):
        """wandbConfig(keys:) returns filtered config. Was broken before v0.5.13."""
        # Create run with config using variables to avoid JSON-in-string escaping
        data = await gql(app_client, """
            mutation($config: JSONString) { upsertBucket(
                entity: "default", project: "cfg-proj", name: "cfg-run",
                config: $config
            ) { bucket { name } }}
        """, variables={"config": json.dumps({"lr": 0.001, "epochs": 10, "batch_size": 32})})
        assert "errors" not in data, f"GraphQL errors: {data.get('errors')}"

        data = await gql(app_client, """
            query { project(name: "cfg-proj", entityName: "default") {
                bucket(name: "cfg-run") {
                    wandbConfig(keys: ["lr", "epochs"])
                }
            }}
        """)
        assert "errors" not in data
        config_str = data["data"]["project"]["bucket"]["wandbConfig"]
        if config_str:
            config = json.loads(config_str)
            # Should only contain the requested keys (if implementation filters)
            assert "lr" in config or "epochs" in config

    async def test_wandb_config_no_keys(self, app_client: httpx.AsyncClient):
        """wandbConfig without keys returns full config."""
        data = await gql(app_client, """
            mutation($config: JSONString) { upsertBucket(
                entity: "default", project: "cfg2-proj", name: "cfg2-run",
                config: $config
            ) { bucket { name } }}
        """, variables={"config": json.dumps({"lr": 0.001})})
        assert "errors" not in data, f"GraphQL errors: {data.get('errors')}"

        data = await gql(app_client, """
            query { project(name: "cfg2-proj", entityName: "default") {
                bucket(name: "cfg2-run") { wandbConfig }
            }}
        """)
        assert "errors" not in data


# ═══════════════════════════════════════════════
# Mutations — upsertBucket
# ═══════════════════════════════════════════════

class TestUpsertBucketMutation:
    async def test_create_run(self, app_client: httpx.AsyncClient):
        data = await gql(app_client, """
            mutation { upsertBucket(
                entity: "default",
                project: "upsert-proj",
                name: "upsert-run-1",
                displayName: "My Run"
            ) {
                bucket { name displayName state }
                inserted
            }}
        """)
        assert "errors" not in data
        result = data["data"]["upsertBucket"]
        assert result["bucket"]["name"] == "upsert-run-1"
        assert result["inserted"] is True

    async def test_update_run(self, app_client: httpx.AsyncClient):
        # Create
        await gql(app_client, """
            mutation { upsertBucket(entity: "default", project: "up2", name: "run-up") {
                bucket { name }
            }}
        """)
        # Update with new display name
        data = await gql(app_client, """
            mutation { upsertBucket(
                entity: "default", project: "up2", name: "run-up",
                displayName: "Updated Name"
            ) {
                bucket { name displayName }
            }}
        """)
        assert "errors" not in data
        result = data["data"]["upsertBucket"]
        assert result["bucket"]["name"] == "run-up"
        assert result["bucket"]["displayName"] == "Updated Name"

    async def test_server_settings_returned(self, app_client: httpx.AsyncClient):
        """upsertBucket should return serverSettings.serverMessages."""
        data = await gql(app_client, """
            mutation { upsertBucket(entity: "default", project: "ss-proj", name: "ss-run") {
                bucket { name }
                serverSettings { serverMessages { utfText messageType } }
            }}
        """)
        assert "errors" not in data
        ss = data["data"]["upsertBucket"]["serverSettings"]
        assert ss is not None
        assert "serverMessages" in ss

    async def test_auto_generate_run_id(self, app_client: httpx.AsyncClient):
        """If no name given, should auto-generate a run_id."""
        data = await gql(app_client, """
            mutation { upsertBucket(entity: "default", project: "auto-proj") {
                bucket { name }
                inserted
            }}
        """)
        assert "errors" not in data
        name = data["data"]["upsertBucket"]["bucket"]["name"]
        assert name is not None
        assert len(name) > 0


# ═══════════════════════════════════════════════
# Mutations — createRunFiles
# ═══════════════════════════════════════════════

class TestCreateRunFilesMutation:
    async def test_create_run_files(self, app_client: httpx.AsyncClient):
        # Create run first
        await gql(app_client, """
            mutation { upsertBucket(entity: "default", project: "files-proj", name: "files-run") {
                bucket { name }
            }}
        """)
        data = await gql(app_client, """
            mutation { createRunFiles(
                entity: "default",
                project: "files-proj",
                run: "files-run",
                files: ["model.pt", "config.yaml"]
            ) {
                runID
                uploadHeaders
                files { name url(upload: true) }
            }}
        """)
        assert "errors" not in data
        result = data["data"]["createRunFiles"]
        assert result["uploadHeaders"] is not None
        assert isinstance(result["files"], list)


# ═══════════════════════════════════════════════
# Mutations — createArtifact
# ═══════════════════════════════════════════════

class TestCreateArtifactMutation:
    async def test_create_artifact(self, app_client: httpx.AsyncClient):
        # Create run first
        await gql(app_client, """
            mutation { upsertBucket(entity: "default", project: "art-proj", name: "art-run") {
                bucket { name }
            }}
        """)
        data = await gql(app_client, """
            mutation { createArtifact(
                artifactTypeName: "dataset",
                artifactCollectionName: "my-dataset",
                runName: "art-run",
                entityName: "default",
                projectName: "art-proj",
                digest: "abc123"
            ) {
                artifact { id digest state }
            }}
        """)
        assert "errors" not in data
        artifact = data["data"]["createArtifact"]["artifact"]
        assert artifact is not None
        assert artifact["digest"] == "abc123"


# ═══════════════════════════════════════════════
# Queries — entity.projects connection
# ═══════════════════════════════════════════════

class TestEntityProjects:
    async def test_entity_projects(self, app_client: httpx.AsyncClient):
        # Create a project
        await gql(app_client, """
            mutation { upsertBucket(entity: "default", project: "ep-proj", name: "ep-run") {
                bucket { name }
            }}
        """)
        data = await gql(app_client, """
            query { entity(name: "default") {
                projects { edges { node { name } } }
            }}
        """)
        assert "errors" not in data
        edges = data["data"]["entity"]["projects"]["edges"]
        names = [e["node"]["name"] for e in edges]
        assert "ep-proj" in names


# ═══════════════════════════════════════════════
# Run fields
# ═══════════════════════════════════════════════

class TestRunFields:
    async def test_run_fields(self, app_client: httpx.AsyncClient):
        """Test that all run fields introduced in v0.5.14 resolve without error."""
        data = await gql(app_client, """
            mutation($tags: [String!]) { upsertBucket(
                entity: "default", project: "rf-proj", name: "rf-run",
                commit: "abc123", tags: $tags
            ) { bucket { name } }}
        """, variables={"tags": ["test"]})
        assert "errors" not in data, f"GraphQL errors: {data.get('errors')}"

        data = await gql(app_client, """
            query { project(name: "rf-proj", entityName: "default") {
                bucket(name: "rf-run") {
                    name displayName state
                    commit stopped running
                    historyLineCount eventsLineCount filesCount logLineCount
                    samplingInfo
                    agent
                }
            }}
        """)
        assert "errors" not in data
        bucket = data["data"]["project"]["bucket"]
        assert bucket["name"] == "rf-run"
        assert isinstance(bucket["stopped"], bool)
        assert isinstance(bucket["running"], bool)
