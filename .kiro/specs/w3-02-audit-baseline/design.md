# 设计文档：审计与日志基线
> spec：`w3-02-audit-baseline` ｜ 波次：Wave 3 ｜ 基线：`757fd12` ｜ 预估：34 人日
> 前置：`w0-01-fork-migration-namespace`、`w0-02-ci-gates`、`w0-03-test-auth-baseline`、`w0-04-fork-isolation-points`、`w1-02-capability-trim`、`w1-05-saas-decoupling`、`w3-01-web-security-baseline` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 概述

本 spec 在 `AuditRepo` 一处收口：请求上下文由最外层中间件写入 contextvar，`jwt_auth` 在认证成功后补上操作人与会话，`AuditRepo.write` 缺省从上下文补齐字段。因此 41 个既有写入点不必改签名。之后按四条线补齐：真实操作人与覆盖面、线程软删除与保留期、日志 Formatter 与 stdout、syslog 外发与下载兜底。表结构变更走一条 fork 迁移，不新增 ErrorCode。

## 现状

- 审计仓库：`src/octop/infra/db/repos/audit.py` 定义 `ACTOR_SYSTEM`（≈L10）、`ACTOR_ADMIN`（≈L11）、`write`（≈L39）、`system_event/admin_event/user_event`、`delete_before`（≈L109）。`delete_before` 全仓没有调用方。唯一构造点是 `infra/db/services.py` 的 `audit_repo=AuditRepo(db)`（≈L81）。
- 写入点：`rg 'audit_repo\.(write|system_event|admin_event|user_event)'` 共 41 处、14 个文件，其中 `infra/users/manager.py` 17 处。
- `ACTOR_ADMIN` 使用点共 14 处：`infra/users/manager.py` 10 处（≈L516/533/570/577/599/637/696/713/721/737），`api/routers/security.py` 3 处（≈L73/165/183，import 在 ≈L13），`api/routers/backup.py` 1 处兜底（≈L353，import 在 ≈L39）。
- 中间件：`api/app.py` 依次 `install_jwt_auth`（≈L132）、`install_setup_lockdown`（≈L133）。两者都是 `@app.middleware("http")`，底层 `insert(0)`，后装的在外层。`jwt_auth.py` 有 `_INSTALL_ATTR`（≈L28），认证成功在 ≈L51 写 `request.state.octop_user`，≈L48 接受 `access_token` 查询参数。
- 令牌：`api/deps.py` 的 `sign_token`（≈L28）、`maybe_sliding_renew_token`（≈L151）、`authenticate_request`（≈L176）。`require_permission` 的 `_dep`（≈L210）与 `require_admin` 的 `_dep`（≈L225）只依赖 `current_user`，拿不到 `server`。
- as_user：`api/common/agent.py::require_agent_row`（≈L39，as_user 分支 ≈L51）是 agent 类路由的统一校验点；`api/routers/usage.py::_resolve_user_scope`（≈L42）是第二份实现。
- 线程：`infra/gateway/threads.py` 的 `get_or_create`（≈L107）与 `get_or_create_by_key`（≈L165）命中 `self._sessions.get(session_key)`（≈L124/176）后直接返回 `row.thread_id`，不查 `threads` 表；`delete_thread`（≈L407）。`sessions.thread_id` 是 `TEXT NOT NULL` 且无外键（`001_initial.sql`）。`infra/db/repos/threads.py` 有 `ThreadRow`（≈L55）、`get`（≈L193）、`delete`（≈L312）。`thread_messages.py` 的 `migration_summary/migration_candidates/migration_active_thread_ids`（≈L154/175/200）自行 JOIN `threads`。
- 删除路径有四条：HTTP `api/routers/chat/history.py::delete_thread`（≈L557，先 `delete_thread_checkpoint` ≈L573 再 `delete_thread` ≈L574）；slash `infra/gateway/slash/handlers/session.py`（≈L137）；CLI `cli/support/offline_ops.py::delete_thread_offline`（≈L546）；fork 回滚 `infra/agents/thread_fork.py`（≈L263，测试断言在 `tests/unit/agents/test_thread_fork.py` ≈L256）。
- `infra/agents/manager.py::delete_thread_checkpoint`（≈L964）在 agent 未运行时返回 False（≈L989）。`thread_messages`、`thread_history_projection`、`trajectory_events` 都以 `ON DELETE CASCADE` 引用 `threads(thread_id)`（`010_*`、`012_*`）。
- 日志：`infra/server.py` 有 `_parse_log_compress/_parse_log_retention_days/_parse_log_max_bytes`（≈L106/140/150）；`_build_log_handler`（≈L160）在 ≈L179 用裸 `logging.Formatter`；`_setup_logging`（≈L545）在 `start()` 的 ≈L293 调用，早于 ≈L295 的 `self.config = config`。全仓没有 `StreamHandler`，只有 `cli/commands/acp.py` 的 `basicConfig`。
- 系统任务：`CronManager.schedule_system_job`（`infra/cron/manager.py` ≈L290）；范式是 `infra/backup/auto.py::apply_auto_backup_schedule`（≈L251），在 `server.py` ≈L449-451 经 `install_auto_backup_job` 装配。
- 错误：`infra/errors.py` 的 `ErrorCode`（≈L13）、`_DEFAULT_STATUS`（≈L115）、`to_envelope`（≈L255）。
- 附件出口共 10 个：`workspace.py` ≈L363（`download_file`）与 ≈L536（`export_workspace_archive`）；`chat/trajectory.py` ≈L393/399（`export_thread_trajectory`）；`chat/history.py` ≈L487（`export_history`，硬编码 attachment）；`memory_portable.py` ≈L179（`pack_agent_memory`）；`knowledge_bases.py` ≈L805（`download_document_file`，disposition 可选）；`backup.py` ≈L313（`download_backup_file`）与 ≈L412（`export_backup`）；`usage.py` ≈L190（`_export_response`，由 `user_export/admin_export` 调用）。`workspace.py` ≈L454 是 inline 预览。
- 查询面：`api/routers/admin.py::audit_log`（≈L48）的 `limit: int = 100`（≈L52）无上限；CLI `cli/support/offline_ops.py::admin_audit_offline`（≈L307）；前端 `dashboard/src/pages/Settings/Security/AuditLogPanel.tsx`。

## 方案

1. **上下文。** 新增纯 stdlib 模块 `infra/utils/request_context.py`，放一个 contextvar，值是可变的 `RequestAudit` 对象。最外层的 `RequestContextMiddleware` 建对象并写入 `request_id/src_ip/user_agent`，`jwt_auth` 认证成功后原地补 `actor/actor_id/session_id`。对象可变，所以不依赖 contextvar 在 `BaseHTTPMiddleware` 间回传。放在 utils 层，日志 Formatter 与 `db/repos` 都能读，不越界。
2. **中间件。** `RequestContextMiddleware` 写成纯 ASGI 类，照 `jwt_auth.py` 的 `_INSTALL_ATTR` 幂等模式，占用 `w3-01` 在栈顶预留的槽位，在 `build_app` 中最后安装。它给所有响应加 `X-Request-Id`，包括内层短路的 401。第二个 ASGI 应用 `http_companion` 只做跳转，不加。
3. **会话 ID。** `sign_token` 增加 `sid` 参数（缺省生成 ULID），滑动续期透传旧 `sid`。`w3-04` 的会话表直接以它为主键。
4. **真实操作人。** `UserManager` 各写审计的方法增加 `*, actor: str | None = None`，取值顺序是参数、上下文 `actor`、`ACTOR_SYSTEM`。路由把依赖参数从 `_` 改名为 `actor` 后透传。`create` 的 `user.create` 改为记创建者，被创建者放 `target`。
5. **覆盖面。** 审计写在路由层，因为路由层同时持有 `actor` 与 `server`。SSO 配置只在 `auth_oidc.put_oidc_config` 与 `auth_oauth.put_oauth_provider` 写，不在 `SsoService` 重复写。`oauth_unbind` 已由 manager 写 `user.sso_unbind`，不加。Codex OAuth 端点已由 `w1-05` 删除，不补。
6. **拒绝与代访问。** 新增 `api/common/audit.py`，提供 `audit_denied()` 与带进程内 TTL 节流的 `audit_impersonation()`。`require_permission/require_admin` 的 `_dep` 增加 `server: OctopServer = Depends(get_server)`。
7. **软删除。** `ThreadRepo` 的读查询加 `deleted_at IS NULL`；新增 `soft_delete/hard_delete/list_deleted_before`。`ThreadRegistry.soft_delete_thread` 同时删除指向该线程的 `sessions` 行；`get_or_create/get_or_create_by_key` 命中 session 后校验线程存在，不存在就进入创建分支。两道保险都要有。
8. **清除。** 新模块 `infra/retention/` 注册两个系统任务：线程清除先删 checkpoint，失败就延期；审计清除调用 `delete_before`。
9. **日志。** 新增 `infra/utils/log_redaction.py`，提供 `RedactingFormatter`（重写 `format()`，对最终字符串脱敏，因此覆盖 `exc_text`）与子类 `JsonLogFormatter`。`_build_log_handler` 与新增的 stdout handler 都用它。开关是环境变量 `OCTOP_LOG_FORMAT/OCTOP_LOG_STDOUT`，因为 `_setup_logging` 早于 config 加载，与既有 `OCTOP_LOG_*` 一致。PII 规则由 `p2-04` 通过 `register_redaction_pattern()` 追加，由 `server.py` 注入。
10. **外发。** `SyslogAuditSink` 实现 `AuditSink`：`emit()` 只把事件放进有界 `deque`，守护线程负责格式化与发送，失败时指数退避。
11. **下载兜底。** 在 `w1-02` 的 `CAPABILITY_CATALOG` 登记 `file_download`（默认开启，无挂载与工具）。新增 `api/common/download_guard.py::assert_download_allowed`，10 个出口在构造响应前调用。`p2-07` 之后在同一函数里加按角色的策略。

## 组件与接口

| 文件 | 类型 | 内容 |
|---|---|---|
| `src/octop/infra/utils/request_context.py` | 新增 | `RequestAudit`、`bind_request()`、`current_request()`、`current_request_id()` |
| `src/octop/api/middleware/request_context.py` | 新增 | `RequestContextMiddleware`、`install(app)` |
| `src/octop/api/app.py` | 修改 | `build_app` 末尾安装 request_context |
| `src/octop/api/middleware/jwt_auth.py` | 修改 | ≈L51 之后补上下文字段 |
| `src/octop/api/deps.py` | 修改 | `sign_token(sid=)`、续期透传、`authenticate_request` 顺带暴露 payload、两个 `_dep` 写拒绝审计 |
| `src/octop/api/common/audit.py` | 新增 | `audit_denied`、`audit_impersonation`、`audit_actor(user)` |
| `src/octop/api/common/download_guard.py` | 新增 | `assert_download_allowed` |
| `src/octop/infra/db/repos/audit.py` | 修改 | `AuditEvent`、`AuditSink`、`AuditRow` 新列、`write` 兼容封装、`query` 新过滤；删除零调用者的 `admin_event/system_event/user_event`（`admin_event` 是 `ACTOR_ADMIN` 的第 15 处引用） |
| `src/octop/infra/db/services.py` | 修改 | `AuditRepo(db, sinks=build_audit_sinks(config))` |
| `src/octop/infra/audit/syslog_sink.py` | 新增 | `SyslogAuditSink`、`format_rfc5424()`、`build_audit_sinks()` |
| `src/octop/infra/utils/log_redaction.py` | 新增 | `RedactingFormatter`、`JsonLogFormatter`、`redact()`、`register_redaction_pattern()` |
| `src/octop/infra/server.py` | 修改 | `_parse_log_format/_parse_log_stdout`、`_build_log_handler` 换 Formatter、stdout handler、装配两个清除任务与 sink 生命周期 |
| `src/octop/infra/retention/{__init__,threads,audit}.py` | 新增 | `purge_expired_threads`、`purge_expired_audit`、`install_retention_jobs` |
| `src/octop/infra/db/repos/threads.py`、`thread_messages.py` | 修改 | 软删除列、过滤、`soft_delete/hard_delete/list_deleted_before/bump_purge_attempts` |
| `src/octop/infra/gateway/threads.py` | 修改 | `soft_delete_thread`、`purge_thread`、两处存在性校验；删除 `delete_thread` |
| `api/routers/chat/history.py`、`slash/handlers/session.py`、`cli/support/offline_ops.py`、`agents/thread_fork.py` | 修改 | 四条删除路径（前三条软删除，fork 回滚走 `purge_thread`） |
| `infra/users/manager.py`、`api/routers/{users,security,backup}.py` | 修改 | 真实操作人 |
| `api/routers/{providers,voice,auth_oidc,auth_oauth,envs,backup,uploads,workspace,agent_files,knowledge_bases,memory_portable,usage}.py`、`chat/trajectory.py` | 修改 | 覆盖面、代访问、下载兜底 |
| `api/common/agent.py` | 修改 | `require_agent_row` 的 as_user 分支调用 `audit_impersonation` |
| `infra/errors.py` | 修改 | `to_envelope` 加 `request_id` |
| `api/routers/admin.py`、`cli/commands/admin.py` | 修改 | 新字段与过滤 |
| `src/octop/capability_catalog.py` | 修改 | 登记 `file_download` |
| `dashboard/src/pages/Settings/Security/AuditLogPanel.tsx`、`dashboard/src/utils/apiError.ts`、`dashboard/src/locales/intranet/{en,zh}.json` | 修改 | 面板列与筛选、解析 `request_id`、overlay 文案 |

关键签名：

```python
# infra/utils/request_context.py
@dataclass
class RequestAudit:
    request_id: str | None = None; src_ip: str | None = None; user_agent: str | None = None
    actor: str | None = None; actor_id: int | None = None; session_id: str | None = None
def bind_request(ra: RequestAudit) -> contextvars.Token[RequestAudit | None]: ...
def current_request() -> RequestAudit | None: ...

# infra/db/repos/audit.py
RESULT_SUCCESS, RESULT_FAILURE, RESULT_DENIED = "success", "failure", "denied"
@dataclass(frozen=True)
class AuditEvent:  # 冻结字段集，p2-03 在其上计算哈希
    ts: int; actor: str; action: str; target: str | None; payload: dict[str, Any] | None
    actor_id: int | None; actor_kind: str; on_behalf_of: str | None; src_ip: str | None
    user_agent: str | None; session_id: str | None; request_id: str | None
    result: str | None; error_code: str | None
class AuditSink(Protocol):
    def emit(self, event: AuditEvent) -> None: ...
class AuditRepo:
    def __init__(self, db: DatabasePool, *, sinks: Sequence[AuditSink] = ()) -> None: ...
    def write(self, *, actor: str | None = None, action: str, target: str | None = None,
              payload: Any = None, result: str | None = None, error_code: str | None = None,
              on_behalf_of: str | None = None, actor_id: int | None = None) -> None: ...

# api/common/download_guard.py
def assert_download_allowed(server: OctopServer, user: User, *, action: str, target: str) -> None: ...

# infra/retention/threads.py
async def purge_expired_threads(server: OctopServer, *, now: int | None = None) -> PurgeReport: ...
```

`result` 缺省时，`auth.*` 由调用方显式传入，其余写入点默认记 `success`。

## 数据模型

fork 迁移 `forkNNN_audit_baseline.sql` 与 `forkNNN_audit_baseline.pg.sql`，由 `w0-01` 的 `run_fork_migrations` 执行，不改 `_schema_version`。

- `audit_log` 新增九列：`actor_id INTEGER`、`actor_kind TEXT`、`on_behalf_of TEXT`、`src_ip TEXT`、`user_agent TEXT`、`session_id TEXT`、`request_id TEXT`、`result TEXT`、`error_code TEXT`。
- 新增索引：`idx_audit_request_id`、`idx_audit_result`、`idx_audit_actor_id`。
- 回填：`actor='_system'` 的行 `actor_kind='system'`，`actor='_admin'` 的行 `actor_kind='legacy_admin'`，其余 `user`。历史行的 `result` 保持 NULL，界面显示为"—"。
- `threads` 新增三列：`deleted_at INTEGER`、`deleted_by INTEGER`、`purge_attempts INTEGER NOT NULL DEFAULT 0`，以及索引 `idx_threads_deleted(deleted_at)`。
- 不新增哈希链列，由 `p2-03` 自己的 fork 迁移追加。

## 配置

`src/octop/config.py` 新增 `AuditConfig`（frozen dataclass，照 `BackupConfig` ≈L92），挂到 `OctopConfig.audit`，由 `_parse_audit_section`（照 `_parse_backup_section` ≈L212）解析。

| 键 | 默认 | 环境变量 |
|---|---|---|
| `retention_days` | 0（不清除；非 0 时必须 ≥180） | `OCTOP_AUDIT_RETENTION_DAYS` |
| `thread_retention_days` | 90 | `OCTOP_THREAD_RETENTION_DAYS` |
| `purge_schedule` | 与 `BackupConfig` 调度字段同格式，每日 03:30 | `OCTOP_AUDIT_PURGE_SCHEDULE` |
| `thread_purge_max_attempts` | 30 | `OCTOP_THREAD_PURGE_MAX_ATTEMPTS` |
| `impersonate_throttle_seconds` | 300 | `OCTOP_AUDIT_IMPERSONATE_THROTTLE_SECONDS` |
| `syslog_enabled` / `syslog_host` / `syslog_port` / `syslog_transport` / `syslog_queue_max` | False / "" / 514 / "tcp" / 10000 | `OCTOP_AUDIT_SYSLOG_{ENABLED,HOST,PORT,TRANSPORT,QUEUE_MAX}` |

三触点：(1) `AuditConfig` 字段加上 `OctopConfig.audit: AuditConfig = field(default_factory=AuditConfig)`；(2) `load_config` 的 env 覆盖块（照 `OCTOP_BACKUP_*`，≈L536 起）；(3) `return OctopConfig(...)` 逐字段构造中传 `audit=audit`。`w1-02` 的三触点单测会覆盖第三处。

只走环境变量、不进 `config.py` 的键：`OCTOP_LOG_FORMAT`（`text|json`，默认 `text`）、`OCTOP_LOG_STDOUT`（默认 `0`）。能力开关：`capabilities.file_download.enabled`（默认 true），由 `w1-02` 的框架解析。

## 错误处理

- 不新增 `ErrorCode`，因此 `_DEFAULT_STATUS` 与四份 i18n JSON 都不动。
- 下载被拒复用 `FORBIDDEN`，`details={"reason": "download_disabled"}`。
- `to_envelope` 在 `error` 对象里增加 `request_id`，取自 `current_request_id()`，没有值时省略该键。
- `jwt_auth` 短路的 401 JSON 也补 `request_id`。
- sink 异常、syslog 发送失败、清除任务单条失败都只记日志，不向上抛。

## 安全考虑

- payload 白名单：密钥类字段只记 `*_changed`；环境变量只记键名；文件只记路径、大小、类型。
- `src_ip` 只取 `w3-01` 的 `client_ip()`，它只信任 `trusted_proxies`，因此审计里不会落入伪造的 `X-Forwarded-For`。
- 入站 `X-Request-Id` 做字符集与长度校验，防止日志注入。
- 脱敏在 Formatter 层对最终字符串统一处理，覆盖 uvicorn access 行与 traceback。如果 uvicorn 自带的 console handler 仍向 stdout 输出，`_setup_logging` 在 `OCTOP_LOG_STDOUT=1` 时清除它们，统一由本 spec 的 handler 输出。
- syslog 是单向外发，不接收任何入站数据。TLS 使用进程级 CA（`w2-04`）。
- 审计写入是同步 SQLite 写，与既有做法一致。高频点（代访问、拒绝）靠节流控制写量。

## 测试策略

- 单测（新增）：`tests/unit/db/test_audit_fields.py`、`tests/unit/api/test_request_context.py`、`tests/unit/infra/test_log_redaction.py`、`tests/unit/audit/test_syslog_sink.py`、`tests/unit/retention/test_thread_purge.py`。命令：`uv run pytest tests/unit/db/test_audit_fields.py tests/unit/api/test_request_context.py tests/unit/infra/test_log_redaction.py tests/unit/audit tests/unit/retention -q`。
- 单测（修改）：`tests/unit/gateway/test_thread_registry.py`（不复活）、`tests/unit/agents/test_thread_fork.py`（≈L256 改断言 `purge_thread`）、`tests/unit/api/test_jwt_tokens.py`、`tests/unit/api/test_jwt_auth_middleware.py`、`tests/unit/api/test_exception_handlers.py`、`tests/unit/test_logging.py`、`tests/unit/api/test_middleware_stack.py`（`w3-01` 新建）。
- 集成（新增）：`tests/integration/test_audit_coverage.py`、`tests/integration/test_thread_soft_delete.py`、`tests/integration/test_download_guard.py`。修改 `tests/integration/test_trajectory_api.py` 中断言删除后事件为空的用例。命令：`uv run pytest tests/integration/test_audit_coverage.py tests/integration/test_thread_soft_delete.py tests/integration/test_download_guard.py tests/integration/test_trajectory_api.py -q`。
- PG：`make test-postgresql`（`w0-02`），覆盖 fork 迁移与软删除查询。
- 前端：`cd dashboard && npx tsc -b && npm run lint && npm run test`。
- 跨平台：syslog 测试只用 `127.0.0.1` 临时端口；日志测试 `monkeypatch.setenv("OCTOP_HOME", str(tmp_path))`，用 `Path` 断言。

## 与其他 spec 的交接

- **依赖：** `w0-01`（`run_fork_migrations`）；`w0-02`（`make test-postgresql`、前端 job）；`w0-03`（管理员显式权限键。bootstrap 会多写一条 `user.set_permissions`，新用例按 action 过滤）；`w0-04`（i18n overlay、`CHANGELOG-intranet.md`、`docs/api-intranet.md`）；`w1-02`（`capability_enabled`、`CAPABILITY_CATALOG`）；`w1-05`（Codex OAuth 已删、`SsoKind` 已收窄）；`w3-01`（`client_ip()`、中间件栈预留槽与 `test_middleware_stack.py`）。
- **交付：**
  - `p2-03`：冻结的 `AuditEvent` 与 `AuditSink`，哈希链与持久化外发队列在其上实现。
  - `w3-03`：`audit_denied()`。收口权限判定时保留这个调用，审计员角色的查询沿用 `admin.py` 接口。
  - `w3-04`：JWT `sid`。
  - `p2-04`：`register_redaction_pattern()`。
  - `p2-07`：`assert_download_allowed()` 挂载点。
  - `w4-01`：信封中的 `request_id` 与 `apiError.ts` 的 `requestId` 字段。
  - `w4-02`：`OCTOP_LOG_STDOUT/OCTOP_LOG_FORMAT`，以及保留期与 syslog 配置的运维说明。
  - 前序 spec 新增的 `connector.custom_mcp.patch/probe`（`w1-01`）与 `tls.certificate.upload`（`w1-03`）自动获得新字段，无需改动。
- **看似相关但不归本 spec：** 能力闸门与强制禁用处的埋点由 `w1-02` 在 `require_capability` 层按本字段集补；前端 14 处 `a.download` 收敛与按角色策略归 `p2-07`；`GET /api/providers` 明文返回 `api_key` 的问题归 `w1-01` 与 `w3-05` 的响应体脱敏契约。

## 风险与回滚

| 风险 | 缓解 | 回滚 |
|---|---|---|
| 软删除后对话经 `sessions` 复活 | 解绑 sessions 加存在性校验双保险，registry 单测锁死 | 回退任务 9 的提交；`deleted_at` 列保留无害 |
| 凌晨清除时 agent 未运行，checkpoint 残留 | 延期重试加计数告警，不删库行 | 把 `thread_retention_days` 设为极大值即停用 |
| 审计写量上升（`env.read`、拒绝、代访问） | 节流；拒绝审计只在 `_dep` 中写一次 | 调大节流窗口 |
| 中间件顺序装错，401 不带 request_id | `test_middleware_stack.py` 加 401 头断言 | 回退任务 3 |
| stdout handler 改变容器日志形态 | 默认关闭，由 `w4-02` 清单打开 | 不设环境变量 |
| 保留期抬高磁盘占用 | CHANGELOG 写容量提示 | 调小保留天数 |

## 待行方确认

- D5：一期是单活部署，进程内节流与 syslog 内存队列不跨副本，丢失上限等于队列长度。二期 `p2-08` 以后再评估是否持久化。
- 另需行方给出（不在 D 表中）：线程保留天数（默认 90）、审计保留天数（默认不清除，等保要求至少 180）、syslog 目标与传输方式、IM 用户删除后"下一条消息开新对话"的表述。
