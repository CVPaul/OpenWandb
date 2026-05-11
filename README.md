# OpenWandb

**开源的 WandB (Weights & Biases) 兼容服务器** — 完全替代 wandb 闭源服务端，支持私有部署。

用户只需设置 `WANDB_BASE_URL` 环境变量，即可将现有训练代码**无缝迁移**到自建服务器，无需修改任何训练脚本。

## v0.2 新特性

- **多租户隔离** — Team → Project → Run 三级权限继承
- **用户管理** — 注册/登录、JWT + API Key 双模认证
- **团队协作** — 创建团队、邀请成员、角色管理 (Owner/Admin/Member/Viewer)
- **分享功能** — 项目/运行级别的 Token 分享链接
- **项目可见性** — Private / Team / Public 三级可见性控制
- **API Key 管理** — 创建/删除/查看 API Key，支持 wandb SDK 认证

## 核心特性

- **完全兼容 wandb Python SDK** — 实现 GraphQL API + File Stream 协议
- **Web 可视化仪表盘** — 项目管理、运行详情、指标图表、运行对比
- **零配置部署** — SQLite 数据库 + 本地文件存储，单命令启动
- **深色主题 UI** — 专业的深色主题界面，ECharts 图表引擎
- **轻量级** — 纯 Python 实现，无需 Docker/K8s

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 启动服务

```bash
python run_server.py
```

服务默认运行在 `http://localhost:8080`

默认管理员账号: `admin` / `admin123`

### 3. 配置训练脚本

只需设置两个环境变量：

```bash
export WANDB_BASE_URL=http://localhost:8080
export WANDB_API_KEY=local0000000000000000000000000000000000000000
```

然后正常运行你的训练脚本即可！

```python
import wandb

wandb.init(project="my-project", config={"lr": 0.001})

for step in range(100):
    loss = train_step()
    wandb.log({"loss": loss, "accuracy": acc}, step=step)

wandb.finish()
```

### 4. 查看结果

打开浏览器访问 `http://localhost:8080` 查看 Web 仪表盘。

### 5. 管理 API Key

1. 登录 Web UI → Settings → API Keys
2. 创建新的 API Key
3. 使用新 Key 替代默认 Key:
   ```bash
   export WANDB_API_KEY=local-xxxxxxxxxxxxxxxxxxxx
   ```

## 多租户使用

### 创建团队

1. 登录 → Settings → Teams → Create New Team
2. 邀请成员加入团队
3. 设置成员角色 (Viewer / Member / Admin)

### 团队项目

通过 wandb SDK 的 `entity` 参数指定团队:

```python
wandb.init(project="my-project", entity="my-team")
```

### 项目可见性

| 可见性 | 说明 |
|--------|------|
| **Private** | 仅创建者可见 |
| **Team** | 团队成员可见 (默认) |
| **Public** | 所有人可见 |

### 分享

在项目页或运行页点击 "Share" 按钮，生成公开链接。任何人可通过链接查看 (只读)。

## 运行示例

### 快速演示 (模拟数据, 无需 GPU)

```bash
# 终端 1: 启动服务器
python run_server.py

# 终端 2: 运行模拟训练
python example_train.py
```

### MLP 真实训练 (MNIST 手写数字识别)

一个完整的 PyTorch 训练脚本，用 MLP 识别手写数字，全程用 wandb 记录：

```bash
# 安装 PyTorch (如果还没有)
pip install torch torchvision

# 终端 1: 启动服务器
python run_server.py

# 终端 2: 运行训练 (默认参数)
python example_mlp.py

# 修改超参数再跑一次, 然后在 Web UI 中对比两次实验!
python example_mlp.py --lr 0.01 --hidden 128 --optimizer sgd --epochs 10
```

脚本会自动下载 MNIST 数据集、训练模型、并将所有指标上传到 OpenWandb。
打开 `http://localhost:8080` → 进入 `mnist-mlp` 项目 → 查看曲线图、对比不同实验。

## Web 仪表盘

| 页面 | 功能 |
|------|------|
| **首页** | 项目列表、团队切换、搜索、统计概览 |
| **项目页** | 运行列表、状态过滤、排序、分享、可见性控制 |
| **运行详情** | 指标图表、配置查看、Summary、系统监控、分享 |
| **运行对比** | 多运行指标叠加图、超参数差异对比 |
| **登录/注册** | 用户登录、新用户注册 |
| **设置** | 个人信息、API Key 管理、团队列表 |
| **团队管理** | 成员列表、邀请、角色修改、团队项目 |

## API 端点

### wandb SDK 兼容端点

| 端点 | 说明 |
|------|------|
| `POST /graphql` | GraphQL API (wandb SDK 核心通信) |
| `POST /files/{entity}/{project}/{run}/file_stream` | 指标流上传 |
| `GET /files/{entity}/{project}/{run}/{filename}` | 文件下载 |
| `PUT /files/{entity}/{project}/{run}/{filename}` | 文件上传 |

### 认证 API

| 端点 | 说明 |
|------|------|
| `POST /api/v2/auth/register` | 用户注册 |
| `POST /api/v2/auth/login` | 用户登录 (返回 JWT) |
| `POST /api/v2/auth/logout` | 用户登出 |
| `GET /api/v2/auth/me` | 获取当前用户信息 |

### 团队管理 API

| 端点 | 说明 |
|------|------|
| `GET /api/v2/teams` | 我的团队列表 |
| `POST /api/v2/teams` | 创建团队 |
| `GET /api/v2/teams/{name}/members` | 成员列表 |
| `POST /api/v2/teams/{name}/members` | 邀请成员 |
| `PUT /api/v2/teams/{name}/members/{uid}` | 修改角色 |
| `DELETE /api/v2/teams/{name}/members/{uid}` | 移除成员 |

### API Key 管理

| 端点 | 说明 |
|------|------|
| `GET /api/v2/settings/api-keys` | 我的 API Key 列表 |
| `POST /api/v2/settings/api-keys` | 创建新 Key (返回明文) |
| `DELETE /api/v2/settings/api-keys/{id}` | 删除 Key |

### 分享 API

| 端点 | 说明 |
|------|------|
| `POST /api/v2/share` | 创建分享链接 |
| `GET /api/v2/share/{token}` | 通过 token 访问 |
| `DELETE /api/v2/share/{id}` | 撤销分享 |
| `GET /s/{token}` | 分享链接入口 (自动跳转) |

### 内部 REST API

| 端点 | 说明 |
|------|------|
| `GET /api/v2/projects` | 项目列表 (按权限过滤) |
| `GET /api/v2/projects/{entity}/{project}/runs` | 运行列表 |
| `GET /api/v2/runs/{run_id}/metrics` | 指标数据 |
| `GET /api/v2/runs/{run_id}/system_metrics` | 系统指标 |
| `PUT /api/v2/projects/{id}/visibility` | 修改可见性 |

## 配置

通过环境变量配置：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OPENWANDB_HOST` | `0.0.0.0` | 监听地址 |
| `OPENWANDB_PORT` | `8080` | 监听端口 |
| `OPENWANDB_JWT_SECRET` | 随机生成 | JWT 签名密钥 |
| `OPENWANDB_JWT_EXPIRE_HOURS` | `72` | JWT 过期时间 (小时) |
| `OPENWANDB_ADMIN_USER` | `admin` | 默认管理员用户名 |
| `OPENWANDB_ADMIN_PASS` | `admin123` | 默认管理员密码 |
| `OPENWANDB_DEFAULT_TEAM` | `default` | 默认团队名 |
| `OPENWANDB_ALLOW_REGISTRATION` | `true` | 是否允许注册 |
| `OPENWANDB_MAX_FILE_SIZE` | `500MB` | 最大文件上传大小 |
| `OPENWANDB_LOG_LEVEL` | `INFO` | 日志级别 |

## 权限模型

```
Team (组织/团队)
├── Owner   — 完全控制 (删除团队、管理成员角色)
├── Admin   — 管理成员 (邀请/移除成员)
├── Member  — 读写 (创建项目、记录 runs)
└── Viewer  — 只读 (查看项目和 runs)

Project
├── Private  — 仅创建者
├── Team     — 团队成员 (默认)
└── Public   — 所有人

Run → 继承所属 Project 的权限
```

## 技术架构

```
┌──────────────────┐         ┌──────────────────────────┐
│  wandb Python SDK │ ──────> │     FastAPI Server        │
│  (训练脚本中)      │  HTTP   │                          │
└──────────────────┘         │  ┌── Auth Middleware ──┐   │
                             │  │ JWT + API Key       │   │
┌──────────────────┐         │  └─────────────────────┘   │
│  Web Dashboard    │ ──────> │                          │
│  (浏览器)         │  HTTP   │  ┌── GraphQL ──────────┐  │
└──────────────────┘         │  │ upsertBucket (+ ACL) │  │
                             │  │ viewer               │  │
                             │  └──────────────────────┘  │
                             │  ┌── REST API ──────────┐  │
                             │  │ Auth / Teams / Share  │  │
                             │  │ Projects / Runs       │  │
                             │  └──────────────────────┘  │
                             │         │                  │
                             │    ┌────▼────┐             │
                             │    │ SQLite  │             │
                             │    │ + ACL   │             │
                             │    └─────────┘             │
                             └────────────────────────────┘
```

## 项目结构

```
open-wandb/
├── server.py              # FastAPI 主入口 + 所有路由
├── database.py            # SQLite 数据库 + 多租户权限
├── graphql_schema.py      # GraphQL schema (wandb SDK 兼容)
├── file_stream.py         # file_stream 处理
├── storage.py             # 文件存储管理
├── auth.py                # JWT + API Key 双模认证
├── config.py              # 服务配置
├── run_server.py          # 启动脚本
├── example_train.py       # 示例训练脚本
├── requirements.txt       # Python 依赖
├── templates/             # Web UI 模板
│   ├── index.html         # 首页 (团队切换器)
│   ├── project.html       # 项目详情 (分享/可见性)
│   ├── run.html           # 运行详情 (分享)
│   ├── compare.html       # 运行对比
│   ├── login.html         # 登录/注册
│   ├── settings.html      # 用户设置 (API Key)
│   └── team.html          # 团队管理
├── static/
│   └── style.css          # 全局样式
├── data/                  # 数据目录 (自动创建)
│   ├── openwandb.db       # SQLite 数据库
│   ├── files/             # 运行文件
│   └── artifacts/         # Artifact 存储
├── LICENSE                # MIT License
└── .gitignore
```

## 贡献

欢迎贡献代码！请遵循以下步骤:

1. Fork 本仓库
2. 创建特性分支: `git checkout -b feature/your-feature`
3. 提交更改: `git commit -m 'Add your feature'`
4. 推送到分支: `git push origin feature/your-feature`
5. 提交 Pull Request

## License

MIT
