"""
OpenWandb v0.3 — 服务配置

路径策略:
- PACKAGE_DIR / TEMPLATES_DIR / STATIC_DIR: 包内只读资源 (pip install 后在 site-packages)
- DATA_DIR / DB_PATH / FILES_DIR / ARTIFACTS_DIR: 用户数据 (默认 ~/.openwandb/)

环境变量 OPENWANDB_DATA_DIR 可自定义数据目录, 例如:
    export OPENWANDB_DATA_DIR=/data/openwandb
    openwandb serve
"""
import os
import secrets
from pathlib import Path

# === 服务配置 ===
HOST = os.getenv("OPENWANDB_HOST", "0.0.0.0")
PORT = int(os.getenv("OPENWANDB_PORT", "8080"))

# === 反向代理路径前缀 ===
# 例如通过 https://example.com/my/prefix/ 访问时, 设置 ROOT_PATH="/my/prefix"
ROOT_PATH = os.getenv("OPENWANDB_ROOT_PATH", "").rstrip("/")

# === 包内资源路径 (只读, 随包安装) ===
PACKAGE_DIR = Path(__file__).parent
TEMPLATES_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"

# === 用户数据目录 (可写, 默认 ~/.openwandb/) ===
_default_data_dir = str(Path.home() / ".openwandb")
DATA_DIR = Path(os.getenv("OPENWANDB_DATA_DIR", _default_data_dir))
DB_PATH = DATA_DIR / "openwandb.db"
FILES_DIR = DATA_DIR / "files"
ARTIFACTS_DIR = DATA_DIR / "artifacts"

DATA_DIR.mkdir(parents=True, exist_ok=True)
FILES_DIR.mkdir(parents=True, exist_ok=True)
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

# === JWT 认证 ===
JWT_SECRET = os.getenv("OPENWANDB_JWT_SECRET", secrets.token_hex(32))
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = int(os.getenv("OPENWANDB_JWT_EXPIRE_HOURS", "72"))

# === 默认管理员 (首次启动自动创建) ===
DEFAULT_ADMIN_USERNAME = os.getenv("OPENWANDB_ADMIN_USER", "admin")
DEFAULT_ADMIN_PASSWORD = os.getenv("OPENWANDB_ADMIN_PASS", "admin123")
DEFAULT_TEAM_NAME = os.getenv("OPENWANDB_DEFAULT_TEAM", "default")

# === 数据库后端 ===
# sqlite (默认, 零依赖) 或 postgres (生产推荐, 需 pip install openwandb[postgres])
DB_BACKEND = os.getenv("OPENWANDB_DB_BACKEND", "sqlite").lower()

# PostgreSQL 连接 (仅 DB_BACKEND=postgres 时使用)
PG_URL = os.getenv("OPENWANDB_PG_URL", "postgresql://openwandb:openwandb@localhost:5432/openwandb")
PG_POOL_MIN = int(os.getenv("OPENWANDB_PG_POOL_MIN", "2"))
PG_POOL_MAX = int(os.getenv("OPENWANDB_PG_POOL_MAX", "10"))

# === 其他 ===
MAX_FILE_SIZE = int(os.getenv("OPENWANDB_MAX_FILE_SIZE", str(500 * 1024 * 1024)))
LOG_LEVEL = os.getenv("OPENWANDB_LOG_LEVEL", "INFO")
ALLOW_REGISTRATION = os.getenv("OPENWANDB_ALLOW_REGISTRATION", "true").lower() == "true"
