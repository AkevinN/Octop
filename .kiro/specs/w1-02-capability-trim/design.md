# 设计文档：高危能力裁剪与横切框架

> spec：`w1-02-capability-trim` ｜ 波次：Wave 1 ｜ 基线：`757fd12` ｜ 预估：16 人日
> 前置：`w0-01-fork-migration-namespace`、`w0-02-ci-gates`、`w0-03-test-auth-baseline`、`w0-04-fork-isolation-points`、`w1-01-security-hotfix` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 概述

**结论：** 本 spec 分三条线推进，按"先删后建"的顺序合入。

1. **物理删除。** 五类能力按 ACP → Web 终端 → 远程手机 → 远程桌面 → 浏览器的顺序逐个删除，每删一类就是一个可独立提交、`make all` 全绿的 commit。浏览器必须与 `BrowserProfileMiddleware`、`browser_media` 的三个孤儿函数在同一个 commit 里删除，否则所有 agent 起不来。
2. **横切框架。** 新增同层于 `octop.config` 的纯数据模块 `octop.capability_catalog`（能力目录、保留名、legacy 键），以及 `infra/capabilities.py`（查询与强制工具集）。框架在三个层面生效：`api/deps.py::require_capability`（依赖闸门）、`api/app.py::_mount_if_capable` 加 fork 登记表 `api/capability_mounts.py`（挂载闸门）、`GET /api/settings/capabilities` 加前端 `useServerCapabilities`（只读查询）。agent 中间件改为"上游列表 + fork 登记表"装配，`manager.py` 只留一处调用。
3. **强制工具禁用分三层。** 第一层把 `forced_disabled_tools(config)` 并入 `harness_cfg.tools_disabled` 与唯一的热同步出口 `sync_tools_disabled`，决定模型能看到哪些工具。第二层是 `ForcedToolGuardMiddleware`，在主代理执行时拒绝强制集内的工具调用。第三层在进程启动时把 harness 的 `browser_use` 与 `desktop_screenshot` 替换为同名中和桩，覆盖不继承主代理中间件的子代理。

本 spec 不删 i18n 键，不增删 `ErrorCode`，不改上游 `CHANGELOG.md` 与 `docs/api.md` 正文。能力目录合入时为空，只登记后续 spec 的保留名。

## 现状

以下事实均在基线 `757fd12` 上用 `rg` / `sed -n` 核实过，行号只作提示。

### 待删除的后端入口

| 能力 | 路由 / 模块 | 关键事实 |
|---|---|---|
| Web 终端 | `src/octop/api/routers/terminal.py`（787 行） | `GET /agents/{agent_id}/terminal/context`（≈L445）、`WS /agents/{agent_id}/terminal/ws`（≈L500）；以 `subprocess.Popen(..., preexec_fn=posix_compat.setsid)`（≈L310-316）拉起 `[shell, "-i"]`（≈L291），无命令审计 |
| 远程浏览器 | `src/octop/api/routers/browser/`（`__init__`、`env`、`harness`、`record_replay`、`stream`、`uninstall`）、`src/octop/infra/browser/`（`__init__`、`setup`） | `/browser-stream/ws`（`stream.py` ≈L326）只调 `resolve_user_from_token`，没有权限键校验；另有 `/browser/install`、`/browser/record-replay/*` 等 12 条路由 |
| 远程桌面 | `src/octop/api/routers/desktop/`（`install`、`settings`、`status`、`stream`、`uninstall`）、`src/octop/infra/desktop/`（含 `scripts/linux`） | `/desktop-stream/ws` 提供截屏与键鼠注入 |
| 远程手机 | `src/octop/api/routers/mobile/`（`install`、`shell_ws`、`status`、`stream`）、`src/octop/infra/mobile/`（含 `config_probe.py`、`tools.py`、`docker_install.py`、`scripts/linux`）、`docker/docker-compose.mobile.yml` | `/mobile/adb/shell/ws` 给出 adb shell；compose 文件含 `privileged: true`（≈L29）、`network_mode: host`（≈L30）、挂载 `/var/run/docker.sock`（≈L33）与 `/dev/binderfs`（≈L34）、`OCTOP_ENABLE_MOBILE=1`（≈L45） |
| ACP | `src/octop/api/routers/acp.py`（303 行）、`src/octop/infra/agents/acp_settings.py`（144 行）、`src/octop/cli/commands/acp.py`、`src/octop/cli/registry.py` 的 `"acp"` 项（≈L34） | 内置 `opencode`、`codebuddy`、`claude_code`、`codex`、`kimi_code`、`cursor_cli`、`pi` 七个 runner（≈L25）；`ACPRunnerBody` 允许自定义 `command` / `args` / `env`；runner 存在 `settings` 表，键前缀为 `acp_runners:user:`（`acp_settings.py` ≈L16 `_SETTINGS_PREFIX`） |

`src/octop/api/app.py::build_app`（≈L101）：import 块中有 `acp`（≈L145）、`browser`（≈L154）、`desktop`（≈L159）、`mobile`（≈L171）、`terminal`（≈L185）；挂载项有 `acp`（≈L217）、`terminal`（≈L259）、`browser`（≈L262）、`desktop`（≈L263）；`enable_mobile`（≈L105-106）与 `if enable_mobile:` 块（≈L270-276）。`_mount_routers`（≈L72）是唯一的挂载入口；w0-04 合入后，它的循环改为经过 `without_fork_disabled`（见 w0-04 design.md）。`api/deps.py` 的 `_JWT_EXEMPT_PREFIXES` / `_JWT_EXEMPT_EXACT`（≈L66-88）里没有指向这五类路由的豁免项。`src/octop/api/openapi_meta.py` 的 `OPENAPI_TAGS` 中有 `terminal`（≈L143）、`browser`（≈L146）、`mobile`（≈L150）、`desktop`（≈L154）四个 tag。

### 致命耦合与必须保留的同名资产

- `src/octop/infra/agents/middleware/browser_profile.py`（71 行）第 ≈L15 行导入 `parse_octop_user_id` 与 `user_browser_profile`。`manager.py::_build_harness_config` 在 ≈L2798 导入它，并在 ≈L2819 把 `BrowserProfileMiddleware()` 无条件放进 `agent_middleware`。该目录没有 `__init__.py`。
- `src/octop/infra/utils/browser_media.py`：`parse_octop_user_id`（≈L21）与 `user_browser_profile`（≈L34）只被上述中间件与已删的 `routers/browser/*` 使用；`harness_settings_for_screenshots_dir`（≈L144）只被 `routers/browser/harness.py` 使用。其余函数仍有消费者：`api/routers/channels.py::_resolve_profiles_root`（≈L336-338）用 `octop_browser_profiles_dir`；`infra/gateway/media/backend_files.py`（≈L33、≈L302）用 `legacy_harness_screenshots_dir`；`manager.py::_agent_runtime_bundle`（≈L2568-2579）用另外四个函数；`infra/server.py::_boot_runtime`（≈L367-371）调用 `configure_browser_idle_timeout`。
- `src/octop/infra/utils/posix_compat.py` 的模块 docstring（≈L4）引用了 `octop.api.routers.terminal.terminal_supported`。删除后，`getpwuid`、`killpg`、`getpgid`、`setsid`、`sigkill`、`set_winsize`、`openpty`、`set_nonblock` 在 `src` 中不再有调用方（`setsid` 只剩 `tests/unit/utils/test_posix_compat.py`）；`geteuid`、`getuid`、`is_root`、`chown`、`getpwnam`、`read_available_posix` 仍被 `infra/setup/service.py`（≈L19、≈L26）与 `infra/utils/subprocess_io.py`（≈L18）使用。
- `tests/unit/desktop/test_stamp_version.py` 测的是仓库根 `desktop/src/build/stamp_version.py`（Wails 打包），与 `infra/desktop` 无关；同目录另外 6 个测试文件才导入 `octop.infra.desktop`。

### 配置与能力开关

- `src/octop/config.py`：`_VALID_MOBILE_BACKENDS`（≈L106）、`MobileCapabilities`（≈L109-117）、`CapabilitiesConfig`（≈L119-121，只有 `mobile` 字段）、`OctopConfig.capabilities`（≈L143）、`_defaults_for_file`（≈L152，用 `asdict(OctopConfig())` 生成首次写出的 `config.json`）、`_parse_mobile_capabilities`（≈L185-201）、`_parse_capabilities_section`（≈L203-209）。`load_config`（≈L412）中 capabilities 解析与 `OCTOP_ENABLE_MOBILE` 覆盖在 ≈L511-521 与 ≈L523-533 逐字重复两遍；`return OctopConfig(...)`（≈L592）在 ≈L615 传入 `capabilities=capabilities`。`load_config` 的 docstring 写明 `octop.config` 不得导入 `infra`。`_coerce_bool`（≈L283）遇到非法值只记 WARNING 并回落到默认值。
- `.capabilities.mobile` 的消费者：`api/app.py`（≈L105-106）、`api/routers/agent_tools.py`（≈L83）、`api/routers/settings.py::get_capabilities`（≈L67-83，响应模型 `MobileCapabilitiesResponse` ≈L58、`CapabilitiesResponse` ≈L63）、`infra/agents/manager.py`（≈L2734）、`infra/mobile/{config_probe,setup,tools}.py`。
- `infra/server.py` 在 ≈L26 导入、在 ≈L294 调用 `ensure_mobile_capabilities_probed(self.paths.config)`，后者会探测并回写 `config.json`（`infra/mobile/config_probe.py` ≈L41），是唯一的既有 capability 写回路径。`load_config` 已在 ≈L16 导入。
- 用 AST 比对 `dataclasses.fields(OctopConfig)` 与 `load_config` 中 `return OctopConfig(...)` 的关键字参数，基线上两者恰好相等，没有遗漏。

### 工具禁用与中间件

- `src/octop/infra/agents/tool_catalog.py`：`CRITICAL_TOOLS`（≈L10）；`_MOBILE_TOOLS`（≈L33-42）；`BUILTIN_TOOL_CATALOG`（≈L52-98）含 `browser_use`（≈L66）、`desktop_screenshot`（≈L67）、`acp_runner`（≈L81）与 6 个 `mobile_*`（≈L90-95）；`effective_tools_disabled`（≈L168）只读 per-agent 配置，最后减去 `CRITICAL_TOOLS`；`builtin_tool_available`（≈L185）带 `mobile_enabled` 形参与 `acp_runner` 分支。`browser_control` 与 `run_terminal_cmd` 不在目录中，只出现在 i18n 与前端。
- `manager.py`（2962 行）的 tools_disabled 路径：`persist_tools_disabled`（≈L1729）与 `persist_plugin_tools_config`（≈L1739）都走 `sync_effective_tools_disabled`（≈L2163），后者再调用唯一的推送出口 `sync_tools_disabled`（≈L2149，最终调用 `agent.set_tools_disabled`）；组装路径在 ≈L2948-2956（受 `if "tools_disabled" in _HARNESS_AGENT_CONFIG_FIELDS` 保护，字段集在 ≈L97 计算）。`api/routers/agent_tools.py` 的 PUT（≈L113）与 PATCH（≈L142）都经 `persist_tools_disabled` 写入；PATCH 对 `CRITICAL_TOOLS` 返回 `HTTPException(400)`（≈L162-166）。
- `manager.py` 的 ACP 与 mobile 装配：`ACPSettingsStore` 导入（≈L23）、类 docstring（≈L324）、`__init__` 与 `replace_persistence` 中的 `self._acp_settings`（≈L369、≈L403）、`acp_settings` property（≈L473-475）、`mobile_tools`（≈L2733-2741、≈L2782、≈L2832）、ACP 配置块（≈L2836-2846）、`acp_runners=` 与 `acp_delegate_enabled=`（≈L2938-2939）。
- `agent_middleware`（≈L2811-2826）是 8 项硬编码列表：`*plugin_middleware`、`TokenQuotaMiddleware`、`ReasoningRequestMiddleware`、`KnowledgeSearchHintMiddleware`、`BrowserProfileMiddleware`、`BinaryReadGuardMiddleware`、`WorkspaceImageMaterializeMiddleware(workspace=ws)`、`ThreadArtifactsMiddleware`，在 ≈L2936 以 `middleware=agent_middleware or None` 交给 harness。
- `api/routers/security.py::get_security_defaults`（≈L190-205）直接用 `i18n.domains.tools.hitl_tool_catalog()` 生成 `hitl_tool_catalog`；该目录来自 i18n 的 tools 标签，会列出 `browser_use` 等已删工具。

### 已安装 harness 的行为（`.venv` 中 `orcakit-harness-agent` 1.0.11，第三方代码）

- `harness_agent/agent.py` 在模块顶层 `from harness_agent.builtin.tools import browser_use, web_fetch`，并导入 `build_desktop_screenshot_tool`；`HarnessAgent._build_tools` 无条件把 `browser_use` 与 `build_desktop_screenshot_tool(self._workspace)` 放进工具集；只有 `cfg.acp_delegate_enabled` 为真时才构建 ACP 工具。`HarnessAgentConfig.acp_delegate_enabled` 默认值为 `False`。
- `harness_agent/middleware/tools_filter.py::ToolsFilterMiddleware` 只在 `wrap_model_call` 中按 `tools_disabled` 过滤 `ModelRequest.tools`，不拦截执行。
- `HarnessAgent._resolve_subagents` 的注释写明"Subagents do not inherit the parent's middleware chain"，省略 `tools:` 的子代理继承主代理工具集；`deepagents/graph.py::create_deep_agent` 自动追加的 general-purpose 子代理使用 `"tools": _tools` 与一条独立的中间件链。因此，`tools_disabled` 与 Octop 注入的中间件都不作用于子代理。

### 权限、测试与前端

- `src/octop/infra/users/permissions.py`：`PERMISSIONS` 中 ≈L56 是 control 分组注释，≈L57-60 是 `terminal` / `browser` / `desktop` / `mobile`，≈L61 是 admin 分组注释（不能误删）。`validate_permission_keys`（≈L237）对未知键抛 `ValueError`，`UserManager.set_permissions`（`infra/users/manager.py` ≈L519-525）把它映射成 400。存储形态：SQLite 为 `TEXT` JSON，PG 为 `JSONB`（`migrations/006_user_permissions*.sql`）；`UserRepo.set_permissions`（`infra/db/repos/users.py` ≈L304）两种方言用同一条 `UPDATE users SET permissions = ? WHERE id = ?`，`UserRepo.create` 不做键校验。
- 删除后会变红的既有测试：`tests/unit/api/test_acl_gate_coverage.py`（`GATED_FILES` 中 ≈L31-36、≈L41、≈L42 共 8 行）、`tests/unit/users/test_permissions.py`（≈L40-41、≈L64-69、≈L83-85）、`tests/unit/api/test_permissions_api.py`（≈L28、≈L36 构造 `require_permission("browser")`）、`tests/unit/agents/test_tool_catalog.py`（≈L69-79）、`tests/unit/cli/test_registry.py::test_acp_help_loads`（≈L24-29）、`tests/unit/test_config.py::test_loads_mobile_capabilities`（≈L392-410）、`tests/integration/test_agents_shared.py`（≈L124-128 断言 terminal/context 返回 403）、`tests/unit/agents/test_agent_manager.py::test_persist_tools_disabled_strips_critical_and_hot_syncs`（≈L1205-1226 精确断言 `set_tools_disabled` 的参数）；`tests/integration/conftest.py` 的 `env_acp_agent`（≈L183-190）与 `env_terminal`（≈L224-231）。`tests/conftest.py::_SLOW_TEST_MODULES`（≈L17）登记了 `tests/unit/browser/test_browser_setup.py`。`tests/unit/db/test_user_permissions_column.py` 直接调用 `UserRepo`，不经过键校验，**不会**变红。`tests/unit/i18n/test_desktop.py`、`test_mobile.py`、`test_tools.py` 只对 i18n bundle 的内容做断言（键存在、前后端 `tools` 全等、HITL 目录含 `browser_use`），不删键就仍然通过。
- `tests/unit/browser/test_browser_setup.py` 中覆盖保留函数的用例：`test_configure_browser_idle_timeout_updates_harness`（≈L29）、`test_octop_browser_profiles_dir_shared`（≈L328）、`test_configure_browser_profiles_dir_sets_env`（≈L343）、`test_legacy_profiles_migrated_once`（≈L356）。
- 前端：`components/BrowserWorkspace/ChatDockPanelShell.tsx` 从 `./index` 导入 `PanelMode`（≈L22），样式来自 `./ChatBrowserPanel.module.less`（≈L31）；保留的 `pages/Chat/components/ChatDockPanel.tsx`（≈L26、≈L346、≈L464）、`ChatDockPanels.tsx`（≈L1）、`hooks/useChatDockPanel.ts`（≈L2）都依赖 `PanelMode` 或该外壳。`pages/Chat/chatBrowserPanel.partial.less`（973 行，经 `index.module.less` ≈L7 导入）除浏览器徽标外，还含 `dockFileList`、`chatFloatActions`、`agentProfileBtn`、`chatPageWithBottomDock` 等保留样式。`useChatDockPanel.ts` 的 `DockTab`（≈L22-39）共 6 个变体。聊天页 `pages/Chat/index.tsx`（1478 行）与浏览器、终端、ACP 相关的位置：≈L39-47、≈L67、≈L121-124、≈L335-347、≈L364-405、≈L559-572、≈L727-732、≈L757-772、≈L1178-1183、≈L1276-1290、≈L1322 起的徽标、≈L1443。`useChatSend.ts` 在 ≈L247-293 动态导入 `api/modules/browser`。`MainLayout/index.tsx` 为 Workbench 做 keep-alive（≈L18、≈L30、≈L67-77、≈L293-318）。`hooks/useServerCapabilities.ts` 只返回 `{ mobileEnabled, loading }`，它唯一的保留消费者是 `layouts/Sidebar.tsx`（≈L265、≈L385）。`routes/index.tsx` 有 `path: "*"` 的 NotFound 路由（≈L286）。
- 依赖：`pyproject.toml` 中 `playwright>=1.40` 是直接依赖（≈L37），另有 `browser` extra（≈L66-68）、`desktop` extra（≈L70），hatch include 中有 `src/octop/infra/desktop/scripts/**/*`（≈L114）。`uv.lock` 中只有 octop 依赖 `playwright`；`harness-browser` 不依赖 playwright，但它是 `orcakit-harness-agent` 的硬依赖；`mss` / `pynput` 还会经 `orcakit-harness-agent[all]` 进来。`docker/Dockerfile` 在 ≈L110 与 ≈L127 执行 `uv sync ... --extra browser`，在 ≈L113 设置 `PLAYWRIGHT_BROWSERS_PATH`。`dashboard/package.json` 在 ≈L26-28 声明三个 `@xterm/*`；`dashboard/vite.config.ts` ≈L116 有一条 `@xterm` 分包规则，删除后该规则不再命中，无害。

## 方案

### 1. 删除边界

- **后端**：凡是 import 已删模块、挂载已删路由、登记已删 tag、注册已删 CLI 的代码，一律删除。被删除者孤立的 `browser_media` 函数（3 个）同批删除。`posix_compat.py` 只改 docstring，8 个孤儿函数登记不删（它们是 utils 纯包装，不构成入口；保留可以减小与上游的差异）。
- **前端**：以下三类删除：(a) 调用已删后端 API 的代码；(b) 通往已删能力的入口（路由、导航、按钮、dock tab、工具设置 tab）；(c) 因前两类删除而编译失败或成为孤儿文件的代码。**只对已删工具名做被动渲染或摘要的分支保留不动**：ACP 权限卡片链（`plugins/toolRenderers/types.ts` 的 `onAcpPermissionSelect` 可选 prop、`DefaultToolRenderer.tsx` 的 ACP 分支、`utils/parseAcpPermission.ts`、5 个 Chat 组件的透传）、`summarizeHitlAction.ts` 的 `BROWSER_TOOLS`、`messageContent.ts` 的 `isBrowserToolName`、`constants.ts` 的 `BROWSER_TOOL_NAMES`、`ToolsPanel.tsx` 的图标映射、`ChatInput` / `ChatInputActionsRow` 的录制可选 props、`useChatDockPanel.ts` 的两个 legacy localStorage 键。这些工具已被强制禁用、永远不会产生输出，聊天页也不再传入回调，所以它们不会渲染。保留它们，可以让上游高 churn 的 Chat 组件少改 9 个文件。
- **数据**：权限键残值与 `acp_runners:user:*` 行由 fork 迁移清除；`agents.config_json` 中残留的 `acp` 段不清洗（代码不再读取，见"待行方确认"）。
- **i18n、ErrorCode、上游文档**：一律不动（全局约束 1.2 与第 5 节）。

### 2. 能力开关框架

**分层。** `octop.config` 不得导入 `infra`，所以能力目录必须放在与 `config.py` 同层的纯标准库模块 `src/octop/capability_catalog.py`（新增）。`config.py` 从这里取目录并解析；`infra/capabilities.py`（新增）在其上提供查询与强制工具集；api 层只依赖 `infra/capabilities.py`。源分析把目录放进 `infra/capabilities.py` 再由 `config.py` 导入，这违反 AGENTS.md §5，已改正。

**目录与保留名。** `CAPABILITY_CATALOG` 在本 spec 合入时为空。能力开关只有在同一个 spec 里把"路由、工具、中间件"全部接好之后才进入目录，避免出现"开关配了但只关了一半"的状态。后续 spec 的名字先登记在 `RESERVED_CAPABILITIES`（名字到 owner spec 的映射），配置里出现保留名时 fail closed。owner spec 落地时，把名字从保留表移进目录，写上默认值与工具名，并接好挂载或中间件。

**解析规则（fail closed）。** 解析在 `capability_catalog.parse_capability_flags(raw, environ)` 中完成，`config.py` 只调用一次：

1. `raw` 为 `None` 时视为 `{}`；不是对象时抛 `ValueError`。
2. 逐键处理：`LEGACY_CAPABILITY_KEYS`（`mobile`）记一条 WARNING 后跳过；目录内的名字要求值为对象且 `enabled` 为 JSON 布尔，否则抛 `ValueError`；保留名抛 `ValueError`，消息含 owner spec；其他名字抛 `ValueError("unknown capability ...")`。
3. 扫描环境中全部 `OCTOP_CAPABILITY_` 前缀的变量：把后缀转成小写作为能力名，按同样规则处理未知名与保留名；值只接受 `1/true/yes/on` 与 `0/false/no/off`（不区分大小写），否则抛 `ValueError`。这里故意不复用 `_coerce_bool` 的"非法值回落默认"语义，报错信息只含变量名，不回显变量值。环境变量覆盖文件值。
4. 目录中缺省的名字取 `default_enabled`。结果是覆盖目录全部名字的 `dict[str, bool]`。

**只读。** 能力开关没有任何写入 API，也不再有启动期回写。删除 `ensure_mobile_capabilities_probed` 之后，应用不会修改 `config.json` 的 `capabilities` 段。`load_config` 在文件不存在时写出一份默认文件，这是既有行为，保留。

**三个运行时闸门。**

- 挂载闸门：`app.py::_mount_if_capable(app, cfg, capability, mounts)` 校验名字在目录中、能力开启时才调用 `_mount_routers`，因此 w0-04 的 `_FORK_DISABLED_MOUNTS` 仍然优先于能力开关。fork 路由登记在 `api/capability_mounts.py::FORK_CAPABILITY_MOUNTS`（`"module:attr"` 引用，由 w0-04 的 `resolve_router_ref` 解析）；`build_app` 在主挂载列表之后，对登记表逐项调用 `_mount_if_capable`。后续 spec 只需在登记表加一行，不改 `app.py`。
- 依赖闸门：`deps.require_capability(name)` 仿照 `require_permission`（`deps.py` ≈L201）的写法，工厂被调用时校验名字，运行时读 `server.services.config`。能力关闭时抛 `OctopError(ErrorCode.NOT_FOUND, "not found")`，以 INFO 级别记录能力名，响应里不带能力名。这样与"路由不挂载"的 404 表现一致（等保探测口径）。它用于同一 router 内部分端点受控、或 WebSocket 这类无法整体不挂载的场景。
- 只读查询：`GET /api/settings/capabilities` 返回 `{"capabilities": {name: {"enabled": bool}}}`，保留原有的 `Depends(current_user)`。

**前端。** `useServerCapabilities()` 泛化为返回 `{ caps, loading }`，保留单次 in-flight 合并；新增纯函数 `isCapabilityEnabled(caps, name)`，缺失时返回 `false`。删除远程桌面后，`buildNavSections` 的 `opts.mobileEnabled` 没有了用途，因此去掉 `opts` 形参，`Sidebar.tsx` 不再调用该 hook。需要按能力隐藏导航的后续 spec（`p2-06`、`p2-07`）再给 `NavItem` 加可选 `capability` 字段；这是新增可选参数，不是破坏性变更。本 spec 不渲染能力显示名，所以不新增 overlay 文案。

### 3. 强制工具禁用

`infra/capabilities.py`：

```python
REMOVED_CAPABILITY_TOOLS: frozenset[str]  # 需求 4.1 的 11 个名字，恒定在强制集内
def forced_disabled_tools(cfg: OctopConfig | None) -> frozenset[str]:
    """REMOVED_CAPABILITY_TOOLS ∪ 所有关闭能力的 CapabilitySpec.tools。"""
```

强制集与 `CRITICAL_TOOLS` 必须不相交，由单测保证。三层落点如下：

1. **模型可见层。** `manager.py::_build_harness_config` 在 ≈L2951 把 `effective_tools_disabled(...)` 与 `forced_disabled_tools(self._config)` 取并集；如果 `tools_disabled` 不在 `_HARNESS_AGENT_CONFIG_FIELDS` 中而强制集非空，就抛 `RuntimeError`。`manager.py::sync_tools_disabled` 在调用 setter 前并入强制集；它是 `persist_tools_disabled`、`persist_plugin_tools_config`、`sync_effective_tools_disabled` 三条路径唯一的推送出口，所以一处即可覆盖全部热同步路径。`tool_catalog.effective_tools_disabled` 与 `normalize_tools_disabled` 不改，agent 配置里持久化的仍是属主自己的选择，强制集只在出口叠加。
2. **执行层（主代理）。** 新增 `infra/agents/middleware/forced_tool_guard.py::ForcedToolGuardMiddleware(denied)`，写法照 `browser_profile.py` 的 `wrap_tool_call` / `awrap_tool_call`。工具名命中强制集时，返回 `ToolMessage(status="error", content=...)`，不调用 handler。它经注册表放在 outer 槽 `order=0`，即 Octop 中间件列表的首位。这段文本给模型看，沿用 `browser_profile.py` 的英文常量先例，不进 i18n。
3. **子代理层（已删工具）。** 新增 `infra/agents/harness_removed_tools.py::neutralize_removed_harness_tools()`：把 `harness_agent.agent.browser_use` 替换为同名、同参数 schema 的 `StructuredTool`，调用时返回 "capability removed in this build"；把 `harness_agent.agent.build_desktop_screenshot_tool` 包装为"构建原工具、返回同名同 schema 的中和桩"的工厂。函数幂等；目标属性缺失时抛 `RuntimeError`（harness 升级改名时 fail closed）。`OctopServer._boot_runtime` 在创建 `AgentManager` 之前调用一次。这是过渡措施：`w2-01` 把 harness 导入行内 Git 后，由内部分支让子代理遵守 `tools_disabled` 并移除这两个内置工具，届时删除本模块。`acp_runner` 在 `acp_delegate_enabled=False` 时不会被构建，`mobile_*` 由已删的 Octop 代码注册，`browser_control` 与 `run_terminal_cmd` 在当前 harness 中不存在，所以这四类不需要中和。

**工具设置与 HITL。** `tool_catalog.py` 从 `BUILTIN_TOOL_CATALOG` 删去 9 个已删条目（`browser_use`、`desktop_screenshot`、`acp_runner`、6 个 `mobile_*`）与 `_MOBILE_TOOLS`；`builtin_tool_available(name, *, agent_cfg, forced=frozenset())` 去掉 `mobile_enabled` 形参与 `acp_runner` 分支，命中 `forced` 时返回 `False`。`agent_tools.py` 的 GET 对强制集内的条目返回 `available=false`、`enabled=false`、`disableable=false`；PATCH 以 `enabled=true` 请求强制集内的内置工具时返回 `HTTPException(400)`，与既有 `CRITICAL_TOOLS` 的处理对称。PUT 不拦截，因为它提交的是禁用清单，强制集在出口叠加，属主无论怎么提交都开不回来。`security.py::get_security_defaults` 过滤 `hitl_tool_catalog()` 的结果，剔除强制集；`i18n.domains.tools` 不改，因为 i18n 层不得导入 infra。

### 4. agent 中间件注册式装配

新增 `src/octop/infra/agents/middleware_registry.py`。`manager.py` 保留上游的硬编码列表（只删去 `BrowserProfileMiddleware` 一项），在列表之后加一条语句：

```python
agent_middleware = assemble_agent_middleware(
    agent_middleware, AgentMiddlewareContext(row=row, config=self._config, repos=self._repos, paths=self._paths, workspace=ws, harness_workspace=harness_workspace)
)
```

上游以后往列表里加中间件时照常合并，fork 的中间件全部登记在 `FORK_AGENT_MIDDLEWARE`。这比"把整条列表搬进 fork 注册表"的冲突面更小。装配顺序为 `[*outer, *upstream, *inner]`，槽内按 `order` 升序。登记项可以声明 `capability`，能力关闭时不装配；工厂返回 `None` 时跳过；`name` 重复或能力名未知时抛 `RuntimeError`。

### 5. 配置三触点门禁

新增 `tests/unit/test_config_touchpoints.py`，内含可复用的检查函数 `missing_constructor_fields(source: str, dataclass_fields: set[str]) -> set[str]`：解析源码，找到 `load_config` 中 `return OctopConfig(...)` 调用的关键字参数集合，与 dataclass 字段取差。用例有两个：对真实 `config.py` 断言差集为空；对一段故意漏写字段的合成源码断言能报出缺失字段，证明检查本身有效。env 覆盖块无法机械校验（不是每个字段都有 env），仍靠评审与 tasks.md 的三触点清单。重复块随 capabilities 解析改造一并删除，`load_config` 中只留一处 `_parse_capabilities_section(...)` 调用。

### 6. 前端聊天 dock 手术

1. 先把 `ChatDockPanelShell.tsx`、`ChatDockPanelShell.test.tsx`、`ChatBrowserPanel.module.less`（改名为 `ChatDockPanelShell.module.less`，类名不变）用 `git mv` 迁到 `components/ChatDockPanelShell/`，并把 `PanelMode` 抽到同目录的 `types.ts`。`ChatDockPanel.tsx`、`ChatDockPanels.tsx`、`useChatDockPanel.ts` 改为从新位置导入。这一步行为不变，可以单独提交。
2. 再收窄 `DockTab` 联合类型，删去 `browser` 与 `terminal` 两个变体，让 `tsc` 把全部分支点报出来，逐个删除 `ChatDockPanel.tsx`、`ChatDockPanels.tsx` 与聊天页中的对应分支。
3. `ChatDockPanels.keepAlive.test.tsx` 改写为以 `files` tab 为样本（不整删），`useChatDockPanel.test.ts` 中借用 browser tab 的通用用例改用 `file` / `knowledge` tab。

### 7. 源分析的纠正

| 源分析原条目 | 核实结论 | 本 spec 处理 |
|---|---|---|
| 删除 `pages/Chat/chatBrowserPanel.partial.less` 与 `index.module.less` 的 `@import` | 该文件含保留 dock 与悬浮按钮样式 | 保留，不删 |
| 从 `ChatDockPanels.tsx` 删 `PanelMode` 导入 | `PanelMode` 仍是 dock 模式的类型 | 随外壳迁出，改导入路径 |
| 外壳迁移只搬两个文件 | 外壳依赖 `./index` 的 `PanelMode` 与 `ChatBrowserPanel.module.less` | 一并迁出 |
| 修改 `tests/unit/db/test_user_permissions_column.py` | `UserRepo` 不做键校验 | 不改 |
| `posix_compat.py` 有 7 个孤儿函数 | 另有 `setsid`，共 8 个 | 只改 docstring，登记不删 |
| "不需要新迁移" | 与全局约束 1.6 冲突 | 写 fork 迁移清洗存量值 |
| i18n 四份 JSON 约 1150 个删键；删 `DESKTOP_*` 两个 `ErrorCode`；删 `test_desktop.py` / `test_mobile.py` | 与全局约束 1.2 冲突 | 全部作废 |
| `require_capability` 抛 `FORBIDDEN` 带能力名 | 与"不挂载即 404"不一致，还会泄露能力名 | 改为 `NOT_FOUND`，待行方确认 |
| 首批目录接 13 个保留能力 | 多数能力的关闭不止于路由（通道网关、调度器、已安装插件），只关路由就是"半关" | 目录合入时为空，只登记保留名 |
| 能力目录放在 `infra/capabilities.py` 且被 `config.py` 导入 | 违反 `octop.config` 不导入 `infra` 的分层 | 目录放在 `octop/capability_catalog.py` |
| 改 `docs/api.md`、`CHANGELOG.md`、`docs/configuration.md` 等上游文档 | 与 w0-04 规则冲突 | 改写 fork 文档 |
| 漏列 `tests/integration/test_agents_shared.py` | 它断言 terminal/context 返回 403，删除后变成 404 | 删除该段断言 |
| 未识别子代理绕过 | harness 子代理不继承中间件与 `tools_disabled` | 加中和层，交接 `w2-01` / `w3-06` |

## 组件与接口

| 路径 | 动作 | 内容 |
|---|---|---|
| `src/octop/capability_catalog.py` | 新增 | `CapabilitySpec`、`CAPABILITY_CATALOG`、`RESERVED_CAPABILITIES`、`LEGACY_CAPABILITY_KEYS`、`ENV_PREFIX`、`parse_capability_flags`、`capability_file_defaults`；只用标准库 |
| `src/octop/config.py` | 修改 | 删 `_VALID_MOBILE_BACKENDS`、`MobileCapabilities`、`_parse_mobile_capabilities` 与两段重复块；重定义 `CapabilitiesConfig`；`_parse_capabilities_section` 改为委托；`_defaults_for_file` 改写 `capabilities` 键 |
| `src/octop/infra/capabilities.py` | 新增 | `capability_enabled`、`enabled_capabilities`、`REMOVED_CAPABILITY_TOOLS`、`forced_disabled_tools` |
| `src/octop/api/deps.py` | 修改 | 新增 `require_capability` |
| `src/octop/api/capability_mounts.py` | 新增 | `CapabilityMount`、`FORK_CAPABILITY_MOUNTS = ()` |
| `src/octop/api/app.py` | 修改 | 删五类 import 与挂载、`enable_mobile` 与 `if enable_mobile:` 块；新增 `_mount_if_capable` 与登记表循环 |
| `src/octop/api/routers/settings.py` | 修改 | `CapabilityView`、`CapabilitiesResponse` 泛化；删 `MobileCapabilitiesResponse` |
| `src/octop/api/routers/agent_tools.py` | 修改 | 用 `forced=` 替代 `mobile_enabled`；强制集条目展示与 PATCH 400 |
| `src/octop/api/routers/security.py` | 修改 | `hitl_tool_catalog` 过滤强制集 |
| `src/octop/infra/agents/tool_catalog.py` | 修改 | 删 9 个条目与 `_MOBILE_TOOLS`；`builtin_tool_available` 改签名 |
| `src/octop/infra/agents/middleware_registry.py` | 新增 | `AgentMiddlewareContext`、`AgentMiddlewareSpec`、`FORK_AGENT_MIDDLEWARE`、`assemble_agent_middleware` |
| `src/octop/infra/agents/middleware/forced_tool_guard.py` | 新增 | `ForcedToolGuardMiddleware` |
| `src/octop/infra/agents/harness_removed_tools.py` | 新增 | `neutralize_removed_harness_tools` |
| `src/octop/infra/agents/manager.py` | 修改 | 删 ACP、mobile 与 `BrowserProfileMiddleware` 相关代码；`sync_tools_disabled` 与组装路径并入强制集；一处 `assemble_agent_middleware` 调用；docstring 去掉 `acp_settings` |
| `src/octop/infra/server.py` | 修改 | 删 `ensure_mobile_capabilities_probed` 的导入与调用，改为 `load_config`；在 `_boot_runtime` 中调用 `neutralize_removed_harness_tools()` |
| `src/octop/infra/utils/browser_media.py` | 修改 | 删 `parse_octop_user_id`、`user_browser_profile`、`harness_settings_for_screenshots_dir` |
| `src/octop/infra/utils/posix_compat.py` | 修改 | 只改模块 docstring |
| `src/octop/infra/users/permissions.py` | 修改 | 删 ≈L56-60，同步模块 docstring 的举例（≈L3、≈L7） |
| `src/octop/api/openapi_meta.py` | 修改 | 删四个 tag |
| `src/octop/cli/registry.py` | 修改 | 删 `"acp"` 项 |
| `src/octop/infra/db/fork_steps.py` | 新增 | `strip_permission_keys(conn, dialect, removed)`（可复用）与本 spec 的步骤 `drop_removed_capability_permissions` |
| `src/octop/infra/db/fork_migrate.py` | 修改（w0-01 的文件） | `_FORK_PY_STEPS` 登记一项 |
| `src/octop/infra/db/migrations/forkNNN_drop_removed_capability_data.sql` / `.pg.sql` | 新增 | 删除 `acp_runners:user:*` 行 |

关键签名如下（本 spec 定稿，后续 spec 只消费）：

```python
# src/octop/capability_catalog.py —— 只导入标准库
ENV_PREFIX = "OCTOP_CAPABILITY_"

@dataclass(frozen=True)
class CapabilitySpec:
    name: str                      # 小写蛇形，与 CAPABILITY_CATALOG 的键一致
    default_enabled: bool
    owner: str                     # 接入该能力的 spec 目录名
    tools: frozenset[str] = frozenset()   # 能力关闭时并入强制集的 harness 工具名

    @property
    def env_var(self) -> str: ...  # f"{ENV_PREFIX}{self.name.upper()}"

CAPABILITY_CATALOG: dict[str, CapabilitySpec] = {}
RESERVED_CAPABILITIES: dict[str, str] = {
    "agent_shell": "w3-06-agent-execution-hardening",
    "content_security": "p2-04-content-security-pii",
    "intranet_im": "p2-06-intranet-integration",
    "intranet_connectors": "p2-06-intranet-integration",
    "frontend_controls": "p2-07-frontend-controls",
}
LEGACY_CAPABILITY_KEYS: frozenset[str] = frozenset({"mobile"})

def parse_capability_flags(raw: object, environ: Mapping[str, str]) -> dict[str, bool]: ...
def capability_file_defaults() -> dict[str, dict[str, bool]]: ...

# src/octop/config.py
@dataclass(frozen=True)
class CapabilitiesConfig:
    enabled: dict[str, bool] = field(default_factory=dict)

# src/octop/infra/capabilities.py
def capability_enabled(cfg: OctopConfig | None, name: str) -> bool: ...   # 未知名或保留名 -> RuntimeError；cfg 为 None 时取默认值
def enabled_capabilities(cfg: OctopConfig | None) -> dict[str, bool]: ...
REMOVED_CAPABILITY_TOOLS: frozenset[str]
def forced_disabled_tools(cfg: OctopConfig | None) -> frozenset[str]: ...

# src/octop/api/deps.py
def require_capability(name: str) -> Callable[..., Awaitable[None]]: ...

# src/octop/api/app.py
def _mount_if_capable(app: FastAPI, cfg: OctopConfig | None, capability: str, mounts: Sequence[_RouterMount]) -> None: ...

# src/octop/api/capability_mounts.py
@dataclass(frozen=True)
class CapabilityMount:
    capability: str
    router_ref: str        # "module:attr"，由 w0-04 的 resolve_router_ref 解析
    prefix: str
    tags: tuple[str, ...]
FORK_CAPABILITY_MOUNTS: tuple[CapabilityMount, ...] = ()

# src/octop/infra/agents/middleware_registry.py
@dataclass(frozen=True)
class AgentMiddlewareContext:
    row: AgentRow
    config: OctopConfig
    repos: RepoBundle
    paths: PathLayout
    workspace: Any            # BackendWorkspace（manager 中的 ws）
    harness_workspace: Any

@dataclass(frozen=True)
class AgentMiddlewareSpec:
    name: str
    slot: Literal["outer", "inner"]
    order: int
    factory: Callable[[AgentMiddlewareContext], Any | None]
    capability: str | None = None

FORK_AGENT_MIDDLEWARE: tuple[AgentMiddlewareSpec, ...]   # 本 spec 登记 forced_tool_guard（outer, 0）
def assemble_agent_middleware(upstream: Sequence[Any], ctx: AgentMiddlewareContext) -> list[Any]: ...

# src/octop/infra/agents/middleware/forced_tool_guard.py
class ForcedToolGuardMiddleware(AgentMiddleware[Any, Any]):
    def __init__(self, denied: frozenset[str]) -> None: ...

# src/octop/infra/agents/harness_removed_tools.py
def neutralize_removed_harness_tools() -> None: ...       # 幂等；目标属性缺失 -> RuntimeError

# src/octop/infra/agents/tool_catalog.py
def builtin_tool_available(name: str, *, agent_cfg: Mapping[str, Any], forced: frozenset[str] = frozenset()) -> bool: ...

# src/octop/infra/db/fork_steps.py
def strip_permission_keys(conn: Any, dialect: str, removed: frozenset[str]) -> None: ...
def drop_removed_capability_permissions(conn: Any, dialect: str) -> None: ...  # 固定剔除 terminal/browser/desktop/mobile
```

前端接口：

```ts
// dashboard/src/api/modules/settings.ts
export type OctopCapabilitiesSettings = {
  capabilities: Record<string, { enabled: boolean }>;
};
// dashboard/src/hooks/useServerCapabilities.ts
export function useServerCapabilities(): { caps: Record<string, { enabled: boolean }>; loading: boolean };
export function isCapabilityEnabled(caps: Record<string, { enabled: boolean }>, name: string): boolean;
// dashboard/src/layouts/sidebarNav.tsx
export function buildNavSections(user: OctopUser | null): NavSection[];
// dashboard/src/components/ChatDockPanelShell/types.ts
export type PanelMode = "hidden" | "bottom" | "right" | "popup";
```

## 数据模型

不新增表或列。新增一条 fork 迁移 `forkNNN_drop_removed_capability_data`，号不预占，合入 fork 主干时取下一个可用号：

- `src/octop/infra/db/migrations/forkNNN_drop_removed_capability_data.sql` 与同名 `.pg.sql`，内容相同：
  `DELETE FROM settings WHERE substr(key, 1, 17) = 'acp_runners:user:';`
  （`'acp_runners:user:'` 恰为 17 个字符；用 `substr` 而不用 `LIKE`，是为了避开 `_` 通配。）
- 在 `_FORK_PY_STEPS` 中登记同一版本号的 Python 步骤 `drop_removed_capability_permissions`，它调用通用函数 `strip_permission_keys(conn, dialect, frozenset({"terminal", "browser", "desktop", "mobile"}))`：
  - 用当前事务连接判断 `users` 表与 `permissions` 列存在（SQLite 用 `PRAGMA table_info(users)`，PG 查 `information_schema.columns`），缺失就返回，以兼容 w0-01 提到的 users-only 残缺库；
  - `SELECT id, permissions FROM users`，同时接受 JSON 文本（SQLite）与已解码列表（PG）；
  - 对含已删键的行，以与 `UserRepo.set_permissions` 相同的 `UPDATE users SET permissions = ? WHERE id = ?` 写回 `json.dumps(剩余键)`，保持原顺序；
  - 只用 `?` 占位，不提交事务，天然幂等。
- 迁移只写死键名，不导入 `infra/users/permissions.py`：`infra/db` 不依赖上层包，迁移内容也应当是冻结的快照。`w1-03`、`w1-05` 删键时复用 `strip_permission_keys`，各自登记自己的版本号。
- 回填：无。`_schema_version` 与 8 个测试文件里的 `== 15` 断言不变。

## 配置

| 项 | 变化 | `config.py` 三触点 |
|---|---|---|
| `capabilities` 段 | 形状改为 `{"<name>": {"enabled": <bool>}}`；`mobile` 子键作为 legacy 忽略；合入时目录为空 | ① 字段 `OctopConfig.capabilities: CapabilitiesConfig`（≈L143）保留，`CapabilitiesConfig`（≈L119-121）重定义为 `enabled: dict[str, bool]`；② env 覆盖块：删去 ≈L511-533 两段重复代码，改为一行 `capabilities = _parse_capabilities_section(raw.get("capabilities"), os.environ)`；③ 构造 `capabilities=capabilities`（≈L615）不变，由新门禁测试保证 |
| `OCTOP_CAPABILITY_<NAME>` | 新增的环境变量族，只接受目录内的名字 | 同上 ②，由 `parse_capability_flags` 扫描 |
| `OCTOP_ENABLE_MOBILE` | 删除，设置后不再有任何效果 | 同上 ② |
| `_defaults_for_file`（≈L152） | `asdict` 会把 `CapabilitiesConfig` 序列化成 `{"enabled": {...}}`，与文件形状不符，因此在 `data["capabilities"]` 处改写为 `capability_file_defaults()` | 这是 steering "`_defaults_for_file` 不需要改"规则的唯一例外，原因是该段的形状不再与 dataclass 同构 |
| `browser_idle_timeout_minutes` | 不变，仍用于通道扫码 Chrome profile，去留归 `w1-05` | 无 |

## 错误处理

- **不新增 `ErrorCode`。** `require_capability` 复用 `NOT_FOUND`（`_DEFAULT_STATUS` 中已登记为 404）；工具设置 PATCH 沿用 `HTTPException(400)`，与既有 `CRITICAL_TOOLS` 一致；配置错误在 `load_config` 抛 `ValueError`，表现为启动失败，与既有的损坏 `config.json` 处理一致。
- **不删除 `ErrorCode`。** `DESKTOP_SESSION_LIMIT` 与 `DESKTOP_CAPTURE_FAILED`（`errors.py` ≈L85-86，`_DEFAULT_STATUS` ≈L187-188）保留为孤儿码，否则 `tests/unit/i18n/test_errors.py` 的三方相等门禁会要求同步删除 i18n 键。
- 编程错误（未知能力名、登记表重名、harness 目标属性缺失、harness 缺 `tools_disabled` 字段）一律抛 `RuntimeError`，在 `build_app`、依赖工厂构造或 agent 组装时暴露。
- `ForcedToolGuardMiddleware` 与中和桩向模型返回错误文本，不抛异常，避免中断对话。

## 安全考虑

- **攻击面收缩：** 删除 5 个 WebSocket（终端 PTY、浏览器 CDP 流、桌面流、手机流、adb shell），其中浏览器流是唯一不校验权限键的 WS；删除 ACP 的任意命令 runner 与 `octop acp` stdio 入口；删除启动期回写 `config.json` 的移动探测；删除特权 compose 文件与运行期 Chromium 下载入口。
- **强制禁用不可绕过：** 强制集在推送出口与组装出口叠加，不依赖 agent 配置；PATCH 明确拒绝；主代理有执行守卫；子代理面对的是中和桩。**残余风险**：能力关闭型工具（将来的 `execute` 等）在子代理中仍可能可达，必须由 `w2-01` 的 harness 补丁或 `w3-06` 的执行后端方案覆盖（见"与其他 spec 的交接"）。
- **开关 fail closed：** 未知名、保留名、非法布尔、未知的 `OCTOP_CAPABILITY_*` 都会让启动失败；报错不回显环境变量值。没有运行期写入接口。
- **数据最小化：** `acp_runners:user:*` 行里可能有外部 CLI 的 `env` 明文凭据，随能力删除一并清除。
- **信息暴露：** 能力关闭统一返回 404，不在响应中暴露能力名；`GET /api/settings/capabilities` 仍然需要登录。
- **分层：** `octop.capability_catalog` 只导入标准库，由测试守护；`infra/db/fork_steps.py` 不导入上层包。

## 测试策略

| 类别 | 内容 | 本地命令 |
|---|---|---|
| 单测：三触点 | `tests/unit/test_config_touchpoints.py`：真实 `config.py` 无遗漏；合成源码能报出缺失字段 | `uv run pytest tests/unit/test_config_touchpoints.py -q` |
| 单测：能力配置 | `tests/unit/test_capabilities_config.py`：默认值、文件覆盖、env 覆盖、未知名、保留名（消息含 owner）、非对象、非布尔、非法 env 值、未知 env 名、legacy `mobile` 忽略与 WARNING、默认文件形状、目录与保留名不相交、`capability_catalog` 只导入标准库；用 `monkeypatch.setitem(CAPABILITY_CATALOG, ...)` 注入测试能力。`tests/unit/test_config.py` 中的 mobile 用例改为 legacy 忽略用例 | `uv run pytest tests/unit/test_capabilities_config.py tests/unit/test_config.py -q` |
| 单测：强制集 | `tests/unit/test_capabilities.py`：`REMOVED_CAPABILITY_TOOLS` 恰为 11 个名字；关闭的测试能力的 `tools` 并入强制集；强制集与 `CRITICAL_TOOLS` 不相交；未知名与保留名抛 `RuntimeError` | `uv run pytest tests/unit/test_capabilities.py -q` |
| 单测：闸门 | `tests/unit/api/test_capability_gate.py`：`_mount_if_capable` 开关两态、`_FORK_DISABLED_MOUNTS` 优先、未知名 `RuntimeError`；`require_capability` 开关两态与 404 信封；`FORK_CAPABILITY_MOUNTS` 登记生效；`get_capabilities` 的响应形状。测试 router 放在 `tests/support/capability_probe.py` | `uv run pytest tests/unit/api/test_capability_gate.py -q` |
| 单测：agent | `tests/unit/agents/test_middleware_registry.py`（槽位顺序、重名、未知能力、能力关闭跳过、工厂返回 `None`）；`tests/unit/agents/test_forced_tool_guard.py`（拒绝与放行，同步与异步）；`tests/unit/agents/test_forced_tool_denylist.py`（`_build_harness_config` 的 `tools_disabled` 是强制集超集、清空 agent 配置后仍在、首个中间件是守卫、没有 `BrowserProfileMiddleware`、`acp_delegate_enabled is False`；`persist_tools_disabled` 与 `persist_plugin_tools_config` 推送超集；缺字段时 `RuntimeError`）；`tests/unit/agents/test_harness_removed_tools.py`（中和后名字与 schema 不变、调用返回错误文本、幂等、属性缺失 `RuntimeError`、`inspect.getsource(HarnessAgent._build_tools)` 仍引用这两个名字）；更新 `test_tool_catalog.py`、`test_agent_manager.py` | `uv run pytest tests/unit/agents -q` |
| 单测：迁移 | `tests/unit/db/test_fork_drop_removed_capability_data.py`：SQLite 上预置含已删键的用户与 `acp_runners:user:1`、`acp_runnersXuser:2`、无关行，把 fork 水位退到本迁移之前再迁移；断言键被剔除且顺序保持、只删前缀行、再次执行不变、users-only 残缺库不报错 | `uv run pytest tests/unit/db/test_fork_drop_removed_capability_data.py tests/unit/db/test_fork_migrate.py -q` |
| 集成 | `tests/integration/test_removed_routes.py`（路由与 OpenAPI）；`tests/integration/test_tool_settings_api.py`（GET 不含已删名、强制集条目三字段、PATCH 400、`GET /api/admin/security/defaults` 过滤）；`tests/integration/test_removed_permission_keys.py`（迁移前 PATCH 回填返回 400、迁移后返回 200）；`tests/integration/test_settings_capabilities_api.py`（200 形状、401、只有 GET）；更新 `test_agents_shared.py` 与 `conftest.py` | `uv run pytest tests/integration/test_removed_routes.py tests/integration/test_tool_settings_api.py tests/integration/test_removed_permission_keys.py tests/integration/test_settings_capabilities_api.py tests/integration/test_agents_shared.py -q` |
| 回归 | 保留资产：`tests/unit/utils/test_browser_profiles_dir.py`（承接 `test_browser_setup.py` 的 4 组用例，并补"通道扫码 profile 根解析"一例）、`tests/unit/desktop/test_stamp_version.py`、`tests/unit/utils/test_posix_compat.py`、i18n 门禁、ACL 覆盖 | `uv run pytest tests/unit/utils tests/unit/desktop tests/unit/i18n tests/unit/api/test_acl_gate_coverage.py tests/unit/users -q` |
| PG | `tests/integration/test_postgresql_fork_capability_trim.py`（带 `@requires_postgresql` 与 `@pytest.mark.postgresql`）：JSONB 列剔除键、前缀行删除、幂等 | 设置 `OCTOP_TEST_DATABASE_URL` 后执行 `make test-postgresql` |
| 前端 | `components/ChatDockPanelShell/ChatDockPanelShell.test.tsx`（迁移后）、改写后的 `ChatDockPanels.keepAlive.test.tsx` 与 `useChatDockPanel.test.ts`、新增 `hooks/useServerCapabilities.test.ts`、更新 `routes/controlAdminPath.test.ts` 与 `layouts/sidebarNav.test.ts` | `cd dashboard && npx tsc -b && npm run lint && npm run test`，或 `make check-frontend` |
| 全量 | ship bar | `make all`、`make check-frontend` |

手工冒烟（任务 20）：聊天页 dock 的 files / file / knowledge / toolUi 四类 tab 与 popup / right / bottom 三种模式；工具设置页；安全策略页的 HITL 选择器；HTTPS 设置页的重启流程（`useServiceRestart`）；通道配置页；持有旧权限键的用户编辑；从旧 `config.json`（含 `capabilities.mobile`）启动。

## 与其他 spec 的交接

**依赖（均假设已合入）：**

- `w0-01`：`forkNNN_` 命名、`_FORK_PY_STEPS`、`set_fork_version`、`discover_fork_migrations`、`current_fork_version`。
- `w0-02`：`make check-frontend`、`make test-postgresql`、CI 的 frontend 与 postgresql job。本 spec 的 vitest 与 PG 验收以它为前提。
- `w0-03`：管理员键集在运行期由 `ALL_PERMISSION_KEYS` 计算，删键后夹具无需改动。w0-03 给 `tests/integration/conftest.py::env_terminal` 接入了 `apply_test_dependency_overrides`，并在 `tests/integration/test_auth_baseline.py` 加了 `env_terminal` 应用的替身断言。本 spec 删除 `env_terminal` 与 `env_acp_agent` 时同步删掉该断言，`octop_client` 分支的断言保留。
- `w0-04`：`_mount_routers` / `without_fork_disabled` / `resolve_router_ref`、`make relock`、`CHANGELOG-intranet.md`、`docs/api-intranet.md`、`docs/intranet/` 目录。
- `w0-05`：它在 `config.py` 新增的三个键由本 spec 的三触点门禁覆盖；它在 `OCTOP_BROWSER_IDLE_TIMEOUT_MINUTES` 块之后追加的 env 段与本 spec 删除的重复块相邻、不重叠。
- `w1-01`：如果它对 ACP 做过改动（例如路由鉴权、`tests/unit/api/test_acp_admin_delegation.py`、ACP 命令白名单配置键），本 spec 随 ACP 一并删除；若有新增配置键，同批从 `config.py` 三触点移除。

**交付给：**

- `w1-03`、`w1-05`：删权限键时复用 `infra/db/fork_steps.py::strip_permission_keys`，各自登记 fork 迁移；只下线不删除的路由用 `_FORK_DISABLED_MOUNTS`；需要"部署期可关"的能力按 `docs/intranet/capabilities.md` 的清单接入目录。`w1-05` 删除公网 IM 通道后，负责评估 `browser_media.py` 的通道 profile 函数、`api/routers/channels.py::_resolve_profiles_root`、`browser_idle_timeout_minutes` 的去留。
- `w1-04`：4 个专家（`news-trend`、`stock-assistant`、`office-automation`、`clinical-learning-subscription`）的 9 个文件在提示词里要求调用 `browser_use`，运行时会得到错误文本；`scripts/install.{sh,ps1,bat}`、`scripts/README.md` 的 playwright / `[browser]` 逻辑；README 与 `docs/` 中对五类能力的描述，以及删除 `docs/acp.md` 后留下的 7 处死链；`fnos/docker/Dockerfile` 的 `.[desktop]`（本 spec 保留 `desktop` extra）。
- `w2-01`：在 harness 内部分支上让子代理遵守 `tools_disabled`，并移除 `browser_use` / `desktop_screenshot` 内置工具，之后删除 `infra/agents/harness_removed_tools.py` 及其 `server.py` 调用；收窄 `orcakit-harness-agent[all]`；评估 `harness-browser` 能否移出依赖树。
- `w2-02`：SBOM 与许可证清单中 playwright 与 `@xterm/*` 消失。
- `w3-04`：需要"令牌移出 URL"的 WS 只剩聊天 WS 与通知 WS（外加轨迹 SSE）。
- `w3-06`：把 `agent_shell` 从 `RESERVED_CAPABILITIES` 移进目录（`tools` 取 harness 的 shell 工具名，已安装版本 `harness_agent/middleware/skill_filter.py` 的 `_SHELL_SKILL_TOOLS` 为 `execute` / `bash` / `shell`），并负责子代理对 `execute` 的覆盖；执行面中间件经 `FORK_AGENT_MIDDLEWARE` 登记（D6）。
- `p2-04`：`content_security` 能力与内容安全中间件经注册表接入。
- `p2-06`：`intranet_im`、`intranet_connectors` 能力；新路由登记在 `FORK_CAPABILITY_MOUNTS`；多维配额如需替换 `TokenQuotaMiddleware`，在注册表层处理，不改 `manager.py` 的上游列表。
- `p2-07`：`frontend_controls` 能力；前端用 `useServerCapabilities` / `isCapabilityEnabled`，按需给 `NavItem` 加 `capability` 字段。
- `w3-02`：能力闸门与强制禁用的审计埋点放在 `require_capability` 与 `ForcedToolGuardMiddleware` 这一层。

**看似相关但归别的 spec：** 云验证码、在线语音、`opencode_session.py`、Codex OAuth（`w1-05`）；联网搜索、`web_fetch`、技能市场、自更新（`w1-03`）；`desktop/`、`fnos/` 打包与 `.github/` 工作流（`w1-04`，D9）；中间件栈顺序与安全头（`w3-01`）；权限判定收口与三员分立（`w3-03`）。

## 风险与回滚

| 风险 | 等级 | 缓解 |
|---|---|---|
| 聊天页回归：浏览器与终端嵌在 dock、头部、输入栏、消息流四处 | 高 | 先迁外壳（行为不变的独立提交），再收窄 `DockTab` 让 `tsc` 报出全部分支；改写 keep-alive 用例作为回归网；手工冒烟四类 tab 与三种模式 |
| 子代理仍能拿到能力关闭型工具 | 高 | 已删工具由中和层覆盖；能力关闭型工具的子代理覆盖交接给 `w2-01` / `w3-06`，并写进 `docs/intranet/capabilities.md` 的"已知限制" |
| harness 升级后中和层失效 | 中 | 目标属性缺失时启动报 `RuntimeError`；契约测试检查 `_build_tools` 源码仍引用这两个名字 |
| 行内误配能力名导致启动失败 | 中 | 这是有意的 fail closed；报错含名字、owner 与修复提示；文档列出全部合法名与保留名 |
| 存量 `config.json` 的 `capabilities.mobile` | 中 | legacy 忽略加 WARNING，有单测 |
| 误删同名资产（`desktop/`、`useServiceRestart`、`browser_media` 保留函数、`chatBrowserPanel.partial.less`） | 中 | 需求 1.5 与 10.5 写成验收，并有对应回归用例 |
| 上游同步冲突：已删文件被上游修改（modify/delete） | 中 | 冲突时一律保持删除；`manager.py` 只留删除加 3 处单点接入；i18n 与上游文档零改动 |
| 锁文件冲突 | 中 | 取上游后执行 `make relock` |
| 强制集推送改变 `set_tools_disabled` 的参数 | 低 | 同步更新 `test_agent_manager.py` 中的精确断言 |

**回滚：** 按提交逆序 revert。代码回滚后，已删权限键与 `acp_runners:user:*` 行不会恢复：老代码面对不含这些键的用户只是"无权限"，不会出错；ACP runner 配置如需恢复，从升级前的系统备份取回。fork 迁移已推进的 `_fork_schema_version` 不回退（w0-01 的 runner 会对"水位高于文件最大号"只记 WARNING）。前端外壳迁移的提交可以独立保留。

## 待行方确认

- **D6（Agent 命令执行）：** 本 spec 只预留 `agent_shell`，不接入。若行方答复"不保留"，`w3-06` 把它移进目录并设 `default_enabled=False`。
- **D13（harness 源码）：** 子代理遵守 `tools_disabled` 与移除内置浏览器、桌面工具，需要 harness 内部分支。若源码不可得，中和层会长期保留，行方需要接受"`harness-browser` 包在磁盘上但无可达代码路径"。
- **D9（`desktop/`、`fnos/`）：** 本 spec 不受影响，始终保留 `tests/unit/desktop/test_stamp_version.py` 与 `desktop` extra，由 `w1-04` 按 D9 处理。
- 以下几项不在 steering 第 4 节，建议补入：(a) 能力关闭的对外表现，本 spec 默认 404，若行方要求 403 加能力名，只改 `require_capability` 一处；(b) 哪些保留能力需要部署期开关、默认开还是关，本 spec 目录为空；(c) ACP 遗留数据，本 spec 默认删除 `acp_runners:user:*`、保留 `agents.config_json` 中的 `acp` 段；若要求"删除即无痕"，需要追加一个清理 `config_json` 的 Python 步骤（约 0.5 人日），若要求留存待审计，则去掉该 DELETE 语句；(d) 是否两阶段落地（先关后删），本 spec 默认一次性物理删除，两阶段约需另加 3 人日。
