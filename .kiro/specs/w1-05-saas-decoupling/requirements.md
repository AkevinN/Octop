# 需求文档：公网 SaaS 断开

> spec：`w1-05-saas-decoupling` ｜ 波次：Wave 1 ｜ 基线：`757fd12` ｜ 预估：24 人日
> 前置：`w0-01-fork-migration-namespace`、`w0-02-ci-gates`、`w0-03-test-auth-baseline`、`w0-04-fork-isolation-points`、`w0-05-ssrf-intranet-allowlist`、`w1-01-security-hotfix`、`w1-02-capability-trim` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 引言

**结论：** 本 spec 把 Octop 里所有"直连公网 SaaS"的功能与入口物理删除，只留下四类可以指向行内的出口：进程内的 dashboard / cli 通道加可接行内 broker 的 MQTT；通用 OIDC 单点登录；WeKnora、Dify、自定义 MCP 三个样板连接器；OpenAI 兼容语音。删除面包括 8 个公网 IM 通道及其 14 个扫码 / 一键建号端点、飞书 / 钉钉 / 企微 3 个 SSO 适配器与 `/api/auth/oauth/callback`、21 个公网连接器（经 `w0-04` 的 `_FORK_REMOVED` 隐藏，配套删除 12 个网关适配器与 7 个飞书 / 企微 CLI 网关文件）、39 条来自 harness 包的公有云模型预设（改读仓库自维护清单）与 Codex OAuth、`opencode_session.py`、edge / 腾讯 / 小米三家在线语音与 `edge-tts` 依赖、火山方舟媒体生成、5 个联网搜索工具、5 个云验证码 provider（滑块保留为过渡态）。本 spec 删除 1 个权限键（`search`），新增 1 个 `ErrorCode`（`OUTBOUND_URL_REJECTED`）、1 条 fork 迁移（清洗权限与存量数据）、不新增配置键、不删除任何 i18n 键。

### 背景

以下事实均在基线 `757fd12` 上核实，证据见设计文档"现状"。

| 能力 | 基线行为 | 在行内网的后果 |
|---|---|---|
| IM 通道 | `ChannelKind` 来自第三方包 `harness_gateway.channels`，9 个取值中 8 个是公网 IM；`api/routers/channels.py` 1071 行里有 811 行是扫码与一键建号逻辑，直连 `oapi.dingtalk.com`、`work.weixin.qq.com` 等，并拉起 Chromium 子进程 | 断网即失败；库里残留的飞书通道在启动时仍会被 harness-gateway 建连 |
| SSO | 除通用 OIDC 外还有飞书、钉钉、企微 3 个 App-ID 适配器，共用 `/api/auth/oauth/callback` 公开回调 | 公网 IdP 不可达；多一个 JWT 豁免的公开路径 |
| 连接器 | 23 个内置条目中 21 个指向公网 SaaS；飞书 / 企微 CLI 连接器在服务启动时改写 `PATH`、按需 `npm install -g` | 能存不能用；运行期装包 |
| 模型预设 | `load_provider_presets()` 读 harness 包内 `provider_template.json`（39 条、256 个 model），再注入指向 `chatgpt.com` 的 `openai-codex` | 首次部署看到的全是公有云；harness 升级会带回新条目 |
| 语音 | 预设含 edge（`edge-tts`）、腾讯（`*.tencentcloudapi.com`）、小米（`api.xiaomimimo.com`）；OpenAI 语音前端把接入点锁死为 `https://api.openai.com/v1` | 公网外呼；OpenAI 兼容语音无法指向行内网关 |
| 媒体生成 / 联网搜索 | 媒体生成写死火山方舟；harness 默认 `web_search_tools="auto"`，`searchfree_search` 不需要任何密钥，每个 agent 都会装上 | 外呼公网搜索；UI 出现永远不可用的工具 |
| 云验证码 | Turnstile、hCaptcha、reCAPTCHA v2/v3、腾讯天御 5 个 provider，前端从公网加载脚本 | 登录页卡死或外呼 |

### 为什么做

1. 行内网完全断外网（全局约束开篇"目标"）。这些能力要么在行内不可达，要么会产生合规扫描必记的外联。
2. 全局约束 1.5"先删后改"：删完之后，`w3-01` 的验证码终态、`w3-05` 的凭据加密、`w3-04` 的会话改造都少一批要处理的对象。
3. `w2-01` 的全量出网静态门禁需要仓库里先没有这些公网域名。

### 范围内

1. **IM 通道**：Octop 自有 `ChannelKind`（默认只含 `mqtt`），在 API、Gateway 运行期、CLI 离线三处生效；删除 14 个扫码 / 一键建号端点、`infra/gateway/bot_creators/`、`infra/gateway/channels/`、`cli/support/feishu_creator.py`、CLI 的 `bind` 与 `feishu-setup`；前端通道页只剩 MQTT。
2. **SSO**：删除 3 个 App-ID 适配器、`/api/auth/oauth/callback` 及其 JWT 豁免；`/api/auth/oauth/*` 其余通用端点只接受 `oidc`；前端登录页、用户管理页、头像菜单同步收窄。
3. **连接器**：21 个 kind 登记进 `_FORK_REMOVED`；删除 12 个网关适配器、7 个 CLI 网关文件、`mail_servers.py`、6 个 CLI / 飞书用户授权端点、启动期 `ensure_cli_path`；删除 `builder.py` / `probe.py` / `service.py` / 路由里写死公网地址或绑定已删 kind 的分支；前端只呈现 WeKnora、Dify、自定义 MCP。
4. **模型**：预设改读 `infra/agents/providers/provider_presets.json`（默认只含本地 Ollama）；删除 Codex OAuth（后端目录 `infra/providers/`、3 个端点、前端组件）与 `opencode_session.py`。
5. **语音**：只保留 browser 与 OpenAI 兼容；OpenAI 兼容语音必须显式配置 `base_url`，前端可填写；删除 `edge-tts` 依赖与 `infra/utils/tencent_sign.py`。
6. **媒体生成与联网搜索**：删除后端模块、路由、工具目录项、设置页；agent 组装时显式关闭 harness 的联网搜索与媒体工具，并把 7 个工具名并入 `w1-02` 的强制禁用集；删除权限键 `search`。
7. **云验证码**：删除 5 个云 provider、`set_test_siteverify_url` 测试缝、前端公网脚本适配器；滑块保留。
8. **存量数据**：一条 fork 迁移清洗 `users.permissions` 中的 `search`、已删 kind 的通道 / 连接器 / 语音供应商行、三家 SSO 行的密钥、媒体生成 / 验证码 / Codex 残留设置。
9. **断网语义**：出站守卫抛出的 `UnsafeOutboundUrl` 冒泡到 HTTP 层时映射为 400 `OUTBOUND_URL_REJECTED`；新增断网冒烟集成测试。
10. **守卫与记录**：两条 fork 自有守卫测试（公网域名不回流、已删路由不回流）；`pyproject.toml` 去掉 `lark-oapi`、`edge-tts`，`dashboard/package.json` 去掉 `qrcode.react`，`make relock`；`CHANGELOG-intranet.md`、`docs/api-intranet.md`、`AGENTS.md` 三处失效引用。

### 范围外（归属）

| 事项 | 归属 |
|---|---|
| SSRF 内网白名单本身（四个放行点、配置三触点、注入） | `w0-05-ssrf-intranet-allowlist`（本 spec 只消费） |
| harness-gateway 重打包去掉 5 个 IM SDK（`dingtalk-stream`、`discord-py`、`lark-oapi`、`python-telegram-bot`、`wecom-aibot-sdk`）、harness-* 入行内 Git、全量出网静态门禁 | `w2-01-offline-build`（D13） |
| 行内大模型网关预设条目、进程级 CA 与代理 | `w2-04-intranet-model-gateway`（D2） |
| 验证码终态（服务端出题的本地图形验证码）、`CAPTCHA_SEAMS` 维护 | `w3-01-web-security-baseline`（D11） |
| 行内 IM 通道、行内 OA / 知识库 / 工单连接器 | `p2-06-intranet-integration`（D13） |
| CAS / SAML / LDAP 身份源 | `p2-11-identity-adapters`（D1） |
| 凭据加密、SSO / 连接器密钥的信封化 | `w3-05-credential-encryption` |
| 权限判定收口、三员分立 | `w3-03-authorization-foundation` |
| 控制台外链（`AvatarDropdown.tsx` 的 GitHub 链接、`assets/providers/index.ts` 的供应商文档链接与 logo） | `w4-01-frontend-baseline` |
| 专家库、subagent 库中提到飞书 / 钉钉 / 微信的内容文件 | `w1-04-content-trim` |
| `web_fetch` 工具 | `w1-02` 的 `forced_disabled_tools` 机制 / `w3-06`，本 spec 不处理 |
| 删除任何 i18n 键（源分析约 282 键 / 份作废）；改写上游 `docs/api.md`、`docs/cli.md`、`docs/configuration.md`、`README*`、`CHANGELOG.md` 正文 | 全局约束 1.2 与第 5 节禁止，任何 spec 都不做 |

## 需求

### 需求 1：通道类型收窄为 Octop 自有白名单

**用户故事：** 作为行内平台管理员，我希望系统只接受行方批准的通道类型，以便任何接口、命令或遗留数据都不能再建立公网 IM 连接。

#### 验收标准

1. 当 `POST /api/agents/{agent_id}/channels`、`PATCH /api/agents/{agent_id}/channels/{channel_id}` 或 `POST /api/agents/{agent_id}/channels/probe` 的请求体 `kind` 为 `feishu`、`dingtalk`、`qq`、`wecom`、`weixin`、`yuanbao`、`xiaoyi`、`telegram` 之一时，API 应当返回 422；`kind` 为 `mqtt` 时行为与基线相同。
2. `octop.infra.gateway.gateway.ChannelKind` 应当始终是 `octop.infra.gateway.channel_kinds.ChannelKind`（Octop 自有 `StrEnum`），其取值集合应当始终等于 `{"mqtt"}`；`src/octop/infra/gateway/gateway.py` 应当不再从 `harness_gateway.channels` 导入 `ChannelKind`。
3. 如果 `channels` 表中存在 kind 不在白名单内的行，那么 `Gateway` 在注册该通道时应当不调用 `ChannelManager.add_channel` 并把其运行态标为 `error`；对它发起探测时应当返回 `ok=false` 且不调用 `ChannelManager.probe_channel`。
4. 当执行 `octop channel create --kind feishu` 时，命令应当以非零退出码结束并提示不支持的通道类型，且不写入数据库；`octop channel --help` 应当不再列出 `bind` 与 `feishu-setup`。
5. 进程内的 dashboard 通道与 CLI 通道应当始终可用：`uv run pytest tests/unit/gateway/test_dashboard_ws.py tests/unit/gateway/test_cli_channel.py -q` 通过。

### 需求 2：删除扫码与一键建号

**用户故事：** 作为安全合规负责人，我希望服务端不再存在拉起浏览器、直连公网 IM 开放平台的接口，以便消除这一整类外联与子进程执行面。

#### 验收标准

1. 应用路由表与 `/api/openapi.json` 应当始终不含以下 14 个端点：`/api/agents/{agent_id}/channels/{dingtalk,wecom,qq,weixin}/qrcode/{generate,poll}`（8 个）与 `/api/agents/{agent_id}/channels/{feishu,yuanbao}/bot-creator/{start,poll,stop}`（6 个）。
2. 路径 `src/octop/infra/gateway/bot_creators/`、`src/octop/infra/gateway/channels/`、`src/octop/cli/support/feishu_creator.py` 应当始终不存在；`uv run python -c "import octop.infra.gateway.bot_creators"` 以 `ModuleNotFoundError` 失败。
3. 当管理员在控制台新建通道时，通道抽屉应当只提供 MQTT 表单，不渲染任何二维码；`dashboard/package.json` 应当不再依赖 `qrcode.react`。
4. 基线 `ChannelsPanel.test.tsx` 守护的"新建通道默认禁用"回归，在改用 MQTT 后应当仍然通过：`cd dashboard && npm run test -- src/pages/Agent/Channels` 通过。

### 需求 3：SSO 只保留通用 OIDC

**用户故事：** 作为行内平台管理员，我希望单点登录只剩可对接行内统一认证的通用 OIDC，以便登录链路不依赖任何公网 IdP，且不误伤唯一剩下的 SSO 登录方式。

#### 验收标准

1. `octop.infra.auth.sso.providers.base.SSO_KINDS` 应当始终等于 `("oidc",)`，`build_adapters(service)` 的键集应当始终等于 `{"oidc"}`。
2. 当请求 `PUT /api/auth/oauth/providers/feishu` 或 `POST /api/auth/oauth/start`（`kind="dingtalk"`）时，API 应当返回 422。
3. `GET /api/auth/oauth/status`、`POST /api/auth/oauth/start`、`POST /api/auth/oauth/exchange`、`POST /api/auth/oauth/bind/start`、`POST /api/auth/oauth/unbind`、`GET|PUT /api/auth/oauth/providers/oidc`、`POST /api/auth/oauth/providers/oidc/test` 与 `/api/auth/oidc/*` 应当始终保留；`uv run pytest tests/integration/test_auth_oidc.py tests/integration/test_auth_oauth.py -q` 通过。
4. 路由表应当始终不含 `/api/auth/oauth/callback`；`octop.api.deps.is_jwt_exempt_path("/api/auth/oauth/callback")` 应当为 `False`，`is_jwt_exempt_path("/api/auth/oidc/callback")` 应当仍为 `True`。
5. 如果 `sso_providers` 表中存在 kind 为 `feishu`、`dingtalk` 或 `wecom` 的行，那么 `GET /api/auth/oauth/status` 返回的 `providers` 的 kind 集合应当仍为 `{"oidc"}`。
6. 控制台登录页、用户管理页、头像菜单应当始终不引用 `assets/channels/{feishu,dingtalk,wecom}.svg`；用户管理页的标签只有"本地"与"OIDC"。

### 需求 4：连接器只保留 WeKnora、Dify 与自定义 MCP

**用户故事：** 作为行内平台管理员，我希望连接器目录只剩可以接入行内系统的样板，以便员工不会看到、也无法配置指向公网 SaaS 的连接器。

#### 验收标准

1. `GET /api/connectors/catalog` 返回的 kind 集合应当始终等于 `{"weknora", "dify"}`；`octop.infra.connectors.catalog_intranet._FORK_REMOVED` 应当恰为设计文档列出的 21 个 kind；`catalog.py` 中 `_BASE` 的 23 条上游条目应当一行不改。
2. `octop.infra.connectors.gateway.registry._ADAPTERS` 的键集应当始终等于 `{"weknora"}`；12 个已删适配器文件、7 个 CLI 网关文件与 `src/octop/infra/connectors/mail_servers.py` 应当不存在。
3. 路由表应当始终不含 `/api/connectors/{kind}/cli-status`、`/api/connectors/{kind}/install-cli`、`/api/connectors/feishu-cli/user-auth/start`、`/api/connectors/feishu-cli/user-auth/complete`、`/api/connector-instances/{instance_id}/feishu-user-auth/start`、`/api/connector-instances/{instance_id}/feishu-user-auth/complete`。
4. 当以被隐藏的 kind（如 `tencent-docs`）调用 `POST /api/connector-instances` 时，API 应当返回 400 与 `CONNECTOR_KIND_UNSUPPORTED`，且不写入数据库。
5. `OctopServer.start()` 应当始终不导入 `octop.infra.connectors.gateway.cli_install`，也不修改进程 `PATH`。
6. 在 `w0-05` 白名单包含 `10.0.0.0/8` 且允许 http 期间，以 `http://10.1.2.3:8080` 为 `base_url` 创建 WeKnora 实例应当成功，以 `http://10.1.2.3/mcp/server/abc/mcp` 为 `mcp_url` 创建 Dify 实例应当成功。
7. 控制台连接器页应当只呈现 WeKnora、Dify 与自定义 MCP；`dashboard/src/assets/connectors/` 应当只剩 `weknora.svg`、`dify.svg`、`index.ts`。

### 需求 5：模型预设自维护，删除 Codex OAuth 与 opencode 会话头

**用户故事：** 作为行内平台管理员，我希望模型供应商预设由本仓库维护，以便首次部署不出现公有云条目，harness 升级也不会把它们带回来。

#### 验收标准

1. `load_provider_presets()` 返回的 id 集合应当始终等于 `provider_presets.json` 中的 id 集合并上 `{"onnx"}`；其中不含 `openai-codex`；每个非空 `base_url` 的主机名都是 `localhost`、`127.0.0.1` 或 `::1`。
2. `load_provider_presets()` 应当始终以显式路径读取 `src/octop/infra/agents/providers/provider_presets.json`：在 `~/.harness-agent/providers_template.json` 存在期间，返回值应当不受其影响。
3. 路由表应当始终不含 `/api/admin/providers/codex-oauth/start`、`/api/admin/providers/codex-oauth/pending/{state_id}`、`/api/admin/providers/codex-oauth`；目录 `src/octop/infra/providers/` 与文件 `src/octop/infra/agents/providers/opencode_session.py` 应当不存在。
4. 当探测或列出任一供应商的模型时，请求头应当始终不含 `x-opencode-session`；`ProviderStore.build_harness_configs()` 产出的 `ProviderConfig.session_header` 应当为 `None`。
5. 控制台"预置供应商"弹窗应当始终不出现 ChatGPT 设备码登录。

### 需求 6：在线语音只保留 OpenAI 兼容

**用户故事：** 作为行内平台管理员，我希望语音识别与朗读只能走浏览器或指向行内网关的 OpenAI 兼容接口，以便语音数据不出行。

#### 验收标准

1. `{p["kind"] for p in load_voice_presets()}` 应当始终是 `{"browser", "openai"}` 的子集；`is_builtin_preset` 对 `edge`、`tencent`、`mimo` 返回 `False`。
2. `pyproject.toml` 应当不含 `edge-tts`；`src/octop/infra/utils/tencent_sign.py` 应当不存在；`rg -n "edge_tts|tencentcloudapi|xiaomimimo" src/octop/infra/voice` 没有输出。
3. 如果 OpenAI 兼容语音供应商没有配置 `base_url`，那么探测应当返回 `ok=false`，且不向任何地址发起 HTTP 请求。
4. 当管理员创建或修改语音供应商且 `kind` 不是 `openai` 时，`POST|PATCH /api/admin/voice/providers` 应当返回 400 与 `VOICE_KIND_UNSUPPORTED`。
5. 当管理员在控制台配置 OpenAI 兼容语音时，表单应当提供可编辑的"API 接入点"输入框，保存与探测提交的请求体应当携带填写的 `base_url`；未填写时前端提示并不提交。

### 需求 7：删除媒体生成与联网搜索

**用户故事：** 作为安全合规负责人，我希望 agent 不再具备调用公网搜索与公网生成服务的工具，以便对话数据不会经由工具调用外发。

#### 验收标准

1. 路由表应当始终不含 `/api/admin/media-generation`（GET、PUT）、`/api/admin/media-generation/test` 与 `/api/search/{provider_id}/test`。
2. `BUILTIN_TOOL_CATALOG` 的名字集合应当与 `{"tavily_search", "brave_search", "google_search", "kimi_search", "searchfree_search", "generate_image", "generate_video"}` 不相交，并且应当仍包含 `memory_search`。
3. `AgentManager._build_harness_config` 产出的 harness 配置应当始终满足 `web_search_tools is False` 且 `media_generation is None`；`forced_disabled_tools(config)` 应当始终包含上述 7 个工具名。
4. `octop.infra.utils.env_file` 应当不再导出 `SEARCH_ENV_KEYS` 与 `search_env_changed`；当 `PUT /api/envs` 写入任何键（含 `TAVILY_API_KEY`）时，应当不触发 `reload_all`，只调用 `invalidate_mcp_tool_cache`。
5. 控制台"模型"页应当只有"对话模型"与"语音"两个标签；如果地址栏带 `?tab=search` 或 `?tab=generation`，那么页面应当回落到"对话模型"。

### 需求 8：删除云验证码，滑块作为过渡

**用户故事：** 作为行内平台管理员，我希望登录验证码不依赖任何公网服务，以便在断网环境中登录页可用，并为 `w3-01` 的本地图形验证码留出干净的起点。

#### 验收标准

1. `octop.infra.auth.captcha.list_providers()` 应当始终等于 `["slider"]`；`get_provider` 对 `turnstile`、`hcaptcha`、`recaptcha`、`recaptcha-v3`、`tencent` 返回 `None`；`octop.infra.auth.captcha.verify` 应当不再有 `set_test_siteverify_url`。
2. 如果 `settings` 中 `captcha.settings` 的 `active` 是已删 provider，那么登录应当按滑块处理，不发起任何 HTTP 请求。
3. 如果环境变量 `OCTOP_CAPTCHA_PROVIDER` 设为已删 provider 且库中没有验证码设置，那么 `validate_boot` 应当抛 `ValueError`，实例启动失败。
4. 控制台登录页与验证码设置页应当始终不加载任何外部脚本：`dashboard/src/pages/Login/captchaAdapters.ts` 不含 `https://`。
5. 在 `tests/integration/test_captcha_api.py` 改写后，`w0-03` 的 `REAL_AUTH_GUARD_MODULES` 应当与文件保持一致：`uv run pytest tests/unit/api/test_auth_guard_exemptions.py -q` 通过。

### 需求 9：删除权限键 `search` 并同批清洗存量

**用户故事：** 作为用户管理员，我希望删除权限键之后仍能正常编辑任何老用户，以便裁剪不会造成"编辑老用户即 500"。

#### 验收标准

1. `"search"` 应当始终不在 `ALL_PERMISSION_KEYS` 中；`tests/unit/api/test_acl_gate_coverage.py` 的 `GATED_FILES` 不含 `routers/search.py` 且该测试通过。
2. 当 fork 迁移执行后，每个用户的 `users.permissions` 应当不含 `search`，其余键保持原顺序。
3. 如果某个老用户的 `permissions` 在迁移前含 `search`，那么迁移后管理员对该用户执行 `PATCH /api/users/{id}`（修改显示名或权限）应当返回 200。
4. `dashboard/src/utils/permissions.ts` 的 `modelsPage` 应当不再包含 `search`。

### 需求 10：清洗已删能力的存量数据

**用户故事：** 作为数据安全负责人，我希望已删能力留下的公网凭据与配置在升级时被清掉或失效，以便库里不再保存公网 SaaS 的密钥，界面也不会出现无法操作的残留条目。

#### 验收标准

1. 当 fork 迁移执行后，`channels` 中 kind 属于 8 个已删通道的行、`connectors` 中 kind 属于 21 个隐藏连接器的行、`voice_providers` 中 kind 为 `edge`、`tencent`、`mimo` 的行应当被删除；`settings` 中 `active_stt_provider` / `active_tts_provider` 如果指向不存在的供应商且不是 `browser` / `openai`，应当被改为 `browser`。
2. 当 fork 迁移执行后，`sso_providers` 中 kind 为 `feishu`、`dingtalk`、`wecom` 的行应当 `enabled = 0` 且 `client_secret_enc IS NULL`，行本身保留（`users.sso_provider_id` 外键指向它）。
3. 当 fork 迁移执行后，`settings` 中 `media_generation_enabled`、`media_generation_image_enabled`、`media_generation_video_enabled`、`media_generation_image_model`、`media_generation_video_model`、`captcha.settings` 与所有以 `codex_oauth.pending.` 开头的键应当不存在，`secrets` 中 `media_generation_credentials` 应当不存在。
4. 迁移应当始终幂等并对缺表跳过：对同一库连续执行两次结果相同；对缺少上述任一表的库执行不报错；SQLite 与 PostgreSQL 上的结果一致。
5. 迁移应当始终不改变 `_schema_version`：8 个测试文件中的 `v == 15` 类断言不变。

### 需求 11：断网启动与出站拒绝的错误语义

**用户故事：** 作为行内运维，我希望在没有公网 DNS 的环境里系统完整可用，出站地址被拒时得到明确的 4xx，以便排障时不被"整站 500"误导。

#### 验收标准

1. 在 `socket.getaddrinfo` 对任何主机名都抛 `socket.gaierror` 期间，`tests/integration/test_offline_boot.py` 应当走通 setup → 登录 → 创建 agent → WebSocket 对话一轮 → 创建定时任务 → 以主机名 `mcp_url` 探测 Dify 连接器，全程无 5xx、无超时。
2. 当出站守卫抛出的 `UnsafeOutboundUrl`（例如 `cannot resolve hostname`）冒泡到 HTTP 层时，API 应当返回 400 与错误码 `OUTBOUND_URL_REJECTED`，信封中不回显主机名；服务端以 WARNING 记录原因。
3. `ErrorCode.OUTBOUND_URL_REJECTED` 应当始终位于枚举末尾，`_DEFAULT_STATUS` 末尾登记为 400；后端 overlay `src/octop/i18n/intranet/{en,zh}.json` 的 `errors` 与 dashboard overlay `dashboard/src/locales/intranet/{en,zh}.json` 的 `apiErrors` 都有该码；`uv run pytest tests/unit/i18n -q` 通过。

### 需求 12：守卫、依赖与记录

**用户故事：** 作为 fork 维护者，我希望删除结果有机器守护、依赖与文档同步，以便上游同步时被删的公网能力不会悄悄回流。

#### 验收标准

1. `tests/unit/test_saas_tokens_removed.py` 应当始终断言设计文档列出的公网主机名不出现在 `src/octop/**/*.py` 与 `dashboard/src/**/*.{ts,tsx}` 中（`src/octop/infra/connectors/catalog.py` 与 `dashboard/src/assets/providers/index.ts` 除外）。
2. `tests/unit/api/test_saas_removed_routes.py` 应当始终断言本 spec 删除的 28 个端点既不在 `app.routes` 中，也不在 `/api/openapi.json` 的 `paths` 中。
3. `pyproject.toml` 应当不含 `lark-oapi` 与 `edge-tts`，并且应当仍含 `harness-gateway`、`orcakit-harness-agent[all]`、`segno`；`uv.lock` 与 `dashboard/package-lock.json` 由 `make relock` 重生成。
4. 本 spec 应当始终不修改 `CHANGELOG.md`、`docs/api.md`、`docs/cli.md`、`docs/configuration.md`、`README.md`、`README_CN.md` 与四份上游 i18n JSON：`git diff --stat w1-05-base -- CHANGELOG.md docs/api.md docs/cli.md docs/configuration.md README.md README_CN.md src/octop/i18n/en.json src/octop/i18n/zh.json dashboard/src/locales/en.json dashboard/src/locales/zh.json` 输出为空。
5. `CHANGELOG-intranet.md` 与 `docs/api-intranet.md` 应当记录本 spec 的删除、变更端点、权限差异、新错误码与连接器目录差异；`AGENTS.md` 应当不再引用 `bot_creators/`、channel QR bind 与 IM 平台语言提示。
6. `make all` 应当全绿；`cd dashboard && npx tsc -b && npm run lint && npm run test` 应当全绿。
