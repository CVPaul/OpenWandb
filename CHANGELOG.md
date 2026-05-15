# Changelog

All notable changes to OpenWandb will be documented in this file.

## [0.5.25] - 2025-05-15

### Fixed
- **Stale database connection after long idle**: PostgreSQL connections in the pool could be silently dropped by firewalls or load balancers during idle periods, causing "Internal Error" on the next request. Added connection health check (`SELECT 1`) before each use — stale connections are automatically replaced.
- **PostgreSQL TCP keepalive**: Connection pool now enables TCP keepalive (60s idle, 10s interval, 5 retries) to keep connections alive through network middleboxes.
- **SQLite lock timeout**: Increased from default 5s to 30s to handle NFS and high-concurrency scenarios.
- **Global error handler**: Unhandled exceptions now return structured JSON error with error type instead of bare "Internal Server Error", with full stack trace in server logs.

## [0.5.24] - 2025-05-15

### Changed
- **License**: Changed from MIT to CC BY-NC 4.0 (non-commercial use only).
- **Documentation**: Full English rewrite of README, CHANGELOG, code comments, and docstrings for open-source promotion.
- **Code cleanup**: Removed all internal/sensitive references; translated all Chinese comments to English.

## [0.5.23] - 2025-05-14

### Fixed
- **Smart proxy detection for upload URLs**: `_get_base_url()` now auto-detects whether a request comes through a reverse proxy (via `x-forwarded-host` header) or directly from the SDK. Direct SDK connections no longer get the `ROOT_PATH` prefix appended, fixing file uploads in K8s deployments where the SDK connects to the internal service while browsers access through the ingress.

### Improved
- Debug endpoint `/api/v1/debug/headers` now shows `is_proxied` field for easier diagnosis.

## [0.5.22] - 2025-05-14

### Added
- **`OPENWANDB_BASE_URL` environment variable**: Highest-priority override for file upload URL generation. Useful when reverse proxy headers are not forwarded correctly.
- **`--base-url` CLI option**: Pass the external URL directly via command line.
- **Diagnostic endpoint** (`GET /api/v1/debug/headers`): Shows computed base URL, detected headers, and proxy configuration for troubleshooting reverse proxy setups.

## [0.5.21] - 2025-05-13

### Fixed
- **GraphQL type compatibility**: Fixed `[String]!` vs `[String!]` mismatch in `RunType.files()` that blocked all file upload URL requests from wandb SDK.
- **`ProjectType.run(name:)` field**: Added missing field that wandb SDK queries for single run lookup.
- **`ArtifactAliasInput` type name**: Renamed from `AliasActionInput` to match SDK's expected type name.
- **`Int64` scalar type**: Added support for 64-bit integer fields used by artifact mutations.
- **`ID` scalar support**: `clientID` and `sequenceClientID` fields now use `strawberry.ID` type.
- **`JSONString` type for labels/metadata**: Artifact labels and metadata now use correct scalar type.
- **`ArtifactManifestHashType` enum**: Added `MANIFEST_MD5` enum value for digest algorithm.
- **`ArtifactType` fields**: Added `aliases`, `version_index`, `artifact_sequence`, `description`, `size`, `labels`, `metadata`, `file_count`, `artifact_type`, and other fields required by SDK.
- **Upload URL generation**: `RunType.files()` now generates upload URLs for new files (not just existing ones), enabling the SDK to upload media files.
- **Media file registration**: `_process_history()` now extracts `wandb.Image`, `wandb.Table`, and other media references from history JSON and registers them in the database.
- **File registration idempotency**: `register_file()` uses `INSERT OR IGNORE` to prevent duplicate errors.
- **Artifact path updates**: Added `update_artifact_path()` for updating artifact file paths after upload.

### Added
- **`Query.artifact(id:)` field**: SDK can now query individual artifacts by ID.

## [0.5.20] - 2025-05-12

### Added
- Initial multi-tenant support with team-based isolation
- JWT + API Key dual authentication
- GraphQL API compatible with wandb Python SDK
- File Stream protocol for metrics upload
- Web dashboard with dark theme and ECharts
- Project/run sharing via token-based links
- PostgreSQL backend option
- MNIST demo with both NumPy and PyTorch Lightning modes
- CLI tools: `openwandb serve`, `init`, `demo`, `version`
- Reverse proxy support via `--root-path`
