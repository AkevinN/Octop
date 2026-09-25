# 需求文档：会话与口令
> spec：`w3-04-session-and-password` ｜ 波次：Wave 3 ｜ 基线：`757fd12` ｜ 预估：33 人日
> 前置：w0-01-fork-migration-namespace, w0-02-ci-gates, w0-03-test-auth-baseline, w0-04-fork-isolation-points, w1-01-security-hotfix, w1-02-capability-trim, w1-04-content-trim, w2-01-offline-build, w3-01-web-security-baseline, w3-02-audit-baseline, w3-03-authorization-foundation ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 引言

**结论：** 本 spec 把 Octop 的身份与会话层从"24 小时无状态 JWT、可无限滑动续签、令牌放在 URL、口令写明文文件"改成"服务端会话表 + 短时令牌 + 可实时吊销、令牌只走请求头或首帧、口令策略可配、零明文落盘"，并把登录方式收口为本地、仅 SSO、混合三态。

**为什么做：** 等保测评最常实测的就是会话吊销、超时、令牌泄露面与口令策略。基线上 `POST /api/auth/logout` 只写审计不吊销，禁用用户在多实例下不失效，JWT 出现在 WS 与 SSE 的 URL 里，首装口令写进 `~/octop-login.txt` 与 `credential.txt` 并打印到终端。

**范围内（源分析 S07 中的 S07a 部分）：**
- 登录模式三态与仅 SSO 模式下自动跳转 IdP。
- 会话表（fork 迁移）、短时令牌、吊销（登出、改密、重置、停用、IdP 停用）、空闲与绝对超时、单用户并发上限、会话管理 API；去掉无限滑动续签。
- 令牌移出 URL：`w1-02` 删除 5 个 WS 后只剩 `chat/ws.py`、`chat/notify_ws.py` 与 trajectory SSE。
- 口令策略：最小长度可配、有效期、历史口令、首次登录强制改密、前端 `passwordPolicy.ts` 从接口取值。
- 删除 `~/octop-login.txt`、`credential.txt` 的明文落盘与终端打印。
- OIDC 加固：算法白名单可配、issuer 仅 https 加主机白名单、准入组、组到角色映射。

**范围外：**
- CAS / SAML / LDAP 身份源适配器：`p2-11-identity-adapters`。
- 安装向导持久关闭标记 `setup.completed`：`w1-01`（本 spec 只消费）。
- 验证码终态、中间件栈顺序、限流：`w3-01`。审计字段集、`sid` 生成与透传的首次落地：`w3-02`。角色实体与三员分立：`w3-03`。
- JWT 密钥由主密钥派生、国密：`w3-05`、`p2-02`。前端空闲登出提示与会话列表页：`p2-07`。
- `fnos/`、`desktop/` 下的凭据链路：已由 `w1-04` 随目录删除（D9）。

## 需求

### 需求 1：登录模式三态

**用户故事：** 作为安全管理员，我希望用一个配置项决定允许本地口令登录、仅统一认证还是两者并存，以便满足行内"统一身份"要求。

#### 验收标准
1. 当 `OCTOP_AUTH_LOGIN_MODE=sso_only` 时，`POST /api/auth/login` 与邀请兑换接口（`invites.py::public_router` 的 `POST /redeem`）应当返回 403，`error.code` 为 `LOGIN_MODE_DISABLED`。
2. 如果 `OCTOP_AUTH_LOGIN_MODE=local`，那么 `GET /api/auth/oidc/status` 与 `GET /api/auth/oauth/status` 应当返回 `enabled=false`，且 `POST /api/auth/oidc/start`、`POST /api/auth/oauth/start` 返回 403 `LOGIN_MODE_DISABLED`。
3. 在 `sso_only` 模式且 OIDC 已启用期间，打开登录页时前端应当直接跳转到 IdP 授权端点；URL 带 `oidc_error` 时不跳转，改为展示错误，避免循环。
4. 两个 status 接口应当始终在响应中返回 `login_mode` 字段。

### 需求 2：服务端会话与短时令牌

**用户故事：** 作为安全管理员，我希望每个访问令牌都对应一条服务端会话，以便令牌可被实时吊销与审计。

#### 验收标准
1. 当任一发令牌点（本地登录、邀请兑换、向导建管理员、OIDC/OAuth 兑换）签发令牌时，系统应当在 `auth_sessions` 写入一行，令牌 `sid` 等于该行 `session_id`。
2. 当滑动续签签发新令牌时，新令牌应当携带与原令牌相同的 `sid`。
3. 如果令牌的 `sid` 在 `auth_sessions` 中不存在或已吊销，那么任何已鉴权接口应当返回 401 `SESSION_REVOKED`。
4. 访问令牌有效期默认应当始终不超过 900 秒（`access_token_ttl_seconds` 默认值由 86400 改为 900）。
5. 当 SSO 登录兑换时，会话行应当记录 `sso_provider_id` 与 `idp_subject`。

### 需求 3：会话吊销

**用户故事：** 作为用户与管理员，我希望登出、改密、停用会立即让旧令牌失效，以便令牌泄露后能止损。

#### 验收标准
1. 当用户调用 `POST /api/auth/logout` 后，同一令牌访问 `GET /api/auth/me` 应当返回 401 `SESSION_REVOKED`。
2. 当用户调用 `POST /api/auth/change-password` 成功后，该用户其他会话应当全部吊销；管理员重置口令后该用户全部会话吊销。
3. 当管理员停用用户后，该用户全部会话应当吊销，旧令牌访问返回 403 `USER_DISABLED`（沿用既有映射）。
4. 当 OIDC provider 的 `enabled` 经 `PUT /api/auth/oidc/config` 或 `PUT /api/auth/oauth/providers/oidc` 由 true 改为 false 时，该 provider 下所有会话应当吊销。

### 需求 4：空闲超时、绝对超时与并发上限

**用户故事：** 作为安全管理员，我希望会话有空闲与绝对时限，并限制单用户并发会话数，以便满足等保会话管理要求。

#### 验收标准
1. 如果会话最后活动时间距今超过 `session_idle_timeout_seconds`，那么请求应当返回 401 `TOKEN_EXPIRED`，会话被标记吊销。
2. 如果会话创建时间距今超过 `session_absolute_timeout_seconds`，那么请求应当返回 401 `TOKEN_EXPIRED`，且滑动续签不再下发 `X-Octop-Access-Token`。
3. 当某用户活跃会话数已达 `max_concurrent_sessions_per_user` 时再次登录，系统应当吊销该用户最早的会话。
4. 会话最后活动时间的写库频率应当始终不高于每会话每 60 秒一次。

### 需求 5：会话管理 API

**用户故事：** 作为用户与管理员，我希望能查看并踢出会话，以便处置可疑登录。

#### 验收标准
1. 当用户调用 `GET /api/auth/sessions` 时，系统应当只返回本人的活跃会话（含创建时间、最后活动、来源 IP、User-Agent、是否当前会话）。
2. 当用户调用 `DELETE /api/auth/sessions/{session_id}` 删除本人会话时，该会话应当立即吊销；删除他人会话返回 404。
3. 当具备用户管理权限的管理员调用 `GET /api/users/{user_id}/sessions` 与 `POST /api/users/{user_id}/sessions/revoke` 时，系统应当列出或吊销该用户全部会话；无权限者返回 403。
4. 每次吊销应当写一条审计事件 `auth.session_revoke`。

### 需求 6：令牌移出 URL

**用户故事：** 作为安全管理员，我希望 JWT 不出现在任何 URL 中，以便它不进入代理日志与浏览器历史。

#### 验收标准
1. 当客户端连接 `/api/agents/{id}/chat/ws` 或 `/api/notifications/ws` 后，服务端应当先 accept，并在 `ws_auth_timeout_seconds` 内等待 `{"type":"auth","token":...}` 首帧，成功回 `{"type":"auth_ok"}`。
2. 如果超时未收到首帧或令牌无效，那么服务端应当以 code 4001 关闭；带 `?token=` 的连接同样走超时分支。
3. 在 WS 长连接期间，服务端应当每 60 秒复核一次会话，会话吊销后以 4001 关闭。
4. `rg -n 'query_params.get\("access_token"\)|access_token: str \| None = Query|token: str \| None = Query' src/octop/api` 与 `rg -n 'params\.set\(\s*"token"|URLSearchParams\(\{\s*token|search\.set\("access_token"' dashboard/src --glob '!*.test.*'` 应当始终零命中。
5. 当轨迹面板订阅 trajectory SSE 时，前端应当用 `fetch` 携带 `Authorization` 头读取流，断线后按 `after_seq` 续传。

### 需求 7：口令策略

**用户故事：** 作为安全管理员，我希望口令有长度、有效期、历史与首次强制改密规则，并在前后端一致，以便满足等保口令要求。

#### 验收标准
1. 当 `GET /api/auth/password-policy`（无需登录）被调用时，系统应当返回 `min_length`、`max_age_days`、`history_count`，前端 `passwordPolicy.ts` 的长度校验应当使用该值。
2. 如果用户 `must_change_password=1`，那么除 `/api/auth/me`、`/api/auth/change-password`、`/api/auth/logout`、`/api/auth/password-policy` 外的 `/api/*` 应当返回 403 `PASSWORD_CHANGE_REQUIRED`，前端应当跳转到强制改密页。
3. 如果新口令与最近 `password_history_count` 个历史口令之一相同，那么改密应当返回 400 `PASSWORD_REUSED`。
4. 当 `password_changed_at` 超过 `password_max_age_days` 后登录时，`GET /api/auth/me` 应当返回 `must_change_password=true`。
5. 管理员新建、邀请兑换、`octop init` 创建的本地口令用户应当首次登录即需改密；SSO 自动开户用户（无本地口令）应当始终 `must_change_password=false`。

### 需求 8：明文凭据清零

**用户故事：** 作为安全管理员，我希望首装与初始化不在磁盘、终端或日志中留下明文口令，以便通过密评与渗透测试。

#### 验收标准
1. `rg -n 'octop-login.txt|credential.txt|password_file' src tests docker dashboard/src docs README.md README_CN.md` 应当始终零命中，`src/octop/infra/setup/password_file.py` 与 `tests/unit/test_wizard_password.py` 已删除。
2. 当服务启动时，stdout 与日志中应当不出现向导口令横幅。
3. 在 `require_setup_password=true` 期间，`POST /api/setup/verify-password` 应当只与注入的 `OCTOP_SETUP_PASSWORD` 做常量时间比较；未注入时返回 401 `SETUP_PASSWORD_WRONG`。
4. 如果容器未注入 `OCTOP_DEFAULT_PASSWORD` 或其未通过策略，那么 `docker/docker-entrypoint.sh` 应当以非零码退出，不生成随机口令、不写任何凭据文件。

### 需求 9：OIDC 加固

**用户故事：** 作为安全管理员，我希望 OIDC 只信任行内 IdP 与强签名算法，并按组准入与赋角色，以便统一认证不成为旁路。

#### 验收标准
1. 如果两条 provider 写入路由提交 `issuer="http://idp.intra"` 或主机不在 `oidc_issuer_host_allowlist`（非空时）中，那么应当返回 400 `OIDC_BAD_REQUEST`；`https://10.20.30.40/realms/x` 在白名单内时应当通过。
2. ID Token 验签算法应当始终取自 `oidc_allowed_algorithms`（默认 `RS256,ES256,PS256`），配置中的 `HS*` 与 `none` 应当始终被代码层剔除。
3. 当 provider 配置了 `allowed_groups` 而 ID Token 的组声明不含其中任一组时，回调应当重定向到 `/login?oidc_error=not_admitted`，且 `users` 表不新增行。
4. 当用户命中 `group_role_map` 时，自动开户与每次登录应当把用户角色同步为映射结果；`auto_provision=false` 时未预置用户一律拒绝。
5. OIDC 的 `dashboard_origin` 应当始终经过 https 校验。

### 需求 10：错误码、文案与文档一致性

**用户故事：** 作为维护者，我希望本 spec 新增的错误码与文案按全局约束登记，以便 i18n 门禁全绿且上游同步不冲突。

#### 验收标准
1. 新增的 `LOGIN_MODE_DISABLED`、`SESSION_REVOKED`、`PASSWORD_CHANGE_REQUIRED`、`PASSWORD_REUSED` 应当始终同时出现在 `ErrorCode` 末尾、`_DEFAULT_STATUS` 末尾、后端 intranet overlay en/zh 与前端 overlay `apiErrors` en/zh。
2. `uv run pytest tests/unit/i18n -q` 应当全绿，且本 spec 不删除任何上游 i18n 键。
3. 当 API 变更合入时，`docs/api-intranet.md` 与 `CHANGELOG-intranet.md` 应当记录新接口、令牌 TTL 默认值变化与 WS 握手协议。
