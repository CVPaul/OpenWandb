"""
OpenWandb — 数据库 dispatcher
根据 DB_BACKEND 配置自动选择 SQLite 或 PostgreSQL 后端

用法:
    # SQLite (默认):
    openwandb serve

    # PostgreSQL:
    export OPENWANDB_DB_BACKEND=postgres
    export OPENWANDB_PG_URL=postgresql://user:pass@host:5432/openwandb
    openwandb serve
    # 或:
    openwandb serve --pg-url postgresql://user:pass@host:5432/openwandb
"""
import logging

from openwandb.config import DB_BACKEND, DB_PATH

logger = logging.getLogger("openwandb.db")

if DB_BACKEND == "postgres":
    logger.info("Using PostgreSQL backend")
    from openwandb._db_postgres import *  # noqa: F401,F403
    from openwandb._db_postgres import init_db, get_db, DB_PATH  # noqa: F811
else:
    logger.info("Using SQLite backend (DB: %s)", DB_PATH)
    from openwandb._db_sqlite import *  # noqa: F401,F403
    from openwandb._db_sqlite import init_db, get_db
