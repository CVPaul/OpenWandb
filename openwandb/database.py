"""
OpenWandb — 数据库后端 dispatcher

根据 OPENWANDB_DB_BACKEND 环境变量选择后端:
  - sqlite  (默认) — 零依赖, 适合本地开发和小规模部署
  - postgres — 生产推荐, 需 pip install openwandb[postgres]

所有调用方不需要任何改动:
    from openwandb import database as db
    db.get_run(run_id)  # 自动使用对应后端
"""
from openwandb.config import DB_BACKEND

if DB_BACKEND == "postgres":
    from openwandb._db_postgres import *  # noqa: F401,F403
else:
    from openwandb._db_sqlite import *  # noqa: F401,F403
