# 设计文档：会话与口令
> spec：`w3-04-session-and-password` ｜ 波次：Wave 3 ｜ 基线：`757fd12` ｜ 预估：33 人日
> 前置：w0-01-fork-migration-namespace, w0-02-ci-gates, w0-03-test-auth-baseline, w0-04-fork-isolation-points, w1-01-security-hotfix, w1-02-capability-trim, w1-04-content-trim, w2-01-offline-build, w3-01-web-security-baseline, w3-02-audit-baseline, w3-03-authorization-foundation ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 概述

在 `w3-02` 已把 `sid` 写进 JWT 的基础上，新增服务端会话表 `auth_sessions`，由 `infra/users/sessions.py::SessionManager` 负责创建、校验、吊销与超时；`api/deps.py` 每次鉴权都查会话。令牌 TTL 默认降到 900 秒，滑动续签只在会话有效且未达绝对时限时进行。两条 WS 改为首帧握手，trajectory SSE 改为 fetch 流。口令策略、登录模式、OIDC 准入都落在 `infra/`，路由只做映射。明文口令文件整体删除，向导口令改由注入的环境变量提供。

## 现状

- `src/octop/api/deps.py`：`sign_token`（≈L28）默认 `ttl_seconds=86400`（≈L34）；`extract_raw_token`（≈L117）接受 `access_token` 形参；`authenticate_request`（≈L176）在 ≈L179 读 `request.query_params.get("access_token")`；`current_user`（≈L186）有 `access_token: str | None = Query(None)`（≈L190）；`maybe_sliding_renew_token`（≈L151）在 ≈L167 再次调用 `sign_token`，没有绝对上限；`resolve_user_from_token`（≈L142）只查内存缓存。
- `src/octop/api/middleware/jwt_auth.py` ≈L48 同样读 query `access_token`，有 `_INSTALL_ATTR` 幂等守卫（≈L28）。
- 发令牌点共 5 处：`auth.py` ≈L111、`invites.py` ≈L150、`setup.py` ≈L365、`auth_oidc.py` ≈L72、`deps.py` ≈L167。`auth.py::logout`（≈L123）docstring 明写"JWTs are stateless and not revoked server-side"。
- `config.py`：`access_token_ttl_seconds: int = 86400`（≈L129）、`require_setup_password: bool = True`（≈L137），env 块 ≈L462/L488，构造 ≈L596/L610。
- WS：`chat/ws.py` 的 `token` Query（≈L36）先鉴权后在 ≈L68 `accept()`；`chat/notify_ws.py` 同构（≈L26、≈L46）。前端 `api/modules/wsChat.ts` ≈L8 `params.set("token", token)`，`wsNotifications.ts` ≈L8 `new URLSearchParams({ token })`。
- SSE：`api/modules/trajectory.ts::streamUrl`（≈L101）把 JWT 放进 `access_token`（≈L105）；`pages/Chat/hooks/useTrajectorySession.ts` ≈L127-162 用 `EventSource`；后端 `api/routers/chat/trajectory.py` ≈L361 返回 `text/event-stream`，靠 jwt_auth 读 query 鉴权。
- 口令：`infra/users/password.py::MIN_PASSWORD_LENGTH = 8`（≈L12）、`validate_password_policy`（≈L48）；前端镜像 `dashboard/src/utils/passwordPolicy.ts` ≈L3 硬编码 8，消费方 `AvatarDropdown.tsx`、`pages/Invite/index.tsx`、`pages/Setup/steps/AdminStep.tsx`。`users` 表无 `must_change_password`、`password_changed_at`。
- `infra/users/manager.py`：`boot`（≈L103）、`create`（≈L122）、`create_from_invite`（≈L189）、SSO 自动开户 `password_hash=None`（≈L260）、`authenticate`（≈L438）、`change_password`（≈L496）、`reset_password`（≈L507）、`disable`（≈L689，≈L695 `set_disabled` 已持久化）。
- 明文凭据：`infra/setup/password_file.py`（`WIZARD_FILE_NAME = "octop-login.txt"` ≈L9、`read_password`、`boot_self_heal`）；`infra/server.py` 导入它（≈L29-30），`_emit_wizard_password`（≈L492）在 ≈L318/L332 被调用并 `print` 横幅；`setup.py::verify_password`（≈L320）在 ≈L334 读文件，`/setup/status` ≈L235-248 返回 `wizard_password_*`；`docker/docker-entrypoint.sh` 的 `CREDENTIAL_FILE`（≈L24）与 `octop_random_password`（≈L30）。测试侧 `tests/support/auth.py` ≈L10 导入 `read_password`，另有 `test_setup_bootstrap.py`、`test_setup_database.py`、`test_setup_wizard.py`、`test_postgresql_control_plane.py`、`test_wizard_password.py`。
- OIDC：`infra/auth/sso/id_token.py::_ALLOWED_ALGORITHMS = ("RS256", "ES256")`（≈L11）；`service.py::put_config_for_kind`（≈L140）只对非 oidc 调 `parse_strict_origin`（≈L171），issuer 只 strip（≈L173）；`status`（≈L56）与 `providers_status`（≈L70）是两条独立路径；`exchange_login_code`（≈L341）只返回 `User`；`repos/sso.py::consume_login_code`（≈L332）`RETURNING user_id`；`upsert_provider`（≈L131）是旧写入口。`auth_oauth.py` 的 `SsoKind`（≈L28）含 `oidc`，`OauthProviderPutBody`（≈L40）独立于 `auth_oidc.py::OidcConfigBody`（≈L36）。
- 错误码：`USER_DISABLED` 映射 403、`TOKEN_EXPIRED` 401、`OIDC_BAD_REQUEST` 400、`SETUP_PASSWORD_WRONG` 401（`_DEFAULT_STATUS` ≈L115 起）。

## 方案

1. **会话。** `SessionManager.create(user, *, sid, src_ip, user_agent, sso_provider_id=None, idp_subject=None)` 写行并执行并发上限（超限吊销最早的，原因 `superseded`）。`validate(sid, now)` 依次检查存在、未吊销、空闲、绝对时限；空闲或绝对超时时置吊销并抛 `TOKEN_EXPIRED`，其余抛 `SESSION_REVOKED`。`touch` 在内存记录上次写库时间，≥60 秒才 `UPDATE last_seen_at`。单实例（D5）下内存节流足够。
2. **鉴权链。** `resolve_user_from_token` 在解码后调 `validate`；无 `sid` 的旧令牌一律 `SESSION_REVOKED`（升级即全员重登，写进 CHANGELOG）。`maybe_sliding_renew_token` 在会话未达绝对时限时透传 `sid` 续签。`sign_token` 去掉默认 TTL，调用方显式传入。删除 `extract_raw_token` 的 `access_token` 形参与两处 query 读取。
3. **吊销挂点。** `logout` → `revoke(sid)`；`change_password` → 吊销本人除当前外全部；`reset_password`、`disable` → 吊销全部；`put_config_for_kind` 检测 enabled 由真变假 → `revoke_by_provider`。挂在 `UserManager` 与 `SsoService` 内，两条 provider 路由自动覆盖。
4. **登录模式。** `infra/auth/login_mode.py::assert_local_login_allowed(config)` 与 `sso_login_allowed(config)`；`auth.py::login`、`invites.py` 的 redeem、`/oidc/start`、`/oauth/start` 调用；`status`/`providers_status` 在 `local` 下返回 `enabled=false` 且都带 `login_mode`。前端 `Login/index.tsx` 读 `login_mode`，`sso_only` 且无 `oidc_error` 时自动发起 OIDC start。
5. **WS 握手。** 新增 `api/common/ws_auth.py::accept_and_authenticate(websocket, server) -> User`：先 `accept()`，`asyncio.wait_for(receive_json, ws_auth_timeout_seconds)`，校验 `type=="auth"` 后走 `resolve_user_from_token`，回 `auth_ok`；失败 `close(4001)`。归属校验保持原关闭码，只是移到 accept 之后。`ws_session_guard(websocket, server, sid)` 每 60 秒复核会话。前端两个构造点改为 onopen 发首帧。
6. **SSE。** 后端 trajectory 路由无需改（鉴权头由 jwt_auth 处理）。前端 `trajectoryApi.openStream(agentId, threadId, afterSeq, signal)` 用 `fetch` + `ReadableStream` 解析 `data:`/`id:` 行，`useTrajectorySession` 用 `AbortController` 管生命周期并保留"隐藏时关闭、断线按 afterSeq 续传"语义。
7. **口令策略。** `password.py` 增加 `PasswordPolicy` 数据类与 `set_password_policy()`（由 `server.py` 注入，CLI 离线路径在 `open_cli_services` 注入）；`validate_password_policy` 读当前策略。历史口令存 hash，`change_password`/`reset_password` 比对最近 N 条。登录成功后若 `password_changed_at` 过期则置 `must_change_password=1`。jwt_auth 在用户解析成功后对 `must_change_password` 做路径白名单拦截（不新增中间件）。
8. **明文凭据。** 删除 `password_file.py`、`_emit_wizard_password`；新增配置 `setup_password`（仅 env `OCTOP_SETUP_PASSWORD`，不写 config.json、不打日志），`verify_password` 用 `hmac.compare_digest`。`/setup/status` 保留 `wizard_password_required`，`wizard_password_exists` 改为"已注入"，删除 `wizard_password_path`。入口脚本删随机口令与凭据文件，未注入或策略拒绝即退出。
9. **OIDC。** `public_base.py` 新增 `validate_issuer(issuer, host_allowlist)`：只要求 https 与主机白名单，不做私网判定（不用 `ssrf_guard`）。`put_config_for_kind` 对 oidc 的 issuer 与 `dashboard_origin` 都校验。`id_token.py` 的算法集改为 `set_allowed_algorithms()` 注入，内部剔除 `HS*`/`none`。准入：`consume_login_code` 扩为 `RETURNING user_id, provider_id, subject`（`attach_login_code` 同步写 subject），`exchange_login_code` 返回 `SsoLogin(user, provider_id, subject)`；`handle_callback` 在开户前按 `group_claim` 与 `allowed_groups` 判定，`group_role_map` 调 `w3-03` 的角色赋值接口。

## 组件与接口

| 文件 | 类型 | 要点 |
|---|---|---|
| `src/octop/infra/users/sessions.py` | 新增 | `SessionManager`：`create`、`validate`、`touch`、`revoke`、`revoke_all(user_id, *, except_sid=None, reason)`、`revoke_by_provider(provider_id)`、`list_active(user_id)` |
| `src/octop/infra/db/repos/auth_sessions.py` | 新增 | `AuthSessionRepo`：SQL only |
| `src/octop/infra/db/repos/password_history.py` | 新增 | `PasswordHistoryRepo.add/recent(user_id, n)` |
| `src/octop/infra/db/services.py` | 修改 | 两个 repo 各三处：`RepoBundle` 字段、构造、`SharedServices` property |
| `src/octop/infra/auth/login_mode.py` | 新增 | `LoginMode = Literal["local","sso_only","hybrid"]`、两个判定函数 |
| `src/octop/api/common/ws_auth.py` | 新增 | `accept_and_authenticate`、`ws_session_guard` |
| `src/octop/api/deps.py` | 修改 | `sign_token`、`extract_raw_token`、`resolve_user_from_token`、`maybe_sliding_renew_token`、`authenticate_request`、`current_user` |
| `src/octop/api/middleware/jwt_auth.py` | 修改 | 删 query 读取；强制改密拦截 |
| `src/octop/api/routers/auth.py` | 修改 | login 建会话与模式判定、logout 吊销、`GET /password-policy`、`GET/DELETE /sessions`、`me_payload` 加 `must_change_password` |
| `src/octop/api/routers/users.py` | 修改 | `GET /{user_id}/sessions`、`POST /{user_id}/sessions/revoke`（沿用该文件既有用户管理判定） |
| `src/octop/api/routers/{invites,setup,auth_oidc,auth_oauth}.py` | 修改 | 建会话；模式判定；`OauthProviderPutBody`/`OidcConfigBody` 扩准入字段；`verify_password` 改口令来源 |
| `src/octop/api/routers/chat/{ws,notify_ws}.py` | 修改 | 改用 `accept_and_authenticate` |
| `src/octop/infra/users/{manager,password,invites}.py` | 修改 | 吊销挂点、历史、有效期、`must_change_password` 赋值 |
| `src/octop/infra/auth/sso/{service,id_token,public_base}.py`、`repos/sso.py` | 修改 | 见方案 9 |
| `src/octop/infra/server.py` | 修改 | 删 `_emit_wizard_password` 及导入；注入口令策略与 OIDC 算法；构造 `SessionManager` |
| `dashboard/src/api/modules/{wsChat,wsNotifications,trajectory,auth,sso}.ts` | 修改 | 首帧、fetch 流、`passwordPolicy`、`login_mode`、准入字段 |
| `dashboard/src/pages/ChangePassword/index.tsx` | 新增 | 强制改密页 |
| `dashboard/src/components/AuthGuard.tsx`、`pages/Login/index.tsx`、`utils/passwordPolicy.ts`、`pages/Setup/steps/PasswordStep.tsx` | 修改 | ≈L64 已有 `authApi.me()` 响应上判定跳转；自动跳 IdP；策略从接口读；删文件位置引导 |

## 数据模型

`forkNNN_auth_sessions_and_password_policy.sql` 与 `.pg.sql`（号不预占）：

- `auth_sessions`：`id` 整数代理主键；`session_id TEXT UNIQUE`（= JWT `sid`）；`user_id INTEGER REFERENCES users(id)`（users 用整数主键，属 AGENTS.md 例外）；`created_at`、`last_seen_at`、`revoked_at`（可空）、`revoke_reason`；`sso_provider_id`、`idp_subject`、`src_ip`、`user_agent`；索引 `(user_id, revoked_at)`、`(sso_provider_id)`。
- `user_password_history`：`id`、`user_id`、`password_hash`、`created_at`（追加型，不设公共 id）。
- `users` 加列：`must_change_password INTEGER NOT NULL DEFAULT 0`、`password_changed_at`。回填：存量 `password_changed_at = 迁移时刻`，存量 `must_change_password = 0`（避免升级即全员强制改密与立即过期）。
- `sso_providers` 加列：`allowed_groups TEXT`（JSON 数组）、`group_claim TEXT DEFAULT 'groups'`、`group_role_map TEXT`（JSON 对象）、`auto_provision INTEGER NOT NULL DEFAULT 1`。

## 配置

每个键改 `src/octop/config.py` 三触点：`OctopConfig` 字段、env 覆盖块、`return OctopConfig(...)` 构造。

| 键 | env | 默认 |
|---|---|---|
| `auth_login_mode` | `OCTOP_AUTH_LOGIN_MODE` | `hybrid`（与基线行为一致） |
| `session_idle_timeout_seconds` | `OCTOP_SESSION_IDLE_TIMEOUT` | 1800 |
| `session_absolute_timeout_seconds` | `OCTOP_SESSION_ABSOLUTE_TIMEOUT` | 28800 |
| `max_concurrent_sessions_per_user` | `OCTOP_MAX_SESSIONS_PER_USER` | 5（0 = 不限） |
| `ws_auth_timeout_seconds` | `OCTOP_WS_AUTH_TIMEOUT` | 10 |
| `password_min_length` | `OCTOP_PASSWORD_MIN_LENGTH` | 8 |
| `password_max_age_days` | `OCTOP_PASSWORD_MAX_AGE_DAYS` | 90（0 = 不过期） |
| `password_history_count` | `OCTOP_PASSWORD_HISTORY_COUNT` | 5 |
| `oidc_allowed_algorithms` | `OCTOP_OIDC_ALLOWED_ALGS` | `RS256,ES256,PS256` |
| `oidc_issuer_host_allowlist` | `OCTOP_OIDC_ISSUER_HOSTS` | 空（只校验 https） |
| `setup_password` | `OCTOP_SETUP_PASSWORD` | 空；仅 env，不落 config.json |

既有键 `access_token_ttl_seconds` 默认值由 86400 改为 900；`require_setup_password` 保留。

## 错误处理

新增码追加到 `ErrorCode` 末尾与 `_DEFAULT_STATUS` 末尾，文案进 intranet overlay：

| 码 | 状态 | 用途 |
|---|---|---|
| `LOGIN_MODE_DISABLED` | 403 | 当前登录模式不允许该入口 |
| `SESSION_REVOKED` | 401 | 会话不存在、已登出、被踢、被并发挤掉 |
| `PASSWORD_CHANGE_REQUIRED` | 403 | 强制改密期间访问其他接口 |
| `PASSWORD_REUSED` | 400 | 命中历史口令 |

复用：超时用 `TOKEN_EXPIRED`（401）；停用沿用 `USER_DISABLED`（403）；issuer 与算法配置错误用 `OIDC_BAD_REQUEST`；向导口令错误用 `SETUP_PASSWORD_WRONG`。OIDC 未准入走回调重定向 `oidc_error=not_admitted`，文案进前端 overlay `login.oidcError.not_admitted`。

## 安全考虑

- 令牌只经 `Authorization` 头或 WS 首帧传递；首帧前的连接由 `ws_auth_timeout_seconds` 回收，限速归 `w3-01` 的书面残留。
- 会话校验读库而非只读缓存，多进程下停用与吊销同样生效；`last_seen_at` 节流避免每请求写库。`w2-03` 指出 `_decode` 每请求读 `secrets`，本 spec 顺带加进程内缓存，密钥轮换时失效。
- `setup_password` 与 `OCTOP_DEFAULT_PASSWORD` 只经环境变量注入，不打印、不落盘；由 w3-02 的日志脱敏 Formatter 兜底。
- issuer 不用 `ssrf_guard`（会拒私网 IP）；强度由 https + 主机白名单 + 行内 CA 保证。
- SSO 用户不设 `must_change_password`，避免无法完成的强制改密死锁。

## 测试策略

- 单测：`uv run pytest tests/unit/users/test_sessions.py tests/unit/api/test_jwt_tokens.py tests/unit/api/test_ws_auth.py tests/unit/test_password.py tests/unit/auth/test_sso_id_token.py tests/unit/auth/test_sso_admission.py tests/unit/auth/test_login_mode.py tests/unit/test_config.py -q`（超时用可注入时钟）。
- 集成：`uv run pytest tests/integration/test_session_revocation.py tests/integration/test_login_mode.py tests/integration/test_password_policy.py tests/integration/test_chat_ws.py tests/integration/test_notifications_ws.py tests/integration/test_auth_oauth.py tests/integration/test_setup_wizard.py tests/integration/test_setup_bootstrap.py tests/integration/test_setup_database.py -q`。
- 前端：`cd dashboard && npx tsc -b && npm run lint && npm run test -- useTrajectorySession passwordPolicy`（依赖 `w0-02` 的 frontend job）。
- PG：`OCTOP_TEST_DATABASE_URL=postgresql://… uv run pytest tests/integration/test_postgresql_control_plane.py tests/integration/test_session_revocation.py -q`（依赖 `w0-02` 的 postgres service）。
- i18n：`uv run pytest tests/unit/i18n -q`。

## 与其他 spec 的交接

- **依赖：** `w0-01` 的 `run_fork_migrations`；`w0-03` 的 `tests/support/auth.py` 新基线（本 spec 只改其中 `wizard_token` 的口令来源与 `TEST_PASSWORD` 长度到 12 位以上）；`w0-04` 的 overlay 与 `CHANGELOG-intranet.md`；`w1-01` 的 `octop.infra.setup.completion.is_setup_completed`（不自建标记）；`w1-02` 已删 5 个 WS；`w1-04` 已删 `fnos/`、`desktop/`；`w2-01` 的入口脚本退出码契约（本 spec 把"退出码 4 → 随机口令重试"和"写 `credential.txt`"改为失败退出，契约表由本 spec 更新）；`w3-02` 的 `sign_token(sid=…)` 与 `AuditContext`；`w3-03` 的角色实体与赋值接口（组到角色映射只调用，不建角色）。
- **交付：** `w3-05` 可对 `auth_sessions` 无需加密（无秘密列）；`p2-02` 接手 JWT 签名密钥派生；`p2-07` 基于 `GET /api/auth/sessions` 做会话列表页与空闲登出提示；`p2-11` 复用 `SessionManager.create(..., sso_provider_id, idp_subject)` 与登录模式判定接入 CAS/SAML/LDAP。
- **看似相关但不归本 spec：** 安装向导 410（`w1-01`）；验证码（`w3-01`）；限流 `auth` 桶改按 user id（`w3-01` 后续，可选）；知识库权限（`p2-05`）。

## 风险与回滚

- 升级后旧令牌无 `sid` 全部失效，用户需重登：写进 CHANGELOG；回滚时回退代码即可，新表与新列对旧代码不可见。
- TTL 降到 900 秒依赖滑动续签，前端 `applyRenewedAccessToken` 已处理响应头；若长时间后台标签页失效，属预期。
- 入口脚本改为缺口令即退出，未注入 `OCTOP_DEFAULT_PASSWORD` 的旧编排会起不来：部署手册与 compose 示例同步。
- trajectory SSE 重写是前端回归最大块：先写 vitest 用例覆盖续传与隐藏关闭。

## 待行方确认

- D1：按 OIDC 起草；若为 CAS/SAML/LDAP，由 `p2-11` 在本 spec 的会话接口上接入。
- D5：单活，会话表放控制面库，`last_seen_at` 节流在进程内；多活时需改为库内条件更新。
- D12：组到角色映射的目标角色取 `w3-03` 定义的三员角色。
- 本 spec 自身假设（无 D 编号）：口令最小长度默认 8、可配到 12；空闲 30 分钟、绝对 8 小时、单用户 5 个并发会话；首装向导口令由 `OCTOP_SETUP_PASSWORD` 注入。
