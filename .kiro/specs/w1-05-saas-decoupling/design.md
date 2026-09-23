# 设计文档：公网 SaaS 断开

> spec：`w1-05-saas-decoupling` ｜ 波次：Wave 1 ｜ 基线：`757fd12` ｜ 预估：24 人日
> 前置：`w0-01-fork-migration-namespace`、`w0-02-ci-gates`、`w0-03-test-auth-baseline`、`w0-04-fork-isolation-points`、`w0-05-ssrf-intranet-allowlist`、`w1-01-security-hotfix`、`w1-02-capability-trim` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 概述

**结论：** 七类公网 SaaS 能力一律物理删除实现与入口，只有连接器目录的"数据"走 `w0-04` 的 `_FORK_REMOVED` 隐藏（`_BASE` 一行不改）。删除之外只做四件补强，每件都是为了让"删干净"可验证、可持续：Octop 自有的 `ChannelKind` 白名单（API、Gateway 运行期、CLI 离线三处生效），一条清洗权限键与存量数据的 fork 迁移，`UnsafeOutboundUrl` 到 400 `OUTBOUND_URL_REJECTED` 的映射，两条防回流守卫测试。保留的四类出口（dashboard / cli / MQTT 通道、通用 OIDC、WeKnora / Dify / 自定义 MCP、OpenAI 兼容语音）在 `w0-05` 的白名单下可以指向行内。

| 领域 | 删除的文件 / 目录 | 修改的上游文件（主要） | 新增的 fork 自有文件 |
|---|---|---|---|
| IM 通道 | `infra/gateway/bot_creators/`、`infra/gateway/channels/`、`cli/support/feishu_creator.py`；前端 9 个通道图标 | `infra/gateway/gateway.py`、`api/routers/channels.py`、`cli/commands/channel.py`、`cli/support/offline_ops.py`、`cli/support/qr.py`、`infra/utils/locale.py`、`infra/gateway/process/response_mode.py`；前端 `Agent/Channels/*`、`api/modules/channel.ts` | `infra/gateway/channel_kinds.py` |
| SSO | `infra/auth/sso/providers/{feishu,dingtalk,wecom}.py`；前端 `Admin/Users/{oauthProviders.ts,OauthProviderCard.tsx,SsoAppProviderShell.tsx}` | `sso/providers/{__init__,base}.py`、`sso/public_base.py`、`sso/service.py`、`api/routers/auth_oauth.py`、`api/deps.py`、`api/openapi_meta.py`；前端 `Admin/Users/index.tsx`、`Login/index.tsx`、`components/AvatarDropdown.tsx`、`api/modules/sso.ts`、`utils/permissions.ts` | 无 |
| 连接器 | 12 个网关适配器、7 个 CLI 网关文件、`mail_servers.py`；前端 35 个品牌图片 | `connectors/gateway/registry.py`、`builder.py`、`probe.py`、`service.py`、`api/routers/connectors.py`、`infra/server.py`；前端 `Agent/Connectors/{index.tsx,connectorDefs.tsx}`、`assets/connectors/index.ts`、`api/modules/connectors.ts` | 无（`catalog_intranet.py` 由 `w0-04` 建，本 spec 填 `_FORK_REMOVED`） |
| 模型 | `infra/providers/`、`infra/agents/providers/opencode_session.py`；前端 `CodexOAuthConnect.tsx` | `agents/providers/{presets,probe,store}.py`、`api/routers/providers.py`；前端 `PresetProviderModal.tsx`、`providerApi.ts` | `agents/providers/provider_presets.json` |
| 语音 | `infra/utils/tencent_sign.py`（与验证码同批） | `infra/voice/{presets,adapters,manager}.py`、`i18n/domains/voice.py`、`api/routers/voice.py`；前端 `Settings/Voice/index.tsx` | 无 |
| 媒体 / 搜索 | `agents/media_generation.py`、`api/routers/{media_generation,search}.py`、`utils/search_probe.py`；前端 `Settings/{SearchConfig,MediaGeneration}/`、`api/modules/mediaGeneration.ts` | `agents/manager.py`、`agents/tool_catalog.py`、`utils/env_file.py`、`api/routers/envs.py`、`api/app.py`、`users/permissions.py`、`infra/capabilities.py`（`w1-02`）；前端 `Settings/Models/index.tsx`、`api/modules/provider.ts` | 无 |
| 云验证码 | 无整文件 | `auth/captcha/{providers,verify,__init__}.py`；前端 `Login/captchaAdapters.ts` | 无 |
| 横切 | — | `api/app.py`（1 行导入 + 1 行调用）、`infra/errors.py`、`infra/db/fork_migrate.py`（登记步骤）、`pyproject.toml`、`dashboard/package.json`、`AGENTS.md` | `infra/db/fork_saas_cleanup.py`、`migrations/forkNNN_saas_decoupling_cleanup{,.pg}.sql`、`api/intranet_exception_handlers.py`、两条守卫测试、断网冒烟测试 |

本 spec 新增 1 个 `ErrorCode`、删除 1 个权限键、1 条 fork 迁移，不新增配置键，不增删 i18n 键（新增文案只进 overlay），不改上游文档正文。

## 现状

以下事实均在基线 `757fd12` 上用 `rg` / `sed -n` / `wc -l` 核实。行号只作提示，实施时以路径 + 符号为准。

### IM 通道

- `ChannelKind` 定义在第三方包：`.venv/.../harness_gateway/channels/__init__.py` 的 `class ChannelKind(StrEnum)` 有 9 个取值（`feishu`、`dingtalk`、`qq`、`wecom`、`weixin`、`yuanbao`、`xiaoyi`、`mqtt`、`telegram`）。`harness_gateway-0.9.8.dist-info/METADATA` 的 `Requires-Dist` 含 `dingtalk-stream`、`discord-py`、`lark-oapi`、`python-telegram-bot`、`wecom-aibot-sdk` 五个 IM SDK 与通用传输层 `python-socketio[asyncio-client]`。
- `src/octop/infra/gateway/gateway.py`：≈L14 `from harness_gateway.channels import ChannelKind`；≈L26-30 从 `process.response_mode` 导入 `qq_channel_response_mode`（≈L29）；`__all__`（≈L47-53）再导出 `"ChannelKind"`；`ChannelCreateSpec.kind: ChannelKind | str`（≈L82）。`create_channel`（≈L304）、`update_channel`（≈L339）只把 kind 转字符串写库，不校验；`probe_channel`（≈L532）与 `probe_config`（≈L541）都走 `_probe_row`（≈L565），直接调 `ChannelManager.probe_channel(row.kind, …)`；`_format_probe_error`（≈L597）有飞书专属分支（≈L602-605）；`_safe_register_channel`（≈L623）吞异常并把运行态标为 `error`；`_register_channel`（≈L632）有全文件唯一的 `if row.kind == "qq"` 分支（≈L636-640），其余把 `row.kind` 原样交给 `manager.add_channel`。**结论：库里残留的 `feishu` 行会在启动时被 harness-gateway 建连。**
- `src/octop/api/routers/channels.py`（1071 行）：≈L25-26 导入 `bot_creators.feishu_runner` 与 `gateway.channels.{dingtalk_registration,qr_bind}`；≈L27 `from octop.infra.gateway.gateway import ChannelKind`；`ChannelCreateBody.kind`（≈L37）、`ChannelPatchBody.kind`（≈L43）、`ChannelProbeBody.kind`（≈L50）用 `ChannelKind`；≈L54-75 是 bot creator 请求体与 `_parse_bot_creator_body`。≈L263 起是 `# ─── QR scan helpers ───` 段，直到文件末尾：`_resolve_profiles_root`（≈L336）、`_pkill_chrome_profile`（≈L387）等辅助函数，以及 14 个端点——dingtalk `qrcode/generate`（≈L454）/`poll`（≈L496）、wecom（≈L599/617）、qq（≈L640/661）、weixin（≈L700/726）、feishu `bot-creator/start|poll|stop`（≈L781/837/891）、yuanbao（≈L929/986/1051）。≈L5-17 的 `asyncio`、`os`、`platform`、`re`、`secrets`、`subprocess`、`sys`、`time`、`dataclass`、`_FsPath`、`Literal` 与 ≈L29 的 `parse_subprocess_json_lines` 只被这一段使用。
- `infra/gateway/channels/` 含 `__init__.py`（1 行 docstring）、`dingtalk_registration.py`（57 行，`oapi.dingtalk.com`）、`qr_bind.py`（136 行，`work.weixin.qq.com`）；`infra/gateway/bot_creators/` 含 `__init__.py`、`feishu_bot_creator.py`（369 行，≈L34 `import lark_oapi as lark`）、`feishu_runner.py`（123 行）、`yuanbao_bot_creator.py`（481 行）。
- `src/octop/cli/commands/channel.py`（571 行）：`bind` 组（≈L207）与 `bind qq`（≈L212）、`bind wecom`（≈L285）、`bind weixin`（≈L344，含 `https://ilink.b.qq.com` ≈L382）；`config` 命令（≈L411）的 kind 列表（≈L423）、QR / 飞书分支（≈L439-463）、QQ 专属表单（≈L464-486）；`feishu-setup`（≈L509）经 `cli/support/feishu_creator.py`（73 行）调用 bot creator。`channel create`（≈L95）调 `cli/support/offline_ops.py::create_channel_offline`（≈L430），后者直接 `channel_repo.create`，**不校验 kind**。`cli/support/qr.py` 的 `render_qrcode_terminal`（≈L116）只被 `bind *` 与 `feishu_creator.py` 使用；`mask_secret`（≈L13）被 `channel get`（≈L76）使用。
- `src/octop/infra/utils/locale.py` ≈L38-41：`im_zh` 集合与 `telegram` 分支。`src/octop/infra/gateway/process/response_mode.py`：`_config_flag`（≈L31）只被 `qq_channel_response_mode`（≈L39）使用，后者在 `__all__`（≈L135）导出，唯一调用方是 `gateway.py`。
- `dashboard` / `cli` 两个进程内通道不走 `ChannelKind`：`infra/gateway/ws/` 与 `infra/gateway/cli/` 继承 `harness_gateway.channel.BaseChannel`，所以 `harness-gateway` 必须保留。
- `infra/utils/browser_media.py::octop_browser_profiles_dir`（≈L84）除 `channels.py::_resolve_profiles_root` 外还被 `agents/manager.py::_agent_runtime_bundle`（≈L2568-2579）使用；`configure_browser_idle_timeout`（≈L132）由 `infra/server.py`（≈L367-371）按 `browser_idle_timeout_minutes` 调用，作用对象是 harness-browser，与 IM 通道无关。
- 前端：`dashboard/src/pages/Agent/Channels/components/constants.ts`（450 行）从 `assets/channels/` 导入 13 个图标（≈L1-13），`ChannelKey` 联合类型（≈L19）、`CHANNEL_KEYS`（≈L38）、`isCollapsedChannelKey`（≈L53）、`partitionChannelKeys`（≈L61）、`CHANNEL_LABEL_KEYS`（≈L78）、`CHANNEL_LABELS`（≈L95）、`CHANNEL_ICONS`（≈L111）、`CHANNEL_COLORS`（≈L128）、`CHANNEL_URLS`（≈L152，含 `open.feishu.cn`、`q.qq.com`、`yuanbao.tencent.com`）、QQ 群上下文全套（≈L177-270）、`CHANNEL_FIELDS`（≈L273）、`applyQqChannelSaveConfig`（≈L408）、`normalizeChannelFieldValue`（≈L421）、`REQUIRED_CREDENTIALS`（≈L430）、`hasRequiredCredentials`（≈L439）。barrel `components/index.ts`（32 行）从 `./constants` 再导出 18 个值与 2 个类型，其中 6 个值将被删除。`ChannelDrawer.tsx`（1890 行）≈L19 导入 `qrcode.react`，`QqGroupContextPolicyFields`（≈L255），默认 kind `?? "feishu"`（≈L491），`render{Qq,Wecom,Weixin,Dingtalk,Feishu,Yuanbao}Panel`（≈L1218-1627）与分派（≈L1794-1799），`normalizeChannelFieldValue` 调用（≈L184、≈L1151），`applyQqChannelSaveConfig` 调用（≈L935、≈L1175）。`ChannelsPanel.tsx`（492 行）≈L19-25 导入上述 helper、≈L62/82 调用、≈L142 `partitionChannelKeys`。`api/modules/channel.ts`（268 行）≈L95 起 14 个扫码 / bot creator 方法。`package.json` ≈L38 `qrcode.react`，只有 `ChannelDrawer.tsx` 使用。
- `Chat/components/SessionChannelIcon.tsx` 已用 `isChannelKey` 回落到 `CHANNEL_ICONS.octopbot`；`Control/CronJobs/components/{CronJobCard.tsx ≈L56/97, columns.tsx ≈L62/79}` 对查表结果做了 `icon ?` 判空。**三者对未知 kind 已经容错，不需要改。**
- `assets/channels/` 共 13 个文件；`feishu.svg`、`dingtalk.svg`、`wecom.svg` 还被 `Login/index.tsx`（≈L20-22）、`Admin/Users/index.tsx`（≈L15-17）、`components/AvatarDropdown.tsx`（≈L48-50）导入。

### SSO

- `infra/auth/sso/providers/base.py` ≈L9 `SSO_KINDS = ("oidc", "feishu", "dingtalk", "wecom")`，≈L10 `DEFAULT_OAUTH_CALLBACK_PATH`（全仓零引用）；`providers/__init__.py::build_adapters`（≈L13-24）；三个适配器 `feishu.py`（159 行）、`dingtalk.py`（138 行）、`wecom.py`（182 行）的 `callback_path = oauth_callback_path()`，而 `oidc.py` ≈L20 用 `oidc_callback_path()`。`public_base.py` ≈L8 `_OAUTH_CALLBACK_PATH`、≈L21-22 `oauth_callback_path()`，只被三个适配器使用。
- `infra/auth/sso/service.py`（496 行）：`providers_status`（≈L70）按 `SSO_KINDS` 遍历，库里多余的行不会返回；`put_config_for_kind`（≈L140）有三家专属分支（≈L159-181）；`handle_callback`（≈L255）对未知 kind 的 `_adapter` 抛 `ValueError` 后重定向为 `misconfigured`。
- `api/routers/auth_oauth.py`：`SsoKind = Literal["oidc", "feishu", "dingtalk", "wecom"]`（≈L28），被 `OauthStartBody`、`OauthUnbindBody` 与三个 `providers/{kind}` 路由使用；`/oauth/callback`（≈L101-127，接受 `code` 与钉钉的 `authCode`）只服务三家（OIDC 的 IdP 回跳到 `auth_oidc.py` ≈L114 的 `/oidc/callback`）。`/oauth/status`（≈L67）、`/oauth/start`（≈L73）、`/oauth/exchange`（≈L129）、`/oauth/bind/start`（≈L137）、`/oauth/unbind`（≈L171）、`/oauth/providers/{kind}`（≈L184/197）、`/oauth/providers/{kind}/test`（≈L221）是通用的。
- `api/deps.py` `_JWT_EXEMPT_EXACT`（≈L73-89）≈L83 含 `"/api/auth/oauth/callback"`；`api/openapi_meta.py` 公开端点说明（≈L30-35）≈L33 列出该路径。
- 表结构：`users.sso_provider_id INTEGER REFERENCES sso_providers(id)`（`migrations/005_shared_experts_sso_knowledge.sql` ≈L64，无 `ON DELETE`）；`user_sso_identities.provider_id … ON DELETE CASCADE`（`015_sso_provider_kind.sql` ≈L11）。
- 测试：`tests/integration/test_auth_oauth.py`（124 行）三个用例都用三家 kind，其中 `test_oauth_callback_accepts_dingtalk_auth_code`（≈L92）直测被删路由；`tests/unit/api/test_jwt_auth_middleware.py` ≈L35 断言回调豁免；`tests/unit/auth/test_public_base.py` ≈L48 只把字面量路径传给 `build_redirect_uri`，**不导入 `oauth_callback_path`，删除后无需改动**；`tests/unit/auth/test_sso_service.py` ≈L362 `test_oidc_status_ignores_feishu_row` 直接写库，正好守护"残留行被忽略"，保留。
- 前端：`Admin/Users/index.tsx`（139 行）有三家标签、`OAUTH_BRAND_ICONS`（≈L23）、`OauthTabPanel`（≈L77）；`Login/index.tsx` ≈L38-54 按 kind 选图标；`components/AvatarDropdown.tsx` ≈L54 `APP_OAUTH_KINDS = new Set(["feishu", "dingtalk", "wecom"])` 决定账号绑定列表（≈L181-210）与渲染（≈L585-620）——**基线上 OIDC 本来就不在该列表里**；`api/modules/sso.ts` ≈L84-95 三个 `@deprecated` 飞书包装；`utils/permissions.ts` ≈L51-57 `USERS_TAB_PERMISSIONS` 含三家。`SsoPanel.tsx`、`SsoProviderCard.tsx` 是纯 OIDC。

### 连接器

- `infra/connectors/catalog.py` `_CATALOG`（≈L96）23 条：删除集 21 条的 kind 在 ≈L98-448，`weknora`（≈L463，`mcp_mode="gateway"`、`auth_kind="custom_fields"`）与 `dify`（≈L508，`remote` + `streamable_http` + `custom_fields`）保留。`w0-04` 把它改名为 `_BASE` 并以 `compose_catalog(_BASE)` 合成 `_CATALOG`。
- `gateway/registry.py` ≈L7-22 导入 13 个适配器，`_ADAPTERS`（≈L32-46）13 项；`gateway/adapters/__init__.py` 只有 docstring，无导出列表要改。7 个 CLI 网关文件：`cli_dirs.py`、`cli_fingerprint.py`、`cli_install.py`、`cli_runner.py`、`feishu_creds.py`（`open.feishu.cn`）、`feishu_user_auth.py`、`wecom_creds.py`（`qyapi.weixin.qq.com`）。`infra/server.py::start` ≈L284-288 导入 `cli_install.ensure_cli_path` 并改写 `PATH`。
- `builder.py`（620 行）：≈L17 导入 `mail_servers`；≈L23 `DIDI_MCP_BASE_URL`；≈L30 `normalize_weiyun_mcp_token`；`_build_remote_spec`（≈L90）中 didi / tencent-docs / tencent-weiyun / tencent-meeting / tencent-lexiang / youdao-note 分支写死公网地址，`is_mcp_oauth_remote` 分支是通用的；`validate_create_credentials`（≈L212）中 `api_key` 分派含 feishu-cli / wecom-cli / wechat-reading / qq-music / yuandian / didi / tencent-ima / tencent-lexiang 子分支，`imap_app_password` 分支调 `resolve_mail_servers`，`session_cookie` 分支含 tencent-ima 子分支；`inject_missing_gateway_tools` 末尾按 `tencent-ima__` 归并日志。`_iter_active_connectors`（≈L452）与 `service.mcp_configs_for_user`（≈L465）在 `get_catalog_entry(inst.kind) is None` 时跳过实例。
- `probe.py`：`prepare_probe_credentials`（≈L102）的 tencent-weiyun / youdao-note 分支；`_probe_mcp_http_error` / `_probe_mcp_mcp_error` 的 youdao 分支；`_probe_mcp_sse`（≈L224）只被 `probe_youdao_note`（≈L286）使用；`_probe_youdao_note_http_error`（≈L295）；`_REMOTE_STATIC_TOOL_KINDS = frozenset({"tencent-weiyun"})`（≈L326）；`probe_connector` 的 youdao 分支。`detect_local_weknora`（≈L35）只访问环回，保留。
- `service.py`：≈L35-39 导入 `cli_dirs.resolve_cli_config_key` 与 `feishu_user_auth`；≈L503-630 六个飞书 CLI 用户授权成员。
- `api/routers/connectors.py`（1401 行）：≈L19-23 导入 `normalize_weiyun_mcp_token`；≈L40-46 导入 `cli_dirs`、`cli_install`、`feishu_user_auth`；`_prepare_credentials`（≈L295）的 tencent-weiyun 分支（≈L315-320）；`_credentials_preview`（≈L339）中 tencent-news / tencent-ima / feishu-cli / wecom-cli / tencent-lexiang / tencent-weiyun 子分支；`get_instance` ≈L654-656 的 feishu-cli 在线预览；`delete_instance` ≈L893-902 的 CLI 目录清理；6 个端点 `cli-status`（≈L992）、`install-cli`（≈L1013）、`feishu-cli/user-auth/{start,complete}`（≈L1034/1061）、`connector-instances/{id}/feishu-user-auth/{start,complete}`（≈L1093/1114）。`/connectors/auth/{kind}/{info,authorize-url,exchange-code}`（≈L1160-1216）与 `/connectors/oauth/*` 是按目录判定的通用端点，不含公网地址。
- `oauth/mcp.py::issuer_for_kind`（≈L30）与 `oauth/registry.py::oauth_target_requires_https`（≈L238）都查 `get_mcp_oauth_remote`，因此 `tests/unit/connectors/test_mcp_oauth_ssrf.py`（≈L19 起 4 处 `issuer_for_kind("notion")`）与 `test_oauth_discovery.py`（≈L49-53）依赖目录里有 `notion`。
- 测试：`tests/unit/connectors/` 12 个文件中 8 个专测已删连接器；`tests/unit/test_connectors.py`（1423 行、80 个用例）与 `tests/integration/test_connectors_api.py`（667 行）大量用已删 kind；另有 `test_experts_api.py`、`test_published_experts.py`、`agents/test_mcp_tool_cache.py`、`agents/test_agent_manager.py`、`connectors/test_custom_mcp.py`、`connectors/test_default_open.py` 用 `tencent-docs` / `qq-mail` / `tencent-ima` 作夹具。
- 前端：`Agent/Connectors/index.tsx`（2340 行）≈L50-53 导入邮箱与引导 helper，≈L392/514/544 调 `cliStatus` / `installCli`，≈L578-703 飞书用户授权流程；`connectorDefs.tsx` `MAIL_PROVIDERS`（≈L7）、`MailProviderId`（≈L34）、`INLINE_CREDENTIAL_GUIDE_KINDS`（≈L37）、`HIDE_INLINE_FIELD_GUIDE_KINDS`（≈L40）、`mailProviderById`（≈L51）；`assets/connectors/index.ts` 23 条导入与 `CONNECTOR_LOGOS`（≈L25）；目录共 38 个条目；`api/modules/connectors.ts` ≈L304-360 六个 CLI / 飞书方法与 ≈L158-190 对应类型。

### 模型预设、Codex OAuth、opencode

- `infra/agents/providers/presets.py`（279 行）`load_provider_presets`（≈L214）：≈L218-220 从 `harness_agent.providers` 包内 `provider_template.json` 读取（实测 39 条、256 个 model，只有 `ollama` 指向 `http://localhost:11434/v1`）；≈L222-244 注入 `openai-codex`（`https://chatgpt.com/backend-api/codex`）；≈L245-273 注入 `onnx`，插在 `ollama` 之后；`_reasoning_profile`（≈L8）按供应商 id 前缀补推理元数据，≈L172 的 `opencode-` 只是前缀分支，**不是 `opencode_session` 的调用点**。harness 的 `load_provider_templates(path)` 传显式路径时不回落用户目录与包内文件。
- `opencode_session.py`（64 行）的生产调用点只有两个文件：`agents/providers/store.py`（≈L12-15 导入，≈L163-165 `session_header=`）与 `agents/providers/probe.py`（≈L15 导入，≈L49、≈L168、≈L274 三处 `ensure_opencode_session_header`）。harness `ProviderConfig.session_header` 默认 `None`。
- `src/octop/infra/providers/` 只有 `codex_oauth.py`（284 行，`auth.openai.com`，令牌存 `~/.octop/codex_oauth.json`）与 `codex_apply.py`（67 行），无 `__init__.py`。`api/routers/providers.py`：≈L27-35 导入，`_is_codex_base_url` / `_maybe_refresh_codex_row`（≈L100-118），`_run_codex_device_poll`（≈L352），三个端点（≈L401、≈L429、≈L448），≈L477 调用。`agents/providers/probe.py` ≈L38-39 与 ≈L56 的 codex 分支。
- 前端：`Settings/Models/components/CodexOAuthConnect.tsx`（140 行）；`components/modals/PresetProviderModal.tsx` ≈L19 导入、≈L50 `isCodexOAuth` 与 6 处分支；`Settings/Models/providerApi.ts` ≈L68 `startCodexOAuth`、≈L76 `pollCodexOAuth`。`Settings/Models/presetUtils.ts` ≈L131 的 `"openai-codex"` 只是字符串集合成员，无害，不改。

### 语音

- `infra/voice/presets.py` ≈L9 `_BUILTIN_PRESET_IDS = frozenset({"browser", "edge", "tencent", "openai", "mimo"})`，`load_voice_presets` 返回 browser / edge / tencent / openai / mimo-stt / mimo-tts 六条。
- `infra/voice/adapters.py`（571 行）：≈L19 导入 `tencent_api_language`，≈L26 模块级导入 `tencent_sign.tc3_headers`；`_parse_tencent_credentials`（≈L41）、`_voice_format`（≈L54，只被腾讯 ASR 使用）、`transcribe_tencent` / `synthesize_tencent`（≈L159/205）、`synthesize_edge`（≈L252，≈L259 `import edge_tts`）、`_guard_mimo_base_url`（≈L271）、`_normalize_mimo_voice`、`_mimo_audio_mime`、`transcribe_mimo` / `synthesize_mimo`（≈L336/390）。**`_wav_header`（≈L283）虽在小米段落里，但被通用的 `_probe_tone_wav`（≈L466-473）使用，必须保留。** `transcribe_openai` / `synthesize_openai` 在 `base_url` 为空时回落 `https://api.openai.com/v1`（≈L100、≈L132）。`test_stt` / `test_tts`（≈L498/528）按 kind 分派。
- `infra/voice/manager.py`（222 行）：`_validate_provider_name` 的 edge 分支、`media_type` 的 mimo 分支、`transcribe` / `synthesize` 的 tencent / mimo / edge 分支。
- `infra/utils/tencent_sign.py`（60 行）只有两个使用方：`voice/adapters.py` ≈L26 与 `auth/captcha/providers.py` ≈L42，**两者都由本 spec 删除**。
- `i18n/domains/voice.py`：`tencent_api_language`（≈L9）、`voice_credentials_error` 的腾讯分支（≈L21-22）、`format_voice_probe_error` 的 `voice.tencent.{code}` 查表（≈L36-37）。
- `api/routers/voice.py` 的 `VoiceProviderCreateBody.kind`（≈L45）、`VoiceProviderPatchBody.kind`（≈L54）是任意字符串，不校验。
- 前端 `Settings/Voice/index.tsx`（500 行）：≈L113-131 按 kind 组装请求体，OpenAI 分支 `base_url` 固定为 `null`；≈L424-446 OpenAI 表单的"API 接入点"是 `disabled` 的 `Select`，唯一选项 `https://api.openai.com/v1`。**所以基线上 OpenAI 兼容语音无法经控制台指向行内网关。**

### 媒体生成与联网搜索

- `infra/agents/media_generation.py`（308 行）写死 `ark.cn-beijing.volces.com`，settings 键 `media_generation_{enabled,image_enabled,video_enabled,image_model,video_model}`，密钥 `media_generation_credentials`。`agents/manager.py` ≈L25-27 导入、≈L364（`__init__`）与 ≈L398（`replace_persistence`）构造、≈L486-487 属性、≈L1636-1660 `save_media_generation`、≈L2944 `media_generation=self._media_generation.harness_config()`。harness `agent.py` ≈L1348 只在 `cfg.media_generation` 非空且有密钥时装配媒体工具。
- `api/routers/media_generation.py`（145 行）三个端点：`GET`、`PUT` `""` 与 `POST /test`，挂在 `/api/admin/media-generation`；`api/routers/search.py`（52 行）`POST /search/{provider_id}/test`（`require_permission("search")`）；`infra/utils/search_probe.py`（221 行）。`api/app.py`：≈L168 与 ≈L178 导入，≈L227 与 ≈L235-239 两条 `_RouterMount`。`api/openapi_meta.py` ≈L106 有 `search` tag。
- harness `HarnessAgentConfig.web_search_tools` 默认 `"auto"`（`harness_agent/config/__init__.py` ≈L547），`agent.py` ≈L1345 调 `load_web_search_tools(cfg.web_search_tools)`；`web_search/_registry.py` ≈L77-79 注明 `searchfree` 不需要任何环境变量。Octop 从不传 `web_search_tools`（`rg` 在 `src/octop` 只命中 `tool_catalog.py`）。**结论：基线上每个 agent 都会装上外呼公网的 `searchfree_search`。**
- `agents/tool_catalog.py`：`_WEB_SEARCH_TOOLS`（≈L22-30）、`_MEDIA_TOOLS`（≈L31）、目录项（≈L72-78）、`builtin_tool_available`（≈L185）中两段判定（≈L199-205）。
- `infra/utils/env_file.py` ≈L24 `SEARCH_ENV_KEYS`、≈L106 `search_env_changed`；唯一生产调用点是 `api/routers/envs.py` ≈L20 导入与 `_after_env_sync`（≈L48）中 ≈L57 的判定，语义是"搜索键变化才后台 `reload_all`"。
- `infra/users/permissions.py` ≈L144-152 `"search"` 权限键；`tests/unit/users/test_permissions.py` ≈L72 断言它存在；`tests/unit/api/test_acl_gate_coverage.py` 的 `GATED_FILES` 含 `"routers/search.py"`（基线 ≈L26，`w1-03` 删条目后会上移）；`dashboard/src/utils/permissions.ts` ≈L24 `modelsPage` 含 `"search"`。
- 前端：`Settings/Models/index.tsx`（427 行）≈L45/47 导入两个面板，≈L49 `ModelCategory`，≈L51 `resolveModelCategory`（源分析称 `resolveTab`，实为此函数），≈L80 `canSearch`，≈L105 tab 白名单，≈L273-320 标签与渲染；`api/modules/provider.ts` ≈L112 `testSearch`；`Agent/Tools/ToolsPanel.tsx` ≈L101-106 的图标映射是 `Record<string, …>`，孤儿条目无害，不改。

### 云验证码

- `infra/auth/captcha/providers.py`（354 行）：`_form_call`、`_FormPostProvider`、`_RecaptchaV3Provider`（≈L160，`www.google.com/recaptcha`）、`_TencentProvider`（≈L192，`captcha.tencentcloudapi.com`，用 `tc3_headers`）、`_TURNSTILE`（≈L287）、`_HCAPTCHA`、`_RECAPTCHA`、`_register_builtins`（≈L345）与末尾类型检查变量。`_SliderProvider`（≈L105，`requires_token=False`）与注册表函数是通用的。
- `verify.py` ≈L24 `set_test_siteverify_url` 与 `_TEST_URLS`（测试缝，`captcha/__init__.py` ≈L27、≈L48 再导出）；`ensure_captcha` 在 provider 不要求 token 时直接返回。
- `store.py` 对未注册的 `active` 记 WARNING 并回落滑块（≈L166-172、≈L177-180）；`config.py::validate_boot`（≈L66）对未知的 `OCTOP_CAPTCHA_PROVIDER` 抛 `ValueError`。设置键为 `captcha.settings`（`store.py` ≈L19）。
- 前端 `Login/captchaAdapters.ts`（75 行）`CAPTCHA_WIDGETS` 除 `slider` 外 5 项都从公网加载脚本（≈L25-60）；`CaptchaField.tsx` 与 `CaptchaSettings.tsx` 按后端 `available` 与适配器表工作，适配器只剩 `slider` 时自然只走滑块分支。
- 测试：`tests/unit/auth/test_captcha_{providers,verify,store,env}.py`、`tests/integration/test_captcha_api.py`（350 行，turnstile 与腾讯用例）、`tests/unit/cli/test_captcha_cmd.py`、`dashboard/src/pages/Login/CaptchaField.test.tsx`。

### 出站守卫的错误语义

- `infra/utils/ssrf_guard.py` ≈L16 `class UnsafeOutboundUrl(ValueError)`；`_resolve_validated_ip` 在 `socket.gaierror` 时抛 `cannot resolve hostname …`（≈L104/106）。
- `api/app.py::_install_exception_handlers`（≈L77-98）只有 `OctopError` 与兜底 `Exception` 两个处理器，后者返回 500 `INTERNAL_ERROR`。
- 连接器探测把 `UnsafeOutboundUrl` 转成 `ok=false`（`probe.py` ≈L435），但语音 `POST /api/voice/stt|tts`（`api/routers/voice.py` ≈L113/134）经 `_guard_voice_base_url` 抛出的 `UnsafeOutboundUrl` 不被捕获，表现为 500。

### 依赖与文档

- `pyproject.toml`：≈L24 `orcakit-harness-agent[all]`、≈L26 `lark-oapi`、≈L27 `harness-gateway`、≈L30 `edge-tts`、≈L31 `segno`（`cli/support/qr.py` 与内置插件 `plugins/bundled/qrcode/main.py` 使用，保留）；hatch 打包包含 `src/octop/**/*.json`。
- `lark-oapi` 在 `src/octop` 的唯一使用点是 `feishu_bot_creator.py`，测试侧唯一使用点是 `tests/unit/gateway/test_feishu_bot_creator.py`；`edge-tts` 唯一使用点是 `voice/adapters.py`。
- `AGENTS.md` ≈L115 `bot setup (bot_creators/)`、≈L163 `channel QR bind (WeCom/WeChat), Feishu bot-creator subprocess`、≈L275 `IM platforms default zh, telegram → en` 会因本 spec 失效。

### 源分析中被推翻或修正的结论

| 源分析结论 | 核实结果 | 本设计的处理 |
|---|---|---|
| 13 个适配器全删 | `weknora` 是 gateway 模式，必须保留其适配器 | 删 12 个 |
| `AuthKind` 收窄为 `custom_fields`、`ConnectorCategory` 收窄 | `_BASE` 按 `w0-04` 不改，仍引用这些取值，收窄会让 mypy 失败 | 两个类型都不收窄 |
| `tencent_sign.py` 不能删 | 两个使用方（腾讯语音、腾讯验证码）都由本 spec 删除 | 随最后一个使用方删除 |
| 删小米段落含 `_wav_header` | `_probe_tone_wav` 使用它 | 保留 `_wav_header` |
| `test_public_base.py:48` 会 `ImportError` | 该用例只传字面量 | 不改 |
| `SessionChannelIcon.tsx`、CronJobs 两个卡片需改 | 已容错 | 不改 |
| `docs/api.md`、`docs/cli.md`、`docs/configuration.md`、README 按行改写 | 全局约束第 5 节 | 只写 fork 文档 |
| 删约 282 键 / 份 i18n | 全局约束 1.2 | 不删；新增文案进 overlay |
| 43 个测试文件的 IM 字面量都要替换 | 多数只是 `channel_type` 之类的不透明字符串，不经白名单 | 只改实际失败的用例 |
| `opencode_session.py` 三个调用点含 `presets.py` | `presets.py:172` 只是 id 前缀分支 | 调用点是 `store.py` 与 `probe.py`（3 处） |
| 语音只需删三家 | 控制台把 OpenAI 接入点锁死为公网 | 放开 `base_url` 输入、后端要求显式 `base_url` |
| 删目录项即可去掉搜索工具 | harness 默认 `"auto"` 且 `searchfree` 恒可用 | 显式传 `web_search_tools=False`，并入强制禁用集 |
| 用户页之外没有三家 SSO 前端入口 | `AvatarDropdown.tsx` 的账号绑定只认三家 | 删除绑定列表与图标 |

## 方案

### 删除原则

1. **只服务已删能力的模块整文件删除**：见概述表。
2. **共享上游文件里只删四类东西**：对已删模块的导入与调用；以已删 kind 为键的分支；写死公网地址的常量与分支；只服务已删能力、或删除后恒失败的 HTTP / CLI 入口。
3. **与 kind 无关、不含公网地址的通用机制保留**：`validate_create_credentials` 的 `personal_token` / `oauth2` / `auth_code` / `api_key` / `api_credentials` 通用分派、`_build_remote_spec` 的 `is_mcp_oauth_remote` 分支、`oauth/registry.py` 全部、`/connectors/auth/{kind}/*` 与 `/connectors/oauth/*` 端点。它们对被隐藏的 kind 返回 400，保留可以缩小与上游的差异（`auth_code`、`session_cookie`、`api_credentials` 在基线目录里本就无条目使用，是既有死路径，不在本 spec 清理）。
4. **目录数据走隔离点**：连接器目录只填 `w0-04` 的 `_FORK_REMOVED`；前端图片、表单分支按"已删 kind"删除。
5. **运行期闸门与存量清洗双保险**：API 枚举挡新请求，Gateway 注册 / 探测与 CLI 离线挡残留与旁路，fork 迁移清掉残留数据。
6. **不删 i18n 键、不改上游文档正文**；新增文案进 overlay（全局约束 1.2、第 5 节）。
7. **热点文件只做删除与单行改动**：`agents/manager.py` 只删媒体生成接线并加 1 行 `web_search_tools=False`；`gateway.py` 只改 1 行导入、删 qq 与飞书分支、加 3 处单行闸门调用。

### IM 通道

- 新增 fork 自有模块 `infra/gateway/channel_kinds.py`，定义 Octop 自有 `ChannelKind`（只含 `MQTT = "mqtt"`）、`SUPPORTED_CHANNEL_KINDS` 与 `ensure_supported_channel_kind(kind)`（不在白名单抛 `OctopError(ErrorCode.CHANNEL_KIND_UNSUPPORTED)`，该码已登记 400）。`gateway.py` ≈L14 改为从它导入，`__all__` 继续再导出，所以 `api/routers/channels.py` ≈L27 的导入不用改，三个请求体自动收窄为 422。
- `Gateway` 三处单行闸门：`create_channel` 与 `update_channel`（传入 kind 时）开头调用 `ensure_supported_channel_kind`；`_register_channel` 开头调用（异常由 `_safe_register_channel` 转成运行态 `error`）；`_probe_row` 开头判定不支持时返回 `{"ok": False, "error": tr("errors.CHANNEL_KIND_UNSUPPORTED", locale)}`，不调 `ChannelManager`。删除 qq 分支（统一走 `normalize_channel_response_mode`）与 `_format_probe_error` 的飞书分支。
- `channels.py` 删除 ≈L25-26 两行导入、≈L54-75 的请求体与解析函数、≈L263 到文件末尾的整段，以及只被这些代码使用的标准库导入。`_resolve_profiles_root` 随之删除；`browser_media.py` 的函数与配置键 `browser_idle_timeout_minutes` 仍被 `manager.py` / `server.py` 用于 harness-browser，**保留**（这是 `w1-02` 交接项的评估结论）。
- CLI：删除 `bind` 组与三个子命令、`feishu-setup`、`cli/support/feishu_creator.py`；`config` 命令的 kind 列表改为 `sorted(SUPPORTED_CHANNEL_KINDS)`，删除 QR / 飞书 / QQ 分支；`create_channel_offline` 开头调用 `ensure_supported_channel_kind`；`cli/support/qr.py` 删除成为孤儿的 `render_qrcode_terminal` 及其私有辅助函数，保留 `mask_secret`。
- 其余：删除 `locale.py` 的 `im_zh` 与 `telegram` 分支、`response_mode.py` 的 `_config_flag` 与 `qq_channel_response_mode`、`openapi_meta.py` channels tag 描述改为"MQTT broker bridges per agent"。
- 前端：`constants.ts` 的 `ChannelKey` 收窄为 `"mqtt" | "dashboard" | "agentchat" | "octopbot"`（后三者用于历史会话图标），`CHANNEL_KEYS = ["mqtt"]`；删除 `isCollapsedChannelKey`、`partitionChannelKeys`、`CHANNEL_URLS` 的公网条目、QQ 群上下文全套、`applyQqChannelSaveConfig`、`normalizeChannelFieldValue`；四张 Record 与 `CHANNEL_FIELDS` 只留白名单；barrel 同步。`ChannelDrawer.tsx` 删除全部扫码 / 一键建号状态机与渲染、`QqGroupContextPolicyFields`、`qrcode.react`，默认 kind 改为 `"mqtt"`，保留表单、display config、启用开关、防重复保存与 `draftScope`。`ChannelsPanel.tsx` 删除对应导入与调用、"更多通道"折叠与按 kind 的成功提示。`api/modules/channel.ts` 删除 14 个方法。`api/types/channel.ts` 只有类型声明、无运行时与地址，不改。

### SSO

- 删除三个适配器；`SSO_KINDS = ("oidc",)`；`build_adapters` 只返回 `oidc`；删除 `base.py` 的 `DEFAULT_OAUTH_CALLBACK_PATH` 与 `public_base.py` 的 `_OAUTH_CALLBACK_PATH` / `oauth_callback_path()`；`service.py::put_config_for_kind` 删除三家分支与 `default_names`，默认显示名直接用 `"Octop SSO"`。
- `auth_oauth.py`：`SsoKind = Literal["oidc"]`；删除 `/oauth/callback`（及只被它用到的辅助导入）。其余 `/oauth/*` 端点保留，`/oauth/exchange` 是 OIDC 浏览器短码换 JWT 的通路，必须保留。`deps.py` 删除 `_JWT_EXEMPT_EXACT` 中的回调项；`openapi_meta.py` 公开端点说明删除该路径。
- 前端：删除 `oauthProviders.ts`、`OauthProviderCard.tsx`、`SsoAppProviderShell.tsx`；`Admin/Users/index.tsx` 只留"本地"与"OIDC"；`Login/index.tsx` 删除三家图标分支；`AvatarDropdown.tsx` 删除 `APP_OAUTH_KINDS`、`oauthProviderIcon`、三个图标导入以及只服务这三家的账号绑定列表（状态、处理函数、弹窗消息监听与渲染块，以 `tsc` / `eslint` 报出的孤儿为准）；`sso.ts` 删除三个飞书包装；`permissions.ts` 的 `USERS_TAB_PERMISSIONS` 删除三家。三家图标与通道图标在同一任务中删除。

### 连接器

- 在 `catalog_intranet.py` 的 `_FORK_REMOVED` 登记 21 个 kind：`tencent-docs`、`tencent-ima`、`tencent-meeting`、`tencent-news`、`wechat-reading`、`tencent-lexiang`、`tencent-weiyun`、`qq-mail`、`qq-music`、`fliggy`、`baidu-map`、`ctrip-wendao`、`meituan-travel`、`didi`、`yuandian`、`tencent-ardot`、`youdao-note`、`notion`、`dida365`、`feishu-cli`、`wecom-cli`，行尾注释 `# w1-05`。
- 删除 12 个适配器、7 个 CLI 网关文件、`mail_servers.py`；`registry.py` 只导入与登记 `weknora`；`server.py::start` 删除 `ensure_cli_path` 三行。
- `builder.py`：删除 `mail_servers` 导入、`DIDI_MCP_BASE_URL`、`normalize_weiyun_mcp_token`、`_build_remote_spec` 的 6 个公网 kind 分支、`validate_create_credentials` 中 8 个 kind 子分支与 `imap_app_password` 分支、`session_cookie` 的 tencent-ima 子分支（`personal_token` 分支改为直接用原始 token）、`inject_missing_gateway_tools` 的 `ima_names` 日志字段。
- `probe.py`：删除 weiyun / youdao 相关分支、`probe_youdao_note`、`_probe_youdao_note_http_error`、成为孤儿的 `_probe_mcp_sse`，`_REMOTE_STATIC_TOOL_KINDS` 变空后连同其判断一起删除。
- `service.py`：删除 ≈L35-39 两处导入与 ≈L503-630 六个成员。
- `api/routers/connectors.py`：删除三处 CLI / 飞书导入与 `normalize_weiyun_mcp_token` 导入、6 个端点及其请求 / 响应模型、`_prepare_credentials` 的 weiyun 分支、`_credentials_preview` 的 6 个 kind 子分支、`get_instance` 的飞书在线预览、`delete_instance` 的 CLI 目录清理。`routers/connectors.py` 仍保留多处 `require_permission("connectors")`，`GATED_FILES` 校验不受影响。
- `infra/utils/paths.py` 的 `connector_cli_dir` 等三个方法成为孤儿：属于 utils 纯函数，只登记、不删除（与 `w1-02` 对 `posix_compat.py` 的处理一致）。
- 前端：`connectorDefs.tsx` 删除邮箱与两个引导集合；`index.tsx` 删除 CLI 安装、飞书用户授权、邮箱服务商、tencent-* 专属表单与导入，保留 `custom_fields`（WeKnora / Dify）与自定义 MCP 路径；`assets/connectors/index.ts` 只保留 `weknora`、`dify`，删除 35 个图片；`api/modules/connectors.ts` 删除 6 个方法与 3 个类型。`ConnectorCategory` 不收窄（后端 `_BASE` 仍含其他分类）。

### 模型预设、Codex OAuth、opencode

- 新增 `src/octop/infra/agents/providers/provider_presets.json`：harness 模板格式的数组，默认只含一条与 harness 模板相同的 `ollama`（`http://localhost:11434/v1`）。`load_provider_presets()` 改为 `load_provider_templates(str(Path(__file__).with_name("provider_presets.json")))`：显式路径不回落用户目录与包内文件；`serialize_provider_preset` 继续复用；删除 `openai-codex` 注入块；`onnx` 注入不变（有 `ollama` 条目，插入位置保持在其后）。`_reasoning_profile` 不改。行内网关条目由 `w2-04` 追加到这份 JSON。
- 删除 `src/octop/infra/providers/`、`providers.py` 的 codex 导入 / 辅助函数 / 后台轮询 / 三个端点 / ≈L477 调用、`agents/providers/probe.py` 的 codex 判定与分支。
- 删除 `opencode_session.py`：`store.py` 删除导入与 `session_header=` 实参；`probe.py` 三处改为直接使用原 headers（`dict(headers) if headers else {}`）。
- 前端删除 `CodexOAuthConnect.tsx`、`PresetProviderModal.tsx` 的 codex 分支、`providerApi.ts` 的两个函数。

### 语音

- `presets.py`：`_BUILTIN_PRESET_IDS = frozenset({"browser", "openai"})`，只返回 browser 与 openai 两条。
- `adapters.py`：删除腾讯、edge、小米三组实现与常量、`_voice_format`、`tencent_sign` 与 `tencent_api_language` 导入；保留 `_wav_header`（其默认采样率参数改为不依赖小米常量的字面量或 `_PROBE_TONE_RATE`，以实现时 mypy 为准）；`transcribe_openai` / `synthesize_openai` 在 `row.base_url` 为空时抛 `ValueError("base_url is required for OpenAI-compatible voice")`，不再回落公网地址；`test_stt` / `test_tts` 只分派 `openai`，`_missing_credentials` 只查 `openai`。
- `manager.py`：删除 edge / tencent / mimo 分支，`media_type` 恒为 `audio/mpeg`。
- `i18n/domains/voice.py`：删除 `tencent_api_language`、腾讯凭据分支与 `voice.tencent.{code}` 查表（键本身保留为孤儿）。
- `api/routers/voice.py`：新增模块常量 `_SUPPORTED_VOICE_KINDS = frozenset({"openai"})`，`admin_create_voice_provider`、`admin_patch_voice_provider`（传入 kind 时）与 `test-configuration` 对其他 kind 抛 `OctopError(ErrorCode.VOICE_KIND_UNSUPPORTED)`。
- 前端 `Voice/index.tsx`：删除腾讯 / edge / 小米状态与表单；OpenAI 表单的"API 接入点"改为可编辑 `Input`（沿用 `voice.mimoEndpoint` 文案，即"API 接入点"），请求体带 `base_url`，未填写时提示 `voice.baseUrlRequired`（overlay 新键）并不提交；`voice.openaiHint` 在 overlay 中改写为"OpenAI 兼容接口，可指向行内语音网关"。

### 媒体生成与联网搜索

- 删除 `media_generation.py`、`routers/media_generation.py`、`routers/search.py`、`utils/search_probe.py`；`app.py` 同批删除两处导入与两条 mount；`openapi_meta.py` 删除 `search` tag。
- `manager.py`：删除 ≈L25-27 导入、`__init__` 与 `replace_persistence` 中的构造、属性、`save_media_generation` 与 ≈L2944 传参；在同一构造调用中加一行 `web_search_tools=False,`。这样 harness 不构建任何联网搜索与媒体工具。
- `w1-02` 的 `infra/capabilities.py::REMOVED_CAPABILITY_TOOLS` 追加 7 个工具名，经 `forced_disabled_tools` 进入 `tools_disabled` 与 `ForcedToolGuardMiddleware`，符合"强制禁用只走 `forced_disabled_tools`"的约定，作为纵深防御。
- `tool_catalog.py`：删除 `_WEB_SEARCH_TOOLS`、`_MEDIA_TOOLS`、7 个目录项与两段 available 判定。
- `env_file.py` 删除 `SEARCH_ENV_KEYS` 与 `search_env_changed`；`envs.py::_after_env_sync` 只保留 `invalidate_mcp_tool_cache()`，不再后台 `reload_all`（其他键本来就不触发重载，行为统一）；PUT 路由描述同步。
- 权限键 `search` 在数据清洗任务中与 fork 迁移同一提交删除（全局约束 1.6）；`GATED_FILES` 删除 `routers/search.py` 与删路由同批。
- 前端：删除 `Settings/SearchConfig/`、`Settings/MediaGeneration/`、`api/modules/mediaGeneration.ts`、`provider.ts::testSearch` 与其类型；`Models/index.tsx` 的 `ModelCategory` 收窄为 `"chat" | "voice"`，`resolveModelCategory`、tab 白名单与渲染同步；`permissions.ts` 的 `modelsPage` 删除 `search`。

### 云验证码

- `providers.py`：删除 5 个云 provider 及其实现类、`_form_call`、`tencent_sign` 导入与末尾类型检查变量，`_register_builtins` 只注册 `_SLIDER`；模块 docstring 改为"滑块为过渡态，终态见 w3-01"。
- `verify.py`：删除 `_TEST_URLS` 与 `set_test_siteverify_url`，`url = call.url`；`captcha/__init__.py` 同步删除再导出。`ensure_captcha` 的通用执行路径保留，由 `w3-01` 重写。
- `store.py`、`config.py` 不改：未注册的 `active` 已回落滑块，未知的环境变量 provider 已在启动时报错。
- 删除 `infra/utils/tencent_sign.py`（最后一个使用方随本任务删除）。
- 前端 `captchaAdapters.ts` 的 `CAPTCHA_WIDGETS` 只留 `slider`；`CaptchaField.tsx`、`CaptchaSettings.tsx` 不改。

### 存量数据

一条 fork 迁移 `forkNNN_saas_decoupling_cleanup`，由 Python 步骤完成全部清洗，SQL 对只含说明注释（沿用 `w1-03` 的做法，满足 `w0-01` 的成对检查）。详见"数据模型"。

### 断网语义

新增 fork 自有模块 `api/intranet_exception_handlers.py`，为 `UnsafeOutboundUrl` 注册专用处理器：服务端 WARNING 记录请求路径与守卫消息，响应 400 `OUTBOUND_URL_REJECTED`，信封 `details` 为空、不回显主机名。`app.py::build_app` 在 `_install_exception_handlers(app)` 之后加 1 行调用。Starlette 按异常类的 MRO 选择最具体的处理器，所以它优先于兜底的 `Exception` 处理器。

## 组件与接口

| 文件 | 类型 | 改动 |
|---|---|---|
| `src/octop/infra/gateway/channel_kinds.py` | 新增 | `ChannelKind`、`SUPPORTED_CHANNEL_KINDS`、`is_supported_channel_kind`、`ensure_supported_channel_kind` |
| `src/octop/infra/gateway/gateway.py` | 修改 | 导入改指新模块；3 处闸门；删 qq 分支与飞书探测错误分支 |
| `src/octop/api/routers/channels.py` | 修改 | 删 ≈L25-26、≈L54-75、≈L263-1071 与孤儿导入 |
| `src/octop/cli/commands/channel.py`、`cli/support/offline_ops.py`、`cli/support/qr.py` | 修改 | 删 `bind`、`feishu-setup`、QR 分支；离线创建加闸门；删 `render_qrcode_terminal` |
| `src/octop/infra/utils/locale.py`、`infra/gateway/process/response_mode.py` | 修改 | 删 IM 语言提示；删 `_config_flag`、`qq_channel_response_mode` |
| `src/octop/infra/auth/sso/providers/{__init__,base}.py`、`sso/public_base.py`、`sso/service.py` | 修改 | 只留 OIDC |
| `src/octop/api/routers/auth_oauth.py`、`api/deps.py`、`api/openapi_meta.py` | 修改 | `SsoKind` 收窄、删回调与豁免、更新说明、删 `search` tag |
| `src/octop/infra/connectors/catalog_intranet.py` | 修改（`w0-04` 建） | `_FORK_REMOVED` 填 21 个 kind |
| `src/octop/infra/connectors/{builder,probe,service}.py`、`gateway/registry.py`、`api/routers/connectors.py`、`infra/server.py` | 修改 | 见"方案·连接器" |
| `src/octop/infra/agents/providers/{presets,probe,store}.py`、`provider_presets.json`、`api/routers/providers.py` | 修改 / 新增 | 自维护预设；删 Codex 与 opencode |
| `src/octop/infra/voice/{presets,adapters,manager}.py`、`i18n/domains/voice.py`、`api/routers/voice.py` | 修改 | 只留 browser / OpenAI 兼容 |
| `src/octop/infra/agents/{manager,tool_catalog}.py`、`infra/capabilities.py`、`infra/utils/env_file.py`、`api/routers/envs.py`、`api/app.py`、`infra/users/permissions.py` | 修改 | 删媒体 / 搜索；强制禁用；删权限键 |
| `src/octop/infra/auth/captcha/{providers,verify,__init__}.py` | 修改 | 只留滑块 |
| `src/octop/infra/errors.py` | 修改 | 末尾追加 `OUTBOUND_URL_REJECTED` 与 `_DEFAULT_STATUS` 400 |
| `src/octop/api/intranet_exception_handlers.py` | 新增 | `install_intranet_exception_handlers` |
| `src/octop/infra/db/fork_saas_cleanup.py`、`infra/db/fork_migrate.py`、`migrations/forkNNN_saas_decoupling_cleanup{,.pg}.sql` | 新增 / 修改 | 清洗步骤与登记 |
| `src/octop/i18n/intranet/{en,zh}.json`、`dashboard/src/locales/intranet/{en,zh}.json` | 修改（`w0-04` 建） | `errors` / `apiErrors.OUTBOUND_URL_REJECTED`；`voice.baseUrlRequired`、`voice.openaiHint` |
| `pyproject.toml`、`uv.lock`、`dashboard/package.json`、`dashboard/package-lock.json` | 修改 | 删 `lark-oapi`、`edge-tts`、`qrcode.react`；`make relock` |
| `AGENTS.md`、`CHANGELOG-intranet.md`、`docs/api-intranet.md` | 修改 | 三处失效引用；fork 记录 |

关键签名：

```python
# src/octop/infra/gateway/channel_kinds.py（fork 自有）
class ChannelKind(StrEnum):
    MQTT = "mqtt"

SUPPORTED_CHANNEL_KINDS: frozenset[str] = frozenset(k.value for k in ChannelKind)

def is_supported_channel_kind(kind: str) -> bool: ...

def ensure_supported_channel_kind(kind: str) -> None:
    """Raise OctopError(CHANNEL_KIND_UNSUPPORTED) for kinds outside the intranet allowlist."""
```

```python
# src/octop/infra/db/fork_saas_cleanup.py（fork 自有；冻结快照，不导入上层包）
REMOVED_CHANNEL_KINDS: frozenset[str]      # 8 个
REMOVED_CONNECTOR_KINDS: frozenset[str]    # 21 个，单测断言与 _FORK_REMOVED 相等
REMOVED_VOICE_KINDS: frozenset[str]        # {"edge", "tencent", "mimo"}
REMOVED_SSO_KINDS: frozenset[str]          # {"feishu", "dingtalk", "wecom"}
REMOVED_SETTINGS_KEYS: frozenset[str]      # 5 个 media_generation_* 与 "captcha.settings"
REMOVED_SETTINGS_PREFIXES: tuple[str, ...] # ("codex_oauth.pending.",)
REMOVED_SECRET_KEYS: frozenset[str]        # {"media_generation_credentials"}
REMOVED_PERMISSION_KEYS: frozenset[str]    # {"search"}

def step_saas_decoupling_cleanup(conn: Any, dialect: str) -> None:
    """forkNNN: strip removed permission keys and purge removed-SaaS rows; idempotent, skips missing tables."""
```

```python
# src/octop/api/intranet_exception_handlers.py（fork 自有）
def install_intranet_exception_handlers(app: FastAPI) -> None:
    """Map UnsafeOutboundUrl to 400 OUTBOUND_URL_REJECTED without echoing the host."""
```

```python
# src/octop/infra/agents/providers/presets.py
def load_provider_presets() -> list[dict[str, Any]]:
    """Serialize the fork-maintained provider_presets.json (explicit path, no harness fallback)."""
```

## 数据模型

不新增表或列。新增一条 fork 迁移 `forkNNN_saas_decoupling_cleanup`（号不预占，合入 fork 主干时取下一个可用号）：

- `src/octop/infra/db/migrations/forkNNN_saas_decoupling_cleanup.sql` 与同名 `.pg.sql`：只含说明注释，runner 执行 0 条语句。
- `infra/db/fork_migrate.py::_FORK_PY_STEPS[NNN] = step_saas_decoupling_cleanup`，按顺序执行：
  1. `strip_permission_keys(conn, dialect, REMOVED_PERMISSION_KEYS)`（复用 `w1-02` 的 `infra/db/fork_steps.py`）；
  2. `DELETE FROM channels WHERE kind IN (…8 个…)`；
  3. `DELETE FROM connectors WHERE kind IN (…21 个…)`；
  4. `DELETE FROM voice_providers WHERE kind IN ('edge', 'tencent', 'mimo')`，随后把 `settings` 中 `active_stt_provider` / `active_tts_provider` 的值在"不是 `browser` / `openai`，且不在 `voice_providers.name` 中"时改为 `browser`；
  5. `UPDATE sso_providers SET enabled = 0, client_secret_enc = NULL WHERE kind IN ('feishu', 'dingtalk', 'wecom')`——不删行，因为 `users.sso_provider_id` 外键无 `ON DELETE`；
  6. 删除 `settings` 中 `REMOVED_SETTINGS_KEYS` 与以 `codex_oauth.pending.` 开头的键（用 `substr(key, 1, 20) = 'codex_oauth.pending.'`，避开 `LIKE` 的 `_` 通配），删除 `secrets` 中 `k = 'media_generation_credentials'`。
- 每一步先判断表存在（SQLite 查 `sqlite_master`，PG 查 `information_schema.tables`，与 `strip_permission_keys` 同一做法），缺表跳过；只用 `?` 占位；不提交事务；天然幂等。
- 键名与 kind 写死为快照，不导入 `infra/users/permissions.py`、`catalog_intranet.py`，符合"`infra/db` 不依赖上层包"。
- 回填：无。`_schema_version` 与 8 个测试文件中的 `v == 15` 断言不变。
- 文件系统残留（`~/.octop/codex_oauth.json`、`~/.octop/connector-cli/`、`~/.octop/env` 中的 `TAVILY_API_KEY` 等搜索键）不在迁移内处理，写入 `CHANGELOG-intranet.md` 的升级须知，由运维手工删除。

## 配置

无。本 spec 不新增 `OctopConfig` 字段，也不删除既有字段（`browser_idle_timeout_minutes` 保留，理由见"方案·IM 通道"）。`OCTOP_CAPTCHA_*` 环境变量由 `infra/auth/captcha/config.py` 自行读取，不经 `OctopConfig`，行为见需求 8.3。

## 错误处理

| 场景 | 表现 | 说明 |
|---|---|---|
| 请求体 `kind` 不在白名单（通道、`/oauth/*`） | 422 | Pydantic 枚举 / `Literal` 校验 |
| Gateway / CLI 遇到非白名单通道 | `CHANNEL_KIND_UNSUPPORTED`（既有码，400）；注册路径转为运行态 `error`；探测返回 `ok=false` | 复用既有码 |
| 以隐藏的连接器 kind 建实例 | `CONNECTOR_KIND_UNSUPPORTED`（既有码，400） | 基线行为，靠 `_FORK_REMOVED` 触发 |
| 语音供应商 kind 不是 `openai` | `VOICE_KIND_UNSUPPORTED`（既有码，400） | 复用既有码 |
| OpenAI 兼容语音缺 `base_url` | 探测 `ok=false`；实际调用沿用基线"缺 api_key"的 `ValueError` 语义 | 不新增码 |
| `UnsafeOutboundUrl` 冒泡到 HTTP 层 | **新增** `OUTBOUND_URL_REJECTED`，`_DEFAULT_STATUS` 登记 400 | 见下 |

新增 `ErrorCode.OUTBOUND_URL_REJECTED = "OUTBOUND_URL_REJECTED"`，按全局约束 1.2 规则三同批改齐：`errors.py` 枚举末尾与 `_DEFAULT_STATUS` 末尾（400）；后端 overlay `errors.OUTBOUND_URL_REJECTED`（en："The configured outbound address is not allowed or cannot be resolved."；zh："配置的出站地址不被允许或无法解析。"）；dashboard overlay `apiErrors.OUTBOUND_URL_REJECTED`（同文案）。选 400 而不是 502：被拒的原因是配置的地址不在白名单或无法解析，属于调用方可修正的配置错误。没有可复用的既有码：`SLASH_BAD_ARGS` 文案"Invalid arguments."会误导排障，`OIDC_BAD_REQUEST` 语义不符。

不删除任何既有 `ErrorCode`；`VOICE_BROWSER_ONLY` 等与裁剪相关的码继续保留。

## 安全考虑

- **攻击面收缩**：删除 28 个 HTTP 端点（14 扫码 / 建号、1 个公开回调、3 个 Codex、6 个连接器 CLI / 飞书授权、3 个媒体生成、1 个搜索探测）、两个拉起 Chromium 的子进程流程、启动期改写 `PATH` 与运行期 `npm install -g`、一个 JWT 豁免的公开路径、一个生产代码里的测试缝（`set_test_siteverify_url`）。
- **防旁路**：通道白名单同时在 API、Gateway 注册 / 探测、CLI 离线生效；即使残留数据或直接写库，harness-gateway 也不会建公网 IM 连接。harness-gateway 包内仍有 IM SDK 代码，但无可达路径；去除 SDK 由 `w2-01` 负责。
- **数据最小化**：迁移删除已删能力的公网凭据（通道配置、连接器凭据、语音密钥、媒体生成密钥、验证码密钥），清空三家 SSO 的 `client_secret_enc`。
- **信息泄露**：`OUTBOUND_URL_REJECTED` 的信封不回显主机名，避免普通用户在调用语音时看到行内网关的主机名；管理员通过探测接口与服务端日志排障。
- **默认安全**：OpenAI 兼容语音不再回落 `api.openai.com`；模型预设不再回落 harness 包内与用户目录的模板；联网搜索工具不再以 `"auto"` 默认装配。
- **残余风险**：`probe_streamable_http_mcp`（Dify、自定义 MCP）建连前没有解析期校验，这是基线缺口，按 `w0-05` 的交接由 `w3-06` 补。

## 测试策略

测试先行：每个删除任务先把自己的条目加进两条守卫测试的清单（此时变红），再做删除使之变绿；行为类改动先写会失败的用例。

| 类别 | 内容 | 本地命令 |
|---|---|---|
| 守卫：域名 | `tests/unit/test_saas_tokens_removed.py`：用 `pathlib` 遍历 `src/octop/**/*.py` 与 `dashboard/src/**/*.{ts,tsx}`，以 UTF-8 读取，逐个断言公网主机名不出现（排除 `infra/connectors/catalog.py` 与 `dashboard/src/assets/providers/index.ts`）；清单：`open.feishu.cn`、`accounts.feishu.cn`、`oapi.dingtalk.com`、`login.dingtalk.com`、`api.dingtalk.com`、`work.weixin.qq.com`、`qyapi.weixin.qq.com`、`q.qq.com`、`yuanbao.tencent.com`、`ilink.b.qq.com`、`tencentcloudapi.com`、`xiaomimimo.com`、`ark.cn-beijing.volces.com`、`chatgpt.com`、`auth.openai.com`、`opencode.ai`、`challenges.cloudflare.com`、`hcaptcha.com`、`google.com/recaptcha`、`captcha.qcloud.com`、`docs.qq.com`、`mcp.meeting.tencent.com`、`weiyun.com`、`lexiang-app.com`、`open.mail.163.com`、`mcp.didichuxing.com`、`imap.qq.com`，以及模块名 `lark_oapi`、`edge_tts` | `uv run pytest tests/unit/test_saas_tokens_removed.py -q` |
| 守卫：路由 | `tests/unit/api/test_saas_removed_routes.py`：`write_octop_config(enable_api_docs=True)` 启动 `OctopServer` 并 `build_app`，断言 28 个 `(path, method)` 不在 `app.routes`，路径不在 `/api/openapi.json` 的 `paths`；同时断言 `/api/auth/oidc/callback`、`/api/auth/oauth/exchange` 仍在 | `uv run pytest tests/unit/api/test_saas_removed_routes.py -q` |
| 单测：通道 | `tests/unit/gateway/test_channel_kind_allowlist.py`（取值集合、`gateway.ChannelKind is channel_kinds.ChannelKind`、`gateway.py` 源码不含 `harness_gateway.channels`、`create_channel` / `update_channel` 抛错、注册残留 `feishu` 行时 `add_channel` 未被调用且运行态 `error`、`probe_config(kind="feishu")` 返回 `ok=false` 且 `probe_channel` 未被调用）；改写 `test_gateway.py`、`test_gateway_probe.py`、`test_response_mode.py`、`test_user_locale.py`；删除 `test_channels_qr.py`、`test_feishu_bot_creator.py` | `uv run pytest tests/unit/gateway tests/unit/test_user_locale.py -q` |
| 单测：CLI | `tests/unit/cli/test_channel_cmd.py`（`CliRunner`，`monkeypatch.setenv("OCTOP_HOME", str(tmp_path))`）：`--help` 不含 `bind`、`feishu-setup`；`create --kind feishu` 非零退出且库中无行 | `uv run pytest tests/unit/cli/test_channel_cmd.py -q` |
| 单测：SSO | 删除三个适配器测试；`test_sso_service.py` 保留；`test_jwt_auth_middleware.py` 回调断言改为 `not is_jwt_exempt_path(...)` | `uv run pytest tests/unit/auth tests/unit/api/test_jwt_auth_middleware.py -q` |
| 单测：连接器 | 删除 `tests/unit/connectors/` 中 8 个专测文件；`test_connectors.py` 删除已删 kind 的用例，通用用例夹具换成 `weknora` / `dify`；`test_mcp_oauth_ssrf.py` 以字面量 issuer 替代 `issuer_for_kind("notion")`；`test_oauth_discovery.py` 用 monkeypatch 的桩条目替代 `notion`；其余夹具按实际失败替换 | `uv run pytest tests/unit/connectors tests/unit/test_connectors.py tests/unit/agents -q` |
| 单测：模型 / 语音 / 媒体 / 验证码 | 重写 `test_provider_preset_expansion.py`（id 集合、无 `openai-codex`、环回主机、`onnx` 紧跟 `ollama`、用户目录模板不影响结果）；删除 `test_codex_oauth.py`、`test_opencode_session.py`、`test_voice_formats.py`、`api/test_voice_mimo.py`、`test_media_generation_settings.py`、`utils/test_search_probe.py`；改写 `test_voice_{manager,probe,stt_probe}.py`、`i18n/test_voice.py`、`test_tool_catalog.py`、`test_env_file.py`、`users/test_permissions.py`、`test_captcha_{providers,verify,store,env}.py`；`w1-02` 的 `test_capabilities.py` 按名字集合断言强制集 | `uv run pytest tests/unit -q -k "preset or codex or voice or tool_catalog or env_file or permissions or captcha or capabilities"` |
| 单测：迁移 | `tests/unit/db/test_fork_saas_cleanup.py`：六类清洗、保序、幂等、缺表跳过、`REMOVED_CONNECTOR_KINDS == _FORK_REMOVED`、`REMOVED_CHANNEL_KINDS` 与基线 harness `ChannelKind` 差集一致 | `uv run pytest tests/unit/db/test_fork_saas_cleanup.py -q` |
| 集成 | `test_channels_api.py`、`test_channel_probe_draft.py`、`integration/conftest.py::env_with_channel` 改用 `mqtt`；`test_auth_oauth.py` 改写；`test_connectors_api.py` 目录断言与夹具；删除 `test_media_generation_api.py`、`test_search_api.py`；`test_provider_test_draft.py` 删 codex 用例；`test_captcha_api.py` 改写为滑块与管理端读写；新增 `test_saas_cleanup_migration.py`（写入残留数据后用 `set_fork_version(pool, v - 1)` 回拨水位，`v` 从 `_FORK_PY_STEPS` 反查，再 `run_fork_migrations`；含"老用户含 `search` 可被 `PATCH`"）；新增 `test_offline_boot.py`（需求 11） | `uv run pytest tests/integration -q` |
| PG | `test_saas_cleanup_migration.py` 中的 PG 用例用 `tests.support.postgresql.requires_postgresql` 标记，前提 `w0-02` | `OCTOP_TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:15432/octop_test uv run pytest tests/integration/test_saas_cleanup_migration.py -q`（或 `make test-postgresql`） |
| 前端 | 改写 `constants.test.ts`、`ChannelsPanel.test.tsx`（保留"新建默认禁用"断言）、`SsoPanel.test.tsx`、`sso.test.ts`、`ConnectorCard.test.tsx`、`guidedConnectorUtils.test.ts`、`CaptchaField.test.tsx`；删除 `SearchConfig/index.test.tsx`；新增 `Settings/Voice/index.test.tsx`（OpenAI 表单可填 `base_url`、请求体携带、未填不提交）。前提 `w0-02` | `cd dashboard && npx tsc -b && npm run lint && npm run test` |
| i18n | overlay 新键的 en / zh 对等与三方相等 | `uv run pytest tests/unit/i18n -q` |
| 全量 | ship bar | `make all` |

所有新增 Python 测试遵守 AGENTS.md §7：只用 `pathlib` 与 `tmp_path`，设置 `OCTOP_HOME` 用 `monkeypatch.setenv`，不硬编码 POSIX 路径。断网冒烟只 monkeypatch `socket.getaddrinfo`（对 IP 字面量委托原函数），不依赖平台特性。

## 与其他 spec 的交接

**依赖：**

- `w0-01`：`forkNNN_` 命名、`_FORK_PY_STEPS`、`set_fork_version`、`run_fork_migrations` 与成对静态检查。
- `w0-02`：vitest 与 PG 用例进入 CI；本 spec 的前端与 PG 验收以它为前提。
- `w0-03`：管理员键集运行期计算，删 `search` 后夹具无需改；`REAL_AUTH_GUARD_MODULES` 与 `test_real_guard_modules_exist`（改写 `test_captcha_api.py` 时同步维护）。
- `w0-04`：`_FORK_REMOVED`、i18n overlay、`make relock`、`CHANGELOG-intranet.md`、`docs/api-intranet.md`。
- `w0-05`：白名单使 WeKnora、Dify、自定义 MCP、OpenAI 兼容语音在行内地址上可用（源分析所称硬阻塞）；它把"无 DNS 映射 4xx 的断网冒烟"交给本 spec。
- `w1-01`：语音凭据脱敏按键名通用处理，删除腾讯语音无需改 `infra/voice/credentials.py`；`Voice/index.tsx` 中它对腾讯分支的改动随分支删除。
- `w1-02`：`infra/capabilities.py::REMOVED_CAPABILITY_TOOLS` / `forced_disabled_tools`、`infra/db/fork_steps.py::strip_permission_keys`。本 spec 完成了它交接的评估：`_resolve_profiles_root` 随扫码段删除；`browser_media.py` 的保留函数与 `browser_idle_timeout_minutes` 仍服务 harness-browser，不删。

**交付给：**

- `w2-01`：harness-gateway 重打包去掉 5 个 IM SDK（本 spec 删除后 Octop 已无可达路径）；`lark-oapi` 仍由 harness-gateway 传递引入；全量出网门禁可以直接吸收本 spec 的域名守卫清单，`catalog.py` 的 `_BASE` 需按合成后的 `_CATALOG` 判定。
- `w2-02`：SBOM 中 `edge-tts`、`qrcode.react` 消失，`lark-oapi` 要等 `w2-01`。
- `w2-04`：在 `provider_presets.json` 追加行内网关条目；OpenAI 兼容语音与模型网关可共用同一行内 CA。
- `w3-01`：验证码只剩滑块、`set_test_siteverify_url` 已删、`captcha.settings` 已被迁移清空，终态可以从干净起点实现；`CAPTCHA_SEAMS` 不受影响。
- `w3-03`：权限键少了 `search`，已清洗。
- `w3-04`：少一个 JWT 豁免的公开回调；账号绑定只剩 OIDC（基线上头像菜单并不提供 OIDC 绑定）。
- `w3-05`：需加密的明文列少了公网凭据；三家 SSO 行的 `client_secret_enc` 已清空。
- `w3-06`：`probe_streamable_http_mcp` 解析期校验缺口（`w0-05` 已登记）。
- `p2-06`：在 `channel_kinds.py` 的 `ChannelKind` 追加行内 IM kind（需 harness-gateway 内部分支支持，D13），在 `_fork_entries()` 追加行内连接器。
- `p2-11`：OIDC 之外的身份源。

**看似相关但归别的 spec：** `web_fetch` 工具（`w1-02` 强制禁用机制 / `w3-06`）；专家库与 subagent 库中飞书 / 钉钉 / 微信相关内容（`w1-04`）；控制台 GitHub 与供应商文档外链、`assets/providers/index.ts`（`w4-01`）；技能市场、自更新（`w1-03`）；`infra/utils/paths.py` 的连接器 CLI 目录方法（孤儿，登记不删）。

## 风险与回滚

| 风险 | 等级 | 缓解 |
|---|---|---|
| 未合入 `w0-05` 就上线，保留的三个连接器与语音在行内地址上全被拒 | 高 | 头部前置写明；任务 1 核对；需求 4.6 用白名单配置做正向验收 |
| `ChannelDrawer.tsx`（1890 行）删除三分之二时误伤表单、启用开关、防重复保存 | 高 | 先改写 `ChannelsPanel.test.tsx` 保住"新建默认禁用"回归；`tsc -b` 报出全部孤儿；手工冒烟 MQTT 新建 / 编辑 / 启停 |
| 迁移删除存量通道 / 连接器 / 语音行，引用它们的定时任务投递或 agent 的 `mcp_servers` 失效 | 中 | 这些对象本来就无法工作；升级须知写明；回滚走系统备份 |
| 连接器测试面大（`test_connectors.py` 58 个用例触及已删 kind） | 中 | 通用用例保留并换夹具；专测已删 kind 的用例删除；目录断言改为 `{"weknora", "dify"}` |
| 上游同步冲突：已删文件被上游修改；`channels.py`、`connectors.py`、`builder.py`、`ChannelDrawer.tsx`、`Connectors/index.tsx` 是中高频文件 | 中 | 冲突时保持删除；两条守卫测试拦截回流；连接器目录走 `_FORK_REMOVED`，`_BASE` 零改动 |
| harness 升级改名 `web_search_tools` 字段 | 低 | 单测断言 `_build_harness_config` 的字段值，升级时变红 |
| 锁文件冲突 | 低 | 取上游后 `make relock` |

**回滚：** 按提交逆序 revert。代码回滚后，fork 迁移已删除的数据不会恢复：老代码面对缺失的通道、连接器、语音行只是"没有配置"；三家 SSO 行已停用且无密钥，需要管理员重新填写；`search` 权限键缺失只是"无权限"。如需恢复数据，从升级前的系统备份取回。`_fork_schema_version` 不回退（`w0-01` 的 runner 对"水位高于文件最大号"只记 WARNING）。

## 待行方确认

- **D10（语音能力）**：本设计按默认假设保留 OpenAI 兼容 STT / TTS 并要求显式 `base_url`。若行方要求语音整体下线，追加删除 `api/routers/voice.py`、`infra/voice/`、前端语音页与 `voice` 权限键（同批清洗），约 +1.5 人日。
- **D1（统一认证协议）**：本设计保留通用 OIDC。若行方是 CAS / SAML / LDAP，由 `p2-11` 实现，本 spec 不变。
- **D11（验证码终态）**：本 spec 只做"删云 provider、保留滑块"的过渡，终态由 `w3-01` 实现。
- **D13（harness-* 源码）**：去掉 harness-gateway 的 IM SDK 与后续接入行内 IM 都依赖源码可得。
- **D2（行内大模型平台）**：`provider_presets.json` 默认只含本地 Ollama，行内网关条目由 `w2-04` 按 D2 补。
- 以下不在第 4 节 D 表中，建议补入：
  - 通道白名单是否只保留 MQTT（本设计默认 `{"mqtt"}`）；
  - 存量数据的处理口径：本设计默认删除已删能力的通道 / 连接器 / 语音行、停用三家 SSO 并清空密钥；若行方要求"留存待审计"，改为全部停用不删除，约 −0.25 人日；
  - 媒体生成与联网搜索是否需要行内替代能力（本 spec 只删除，不实现替代）。
