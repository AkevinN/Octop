# 设计文档：Agent 执行面收紧

> spec：`w3-06-agent-execution-hardening` ｜ 波次：Wave 3 ｜ 基线：`757fd12` ｜ 预估：9.5 人日
> 前置：`w0-02-ci-gates`、`w0-03-test-auth-baseline`、`w0-04-fork-isolation-points`、`w0-05-ssrf-intranet-allowlist`、`w1-01-security-hotfix`、`w1-02-capability-trim`、`w1-05-saas-decoupling`、`w2-01-offline-build` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 概述

本 spec 只做"收紧"，不做"隔离"：执行仍在服务进程的 `local_shell` 里发生，但根目录、审批、护栏、环境变量、MCP 传输与权限、目录浏览七处默认值全部改为最小授权。所有强制禁用走 `w1-02` 的 `forced_disabled_tools`，本 spec 只往它的数据里加默认值（`agent_shell` 能力条目与 `web_fetch`）。不新增 `ErrorCode`、不新增 `config.py` 键、不新增权限键、不写 fork 迁移、不改上游 i18n JSON。`manager.py` 只改 `create()` 内两行。

## 现状

以下均在基线 `757fd12` 上核实。

- **默认后端是主机根。** `src/octop/infra/backend/resolver.py::default_agent_backend_spec`（≈L12）在 ≈L23 导入 harness 的 `DEFAULT_BACKEND_SPEC`，≈L31 在非 Windows 平台 `return dict(DEFAULT_BACKEND_SPEC)`；`windows_neutralize_host_root`（≈L34）在 ≈L48 `if os.name != "nt"` 原样返回。`tests/unit/backend/test_resolver.py::test_default_agent_backend_spec_posix_uses_host_root`（≈L24）与 `test_windows_neutralize_is_passthrough_on_posix`（≈L93）守护这一行为。
- **消费点。** `infra/agents/manager.py` ≈L57 导入 `windows_neutralize_host_root`，`_backend_spec_for_row`（≈L2348）在 ≈L2368 调用；`create()`（≈L505）在 ≈L540-548 调 `raise_if_backend_outside_user_root`，≈L551 调 `seed_workspace_dir_on_create`（返回值未使用），≈L555 写 `system_files_path`；`update` 路径 ≈L678 再调一次 `raise_if_backend_outside_user_root`。`_backend_supports_host_skill_packages`（≈L1778）只在根为 `"/"` 或等于 `workspace_dir` 时为真。
- **setup 首个专家以 HOME 为根。** `infra/agents/default_agent.py::default_home_local_backend`（≈L23）返回 `root_dir=host_path_text(host_home_dir())`，≈L64 作为 `config_extra={"backend": …}` 传入。
- **根目录校验。** `api/common/validators.py::assert_user_backend_root_dirs`（≈L12）在无 `policy_repo` 时只做 `assert_backend_root_dirs_allowed(restrict_to_home=False)`；调用点共 5 个：`api/routers/agents.py` ≈L262、≈L360，`api/routers/experts.py` ≈L511、≈L608、≈L699。
- **目录浏览。** `api/routers/filesystem.py` 模块说明 ≈L10 为 "All authenticated users may browse from host root `/`"；`_user_workspace_root`（≈L51）读 `effective_workspace_root_dir`；`filesystem_defaults`（≈L78）在无策略时返回 `allow_outside_home=True` 与 `host_fs_tree_root(...)`；`list_host_dirs`（≈L108）、`probe_host_dir`（≈L129）、`mkdir_host_dir`（≈L190）、`rename_host_directory`（≈L210）都只挂 `current_user`，`restrict_to_root` 为 `None` 时不限制。
- **容器内策略失效。** `infra/users/resource_policy.py::effective_workspace_root_dir`（≈L55）在 ≈L57 `if running_in_container()` 返回 `None`；`normalize_workspace_root_dir`（≈L94）在 ≈L102 拒绝设置（错误码 `WORKSPACE_ROOT_CONTAINER_UNSUPPORTED`，`errors.py` ≈L108）。
- **审批与护栏。** `infra/agents/security/policy_store.py::_default_policy`（≈L18）在 ≈L21 `hitl.enabled=False`、≈L22 `tool_guard={"enabled": True, "mode": "warn"}`；`manager.py` ≈L2958 `policy.apply_to_config(harness_cfg)` 把它施加到 harness。`tests/unit/test_security_settings.py::test_load_defaults_when_missing`（≈L12）断言旧默认值；仪表盘 `pages/Settings/Security/index.tsx` ≈L141、≈L188 以 `"warn"` 兜底。
- **定时任务遇审批即失败。** `infra/cron/delivery.py` ≈L147 见到 `hitl_required` 置位，≈L150 `raise RuntimeError("cron agent run requires user interaction")`。
- **执行环境。** `infra/agents/execute_env.py::inject_agent_execute_env`（≈L93）在 ≈L137 `out.setdefault("inherit_env", True)`；`infra/utils/env_file.py::apply_env_file`（≈L87）把 `~/.octop/env` 并进 `os.environ`，`_is_protected_env_key`（≈L110）把 `_PROTECTED_EXACT` 与 `OCTOP_` 前缀视为受保护，`env_file_path(root)`（≈L35）返回 `root / "env"`。`tests/unit/agents/test_execute_env.py` ≈L56、≈L114 断言 `inherit_env is True`。
- **工具目录。** `infra/agents/tool_catalog.py` ≈L60 `execute`、≈L65 `web_fetch`；`effective_tools_disabled`（≈L168）≈L182 `return disabled - CRITICAL_TOOLS`。热同步：`persist_tools_disabled`（≈L1729）→ `sync_effective_tools_disabled`（≈L2163，≈L2176 调 `effective_tools_disabled`）→ `sync_tools_disabled`（≈L2149）；组装路径 `_build_harness_config`（≈L2683，≈L2952）。`_HARNESS_AGENT_CONFIG_FIELDS`（≈L97）由 `dataclasses.fields(HarnessAgentConfig)` 生成。
- **自定义 MCP。** `infra/connectors/custom_mcp.py`：`Transport = Literal["streamable_http", "stdio"]`（≈L22）、`_normalize_env`（≈L88）、`_normalize_args`（≈L102，二者只在 stdio 分支 ≈L178、≈L181 使用）、`normalize_server_spec`（≈L143，≈L147 接受 `stdio`/`http`）、`harness_spec_for_server`（≈L342，≈L346 stdio 兜底）。`infra/connectors/probe.py`：`probe_streamable_http_mcp`（≈L329，≈L341 直接 `streamablehttp_client`）、`probe_custom_mcp_server`（≈L497，≈L518 分派 stdio）、`_probe_stdio_mcp`（≈L523）。`api/routers/connectors.py` 的 custom-mcp 四个端点（≈L521、≈L531、≈L562、≈L591）只挂 `Depends(current_user)`；`require_permission` 已在 ≈L17 导入。`infra/connectors/service.py::custom_harness_configs`（≈L447）。`infra/utils/ssrf_guard.py::validate_https_url_resolved`（≈L80）存在。
- **权限基线。** `infra/users/permissions.py` ≈L53 `connectors` 属 `settings` 类，≈L222 `BASELINE_PERMISSIONS` 按 `settings` 类生成，即新用户默认持有。

- **前端。** `agentBackendForm.ts` ≈L49 `root_dir: rootDir ?? "/"`，≈L104 主机根恒支持技能包；`CustomMcpTab.tsx` ≈L573、≈L702 暴露 stdio；`connectors.ts` ≈L128 类型含 stdio。

前序 spec 的交付物（`forced_disabled_tools`、`CAPABILITY_CATALOG`、`custom_mcp_gate.py`、`web_search_tools=False`、SSRF 白名单、harness 内部分支）见"与其他 spec 的交接"。

## 方案

1. **默认根 = Agent 工作区。** `default_agent_backend_spec` 全平台返回 `{"type":"local_shell","root_dir":str(ws.resolve()),"virtual_mode":True}`，删去对 `DEFAULT_BACKEND_SPEC` 的导入。`windows_neutralize_host_root` 更名为 `neutralize_host_root`，删去非 Windows 早退，并对 `composite.routes` 子后端同样收敛；保留 `windows_neutralize_host_root = neutralize_host_root` 别名，使 `manager.py` 的导入与调用不改。必须选"该 Agent 的 `workspace_dir`"而不是用户工作区父目录，否则 `_backend_supports_host_skill_packages` 为假，技能包挂载全线失败。
2. **创建时落盘。** `create()` 在 ≈L551 捕获 `seed_workspace_dir_on_create` 的返回值，并在 ≈L555 之后加一行 `config.setdefault("backend", default_agent_backend_spec(ws_host))`。放在 `raise_if_backend_outside_user_root` 之后，所以默认后端不会被用户自己的策略拦截。`default_home_local_backend` 改为返回 `None`，`bootstrap_default_agent` 不再传 `backend`。存量行靠运行期 `neutralize_host_root` 收敛，不写数据迁移。
3. **根目录校验。** `assert_user_backend_root_dirs` 增加关键字参数 `own_workspace_dir: Path | None = None`。无生效策略时：本地 `root_dir` 缺省或等于 `own_workspace_dir` 放行，否则抛 `WORKSPACE_ROOT_RESTRICTED`。有策略时：维持"位于策略根下"，额外放行等于 `own_workspace_dir` 的根。`raise_if_backend_outside_user_root` 同步加该参数，`manager.py` ≈L678 不改。PATCH 类入口（`agents.py` ≈L360、`experts.py` 的更新入口）传入该 Agent 的 `workspace_dir`。
4. **目录浏览。** `filesystem.py` 新增 `_require_workspace_root(server, user) -> str`：无生效策略时抛 `OctopError(ErrorCode.WORKSPACE_ROOT_RESTRICTED, …)`；`list_host_dirs`、`probe_host_dir`、`mkdir_host_dir`、`rename_host_directory` 全部改用它，并以 `restrict_to_root=<根>` 调用 `host_dirs`。`filesystem_defaults` 无策略时返回 `default_root_dir=""`、`tree_root=""`、`allow_outside_home=False`。管理员不例外；需要自定义目录的用户由管理员下发 `workspace_root_dir` 策略。`resource_policy` 删除两处 `running_in_container()` 短路；`WORKSPACE_ROOT_CONTAINER_UNSUPPORTED` 成为未使用码，按 steering 1.2 保留枚举与文案。
5. **审批与护栏默认值。** `_default_policy` 改为 `hitl.enabled=True`、`hitl` 工具集 = `EXECUTION_TOOLS ∩ hitl_tool_catalog() 名称`、`tool_guard={"enabled": True, "mode": "block"}`。`hitl` 工具字段名以实施时 `SecurityPolicy.defaults().to_dict()["hitl"]` 的实际键为准（任务 6 先确认）。定时任务遇审批即失败是既有行为，本 spec 只补回归用例。
6. **执行能力开关。** 新增 fork 模块 `src/octop/infra/agents/execution_policy.py`，定义 `EXECUTION_TOOLS = frozenset({"execute", "bash", "shell"})`（对齐 harness `_SHELL_SKILL_TOOLS`）。在 `capability_catalog.py` 把 `agent_shell` 从 `RESERVED_CAPABILITIES` 移入 `CAPABILITY_CATALOG`：`CapabilitySpec("agent_shell", default_enabled=True, owner="w3-06-agent-execution-hardening", tools=EXECUTION_TOOLS)`（`capability_catalog.py` 只导入标准库，所以集合字面量写在该文件内，`execution_policy.py` 反向引用它）。子代理覆盖：在 `w2-01` 的 harness 内部分支上提交补丁，让子代理的工具集减去主代理 `tools_disabled`，并加内部分支单测。
7. **`web_fetch` 强制禁用。** 在 `infra/capabilities.py::REMOVED_CAPABILITY_TOOLS` 追加 `web_fetch`（与 `w1-05` 追加搜索工具的做法一致），并从 `BUILTIN_TOOL_CATALOG` 删去 `web_fetch` 条目（`w1-02` 的测试要求 `REMOVED_CAPABILITY_TOOLS` 中的名字不出现在 tool-settings 响应里）。i18n 的 `tools.web_fetch` 键保留为孤儿键。不改 `effective_tools_disabled`：强制集已在 `sync_tools_disabled` 出口叠加，本 spec 只补"属主 PUT 后热同步仍含 `web_fetch`"的回归用例。
8. **执行环境最小化。** `inject_agent_execute_env` 新增关键字参数 `base_env: Mapping[str, str] | None = None`；对 `local_shell` 无条件设 `out["inherit_env"] = False`，`env` 按"基础白名单 ← `~/.octop/env` 非受保护键 ← 后端规格 `env` ← `agent_execute_env_defaults`"顺序合并。基础白名单常量 `EXECUTE_BASE_ENV_KEYS` 放在 `execution_policy.py`，由它提供 `build_execute_base_env(paths) -> dict[str, str]`（读 `os.environ` 与 `env_file.load_env_file(env_file_path(paths.root))`，过滤 `_is_protected_env_key`）。`manager.py` ≈L2907 的调用点不改：`base_env` 缺省时 `inject_agent_execute_env` 自行调用 `build_execute_base_env(paths)`。不新增配置键：需要透传的行内变量由管理员写进 `~/.octop/env`。
9. **自定义 MCP 只留 HTTP。** `Transport = Literal["streamable_http"]`；`normalize_server_spec` 对 `stdio` 抛 `ValueError("stdio transport is not supported")`，保留 `http` 别名；删除 `_normalize_env`、`_normalize_args`、stdio 分支与 `harness_spec_for_server` 的 stdio 兜底。`probe.py` 删除 `_probe_stdio_mcp` 与 ≈L517-518 的分派。`custom_mcp_gate.py` 删除 `reject_stdio_spec` / `reject_stdio_servers` 及其调用点（`normalize_server_spec` 已拒绝），保留 `drop_non_http_configs` 作为存量数据兜底；`GET /connectors/custom-mcp` 返回前同样过滤非 HTTP 条目。`env_file.overlay_stdio_*` 与 `manager.py` 中它们的三处调用不删：输入已无 stdio 条目，它们成为无操作，删除只会增加热点文件冲突（登记为死代码，交上游同步时处理）。
10. **权限与探测校验。** custom-mcp 四个端点追加 `_: Any = Depends(require_permission("connectors"))`，保留 `user` 用于归属。`probe_streamable_http_mcp` 在建连前：若主机不是回环地址则 `await validate_https_url_resolved(url)`，失败返回与基线一致的探测失败结构。
11. **前端。** `backendRefToSpec` 未选目录时不带 `root_dir`；`supportsHostSkillPackages` 新增可选 `workspaceDir`，主机根不再恒真；`tree_root` 为空时隐藏目录选择器（提示文案写 `dashboard/src/locales/intranet/{en,zh}.json`）；MCP 三文件去 stdio；安全页 `tool_guard` 兜底改 `"block"`。

## 组件与接口

改动文件清单见 tasks.md 各任务的"改动"行；新增模块只有 `src/octop/infra/agents/execution_policy.py`，另在 `w2-01` 建立的 harness 内部分支上提交一处补丁。

关键签名：

```python
# src/octop/infra/backend/resolver.py
def default_agent_backend_spec(workspace_dir: Path) -> dict[str, Any]: ...
def neutralize_host_root(spec: Any, *, workspace_dir: Path) -> Any: ...
windows_neutralize_host_root = neutralize_host_root  # 兼容别名，manager.py 不改

# src/octop/infra/agents/execution_policy.py（新增）
EXECUTION_TOOLS: frozenset[str]
EXECUTE_BASE_ENV_KEYS: tuple[str, ...] = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "TMPDIR")
def build_execute_base_env(paths: PathLayout) -> dict[str, str]: ...

# src/octop/infra/agents/execute_env.py
def inject_agent_execute_env(backend: Any, *, paths: PathLayout, row: AgentRow, workspace_dir: Path,
                             cfg: dict[str, Any] | None = None, base_env: Mapping[str, str] | None = None) -> Any: ...

# src/octop/api/common/validators.py
def assert_user_backend_root_dirs(user: Any, backend: Any, *, policy_repo: Any | None = None,
                                  own_workspace_dir: Path | None = None) -> None: ...

```

## 数据模型

无。存量 `config_json` 中的 `root_dir="/"` 由运行期 `neutralize_host_root` 收敛；存量 stdio MCP 条目由 `w1-01` 的 `drop_non_http_configs` 兜底并在下次保存时丢弃。不写 fork 迁移。

## 配置

无新增 `config.py` 键。执行能力开关使用 `w1-02` 框架的通用键 `capabilities.agent_shell.enabled`（环境变量由 `CapabilitySpec.env_var` 派生），不动 `config.py` 三触点。

## 错误处理

不新增 `ErrorCode`。复用：`WORKSPACE_ROOT_RESTRICTED`（400，`errors.py` ≈L107/≈L209）用于根目录越界与无策略浏览；`CONNECTOR_KIND_UNSUPPORTED`（400，≈L54/≈L156）用于 stdio 规格；`FORBIDDEN`（403）由 `require_permission` 产生。`WORKSPACE_ROOT_CONTAINER_UNSUPPORTED` 不再被抛出，保留定义与四份文案。

## 安全考虑

- **收敛了什么：** 主机根默认可读写执行；执行进程读取服务进程口令；普通用户经 stdio MCP 启动进程；普通用户经 streamable_http 探测做内网扫描；普通用户浏览主机目录树；默认无审批。
- **残余风险（交 `p2-01`）：** `local_shell` 以服务进程 uid 运行，`virtual_mode` 只约束 harness 文件工具；`execute` 里的 shell 仍能读服务进程可读的文件（含 `~/.octop/octop.db`）。一期靠"执行需审批 + 护栏拦截 + 镜像非 root（`w2-01`）"降低风险。
- 审批只对交互渠道有效；定时任务遇审批直接失败，不会绕过。

## 测试策略

| 类别 | 内容 | 命令 |
|---|---|---|
| 单测：后端根 | `default_agent_backend_spec`、`neutralize_host_root` 全平台、技能包判定 | `uv run pytest tests/unit/backend/test_resolver.py tests/unit/agents/test_agent_manager.py tests/unit/agents/test_default_agent.py -q` |
| 单测：策略、环境、工具 | 默认策略、`execute_env`、`resource_policy`、`agent_shell`、强制集与热同步 | `uv run pytest tests/unit/test_security_settings.py tests/unit/agents tests/unit/users tests/unit/test_capabilities_config.py -q` |
| 单测：MCP | stdio 拒绝、探测校验 | `uv run pytest tests/unit/connectors/test_custom_mcp.py tests/unit/connectors -q` |
| 集成 | 根目录校验 5 入口、目录浏览、工具设置、custom-mcp 权限、安全 API、bwrap jail | `uv run pytest tests/integration/test_agents_api.py tests/integration/test_experts_api.py tests/integration/test_filesystem_api.py tests/integration/test_tool_settings_api.py tests/integration/test_connectors_api.py tests/integration/test_security_api.py tests/integration/test_bwrap_jail.py tests/integration/test_setup_bootstrap.py -q` |
| 前端 | 表单语义、vitest | `cd dashboard && npx tsc -b && npm run lint && npm run test` |
| PG | 无 SQL 改动；按 `w0-02` 设 `OCTOP_TEST_DATABASE_URL` 后重跑集成 | `uv run pytest tests/integration -q` |

跨平台：执行 `env` 的集成用例与 `"/"` 收敛用例按 AGENTS.md §7 用 `posix_only`；路径比较用 `Path` 相等。

## 与其他 spec 的交接

- **依赖：** `w1-02`（`forced_disabled_tools`、`CAPABILITY_CATALOG`、`agent_tools.py` 强制项展示）；`w1-05`（`web_search_tools=False` 与搜索工具强制禁用，本 spec 只加断言）；`w1-01`（`custom_mcp_gate.py`，本 spec 删其中 `reject_stdio_*`）；`w0-05`（`validate_https_url_resolved` 的白名单语义）；`w2-01`（harness 内部分支、`ensure_bubblewrap`/`docker_status` 已去安装化、镜像非 root）；`w0-03`（测试鉴权基线，用于构造无 `connectors` 权限用户）；`w0-04`（dashboard intranet overlay、`CHANGELOG-intranet.md`、`docs/api-intranet.md`）。
- **交付给 `w3-03`：** custom-mcp 已改为 `require_permission("connectors")`。`connectors` 当前在 `BASELINE_PERMISSIONS`，要真正"收归管理员"，需由 `w3-03` 在三员分立角色中只把它授予系统管理员角色、并移出普通用户基线（D12）。
- **交付给 `p2-01`：** 执行进程的文件系统与网络隔离、镜像预装 bubblewrap、容器 user namespace、`ensure-bwrap` 等端点的最终去留；`agent_shell` 能力条目与 `EXECUTION_TOOLS` 可直接复用。
- **源分析中归别处的条目（不在本 spec 做）：** `bwrap.py` / `docker_env.py` / `launch.py` 去安装化、Dockerfile `USER`（`w2-01`）；`mobile/docker_install.py`（`w1-02` 随远程手机删除）；SSRF 白名单与 `egress-allowlist` 管理接口（`w0-05`）；联网搜索工具目录项删除（`w1-05`）；`browser_use` / `desktop_screenshot`（`w1-02`/`w2-01`）；`OCTOP_SANDBOX_MODE`、启动期沙箱 fail-fast（`p2-01`）。
- **未被认领、登记待定：** 安全策略"部署锁"（只允许收紧）、`skill_scan.mode` 默认 `block`、`filesystem` 规则补 `{OCTOP_HOME}/**`、`/api/envs` 可写键收紧（`w2-04` 提到）。建议并入 `w4-02` 或二期 `p2-01`，由行方确认。

## 风险与回滚

| 风险 | 等级 | 缓解 |
|---|---|---|
| 存量专家原以 `/` 或 HOME 为根，收敛后技能脚本找不到工作区外文件 | 高 | 发布说明写明；需要外部目录的用户由管理员下发 `workspace_root_dir` 并显式设根 |
| `inherit_env=False` 后技能脚本找不到依赖变量 | 中 | 白名单保留 `PATH`；行内变量写 `~/.octop/env` |
| `tool_guard` 改 `block` 误拦常规命令 | 中 | 上线前以 `warn` 跑一轮统计误报，管理员可在安全页调整 |
| HITL 默认开启使 IM 与定时任务中的执行请求需审批或失败 | 中 | 定时任务失败有明确错误；需要无人值守执行的专家由管理员在安全页调整工具集 |
| 删除 `web_fetch` 目录项与上游冲突 | 低 | 单行删除；上游同步时取上游再重删 |

回滚：各顶层任务独立提交，可逐个 `git revert`；无数据迁移，回滚不需要数据修复。

## 待行方确认

- **D6：** 默认保留执行能力（`agent_shell.default_enabled=True`）。**若行方决定不保留执行能力**，简化路径为：把 `agent_shell` 的 `default_enabled` 改为 `False`（一行），执行类工具进入强制集，主代理由 `w1-02` 的 `ForcedToolGuardMiddleware` 拦截、子代理由任务 8 的补丁覆盖；任务 6 的 HITL 工具集改为空（执行工具已不可见）；任务 10（执行环境）仍建议保留作为纵深防御；需求 1、2、5、7、8、9 不变；`p2-01` 取消。预估降为约 7.5 人日。
- **D4：** 容器部署下 `workspace_root_dir` 生效的前提是该目录已挂载进容器；部署手册由 `w4-02` 写明。
- **D12：** `connectors` 权限只授予系统管理员角色（见交接）。
