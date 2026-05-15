"""
OpenWandb v0.3 — Server Configuration

Path strategy:
- PACKAGE_DIR / TEMPLATES_DIR / STATIC_DIR: Package read-only resources (in site-packages after pip install)
- DATA_DIR / DB_PATH / FILES_DIR / ARTIFACTS_DIR: User data (default ~/.openwandb/)

Environment variable OPENWANDB_DATA_DIR can customize the data directory, e.g.:
    export OPENWANDB_DATA_DIR=/data/openwandb
    openwandb serve
"""
import os
import secrets
from pathlib import Path

# === Server config ===
HOST = os.getenv("OPENWANDB_HOST", "0.0.0.0")
PORT = int(os.getenv("OPENWANDB_PORT", "8080"))

# === Reverse proxy path prefix ===
# e.g. when accessed via https://example.com/my/prefix/, set ROOT_PATH="/my/prefix"
ROOT_PATH = os.getenv("OPENWANDB_ROOT_PATH", "").rstrip("/")

# === External full URL (for file upload URL generation) ===
# When deploying with K8s/reverse proxy, if X-Forwarded-Host/Proto headers are not forwarded correctly, specify manually
# Example: https://my-domain.com/prefix
BASE_URL = os.getenv("OPENWANDB_BASE_URL", "").rstrip("/")

# === Package resource paths (read-only, installed with package) ===
PACKAGE_DIR = Path(__file__).parent
TEMPLATES_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"

# === User data directory (writable, default ~/.openwandb/) ===
_default_data_dir = str(Path.home() / ".openwandb")
DATA_DIR = Path(os.getenv("OPENWANDB_DATA_DIR", _default_data_dir))
DB_PATH = DATA_DIR / "openwandb.db"
FILES_DIR = DATA_DIR / "files"
ARTIFACTS_DIR = DATA_DIR / "artifacts"

DATA_DIR.mkdir(parents=True, exist_ok=True)
FILES_DIR.mkdir(parents=True, exist_ok=True)
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

# === JWT Authentication ===
JWT_SECRET = os.getenv("OPENWANDB_JWT_SECRET", secrets.token_hex(32))
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = int(os.getenv("OPENWANDB_JWT_EXPIRE_HOURS", "72"))

# === Default admin (auto-created on first startup) ===
DEFAULT_ADMIN_USERNAME = os.getenv("OPENWANDB_ADMIN_USER", "admin")
DEFAULT_ADMIN_PASSWORD = os.getenv("OPENWANDB_ADMIN_PASS", "admin123")
DEFAULT_TEAM_NAME = os.getenv("OPENWANDB_DEFAULT_TEAM", "default")

# === Database backend ===
# Supports "sqlite" (default) or "postgres"
DB_BACKEND = os.getenv("OPENWANDB_DB_BACKEND", "sqlite").lower()
PG_URL = os.getenv("OPENWANDB_PG_URL", "")
PG_POOL_MIN = int(os.getenv("OPENWANDB_PG_POOL_MIN", "2"))
PG_POOL_MAX = int(os.getenv("OPENWANDB_PG_POOL_MAX", "10"))

# === Other ===
MAX_FILE_SIZE = int(os.getenv("OPENWANDB_MAX_FILE_SIZE", str(500 * 1024 * 1024)))
LOG_LEVEL = os.getenv("OPENWANDB_LOG_LEVEL", "INFO")
ALLOW_REGISTRATION = os.getenv("OPENWANDB_ALLOW_REGISTRATION", "true").lower() == "true"
