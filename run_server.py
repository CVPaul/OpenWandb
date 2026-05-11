#!/usr/bin/env python3
"""
OpenWandb v0.2 — 启动脚本
"""
import sys
import os

# 确保项目根目录在 Python Path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uvicorn
from config import HOST, PORT, LOG_LEVEL


def main():
    print(r"""
   ___                 _    _                 _ _
  / _ \ _ __  ___ _ _ | |  | |_ _ _ _  _ _  __| | |__
 | (_) | '_ \/ -_) ' \| |/\| / _` | ' \ ' \/ _` | '_ \
  \___/| .__/\___|_||_|__/\__\__,_|_||_|_||_\__,_|_.__/
       |_|
    Open Source WandB Server v0.2.0
    Multi-tenant | Sharing | Team Management
    """)
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
        "server:app",
        host=HOST,
        port=PORT,
        log_level=LOG_LEVEL.lower(),
        reload=False,
    )


if __name__ == "__main__":
    main()
