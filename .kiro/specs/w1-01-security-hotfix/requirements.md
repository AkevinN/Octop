# 需求文档：五个现成漏洞热修

> spec：`w1-01-security-hotfix` ｜ 波次：Wave 1 ｜ 基线：`757fd12` ｜ 预估：7 人日
> 前置：`w0-01-fork-migration-namespace`、`w0-02-ci-gates`、`w0-03-test-auth-baseline`、`w0-04-fork-isolation-points` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 引言

**结论：** 本 spec 用最小改动堵住基线上五个已核实、可直接利用的漏洞，不删除任何功能，可以在 Wave 1 里最先单独合入。其中 #1、#1b、#2、#5 完整修复；#3（自定义 MCP）与 #4（ACP 运行器）只做"临时闸门"，两项合计约 1 人日，因为 ACP 会在 `w1-02` 被整体删除，stdio 传输会在 `w3-06` 被移除。本 spec 不新增 `ErrorCode`、不新增权限键、不新增配置键，也不改上游 i18n JSON。

### 背景

基线上已核实的五个漏洞：

| # | 漏洞 | 利用门槛 |
|---|---|---|
| 1 | `GET /api/providers` 只要求登录，响应原样返回每个大模型供应商的明文 `api_key` | 任意登录用户 |
| 1b | `GET /api/voice/providers` 同样只要求登录，返回语音供应商的 `api_key`，以及 `extra` 里腾讯云的 `secret_id` / `secret_key` | 任意登录用户 |
| 2 | 持 `users` 权限的非管理员可以创建管理员、把自己提为管理员，还能对管理员账号改密、停用、删除、解锁 | 持 `users` 权限的普通用户 |
| 3 | 自定义 MCP 的保存与探测接口接受 stdio 传输，探测会在服务器上直接起子进程；任何用户都能把自己的 server 标为 `shared`，从而注入到所有其他用户（含管理员）的 agent | 任意登录用户 |
| 4 | ACP 的 3 个 agent 作用域路由用 Python 直调管理员路由函数，绕过了 `Depends(require_admin())`；`PUT /api/agents/{aid}/acp` 从未有过管理员校验；另有一条经 `PATCH /api/agents/{id}` 写入 `config.acp.runners`、再被遗留迁移吸收的写入链。运行器命令会交给 harness 在主机上执行 | agent owner（任意登录用户） |
| 5 | `POST /api/setup/resume-wizard` 零鉴权，全站恰有 1 个账号时，匿名者可以拿到 wizard 令牌，再调 `finish` 写入自己的大模型地址与密钥，劫持全部大模型流量 | 匿名 |

### 为什么做

这五个漏洞在内网渗透测试中都会被直接开单，其中 #3、#4、#5 可以拿到主机命令执行或劫持全部模型流量。它们的修复与后续加固 spec 不冲突：#1 的脱敏契约是 `w3-05`（落库加密）与 `p2-06`（行内网关字段）的前提；#5 的持久关闭标记由 `w3-04` 消费。

### 范围内

1. **#1 供应商密钥脱敏**：`GET /api/providers` 与 `GET /api/admin/providers` 的元素去掉 `api_key`，改为 `has_api_key` 与 `local_runtime`；`GET /api/providers` 改为 `require_permission("providers")`；`POST /api/admin/providers/fetch-models` 支持 `provider_id` 取库内密钥；前端同批改完。
2. **#1b 语音凭据脱敏**：两个语音列表接口去掉 `api_key`，`extra` 去掉敏感项；`GET /api/voice/providers` 改为 `require_permission("voice")`；PATCH 时空的敏感项保留库内值；语音设置页同批改完。
3. **#2 用户越权**：非管理员不能授予 `admin` 角色，不能对管理员账号执行任何写操作；用户管理页同批改完。
4. **#3 自定义 MCP 临时闸门**：stdio 传输在保存、探测、运行时装配三处默认拒绝；`shared: true` 只有管理员能设置，并在启动时清理非管理员的存量共享；`PATCH` 与探测补审计。
5. **#4 ACP 临时闸门**：4 个 agent 作用域路由（含 `put_acp_config`）改为 `require_admin()`；运行时忽略非管理员的 runner 数据；用 fork 迁移清理存量非管理员 runner。
6. **#5 安装向导**：`resume-wizard` 手写鉴权；新增持久标记 `setup.completed`，`finish` 写入、`initial-admin` 在空库时清除、两条启动路径对存量单管理员实例回填。本 spec 是该标记的 owner。
7. 记录：`CHANGELOG-intranet.md`「安全」小节、`docs/api-intranet.md` 第 3、4 节。

### 范围外（归属）

- **stdio 命令白名单、ACP 运行器命令白名单**：不做。ACP 由 `w1-02-capability-trim` 物理删除；stdio 由 `w3-06-agent-execution-hardening` 移除。本 spec 的闸门是过渡实现。
- **自定义 MCP 接口要求 `connectors` 权限键、权限判定收口（含 admin 绕过）**：`w3-03-authorization-foundation`。本 spec 的 #2 仍以 `admin` 角色为界。
- **providers / voice_providers 凭据落库加密与国密**：`w3-05-credential-encryption`、`p2-02-kms-sm-crypto`。本 spec 只做传输层脱敏。
- **供应商、用户写操作的审计，审计字段集与防篡改**：`w3-02-audit-baseline`、`p2-03-audit-tamper-proof`。本 spec 只按范围在自定义 MCP 的 PATCH 与探测上补审计。
- **在线语音（腾讯、小米、edge）删除**：`w1-05-saas-decoupling`。本 spec 的语音脱敏按键名通用处理，不依赖具体厂商。
- **会话吊销、令牌移出 URL、登录模式**：`w3-04-session-and-password`，它只消费本 spec 的 `setup.completed`。
- **`docs/api.md` 中已过期的记录**（如 ≈L228-231 不存在的 `/providers` 写路由、≈L77 的 `resume-wizard | public`）：全局约束第 5 节规定 fork 不改 `docs/api.md`，本 spec 只在 `docs/api-intranet.md` 记录差异。
- **死代码 `dashboard/src/pages/Settings/octop/Providers.tsx`**：它自带局部类型，不受响应形状影响，本 spec 不动，由 `w1-04-content-trim` 决定去留。

## 需求

### 需求 1：大模型供应商列表不再返回明文密钥

**用户故事：** 作为银行安全管理员，我希望任何 HTTP 响应都不再携带大模型供应商的明文 API Key，并且只有具备模型管理权限的人才能读取供应商列表，以便普通账号泄露时不会连带泄露全部大模型凭据。

#### 验收标准

1. 当管理员或持 `providers` 权限的用户请求 `GET /api/providers` 或 `GET /api/admin/providers` 时，providers 路由应当返回不含 `api_key` 键的元素，并为每个元素给出布尔字段 `has_api_key`（库内 `api_key` 非空时为 `true`）与 `local_runtime`（`"onnx"`、`"ollama"` 或 `null`）。
2. 如果请求 `GET /api/providers` 的用户既不是管理员、也不持有 `providers` 权限，那么系统应当返回 403，且 `error.code == "FORBIDDEN"`。
3. 当管理员调用 `POST /api/admin/providers` 或 `PATCH /api/admin/providers/{id}` 时，返回体应当同样不含 `api_key`，而请求中的 `api_key` 仍照常入库（`provider_repo.get(id).api_key` 等于提交值）。
4. providers 与 voice 路由应当始终不把库内凭据原样写进响应：`rg -n '"api_key": r\.api_key' src/octop/api/routers/` 无输出。
5. 在「模型」设置页渲染期间，dashboard 应当以 `has_api_key` 判断授权状态、以 `local_runtime` 识别本地 ONNX 与 Ollama 供应商，页面上不出现密钥的任何字符；`presetUtils` 的 vitest 用例覆盖 `local_runtime` 判定。

### 需求 2：不重输密钥也能测试连通性与拉取模型

**用户故事：** 作为模型管理员，我希望在脱敏之后仍能不重输密钥就测试已保存的供应商、拉取它的模型列表，以便脱敏不变成功能裁剪；同时库内密钥不能被带到别的主机上。

#### 验收标准

1. 当 `POST /api/admin/providers/fetch-models` 的 `api_key` 为空、带 `provider_id`，且 `base_url` 为空或与库内 `base_url` 相同时，系统应当用库内 `api_key`（请求未带 `extra_json` 时也用库内 `extra_json`）拉取模型列表。
2. 如果请求带 `provider_id`、未提供 `api_key`，而 `base_url` 与库内不同，那么系统应当返回 `{"ok": false, "error": "api_key is required"}`，且不发起任何外呼。
3. 如果 `provider_id` 指向不存在的供应商，那么系统应当返回 404，且 `error.code == "NOT_FOUND"`。
4. 当管理员在供应商配置弹窗里不重输密钥就点「拉取模型」或「测试」时，dashboard 应当分别以 `provider_id` 调用 fetch-models、以 `POST /admin/providers/{id}/test` 测试；如果改了 Base URL 却没重输密钥，dashboard 应当提示既有文案 `models.pleaseEnterApiKey` 且不发请求。
5. 基线用例 `tests/integration/test_provider_fetch_models.py`、`tests/integration/test_provider_test_draft.py`、`tests/integration/test_provider_test_endpoint.py` 应当始终零修改通过。

### 需求 3：语音供应商凭据脱敏

**用户故事：** 作为银行安全管理员，我希望语音供应商的 API Key 与 `extra` 里的云厂商密钥都不再出现在响应中，并且编辑已配置的语音供应商时不会误清空库内凭据，以便这个洞被完整堵住而不是只堵一半。

#### 验收标准

1. 当调用 `GET /api/voice/providers` 或 `GET /api/admin/voice/providers` 时，每个元素应当不含 `api_key`、含 `has_api_key`，并且 `extra` 中不含 `secret_id`、`secret_key`、`api_key`、`token`、`password`，也不含键名以 `_key`、`_secret`、`_token`、`_password` 结尾的项；当被移除的项中任一值非空时 `has_secret_key` 为 `true`；`region` 等非敏感项原样保留。
2. 如果请求 `GET /api/voice/providers` 的用户既不是管理员、也不持有 `voice` 权限，那么系统应当返回 403，且 `error.code == "FORBIDDEN"`。
3. 当管理员 `PATCH /api/admin/voice/providers/{id}` 且 `extra_json` 中的敏感项缺失或为空串时，系统应当保留库内原值；`api_key` 为 `null` 时库内值不变。以腾讯语音为例：只带 `{"region": "ap-guangzhou"}` 的 PATCH 之后，库内 `extra` 的 `secret_id`、`secret_key` 与 `api_key` 均不变。
4. 在编辑已配置的语音供应商期间，dashboard 应当不预填任何凭据，允许不重输凭据直接保存，并在不重输凭据时改用 `POST /admin/voice/providers/{id}/test` 探测。

### 需求 4：持 users 权限的非管理员不能越权到管理员

**用户故事：** 作为银行系统管理员，我希望被授予"用户管理"权限的普通运维账号只能管理普通账号，以便这个权限不能被用来把自己变成管理员或接管管理员账号。

#### 验收标准

1. 当持 `users` 权限的非管理员 `POST /api/users` 且 `role` 为 `"admin"` 时，系统应当返回 403，且用户表不新增行。
2. 当该非管理员 `PATCH /api/users/{自己的 id}` 带 `role: "admin"` 时，系统应当返回 403，且此后 `GET /api/auth/me` 返回的 `role` 仍为 `"user"`。
3. 如果目标账号是管理员，那么该非管理员发起的 `PATCH /api/users/{id}`（任意字段）、`POST /api/users/{id}/reset-password`、`POST /api/users/{id}/unlock-login`、`DELETE /api/users/{id}` 均应当返回 403，目标账号的角色、口令、停用状态与存在性都不变。
4. 当该非管理员编辑普通账号、请求体带 `role: "user"`（dashboard 编辑弹窗总会带上 `role`）时，系统应当照常返回 200。
5. 基线 `tests/integration/test_users_api.py` 的 10 个用例应当始终零修改通过。
6. 在用户管理页中，非管理员操作者应当看不到"管理员"角色选项；对管理员行发起改角色、停用、编辑、改密、解锁、删除时，dashboard 应当在本地拦截并提示 overlay 文案 `adminUsers.adminTargetAdminOnly`。

### 需求 5：自定义 MCP 的 stdio 传输默认拒绝（临时闸门）

**用户故事：** 作为银行安全管理员，我希望任何人都不能经由自定义 MCP 在服务器上启动任意进程，包括升级前已经存入库里的 stdio 配置，以便在 `w3-06` 移除 stdio 之前这条命令执行链就已关闭。

#### 验收标准

1. 当任何用户（含管理员）`PUT /api/connectors/custom-mcp`，且 `servers` 中任一项的 `transport` 为 `"stdio"` 时，系统应当返回 400 `CONNECTOR_KIND_UNSUPPORTED`，库内文档保持不变。
2. 当 `POST /api/connectors/custom-mcp/test` 携带 stdio 内联 spec、或 `name` 指向库内 stdio 项，或者 `POST /api/connector-instances/{id}/test` 指向库内 stdio 自定义项时，系统应当返回 400 `CONNECTOR_KIND_UNSUPPORTED`，且 `mcp.client.stdio.stdio_client` 未被调用。
3. 在库内已存在 stdio 自定义 server（升级前写入）期间，`ConnectorService.custom_harness_configs(user_id)` 应当不返回任何 `transport` 不为 `"streamable_http"` 的项（自有与共享两个分支都适用），并记录 warning。
4. `tests/unit/connectors/test_custom_mcp.py` 与 `tests/unit/agents/test_mcp_tool_cache.py` 应当始终零修改通过，即闸门不下沉进 `normalize_server_spec`、`validate_servers_map` 与 `ConnectorService.put_custom_servers`。

### 需求 6：共享自定义 MCP 收归管理员，变更与探测留痕

**用户故事：** 作为银行安全管理员，我希望只有管理员能把自定义 MCP 共享给全体用户，已被普通用户共享出去的 server 在升级后自动收回，并且探测与变更都留审计，以便堵住跨用户注入并能追溯。

#### 验收标准

1. 当非管理员 `PUT /api/connectors/custom-mcp` 的任一项带 `shared: true`，或 `PATCH /api/connectors/custom-mcp/servers/{name}` 带 `shared: true` 时，系统应当返回 403 `FORBIDDEN` 且不写库；管理员做同样的操作应当成功。
2. 当 `OctopServer.start()` 或 `OctopServer.bind_control_plane()` 完成服务装配时，系统应当把非管理员拥有的自定义 MCP 文档中所有 `shared: true` 改为不共享，该步骤幂等；此后其他用户的 `custom_harness_configs` 不再包含这些 server。
3. 当 `PATCH /api/connectors/custom-mcp/servers/{name}` 成功，或 `POST /api/connectors/custom-mcp/test`、`POST /api/connector-instances/{id}/test`（自定义目标）被调用时（含被 stdio 闸门拒绝的调用），系统应当各写一条 `audit_log`，`action` 分别为 `connector.custom_mcp.patch` 与 `connector.custom_mcp.probe`，可经 `GET /api/admin/audit-log?action=<action>` 查到。
4. 基线 `tests/integration/test_connectors_api.py` 应当始终零修改通过，包括管理员设置共享的 `test_shared_custom_mcp_is_visible_with_collision_safe_name`。

### 需求 7：ACP 运行器配置收归管理员（临时闸门）

**用户故事：** 作为银行安全管理员，我希望在 `w1-02` 删除 ACP 之前，普通用户无论经哪条路径都不能定义会在主机上执行的 ACP 运行器命令，存量数据也被清理，以便过渡期不留命令执行口子。

#### 验收标准

1. 当非管理员在自己拥有的 agent 上调用 `GET`、`PUT`、`DELETE /api/agents/{aid}/acp/{runner_name}` 或 `PUT /api/agents/{aid}/acp` 时，系统应当返回 403 `FORBIDDEN`，settings 中的 runner 定义不变。
2. 在上述限制生效期间，`GET /api/agents/{aid}/acp` 与 `PUT /api/agents/{aid}/acp/tool` 对 agent owner 应当仍返回 200。
3. 当 `AgentManager` 为某个 agent 组装 ACP 配置、而 runner 归属用户不是管理员时，系统应当只提供内置运行器的默认定义，忽略该用户在 settings 中保存的覆盖，也不触发对 agent `config_json` 中遗留 `acp.runners` 的迁移。
4. 当 fork 迁移 `forkNNN_purge_non_admin_acp_runners` 执行时，settings 表中属于非管理员的 `acp_runners:user:<id>` 行应当被删除，属于管理员的行保留；SQLite 与 PostgreSQL 都成立。
5. 基线 `tests/integration/test_acp_api.py` 与 `tests/unit/agents/test_acp_settings.py` 应当始终零修改通过。

### 需求 8：安装向导 resume-wizard 鉴权与持久关闭

**用户故事：** 作为银行运维人员，我希望安装向导在首位管理员建好后不能再被匿名者接管，完成后永久关闭，已经在运行的存量实例升级后也同样关闭，以便没有人能借向导静默替换大模型配置。

#### 验收标准

1. 如果全站恰有 1 个用户、安装尚未完成，而请求不带有效凭据，那么 `POST /api/setup/resume-wizard` 应当返回 401 `SETUP_TOKEN_INVALID`（基线为 200）。
2. 当请求带 `POST /api/setup/initial-admin` 返回的 `access_token` 或有效的 wizard token 时，`POST /api/setup/resume-wizard` 应当返回 200 与新的 `wizard_token`。
3. 当用户数 ≥ 1 且 `POST /api/setup/finish` 成功返回后，settings 表应当存在键 `setup.completed`；此后 `resume-wizard`、`finish`、`test-provider`、`validate-token` 即使带有效凭据也应当返回 410。用户数为 0 时 `finish` 不写该标记。
4. 当 `start()` 或 `bind_control_plane()` 打开一个"有用户，且用户数 > 1、或已配置 active model、或已存在 `main` agent，却没有 `setup.completed`"的库时，系统应当在对外服务前写入该标记；两条启动路径各有集成用例断言随后 `resume-wizard` 返回 410。
5. 如果库内只有 1 个用户，且既无 active model、也无 `main` agent（向导中途），那么启动回填应当不写标记，带管理员 JWT 调 `resume-wizard` 仍返回 200。
6. 当 `POST /api/setup/initial-admin` 在用户数为 0 时成功创建管理员后，系统应当清除遗留的 `setup.completed`，使随后的 `finish` 能够完成。
7. `src/octop/infra/setup/completion.py` 应当始终是该标记的唯一读写入口：`rg -n 'setup\.completed' src/octop --glob '*.py'` 只命中这一个文件。

### 需求 9：交付门禁与记录

**用户故事：** 作为 fork 维护者，我希望这次热修不引入新的错误码、权限键、配置键，也不改上游高 churn 文件，并且变更有据可查，以便它能最先单独合入且不增加上游同步成本。

#### 验收标准

1. 当本 spec 的最后一个任务完成时，`make all` 与 `cd dashboard && npx tsc -b && npm run lint && npm run test` 应当全绿。
2. 本 spec 应当始终不新增 `ErrorCode`、权限键与 `OctopConfig` 字段，也不改上游 i18n JSON：相对任务 1 记录的基线提交，`git diff --stat "$W101_BASE" -- src/octop/infra/errors.py src/octop/config.py src/octop/infra/users/permissions.py src/octop/i18n/en.json src/octop/i18n/zh.json dashboard/src/locales/en.json dashboard/src/locales/zh.json` 无输出，且 `uv run pytest tests/unit/i18n tests/unit/api/test_acl_gate_coverage.py -q` 全绿。
3. 新增的前端文案应当只写在 `dashboard/src/locales/intranet/{en,zh}.json`，两份同键，`w0-04` 的 overlay 对等测试全绿。
4. `CHANGELOG-intranet.md` 的「安全」小节与 `docs/api-intranet.md` 第 3、4 节应当记录本 spec 的全部行为与鉴权差异；`CHANGELOG.md` 与 `docs/api.md` 不改。
