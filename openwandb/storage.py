"""
OpenWandb — 文件与 Artifact 存储模块
"""
import hashlib
import os
from pathlib import Path
from typing import Optional

from openwandb.config import ARTIFACTS_DIR, FILES_DIR


def get_run_files_dir(entity: str, project: str, run_id: str) -> Path:
    """获取运行的文件存储目录"""
    d = FILES_DIR / entity / project / run_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_file(entity: str, project: str, run_id: str,
              filename: str, content: bytes) -> dict:
    """保存文件, 返回文件信息"""
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
    """读取文件"""
    filepath = FILES_DIR / entity / project / run_id / filename
    if filepath.exists():
        return filepath.read_bytes()
    return None


def append_file(entity: str, project: str, run_id: str,
                filename: str, content: str):
    """追加内容到文件 (用于日志等)"""
    run_dir = get_run_files_dir(entity, project, run_id)
    filepath = run_dir / filename
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(content)


def get_artifact_dir(entity: str, project: str, artifact_name: str) -> Path:
    """获取 Artifact 存储目录"""
    d = ARTIFACTS_DIR / entity / project / artifact_name
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_run_files(entity: str, project: str, run_id: str) -> list[dict]:
    """列出运行的所有文件"""
    run_dir = FILES_DIR / entity / project / run_id
    if not run_dir.exists():
        return []

    result = []
    for filepath in run_dir.rglob("*"):
        if filepath.is_file():
            result.append({
                "name": str(filepath.relative_to(run_dir)).replace("\\", "/"),
                "size": filepath.stat().st_size,
                "path": str(filepath)
            })
    return result
