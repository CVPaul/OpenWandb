# OpenWandb

**Open-source, self-hosted WandB (Weights & Biases) compatible server** — a drop-in replacement for the proprietary wandb server, designed for private deployment.

Just set `WANDB_BASE_URL` and your existing training scripts work seamlessly with your own server — zero code changes required.

[![PyPI version](https://badge.fury.io/py/openwandb.svg)](https://pypi.org/project/openwandb/)
[![License: CC BY-NC 4.0](https://img.shields.io/badge/License-CC%20BY--NC%204.0-lightgrey.svg)](https://creativecommons.org/licenses/by-nc/4.0/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![GitHub stars](https://img.shields.io/github/stars/CVPaul/OpenWandb?style=social)](https://github.com/CVPaul/OpenWandb)

> If you find OpenWandb useful, please consider giving it a star on GitHub — it helps others discover the project!

## Why OpenWandb?

| | **wandb Cloud** | **OpenWandb** |
|---|---|---|
| **Pricing** | Free tier limited; paid plans per user | Free forever |
| **Data location** | wandb servers (US) | Your own server |
| **Privacy** | Data uploaded to third party | 100% on-premise |
| **Setup** | Create account, get API key | `pip install openwandb && openwandb serve` |
| **Code changes** | None | None — just change `WANDB_BASE_URL` |
| **User limits** | Varies by plan | Unlimited |
| **Run limits** | Varies by plan | Unlimited |
| **Storage** | Limited by plan | Limited by your disk |
| **Offline/Air-gapped** | No | Yes |
| **Custom deployment** | No | K8s, Docker, bare metal, NFS |
| **Multi-tenant** | Enterprise only | Built-in |

## Features

- **Fully compatible with wandb Python SDK** — implements GraphQL API + File Stream protocol
- **One-command deployment** — `pip install openwandb && openwandb serve`
- **Built-in CLI** — `openwandb serve / init / demo / version`
- **Multi-tenant isolation** — Team → Project → Run three-level permission hierarchy
- **User management** — Registration/login, JWT + API Key dual authentication
- **Team collaboration** — Create teams, invite members, role management (Owner/Admin/Member/Viewer)
- **Sharing** — Project/run-level token-based share links
- **Web dashboard** — Dark-theme UI with ECharts visualization engine
- **Zero configuration** — SQLite database + local file storage, no Docker/K8s required
- **PostgreSQL support** — Optional PostgreSQL backend for production scale
- **Reverse proxy ready** — Full support for K8s ingress / Nginx with path prefixes
- **Media & Artifacts** — `wandb.Image`, `wandb.Table`, `wandb.Artifact` all supported

## Quick Start

### Install from PyPI (recommended)

```bash
pip install openwandb

# Start the server (data stored in ~/.openwandb/ by default)
openwandb serve

# Customize port and data directory
openwandb serve --port 9090 --data-dir /data/openwandb
```

### Install from source (development)

```bash
git clone https://github.com/CVPaul/OpenWandb.git
cd OpenWandb

# Editable install
pip install -e .
openwandb serve

# Or run directly (data stored in ./data/)
python run_server.py
```

The server runs at `http://localhost:8080` by default.
Default admin credentials: `admin` / `admin123` (change via environment variables in production).

### Configure your training script

Set two environment variables and run your training script as usual:

```bash
export WANDB_BASE_URL=http://localhost:8080
export WANDB_API_KEY=local0000000000000000000000000000000000000000
```

```python
import wandb

wandb.init(project="my-project", config={"lr": 0.001})

for step in range(100):
    loss = train_step()
    wandb.log({"loss": loss, "accuracy": acc}, step=step)

wandb.finish()
```

### Run the built-in demo

OpenWandb ships with a full MNIST demo that showcases all wandb features:

```bash
# Default mode: pure NumPy (no PyTorch needed!)
openwandb demo

# PyTorch Lightning mode
openwandb demo --lightning

# Customize runs and epochs
openwandb demo --runs 5 --epochs 50
```

The demo showcases: `wandb.log()`, `wandb.Image`, `wandb.Table`, `wandb.Artifact`, namespace grouping, multi-run comparison, and more.

### Manage API Keys

1. Log in to the Web UI → Settings → API Keys
2. Create a new API Key
3. Use the new key in your scripts:
   ```bash
   export WANDB_API_KEY=local-xxxxxxxxxxxxxxxxxxxx
   ```

## CLI Reference

```bash
# Start the server
openwandb serve [OPTIONS]
  --host TEXT          Bind address (default: 0.0.0.0)
  --port/-p INT        Port (default: 8080)
  --data-dir PATH      Data directory (default: ~/.openwandb)
  --log-level TEXT     Log level: debug/info/warning/error
  --reload             Enable auto-reload (dev mode)
  --root-path TEXT     URL path prefix for reverse proxy
  --base-url TEXT      Full external URL override for file uploads
  --db TEXT            Database backend: sqlite/postgres
  --pg-url TEXT        PostgreSQL connection URL

# Initialize data directory and database
openwandb init [--data-dir PATH] [--pg-url URL]

# Run MNIST demo
openwandb demo [--lightning] [--runs N] [--epochs N] [--no-run]

# Show version
openwandb version

# Also supports python -m
python -m openwandb serve
```

## Multi-Tenancy

### Create a team

1. Log in → Settings → Teams → Create New Team
2. Invite members to the team
3. Set member roles (Viewer / Member / Admin)

### Team projects

Specify the team via the `entity` parameter in wandb SDK:

```python
wandb.init(project="my-project", entity="my-team")
```

### Project visibility

| Visibility | Description |
|------------|-------------|
| **Private** | Only the creator can access |
| **Team** | Team members can access (default) |
| **Public** | Everyone can access |

### Sharing

Click the "Share" button on any project or run page to generate a public link. Anyone with the link can view (read-only).

## Configuration

All settings are configurable via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENWANDB_DATA_DIR` | `~/.openwandb` | Data storage directory |
| `OPENWANDB_HOST` | `0.0.0.0` | Bind address |
| `OPENWANDB_PORT` | `8080` | Listen port |
| `OPENWANDB_JWT_SECRET` | Random | JWT signing secret |
| `OPENWANDB_JWT_EXPIRE_HOURS` | `72` | JWT expiration (hours) |
| `OPENWANDB_ADMIN_USER` | `admin` | Default admin username |
| `OPENWANDB_ADMIN_PASS` | `admin123` | Default admin password |
| `OPENWANDB_DEFAULT_TEAM` | `default` | Default team name |
| `OPENWANDB_ALLOW_REGISTRATION` | `true` | Allow new user registration |
| `OPENWANDB_MAX_FILE_SIZE` | `500MB` | Maximum file upload size |
| `OPENWANDB_LOG_LEVEL` | `INFO` | Log level |
| `OPENWANDB_DB_BACKEND` | `sqlite` | Database backend (`sqlite` or `postgres`) |
| `OPENWANDB_PG_URL` | | PostgreSQL connection URL |
| `OPENWANDB_ROOT_PATH` | | URL path prefix for reverse proxy |
| `OPENWANDB_BASE_URL` | | Full external URL override for uploads |

## Deployment

### Basic (single machine)

```bash
pip install openwandb
openwandb serve --port 8080 --data-dir /data/openwandb
```

### With PostgreSQL

```bash
openwandb serve --pg-url postgresql://user:pass@db-host:5432/openwandb
```

### Behind a reverse proxy (Nginx / K8s Ingress)

When deploying behind a reverse proxy with a URL path prefix:

```bash
# The server auto-detects the prefix from X-Forwarded-* headers
openwandb serve --root-path /my/prefix
```

**K8s deployment example:**

```yaml
containers:
  - name: openwandb
    image: python:3.12-slim
    command: ["openwandb", "serve", "--root-path", "/my/prefix"]
    env:
      - name: OPENWANDB_DATA_DIR
        value: "/data/openwandb"
      # Optional: override upload URL if headers aren't forwarded correctly
      # - name: OPENWANDB_BASE_URL
      #   value: "https://my-domain.com/my/prefix"
```

The server automatically distinguishes between direct SDK access (internal service) and browser access (through ingress) to generate correct file upload URLs.

### Diagnostic endpoint

Use the built-in debug endpoint to verify reverse proxy configuration:

```
GET /api/v1/debug/headers
```

Returns the computed base URL, detected headers, and proxy status.

## API Endpoints

### wandb SDK compatible endpoints

| Endpoint | Description |
|----------|-------------|
| `POST /graphql` | GraphQL API (wandb SDK core communication) |
| `POST /files/{entity}/{project}/{run}/file_stream` | Metrics stream upload |
| `GET /files/{entity}/{project}/{run}/{filename}` | File download |
| `PUT /files/{entity}/{project}/{run}/{filename}` | File upload |

### Authentication API

| Endpoint | Description |
|----------|-------------|
| `POST /api/v2/auth/register` | User registration |
| `POST /api/v2/auth/login` | User login (returns JWT) |
| `POST /api/v2/auth/logout` | User logout |
| `GET /api/v2/auth/me` | Get current user info |

### Team Management API

| Endpoint | Description |
|----------|-------------|
| `GET /api/v2/teams` | List my teams |
| `POST /api/v2/teams` | Create a team |
| `GET /api/v2/teams/{name}/members` | List members |
| `POST /api/v2/teams/{name}/members` | Invite member |
| `PUT /api/v2/teams/{name}/members/{uid}` | Update role |
| `DELETE /api/v2/teams/{name}/members/{uid}` | Remove member |

### API Key Management

| Endpoint | Description |
|----------|-------------|
| `GET /api/v2/settings/api-keys` | List my API keys |
| `POST /api/v2/settings/api-keys` | Create new key (returns plaintext once) |
| `DELETE /api/v2/settings/api-keys/{id}` | Delete key |

### Sharing API

| Endpoint | Description |
|----------|-------------|
| `POST /api/v2/share` | Create share link |
| `GET /api/v2/share/{token}` | Access via token |
| `DELETE /api/v2/share/{id}` | Revoke share link |
| `GET /s/{token}` | Share link entry (auto-redirect) |

### Internal REST API

| Endpoint | Description |
|----------|-------------|
| `GET /api/v2/projects` | List projects (filtered by permission) |
| `GET /api/v2/projects/{entity}/{project}/runs` | List runs |
| `GET /api/v2/runs/{run_id}/metrics` | Get metric data |
| `GET /api/v2/runs/{run_id}/system_metrics` | Get system metrics |
| `PUT /api/v2/projects/{id}/visibility` | Update visibility |

## Web Dashboard

| Page | Features |
|------|----------|
| **Home** | Project list, team switcher, search, stats overview |
| **Project** | Run list, status filter, sort, share, visibility control |
| **Run Detail** | Metric charts, config viewer, summary, system monitoring, media |
| **Run Compare** | Multi-run metric overlay, hyperparameter diff |
| **Login/Register** | User login, new user registration |
| **Settings** | Profile, API key management, team list |
| **Team** | Member list, invite, role management, team projects |

## Permission Model

```
Team (Organization)
├── Owner   — Full control (delete team, manage roles)
├── Admin   — Manage members (invite/remove)
├── Member  — Read/write (create projects, log runs)
└── Viewer  — Read-only (view projects and runs)

Project
├── Private  — Creator only
├── Team     — Team members (default)
└── Public   — Everyone

Run → Inherits permissions from its parent project
```

## Architecture

```
┌──────────────────┐         ┌──────────────────────────┐
│  wandb Python SDK │ ──────> │     FastAPI Server        │
│  (training script)│  HTTP   │                          │
└──────────────────┘         │  ┌── Auth Middleware ──┐   │
                             │  │ JWT + API Key       │   │
┌──────────────────┐         │  └─────────────────────┘   │
│  Web Dashboard    │ ──────> │                          │
│  (browser)        │  HTTP   │  ┌── GraphQL ──────────┐  │
└──────────────────┘         │  │ Strawberry GraphQL   │  │
                             │  │ (wandb SDK compat)   │  │
                             │  └──────────────────────┘  │
                             │  ┌── REST API ──────────┐  │
                             │  │ Auth / Teams / Share  │  │
                             │  │ Projects / Runs       │  │
                             │  └──────────────────────┘  │
                             │         │                  │
                             │    ┌────▼────┐             │
                             │    │ SQLite  │  (or Postgres)
                             │    │ + Files │             │
                             │    └─────────┘             │
                             └────────────────────────────┘
```

## Project Structure

```
open-wandb/
├── pyproject.toml             # Package config (hatchling)
├── run_server.py              # Dev mode startup script
├── examples/
│   ├── example_train.py       # Mock training example
│   └── example_mlp.py         # MNIST MLP training example
├── openwandb/                 # Python package
│   ├── __init__.py            # Version
│   ├── __main__.py            # python -m openwandb
│   ├── cli.py                 # CLI commands (serve/init/demo/version)
│   ├── config.py              # Configuration (paths/env vars)
│   ├── server.py              # FastAPI main app + all routes
│   ├── database.py            # DB dispatcher (SQLite/Postgres)
│   ├── _db_sqlite.py          # SQLite backend
│   ├── _db_postgres.py        # PostgreSQL backend
│   ├── graphql_schema.py      # GraphQL schema (wandb SDK compat)
│   ├── file_stream.py         # File stream handler
│   ├── storage.py             # File/artifact storage
│   ├── auth.py                # JWT + API Key authentication
│   ├── templates/             # Web UI templates (7 pages)
│   └── static/                # CSS + JS assets
├── tests/                     # Test suite
└── LICENSE                    # CC BY-NC 4.0 License
```

## Contributing

Contributions are welcome! Please follow these steps:

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Commit your changes: `git commit -m 'Add your feature'`
4. Push to the branch: `git push origin feature/your-feature`
5. Open a Pull Request

### Development setup

```bash
git clone https://github.com/CVPaul/OpenWandb.git
cd OpenWandb
pip install -e ".[dev]"
pytest
```

## License

This project is licensed under [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) — free for non-commercial use. Commercial use requires a separate license agreement.
