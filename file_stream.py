"""
OpenWandb v0.2 — File Stream 处理模块
wandb SDK 通过 POST /files/{entity}/{project}/{run_id}/file_stream 发送指标数据
这是 wandb.log() 的核心传输通道
"""
import json
import logging
import time
from typing import Any

import database as db
import storage

logger = logging.getLogger("openwandb.file_stream")


def process_file_stream(entity: str, project: str, run_id: str, payload: dict,
                        user_id: int = None) -> dict:
    """
    处理 file_stream 请求

    v0.2: 新增 user_id 参数用于权限校验
    如果传入 user_id, 会校验该用户对 run 所属项目的写权限

    wandb SDK 发送的 payload 格式:
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
    # 权限校验 (如果提供了 user_id)
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
            # 其他文件直接保存到磁盘
            _save_raw_file(entity, project, run_id, filename, content_lines)

    # 更新心跳
    db.update_run_heartbeat(run_id)

    # 如果标记完成, 更新运行状态
    if complete:
        db.update_run_state(run_id, "finished")
        logger.info(f"Run {run_id} marked as finished")

    return {"exitcode": None, "limits": {}}


def _process_history(entity: str, project: str, run_id: str, content_lines: list):
    """
    处理 wandb-history.jsonl — 包含 wandb.log() 记录的所有指标
    每行是一个 JSON 对象: {"loss": 0.5, "accuracy": 0.8, "_step": 1, "_timestamp": 1234.5, "_runtime": 10.2}
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

        # 提取所有非内部字段 (以_开头的是wandb内部字段)
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

    if metrics_batch:
        db.insert_metrics(run_id, metrics_batch)
        logger.debug(f"Inserted {len(metrics_batch)} metrics for run {run_id}")

    # 同时保存原始文件
    raw = "\n".join(content_lines) + "\n"
    storage.append_file(entity, project, run_id, "wandb-history.jsonl", raw)


def _process_summary(run_id: str, content_lines: list):
    """
    处理 wandb-summary.json — 运行的最终 summary 指标
    """
    for line in content_lines:
        if not line or not line.strip():
            continue
        try:
            data = json.loads(line)
            # 过滤掉内部字段
            summary = {k: v for k, v in data.items()
                       if not k.startswith("_") and isinstance(v, (int, float, str, bool))}
            if summary:
                db.update_run_summary(run_id, summary)
                logger.debug(f"Updated summary for run {run_id}")
        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON in summary: {line[:100]}")


def _process_events(run_id: str, content_lines: list):
    """
    处理 wandb-events.jsonl — 系统资源监控指标
    格式: {"system.cpu": 50.2, "system.memory": 30.5, "_timestamp": 1234}
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
    处理 config.yaml — 运行配置
    wandb 发送的 config 内容可能是 YAML 或 JSON 格式
    每个配置项的格式: {"key": {"desc": null, "value": actual_value}}
    """
    raw_content = "\n".join(content_lines)
    if not raw_content.strip():
        return

    config = {}
    try:
        # 尝试 JSON 解析
        parsed = json.loads(raw_content)
        for key, val in parsed.items():
            if isinstance(val, dict) and "value" in val:
                config[key] = val["value"]
            else:
                config[key] = val
    except json.JSONDecodeError:
        # 尝试 YAML 解析
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

    # 保存原始文件
    storage.append_file(entity, project, run_id, "config.yaml", raw_content + "\n")


def _process_log(entity: str, project: str, run_id: str, content_lines: list):
    """处理 output.log — 训练输出日志"""
    raw = "\n".join(content_lines) + "\n"
    storage.append_file(entity, project, run_id, "output.log", raw)


def _save_raw_file(entity: str, project: str, run_id: str,
                   filename: str, content_lines: list):
    """保存原始文件内容"""
    raw = "\n".join(content_lines)
    if raw:
        storage.save_file(entity, project, run_id, filename, raw.encode("utf-8"))
