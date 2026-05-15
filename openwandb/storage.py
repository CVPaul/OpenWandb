"""
OpenWandb — File and Artifact storage module
"""
import hashlib
import os
from pathlib import Path
from typing import Optional

from openwandb.config import ARTIFACTS_DIR, FILES_DIR


def get_run_files_dir(entity: str, project: str, run_id: str) -> Path:
    """Get the file storage directory for a run"""
    d = FILES_DIR / entity / project / run_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_file(entity: str, project: str, run_id: str,
              filename: str, content: bytes) -> dict:
    """Save file and return file info"""
    run_dir = get_run_files_dir(entity, project, run_id)
    filepath = run_dir / filename
    filepath.parent.mkdir(parents=True, exist_ok=True)

    with open(filepath, "wb") as f:
        f.write(content)

    md5 = hashlib.md5(content).hexdigest()
    return {
        "path": str(filepath),
        "size": len(content),
        "md5": md5
    }


def read_file(entity: str, project: str, run_id: str,
              filename: str) -> Optional[bytes]:
    """Read file"""
    filepath = FILES_DIR / entity / project / run_id / filename
    if filepath.exists():
        return filepath.read_bytes()
    return None


def append_file(entity: str, project: str, run_id: str,
                filename: str, content: str):
    """Append content to file (for logs, etc.)"""
    run_dir = get_run_files_dir(entity, project, run_id)
    filepath = run_dir / filename
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(content)


def get_artifact_dir(entity: str, project: str, artifact_name: str) -> Path:
    """Get the Artifact storage directory"""
    d = ARTIFACTS_DIR / entity / project / artifact_name
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_run_files(entity: str, project: str, run_id: str) -> list[dict]:
    """List all files for a run"""
    run_dir = FILES_DIR / entity / project / run_id
    if not run_dir.exists():
        return []

    result = []
    for filepath in run_dir.rglob("*"):
        if filepath.is_file():
            result.append({
                "name": str(filepath.relative_to(run_dir)),
                "size": filepath.stat().st_size,
                "path": str(filepath)
            })
    return result
