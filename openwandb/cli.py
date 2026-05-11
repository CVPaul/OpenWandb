"""
OpenWandb CLI — 服务管理命令行工具

用法:
    openwandb serve          # 启动服务器
    openwandb init           # 初始化数据目录
    openwandb version        # 显示版本
"""
import os
import sys
from pathlib import Path

import click


def _print_banner(host: str, port: int, data_dir: Path):
    """打印启动横幅"""
    click.echo(r"""
   ___                 _    _                 _ _
  / _ \ _ __  ___ _ _ | |  | |_ _ _ _  _ _  __| | |__
 | (_) | '_ \/ -_) ' \| |/\| / _` | ' \ ' \/ _` | '_ \
  \___/| .__/\___|_||_|__/\__\__,_|_||_|_||_\__,_|_.__/
       |_|
    Open Source WandB Server v0.3.0
    Multi-tenant | Sharing | Team Management
    """)
    click.echo(f"  Data directory: {data_dir}")
    click.echo(f"  Starting server on http://{host}:{port}")
    click.echo(f"  Web Dashboard:  http://localhost:{port}")
    click.echo(f"  Login:          http://localhost:{port}/login")
    click.echo(f"  GraphQL API:    http://localhost:{port}/graphql")
    click.echo()
    click.echo("  Default admin:  admin / admin123")
    click.echo()
    click.echo("  wandb SDK quick start:")
    click.echo(f"    export WANDB_BASE_URL=http://localhost:{port}")
    click.echo("    export WANDB_API_KEY=local0000000000000000000000000000000000000000")
    click.echo("    python your_train_script.py")
    click.echo()


@click.group(invoke_without_command=True)
@click.pass_context
@click.version_option(package_name="openwandb")
def main(ctx):
    """OpenWandb - Open-source WandB-compatible server.

    Run 'openwandb serve' to start the server, or 'openwandb --help' for more options.
    """
    # 如果没有子命令, 默认执行 serve
    if ctx.invoked_subcommand is None:
        ctx.invoke(serve)


@main.command()
@click.option("--host", default=None, help="Bind address (default: 0.0.0.0)")
@click.option("--port", "-p", default=None, type=int, help="Port (default: 8080)")
@click.option("--data-dir", default=None, type=click.Path(),
              help="Data directory (default: ~/.openwandb)")
@click.option("--log-level", default=None,
              type=click.Choice(["debug", "info", "warning", "error"], case_sensitive=False),
              help="Log level (default: INFO)")
@click.option("--reload", is_flag=True, default=False, help="Enable auto-reload (dev mode)")
def serve(host, port, data_dir, log_level, reload):
    """Start the OpenWandb server."""
    # 在 import config 之前设置环境变量 (config 在导入时读取)
    if data_dir:
        os.environ["OPENWANDB_DATA_DIR"] = str(Path(data_dir).resolve())
    if host:
        os.environ["OPENWANDB_HOST"] = host
    if port is not None:
        os.environ["OPENWANDB_PORT"] = str(port)
    if log_level:
        os.environ["OPENWANDB_LOG_LEVEL"] = log_level.upper()

    # 现在导入 config (触发目录创建)
    from openwandb.config import HOST, PORT, LOG_LEVEL, DATA_DIR

    _print_banner(HOST, PORT, DATA_DIR)

    import uvicorn
    uvicorn.run(
        "openwandb.server:app",
        host=HOST,
        port=PORT,
        log_level=LOG_LEVEL.lower(),
        reload=reload,
    )


@main.command()
@click.option("--data-dir", default=None, type=click.Path(),
              help="Data directory to initialize (default: ~/.openwandb)")
def init(data_dir):
    """Initialize the data directory and database."""
    if data_dir:
        os.environ["OPENWANDB_DATA_DIR"] = str(Path(data_dir).resolve())

    from openwandb.config import DATA_DIR, DB_PATH
    from openwandb import database as db

    click.echo(f"Initializing OpenWandb data directory: {DATA_DIR}")
    click.echo(f"  Database: {DB_PATH}")
    click.echo(f"  Files:    {DATA_DIR / 'files'}")
    click.echo(f"  Artifacts: {DATA_DIR / 'artifacts'}")

    db.init_db()

    click.echo()
    click.echo("Done! Run 'openwandb serve' to start the server.")


@main.command()
def version():
    """Show version information."""
    from openwandb import __version__
    click.echo(f"OpenWandb v{__version__}")


if __name__ == "__main__":
    main()
