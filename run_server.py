#!/usr/bin/env python3
"""
OpenWandb — Development mode startup script

For production use:
    pip install openwandb
    openwandb serve

Development mode (no pip install needed):
    python run_server.py
"""
import sys
import os

# Dev mode default data directory: ./data/ (preserves old behavior, does not write to ~/.openwandb)
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
    Open Source WandB Server (dev mode)
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
