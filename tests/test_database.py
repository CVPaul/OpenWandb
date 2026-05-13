"""
Tests for openwandb._db_sqlite — all CRUD operations against a fresh temp DB.
"""
import json
import pytest
from openwandb import database as db


# ═══════════════════════════════════════════════
# init_db / bootstrap
# ═══════════════════════════════════════════════

class TestInitDB:
    def test_admin_user_exists(self, tmp_data_dir):
        user = db.get_user_by_username("admin")
        assert user is not None
        assert user["username"] == "admin"

    def test_default_team_exists(self, tmp_data_dir):
        team = db.get_team_by_name("default")
        assert team is not None
        assert team["name"] == "default"

    def test_admin_is_team_owner(self, tmp_data_dir, admin_user):
        team = db.get_team_by_name("default")
        role = db.get_user_team_role(admin_user["id"], team["id"])
        assert role == "owner"

    def test_default_api_key_works(self, tmp_data_dir):
        user = db.verify_api_key("local0000000000000000000000000000000000000000")
        assert user is not None
        assert user["username"] == "admin"


# ═══════════════════════════════════════════════
# User operations
# ═══════════════════════════════════════════════

class TestUserOps:
    def test_create_user(self, tmp_data_dir):
        user = db.create_user("alice", "password1", display_name="Alice", email="alice@test.com")
        assert user is not None
        assert user["username"] == "alice"
        assert user["display_name"] == "Alice"
        assert user["email"] == "alice@test.com"
        assert user["default_team_id"] is not None

    def test_create_user_auto_creates_personal_team(self, tmp_data_dir):
        db.create_user("bob", "pass")
        team = db.get_team_by_name("bob")
        assert team is not None

    def test_create_user_duplicate_returns_none(self, tmp_data_dir):
        db.create_user("dup", "pass1")
        result = db.create_user("dup", "pass2")
        assert result is None

    def test_verify_user_correct_password(self, tmp_data_dir):
        db.create_user("carol", "mypass")
        user = db.verify_user("carol", "mypass")
        assert user is not None
        assert user["username"] == "carol"

    def test_verify_user_wrong_password(self, tmp_data_dir):
        db.create_user("dave", "rightpass")
        user = db.verify_user("dave", "wrongpass")
        assert user is None

    def test_verify_user_nonexistent(self, tmp_data_dir):
        user = db.verify_user("ghost", "nope")
        assert user is None

    def test_get_user_by_id(self, admin_user):
        user = db.get_user_by_id(admin_user["id"])
        assert user is not None
        assert user["username"] == "admin"

    def test_get_user_by_id_nonexistent(self, tmp_data_dir):
        assert db.get_user_by_id(99999) is None

    def test_get_user_by_username(self, admin_user):
        user = db.get_user_by_username("admin")
        assert user["id"] == admin_user["id"]

    def test_get_user_by_username_nonexistent(self, tmp_data_dir):
        assert db.get_user_by_username("nobody") is None


# ═══════════════════════════════════════════════
# API Key operations
# ═══════════════════════════════════════════════

class TestAPIKeyOps:
    def test_create_api_key(self, admin_user):
        key = db.create_api_key(admin_user["id"], name="test-key")
        assert "raw_key" in key
        assert key["raw_key"].startswith("local-")
        assert len(key["raw_key"]) >= 40
        assert key["name"] == "test-key"

    def test_verify_api_key(self, admin_user):
        key = db.create_api_key(admin_user["id"])
        user = db.verify_api_key(key["raw_key"])
        assert user is not None
        assert user["id"] == admin_user["id"]

    def test_verify_api_key_invalid(self, tmp_data_dir):
        result = db.verify_api_key("totally-invalid-key-that-does-not-exist")
        assert result is None

    def test_list_api_keys(self, admin_user):
        db.create_api_key(admin_user["id"], name="key-a")
        db.create_api_key(admin_user["id"], name="key-b")
        keys = db.list_api_keys(admin_user["id"])
        # At least 3: default + key-a + key-b
        assert len(keys) >= 3
        names = [k["name"] for k in keys]
        assert "key-a" in names
        assert "key-b" in names

    def test_delete_api_key(self, admin_user):
        key = db.create_api_key(admin_user["id"], name="to-delete")
        assert db.delete_api_key(key["id"], admin_user["id"]) is True
        # Verify it's gone
        keys = db.list_api_keys(admin_user["id"])
        ids = [k["id"] for k in keys]
        assert key["id"] not in ids

    def test_delete_api_key_wrong_user(self, admin_user, test_user):
        key = db.create_api_key(admin_user["id"], name="admin-key")
        # test_user tries to delete admin's key
        assert db.delete_api_key(key["id"], test_user["id"]) is False


# ═══════════════════════════════════════════════
# Team operations
# ═══════════════════════════════════════════════

class TestTeamOps:
    def test_create_team(self, test_user):
        team = db.create_team("team-x", "Team X", test_user["id"])
        assert team is not None
        assert team["name"] == "team-x"
        # Owner should be a member
        role = db.get_user_team_role(test_user["id"], team["id"])
        assert role == "owner"

    def test_create_team_duplicate(self, test_user):
        db.create_team("dup-team", "Dup", test_user["id"])
        result = db.create_team("dup-team", "Dup2", test_user["id"])
        assert result is None

    def test_get_team_by_name(self, tmp_data_dir):
        team = db.get_team_by_name("default")
        assert team is not None

    def test_get_team_by_id(self, tmp_data_dir):
        team = db.get_team_by_name("default")
        result = db.get_team_by_id(team["id"])
        assert result["name"] == "default"

    def test_list_teams_for_user(self, admin_user):
        teams = db.list_teams_for_user(admin_user["id"])
        assert len(teams) >= 1
        names = [t["name"] for t in teams]
        assert "default" in names

    def test_add_team_member(self, test_team, admin_user):
        result = db.add_team_member(test_team["id"], admin_user["id"], role="member")
        assert result is True
        role = db.get_user_team_role(admin_user["id"], test_team["id"])
        assert role == "member"

    def test_add_team_member_duplicate(self, test_team, test_user):
        # test_user is already the owner
        result = db.add_team_member(test_team["id"], test_user["id"], role="member")
        assert result is False  # Duplicate

    def test_update_team_member_role(self, test_team, admin_user):
        db.add_team_member(test_team["id"], admin_user["id"], role="member")
        result = db.update_team_member_role(test_team["id"], admin_user["id"], "admin")
        assert result is True
        role = db.get_user_team_role(admin_user["id"], test_team["id"])
        assert role == "admin"

    def test_remove_team_member(self, test_team, admin_user):
        db.add_team_member(test_team["id"], admin_user["id"], role="member")
        result = db.remove_team_member(test_team["id"], admin_user["id"])
        assert result is True
        role = db.get_user_team_role(admin_user["id"], test_team["id"])
        assert role is None

    def test_list_team_members(self, test_team, test_user):
        members = db.list_team_members(test_team["id"])
        assert len(members) >= 1
        usernames = [m["username"] for m in members]
        assert test_user["username"] in usernames


# ═══════════════════════════════════════════════
# Permission checks
# ═══════════════════════════════════════════════

class TestPermissions:
    def test_owner_can_access_project(self, test_project, admin_user):
        assert db.user_can_access_project(admin_user["id"], test_project["id"]) is True

    def test_owner_can_write_project(self, test_project, admin_user):
        assert db.user_can_write_project(admin_user["id"], test_project["id"]) is True

    def test_team_member_can_access_team_project(self, tmp_data_dir):
        owner = db.create_user("proj-owner", "pass")
        member = db.create_user("proj-member", "pass")
        team = db.create_team("pteam", "PTeam", owner["id"])
        db.add_team_member(team["id"], member["id"], "member")
        proj = db.get_or_create_project("pteam", "teamproj", owner_id=owner["id"])
        assert db.user_can_access_project(member["id"], proj["id"]) is True
        assert db.user_can_write_project(member["id"], proj["id"]) is True

    def test_viewer_can_read_but_not_write(self, tmp_data_dir):
        owner = db.create_user("v-owner", "pass")
        viewer = db.create_user("v-viewer", "pass")
        team = db.create_team("vteam", "VTeam", owner["id"])
        db.add_team_member(team["id"], viewer["id"], "viewer")
        proj = db.get_or_create_project("vteam", "vproj", owner_id=owner["id"])
        assert db.user_can_access_project(viewer["id"], proj["id"]) is True
        assert db.user_can_write_project(viewer["id"], proj["id"]) is False

    def test_nonmember_cannot_access_team_project(self, tmp_data_dir):
        owner = db.create_user("nm-owner", "pass")
        outsider = db.create_user("nm-outsider", "pass")
        team = db.create_team("nmteam", "NMTeam", owner["id"])
        proj = db.get_or_create_project("nmteam", "nmproj", owner_id=owner["id"])
        assert db.user_can_access_project(outsider["id"], proj["id"]) is False

    def test_public_project_accessible_by_anyone(self, tmp_data_dir):
        owner = db.create_user("pub-owner", "pass")
        stranger = db.create_user("pub-stranger", "pass")
        proj = db.get_or_create_project("default", "pubproj", owner_id=owner["id"])
        db.update_project_visibility(proj["id"], "public")
        assert db.user_can_access_project(stranger["id"], proj["id"]) is True

    def test_user_can_access_run(self, test_run, admin_user):
        assert db.user_can_access_run(admin_user["id"], test_run["run_id"]) is True

    def test_nonexistent_project_returns_false(self, tmp_data_dir, admin_user):
        assert db.user_can_access_project(admin_user["id"], 99999) is False


# ═══════════════════════════════════════════════
# Project operations
# ═══════════════════════════════════════════════

class TestProjectOps:
    def test_get_or_create_project_new(self, tmp_data_dir, admin_user):
        proj = db.get_or_create_project("default", "brand-new-proj", owner_id=admin_user["id"])
        assert proj is not None
        assert proj["name"] == "brand-new-proj"

    def test_get_or_create_project_existing(self, test_project, admin_user):
        proj2 = db.get_or_create_project("default", "test-project", owner_id=admin_user["id"])
        assert proj2["id"] == test_project["id"]

    def test_get_or_create_project_auto_creates_team(self, tmp_data_dir, admin_user):
        proj = db.get_or_create_project("auto-team", "auto-proj", owner_id=admin_user["id"])
        assert proj is not None
        team = db.get_team_by_name("auto-team")
        assert team is not None

    def test_get_project(self, test_project):
        proj = db.get_project("default", "test-project")
        assert proj is not None
        assert proj["id"] == test_project["id"]

    def test_get_project_nonexistent(self, tmp_data_dir):
        assert db.get_project("default", "no-such-project") is None

    def test_get_project_by_id(self, test_project):
        proj = db.get_project_by_id(test_project["id"])
        assert proj["name"] == "test-project"

    def test_list_projects_for_user(self, test_project, admin_user):
        projects = db.list_projects_for_user(admin_user["id"])
        names = [p["name"] for p in projects]
        assert "test-project" in names

    def test_update_project_visibility(self, test_project):
        result = db.update_project_visibility(test_project["id"], "public")
        assert result is True
        proj = db.get_project_by_id(test_project["id"])
        assert proj["visibility"] == "public"

    def test_get_project_run_count(self, test_project, test_run):
        count = db.get_project_run_count(test_project["id"])
        assert count >= 1

    def test_get_project_team(self, test_project):
        team = db.get_project_team(test_project["id"])
        assert team is not None
        assert team["name"] == "default"


# ═══════════════════════════════════════════════
# Run operations
# ═══════════════════════════════════════════════

class TestRunOps:
    def test_upsert_run_create(self, test_project, admin_user):
        run = db.upsert_run(
            project_id=test_project["id"],
            run_id="new-run-001",
            display_name="My Run",
            config={"epochs": 10},
            tags=["experiment"],
            state="running",
            owner_id=admin_user["id"],
        )
        assert run["run_id"] == "new-run-001"
        assert run["display_name"] == "My Run"
        assert run["state"] == "running"
        config = json.loads(run["config_json"])
        assert config["epochs"] == 10

    def test_upsert_run_auto_display_name(self, test_project, admin_user):
        run = db.upsert_run(
            project_id=test_project["id"],
            run_id="xyzabc1234567890",
            owner_id=admin_user["id"],
        )
        assert run["display_name"].startswith("run-")

    def test_upsert_run_update_merges_config(self, test_project, admin_user):
        db.upsert_run(
            project_id=test_project["id"],
            run_id="merge-run",
            config={"lr": 0.001},
            owner_id=admin_user["id"],
        )
        run = db.upsert_run(
            project_id=test_project["id"],
            run_id="merge-run",
            config={"batch_size": 64},
            owner_id=admin_user["id"],
        )
        config = json.loads(run["config_json"])
        assert config["lr"] == 0.001  # preserved
        assert config["batch_size"] == 64  # added

    def test_get_run(self, test_run):
        run = db.get_run(test_run["run_id"])
        assert run is not None
        assert run["run_id"] == test_run["run_id"]

    def test_get_run_nonexistent(self, tmp_data_dir):
        assert db.get_run("no-such-run") is None

    def test_list_runs(self, test_project, test_run):
        runs = db.list_runs(test_project["id"])
        assert len(runs) >= 1
        run_ids = [r["run_id"] for r in runs]
        assert test_run["run_id"] in run_ids

    def test_list_runs_filter_state(self, test_project, admin_user):
        db.upsert_run(test_project["id"], "running-run", state="running", owner_id=admin_user["id"])
        db.upsert_run(test_project["id"], "finished-run", state="finished", owner_id=admin_user["id"])
        running = db.list_runs(test_project["id"], state="running")
        finished = db.list_runs(test_project["id"], state="finished")
        running_ids = [r["run_id"] for r in running]
        finished_ids = [r["run_id"] for r in finished]
        assert "running-run" in running_ids
        assert "finished-run" in finished_ids
        assert "finished-run" not in running_ids

    def test_update_run_state(self, test_run):
        db.update_run_state(test_run["run_id"], "finished")
        run = db.get_run(test_run["run_id"])
        assert run["state"] == "finished"

    def test_update_run_summary(self, test_run):
        db.update_run_summary(test_run["run_id"], {"loss": 0.5})
        db.update_run_summary(test_run["run_id"], {"accuracy": 0.9})
        run = db.get_run(test_run["run_id"])
        summary = json.loads(run["summary_json"])
        assert summary["loss"] == 0.5
        assert summary["accuracy"] == 0.9

    def test_update_run_config(self, test_run):
        db.update_run_config(test_run["run_id"], {"new_param": 42})
        run = db.get_run(test_run["run_id"])
        config = json.loads(run["config_json"])
        assert config["new_param"] == 42
        assert config["lr"] == 0.001  # original preserved

    def test_update_run_heartbeat(self, test_run):
        old_heartbeat = test_run["heartbeat_at"]
        import time; time.sleep(0.01)  # ensure time moves forward
        db.update_run_heartbeat(test_run["run_id"])
        run = db.get_run(test_run["run_id"])
        assert run["heartbeat_at"] != old_heartbeat


# ═══════════════════════════════════════════════
# Metrics
# ═══════════════════════════════════════════════

class TestMetrics:
    def test_insert_and_get_metrics(self, test_run):
        metrics = [
            {"key": "loss", "step": 1, "value": 0.9, "wall_time": 100.0},
            {"key": "loss", "step": 2, "value": 0.7, "wall_time": 101.0},
            {"key": "acc", "step": 1, "value": 0.5, "wall_time": 100.0},
        ]
        db.insert_metrics(test_run["run_id"], metrics)
        all_metrics = db.get_metrics(test_run["run_id"])
        assert len(all_metrics) == 3

    def test_get_metrics_by_key(self, test_run):
        metrics = [
            {"key": "loss", "step": 1, "value": 0.9},
            {"key": "acc", "step": 1, "value": 0.5},
        ]
        db.insert_metrics(test_run["run_id"], metrics)
        loss_metrics = db.get_metrics(test_run["run_id"], key="loss")
        assert all(m["key"] == "loss" for m in loss_metrics)

    def test_get_metric_keys(self, test_run):
        metrics = [
            {"key": "loss", "step": 1, "value": 0.9},
            {"key": "acc", "step": 1, "value": 0.5},
            {"key": "lr", "step": 1, "value": 0.001},
        ]
        db.insert_metrics(test_run["run_id"], metrics)
        keys = db.get_metric_keys(test_run["run_id"])
        assert set(keys) == {"loss", "acc", "lr"}

    def test_get_latest_metrics(self, test_run):
        metrics = [
            {"key": "loss", "step": 1, "value": 0.9},
            {"key": "loss", "step": 2, "value": 0.7},
            {"key": "loss", "step": 3, "value": 0.5},
        ]
        db.insert_metrics(test_run["run_id"], metrics)
        latest = db.get_latest_metrics(test_run["run_id"])
        assert latest["loss"]["value"] == 0.5
        assert latest["loss"]["step"] == 3

    def test_system_metrics(self, test_run):
        sys_metrics = [
            {"key": "system.cpu", "value": 50.0, "wall_time": 100.0},
            {"key": "system.memory", "value": 30.0, "wall_time": 100.0},
        ]
        db.insert_system_metrics(test_run["run_id"], sys_metrics)
        result = db.get_system_metrics(test_run["run_id"])
        assert len(result) == 2
        keys = [m["key"] for m in result]
        assert "system.cpu" in keys


# ═══════════════════════════════════════════════
# Artifacts & Files
# ═══════════════════════════════════════════════

class TestArtifactsAndFiles:
    def test_create_artifact(self, test_run):
        art = db.create_artifact(
            test_run["run_id"], "my-dataset", artifact_type="dataset",
            metadata={"version": "1.0"}
        )
        assert art is not None
        assert art["name"] == "my-dataset"
        assert art["artifact_type"] == "dataset"

    def test_list_artifacts(self, test_run):
        db.create_artifact(test_run["run_id"], "art-1")
        db.create_artifact(test_run["run_id"], "art-2")
        arts = db.list_artifacts(test_run["run_id"])
        assert len(arts) >= 2
        names = [a["name"] for a in arts]
        assert "art-1" in names
        assert "art-2" in names
        # metadata should be parsed
        for a in arts:
            assert isinstance(a["metadata"], dict)

    def test_register_file(self, test_run):
        f = db.register_file(test_run["run_id"], "model.pt", "/tmp/model.pt", size=1024, md5="abc123")
        assert f["name"] == "model.pt"
        assert f["size"] == 1024

    def test_list_files(self, test_run):
        db.register_file(test_run["run_id"], "file-a.txt", "/a", size=10)
        db.register_file(test_run["run_id"], "file-b.txt", "/b", size=20)
        files = db.list_files(test_run["run_id"])
        assert len(files) >= 2
        names = [f["name"] for f in files]
        assert "file-a.txt" in names
        assert "file-b.txt" in names


# ═══════════════════════════════════════════════
# Share Links
# ═══════════════════════════════════════════════

class TestShareLinks:
    def test_create_and_get_share_link(self, test_project, admin_user):
        link = db.create_share_link("project", test_project["id"], admin_user["id"])
        assert link is not None
        assert "token" in link
        # Retrieve it
        fetched = db.get_share_link(link["token"])
        assert fetched is not None
        assert fetched["resource_type"] == "project"
        assert fetched["resource_id"] == test_project["id"]

    def test_get_share_link_nonexistent(self, tmp_data_dir):
        assert db.get_share_link("no-such-token") is None

    def test_list_share_links(self, test_project, admin_user):
        db.create_share_link("project", test_project["id"], admin_user["id"])
        db.create_share_link("project", test_project["id"], admin_user["id"])
        links = db.list_share_links(admin_user["id"])
        assert len(links) >= 2

    def test_delete_share_link(self, test_project, admin_user):
        link = db.create_share_link("project", test_project["id"], admin_user["id"])
        result = db.delete_share_link(link["id"], admin_user["id"])
        assert result is True
        assert db.get_share_link(link["token"]) is None

    def test_delete_share_link_wrong_user(self, test_project, admin_user, test_user):
        link = db.create_share_link("project", test_project["id"], admin_user["id"])
        result = db.delete_share_link(link["id"], test_user["id"])
        assert result is False  # Not the creator
