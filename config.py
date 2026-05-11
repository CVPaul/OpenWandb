"""
OpenWandb v0.2 — 服务配置
"""
import os
import secrets
from pathlib import Path

# === 服务配置 ===
HOST = os.getenv("OPENWANDB_HOST", "0.0.0.0")
PORT = int(os.getenv("OPENWANDB_PORT", "8080"))

# === 数据目录 ===
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "openwandb.db"
FILES_DIR = DATA_DIR / "files"
ARTIFACTS_DIR = DATA_DIR / "artifacts"

DATA_DIR.mkdir(exist_ok=True)
FILES_DIR.mkdir(exist_ok=True)
ARTIFACTS_DIR.mkdir(exist_ok=True)

# === JWT 认证 ===
JWT_SECRET = os.getenv("OPENWANDB_JWT_SECRET", secrets.token_hex(32))
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = int(os.getenv("OPENWANDB_JWT_EXPIRE_HOURS", "72"))

# === 默认管理员 (首次启动自动创建) ===
DEFAULT_ADMIN_USERNAME = os.getenv("OPENWANDB_ADMIN_USER", "admin")
DEFAULT_ADMIN_PASSWORD = os.getenv("OPENWANDB_ADMIN_PASS", "admin123")
DEFAULT_TEAM_NAME = os.getenv("OPENWANDB_DEFAULT_TEAM", "default")

# === 其他 ===
MAX_FILE_SIZE = int(os.getenv("OPENWANDB_MAX_FILE_SIZE", str(500 * 1024 * 1024)))
LOG_LEVEL = os.getenv("OPENWANDB_LOG_LEVEL", "INFO")
ALLOW_REGISTRATION = os.getenv("OPENWANDB_ALLOW_REGISTRATION", "true").lower() == "true"
