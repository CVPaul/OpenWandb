"""
OpenWandb — Database dispatcher
Auto-selects SQLite or PostgreSQL backend based on DB_BACKEND config.

Usage:
    # SQLite (default):
    openwandb serve

    # PostgreSQL:
    export OPENWANDB_DB_BACKEND=postgres
    export OPENWANDB_PG_URL=postgresql://user:pass@host:5432/openwandb
    openwandb serve
    # Or:
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
