#!/usr/bin/env python3
"""
OpenWandb — 开发模式启动脚本

生产环境请使用:
    pip install openwandb
    openwandb serve

开发模式 (无需 pip install):
    python run_server.py
"""
import sys
import os

# 开发模式: 将 src/ 加入 Python Path, 使包导入无需安装即可工作
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

# 开发模式默认数据目录: ./data/ (保留旧行为, 不写入 ~/.openwandb)
os.environ.setdefault("OPENWANDB_DATA_DIR",
                      os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))

from openwandb.config import HOST, PORT, LOG_LEVEL, DATA_DIR
import uvicorn


def main():
    print(r"""
   ___                 _    _                 _ _
  / _ \ _ __  ___ _ _ | |  | |_ _ _ _  _ _  __| | |__
 | (_) | '_ \/ -_) ' \| |/\| / _` | ' \ ' \/ _` | '_ \
  \___/| .__/\___|_||_|__/\__\__,_|_||_|_||_\__,_|_.__/
       |_|
    Open Source WandB Server v0.3.0
    Multi-tenant | Sharing | Team Management
    """)
    print(f"  Data directory: {DATA_DIR}")
    print(f"  Starting server on http://{HOST}:{PORT}")
    print(f"  Web Dashboard:  http://localhost:{PORT}")
    print(f"  Login:          http://localhost:{PORT}/login")
    print(f"  GraphQL API:    http://localhost:{PORT}/graphql")
    print()
    print("  Default admin:  admin / admin123")
    print()
    print("  wandb SDK quick start:")
    print(f"    export WANDB_BASE_URL=http://localhost:{PORT}")
    print("    export WANDB_API_KEY=local0000000000000000000000000000000000000000")
    print("    python your_train_script.py")
    print()

    uvicorn.run(
        "openwandb.server:app",
        host=HOST,
        port=PORT,
        log_level=LOG_LEVEL.lower(),
        reload=False,
    )


if __name__ == "__main__":
    main()
