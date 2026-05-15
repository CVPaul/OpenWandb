"""
OpenWandb v0.2 — File Stream processing module
wandb SDK sends metrics data via POST /files/{entity}/{project}/{run_id}/file_stream
This is the core transport channel for wandb.log()
"""
import json
import logging
import time
from typing import Any

from openwandb import database as db
from openwandb import storage

logger = logging.getLogger("openwandb.file_stream")


def process_file_stream(entity: str, project: str, run_id: str, payload: dict,
                        user_id: int = None) -> dict:
    """
    Process file_stream request.

    v0.2: Added user_id parameter for permission checking.
    If user_id is provided, write permission for the run's project will be verified.

    Payload format sent by wandb SDK:
    {
        "files": {
            "wandb-history.jsonl": {
                "offset": 0,
                "content": ["{\"loss\": 0.5, \"_step\": 1, \"_timestamp\": 1234}"]
            },
            "wandb-summary.json": {
                "offset": 0,
                "content": ["{\"loss\": 0.3, \"accuracy\": 0.9}"]
            },
            "wandb-events.jsonl": {
                "offset": 0,
                "content": ["{\"system.cpu\": 50, \"system.memory\": 30}"]
            },
            "config.yaml": {
                "offset": 0,
                "content": ["learning_rate: 0.001\\nbatch_size: 32"]
            }
        },
        "dropped": 0,
        "complete": false
    }
    """
    # Permission check (if user_id is provided)
    if user_id:
        run = db.get_run(run_id)
        if run:
            if not db.user_can_write_project(user_id, run["project_id"]):
                logger.warning(f"User {user_id} has no write access to run {run_id}")
                return {"exitcode": None, "limits": {}, "error": "Permission denied"}

    files = payload.get("files", {})
    complete = payload.get("complete", False)

    for filename, file_data in files.items():
        content_lines = file_data.get("content", [])
        offset = file_data.get("offset", 0)

        if filename == "wandb-history.jsonl":
            _process_history(entity, project, run_id, content_lines)
        elif filename == "wandb-summary.json":
            _process_summary(run_id, content_lines)
        elif filename == "wandb-events.jsonl":
            _process_events(run_id, content_lines)
        elif filename == "config.yaml":
            _process_config(entity, project, run_id, content_lines)
        elif filename == "output.log":
            _process_log(entity, project, run_id, content_lines)
        else:
            # Other files are saved directly to disk
            _save_raw_file(entity, project, run_id, filename, content_lines)

    # Update heartbeat
    db.update_run_heartbeat(run_id)

    # If marked as complete, update run state
    if complete:
        db.update_run_state(run_id, "finished")
        logger.info(f"Run {run_id} marked as finished")

    return {"exitcode": None, "limits": {}}


def _process_history(entity: str, project: str, run_id: str, content_lines: list):
    """
    Process wandb-history.jsonl -- contains all metrics logged by wandb.log().
    Each line is a JSON object: {"loss": 0.5, "accuracy": 0.8, "_step": 1, "_timestamp": 1234.5, "_runtime": 10.2}
    """
    metrics_batch = []

    for line in content_lines:
        if not line or not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON in history: {line[:100]}")
            continue

        step = data.get("_step", 0)
        wall_time = data.get("_timestamp", time.time())

        # Extract all non-internal fields (fields starting with _ are wandb internal fields)
        for key, value in data.items():
            if key.startswith("_"):
                continue
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                metrics_batch.append({
                    "key": key,
                    "step": step,
                    "value": float(value),
                    "wall_time": wall_time
                })
            elif isinstance(value, dict) and "_type" in value:
                # wandb.Image / wandb.Table and other media objects
                _extract_media_files(entity, project, run_id, value)
            elif isinstance(value, list):
                # List of media objects, e.g. [wandb.Image(...), ...]
                for item in value:
                    if isinstance(item, dict) and "_type" in item:
                        _extract_media_files(entity, project, run_id, item)

    if metrics_batch:
        db.insert_metrics(run_id, metrics_batch)
        logger.debug(f"Inserted {len(metrics_batch)} metrics for run {run_id}")

    # Also save the raw file
    raw = "\n".join(content_lines) + "\n"
    storage.append_file(entity, project, run_id, "wandb-history.jsonl", raw)


def _process_summary(run_id: str, content_lines: list):
    """
    Process wandb-summary.json -- the run's final summary metrics.
    """
    for line in content_lines:
        if not line or not line.strip():
            continue
        try:
            data = json.loads(line)
            # Filter out internal fields
            summary = {k: v for k, v in data.items()
                       if not k.startswith("_") and isinstance(v, (int, float, str, bool))}
            if summary:
                db.update_run_summary(run_id, summary)
                logger.debug(f"Updated summary for run {run_id}")
        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON in summary: {line[:100]}")


def _process_events(run_id: str, content_lines: list):
    """
    Process wandb-events.jsonl -- system resource monitoring metrics.
    Format: {"system.cpu": 50.2, "system.memory": 30.5, "_timestamp": 1234}
    """
    sys_metrics_batch = []

    for line in content_lines:
        if not line or not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue

        wall_time = data.get("_timestamp", time.time())

        for key, value in data.items():
            if key.startswith("_"):
                continue
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                sys_metrics_batch.append({
                    "key": key,
                    "step": 0,
                    "value": float(value),
                    "wall_time": wall_time
                })

    if sys_metrics_batch:
        db.insert_system_metrics(run_id, sys_metrics_batch)


def _process_config(entity: str, project: str, run_id: str, content_lines: list):
    """
    Process config.yaml -- run configuration.
    Config content sent by wandb may be in YAML or JSON format.
    Each config item format: {"key": {"desc": null, "value": actual_value}}
    """
    raw_content = "\n".join(content_lines)
    if not raw_content.strip():
        return

    config = {}
    try:
        # Try JSON parsing
        parsed = json.loads(raw_content)
        for key, val in parsed.items():
            if isinstance(val, dict) and "value" in val:
                config[key] = val["value"]
            else:
                config[key] = val
    except json.JSONDecodeError:
        # Try YAML parsing
        try:
            import yaml
            parsed = yaml.safe_load(raw_content)
            if isinstance(parsed, dict):
                for key, val in parsed.items():
                    if isinstance(val, dict) and "value" in val:
                        config[key] = val["value"]
                    else:
                        config[key] = val
        except Exception:
            logger.warning(f"Failed to parse config for run {run_id}")
            return

    if config:
        db.update_run_config(run_id, config)
        logger.debug(f"Updated config for run {run_id}: {list(config.keys())}")

    # Save raw file
    storage.append_file(entity, project, run_id, "config.yaml", raw_content + "\n")


def _process_log(entity: str, project: str, run_id: str, content_lines: list):
    """Process output.log -- training output logs"""
    raw = "\n".join(content_lines) + "\n"
    storage.append_file(entity, project, run_id, "output.log", raw)


def _extract_media_files(entity: str, project: str, run_id: str, media_obj: dict):
    """
    Extract file references from wandb media objects and register them in the database.

    wandb SDK records media references as dicts in history JSON, common types:
      - {"_type": "images/separated", "filenames": ["media/images/xxx.png", ...]}
      - {"_type": "image-file", "path": "media/images/xxx.png", ...}
      - {"_type": "table-file", "path": "media/table/xxx.table.json", ...}

    These files are uploaded independently by the SDK via PUT /files/... to the server disk,
    but if they are not registered in the DB files table, the UI Media tab cannot find them.
    This performs "pre-registration": placeholder entries in DB, so once files are actually
    uploaded, the path/size will match.
    """
    media_type = media_obj.get("_type", "")
    filenames = []

    if media_type == "images/separated":
        # Batch images: {"filenames": ["media/images/pred_0_abc.png", ...]}
        filenames = media_obj.get("filenames", [])
    elif media_type in ("image-file", "images"):
        # Single image: {"path": "media/images/xxx.png"}
        p = media_obj.get("path")
        if p:
            filenames = [p]
    elif media_type == "table-file":
        # wandb.Table: {"path": "media/table/xxx.table.json"}
        p = media_obj.get("path")
        if p:
            filenames = [p]
    else:
        # Other unknown media types, try to extract path / filenames
        p = media_obj.get("path")
        if p:
            filenames = [p]
        filenames.extend(media_obj.get("filenames", []))

    run_files_dir = storage.get_run_files_dir(entity, project, run_id)

    for fname in filenames:
        if not fname:
            continue
        filepath = run_files_dir / fname
        size = filepath.stat().st_size if filepath.exists() else 0
        try:
            db.register_file(run_id, fname, str(filepath), size, "")
            logger.debug(f"Registered media file: {fname} for run {run_id}")
        except Exception:
            logger.debug(f"Media file already registered or DB error: {fname}")


def _save_raw_file(entity: str, project: str, run_id: str,
                   filename: str, content_lines: list):
    """Save raw file content and register in database"""
    raw = "\n".join(content_lines)
    if raw:
        info = storage.save_file(entity, project, run_id, filename, raw.encode("utf-8"))
        # Register in database so Media tab can find it (fix: previously only saved to disk without registering)
        try:
            db.register_file(run_id, filename, info["path"], info["size"], info["md5"])
        except Exception:
            logger.debug(f"File already registered or DB error: {filename}")
