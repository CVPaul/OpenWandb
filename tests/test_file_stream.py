"""
Tests for openwandb.file_stream — processing wandb SDK file_stream payloads.
"""
import json
import pytest
from openwandb import database as db
from openwandb import storage
from openwandb.file_stream import process_file_stream


class TestProcessHistory:
    def test_metrics_inserted(self, test_run, test_project, tmp_data_dir):
        payload = {
            "files": {
                "wandb-history.jsonl": {
                    "offset": 0,
                    "content": [
                        json.dumps({"loss": 0.9, "acc": 0.1, "_step": 1, "_timestamp": 100.0}),
                        json.dumps({"loss": 0.7, "acc": 0.3, "_step": 2, "_timestamp": 101.0}),
                    ]
                }
            }
        }
        result = process_file_stream("default", "test-project", test_run["run_id"], payload)
        assert result["exitcode"] is None

        # Check metrics in DB
        metrics = db.get_metrics(test_run["run_id"])
        assert len(metrics) == 4  # 2 steps x 2 keys
        keys = {m["key"] for m in metrics}
        assert keys == {"loss", "acc"}

    def test_internal_fields_skipped(self, test_run, test_project, tmp_data_dir):
        """Fields starting with _ should NOT be stored as metrics."""
        payload = {
            "files": {
                "wandb-history.jsonl": {
                    "offset": 0,
                    "content": [
                        json.dumps({"_step": 1, "_timestamp": 100.0, "_runtime": 5.0, "loss": 0.5}),
                    ]
                }
            }
        }
        process_file_stream("default", "test-project", test_run["run_id"], payload)
        metrics = db.get_metrics(test_run["run_id"])
        keys = {m["key"] for m in metrics}
        assert "_step" not in keys
        assert "_timestamp" not in keys
        assert "_runtime" not in keys
        assert "loss" in keys

    def test_non_numeric_values_skipped(self, test_run, test_project, tmp_data_dir):
        """String and boolean values should be skipped in metrics."""
        payload = {
            "files": {
                "wandb-history.jsonl": {
                    "offset": 0,
                    "content": [
                        json.dumps({
                            "_step": 1, "loss": 0.5,
                            "model_name": "resnet",  # string — skip
                            "converged": True,  # bool — skip
                        }),
                    ]
                }
            }
        }
        process_file_stream("default", "test-project", test_run["run_id"], payload)
        metrics = db.get_metrics(test_run["run_id"])
        keys = {m["key"] for m in metrics}
        assert "loss" in keys
        assert "model_name" not in keys
        assert "converged" not in keys

    def test_raw_file_saved(self, test_run, test_project, tmp_data_dir):
        payload = {
            "files": {
                "wandb-history.jsonl": {
                    "offset": 0,
                    "content": ['{"loss": 0.5, "_step": 1}']
                }
            }
        }
        process_file_stream("default", "test-project", test_run["run_id"], payload)
        raw = storage.read_file("default", "test-project", test_run["run_id"], "wandb-history.jsonl")
        assert raw is not None
        assert b'"loss"' in raw


class TestProcessSummary:
    def test_summary_merged(self, test_run, test_project, tmp_data_dir):
        payload = {
            "files": {
                "wandb-summary.json": {
                    "offset": 0,
                    "content": [json.dumps({"loss": 0.3, "accuracy": 0.95})]
                }
            }
        }
        process_file_stream("default", "test-project", test_run["run_id"], payload)
        run = db.get_run(test_run["run_id"])
        summary = json.loads(run["summary_json"])
        assert summary["loss"] == 0.3
        assert summary["accuracy"] == 0.95

    def test_summary_filters_internal(self, test_run, test_project, tmp_data_dir):
        payload = {
            "files": {
                "wandb-summary.json": {
                    "offset": 0,
                    "content": [json.dumps({"_wandb": {}, "loss": 0.2})]
                }
            }
        }
        process_file_stream("default", "test-project", test_run["run_id"], payload)
        run = db.get_run(test_run["run_id"])
        summary = json.loads(run["summary_json"])
        assert "_wandb" not in summary
        assert "loss" in summary


class TestProcessEvents:
    def test_system_metrics_inserted(self, test_run, test_project, tmp_data_dir):
        payload = {
            "files": {
                "wandb-events.jsonl": {
                    "offset": 0,
                    "content": [
                        json.dumps({"system.cpu": 50.0, "system.memory": 30.0, "_timestamp": 100.0}),
                    ]
                }
            }
        }
        process_file_stream("default", "test-project", test_run["run_id"], payload)
        sys_metrics = db.get_system_metrics(test_run["run_id"])
        assert len(sys_metrics) == 2
        keys = {m["key"] for m in sys_metrics}
        assert "system.cpu" in keys
        assert "system.memory" in keys


class TestProcessConfig:
    def test_config_json_format(self, test_run, test_project, tmp_data_dir):
        config_data = {"lr": {"desc": None, "value": 0.001}, "epochs": {"desc": None, "value": 50}}
        payload = {
            "files": {
                "config.yaml": {
                    "offset": 0,
                    "content": [json.dumps(config_data)]
                }
            }
        }
        process_file_stream("default", "test-project", test_run["run_id"], payload)
        run = db.get_run(test_run["run_id"])
        config = json.loads(run["config_json"])
        assert config["lr"] == 0.001
        assert config["epochs"] == 50

    def test_config_yaml_format(self, test_run, test_project, tmp_data_dir):
        yaml_content = "learning_rate:\n  value: 0.01\nbatch_size:\n  value: 32"
        payload = {
            "files": {
                "config.yaml": {
                    "offset": 0,
                    "content": [yaml_content]
                }
            }
        }
        process_file_stream("default", "test-project", test_run["run_id"], payload)
        run = db.get_run(test_run["run_id"])
        config = json.loads(run["config_json"])
        assert config["learning_rate"] == 0.01
        assert config["batch_size"] == 32

    def test_config_plain_values(self, test_run, test_project, tmp_data_dir):
        """Config without nested 'value' field."""
        config_data = {"lr": 0.001, "epochs": 50}
        payload = {
            "files": {
                "config.yaml": {
                    "offset": 0,
                    "content": [json.dumps(config_data)]
                }
            }
        }
        process_file_stream("default", "test-project", test_run["run_id"], payload)
        run = db.get_run(test_run["run_id"])
        config = json.loads(run["config_json"])
        assert config["lr"] == 0.001


class TestProcessLog:
    def test_log_appended(self, test_run, test_project, tmp_data_dir):
        payload = {
            "files": {
                "output.log": {
                    "offset": 0,
                    "content": ["Epoch 1/10: loss=0.5", "Epoch 2/10: loss=0.3"]
                }
            }
        }
        process_file_stream("default", "test-project", test_run["run_id"], payload)
        raw = storage.read_file("default", "test-project", test_run["run_id"], "output.log")
        assert raw is not None
        text = raw.decode("utf-8")
        assert "Epoch 1/10" in text
        assert "Epoch 2/10" in text


class TestCompleteFlag:
    def test_complete_sets_finished(self, test_run, test_project, tmp_data_dir):
        payload = {"files": {}, "complete": True}
        process_file_stream("default", "test-project", test_run["run_id"], payload)
        run = db.get_run(test_run["run_id"])
        assert run["state"] == "finished"

    def test_incomplete_keeps_running(self, test_run, test_project, tmp_data_dir):
        payload = {"files": {}, "complete": False}
        process_file_stream("default", "test-project", test_run["run_id"], payload)
        run = db.get_run(test_run["run_id"])
        assert run["state"] == "running"


class TestPermissionCheck:
    def test_permission_denied(self, tmp_data_dir):
        """User without write access gets error."""
        owner = db.create_user("fs-owner", "pass")
        viewer = db.create_user("fs-viewer", "pass")
        team = db.create_team("fsteam", "FSTeam", owner["id"])
        db.add_team_member(team["id"], viewer["id"], "viewer")
        proj = db.get_or_create_project("fsteam", "fsproj", owner_id=owner["id"])
        run = db.upsert_run(proj["id"], "fs-run-001", owner_id=owner["id"])

        payload = {
            "files": {
                "wandb-history.jsonl": {
                    "offset": 0,
                    "content": ['{"loss": 0.5, "_step": 1}']
                }
            }
        }
        result = process_file_stream("fsteam", "fsproj", "fs-run-001", payload, user_id=viewer["id"])
        assert "error" in result
        assert result["error"] == "Permission denied"
