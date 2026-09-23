# 实施计划：审计与日志基线
> spec：`w3-02-audit-baseline` ｜ 波次：Wave 3 ｜ 基线：`757fd12` ｜ 预估：34 人日
> 前置：`w0-01-fork-migration-namespace`、`w0-02-ci-gates`、`w0-03-test-auth-baseline`、`w0-04-fork-isolation-points`、`w1-02-capability-trim`、`w1-05-saas-decoupling`、`w3-01-web-security-baseline` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

每个顶层任务完成后可独立提交；提交前运行任务内的验证命令。

- [ ] 1. 确认前置 spec 已合入并记录基线
  - 改动：无代码改动。确认 `run_fork_migrations`、`src/octop/i18n/intranet/`、`capability_enabled`、`src/octop/api/common/client_ip.py`、`tests/unit/api/test_middleware_stack.py` 都已存在，并记录 `rg -n 'ACTOR_ADMIN' src/octop | wc -l`（基线 16）与审计写入点数（41）。
  - 验证：`ls src/octop/api/common/client_ip.py tests/unit/api/test_middleware_stack.py src/octop/i18n/intranet && make all`
  - _需求：1.5, 2.6_

- [ ] 2. 审计字段集与写入接口
  - [ ] 2.1 先写 `tests/unit/db/test_audit_fields.py`：新列往返、旧 kwargs 兼容、上下文补齐、sink 投递与异常隔离、无上下文默认值。
  - [ ] 2.2 新增 `forkNNN_audit_baseline.sql` 与 `.pg.sql`，内容为 `audit_log` 九列、三个索引、`actor_kind` 回填，以及 `threads` 三列与索引。
  - [ ] 2.3 新增 `src/octop/infra/utils/request_context.py`。改 `src/octop/infra/db/repos/audit.py`：加入 `AuditEvent`、`AuditSink`、`AuditRow` 新列、`write` 补齐、`query` 新过滤，删除 `admin_event/system_event/user_event`。改 `src/octop/infra/db/services.py`：给 `AuditRepo(db, sinks=...)` 传 sinks（本任务先传空元组）。
  - 验证：`uv run pytest tests/unit/db/test_audit_fields.py tests/unit/db/test_repo_secret_audit.py tests/unit/db -q && ls src/octop/infra/db/migrations | grep -c '^016_'`（输出 0）
  - _需求：1.1, 1.2, 1.3, 1.4, 1.5_

- [ ] 3. request_id 中间件与错误信封
  - 改动：先写 `tests/unit/api/test_request_context.py`，覆盖入站透传、非法重生成、401 带头、并发不串、信封含 id。新增 `src/octop/api/middleware/request_context.py`（纯 ASGI，`_INSTALL_ATTR` 幂等），在 `src/octop/api/app.py` 的 `build_app` 中最后安装。修改 `src/octop/infra/errors.py::to_envelope`、`jwt_auth.py` 短路 401 的 JSON，以及 `tests/unit/api/test_middleware_stack.py` 的预留槽断言。
  - 验证：`uv run pytest tests/unit/api/test_request_context.py tests/unit/api/test_middleware_stack.py tests/unit/api/test_exception_handlers.py tests/unit/api/test_jwt_auth_middleware.py -q`
  - _需求：2.1, 2.2, 2.3, 2.5, 2.6_

- [ ] 4. 会话 ID 与认证上下文
  - 改动：`src/octop/api/deps.py` 的 `sign_token` 加 `sid`，`maybe_sliding_renew_token` 透传，`authenticate_request` 暴露 payload；`jwt_auth.py` 在 ≈L51 之后补 `actor/actor_id/session_id`；`api/routers/auth.py` 的 login 传 `sid`，登录成功与失败写 `result`。先在 `test_jwt_tokens.py`、`test_jwt_auth_middleware.py` 加断言。
  - 验证：`uv run pytest tests/unit/api/test_jwt_tokens.py tests/unit/api/test_jwt_auth_middleware.py tests/integration/test_auth_api.py -q`（若集成文件名不同，用 `rg -l 'auth/login' tests/integration` 定位）
  - _需求：2.4, 3.3, 3.4_

- [ ] 5. 替换 ACTOR_ADMIN 的 14 处使用点
  - 改动：`src/octop/infra/users/manager.py` 的 10 处加 `actor=` 参数，`create` 改为记创建者；`src/octop/api/routers/users.py` 的 `create_user/patch_user/unlock_user_login/reset_password/delete_user` 透传 actor；`api/routers/security.py`（≈L73/165/183）与 `api/routers/backup.py`（≈L353）改用真实用户名，并删除两处 import。先写 set_role 审计定责集成用例。
  - 验证：`test "$(rg -n 'ACTOR_ADMIN' src/octop | wc -l)" = 1 && uv run pytest tests/integration/test_audit_coverage.py -k actor -q`
  - _需求：3.1, 3.2_

- [ ] 6. 权限拒绝与代访问审计
  - 改动：新增 `src/octop/api/common/audit.py`；`deps.py` 的 `require_permission/require_admin` 的 `_dep` 加 `get_server` 依赖，调用 `audit_denied`；`api/common/agent.py::require_agent_row` 与 `api/routers/usage.py::_resolve_user_scope` 调用 `audit_impersonation`（节流）。
  - 验证：`uv run pytest tests/integration/test_audit_coverage.py -k "denied or impersonate" tests/integration/test_personas_admin_api.py -q`
  - _需求：3.5, 4.3_

- [ ] 7. 覆盖面 A：密钥与配置面
  - 改动：`providers.py` 的 `admin_create_provider/admin_patch_provider/admin_delete_provider`；`voice.py` 的 `admin_create/patch/delete_voice_provider`；`auth_oidc.py::put_oidc_config`；`auth_oauth.py::put_oauth_provider`；`envs.py` 的 `list_envs/batch_save_envs/delete_env`。payload 只记字段名与 `*_changed`。
  - 验证：`uv run pytest tests/integration/test_audit_coverage.py -k "provider or voice or sso or env" -q`
  - _需求：4.1, 4.2, 4.4_

- [ ] 8. 覆盖面 B：备份、文件、知识库、记忆
  - 改动：`backup.py` 除 restore 外的 7 个写或导出端点；`uploads.py::upload_attachment`；`workspace.py` 的 `write_file/delete_workspace_file/upload_file`；`agent_files.py` 的 `read_daily_memory/delete_daily_memory`；`knowledge_bases.py` 的 `upload_document/delete_document/delete_base/reindex_document/reindex_base`；`memory_portable.py::adopt_agent_memory`。
  - 验证：`uv run pytest tests/integration/test_audit_coverage.py -k "backup or file or knowledge or memory" -q`
  - _需求：4.1, 4.2_

- [ ] 9. 线程软删除
  - [ ] 9.1 先写会失败的测试：`tests/unit/gateway/test_thread_registry.py` 验证软删除后同一 key 返回新 id；`tests/integration/test_thread_soft_delete.py` 覆盖可见性、数据保留、三个 migration 查询、三条删除路径一致；改 `tests/unit/agents/test_thread_fork.py`（≈L256）与 `tests/integration/test_trajectory_api.py` 中断言事件清空的用例。
  - [ ] 9.2 改 `src/octop/infra/db/repos/threads.py` 与 `thread_messages.py`；在 `src/octop/infra/gateway/threads.py` 新增 `soft_delete_thread`（解绑 sessions）与 `purge_thread`，在 `get_or_create/get_or_create_by_key` 加存在性校验，删除 `delete_thread`。
  - [ ] 9.3 改删除路径：`chat/history.py::delete_thread`、`slash/handlers/session.py`、`offline_ops.delete_thread_offline` 改为软删除并写审计；`thread_fork.py` 回滚改调 `purge_thread`。
  - 验证：`uv run pytest tests/unit/gateway/test_thread_registry.py tests/unit/agents/test_thread_fork.py tests/integration/test_thread_soft_delete.py tests/integration/test_trajectory_api.py -q`
  - _需求：4.1, 5.1, 5.2, 5.3, 5.4, 5.5_

- [ ] 10. AuditConfig 与保留期清除任务
  - 改动：`src/octop/config.py` 新增 `AuditConfig`，三触点（dataclass 字段与 `OctopConfig.audit`、env 覆盖块、`return OctopConfig(...)` 传参），加 `retention_days` 的 180 校验。新增 `src/octop/infra/retention/`，包含 `purge_expired_threads`（先删 checkpoint，失败则延期并累加 `purge_attempts`）、`purge_expired_audit`、`install_retention_jobs`；在 `server.py` 的 `install_auto_backup_job` 旁装配。`offline_ops` 增加 `purge_threads_offline`（只清已无 checkpoint 句柄的行，并提示运维）。先写 `tests/unit/retention/test_thread_purge.py`，mock `delete_thread_checkpoint` 分别返回 True 和 False。
  - 验证：`uv run pytest tests/unit/retention tests/unit/test_config.py -q`（配置测试文件名以 `rg -l 'def test_.*backup' tests/unit` 定位）
  - _需求：6.1, 6.2, 6.3, 6.4_

- [ ] 11. 日志脱敏 Formatter 与 stdout
  - 改动：先写 `tests/unit/infra/test_log_redaction.py`，覆盖 msg、args、traceback 三处、JSON 结构，以及无上下文的第三方 handler 不抛异常。新增 `src/octop/infra/utils/log_redaction.py`；`src/octop/infra/server.py` 新增 `_parse_log_format/_parse_log_stdout`，`_build_log_handler`（≈L179）换用 `RedactingFormatter/JsonLogFormatter`，`_setup_logging` 按开关挂 stdout handler 并接管 uvicorn console handler。在 `tests/unit/test_logging.py` 补文本格式带 `[request_id]` 的用例。
  - 验证：`uv run pytest tests/unit/infra/test_log_redaction.py tests/unit/test_logging.py -q`
  - _需求：2.4, 7.1, 7.2, 7.3, 7.4_

- [ ] 12. syslog 单向外发
  - 改动：新增 `src/octop/infra/audit/syslog_sink.py`（有界 deque、守护线程、退避、RFC5424、tcp/udp/tls），把 `build_audit_sinks` 接入 `services.py`；在 `server.py` 的 start/stop 中管理线程生命周期。先写 `tests/unit/audit/test_syslog_sink.py`，覆盖不可达目标下 200 次写入小于 1 秒、队列溢出、本地监听收到的格式。
  - 验证：`uv run pytest tests/unit/audit -q`
  - _需求：8.1, 8.2, 8.3, 8.4_

- [ ] 13. 下载出口兜底与留痕
  - 改动：在 `src/octop/capability_catalog.py` 登记 `file_download`；新增 `src/octop/api/common/download_guard.py`；10 个出口在构造响应前调用它，覆盖 `workspace.download_file/export_workspace_archive`、`chat/trajectory.export_thread_trajectory`（两处）、`chat/history.export_history`、`memory_portable.pack_agent_memory`、`knowledge_bases.download_document_file`（仅 attachment）、`backup.download_backup_file/export_backup`、`usage._export_response`。先写参数化的 `tests/integration/test_download_guard.py`，含 inline 预览放行用例。
  - 验证：`uv run pytest tests/integration/test_download_guard.py -q`
  - _需求：4.1, 9.1, 9.2, 9.3_

- [ ] 14. 审计查询 API 与 CLI
  - 改动：`api/routers/admin.py::audit_log` 加 `response_model`、新过滤项和 `limit` 上限 `le=1000`；`cli/support/offline_ops.py::admin_audit_offline` 与 `cli/commands/admin.py` 加 `--result/--since` 与新列。
  - 验证：`uv run pytest tests/integration/test_audit_coverage.py -k query tests/integration/test_personas_admin_api.py tests/unit/cli -q`
  - _需求：10.1, 10.2_

- [ ] 15. 前端审计面板
  - 改动：`dashboard/src/pages/Settings/Security/AuditLogPanel.tsx` 加 `AuditRow` 新字段、来源 IP、结果、代访问列与结果筛选，并在 `ACTION_OPTIONS` 补齐缺失项和本期新增 action；`dashboard/src/utils/apiError.ts` 解析 `request_id`；文案只写 `dashboard/src/locales/intranet/{en,zh}.json`，不动上游 locale。
  - 验证：`cd dashboard && npx tsc -b && npm run lint && npm run test`
  - _需求：10.3_

- [ ] 16. 收尾
  - 改动：`make all` 全绿；更新 `CHANGELOG-intranet.md`（写明软删除语义、保留期与容量提示、新环境变量）；在 `docs/api-intranet.md` 记录 `X-Request-Id`、信封 `request_id`、audit-log 新字段与过滤、下载 403；跑一次 `make test-postgresql`。
  - 验证：`make all && cd dashboard && npx tsc -b && npm run lint && npm run test && cd .. && make test-postgresql && uv run pytest tests/unit/i18n -q`
  - _需求：1.1, 2.1, 10.1_
