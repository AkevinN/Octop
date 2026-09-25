# 需求文档：Agent 执行面收紧

> spec：`w3-06-agent-execution-hardening` ｜ 波次：Wave 3 ｜ 基线：`757fd12` ｜ 预估：9.5 人日
> 前置：`w0-02-ci-gates`、`w0-03-test-auth-baseline`、`w0-04-fork-isolation-points`、`w0-05-ssrf-intranet-allowlist`、`w1-01-security-hotfix`、`w1-02-capability-trim`、`w1-05-saas-decoupling`、`w2-01-offline-build` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 引言

**结论：** 本 spec 按 steering D6 的默认假设"保留命令执行但收紧"，把 Agent 执行面收敛为"以该 Agent 自己的工作区为根、执行类工具默认人工审批、命令护栏默认拦截、执行环境最小化、自定义 MCP 只剩 HTTP 且需 `connectors` 权限"。完整的 bubblewrap / Docker 强制沙箱不在本 spec，归 `p2-01-agent-sandbox`。

**背景：** 基线上未配置后端的 Agent 在 POSIX 下以主机 `/` 为根（`resolver.default_agent_backend_spec` 直接返回 harness 的 `DEFAULT_BACKEND_SPEC`），默认安全策略关闭 HITL 且护栏只告警，`local_shell` 执行继承服务进程环境，自定义 MCP 仍接受 stdio 且任意登录用户可配，`/api/filesystem/*` 允许任意登录用户从主机根浏览。证据见 design.md"现状"。

**范围内：**

1. 默认后端根目录改为 Agent 工作区（全平台），创建时把 backend 显式写入 `config`；存量 `root_dir="/"` 在运行期收敛。
2. 后端根目录校验与主机文件系统浏览限制在用户工作区根；容器内 `workspace_root_dir` 策略生效。
3. 执行类工具默认需人工审批，命令护栏默认拦截。
4. 登记 `w1-02` 预留的 `agent_shell` 能力（D6 开关），在 `w2-01` 建立的 harness 内部分支上让子代理遵守 `tools_disabled`。
5. `web_fetch` 进入 `w1-02` 的强制禁用集（只提供默认值，不另建机制）；验证 `web_search_tools=False` 与 `sync_effective_tools_disabled` 热同步路径不可绕过。
6. 命令执行不继承服务进程环境变量。
7. stdio MCP 入口从 API、服务层（含探测）、前端表单三处移除；自定义 MCP 只留 HTTP 传输并收归 `connectors` 权限，接替 `w1-01` 的临时闸门；探测建连前补解析期 SSRF 校验。

**范围外：**

| 事项 | 归属 |
|---|---|
| bubblewrap / Docker 强制沙箱、镜像预装 bwrap、容器 user namespace、执行网络隔离 | `p2-01-agent-sandbox` |
| `ensure_bubblewrap` / `docker_status` 去安装化、镜像非 root 用户 | `w2-01-offline-build`（已完成） |
| 远程手机（含 `mobile/docker_install.py`）删除 | `w1-02-capability-trim` |
| 联网搜索工具删除、`web_search_tools=False` 传参 | `w1-05-saas-decoupling`（本 spec 只加回归断言） |
| SSRF 内网白名单本身 | `w0-05-ssrf-intranet-allowlist` |
| `connectors` 权限键归哪个角色、是否移出基线权限 | `w3-03-authorization-foundation` |
| 安全策略"部署锁"、`skill_scan` 默认值、`/api/envs` 可写键收紧 | 不在本轮；见 design.md"与其他 spec 的交接" |

## 需求

### 需求 1：默认后端以 Agent 工作区为根

**用户故事：** 作为银行安全管理员，我希望未显式配置后端的 Agent 只能在它自己的工作区内读写和执行，以便 Agent 无法以服务进程身份访问主机根目录。

#### 验收标准

1. 当调用 `default_agent_backend_spec(ws)` 时，`resolver` 应当在所有平台返回 `{"type": "local_shell", "root_dir": str(ws.resolve()), "virtual_mode": True}`，不再引用 harness 的 `DEFAULT_BACKEND_SPEC`。
2. 如果 `local_shell` / `filesystem` 规格（含 `composite` 的 `default` 与 `routes` 子后端）的 `root_dir` 是主机根（POSIX `"/"`），那么 `neutralize_host_root` 应当在所有平台把它改写为该 Agent 的工作区路径。
3. 当 `AgentManager.create` 收到的 `config` 不含 `backend` 时，管理器应当把第 1 条的规格写入持久化的 `config["backend"]`；setup 向导创建的首个专家同样如此。
4. `manager._backend_supports_host_skill_packages(default_agent_backend_spec(ws), workspace_dir=ws)` 应当始终为 `True`，即默认后端不影响技能包挂载。

### 需求 2：后端根目录与主机文件系统浏览限制在用户工作区根

**用户故事：** 作为银行安全管理员，我希望用户只能在管理员分配的工作区根内选择或浏览目录，以便没有任何接口能让普通用户看到主机目录树。

#### 验收标准

1. 如果用户没有生效的 `workspace_root_dir` 策略，且提交的后端显式带有不等于该 Agent 工作区的本地 `root_dir`，那么 `POST/PATCH /api/agents` 与 `experts.py` 的三个创建/更新入口应当返回 400，错误码为既有的 `WORKSPACE_ROOT_RESTRICTED`。
2. 如果用户有生效的 `workspace_root_dir` 策略，那么后端 `root_dir` 应当位于该根之下或等于该 Agent 自己的工作区；新建专家的默认后端不得被用户自己的策略拦截。
3. 当用户没有生效的 `workspace_root_dir` 策略时调用 `GET /api/filesystem/dirs`、`POST /api/filesystem/probe`、`/mkdir`、`/rename`，接口应当返回 400（`WORKSPACE_ROOT_RESTRICTED`）；`GET /api/filesystem/defaults` 应当返回 `default_root_dir` 为空、`tree_root` 为空。
4. 在 `running_in_container()` 为真期间，`effective_workspace_root_dir({"value": "/data/ws", "enabled": True})` 应当返回 `"/data/ws"`，`normalize_workspace_root_dir` 应当接受该值。
5. `src/octop/api/routers/filesystem.py` 应当始终不含"browse from host root"的说明，且任何用户（含管理员）都不能列出其工作区根以外的目录。

### 需求 3：执行类工具默认人工审批，命令护栏默认拦截

**用户故事：** 作为银行安全管理员，我希望新部署在没有任何配置时，Agent 执行命令前就要人工确认，高危命令直接被拦截，以便默认状态即满足最小授权。

#### 验收标准

1. 当 `settings` 中没有 `security_policy` 行时，`SecuritySettingsStore.load()` 应当返回 `hitl.enabled is True`、`tool_guard.enabled is True`、`tool_guard.mode == "block"`，且 HITL 工具集包含执行类工具（`execute` 及 `hitl_tool_catalog()` 中存在的其他 shell 类名）。
2. 如果定时任务运行中出现 `hitl_required`，那么 `infra/cron/delivery.py` 应当让该次运行以失败结束（既有行为），而不是挂起；该行为应当有回归用例守护。
3. 安全设置页在后端未返回 `tool_guard.mode` 时，应当始终以 `"block"` 作为表单兜底值。

### 需求 4：执行能力开关与子代理覆盖

**用户故事：** 作为行方运维，我希望能用一个部署级开关整体关闭 Agent 的命令执行能力，且子代理同样受限，以便行方决定不保留执行能力时无需改代码。

#### 验收标准

1. `CAPABILITY_CATALOG` 应当始终包含 `agent_shell`，`owner` 为本 spec，`tools` 为执行类工具名集合，`default_enabled=True`（D6 默认假设）；`RESERVED_CAPABILITIES` 不再包含 `agent_shell`。
2. 当 `capabilities.agent_shell.enabled` 为 `false` 时，`forced_disabled_tools(cfg)` 应当包含全部执行类工具，`GET /api/agents/{id}/tool-settings` 中 `execute` 为 `available=false`、`disableable=false`。
3. 当主代理的 `tools_disabled` 含某工具时，harness 内部分支构建的子代理应当同样不含该工具（在内部分支的测试中断言）。

### 需求 5：联网工具强制禁用

**用户故事：** 作为银行安全管理员，我希望 Agent 不具备任何联网抓取能力，且属主无法在工具页或通过 API 重新打开，以便断网环境里不存在绕过出口。

#### 验收标准

1. `forced_disabled_tools(cfg)` 应当始终包含 `web_fetch`，且强制集与 `CRITICAL_TOOLS` 不相交。
2. 当属主 `PUT /api/agents/{id}/tool-settings` 提交不含 `web_fetch` 的 `disabled_builtin` 后，`sync_effective_tools_disabled` 推送给运行中 Agent 的集合应当仍含 `web_fetch`（经 `sync_tools_disabled` 出口）。
3. 当 `_build_harness_config` 构造 `HarnessAgentConfig` 时，结果应当带 `web_search_tools=False`，且 `tools_disabled` 含 `web_fetch`。

### 需求 6：命令执行环境最小化

**用户故事：** 作为银行安全管理员，我希望 Agent 执行的命令拿不到服务进程的口令与密钥类环境变量，以便模型可控的 shell 无法读出数据库口令或 Provider 密钥。

#### 验收标准

1. `inject_agent_execute_env` 为 `local_shell` 产出的规格应当始终带 `inherit_env is False`（覆盖调用方传入的值）。
2. 产出的 `env` 应当只包含：基础白名单（`PATH`、`LANG`、`LC_ALL`、`LC_CTYPE`、`TZ`、`TMPDIR` 中服务进程已有的）、`agent_execute_env_defaults` 注入的 `OCTOP_*` 平台变量、`~/.octop/env` 文件中非受保护键、后端规格自带的 `env`。
3. 如果服务进程环境中有 `OCTOP_DATABASE_PASSWORD` 或任意未出现在 `~/.octop/env` 的变量，那么它不应当出现在产出的 `env` 中。
4. 在 POSIX 下，用默认后端执行 `env` 命令的输出应当不含测试预先注入服务进程的哨兵变量。

### 需求 7：自定义 MCP 只保留 HTTP 传输

**用户故事：** 作为银行安全管理员，我希望系统在数据结构层就不接受 stdio MCP，以便任何入口都无法借 MCP 在服务器上启动进程。

#### 验收标准

1. 当调用 `normalize_server_spec("x", {"transport": "stdio", "command": "sh"})` 时，应当抛 `ValueError`；`transport` 为 `"http"` 时继续归一为 `"streamable_http"`。
2. 当 `PUT /api/connectors/custom-mcp` 或 `POST /api/connectors/custom-mcp/test` 提交 stdio 规格时，接口应当返回 400（`CONNECTOR_KIND_UNSUPPORTED`）。
3. `src/octop/infra/connectors/probe.py` 与 `custom_mcp.py` 应当始终不含 `stdio_client`、`StdioServerParameters`、`_probe_stdio_mcp`；`custom_mcp.Transport` 只含 `"streamable_http"`。
4. 如果库中残留 stdio 规格，那么 `custom_harness_configs` 应当仍把它过滤掉（保留 `w1-01` 的 `drop_non_http_configs` 兜底），`GET /api/connectors/custom-mcp` 不返回该条目。

### 需求 8：自定义 MCP 收归 `connectors` 权限并补探测校验

**用户故事：** 作为银行安全管理员，我希望只有持 `connectors` 权限的管理人员能读写和探测自定义 MCP，且探测前做解析期 SSRF 校验，以便普通用户无法把服务器当作内网探针。

#### 验收标准

1. 当不持 `connectors` 权限的用户调用 `GET/PUT /api/connectors/custom-mcp`、`PATCH /api/connectors/custom-mcp/servers/{name}`、`POST /api/connectors/custom-mcp/test` 时，接口应当返回 403。
2. 当 `probe_streamable_http_mcp` 的目标不是回环地址时，它应当在建连前调用 `validate_https_url_resolved`；未命中 `w0-05` 白名单的私网地址应当在建连前失败，且不调用 `streamablehttp_client`。
3. 回环地址（`127.0.0.1`、`localhost`）的 http/https 探测应当保持基线行为。

### 需求 9：前端表单与后端语义一致

**用户故事：** 作为专家属主，我希望创建和编辑表单不再提供我无权使用的选项，以便不会遇到"保存即报错"。

#### 验收标准

1. `agentBackendForm.ts::backendRefToSpec` 在未选择本地目录时应当不再写 `root_dir: "/"`（改为不提交 backend 或不带 `root_dir`）；`supportsHostSkillPackages` 在 `rootDir` 等于传入的 `workspaceDir` 或未指定时返回 `true`，主机根不再恒为 `true`。
2. 自定义 MCP 页面应当始终不出现 stdio 选项与"添加 stdio 服务器"按钮；`CustomMcpTransport` 类型只含 `"streamable_http"`。
3. `cd dashboard && npx tsc -b && npm run lint && npm run test` 应当全绿，且 `agentBackendForm.skillPackages.test.ts` 覆盖第 1 条的新语义。
