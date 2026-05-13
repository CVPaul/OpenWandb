"""
OpenWandb v0.5 — GraphQL Schema
完全兼容 wandb Python SDK 0.16+ / 0.26.x 的 GraphQL 查询和 Mutation
系统性补全所有 SDK 需要的字段: model, bucket, buckets, wandbConfig,
cliVersionInfo, serverSettings, files, commit, artifact mutations 等
"""
import json
import logging
import uuid
from typing import Annotated, Any, NewType, Optional

import strawberry
from strawberry.scalars import JSON
from strawberry.schema.config import StrawberryConfig
from strawberry.types import Info

from openwandb import database as db
from openwandb import __version__ as _version
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


@strawberry.input
class AliasActionInput:
    """wandb SDK 0.26.x sends aliases as objects, not plain strings"""
    alias: Optional[str] = None
    artifact_collection_name: Optional[str] = None


@strawberry.input
class CreateArtifactInput:
    """wandb SDK createArtifact mutation 输入 — 完全兼容 SDK 0.26.x 发送的所有字段"""
    artifact_type_name: Optional[str] = None
    artifact_collection_name: Optional[str] = None
    artifact_collection_names: Optional[list[str]] = None
    run_name: Optional[str] = None
    entity_name: Optional[str] = None
    project_name: Optional[str] = None
    description: Optional[str] = None
    digest: Optional[str] = None
    digest_algorithm: Optional[str] = None
    labels: Optional[str] = None
    aliases: Optional[list[AliasActionInput]] = None
    metadata: Optional[str] = None
    client_i_d: Optional[str] = strawberry.field(default=None, name="clientID")
    client_mutation_id: Optional[str] = None
    sequence_client_i_d: Optional[str] = strawberry.field(default=None, name="sequenceClientID")
    history_step: Optional[int] = None
    distributed_i_d: Optional[str] = strawberry.field(default=None, name="distributedID")
    enable_digest_deduplication: Optional[bool] = None
    storage_region: Optional[str] = None
    ttl_duration_seconds: Optional[int] = None


@strawberry.input
class CreateRunFilesInput:
    """wandb SDK createRunFiles mutation 输入"""
    entity_name: Optional[str] = None
    project_name: Optional[str] = None
    run_name: Optional[str] = None
    files: Optional[list[str]] = None


@strawberry.input
class CreateArtifactManifestInput:
    """wandb SDK createArtifactManifest mutation 输入"""
    artifact_id: Optional[str] = None
    base_artifact_id: Optional[str] = None
    entity_name: Optional[str] = None
    project_name: Optional[str] = None
    run_name: Optional[str] = None
    name: Optional[str] = None
    digest: Optional[str] = None
    type: Optional[str] = None
    include_upload: Optional[bool] = None


@strawberry.input
class CreateArtifactFileSpecInput:
    """单个 artifact 文件规格"""
    artifact_id: Optional[str] = strawberry.field(default=None, name="artifactID")
    name: Optional[str] = None
    md5: Optional[str] = None
    artifact_manifest_id: Optional[str] = strawberry.field(default=None, name="artifactManifestID")
    upload_url: Optional[str] = None
    storage_path: Optional[str] = None


# ─────────────────────────────────────────────
# GraphQL 类型定义
# ─────────────────────────────────────────────

@strawberry.type(name="ApiKey")
class ApiKeyType:
    id: str
    name: str
    description: Optional[str] = None


@strawberry.type(name="User")
class UserType:
    id: str
    username: str
    entity: str
    email: str = ""
    name: str = ""
    admin: bool = False
    flags: Optional[JSONString] = None
    deleted_at: Optional[str] = None

    @strawberry.field
    def teams(self) -> "EntityConnectionType":
        return EntityConnectionType(
            edges=[EntityEdgeType(node=EntityType(id=self.entity, name=self.entity))]
        )

    @strawberry.field
    def default_entity(self) -> "EntityType":
        return EntityType(id=self.entity, name=self.entity)

    @strawberry.field
    def api_keys(self) -> Optional["ApiKeyConnectionType"]:
        return ApiKeyConnectionType(
            edges=[ApiKeyEdgeType(node=ApiKeyType(id="1", name="default"))]
        )


@strawberry.type
class ApiKeyEdgeType:
    node: ApiKeyType


@strawberry.type
class ApiKeyConnectionType:
    edges: list[ApiKeyEdgeType]


@strawberry.type
class EntityEdgeType:
    node: "EntityType"


@strawberry.type
class EntityConnectionType:
    edges: list[EntityEdgeType]


@strawberry.type
class OrganizationType:
    core_weave_organization_id: Optional[str] = None
    name: str = ""


@strawberry.type
class EntityType:
    id: str
    name: str

    @strawberry.field
    def organization(self) -> Optional[OrganizationType]:
        return None

    @strawberry.field
    def projects(self, first: int = 100) -> "ProjectConnectionType":
        team = db.get_team_by_name(self.name)
        if not team:
            return ProjectConnectionType(edges=[])
        projects = _list_projects_by_team(team["id"], limit=first)
        edges = [ProjectEdgeType(
            node=ProjectType(
                id=str(p["id"]),
                name=p["name"],
                entity_name=self.name,
                description=p.get("description", ""),
                created_at=p["created_at"]
            ),
            cursor=str(p["id"])
        ) for p in projects]
        return ProjectConnectionType(edges=edges)


@strawberry.type
class ProjectType:
    id: str
    name: str
    entity_name: str
    description: str = ""
    created_at: str = ""
    is_benchmark: bool = False

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
        edges = [RunEdgeType(node=_run_to_type(r), cursor=str(r["id"])) for r in runs]
        return RunConnectionType(edges=edges)

    @strawberry.field
    def run_count(self) -> int:
        project = db.get_project(self.entity_name, self.name)
        if not project:
            return 0
        return db.get_project_run_count(project["id"])

    @strawberry.field
    def bucket(self, name: Optional[str] = None,
               missing_ok: Optional[bool] = None,
               desc: Optional[str] = None) -> Optional["RunType"]:
        """wandb SDK 旧版用 'bucket' 查询单个 run (= run)
        missingOk: run 不存在时返回 null; desc: 用于 upload_urls 等"""
        if not name:
            return None
        run = db.get_run(name)
        if not run:
            return None
        return _run_to_type(run)

    @strawberry.field
    def buckets(self, first: int = 100, order: Optional[str] = None,
                filters: Optional[JSONString] = None) -> "RunConnectionType":
        """wandb SDK 旧版用 'buckets' 列出 runs (= runs)"""
        return self.runs(first=first, order=order, filters=filters)

    @strawberry.field
    def artifact(self, name: str) -> Optional["ArtifactCollectionType"]:
        return None

    @strawberry.field
    def artifact_type(self, name: str = "") -> Optional["ArtifactTypeInfoType"]:
        """wandb SDK 查询 project 下的 artifact type"""
        return ArtifactTypeInfoType(id="1", name=name or "dataset")

    @strawberry.field
    def artifact_collection(self, name: str = "") -> Optional["ArtifactCollectionType"]:
        """wandb SDK 查询 artifact collection"""
        return None


# ─────────────────────────────────────────────
# RunType — 包含 wandb SDK 查询的所有字段
# ─────────────────────────────────────────────

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
    commit: Optional[str] = None
    history_line_count: int = 0
    events_line_count: int = 0
    files_count: int = 0
    log_line_count: int = 0
    history_tail: Optional[str] = None
    events_tail: Optional[str] = None
    summary_metrics_last: Optional[JSONString] = None
    stopped: bool = False
    running: bool = False
    _config_json: strawberry.Private[str] = "{}"
    _entity_name: strawberry.Private[str] = ""
    _project_name: strawberry.Private[str] = ""

    @strawberry.field
    def wandb_config(self, keys: Optional[list[str]] = None) -> Optional[JSONString]:
        """wandb SDK 查询 wandbConfig(keys: [...])"""
        if keys:
            try:
                full = json.loads(self._config_json)
                filtered = {k: v for k, v in full.items() if k in keys}
                return json.dumps(filtered)
            except (json.JSONDecodeError, TypeError):
                pass
        return self._config_json

    @strawberry.field
    def project(self) -> Optional[ProjectType]:
        run = db.get_run(self.name)
        if run:
            proj_dict = db.get_project_by_id(run["project_id"])
            if proj_dict:
                team = db.get_team_by_id(proj_dict["team_id"])
                entity_name = team["name"] if team else DEFAULT_TEAM_NAME
                return ProjectType(
                    id=str(proj_dict["id"]),
                    name=proj_dict["name"],
                    entity_name=entity_name,
                    description=proj_dict.get("description", ""),
                    created_at=proj_dict["created_at"]
                )
        return None

    @strawberry.field
    def files(self, pattern: Optional[str] = None,
              names: Optional[list[str]] = None,
              first: int = 1000) -> Optional["FileConnectionType"]:
        """wandb SDK 查询 run 的文件列表"""
        file_list = db.list_files(self.name)
        edges = []
        for f in file_list[:first]:
            url = f"/files/{self._entity_name}/{self._project_name}/{self.name}/{f['name']}"
            edges.append(FileEdgeType(
                node=FileType(
                    id=str(f["id"]),
                    name=f["name"],
                    display_name=f["name"],
                    direct_url=url,
                    upload_url=url,
                    md5=f.get("md5", ""),
                    size_bytes=f.get("size", 0),
                    updated_at=f.get("created_at", ""),
                )
            ))
        return FileConnectionType(edges=edges, upload_headers=[])

    @strawberry.field
    def sampling_info(self) -> Optional[JSONString]:
        return None

    @strawberry.field
    def agent(self) -> Optional[str]:
        return None


# ─────────────────────────────────────────────
# Connection / Edge types
# ─────────────────────────────────────────────

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


# ─────────────────────────────────────────────
# File types
# ─────────────────────────────────────────────

@strawberry.type
class FileType:
    id: str
    name: str = ""
    display_name: str = ""
    direct_url: str = ""
    upload_url: Optional[str] = None
    upload_headers: list[str] = strawberry.field(default_factory=list)
    md5: Optional[str] = None
    size_bytes: int = 0
    updated_at: Optional[str] = None

    @strawberry.field
    def url(self, upload: Optional[bool] = None) -> Optional[str]:
        """wandb SDK 查询 url(upload: true/false)"""
        if upload:
            return self.upload_url or self.direct_url
        return self.direct_url


@strawberry.type
class FileEdgeType:
    node: FileType


@strawberry.type
class FileConnectionType:
    edges: list[FileEdgeType]
    upload_headers: list[str] = strawberry.field(default_factory=list)


# ─────────────────────────────────────────────
# Server info types
# ─────────────────────────────────────────────

@strawberry.type
class CliVersionInfoType:
    """wandb SDK 查询 serverInfo.cliVersionInfo.max_cli_version"""
    max_cli_version: Optional[str] = None


@strawberry.type
class ServerFeatureType:
    name: str
    is_enabled: bool = True


@strawberry.type
class ServerMessageType:
    utf_text: str = ""
    plain_text: str = ""
    html_text: str = ""
    message_type: str = ""
    message_level: str = ""


@strawberry.type
class ServerSettingsType:
    """wandb SDK 查询 upsertBucket 返回中的 serverSettings"""
    server_messages: list[ServerMessageType] = strawberry.field(default_factory=list)


@strawberry.type
class ServerInfoType:
    local_launch: bool = True
    message_of_the_day: str = ""

    @strawberry.field
    def latest_local_version_info(self) -> "VersionInfoType":
        return VersionInfoType(
            out_of_date=False,
            latest_version_string=_version
        )

    @strawberry.field
    def cli_version_info(self) -> Optional[CliVersionInfoType]:
        """wandb SDK 需要 cliVersionInfo 是对象而非 None/string"""
        return CliVersionInfoType(max_cli_version=_version)

    @strawberry.field
    def features(self) -> list[ServerFeatureType]:
        return [
            ServerFeatureType(name="artifact", is_enabled=True),
        ]


@strawberry.type
class VersionInfoType:
    out_of_date: bool = False
    latest_version_string: str = _version
    version_on_this_instance_string: str = _version


# ─────────────────────────────────────────────
# Mutation payload types
# ─────────────────────────────────────────────

@strawberry.type
class UpsertBucketPayload:
    bucket: Optional[RunType] = None
    inserted: bool = False
    server_settings: Optional[ServerSettingsType] = None


@strawberry.type
class CreateArtifactPayload:
    artifact: Optional["ArtifactType"] = None


@strawberry.type
class CommitArtifactPayload:
    artifact: Optional["ArtifactType"] = None


@strawberry.type
class ArtifactCollectionType:
    id: str
    name: str = ""

    @strawberry.field
    def artifact_type(self) -> Optional["ArtifactTypeInfoType"]:
        return ArtifactTypeInfoType(id="1", name="model")


@strawberry.type
class ArtifactTypeInfoType:
    id: str
    name: str = ""


@strawberry.type
class ArtifactSequenceType:
    id: str = "1"
    latest_artifact: Optional["ArtifactType"] = None


@strawberry.type
class ArtifactType:
    id: str
    digest: str = ""
    state: str = "COMMITTED"
    current_manifest: Optional["ArtifactManifestType"] = None

    @strawberry.field
    def artifact_sequence(self) -> Optional[ArtifactSequenceType]:
        return ArtifactSequenceType(id=self.id, latest_artifact=None)


@strawberry.type
class ArtifactManifestType:
    id: str
    file: Optional[FileType] = None


@strawberry.type
class CreateArtifactManifestPayload:
    artifact_manifest: Optional[ArtifactManifestType] = None


@strawberry.type
class CreateArtifactFilesPayload:
    files: Optional["ArtifactFileConnectionType"] = None


@strawberry.type
class ArtifactFileEdgeType:
    node: FileType


@strawberry.type
class ArtifactFileConnectionType:
    edges: list[ArtifactFileEdgeType] = strawberry.field(default_factory=list)


@strawberry.type
class CreateRunFilesPayload:
    run_i_d: Optional[str] = strawberry.field(default=None, name="runID")
    upload_headers: list[str] = strawberry.field(default_factory=list)
    files: Optional[list[FileType]] = None


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

    # 查询 entity_name 和 project_name 用于文件 URL
    entity_name = ""
    project_name = ""
    proj_dict = db.get_project_by_id(run.get("project_id")) if run.get("project_id") else None
    if proj_dict:
        project_name = proj_dict["name"]
        team = db.get_team_by_id(proj_dict["team_id"]) if proj_dict.get("team_id") else None
        entity_name = team["name"] if team else DEFAULT_TEAM_NAME

    state = run.get("state", "running")
    return RunType(
        id=str(run["id"]),
        name=run["run_id"],
        display_name=run.get("display_name", ""),
        state=state,
        config=config_str,
        _config_json=config_str,
        summary_metrics=summary_str,
        summary_metrics_last=summary_str,
        tags=tags,
        notes=run.get("notes", ""),
        created_at=run.get("created_at", ""),
        heartbeat_at=run.get("heartbeat_at", ""),
        commit=run.get("commit", ""),
        running=(state == "running"),
        stopped=(state in ("finished", "failed", "crashed")),
        _entity_name=entity_name,
        _project_name=project_name,
    )


def _list_projects_by_team(team_id: int, limit: int = 100) -> list[dict]:
    """列出团队下的项目 — 兼容 SQLite/PostgreSQL"""
    with db.get_db() as conn:
        from openwandb.config import DB_BACKEND
        if DB_BACKEND == "postgres":
            conn.execute(
                "SELECT * FROM projects WHERE team_id = %s ORDER BY created_at DESC LIMIT %s",
                (team_id, limit)
            )
            return [dict(r) for r in conn.fetchall()]
        else:
            cur = conn.execute(
                "SELECT * FROM projects WHERE team_id = ? ORDER BY created_at DESC LIMIT ?",
                (team_id, limit)
            )
            return [dict(r) for r in cur.fetchall()]


def _get_user_from_context(info: Info) -> dict:
    user = info.context.get("user")
    if not user:
        return {"id": 1, "username": "admin", "entity": DEFAULT_TEAM_NAME}
    return user


def _resolve_project(name, entity_name, entity):
    """共享的 project/model 查询逻辑"""
    ent = entity_name or entity or DEFAULT_TEAM_NAME
    proj = db.get_project(ent, name)
    if not proj:
        proj = db.get_or_create_project(ent, name)
    team = db.get_team_by_id(proj["team_id"]) if proj.get("team_id") else None
    proj_entity = team["name"] if team else ent
    return ProjectType(
        id=str(proj["id"]),
        name=proj["name"],
        entity_name=proj_entity,
        description=proj.get("description", ""),
        created_at=proj["created_at"]
    )


# ─────────────────────────────────────────────
# Query
# ─────────────────────────────────────────────

@strawberry.type
class Query:
    @strawberry.field
    def viewer(self, info: Info) -> Optional[UserType]:
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
        return EntityType(id=name or DEFAULT_TEAM_NAME, name=name or DEFAULT_TEAM_NAME)

    @strawberry.field
    def project(self, name: Optional[str] = None, entity_name: Optional[str] = None,
                entity: Optional[str] = None) -> Optional[ProjectType]:
        return _resolve_project(name, entity_name, entity)

    @strawberry.field
    def model(self, name: Optional[str] = None, entity_name: Optional[str] = None,
              entity: Optional[str] = None) -> Optional[ProjectType]:
        """wandb SDK 旧版用 'model' 查询项目 (= project)"""
        return _resolve_project(name, entity_name, entity)

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

        proj = db.get_or_create_project(entity_name, project_name, owner_id=user_id)

        if not db.user_can_write_project(user_id, proj["id"]):
            team = db.get_team_by_name(entity_name)
            if team:
                role = db.get_user_team_role(user_id, team["id"])
                if not role:
                    db.add_team_member(team["id"], user_id, "member")
                    logger.info(f"Auto-added user {user.get('username')} to team {entity_name}")

        config_dict = {}
        if config:
            try:
                config_dict = json.loads(config)
            except json.JSONDecodeError:
                pass

        summary_dict = {}
        if summary_metrics:
            try:
                summary_dict = json.loads(summary_metrics)
            except json.JSONDecodeError:
                pass

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
        return UpsertBucketPayload(
            bucket=run_type,
            inserted=True,
            server_settings=ServerSettingsType(server_messages=[])
        )

    @strawberry.mutation
    def create_artifact(
        self,
        info: Info,
        input: Optional[CreateArtifactInput] = None,
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
        if input is not None:
            artifact_type_name = input.artifact_type_name or artifact_type_name
            artifact_collection_name = input.artifact_collection_name or artifact_collection_name
            run_name = input.run_name or run_name
            entity_name = input.entity_name or entity_name
            project_name = input.project_name or project_name
            description = input.description or description
            digest = input.digest or digest
            metadata = input.metadata or metadata

        logger.info(f"createArtifact: run={run_name}, type={artifact_type_name}, "
                     f"collection={artifact_collection_name}, digest={digest}")

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

    @strawberry.mutation
    def commit_artifact(
        self,
        info: Info,
        artifact_id: Annotated[Optional[str], strawberry.argument(name="artifactID")] = None,
    ) -> Optional[CommitArtifactPayload]:
        """wandb SDK commitArtifact mutation"""
        logger.info(f"commitArtifact: id={artifact_id}")
        return CommitArtifactPayload(
            artifact=ArtifactType(id=artifact_id or "0", digest="", state="COMMITTED")
        )

    @strawberry.mutation
    def create_artifact_manifest(
        self,
        info: Info,
        artifact_id: Annotated[Optional[str], strawberry.argument(name="artifactID")] = None,
        base_artifact_id: Annotated[Optional[str], strawberry.argument(name="baseArtifactID")] = None,
        entity_name: Optional[str] = None,
        project_name: Optional[str] = None,
        run_name: Optional[str] = None,
        name: Optional[str] = None,
        digest: Optional[str] = None,
        type: Optional[str] = None,
        include_upload: Optional[bool] = None,
    ) -> Optional[CreateArtifactManifestPayload]:
        """wandb SDK createArtifactManifest mutation"""
        logger.info(f"createArtifactManifest: artifact_id={artifact_id}, name={name}")
        manifest_id = uuid.uuid4().hex[:8]
        upload_url = f"/artifacts/{entity_name or 'default'}/{project_name or 'default'}/{run_name or 'unknown'}/manifest"
        return CreateArtifactManifestPayload(
            artifact_manifest=ArtifactManifestType(
                id=manifest_id,
                file=FileType(
                    id=manifest_id,
                    name=name or "manifest.json",
                    display_name=name or "manifest.json",
                    direct_url=upload_url,
                    upload_url=upload_url,
                    upload_headers=[],
                )
            )
        )

    @strawberry.mutation
    def create_artifact_files(
        self,
        info: Info,
        artifact_id: Annotated[Optional[str], strawberry.argument(name="artifactID")] = None,
        artifact_files: Optional[list[CreateArtifactFileSpecInput]] = None,
    ) -> Optional[CreateArtifactFilesPayload]:
        """wandb SDK createArtifactFiles mutation"""
        logger.info(f"createArtifactFiles: artifact_id={artifact_id}, files={len(artifact_files or [])}")
        edges = []
        for spec in (artifact_files or []):
            fid = uuid.uuid4().hex[:8]
            upload_url = f"/artifacts/upload/{fid}"
            edges.append(ArtifactFileEdgeType(
                node=FileType(
                    id=fid,
                    name=spec.name or "",
                    display_name=spec.name or "",
                    direct_url=upload_url,
                    upload_url=upload_url,
                    upload_headers=[],
                )
            ))
        return CreateArtifactFilesPayload(
            files=ArtifactFileConnectionType(edges=edges)
        )

    @strawberry.mutation
    def create_run_files(
        self,
        info: Info,
        input: Optional[CreateRunFilesInput] = None,
        entity: Optional[str] = None,
        project: Optional[str] = None,
        run: Optional[str] = None,
        files: Optional[list[str]] = None,
    ) -> Optional[CreateRunFilesPayload]:
        if input is not None:
            entity = input.entity_name or entity
            project = input.project_name or project
            run = input.run_name or run
            files = input.files or files

        entity_name = entity or DEFAULT_TEAM_NAME
        run_name = run or ""
        file_list = files or []

        logger.info(f"createRunFiles: entity={entity_name}, project={project}, "
                     f"run={run_name}, files={file_list}")

        result_files = []
        for f in file_list:
            file_id = uuid.uuid4().hex[:8]
            upload_url = f"/files/{entity_name}/{project}/{run_name}/{f}"
            result_files.append(FileType(
                id=file_id,
                name=f,
                display_name=f,
                direct_url=upload_url,
                upload_url=upload_url,
                upload_headers=[],
            ))

        return CreateRunFilesPayload(
            run_i_d=run_name,
            upload_headers=[],
            files=result_files,
        )

    @strawberry.mutation
    def link_artifact(
        self,
        info: Info,
        artifact_id: Annotated[Optional[str], strawberry.argument(name="artifactID")] = None,
        artifact_portfolio_name: Optional[str] = None,
        entity_name: Optional[str] = None,
        project_name: Optional[str] = None,
    ) -> Optional[bool]:
        """wandb SDK linkArtifact mutation — stub"""
        logger.info(f"linkArtifact: id={artifact_id}")
        return True

    @strawberry.mutation
    def use_artifact(
        self,
        info: Info,
        artifact_id: Annotated[Optional[str], strawberry.argument(name="artifactID")] = None,
        entity_name: Optional[str] = None,
        project_name: Optional[str] = None,
        run_name: Optional[str] = None,
    ) -> Optional["ArtifactType"]:
        """wandb SDK useArtifact mutation — stub"""
        logger.info(f"useArtifact: id={artifact_id}")
        return ArtifactType(id=artifact_id or "0", digest="", state="COMMITTED")


# ─────────────────────────────────────────────
# Schema
# ─────────────────────────────────────────────

schema = strawberry.Schema(
    query=Query,
    mutation=Mutation,
)
