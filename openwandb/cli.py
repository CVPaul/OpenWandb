"""
OpenWandb CLI — 服务管理命令行工具

用法:
    openwandb serve          # 启动服务器
    openwandb init           # 初始化数据目录
    openwandb demo           # 生成并运行演示脚本
    openwandb version        # 显示版本
"""
import os
import subprocess
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
    Open Source WandB Server v0.5.1
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
@click.option("--root-path", default=None,
              help="URL path prefix for reverse proxy (e.g. /my/prefix)")
@click.option("--db", type=click.Choice(["sqlite", "postgres"], case_sensitive=False),
              default=None, help="Database backend (default: sqlite)")
@click.option("--pg-url", default=None,
              help="PostgreSQL URL (e.g. postgresql://user:pass@host:5432/db)")
def serve(host, port, data_dir, log_level, reload, root_path, db, pg_url):
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
    if root_path:
        os.environ["OPENWANDB_ROOT_PATH"] = root_path
    if db:
        os.environ["OPENWANDB_DB_BACKEND"] = db.lower()
    if pg_url:
        os.environ["OPENWANDB_PG_URL"] = pg_url

    # 现在导入 config (触发目录创建)
    from openwandb.config import HOST, PORT, LOG_LEVEL, DATA_DIR, ROOT_PATH, DB_BACKEND

    _print_banner(HOST, PORT, DATA_DIR)
    if DB_BACKEND == "postgres":
        from openwandb.config import PG_URL
        # 隐藏密码部分
        display_url = PG_URL
        if "@" in display_url:
            prefix, rest = display_url.split("@", 1)
            if ":" in prefix:
                proto_user = prefix.rsplit(":", 1)[0]
                display_url = f"{proto_user}:****@{rest}"
        click.echo(f"  DB backend:     PostgreSQL")
        click.echo(f"  PG URL:         {display_url}")
    else:
        click.echo(f"  DB backend:     SQLite")
    if ROOT_PATH:
        click.echo(f"  Root path:      {ROOT_PATH}")

    import uvicorn
    uvicorn.run(
        "openwandb.server:app",
        host=HOST,
        port=PORT,
        log_level=LOG_LEVEL.lower(),
        reload=reload,
        root_path=ROOT_PATH,
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
@click.option("--server-url", default=None,
              help="OpenWandb server URL (default: http://localhost:8080)")
@click.option("--api-key", default=None,
              help="API key (default: local0000...)")
@click.option("--project", default="mnist-demo",
              help="Project name (default: mnist-demo)")
@click.option("--runs", default=3, type=int, help="Number of demo runs (default: 3)")
@click.option("--epochs", default=30, type=int, help="Epochs per run (default: 30)")
@click.option("--no-run", is_flag=True, default=False,
              help="Only generate script, don't execute")
@click.option("--output", "-o", default="openwandb-demo.py", type=click.Path(),
              help="Output script path (default: openwandb-demo.py)")
def demo(server_url, api_key, project, runs, epochs, no_run, output):
    """Generate and run an MNIST digit classification demo.

    \b
    Uses PyTorch Lightning to train MLP classifiers on the bundled
    MNIST dataset. The demo showcases wandb SDK features:
      • Config tracking & hyperparameter logging
      • Real-time metric logging (loss, accuracy)
      • wandb.Image — prediction samples with labels
      • wandb.Table — prediction results comparison
      • wandb.Artifact — model weight versioning
      • Namespace grouping (train/*, val/*)
      • Cosine annealing learning rate schedule
      • Multi-run comparison across architectures
      • Tags, notes, and group for organizing experiments

    \b
    Prerequisites: pip install torch lightning wandb

    \b
    Examples:
      openwandb demo                     # Default: 3 runs × 30 epochs
      openwandb demo --runs 5 --epochs 50
      openwandb demo --no-run            # Only generate script
      openwandb demo --server-url http://myserver:8080
    """
    if server_url is None:
        server_url = os.environ.get("WANDB_BASE_URL", "http://localhost:8080")
    if api_key is None:
        api_key = os.environ.get(
            "WANDB_API_KEY",
            "local0000000000000000000000000000000000000000"
        )

    # 读取包内 demo 模板
    demo_template_path = Path(__file__).parent / "demo_script.py"
    template = demo_template_path.read_text(encoding="utf-8")

    # 替换参数占位符
    script_content = (template
                      .replace("{server_url}", server_url)
                      .replace("{api_key}", api_key)
                      .replace("{project}", project)
                      .replace("{num_runs}", str(runs))
                      .replace("{epochs}", str(epochs)))

    # 写出到目标文件
    output_path = Path(output).resolve()
    output_path.write_text(script_content, encoding="utf-8")

    click.echo()
    click.echo("=" * 60)
    click.echo("  OpenWandb Demo — ML Experiment Tracking Showcase")
    click.echo("=" * 60)
    click.echo()
    click.echo(f"  Demo script saved to: {output_path}")
    click.echo(f"  You can re-run it anytime: python {output}")
    click.echo()
    click.echo(f"  Server:     {server_url}")
    click.echo(f"  Project:    {project}")
    click.echo(f"  Runs:       {runs}")
    click.echo(f"  Epochs:     {epochs}")
    click.echo("=" * 60)

    if no_run:
        click.echo()
        click.echo("  --no-run specified, skipping execution.")
        click.echo(f"  Run it manually: python {output}")
        click.echo()
        return

    # 检查依赖
    missing = []
    try:
        import torch  # noqa: F401
    except ImportError:
        missing.append("torch")
    try:
        import lightning  # noqa: F401
    except ImportError:
        try:
            import pytorch_lightning  # noqa: F401
        except ImportError:
            missing.append("lightning")
    try:
        import wandb  # noqa: F401
    except ImportError:
        missing.append("wandb")
    if missing:
        click.echo()
        click.secho("  ERROR: missing packages: %s" % ", ".join(missing),
                     fg="red", bold=True)
        click.echo("  Install first: pip install %s" % " ".join(missing))
        click.echo(f"  Then run: python {output}")
        click.echo()
        sys.exit(1)

    click.echo()
    click.echo("  Running demo...")
    click.echo()

    # 执行生成的脚本 (使用当前 Python 解释器)
    result = subprocess.run(
        [sys.executable, str(output_path)],
        cwd=str(output_path.parent),
    )

    if result.returncode != 0:
        click.secho(f"\n  Demo exited with code {result.returncode}", fg="red")
        sys.exit(result.returncode)


@main.command()
def version():
    """Show version information."""
    from openwandb import __version__
    click.echo(f"OpenWandb v{__version__}")


if __name__ == "__main__":
    main()
