# 实施计划：Agent 执行面收紧

> spec：`w3-06-agent-execution-hardening` ｜ 波次：Wave 3 ｜ 基线：`757fd12` ｜ 预估：9.5 人日
> 前置：`w0-02-ci-gates`、`w0-03-test-auth-baseline`、`w0-04-fork-isolation-points`、`w0-05-ssrf-intranet-allowlist`、`w1-01-security-hotfix`、`w1-02-capability-trim`、`w1-05-saas-decoupling`、`w2-01-offline-build` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

每个顶层任务完成后可独立提交；提交前运行任务内的验证命令。

- [ ] 1. 确认前置 spec 已合入并记录基线
  - 改动：无代码改动。确认 `src/octop/capability_catalog.py` 含 `RESERVED_CAPABILITIES["agent_shell"]`，`src/octop/infra/capabilities.py` 含 `forced_disabled_tools` 与 `REMOVED_CAPABILITY_TOOLS`，`src/octop/infra/connectors/custom_mcp_gate.py` 存在，`manager.py::_build_harness_config` 已含 `web_search_tools=False`。
  - 验证：`rg -n 'agent_shell' src/octop/capability_catalog.py && rg -n 'def forced_disabled_tools' src/octop/infra/capabilities.py && rg -n 'def drop_non_http_configs' src/octop/infra/connectors/custom_mcp_gate.py && rg -n 'web_search_tools=False' src/octop/infra/agents/manager.py && make all`
  - _需求：5.3_

- [ ] 2. 默认后端以工作区为根（resolver）
  - [ ] 2.1 先改测试
    - 改动：`tests/unit/backend/test_resolver.py`：`test_default_agent_backend_spec_posix_uses_host_root` 改为断言全平台返回工作区根；两个 `test_default_agent_backend_resolve_*` 用例的 `cwd == "/"` 改为工作区；`test_windows_neutralize_is_passthrough_on_posix` 反转为"POSIX 也收敛"；新增 `composite.routes` 子后端收敛用例；新增 `_backend_supports_host_skill_packages(default_agent_backend_spec(ws), workspace_dir=ws) is True` 用例（放 `tests/unit/agents/test_agent_manager.py`）。同步 `tests/unit/gateway/` 下三处对该函数的期望。
    - 验证：`uv run pytest tests/unit/backend/test_resolver.py -q`（此时应失败）
    - _需求：1.1, 1.2, 1.4_
  - [ ] 2.2 实现
    - 改动：`src/octop/infra/backend/resolver.py` 的 `default_agent_backend_spec` 删除 `DEFAULT_BACKEND_SPEC` 导入与平台分支；`windows_neutralize_host_root` 更名 `neutralize_host_root`，删去 `os.name != "nt"` 早退，覆盖 `routes`；保留别名 `windows_neutralize_host_root = neutralize_host_root`；更新 `src/octop/infra/utils/host_dirs.py` 中提到旧名的注释。
    - 验证：`uv run pytest tests/unit/backend tests/unit/gateway tests/unit/agents/test_agent_manager.py -q`
    - _需求：1.1, 1.2, 1.4_

- [ ] 3. 创建时显式落盘 backend，首个专家不再以 HOME 为根
  - 改动：先在 `tests/unit/agents/test_agent_manager.py` 加"无 backend 创建后 `config["backend"]["root_dir"]` 等于工作区"用例，在 `tests/unit/agents/test_default_agent.py::test_bootstrap_creates_general_assistant` 改期望；再改 `src/octop/infra/agents/manager.py::create`：≈L551 捕获 `seed_workspace_dir_on_create` 返回值，≈L555 后加 `config.setdefault("backend", default_agent_backend_spec(ws_host))`；`src/octop/infra/agents/default_agent.py::bootstrap_default_agent` 不再传 `backend`，`default_home_local_backend` 无引用后删除。
  - 验证：`uv run pytest tests/unit/agents/test_agent_manager.py tests/unit/agents/test_default_agent.py tests/integration/test_setup_bootstrap.py -q`
  - _需求：1.3_

- [ ] 4. 后端根目录校验收紧，容器内策略生效
  - [ ] 4.1 先改测试
    - 改动：`tests/integration/test_agents_api.py` 与 `tests/integration/test_experts_api.py` 为五个入口各加一例：无策略用户提交 `root_dir="/"` 得 400 `WORKSPACE_ROOT_RESTRICTED`；有策略用户新建专家（不带 backend）成功。`tests/unit/users/test_resource_policy.py::test_normalize_workspace_root_dir_rejected_in_container` 改写为"容器内允许并生效"，新增 `effective_workspace_root_dir` 容器用例。
    - 验证：`uv run pytest tests/unit/users/test_resource_policy.py tests/integration/test_agents_api.py tests/integration/test_experts_api.py -q`（此时应失败）
    - _需求：2.1, 2.2, 2.4_
  - [ ] 4.2 实现
    - 改动：`src/octop/api/common/validators.py::assert_user_backend_root_dirs` 加 `own_workspace_dir`，无策略时只放行缺省根或等于 `own_workspace_dir` 的根；`src/octop/infra/users/resource_policy.py` 的 `raise_if_backend_outside_user_root` 加同名参数，删除 `effective_workspace_root_dir` 与 `normalize_workspace_root_dir` 中的 `running_in_container()` 短路；`src/octop/api/routers/agents.py` ≈L360 与 `experts.py` 的更新入口传入该 Agent 的 `workspace_dir`。
    - 验证：`uv run pytest tests/unit/users tests/integration/test_agents_api.py tests/integration/test_experts_api.py tests/integration/test_bwrap_jail.py -q`
    - _需求：2.1, 2.2, 2.4_

- [ ] 5. 主机文件系统浏览限制在用户工作区根
  - 改动：先改 `tests/integration/test_filesystem_api.py`：`test_non_admin_can_list_outside_home` 改为 `test_non_admin_cannot_list_without_workspace_root`（400），复核其余 defaults / probe 用例；加管理员无策略同样 400 的用例。再改 `src/octop/api/routers/filesystem.py`：新增 `_require_workspace_root`，`list_host_dirs`、`probe_host_dir`、`mkdir_host_dir`、`rename_host_directory` 改用它；`filesystem_defaults` 无策略返回空根；改写模块说明。
  - 验证：`uv run pytest tests/integration/test_filesystem_api.py tests/unit/infra/utils/test_host_dirs.py -q && ! rg -n 'browse from host root' src/octop/api/routers/filesystem.py`
  - _需求：2.3, 2.5_

- [ ] 6. 执行类工具默认审批、命令护栏默认拦截
  - 改动：先确认 `SecurityPolicy.defaults().to_dict()["hitl"]` 的工具字段键名（`rg -n 'class SecurityPolicy' .venv/lib/python3.12/site-packages/harness_agent` 定位后读其 `defaults()`）。改 `tests/unit/test_security_settings.py::test_load_defaults_when_missing`（含 `resolve_interrupt_on()` 断言）与 `tests/integration/test_security_api.py` 的默认值断言；在 `tests/unit/cron/` 加 `hitl_required` 使运行失败的回归用例。再改 `src/octop/infra/agents/security/policy_store.py::_default_policy`。
  - 验证：`uv run pytest tests/unit/test_security_settings.py tests/integration/test_security_api.py tests/unit/cron -q`
  - _需求：3.1, 3.2_

- [ ] 7. 登记 `agent_shell` 能力
  - 改动：先在 `tests/unit/test_capabilities_config.py` 加：`agent_shell` 在 `CAPABILITY_CATALOG` 而不在 `RESERVED_CAPABILITIES`；关闭时 `forced_disabled_tools` 含 `execute`；在 `tests/integration/test_tool_settings_api.py` 加关闭时 `execute` 为 `available=false`、`disableable=false`。再改 `src/octop/capability_catalog.py`（移入目录，`default_enabled=True`，`tools={"execute","bash","shell"}`），新增 `src/octop/infra/agents/execution_policy.py` 引用该集合为 `EXECUTION_TOOLS`。
  - 验证：`uv run pytest tests/unit/test_capabilities_config.py tests/integration/test_tool_settings_api.py -q`
  - _需求：4.1, 4.2_

- [ ] 8. harness 内部分支：子代理遵守 `tools_disabled`
  - 改动（行内 Git `orcakit-harness-agent` 内部分支）：先加用例"主代理 `tools_disabled={'execute','web_fetch'}` 时构建的子代理工具集不含二者"，再在子代理构建处减去主代理 `tools_disabled`；按 `w2-01` 的发布流程出包，Octop 侧按其约定更新依赖并在末尾 commit `make relock`。
  - 验证：内部分支 `uv run pytest -q` 全绿；Octop 侧 `uv run pytest tests/unit/agents -q`
  - _需求：4.3_

- [ ] 9. `web_fetch` 强制禁用与热同步回归
  - 改动：先加用例：`tests/unit/agents/test_tool_catalog.py` 断言 `web_fetch` 不在 `BUILTIN_TOOL_CATALOG`、强制集与 `CRITICAL_TOOLS` 不相交；`tests/unit/agents/test_agent_manager.py` 断言 `persist_tools_disabled(agent_id, set())` 后推送给 `set_tools_disabled` 的集合含 `web_fetch`，`_build_harness_config` 结果 `web_search_tools is False` 且 `tools_disabled` 含 `web_fetch`。再在 `src/octop/infra/capabilities.py::REMOVED_CAPABILITY_TOOLS` 追加 `web_fetch`，删去 `src/octop/infra/agents/tool_catalog.py` 的 `web_fetch` 目录项（i18n 键不删）。
  - 验证：`uv run pytest tests/unit/agents/test_tool_catalog.py tests/unit/agents/test_agent_manager.py tests/integration/test_tool_settings_api.py tests/unit/i18n -q`
  - _需求：5.1, 5.2, 5.3_

- [ ] 10. 命令执行环境最小化
  - 改动：先改 `tests/unit/agents/test_execute_env.py`（≈L56、≈L114 改为 `inherit_env is False`；新增 `env` 只含白名单、`~/.octop/env` 非受保护键与 `OCTOP_*` 平台变量，`monkeypatch.setenv("OCTOP_DATABASE_PASSWORD", …)` 后不出现）；在 `tests/integration/test_bwrap_jail.py` 旁新增 `posix_only` 用例，用默认后端执行 `env` 断言哨兵变量不出现。再新增 `execution_policy.build_execute_base_env`，改 `src/octop/infra/agents/execute_env.py::inject_agent_execute_env`（新增 `base_env` 参数，`inherit_env=False`）。
  - 验证：`uv run pytest tests/unit/agents/test_execute_env.py tests/integration/test_bwrap_jail.py -q`
  - _需求：6.1, 6.2, 6.3, 6.4_

- [ ] 11. 自定义 MCP 只留 HTTP（后端）
  - [ ] 11.1 先改测试
    - 改动：`tests/unit/connectors/test_custom_mcp.py`：`test_normalize_streamable_http_and_stdio` 改为 stdio 抛 `ValueError`、`http` 别名归一；删除 `test_harness_spec_stdio_default_args`；其余 fixture 中的 stdio 规格改为 streamable_http。`tests/integration/test_connectors_api.py` 加 PUT / test 提交 stdio 得 400、库中残留 stdio 时 GET 不返回。
    - 验证：`uv run pytest tests/unit/connectors/test_custom_mcp.py tests/integration/test_connectors_api.py -q`（此时应失败）
    - _需求：7.1, 7.2, 7.4_
  - [ ] 11.2 实现
    - 改动：`src/octop/infra/connectors/custom_mcp.py`（`Transport`、`normalize_server_spec`、删 `_normalize_env`/`_normalize_args`、`harness_spec_for_server` stdio 兜底）；`src/octop/infra/connectors/probe.py` 删 `_probe_stdio_mcp` 与分派；`src/octop/infra/connectors/custom_mcp_gate.py` 删 `reject_stdio_*` 及调用点，保留 `drop_non_http_configs`；GET 路径过滤非 HTTP 条目。
    - 验证：`uv run pytest tests/unit/connectors tests/integration/test_connectors_api.py -q && ! rg -n 'stdio_client|StdioServerParameters|_probe_stdio_mcp' src/octop/infra/connectors/probe.py src/octop/infra/connectors/custom_mcp.py`
    - _需求：7.1, 7.2, 7.3, 7.4_

- [ ] 12. 自定义 MCP 收归 `connectors` 权限并补探测校验
  - 改动：先在 `tests/integration/test_connectors_api.py` 加无 `connectors` 权限用户调用四个端点得 403；在 `tests/unit/connectors/` 新增 `test_probe_ssrf.py`：私网目标未入白名单时 `probe_streamable_http_mcp` 不调用 `streamablehttp_client`（monkeypatch），回环目标保持基线。再改 `src/octop/api/routers/connectors.py` 四个 custom-mcp 端点加 `Depends(require_permission("connectors"))`，改 `src/octop/infra/connectors/probe.py::probe_streamable_http_mcp` 建连前调用 `validate_https_url_resolved`（回环除外）。
  - 验证：`uv run pytest tests/integration/test_connectors_api.py tests/unit/connectors -q`
  - _需求：8.1, 8.2, 8.3_

- [ ] 13. 前端：后端表单与技能包判定
  - 改动：先改 `dashboard/src/pages/Experts/components/agentBackendForm.skillPackages.test.ts`（主机根不再恒真；等于 `workspaceDir` 或未指定为真）；再改 `agentBackendForm.ts` 的 `backendRefToSpec`、`supportsHostSkillPackages`、`supportsHostSkillPackagesFromConfig`，`CreateFromExpertDrawer.tsx`、`EditAgentDrawer.tsx` 传入 `workspaceDir`，`AgentBackendFields.tsx` 在 `tree_root` 为空时隐藏目录选择器并显示提示（文案写 `dashboard/src/locales/intranet/{en,zh}.json`）。
  - 验证：`cd dashboard && npx tsc -b && npm run lint && npm run test`
  - _需求：9.1, 9.3_

- [ ] 14. 前端：自定义 MCP 去 stdio
  - 改动：`dashboard/src/api/modules/connectors.ts` 的 `CustomMcpTransport` 收窄并删除 stdio 专用字段；`CustomMcpTab.tsx` 删 stdio 选项与"添加 stdio"按钮；`CustomMcpServerCard.tsx` 删 command/args/env 输入区；`customMcpUtils.ts` 的示例、归一与默认名固定为 HTTP。
  - 验证：`cd dashboard && npx tsc -b && npm run lint && npm run test && ! rg -n '"stdio"' dashboard/src/pages/Agent/Connectors dashboard/src/api/modules/connectors.ts`
  - _需求：9.2, 9.3_

- [ ] 15. 前端：安全页兜底值
  - 改动：`dashboard/src/pages/Settings/Security/index.tsx` 中 `tool_guard` 相关的两处 `?? "warn"` 改为 `?? "block"`（`skill_scan` 兜底不改）。
  - 验证：`cd dashboard && npx tsc -b && npm run lint && rg -n 'tool_guard.*\?\? "block"' src/pages/Settings/Security/index.tsx`
  - _需求：3.3_

- [ ] 16. 收尾
  - 改动：清理本 spec 引入的孤儿符号；`CHANGELOG-intranet.md` 记录默认根、审批与护栏默认值、执行环境、stdio 移除、`web_fetch` 强制禁用、`agent_shell` 开关；`docs/api-intranet.md` 记录 `/api/filesystem/*` 无策略返回 400、custom-mcp 需 `connectors` 权限且拒绝 stdio、tool-settings 不再含 `web_fetch`；在 `docs/intranet/capabilities.md`（`w1-02` 建立）补 `agent_shell` 条目与 D6 简化路径。
  - 验证：`make all && cd dashboard && npx tsc -b && npm run lint && npm run test`
  - _需求：2.5, 7.3, 9.3_
