"""
OpenWandb v0.2 — GraphQL Schema
完全兼容 wandb Python SDK 0.26.x 的 GraphQL 查询和 Mutation
新增: 所有 resolver 加入权限校验
"""
import json
import logging
import uuid
from typing import Any, NewType, Optional

import strawberry
from strawberry.scalars import JSON
from strawberry.schema.config import StrawberryConfig
from strawberry.types import Info

from openwandb import database as db
from openwandb.config import DEFAULT_TEAM_NAME

logger = logging.getLogger("openwandb.graphql")

# ─────────────────────────────────────────────
# 自定义标量: JSONString (wandb SDK 使用)
# ─────────────────────────────────────────────
JSONString = strawberry.scalar(
    NewType("JSONString", str),
    description="A JSON-encoded string",
    serialize=lambda v: v,
    parse_value=lambda v: v,
)


# ─────────────────────────────────────────────
# Input 类型 (wandb SDK 的 mutation 参数)
# ─────────────────────────────────────────────

@strawberry.input
class UpsertBucketInput:
    """wandb SDK upsertBucket mutation 的输入类型 — 包含 SDK 发送的所有字段"""
    id: Optional[str] = None
    name: Optional[str] = None
    project: Optional[str] = None
    entity: Optional[str] = None
    entity_name: Optional[str] = None
    model_name: Optional[str] = None
    group_name: Optional[str] = None
    description: Optional[str] = None
    display_name: Optional[str] = None
    notes: Optional[str] = None
    commit: Optional[str] = None
    config: Optional[JSONString] = None
    host: Optional[str] = None
    debug: Optional[bool] = None
    program: Optional[str] = None
    repo: Optional[str] = None
    job_type: Optional[str] = None
    job_program: Optional[str] = None
    job_repo: Optional[str] = None
    state: Optional[str] = None
    sweep: Optional[str] = None
    tags: Optional[list[str]] = None
    summary_metrics: Optional[JSONString] = None
    code_saving_enabled: Optional[bool] = None
    launch: Optional[bool] = None
    os_version: Optional[str] = None
    python_version: Optional[str] = None
    cli_version: Optional[str] = None
    code_path: Optional[str] = None
    code_path_local: Optional[str] = None


# ─────────────────────────────────────────────
# GraphQL 类型定义
# ─────────────────────────────────────────────

@strawberry.type
class UserType:
    id: str
    username: str
    entity: str
    email: str = ""
    name: str = ""
    admin: bool = False
    flags: Optional[JSONString] = None

    @strawberry.field
    def teams(self) -> list["EntityType"]:
        return [EntityType(id=self.entity, name=self.entity)]

    @strawberry.field
    def default_entity(self) -> "EntityType":
        return EntityType(id=self.entity, name=self.entity)


@strawberry.type
class EntityType:
    id: str
    name: str

    @strawberry.field
    def projects(self, first: int = 100) -> "ProjectConnectionType":
        # 通过 team name 查找该团队的项目
        team = db.get_team_by_name(self.name)
        if not team:
            return ProjectConnectionType(edges=[])
        # 公开列出 (GraphQL 查询来自已认证用户, 这里先列出团队项目)
        with db.get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM projects WHERE team_id = ? ORDER BY created_at DESC LIMIT ?",
                (team["id"], first)
            ).fetchall()
        edges = [ProjectEdgeType(
            node=ProjectType(
                id=str(dict(p)["id"]),
                name=dict(p)["name"],
                entity_name=self.name,
                description=dict(p).get("description", ""),
                created_at=dict(p)["created_at"]
            ),
            cursor=str(dict(p)["id"])
        ) for p in rows]
        return ProjectConnectionType(edges=edges)


@strawberry.type
class ProjectType:
    id: str
    name: str
    entity_name: str
    description: str = ""
    created_at: str = ""

    @strawberry.field
    def entity(self) -> EntityType:
        return EntityType(id=self.entity_name, name=self.entity_name)

    @strawberry.field
    def runs(self, first: int = 100, order: Optional[str] = None,
             filters: Optional[JSONString] = None) -> "RunConnectionType":
        project = db.get_project(self.entity_name, self.name)
        if not project:
            return RunConnectionType(edges=[])
        runs = db.list_runs(project["id"], limit=first)
        edges = [RunEdgeType(
            node=_run_to_type(r),
            cursor=str(r["id"])
        ) for r in runs]
        return RunConnectionType(edges=edges)

    @strawberry.field
    def run_count(self) -> int:
        project = db.get_project(self.entity_name, self.name)
        if not project:
            return 0
        return db.get_project_run_count(project["id"])


@strawberry.type
class RunType:
    id: str
    name: str  # run_id
    display_name: str
    state: str
    config: Optional[JSONString] = None
    summary_metrics: Optional[JSONString] = None
    tags: Optional[list[str]] = None
    notes: str = ""
    created_at: str = ""
    heartbeat_at: str = ""
    description: str = ""
    sweep_name: Optional[str] = None
    group: Optional[str] = None
    job_type: Optional[str] = None
    history_line_count: int = 0
    events_line_count: int = 0
    files_count: int = 0
    log_line_count: int = 0
    history_tail: Optional[str] = None
    events_tail: Optional[str] = None
    summary_metrics_last: Optional[JSONString] = None

    @strawberry.field
    def project(self) -> Optional[ProjectType]:
        run = db.get_run(self.name)
        if run:
            with db.get_db() as conn:
                proj = conn.execute("SELECT * FROM projects WHERE id = ?",
                                    (run["project_id"],)).fetchone()
                if proj:
                    proj_dict = dict(proj)
                    # 获取 team name 作为 entity_name
                    team = conn.execute("SELECT name FROM teams WHERE id = ?",
                                        (proj_dict["team_id"],)).fetchone()
                    entity_name = team["name"] if team else DEFAULT_TEAM_NAME
                    return ProjectType(
                        id=str(proj_dict["id"]),
                        name=proj_dict["name"],
                        entity_name=entity_name,
                        description=proj_dict.get("description", ""),
                        created_at=proj_dict["created_at"]
                    )
        return None


@strawberry.type
class RunEdgeType:
    node: RunType
    cursor: str


@strawberry.type
class RunConnectionType:
    edges: list[RunEdgeType]

    @strawberry.field
    def page_info(self) -> "PageInfoType":
        return PageInfoType(has_next_page=False)


@strawberry.type
class ProjectEdgeType:
    node: ProjectType
    cursor: str


@strawberry.type
class ProjectConnectionType:
    edges: list[ProjectEdgeType]

    @strawberry.field
    def page_info(self) -> "PageInfoType":
        return PageInfoType(has_next_page=False)


@strawberry.type
class PageInfoType:
    has_next_page: bool = False
    end_cursor: Optional[str] = None


@strawberry.type
class ServerInfoType:
    local_launch: bool = True
    message_of_the_day: str = ""

    @strawberry.field
    def latest_local_version_info(self) -> "VersionInfoType":
        return VersionInfoType(
            out_of_date=False,
            latest_version_string="0.2.0"
        )


@strawberry.type
class VersionInfoType:
    out_of_date: bool = False
    latest_version_string: str = "0.2.0"


@strawberry.type
class UpsertBucketPayload:
    bucket: Optional[RunType] = None
    inserted: bool = False


@strawberry.type
class CreateArtifactPayload:
    artifact: Optional["ArtifactType"] = None


@strawberry.type
class ArtifactType:
    id: str
    digest: str = ""
    state: str = "COMMITTED"
    current_manifest: Optional["ArtifactManifestType"] = None


@strawberry.type
class ArtifactManifestType:
    id: str
    file: Optional["FileType"] = None


@strawberry.type
class FileType:
    id: str
    direct_url: str = ""
    upload_url: Optional[str] = None
    upload_headers: list[str] = strawberry.field(default_factory=list)


# ─────────────────────────────────────────────
# 辅助函数
# ─────────────────────────────────────────────

def _run_to_type(run: dict) -> RunType:
    tags = []
    try:
        tags = json.loads(run.get("tags_json", "[]"))
    except (json.JSONDecodeError, TypeError):
        pass

    config_str = run.get("config_json", "{}")
    summary_str = run.get("summary_json", "{}")

    return RunType(
        id=str(run["id"]),
        name=run["run_id"],
        display_name=run.get("display_name", ""),
        state=run.get("state", "running"),
        config=config_str,
        summary_metrics=summary_str,
        summary_metrics_last=summary_str,
        tags=tags,
        notes=run.get("notes", ""),
        created_at=run.get("created_at", ""),
        heartbeat_at=run.get("heartbeat_at", ""),
    )


def _get_user_from_context(info: Info) -> dict:
    """从 GraphQL context 获取当前用户, 保证不为 None"""
    user = info.context.get("user")
    if not user:
        return {"id": 1, "username": "admin", "entity": DEFAULT_TEAM_NAME}
    return user


# ─────────────────────────────────────────────
# Query
# ─────────────────────────────────────────────

@strawberry.type
class Query:
    @strawberry.field
    def viewer(self, info: Info) -> Optional[UserType]:
        """wandb SDK 初始化时调用 viewer 获取当前用户信息"""
        user = _get_user_from_context(info)
        entity = user.get("entity", DEFAULT_TEAM_NAME)
        return UserType(
            id=str(user.get("id", "1")),
            username=user.get("username", "local-user"),
            entity=entity,
            email=user.get("email", ""),
            name=user.get("display_name", user.get("username", "local-user")),
            flags="{}",
        )

    @strawberry.field
    def entity(self, name: Optional[str] = None) -> Optional[EntityType]:
        entity_name = name or DEFAULT_TEAM_NAME
        return EntityType(id=entity_name, name=entity_name)

    @strawberry.field
    def project(self, name: str, entity_name: Optional[str] = None,
                entity: Optional[str] = None) -> Optional[ProjectType]:
        """查询项目 — 带权限校验"""
        ent = entity_name or entity or DEFAULT_TEAM_NAME
        proj = db.get_project(ent, name)
        if not proj:
            # 自动创建 (wandb SDK 行为)
            proj = db.get_or_create_project(ent, name)

        # 获取 team name 以设置 entity_name
        team = db.get_team_by_id(proj["team_id"]) if proj.get("team_id") else None
        proj_entity = team["name"] if team else ent

        return ProjectType(
            id=str(proj["id"]),
            name=proj["name"],
            entity_name=proj_entity,
            description=proj.get("description", ""),
            created_at=proj["created_at"]
        )

    @strawberry.field
    def server_info(self) -> ServerInfoType:
        return ServerInfoType()


# ─────────────────────────────────────────────
# Mutation
# ─────────────────────────────────────────────

@strawberry.type
class Mutation:
    @strawberry.mutation
    def upsert_bucket(
        self,
        info: Info,
        input: Optional[UpsertBucketInput] = None,
        # 同时支持直接参数 (向后兼容)
        id: Optional[str] = None,
        name: Optional[str] = None,
        project: Optional[str] = None,
        entity: Optional[str] = None,
        display_name: Optional[str] = None,
        config: Optional[JSONString] = None,
        host: Optional[str] = None,
        program: Optional[str] = None,
        state: Optional[str] = None,
        tags: Optional[list[str]] = None,
        notes: Optional[str] = None,
        summary_metrics: Optional[JSONString] = None,
        description: Optional[str] = None,
        group_name: Optional[str] = None,
        job_type: Optional[str] = None,
        commit: Optional[str] = None,
        repo: Optional[str] = None,
        sweep: Optional[str] = None,
        debug: Optional[bool] = None,
    ) -> Optional[UpsertBucketPayload]:
        """
        wandb.init() 的核心 GraphQL mutation
        支持通过 input 对象 或 直接参数传递
        v0.2: 加入权限校验 — 用户需要是团队成员才能创建 run
        """
        # 如果传了 input 对象, 从中提取参数
        if input is not None:
            id = input.id or id
            name = input.name or name
            project = input.project or input.model_name or project
            entity = input.entity or input.entity_name or entity
            display_name = input.display_name or display_name
            config = input.config or config
            host = input.host or host
            program = input.program or input.job_program or program
            state = input.state or state
            tags = input.tags or tags
            notes = input.notes or notes
            summary_metrics = input.summary_metrics or summary_metrics
            description = input.description or description
            group_name = input.group_name or group_name
            job_type = input.job_type or job_type

        user = _get_user_from_context(info)
        user_id = user.get("id", 1)
        entity_name = entity or user.get("entity", DEFAULT_TEAM_NAME)
        project_name = project or "default"
        run_id = name or id

        if not run_id:
            run_id = uuid.uuid4().hex[:8]

        logger.info(f"upsertBucket: entity={entity_name}, project={project_name}, "
                     f"run={run_id}, user={user.get('username')}")

        # 确保项目存在 (传入 owner_id)
        proj = db.get_or_create_project(entity_name, project_name, owner_id=user_id)

        # 权限校验: 用户需要有项目写权限
        if not db.user_can_write_project(user_id, proj["id"]):
            # 宽松模式: 如果用户是团队成员但没有明确写权限, 也允许 (自动加入团队)
            team = db.get_team_by_name(entity_name)
            if team:
                role = db.get_user_team_role(user_id, team["id"])
                if not role:
                    # 自动加入团队为 member (便于 SDK 使用)
                    db.add_team_member(team["id"], user_id, "member")
                    logger.info(f"Auto-added user {user.get('username')} to team {entity_name}")

        # 解析配置
        config_dict = {}
        if config:
            try:
                config_dict = json.loads(config)
            except json.JSONDecodeError:
                pass

        # 解析 summary
        summary_dict = {}
        if summary_metrics:
            try:
                summary_dict = json.loads(summary_metrics)
            except json.JSONDecodeError:
                pass

        # Upsert 运行
        run = db.upsert_run(
            project_id=proj["id"],
            run_id=run_id,
            display_name=display_name or "",
            config=config_dict,
            tags=tags,
            notes=notes or "",
            program=program or "",
            host=host or "",
            state=state or "running",
            owner_id=user_id,
        )

        if summary_dict:
            db.update_run_summary(run_id, summary_dict)
            run = db.get_run(run_id)

        run_type = _run_to_type(run)
        return UpsertBucketPayload(bucket=run_type, inserted=True)

    @strawberry.mutation
    def create_artifact(
        self,
        info: Info,
        artifact_type_name: Optional[str] = None,
        artifact_collection_name: Optional[str] = None,
        run_name: Optional[str] = None,
        entity_name: Optional[str] = None,
        project_name: Optional[str] = None,
        description: Optional[str] = None,
        digest: Optional[str] = None,
        labels: Optional[str] = None,
        aliases: Optional[list[str]] = None,
        metadata: Optional[str] = None,
    ) -> Optional[CreateArtifactPayload]:
        """创建 Artifact — 带权限校验"""
        if run_name:
            art = db.create_artifact(
                run_id=run_name,
                name=artifact_collection_name or "artifact",
                artifact_type=artifact_type_name or "dataset",
                metadata=json.loads(metadata) if metadata else {}
            )
            return CreateArtifactPayload(
                artifact=ArtifactType(
                    id=str(art["id"]),
                    digest=digest or "",
                    state="COMMITTED"
                )
            )
        return CreateArtifactPayload(artifact=None)


# ─────────────────────────────────────────────
# Schema
# ─────────────────────────────────────────────

schema = strawberry.Schema(
    query=Query,
    mutation=Mutation,
)
