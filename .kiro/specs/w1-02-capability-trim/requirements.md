# 需求文档：高危能力裁剪与横切框架

> spec：`w1-02-capability-trim` ｜ 波次：Wave 1 ｜ 基线：`757fd12` ｜ 预估：16 人日
> 前置：`w0-01-fork-migration-namespace`、`w0-02-ci-gates`、`w0-03-test-auth-baseline`、`w0-04-fork-isolation-points`、`w1-01-security-hotfix` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 引言

**结论：** 本 spec 做两件事。第一，物理删除五类高危能力：Web 终端、远程桌面、远程手机、浏览器自动化与远程浏览器、ACP 外部 CLI 委派。删除范围覆盖后端路由、基础设施模块、agent 装配代码、CLI 子命令、权限键、前端页面与入口、依赖与构建脚本，并用 fork 迁移清洗存量数据。第二，作为三个横切框架的唯一 owner 交付地基：能力开关框架（`capabilities.<name>.enabled`）、配置三触点门禁（含 `config.py` 重复块修复）、agent 中间件注册式装配与 host 级强制工具禁用（`forced_disabled_tools`）。本 spec 不删任何 i18n 键，不新增 `ErrorCode`，不改上游 `CHANGELOG.md` 与 `docs/api.md` 正文。

### 背景

- **五类能力都等价于"服务进程身份下的任意操作"。** Web 终端 `api/routers/terminal.py` 用 `subprocess.Popen(..., preexec_fn=posix_compat.setsid)` 以服务进程 uid 拉起交互式 shell，全程无命令审计。远程浏览器的 `/browser-stream/ws` 只校验令牌、不校验权限键，拿到令牌即可驱动真实 Chrome。远程桌面提供宿主机截屏与键鼠注入。远程手机提供 adb shell PTY，配套的 `docker/docker-compose.mobile.yml` 使用 `privileged: true`、`network_mode: host`，并挂载 `/var/run/docker.sock`。ACP 路由内置 7 个外部 CLI runner，且允许自定义 `command` / `args` / `env`。
- **只删路由不等于能力消失。** `browser_use` 与 `desktop_screenshot` 由已安装的 `orcakit-harness-agent` 在 `HarnessAgent._build_tools` 中无条件注册，Octop 能用的只有 `harness_cfg.tools_disabled`。而这个字段目前只来自 per-agent 配置，工具设置 API 可以任意改写。另外，harness 的 `tools_disabled` 只在 `wrap_model_call` 过滤模型可见的工具列表，既不拦截执行，也不作用于子代理：deepagents 的 general-purpose 子代理直接继承主代理工具集，却不继承主代理的中间件链。
- **致命耦合：** `infra/agents/middleware/browser_profile.py` 导入了 `browser_media.user_browser_profile` 与 `parse_octop_user_id`，而 `manager.py` 在组装每个 agent 时都会无条件实例化 `BrowserProfileMiddleware()`。只删函数不删中间件，所有 agent 都会在启动时 `ImportError`。
- **能力开关现状是"mobile 一条写死到底"。** 配置里只有 `CapabilitiesConfig.mobile`，`GET /api/settings/capabilities` 的响应字段是写死的 `mobile`，前端 `useServerCapabilities` 返回 `{ mobileEnabled }`，`app.py` 用一段 `if enable_mobile:` 条件挂载。`load_config` 里的 capabilities 解析与 `OCTOP_ENABLE_MOBILE` 覆盖逻辑逐字重复了两遍。启动时 `ensure_mobile_capabilities_probed` 还会回写 `config.json`。
- **配置三触点陷阱：** `config.py` 新增一个键要改三处，漏掉 `return OctopConfig(...)` 这一处时开关永远取默认值，而 mypy、lint、测试可能全绿。
- **agent 中间件注入点是一条硬编码列表**，`w3-06`、`p2-04`、`p2-06` 都要往里加东西。

### 为什么做

- 全局约束 1.5"先删后改"：先删掉 5 个 WebSocket，`w3-04` 的"令牌移出 URL"就从 7 个 WS 降到 2 个；`w3-*` 与 `p2-*` 不再为已删能力写加固代码。
- 能力开关、三触点门禁、中间件注册点被 8 个以上后续 spec 消费。它们必须先由一个 owner 定型，否则 `settings.py` 的响应形状和前端 hook 的签名会被依次破坏性地改好几遍。

### 范围内

1. 物理删除五类能力的后端路由、`infra/{browser,desktop,mobile}` 包、`acp_settings.py`、`BrowserProfileMiddleware`、`cli/commands/acp.py`、`docker/docker-compose.mobile.yml`、OpenAPI tag，以及 `manager.py` 中的 ACP、mobile 装配代码。
2. 删除 `terminal` / `browser` / `desktop` / `mobile` 四个权限键，并用 fork 迁移清洗 `users.permissions` 的存量值与 `settings` 表中 `acp_runners:user:*` 的遗留行（全局约束 1.6）。
3. host 级强制工具禁用：`forced_disabled_tools` 并入 harness 配置组装与全部热同步路径，另加主代理执行守卫中间件；对子代理可达的 `browser_use` / `desktop_screenshot` 做中和。
4. 能力开关框架：能力目录与保留名、`config.py` 解析泛化、`infra/capabilities.py`、`deps.require_capability`、`app.py` 的 `_mount_if_capable` 与登记表、`GET /api/settings/capabilities` 泛化、前端 `useServerCapabilities` 泛化。
5. 配置三触点门禁单测，以及删除 `config.py` 的重复块。
6. agent 中间件注册式装配。
7. 前端删除五类能力的页面、组件、hooks、API 模块、路由、导航、工具设置 ACP tab，以及聊天页的终端、浏览器入口。`ChatDockPanelShell` 迁出后保留。
8. 依赖与构建：`playwright` 直接依赖与 `browser` extra、`@xterm/*`、`Dockerfile` 的 `--extra browser`，并用 `make relock` 重生成两份锁文件。
9. fork 文档：`CHANGELOG-intranet.md`、`docs/api-intranet.md`、新增 `docs/intranet/capabilities.md`；`AGENTS.md` 中因本次删除而失效的三处引用；删除 `docs/acp.md`。

### 范围外（归属）

- **删除 i18n 键：不做**（全局约束 1.2）。源分析列出的约 1150 个删键项全部作废，孤儿键保留。`DESKTOP_SESSION_LIMIT`、`DESKTOP_CAPTURE_FAILED` 两个 `ErrorCode` 也保留为孤儿码，因为三方相等门禁要求枚举与四份 JSON 同步。
- **上游文档正文**（`docs/api.md`、`docs/cli.md`、`docs/architecture.md`、`docs/user-guide.*`、`docs/configuration.md`、`README*`）：不改。变更只写进 fork 文档（w0-04 规则）。删除 `docs/acp.md` 后，上游文档里会留下 7 处死链，由 `w1-04` 在裁剪非交付文档时一并评估。
- **"保留但可关停"的能力逐项接入开关**（插件、技能包、连接器、通道、定时任务、备份等）：本 spec 只交付框架。能力目录合入时为空，只登记保留名：`agent_shell` 归 `w3-06`，`content_security` 归 `p2-04`，`intranet_im` 与 `intranet_connectors` 归 `p2-06`，`frontend_controls` 归 `p2-07`。其余能力是否接入、默认开还是关，待行方确认。
- **子代理对"能力关闭型"工具的覆盖**（如 `w3-06` 的 `execute`）：需要修改 harness（让子代理遵守 `tools_disabled`）或调整执行后端。harness 内部分支由 `w2-01` 建立，执行面由 `w3-06` 负责。
- `orcakit-harness-agent[all]` extra 收窄（`mss`、`pynput`、`agent-client-protocol` 等），以及 `harness-browser` 包本身能否移出依赖树：`w2-01`。
- 公网 IM 通道删除后 `browser_media.py` 中通道扫码 profile 相关函数、`browser_idle_timeout_minutes` 的去留：`w1-05`。
- `opencode_session.py`、Codex OAuth、云验证码、在线语音：`w1-05`。联网搜索、`web_fetch`、技能市场、自更新：`w1-03`。
- 专家库中引用 `browser_use` 的 4 个专家（9 个文件）、`scripts/install.*` 与 `scripts/README.md` 中的 playwright / `[browser]` 安装逻辑、`fnos/docker/Dockerfile` 的 `.[desktop]`：`w1-04`（本 spec 保留 `desktop` extra，不打断 fnos 构建）。
- 能力开关闸门处的操作审计：`w3-02`。权限判定收口：`w3-03`。聊天 WS 与通知 WS 的令牌移出 URL：`w3-04`。

## 需求

### 需求 1：五类高危能力的后端入口物理删除

**用户故事：** 作为行方安全评审人员，我希望 Web 终端、远程桌面、远程手机、远程浏览器与 ACP 的全部后端入口在代码中物理不存在，以便它们无法通过任何 API、CLI 或配置被重新启用。

#### 验收标准

1. 当 `build_app` 构建应用时，`app.routes` 中应当不存在路径以 `/api/browser`、`/api/browser-stream`、`/api/desktop`、`/api/desktop-stream`、`/api/mobile`、`/api/mobile-stream`、`/api/acp` 开头的路由，也不存在 `/api/agents/{agent_id}/terminal/...` 与 `/api/agents/{agent_id}/acp...` 路由；已登录用户请求 `GET /api/browser/env-status`、`GET /api/desktop/status`、`GET /api/mobile/status`、`GET /api/acp`、`GET /api/agents/{id}/terminal/context` 时应当得到 404。
2. 当 `enable_api_docs=True` 并请求 `/api/openapi.json` 时，`tags` 中应当不含 `terminal`、`browser`、`desktop`、`mobile`，`paths` 中不含第 1 条所列的前缀。
3. 当执行 `uv run octop acp --help` 时，CLI 应当以非零退出码结束；`octop.cli.registry.COMMANDS` 中应当不含 `acp`。
4. 仓库应当始终不存在以下路径：`src/octop/api/routers/{terminal.py,acp.py}`、`src/octop/api/routers/{browser,desktop,mobile}/`、`src/octop/infra/{browser,desktop,mobile}/`、`src/octop/infra/agents/acp_settings.py`、`src/octop/infra/agents/middleware/browser_profile.py`、`src/octop/cli/commands/acp.py`、`docker/docker-compose.mobile.yml`、`docs/acp.md`；并且 `rg -n 'octop\.infra\.(browser|desktop|mobile)|routers\.(terminal|acp)\b|acp_settings|harness_agent\.acp|config_probe' src` 没有输出。
5. 本 spec 应当始终保留以下同名但无关的资产：仓库根 `desktop/`、`tests/unit/desktop/test_stamp_version.py`、`infra/utils/posix_compat.py`（其模块 docstring 不再引用 `terminal_supported`），以及 `infra/utils/browser_media.py` 中被通道与网关使用的 `octop_browser_profiles_dir`、`configure_browser_screenshots_dir`、`configure_browser_profiles_dir`、`configure_browser_idle_timeout`、`agent_outbound_screenshots_dir`、`legacy_harness_screenshots_dir`。`uv run pytest tests/unit/desktop/test_stamp_version.py tests/unit/utils/test_posix_compat.py tests/unit/utils/test_browser_profiles_dir.py -q` 应当通过。

### 需求 2：删除后 agent 仍可启动，且不再装配已删能力

**用户故事：** 作为运维人员，我希望删除高危能力后所有 agent 照常启动，不因残留的中间件或配置读取而崩溃，以便裁剪版本可以直接替换线上实例。

#### 验收标准

1. 当 `AgentManager._build_harness_config(row)` 为任一 agent 组装配置时，应当成功返回；返回值的 `middleware` 中不含 `BrowserProfileMiddleware`，`acp_delegate_enabled` 为 `False`，`tools` 中不含任何 `mobile_*` 工具。
2. 当 `OctopServer.start()` 启动时，服务应当直接以 `load_config` 读取配置，不执行移动能力探测，也不因探测回写 `config.json`。
3. `rg -n 'user_browser_profile|parse_octop_user_id|harness_settings_for_screenshots_dir|BrowserProfileMiddleware|ACPSettingsStore|mobile_tools|\.capabilities\.mobile' src` 应当始终没有输出。

### 需求 3：删除权限键并同批清洗存量值

**用户故事：** 作为管理员，我希望删除 `terminal`、`browser`、`desktop`、`mobile` 权限键后，仍能正常编辑持有这些残值的老用户，以便升级后用户管理不出错。

#### 验收标准

1. 当导入 `octop.infra.users.permissions` 时，`PERMISSIONS` 应当不含 `terminal`、`browser`、`desktop`、`mobile`，且没有任何键的 `category == "control"`；`ALL_PERMISSION_KEYS` 由 `PERMISSIONS` 派生，不需要单独修改。
2. 当 fork 迁移 `forkNNN_drop_removed_capability_data` 在含已删键的库上执行时，每个用户的 `permissions` 应当剔除这四个键、其余键保持原顺序，`settings` 表中键以 `acp_runners:user:` 开头的行应当被删除，其他 `settings` 行不变；在 SQLite 与 PostgreSQL 上再次执行该步骤，结果都不再变化。
3. 如果升级前某个用户的 `permissions` 含已删键，那么升级后管理员以 `GET /api/users/{id}` 读回的 `permissions` 原样调用 `PATCH /api/users/{id}` 时，接口应当返回 200，读回结果不含已删键。
4. `tests/unit/api/test_acl_gate_coverage.py` 的 `GATED_FILES` 应当始终只列仓库中存在的文件，并且 `uv run pytest tests/unit/api/test_acl_gate_coverage.py tests/unit/users/test_permissions.py tests/unit/api/test_permissions_api.py -q` 通过。

### 需求 4：host 级强制工具禁用，per-agent 配置不可绕过

**用户故事：** 作为行方安全评审人员，我希望已删能力对应的 harness 工具在主机层面被强制禁用，并且 agent 属主无法通过工具设置重新打开，以便"删除"不会退化成"只删了页面"。

#### 验收标准

1. 当 `_build_harness_config` 组装配置时，`harness_cfg.tools_disabled` 应当包含 `forced_disabled_tools(config)` 的全部名字，其中至少有 `REMOVED_CAPABILITY_TOOLS` 的 11 个名字：`browser_use`、`browser_control`、`desktop_screenshot`、`acp_runner`、`run_terminal_cmd`、`mobile_screenshot`、`mobile_tap`、`mobile_swipe`、`mobile_launch_app`、`mobile_ui_dump`、`mobile_handoff_to_user`。把 agent 配置的 `tools_disabled` 清空后，以上名字仍然全部在内。
2. 当 `persist_tools_disabled`、`persist_plugin_tools_config`、`sync_effective_tools_disabled` 或 `sync_tools_disabled` 触发热同步时，推给运行中 agent 的 `set_tools_disabled` 参数应当是强制集的超集。
3. 如果模型在主代理中调用强制集内的工具，那么 `ForcedToolGuardMiddleware` 应当直接返回 `status="error"` 的 `ToolMessage`，不调用下游 handler；调用强制集外的工具时原样放行。
4. 如果运行时的 `HarnessAgentConfig` 没有 `tools_disabled` 字段，而强制集非空，那么 `_build_harness_config` 应当抛出 `RuntimeError`，而不是静默跳过强制集。
5. 在子代理继承主代理工具集期间（deepagents general-purpose 子代理与工作区子代理），`browser_use` 与 `desktop_screenshot` 应当是中和桩：名字与参数 schema 与原工具相同，调用时返回错误文本，不启动浏览器、不截屏。如果已安装的 harness 不再以 `harness_agent.agent.browser_use` 与 `harness_agent.agent.build_desktop_screenshot_tool` 暴露这两个工具，那么中和函数应当抛出 `RuntimeError`，契约测试随之失败。

### 需求 5：工具设置与 HITL 目录不暴露、不可重开已删或强制禁用的工具

**用户故事：** 作为 agent 属主，我希望工具设置页与安全策略页只列出真实可用的工具，并且开不回被主机禁用的工具，以便界面与运行时行为一致。

#### 验收标准

1. 当请求 `GET /api/agents/{id}/tool-settings` 时，响应中应当不含需求 4.1 的 11 个已删工具名；如果某个内置工具因能力关闭而落在强制集内，那么它的条目应当是 `available=false`、`enabled=false`、`disableable=false`。
2. 如果以 `{"enabled": true}` 调用 `PATCH /api/agents/{id}/tool-settings/{tool}`，且 `{tool}` 在强制集内，那么接口应当返回 400，agent 配置里的 `tools_disabled` 保持不变。
3. 当请求 `GET /api/admin/security/defaults` 时，`hitl_tool_catalog` 应当不含强制集内的任何名字。

### 需求 6：能力开关配置

**用户故事：** 作为行方部署人员，我希望通过 `config.json` 与环境变量在进程启动时一次性决定每个可选能力是否开启，任何写错的名字都让启动失败，以便开关不会因为拼写错误而静默失效。

#### 验收标准

1. 当 `config.json` 含 `{"capabilities": {"<name>": {"enabled": false}}}`，且 `<name>` 在 `CAPABILITY_CATALOG` 中时，`load_config` 的结果应当使 `capability_enabled(cfg, "<name>")` 为 `False`；环境变量 `OCTOP_CAPABILITY_<NAME>` 应当覆盖文件中的值。缺省的能力取目录中的 `default_enabled`。
2. 如果 `capabilities` 段含未知名或保留名、某能力的值不是对象、`enabled` 不是 JSON 布尔，或者环境中存在未知名或保留名的 `OCTOP_CAPABILITY_*`、其值不是合法布尔，那么 `load_config` 应当抛出 `ValueError`，消息里含该名字；保留名的消息里还要含 owner spec。
3. 如果存量 `config.json` 含 `capabilities.mobile`（任意形状），那么 `load_config` 应当忽略它、记一条 WARNING，且不抛异常。
4. 当 `config.json` 不存在、`load_config` 首次写出默认文件时，文件中的 `capabilities` 段应当是 `{"<name>": {"enabled": <default>}}` 形状（本 spec 合入时目录为空，即 `{}`）。
5. 能力开关应当始终只由 `config.json` 与 `OCTOP_CAPABILITY_*` 在进程启动时决定：`app.routes` 中路径含 `capabilities` 的路由只有 `GET` 方法，应用任何代码路径都不回写 `config.json` 的 `capabilities` 段。
6. `RESERVED_CAPABILITIES` 应当始终至少预留 `agent_shell`（`w3-06`）、`content_security`（`p2-04`）、`intranet_im` 与 `intranet_connectors`（`p2-06`）、`frontend_controls`（`p2-07`），与 `CAPABILITY_CATALOG` 不相交，也不含 `LEGACY_CAPABILITY_KEYS` 中的 `mobile`；`octop.capability_catalog` 只导入标准库。

### 需求 7：能力开关的运行时闸门与只读查询

**用户故事：** 作为后续 spec 的开发者，我希望有统一的路由挂载闸门、依赖闸门和能力查询接口，以便新能力只需登记一行，就能在"路由、依赖、前端"三层同时生效。

#### 验收标准

1. 当某能力关闭时，经 `_mount_if_capable` 或 `FORK_CAPABILITY_MOUNTS` 登记的路由应当不出现在 `app.routes` 与 OpenAPI 中；能力开启时应当出现。如果该 router 同时登记在 w0-04 的 `_FORK_DISABLED_MOUNTS` 中，那么即使能力开启也不挂载。
2. 如果路由依赖 `require_capability(name)` 且该能力关闭，那么请求应当得到 HTTP 404 与 `NOT_FOUND` 错误信封；能力开启时正常处理。
3. 如果 `require_capability`、`_mount_if_capable` 或 `capability_enabled` 收到不在 `CAPABILITY_CATALOG` 中的名字（含保留名），那么它们应当在构造期抛出 `RuntimeError`：依赖工厂在被调用时抛，挂载在 `build_app` 时抛。
4. 当已登录用户请求 `GET /api/settings/capabilities` 时，接口应当返回 `{"capabilities": {"<name>": {"enabled": <bool>}}}`，覆盖目录中的全部名字，不含保留名；未登录请求返回 401。

### 需求 8：配置三触点门禁与重复块修复

**用户故事：** 作为后续 spec 的开发者，我希望漏写 `return OctopConfig(...)` 这一触点时 CI 直接变红，以便新配置键不会"配了但永远取默认值"。

#### 验收标准

1. 如果 `OctopConfig` 的某个 dataclass 字段没有作为关键字参数出现在 `load_config` 的 `return OctopConfig(...)` 中，那么 `tests/unit/test_config_touchpoints.py` 应当失败，并在失败信息里列出缺失的字段名；该检查对一段故意漏写字段的合成源码也能报出缺失项。
2. `load_config` 中应当始终只有一处 capabilities 解析调用：`rg -c '_parse_capabilities_section\(' src/octop/config.py` 输出 `2`（1 处定义加 1 处调用），并且 `rg -n 'OCTOP_ENABLE_MOBILE' src` 没有输出。

### 需求 9：agent 中间件注册式装配

**用户故事：** 作为 `w3-06`、`p2-04`、`p2-06` 的开发者，我希望新增 agent 中间件时只写一个模块并登记一行，不改 `manager.py`，以便多个 spec 不在同一段热点代码上冲突。

#### 验收标准

1. 当 `_build_harness_config` 组装中间件时，结果应当为 `[*outer 槽, *manager.py 中的上游列表, *inner 槽]`，每个槽内按 `order` 升序排列；`ForcedToolGuardMiddleware` 应当位于结果的首位。
2. 如果登记项的 `name` 重复，或它声明的 `capability` 不在目录中，那么装配应当抛出 `RuntimeError`；如果它声明的能力处于关闭状态，那么该项不参与装配；如果工厂返回 `None`，那么该项被跳过。
3. `manager.py` 应当始终只通过一处 `assemble_agent_middleware(` 调用接入登记表：`rg -c 'assemble_agent_middleware\(' src/octop/infra/agents/manager.py` 输出 `1`。

### 需求 10：前端删除已删能力的页面与入口，保留聊天 dock

**用户故事：** 作为行内用户，我希望界面上不再出现终端、远程桌面、远程手机、远程浏览器、ACP 的任何入口，而聊天页的文件预览、知识引用与工具界面照常可用，以便裁剪不影响日常使用。

#### 验收标准

1. 当执行 `cd dashboard && npx tsc -b && npm run build` 时，应当成功；`dashboard/src/pages/Control/{Terminal,RemoteBrowser,RemoteDesktop,RemoteAndroid,Workbench}/`、`dashboard/src/pages/Agent/ACP/`、`dashboard/src/components/{BrowserViewer,ChromeTabBar,BrowserWorkspace}/` 以及 `dashboard/src/api/modules/{browser,desktop,mobile,acp,terminalAi}.ts` 都应当不存在。
2. 当用户访问 `/workbench`、`/terminal`、`/remote-browser`、`/remote-desktop`、`/remote-phone`、`/remote-android`、`/acp`、`/personalization/acp` 时，路由表应当落到 `*` 对应的 NotFound 页；侧边栏不再有 `nav.control` 分组；agent 工具设置不再有 ACP tab。
3. 在聊天页 dock 打开期间，dock 应当支持且只支持 `files`、`file`、`knowledge`、`toolUi` 四类 tab；`ChatDockPanelShell` 与 `PanelMode` 位于 `dashboard/src/components/ChatDockPanelShell/`，其 vitest 用例与 `ChatDockPanels.keepAlive.test.tsx` 通过。
4. 聊天页应当不再渲染终端悬浮按钮、浏览器状态徽标与"打开浏览器"入口：`rg -n 'api/modules/browser|browserApi|useBrowserSessionState|toggleTerminalPanel|Control/Terminal' dashboard/src` 没有输出。
5. 以下与已删能力同名但无关的前端资产应当始终保留：`hooks/useServiceRestart.ts`（HTTPS 设置页重启流程）、`hooks/useDesktopChrome.ts`、`hooks/useIsMobile.ts`、`utils/desktopChrome.ts`、`utils/mobileDevice.ts`、`utils/browserSpeech.ts`、`pages/Chat/chatBrowserPanel.partial.less`（其中含保留 dock 与悬浮按钮的样式）。

### 需求 11：前端能力开关读取泛化

**用户故事：** 作为 `p2-06`、`p2-07` 的前端开发者，我希望有一个与能力名无关的 hook 读取服务端能力开关，以便新能力只需按名字取值。

#### 验收标准

1. 当多个组件同时挂载 `useServerCapabilities()` 时，hook 应当只发起一次 `GET /api/settings/capabilities`，返回 `{ caps, loading }`；`isCapabilityEnabled(caps, name)` 对 `caps` 中缺失的名字返回 `false`。
2. 如果该请求失败，那么 hook 应当返回空的 `caps` 与 `loading=false`，不抛出异常。
3. `dashboard/src/layouts/` 与 `dashboard/src/utils/permissions.ts` 应当始终不再引用 `mobileEnabled`、`workbench`、`remote-desktop`、`remote-phone`，以及 `PERM.workbench`、`PERM.browser`、`PERM.terminal`、`PERM.desktop`、`PERM.mobile`。

### 需求 12：依赖与构建同步收敛

**用户故事：** 作为构建与供应链负责人，我希望随能力删除一并移除不再需要的依赖与构建参数，以便离线制品与 SBOM 不再包含它们。

#### 验收标准

1. `pyproject.toml` 应当始终不再含 `playwright` 直接依赖、`[project.optional-dependencies].browser` 以及 `"src/octop/infra/desktop/scripts/**/*"`；执行 `make relock` 后 `uv lock --check` 通过，且 `uv.lock` 中不再有名为 `playwright` 的包。
2. `docker/Dockerfile` 应当始终不再含 `--extra browser` 与 `PLAYWRIGHT_BROWSERS_PATH`。
3. `dashboard/package.json` 与 `dashboard/package-lock.json` 应当始终不再含 `@xterm/` 前缀的包。

### 需求 13：遵守 i18n 与上游文件纪律

**用户故事：** 作为执行上游同步的维护者，我希望这次大规模裁剪不碰全仓 churn 最高的 locale 文件与上游变更记录，以便后续同步的冲突面最小。

#### 验收标准

1. 本 spec 应当始终不删除、不改写上游四份 locale JSON 中的任何键：`git diff --stat w1-02-base -- src/octop/i18n/en.json src/octop/i18n/zh.json dashboard/src/locales/en.json dashboard/src/locales/zh.json` 的输出为空，`uv run pytest tests/unit/i18n -q` 通过。
2. `ErrorCode` 枚举与 `_DEFAULT_STATUS` 应当始终不变（`git diff w1-02-base -- src/octop/infra/errors.py` 为空），本 spec 不新增 `ErrorCode`。
3. 本 spec 应当始终不修改 `CHANGELOG.md` 与 `docs/api.md`：`git diff --stat w1-02-base -- CHANGELOG.md docs/api.md` 的输出为空。
4. 当本 spec 的全部任务完成时，`make all` 与 `make check-frontend` 应当全绿。

### 需求 14：fork 文档与交付记录

**用户故事：** 作为行方评审与后续维护者，我希望本次删除与新框架在 fork 自己的文档里有完整记录，以便核对"哪些能力已不存在、开关如何配置"。

#### 验收标准

1. 当本 spec 合入时，`CHANGELOG-intranet.md` 应当有以 `w1-02-capability-trim` 开头的"移除 / 新增 / 变更 / 安全"条目；`docs/api-intranet.md` 的"已物理删除的上游路由"一节应当列出需求 1.1 的全部前缀，"fork 新增或变更的端点"一节说明 `GET /api/settings/capabilities` 的新响应形状，"鉴权与权限差异"一节列出删除的四个权限键。
2. `docs/intranet/capabilities.md` 应当始终说明配置形状、环境变量、保留名与 owner、legacy `mobile` 键的处理、fail-closed 规则、404 语义，以及"新增一个能力要改哪几处"的清单。
3. `AGENTS.md` 应当始终不再引用已删除的 `acp_settings` 与 `api/routers/browser/`，CLI 示例中不再列 `acp`：`rg -n 'acp_settings|routers/browser/|.acp. \|' AGENTS.md` 没有输出。
