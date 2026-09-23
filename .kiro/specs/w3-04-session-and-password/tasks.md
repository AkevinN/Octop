# 实施计划：会话与口令
> spec：`w3-04-session-and-password` ｜ 波次：Wave 3 ｜ 基线：`757fd12` ｜ 预估：33 人日
> 前置：w0-01-fork-migration-namespace, w0-02-ci-gates, w0-03-test-auth-baseline, w0-04-fork-isolation-points, w1-01-security-hotfix, w1-02-capability-trim, w1-04-content-trim, w2-01-offline-build, w3-01-web-security-baseline, w3-02-audit-baseline, w3-03-authorization-foundation ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

每个顶层任务完成后可独立提交；提交前运行任务内的验证命令。

- [ ] 1. 确认前置 spec 已合入并记录基线
  - 改动：核对 `src/octop/infra/db/fork_migrate.py::run_fork_migrations`、`src/octop/infra/setup/completion.py::is_setup_completed`、`api/deps.py::sign_token` 的 `sid` 形参、`api/middleware/stack.py`、`src/octop/i18n/intranet/` 均存在；`rg -n '@router.websocket' src/octop/api` 只剩 `chat/ws.py`、`chat/notify_ws.py`；`fnos/` 不存在。结果记入 PR 描述。
  - 验证：`uv run pytest -m "not live" -q`
  - _需求：6.1, 10.2_

- [ ] 2. 错误码与 overlay 文案
  - 改动：`src/octop/infra/errors.py` 的 `ErrorCode` 末尾与 `_DEFAULT_STATUS` 末尾追加 `LOGIN_MODE_DISABLED`(403)、`SESSION_REVOKED`(401)、`PASSWORD_CHANGE_REQUIRED`(403)、`PASSWORD_REUSED`(400)；后端 `src/octop/i18n/intranet/{en,zh}.json` 与前端 `dashboard/src/locales/intranet/{en,zh}.json` 补 `errors`/`apiErrors`，前端另加 `login.oidcError.not_admitted`、强制改密页文案。不删上游键。
  - 验证：`uv run pytest tests/unit/i18n tests/unit/test_errors.py -q`
  - _需求：10.1, 10.2_

- [ ] 3. 配置键三触点
  - 改动：`src/octop/config.py` 为设计文档"配置"表的 11 个键各改 `OctopConfig` 字段、env 覆盖块、`return OctopConfig(...)` 构造；`access_token_ttl_seconds` 默认改 900。先在 `tests/unit/test_config.py` 写"env 覆盖后构造值生效"用例。
  - 验证：`uv run pytest tests/unit/test_config.py -q`
  - _需求：2.4, 4.1, 4.2, 4.3, 7.1_

- [ ] 4. fork 迁移与两个 repo
  - 改动：新增 `src/octop/infra/db/migrations/forkNNN_auth_sessions_and_password_policy.sql` 与 `.pg.sql`（建 `auth_sessions`、`user_password_history`，`users`、`sso_providers` 加列并回填）；新增 `infra/db/repos/auth_sessions.py`、`infra/db/repos/password_history.py`；`infra/db/services.py` 为两者各改 `RepoBundle` 字段、构造、`SharedServices` property 三处；`repos/users.py` 读写新列。先写 `tests/unit/db/test_repo_auth_sessions.py`。
  - 验证：`uv run pytest tests/unit/db -q`
  - _需求：2.1, 7.3, 7.5_

- [ ] 5. SessionManager 与鉴权链
  - [ ] 5.1 新增 `src/octop/infra/users/sessions.py::SessionManager`（`create`/`validate`/`touch`/`revoke*`/`list_active`，可注入时钟），`infra/server.py` 构造并挂到 server；先写 `tests/unit/users/test_sessions.py`。
    - 验证：`uv run pytest tests/unit/users/test_sessions.py -q`
    - _需求：2.3, 4.1, 4.2, 4.3, 4.4_
  - [ ] 5.2 `api/deps.py`：`sign_token` 去默认 TTL；`resolve_user_from_token` 调 `validate`；`maybe_sliding_renew_token` 透传 `sid` 且过绝对时限不续签；`_decode` 读密钥加进程内缓存。`tests/unit/api/test_jwt_tokens.py` 同步调用签名。
    - 验证：`uv run pytest tests/unit/api/test_jwt_tokens.py tests/unit/api/test_jwt_auth_middleware.py -q`
    - _需求：2.2, 2.3, 4.2_
  - [ ] 5.3 四个签发点建会话：`auth.py::login`、`invites.py` 的 redeem、`setup.py` 的 initial-admin、`auth_oidc.py::exchange_login_code_response`；`repos/sso.py::consume_login_code`/`attach_login_code` 与 `service.py::exchange_login_code` 带出 provider_id 与 subject。
    - 验证：`uv run pytest tests/integration/test_auth_flow.py tests/integration/test_auth_oauth.py -q`
    - _需求：2.1, 2.5_

- [ ] 6. 吊销联动
  - 改动：先写 `tests/integration/test_session_revocation.py`（登出、改密、重置、停用、两条 provider 路由关闭 OIDC）；再改 `auth.py::logout`（更新 docstring）、`manager.py::change_password`/`reset_password`/`disable`、`service.py::put_config_for_kind`；吊销写审计 `auth.session_revoke`。
  - 验证：`uv run pytest tests/integration/test_session_revocation.py -q`
  - _需求：3.1, 3.2, 3.3, 3.4, 5.4_

- [ ] 7. 会话管理 API
  - 改动：`auth.py` 新增 `GET /sessions`、`DELETE /sessions/{session_id}`；`users.py` 新增 `GET /{user_id}/sessions`、`POST /{user_id}/sessions/revoke`，沿用该文件的用户管理判定；Pydantic 响应模型与 summary 齐全。先写集成用例（含他人会话 404、无权限 403）。
  - 验证：`uv run pytest tests/integration/test_session_revocation.py tests/unit/api/test_acl_gate_coverage.py -q`
  - _需求：5.1, 5.2, 5.3_

- [ ] 8. 登录模式后端
  - 改动：新增 `src/octop/infra/auth/login_mode.py`；`auth.py::login`、`invites.py` redeem、`auth_oidc.py` `/oidc/start`、`auth_oauth.py` `/oauth/start` 调判定；`service.py::status`、`providers_status` 按模式返回 `enabled` 与 `login_mode`。先写 `tests/integration/test_login_mode.py`（三态 × 四入口）。
  - 验证：`uv run pytest tests/integration/test_login_mode.py -q`
  - _需求：1.1, 1.2, 1.4_

- [ ] 9. 登录模式前端与自动跳转
  - 改动：`dashboard/src/api/modules/sso.ts` 增 `login_mode` 类型；`pages/Login/index.tsx` 在 `sso_only` 且无 `oidc_error` 时自动发起 OIDC start，并隐藏本地表单；先写 vitest 用例。
  - 验证：`cd dashboard && npx tsc -b && npm run test -- Login`
  - _需求：1.3_

- [ ] 10. WS 首帧握手（后端）
  - 改动：新增 `src/octop/api/common/ws_auth.py`；`chat/ws.py`、`chat/notify_ws.py` 删 `token` Query，改用 `accept_and_authenticate` 与 `ws_session_guard`；`tests/support/http.py` 删 `ws_token`、`chat_ws_path` 去 query，新增首帧辅助；改 `test_chat_ws.py`、`test_notifications_ws.py`，新增 `tests/unit/api/test_ws_auth.py`（无首帧超时 4001、带 `?token=` 仍超时、吊销后 4001）。
  - 验证：`uv run pytest tests/unit/api/test_ws_auth.py tests/integration/test_chat_ws.py tests/integration/test_notifications_ws.py -q`
  - _需求：6.1, 6.2, 6.3_

- [ ] 11. WS 前端与去掉 query 令牌
  - 改动：`dashboard/src/api/modules/wsChat.ts`、`wsNotifications.ts` 改为 onopen 发 `{"type":"auth"}`，等 `auth_ok` 再发业务帧；`api/deps.py::extract_raw_token`/`authenticate_request`/`current_user` 与 `jwt_auth.py` 删 query 读取。
  - 验证：`rg -n 'query_params.get\("access_token"\)|access_token: str \| None = Query|token: str \| None = Query' src/octop/api; rg -n 'params\.set\(\s*"token"|URLSearchParams\(\{\s*token|search\.set\("access_token"' dashboard/src --glob '!*.test.*'; cd dashboard && npx tsc -b`（两条 rg 均无输出）
  - _需求：6.4_

- [ ] 12. trajectory SSE 改 fetch 流
  - 改动：先重写 `dashboard/src/pages/Chat/hooks/useTrajectorySession.test.ts`（mock `fetch` 流，覆盖续传与隐藏关闭）；再把 `api/modules/trajectory.ts::streamUrl` 换成 `openStream`，`useTrajectorySession.ts` 改用 `AbortController`。
  - 验证：`cd dashboard && npm run test -- useTrajectorySession && npx tsc -b`
  - _需求：6.5_

- [ ] 13. 口令策略后端
  - 改动：`infra/users/password.py` 增 `PasswordPolicy`、`set_password_policy()`（`server.py` 与 `cli/support/db.py::open_cli_services` 注入）；`manager.py` 的 `create`/`create_from_invite`/`change_password`/`reset_password`/`authenticate` 处理历史、有效期、`must_change_password`（SSO 开户路径不置位）；`auth.py` 增 `GET /password-policy`，`me_payload` 加字段；`jwt_auth.py` 做强制改密白名单拦截。`tests/unit/test_password.py` 与 `tests/support/auth.py::TEST_PASSWORD` 加长到 12 位以上。先写 `tests/integration/test_password_policy.py`。
  - 验证：`uv run pytest tests/unit/test_password.py tests/unit/test_user_manager.py tests/integration/test_password_policy.py -q`
  - _需求：7.1, 7.2, 7.3, 7.4, 7.5_

- [ ] 14. 口令策略前端
  - 改动：`dashboard/src/utils/passwordPolicy.ts` 改为接收策略参数，`api/modules/auth.ts` 增 `passwordPolicy()`；三个消费方改用接口值；新增 `pages/ChangePassword/index.tsx` 与路由；`components/AuthGuard.tsx` 在已有 `authApi.me()` 响应上判定跳转。先写 vitest 用例。
  - 验证：`cd dashboard && npx tsc -b && npm run test -- passwordPolicy`
  - _需求：7.1, 7.2_

- [ ] 15. 删除明文凭据链路
  - 改动：删除 `src/octop/infra/setup/password_file.py` 与 `tests/unit/test_wizard_password.py`；`infra/server.py` 删导入与 `_emit_wizard_password`；`setup.py::verify_password` 改比对 `config.setup_password`（`hmac.compare_digest`），`/setup/status` 删 `wizard_password_path`；`tests/support/auth.py::wizard_token` 与 `test_setup_bootstrap.py`、`test_setup_database.py`、`test_setup_wizard.py`、`test_postgresql_control_plane.py` 改为经 `OCTOP_SETUP_PASSWORD` 注入；`dashboard/src/pages/Setup/steps/PasswordStep.tsx` 删文件位置引导块。
  - 验证：`uv run pytest tests/integration/test_setup_wizard.py tests/integration/test_setup_bootstrap.py tests/integration/test_setup_database.py -q && cd dashboard && npx tsc -b`
  - _需求：8.1, 8.2, 8.3_

- [ ] 16. 入口脚本与部署文档
  - 改动：`docker/docker-entrypoint.sh` 删 `CREDENTIAL_FILE`、`octop_random_password` 与退出码 4 的重试，缺口令或策略拒绝即退出；更新 `w2-01` 的 `tests/unit/test_docker_entrypoint.py` 期望；`docker/docker-compose.yml`、`docker/README.md`、`docker/README_CN.md`、`docs/user-guide.md`、`README.md`、`README_CN.md` 删凭据文件描述。
  - 验证：`uv run pytest tests/unit/test_docker_entrypoint.py -q && rg -n 'octop-login.txt|credential.txt|password_file' src tests docker dashboard/src docs README.md README_CN.md`（rg 无输出）
  - _需求：8.1, 8.4_

- [ ] 17. OIDC issuer 与算法加固
  - 改动：`infra/auth/sso/public_base.py` 新增 `validate_issuer`；`service.py::put_config_for_kind` 对 oidc 校验 issuer 与 `dashboard_origin`；`id_token.py` 新增 `set_allowed_algorithms()` 并剔除 `HS*`/`none`，由 `server.py` 注入。补 `tests/unit/auth/test_sso_id_token.py`、`test_sso_service.py` 与 `tests/integration/test_auth_oauth.py` 两条路由的用例。
  - 验证：`uv run pytest tests/unit/auth tests/integration/test_auth_oauth.py -q`
  - _需求：9.1, 9.2, 9.5_

- [ ] 18. OIDC 准入与组到角色映射
  - 改动：`auth_oidc.py::OidcConfigBody`、`auth_oauth.py::OauthProviderPutBody` 扩 `allowed_groups`/`group_claim`/`group_role_map`/`auto_provision`；`repos/sso.py` 读写新列，`upsert_provider` 不重置新列；`service.py::handle_callback` 开户前判定准入并调 `w3-03` 角色赋值；前端 OIDC 配置表单加四字段。先写 `tests/unit/auth/test_sso_admission.py`。
  - 验证：`uv run pytest tests/unit/auth/test_sso_admission.py tests/unit/db/test_repo_sso.py -q && cd dashboard && npx tsc -b`
  - _需求：9.3, 9.4_

- [ ] 19. 收尾
  - 改动：`CHANGELOG-intranet.md` 记录令牌 TTL 900、升级需重登、WS 握手协议、入口脚本必填口令；`docs/api-intranet.md` 记录会话 API、`/password-policy`、`login_mode` 字段、WS 首帧格式；清理本 spec 引入的孤儿符号。
  - 验证：`make all && cd dashboard && npx tsc -b && npm run lint && npm run test`
  - _需求：10.2, 10.3_
