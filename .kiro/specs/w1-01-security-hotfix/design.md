# 设计文档：五个现成漏洞热修

> spec：`w1-01-security-hotfix` ｜ 波次：Wave 1 ｜ 基线：`757fd12` ｜ 预估：7 人日
> 前置：`w0-01-fork-migration-namespace`、`w0-02-ci-gates`、`w0-03-test-auth-baseline`、`w0-04-fork-isolation-points` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 概述

**结论：** 五个漏洞都在 HTTP 适配层或它紧邻的装配点上，修复不需要新表、新配置键、新错误码或新权限键。整体做法分三类：

1. **收紧出口**（#1、#1b）：把 `_row_to_dict` 里的凭据换成布尔位，列表接口改用已有的 `providers` / `voice` 权限键；唯一会被脱敏打断的功能是"不重输密钥拉取模型"，用 `provider_id` 补回，并规定库内密钥只能发往库内登记的主机。
2. **补齐判定**（#2、#4、#5）：用户路由加两个独立的 `_assert_*` 函数；ACP 的 4 个 agent 作用域路由改为 `require_admin()`，运行时只对管理员加载自定义 runner；`resume-wizard` 复用 `_authorize_setup_mid_wizard`，并新增持久标记 `setup.completed`。
3. **临时闸门**（#3、#4）：stdio 传输在保存、探测、运行时三处拒绝，共享位只允许管理员设置，存量数据在启动时或由 fork 迁移清理。它们是过渡实现，不做命令白名单：ACP 由 `w1-02` 物理删除，stdio 由 `w3-06` 移除。

新增 3 个 fork 自有模块（`infra/setup/completion.py`、`infra/connectors/custom_mcp_gate.py`、`infra/voice/credentials.py`）与 1 对 fork 迁移，改动的上游文件都只加局部判断。`infra/agents/manager.py` 只改 1 处单行调用。

## 现状

以下事实均在基线 `757fd12` 上用 `rg` / `sed -n` 核实。

### #1 大模型供应商

- `src/octop/api/routers/providers.py::_row_to_dict`（≈L118-136）在 ≈L132 原样输出 `"api_key": r.api_key`。所有出口共用它：`list_providers`、`admin_list_providers`、`admin_create_provider`、`admin_patch_provider`。
- `list_providers`（≈L187-193）的依赖在 ≈L189，是 `_: Any = Depends(current_user)`；同文件 `set_active_model`（≈L177）已在用 `require_permission("providers")`。路由挂在 `/api/providers`（`src/octop/api/app.py` ≈L228）。
- `ProviderFetchModelsBody`（≈L93-97）只有 `kind`、`api_key`、`base_url`、`extra_json`；`admin_fetch_provider_models`（≈L328-349）在 `api_key` 为空时返回 `{"ok": False, "error": "api_key is required"}`。仓库里没有"按 id 用库内密钥拉模型"的路由。
- `admin_test_provider`（≈L465-485，`POST /api/admin/providers/{provider_id}/test`）本来就读库内密钥。
- dashboard 读取明文密钥的位置（基线全部核实）：
  - `dashboard/src/pages/Settings/Models/useProviders.ts` 的 `ProviderRow`（≈L65-74）有 `api_key: string | null`（≈L70），数据来自 `request<ProviderRow[]>("/admin/providers")`（≈L113）。
  - `components/modals/ProviderConfigModal.tsx`：`hasApiKey`（≈L95）；测试流程（≈L768-799）在 `useDraft || !hasApiKey` 时走 `testProviderDraft`，并在 ≈L787 用 `draftApiKey || provider.api_key` 回传明文，否则走 ≈L796 的 `${apiPrefix}/${provider.id}/test`；拉取模型（≈L867-880）在 ≈L869 用 `draftApiKey || provider.api_key`。
  - `components/modals/ModelListEditor.tsx` ≈L207 与 ≈L367：`canTest ?? !!provider.api_key`。
  - `components/sections/ActiveModelPool.tsx` ≈L60：`map.set(p.id, !!p.api_key)`。
  - `components/cards/ProviderCard.tsx` ≈L54 的 `hasApiKey`，以及 ≈L141-146 的 `maskedKey`（前 4 位 + 后 4 位）。**源分析遗漏此文件。**
  - `presetUtils.ts` 的 `localPresetApiKey`（≈L179-182）用 `api_key` 的占位值 `"onnx"` / `"ollama"` 识别本地运行时，被 `isOnnxProviderRow` / `isOllamaProviderRow` 调用，消费方是 `ProviderCard`、`ProviderConfigModal`、`ModelListEditor`。**源分析遗漏：只删 `api_key` 会让本地 ONNX / Ollama 供应商在按名称与 base_url 兜底之外失去识别依据。**
  - `providerApi.ts` 的 `fetchProviderModels`（≈L54-66）手工拼 JSON body（≈L59-64），只改接口类型不会把新字段发出去。
- 后端对应的本地运行时判定在 `src/octop/infra/agents/providers/model_flags.py`：`is_onnx_local_provider`（≈L16）、`is_ollama_local_provider`（≈L33），都以 `provider_api_key` 占位值优先。
- `dashboard/src/pages/Settings/octop/Providers.tsx` 未被任何文件导入，并在 ≈L34-42 自带局部 `ProviderRow` 类型。**源分析称"不处理则 `tsc -b` 必红"不成立**：它不引用共享类型，响应形状变化不影响编译。

### #1b 语音供应商

- `src/octop/api/routers/voice.py::_row_to_dict`（≈L29-40）在 ≈L36 输出 `api_key`、≈L37 输出 `"extra": r.get_extra()`。
- `list_voice_providers`（≈L88-93）依赖在 ≈L90，是 `current_user`；`set_active_voice`（≈L107）已在用 `require_permission("voice")`。
- `admin_patch_voice_provider`（≈L188-211）把 `body.extra_json` 原样交给 `voice_provider_repo.update`。仓储的 `update`（`src/octop/infra/db/repos/voice_providers.py` ≈L105-136）经 `partial_updates`（`src/octop/infra/db/repos/_base.py` ≈L34-43）对 `None` 字段跳过，但非 `None` 的 `extra_json` 会整体替换。
- 腾讯语音的凭据在两处：`src/octop/infra/voice/adapters.py::_parse_tencent_credentials`（≈L39-51）先读 `extra.secret_id` / `extra.secret_key`，缺失时回退到 `api_key` 的 `sid:sk` 形式。
- dashboard：`dashboard/src/api/modules/voice.ts` 的 `VoiceProviderRow`（≈L14-24）有 `api_key`（≈L20）与 `extra`（≈L21）；`dashboard/src/pages/Settings/Voice/index.tsx` 的 `openConfigure`（≈L97-106）用读回的明文预填 `apiKey`、`secretId`、`secretKey`，`buildProviderPayload`（≈L108-146）在 ≈L113-118 把 `secret_id` / `secret_key` 写回 `extra`，`validateCredentials`（≈L148-156）要求凭据完整，`handleProbe`（≈L158-182）总是调 `testConfiguration`。`voiceApi.getProviders()` 的唯一调用方是该页（≈L52），该页属于需要 `voice` 权限的「模型」页。

### #2 用户管理

- `src/octop/infra/users/identity.py` 的 `Role` 只有 `ADMIN`、`USER` 两个值（≈L9-11）。
- `src/octop/api/routers/users.py`：五个写路由全部是 `require_permission("users")`；`user_has_permission`（`src/octop/infra/users/permissions.py` ≈L225-234）对管理员放行、对持键者放行。
- `_assert_can_assign`（≈L83-93）只比较权限键，不看角色。`create_user`（≈L159-184）在 ≈L171 执行 `role = Role(body.role)`，没有任何角色约束。
- `patch_user`（≈L199-239）的角色分支在 ≈L217-220，唯一限制是 `user_id == actor.id and Role(body.role) is not Role.ADMIN`（禁止自降级）；当 `body.role == "admin"` 时直接 `set_role`。停用分支在 ≈L225-226。
- `unlock_user_login`（≈L242-252）、`reset_password`（≈L255-265）、`delete_user`（≈L268-279）都不看目标角色。
- dashboard `dashboard/src/pages/Admin/Users/UsersListPanel.tsx`：`createRoleOptions`（≈L923-937，管理员选项在 ≈L930-934）；`onEditSubmit`（≈L1175 起）**每次都在请求体里带上 `role: values.role`**（≈L1184）；写操作处理函数有 `onCreate`（≈L1083）、`togglePatch`（≈L1148 起，以 `onTogglePatch` prop 传给卡片与表格视图）、`onDelete`（≈L1201）、`onResetSubmit`（≈L1213）、`onUnlockLogin`（≈L1233），改密弹窗由 `setResetTarget(row)` 打开（≈L1319、≈L1496）。现成的 `dashboard/src/hooks/useUserRole.ts` 返回当前用户角色。
- **勘误：** 源分析建议"非管理员一律不能带 `role` 字段"。由于编辑弹窗总会带 `role`，这会让持 `users` 权限的非管理员连普通账号的显示名都改不了。本 spec 只禁止"授予 admin"与"以管理员为目标"。

### #3 自定义 MCP

- `src/octop/api/routers/connectors.py`：`put_custom_mcp`（≈L531-558）、`patch_custom_mcp_server`（≈L561-588）、`test_custom_mcp`（≈L591-625）都只挂 `current_user`。`put_custom_mcp` 已有审计（≈L545-550，`connector.custom_mcp.save`），PATCH 与 test 没有。
- `test_custom_mcp` 先组装 `spec`：内联分支（≈L601）或按 `name` 读库（≈L602-609），再在 ≈L615 调 `probe_custom_mcp_server(spec)`。
- **源分析遗漏的第二个探测入口：** `test_instance`（`POST /api/connector-instances/{instance_id}/test`，≈L911-926）经 `_resolve_custom_target`（≈L456-471）解析到自定义目标后，同样调用 `probe_custom_mcp_server(dict(raw))`。
- `src/octop/infra/connectors/probe.py::probe_custom_mcp_server`（≈L497-520）先 `normalize_server_spec`，stdio 分支进入 `_probe_stdio_mcp`（≈L523 起），它用 `mcp.client.stdio.stdio_client`（函数内导入，≈L526）直接起子进程。
- `src/octop/infra/connectors/custom_mcp.py::normalize_server_spec`（≈L143-192）接受 `streamable_http`、`stdio`、`http`（≈L146-148）。`tests/unit/connectors/test_custom_mcp.py` 有大量用例直接调用 `normalize_server_spec`、`validate_servers_map` 与 `ConnectorService.put_custom_servers` 并传入 stdio（例如 ≈L81-93、≈L156、≈L160、≈L226-240、≈L262-270、≈L281-293），所以闸门不能下沉到这些函数。
- 运行时唯一的自定义 MCP 装配点是 `src/octop/infra/connectors/service.py::ConnectorService.custom_harness_configs`（≈L447-463）。它先装配本人的 server，再遍历所有 `custom-mcp` 父记录，把其他用户标了 `shared` 的 server 注入进来。调用方有三处：`infra/agents/manager.py` ≈L1446、`infra/connectors/builder.py` ≈L524、`service.py` 自身 ≈L493。
- `ConnectorService.patch_custom_server`（≈L276 起）可以单独改 `shared`；自定义 MCP 文档存放在加密的连接器凭据里（`decrypt`，≈L101-105），无法用 SQL 清理。

### #4 ACP

- `src/octop/api/routers/acp.py`：全局路由 `get_global_acp_runners`、`put_global_acp_runners`、`get_global_acp_runner`、`put_global_acp_runner`（≈L185-201）、`delete_global_acp_runner` 都挂 `require_admin()`。
- agent 作用域的 `get_acp_runner`（≈L268-276）、`put_acp_runner`（≈L279-288）、`delete_acp_runner`（≈L291-303）只挂 `current_user`，然后用 Python 直调对应的全局函数并显式传入 `user=user`，被调方的 `Depends(require_admin())` 因此永不执行。
- `put_acp_config`（≈L234-250）只挂 `current_user`，在 ≈L244-247 直接 `save_runners(user.id, runners)`。
- `get_acp_config`（≈L221-231）与 `put_acp_tool_toggle`（≈L253-265）是 owner 级接口。dashboard `dashboard/src/api/modules/acp.ts` 只在页面里用到 `getGlobalRunners`、`getConfig`、`updateGlobalRunners`、`updateToolEnabled`（`pages/Agent/ACP/index.tsx` ≈L54/86/127/136），`updateConfig`、`updateAgentRunner`、`deleteAgentRunner` 没有调用方。
- **源分析遗漏的第五条写入链：** `src/octop/api/routers/agents.py::patch_agent`（≈L345 起）对 owner 开放，在 ≈L379 把任意 `body.config` 写进 `config_json`；`src/octop/infra/agents/acp_settings.py::ACPSettingsStore.load_runners`（≈L52-72）在该用户没有 settings 键时调用 `_migrate_legacy_from_agents`（≈L84-105），把 agent 配置里的 `acp.runners` 迁入 settings。
- 运行时在 `src/octop/infra/agents/manager.py` ≈L2843-2846 用 `self._acp_settings.load_runners(acp_user_id)` 组装 `ACPConfig`，≈L2938 以 `acp_runners=acp_config.runners` 交给 harness。`acp_runner` 在 `HITL_TOOL_EXCLUDE`（`src/octop/i18n/domains/tools.py` ≈L38）中，管理员无法给它配人工审批。
- runner 存在 settings 表，键为 `acp_runners:user:<user_id>`（`acp_settings.py` ≈L16、≈L41-42）。`_runners_response`（≈L123-134）把内置运行器与保存的覆盖合并。
- `manager.py` 的 `self._repos` 是 `RepoBundle`，含 `user_repo`（`src/octop/infra/db/services.py` ≈L40）。

### #5 安装向导

- `src/octop/api/routers/setup.py::resume_wizard`（≈L378-387）的签名只有 `server: Any = Depends(get_server)`，零鉴权。
- `_enforce_wizard_token_phase`（≈L111-115）唯一的判据是 `user_manager.count() > 1`；`count()` 是裸 `SELECT COUNT(*) FROM users`（`src/octop/infra/db/repos/users.py` ≈L316-318）。全站恰有 1 个账号时窗口一直敞开。
- `finish`（≈L412-443）接受 `_authorize_setup_mid_wizard`（≈L139-152）认可的凭据：有效 wizard token，或 `count() == 1` 时的管理员 JWT。`finish` 带 `provider_draft` 时调 `_apply_provider_draft`（≈L173-210），写入供应商并 `set_active_model`。`provider_draft` 可以为空，所以"已配置 active model"不是完成安装的必要条件；`finish` 总会尝试创建 pinned id 为 `main` 的默认 agent（`SETUP_DEFAULT_AGENT_ID = "main"`，`src/octop/infra/agents/default_agent.py` ≈L20）。
- `/api/setup/` 在 JWT 中间件豁免清单里（`src/octop/api/deps.py` `_JWT_EXEMPT_PREFIXES` ≈L66-72），也被 setup 锁定中间件放行（`src/octop/api/middleware/setup_lockdown.py` ≈L16）。
- **勘误：** 源分析称"JWT 中间件不运行，所以 `Depends(require_admin())` 失效"。实际 `current_user`（`deps.py` ≈L186-198）在未命中 `request.state` 缓存时会自行解析 Authorization。真正不能用 `require_admin()` 的原因是语义：它会拒绝向导自己持有的 wizard token，而且不受 `count() == 1` 约束。
- 启动路径：`OctopServer.start()`（`src/octop/infra/server.py` ≈L281-332）在 `should_defer_control_plane_db` 为真时于 ≈L316-320 提前返回，否则在 ≈L324 建服务、≈L329 `_boot_runtime`；`bind_control_plane()`（≈L334-360）在 ≈L351 建服务、≈L356 `_boot_runtime`。首装向导的 `POST /setup/database` 在调用 `bind_control_plane` 之前先 `assert_control_plane_database_empty`（`src/octop/infra/db/rebind.py` ≈L82-99），所以基线上经这条路径打开的库用户数为 0；在这条路径上回填是防御性的，用来覆盖 `w0-01` 所列的其他启动形态。
- `settings` 是 KV 表，`SettingsRepo` 有 `get`、`set`（upsert）、`delete`、`get_active_model`（`src/octop/infra/db/repos/settings.py` ≈L14-38），写标记不需要 DDL。
- `tests/integration/test_setup_wizard.py::test_resume_wizard_after_admin_created`（≈L258-271）在 ≈L267-268 断言匿名调用返回 200，把漏洞钉成了预期行为。
- dashboard `dashboard/src/pages/Setup/wizardClient.ts::resolveSetupProbeToken`（≈L202-223）先用 wizard token、再用 setup JWT，最后才匿名 `resumeWizard()`，且整段包在 `try/catch → return null` 里；调用方 `FinishStep.tsx`（≈L35-56）与 `ModelStep.tsx`（≈L484-488）对 `null` 已提示既有文案 `wizard.sessionExpired`。所以后端加鉴权后前端自然降级，不需要改。

### 横切

- 审计写入接口：`AuditRepo.write(*, actor, action, target=None, payload=None)`（`src/octop/infra/db/repos/audit.py` ≈L39-50）；查询接口是 `GET /api/admin/audit-log`（`src/octop/api/routers/admin.py` ≈L47-56，需要 `admin_console` 权限）。**源分析写的 `/api/admin/audit` 不存在。**
- 可复用的错误码及默认状态（`src/octop/infra/errors.py` 的 `_DEFAULT_STATUS`）：`FORBIDDEN` 403、`NOT_FOUND` 404、`CONNECTOR_KIND_UNSUPPORTED` 400、`SETUP_TOKEN_INVALID` 401、`SETUP_REQUIRED` 409（setup 路由在需要 410 时显式传 `status=410`，见 `_enforce_wizard_token_phase`）。
- dashboard 现成文案：`models.pleaseEnterApiKey`、`models.apiKeyPlaceholderKeep`、`models.apiKeyExtraConfigured`（en、zh 都有）。

## 方案

### #1 供应商：脱敏 + 本地运行时字段 + "密钥跟随主机"

1. `_row_to_dict` 删除 `api_key`，新增 `has_api_key = bool(r.api_key)` 与 `local_runtime`。`local_runtime` 由新的私有函数 `_local_runtime(r)` 调用 `is_onnx_local_provider` / `is_ollama_local_provider` 算出，保证前端识别本地运行时的依据与后端删除保护一致，同时不泄露占位值以外的任何信息。
2. `list_providers` 的依赖改为 `require_permission("providers")`（该文件已导入）。
3. `ProviderFetchModelsBody` 新增 `provider_id: int | None = None`。`api_key` 为空且带 `provider_id` 时：行不存在返回 404；`base_url` 非空且（去首尾空白与末尾 `/` 后）与库内不同，返回 `{"ok": False, "error": "api_key is required"}`；否则用库内 `api_key`、库内 `base_url`，请求未带 `extra_json` 时用库内 `extra_json`。
   - **为什么加"密钥跟随主机"：** 如果允许 `provider_id` 搭配任意 `base_url`，一次调用就能把库内密钥发到调用者指定的主机。基线上持 `providers` 权限的人经"PATCH 改 base_url → `/{id}/test`"也能做到，但那条路径会留下持久改动；本 spec 不为它再开一条无痕的捷径。
   - `ProviderTestDraftBody` 不改：测试已保存的供应商本来就有 `/{id}/test`。
4. 前端：
   - `ProviderRow` 的 `api_key` 换成 `has_api_key: boolean` 与 `local_runtime: "onnx" | "ollama" | null`。
   - `presetUtils.localPresetApiKey` 改读 `local_runtime`，三个 `is*ProviderRow` 的参数类型同步；新增 vitest 用例。
   - `ProviderCard` 的 `hasApiKey` 改读 `has_api_key`，`maskedKey` 改为固定掩码（`has_api_key` 为真时显示 `••••••••`）。
   - `ProviderConfigModal`：`hasApiKey` 改读 `has_api_key`。测试流程改为：Base URL 变了而没有新密钥时提示 `models.pleaseEnterApiKey` 并返回；只有 `draftApiKey` 非空时才走 `testProviderDraft`（只传 `draftApiKey`），否则在 `has_api_key` 为真时走 `/{id}/test`。拉取模型流程同理：Base URL 变了而没有新密钥就提示并返回；有新密钥时照旧传 `api_key`；没有新密钥但 `has_api_key` 为真时传 `provider_id: provider.id`。
   - `ModelListEditor`、`ActiveModelPool` 改读 `has_api_key`；`providerApi.fetchProviderModels` 的接口与 JSON body 都加 `provider_id`。

### #1b 语音：通用敏感键脱敏 + PATCH 合并

1. 新模块 `src/octop/infra/voice/credentials.py` 按键名判定敏感项：`secret_id`、`secret_key`、`api_key`、`token`、`password`，以及以 `_key`、`_secret`、`_token`、`_password` 结尾的键（不区分大小写）。规则与厂商无关，`w1-05` 删掉腾讯语音后仍然适用。
2. `voice._row_to_dict`：删除 `api_key`，新增 `has_api_key`；`extra` 换成去掉敏感项的副本；新增 `has_secret_key`（被移除项中任一值非空时为真）。
3. `list_voice_providers` 改为 `require_permission("voice")`。
4. `admin_patch_voice_provider`：`body.extra_json` 不为 `None` 时，先经 `merge_voice_extra_json(row.extra_json, body.extra_json)` 合并——请求里缺失或为空串的敏感项沿用库内值，非敏感项以请求为准。`api_key` 继续依靠 `partial_updates` 的 `None` 跳过语义。`test-configuration` 不改：它测的是未保存的草稿，要求调用方提供凭据。
5. 前端：`VoiceProviderRow` 改为 `has_api_key`、`has_secret_key`；`openConfigure` 不再预填凭据；已有凭据时输入框占位显示既有文案 `models.apiKeyPlaceholderKeep`；`validateCredentials` 在"已有凭据且未重输"时放行；`buildProviderPayload` 在未重输时下发 `api_key: null`，腾讯分支的 `extra` 省略空的 `secret_id` / `secret_key`；`handleProbe` 在"已有凭据且未重输"时改调 `voiceApi.testProvider(existing.id, mode)`。

### #2 用户：两个独立判定函数

在 `users.py` 的 `_assert_can_assign` 之后新增：

- `_assert_may_assign_role(actor, role)`：`Role(role) is Role.ADMIN` 且 `actor.is_admin` 为假时，抛 `OctopError(ErrorCode.FORBIDDEN, "only admins can grant the admin role")`。
- `_assert_may_target(actor, row)`：`str(row.role) == "admin"` 且 `actor.is_admin` 为假时，抛 `OctopError(ErrorCode.FORBIDDEN, "only admins can manage admin accounts")`。

调用点：`create_user` 在 `Role(body.role)` 之前调前者；`patch_user` 拿到 `row` 后立刻调后者，`body.role is not None` 时再调前者；`unlock_user_login`、`reset_password`、`delete_user` 拿到 `row` 后调后者。两个函数独立成块，降低与上游 `patch_user` 主体的冲突面。

由于只有两个角色，这两条合起来等价于"非管理员只能对普通账号做 `role: "user"` 的无效变更"，编辑弹窗的正常保存不受影响。

前端 `UsersListPanel.tsx`：用 `useUserRole()` 得到 `actorIsAdmin`；`createRoleOptions` 在非管理员时去掉 `admin` 项；新增一个 `guardAdminTarget(row)` 判断（非管理员且 `row.role === "admin"` 时提示 overlay 文案 `adminUsers.adminTargetAdminOnly` 并返回 `false`），在 `togglePatch`、`onDelete`、`onUnlockLogin`、`onEditSubmit`、`onResetSubmit` 各加一行（改密在提交时拦截，不改两处打开弹窗的 JSX）。不改 JSX 结构。顺手把文件头注释（≈L10）里"all require admin role"改为"require the `users` permission; admin accounts are admin-only"，因为它描述的正是本次修改的规则。

### #3 自定义 MCP：临时闸门

新模块 `src/octop/infra/connectors/custom_mcp_gate.py` 提供三个纯函数与一个启动清理函数（接口见下节）。

1. **保存**：`put_custom_mcp` 在调用 `svc.put_custom_servers` 之前调用 `reject_stdio_servers(body.servers)`。判据是 `str(spec.get("transport") or "").strip() == "stdio"`，与 `normalize_server_spec` 的取值方式一致。
2. **探测**：`test_custom_mcp` 在组装好 `spec` 之后（≈L614 之后）、调用 `probe_custom_mcp_server` 之前调用 `reject_stdio_spec`，这样内联与按名读库两条分支都被拦住；`test_instance` 的自定义分支在 ≈L926 调用探测之前同样调用。
3. **运行时**：`custom_harness_configs` 的返回值经 `drop_non_http_configs` 过滤，只保留 `transport == "streamable_http"` 的项，其余丢弃并记 warning。按"只放行已知安全的传输"写，而不是"只拦 stdio"，存量库里的异常值也会被挡住。三个调用方都经过这一处，`manager.py` 不需要改。
4. **共享收归管理员**：`put_custom_mcp` 中任一项 `shared is True`、`patch_custom_mcp_server` 中 `body.shared is True`，且 `user.is_admin` 为假时抛 `FORBIDDEN`。取消共享（`shared: false`）不受限。
5. **存量共享清理**：`unshare_non_admin_custom_servers(services)` 遍历 `connector_repo.list_by_kind(CUSTOM_MCP_KIND)`，对属主不是管理员的文档，用 `ConnectorService.patch_custom_server(uid, name, shared=False)` 取消共享。它在 `start()` 与 `bind_control_plane()` 中、`_boot_runtime` 之前调用，所以 agent 启动时装配到的已是清理后的数据。每次启动都执行，幂等；管理员被降级后，其共享也会在下次启动时收回。
6. **审计**：`patch_custom_mcp_server` 成功后写 `connector.custom_mcp.patch`（target 为 server 名，payload 为本次改动的字段）；两个探测入口在闸门之前写 `connector.custom_mcp.probe`（target 为 server 名或 `<inline>`，payload 为 transport），所以被拒绝的尝试也有记录。

**为什么不设配置开关：** stdio 在终态中不存在（`w3-06` 移除），加一个开关要动 `config.py` 三触点、文档与测试，随后又要由 `w3-06` 删除。stdio 的存量配置不会被删除，只是不再被使用。若行方要求过渡期保留 stdio，见"待行方确认"D6。

**前端不改：** 非管理员打开共享开关或保存 stdio 时，会看到 `apiErrors.FORBIDDEN` / `apiErrors.CONNECTOR_KIND_UNSUPPORTED` 的本地化提示。表单与开关的去留由 `w3-06` 一并处理，避免在即将删除的表单上投入。

### #4 ACP：临时闸门

1. `get_acp_runner`、`put_acp_runner`、`delete_acp_runner`、`put_acp_config` 四个路由的依赖改为 `Depends(require_admin())`，保留 `_agent_row` 归属校验与对全局函数的委托。`put_acp_config` 整体收归管理员，dashboard 没有调用方；owner 切换工具开关继续走 `PUT /api/agents/{aid}/acp/tool`。
2. **运行时只对管理员加载自定义 runner**：在 `acp_settings.py` 新增 `runtime_acp_runners(store, user_repo, user_id)`。`user_id` 为空时返回 `{}`（与基线一致）；用户不存在或不是管理员时返回 `_runners_response({})`，即只有内置运行器的默认定义，不调用 `load_runners`，因此既不读 settings 覆盖，也不会触发遗留迁移；管理员照旧 `store.load_runners(user_id)`。`manager.py` ≈L2843-2845 的三行赋值换成一行调用，并在 ≈L23 的既有导入里加上该名字。这一步同时堵住"`PATCH /api/agents/{id}` 写 `config.acp.runners`"那条链。
3. **存量清理**：fork 迁移 `forkNNN_purge_non_admin_acp_runners` 删除非管理员的 `acp_runners:user:<id>` 行（SQL 见"数据模型"）。它由 `w0-01` 的 runner 在所有打开库的路径上执行一次。
4. 不做运行器命令白名单与 AST 静态门禁：`w1-02` 会删除 `acp.py`、`acp_settings.py` 及 `manager.py` 中的 ACP 装配，这些投入会在几天内作废。

### #5 安装向导

新模块 `src/octop/infra/setup/completion.py` 是 `setup.completed` 的唯一读写入口。

1. `resume_wizard` 增加形参 `authorization: str | None = Header(default=None)`，顺序为 `_enforce_wizard_token_phase` → `require_database` → `_authorize_setup_mid_wizard(authorization, server)` → 用户数为 0 时返回 400（保留）→ 签发新令牌。在函数 docstring 里写明不能改成 `Depends(require_admin())`（原因见"现状"）。
2. `_enforce_wizard_token_phase` 在 `count() > 1` 之外，增加"用户数 ≥ 1、`server.services` 已就绪且 `is_setup_completed(...)` 为真"时抛 410。用户数为 0 时向导本就处于开放状态（`initial-admin` 由 `_enforce_wizard_open` 把关），遗留标记不应挡住首装流程中的 `test-provider`；延迟建库时 `server.services` 为 `None`，判断会跳过。
3. `finish` 在 `consume` 之后、返回之前，若 `user_manager.count() >= 1` 则 `mark_setup_completed`。用户数为 0 时不写（基线用例 `test_finish_returns_ok_with_valid_token` 就是这种情形）。
4. `initial_admin` 创建成功后调用 `clear_setup_completed`。它只在用户数为 0、且持有 wizard token 时可达，信任级别与首次安装相同；用于"用户被全部删除后重新走向导"的场景，否则 `finish` 会因旧标记返回 410。
5. `backfill_setup_completed(services)`：已有标记则返回；用户数为 0 则返回；用户数 > 1、或 active model 已配置（`get_active_model()` 两项都非空）、或 `main` agent 存在，则写标记。在 `start()` 与 `bind_control_plane()` 中、`_boot_runtime` 之前调用。
   - 判据比源分析的"active model 已配置"更宽：`finish` 可以不带 `provider_draft`，只看 active model 会漏掉这类已完成的实例；`main` agent 是 `finish` 必然尝试创建的产物。
   - 向导中途的实例（1 个管理员、无模型、无 `main`）不回填，依靠第 1 点的鉴权保护。
6. 前端不改（见"现状"）。

## 组件与接口

| 文件 | 类型 | 改动 |
|---|---|---|
| `src/octop/api/routers/providers.py` | 修改 | `_row_to_dict`、新增 `_local_runtime`、`list_providers` 依赖、`ProviderFetchModelsBody.provider_id`、`admin_fetch_provider_models` |
| `src/octop/api/routers/voice.py` | 修改 | `_row_to_dict`、`list_voice_providers` 依赖、`admin_patch_voice_provider` 合并 `extra_json` |
| `src/octop/infra/voice/credentials.py` | **新增** | 语音 `extra` 敏感键判定、脱敏、合并 |
| `src/octop/api/routers/users.py` | 修改 | 新增 `_assert_may_assign_role`、`_assert_may_target`，5 个写路由各加一行调用 |
| `src/octop/api/routers/connectors.py` | 修改 | `put_custom_mcp`、`patch_custom_mcp_server`、`test_custom_mcp`、`test_instance` |
| `src/octop/infra/connectors/custom_mcp_gate.py` | **新增** | stdio 闸门、运行时过滤、存量共享清理 |
| `src/octop/infra/connectors/service.py` | 修改 | `custom_harness_configs` 返回前过一次 `drop_non_http_configs` |
| `src/octop/api/routers/acp.py` | 修改 | 4 个路由依赖改为 `require_admin()` |
| `src/octop/infra/agents/acp_settings.py` | 修改 | 新增 `runtime_acp_runners` |
| `src/octop/infra/agents/manager.py` | 修改 | ≈L23 导入加一个名字；≈L2843-2845 换成单行调用 |
| `src/octop/infra/db/migrations/forkNNN_purge_non_admin_acp_runners.sql`、`.pg.sql` | **新增** | 存量非管理员 runner 清理 |
| `src/octop/infra/setup/completion.py` | **新增** | `setup.completed` 读写与回填 |
| `src/octop/api/routers/setup.py` | 修改 | `_enforce_wizard_token_phase`、`resume_wizard`、`initial_admin`、`finish` |
| `src/octop/infra/server.py` | 修改 | `start()`、`bind_control_plane()` 各加两行启动步骤 |
| `dashboard/src/pages/Settings/Models/useProviders.ts`、`presetUtils.ts`、`providerApi.ts`、`components/cards/ProviderCard.tsx`、`components/modals/ProviderConfigModal.tsx`、`components/modals/ModelListEditor.tsx`、`components/sections/ActiveModelPool.tsx` | 修改 | 见方案 #1 |
| `dashboard/src/pages/Settings/Models/presetUtils.test.ts` | **新增** | `local_runtime` 判定 |
| `dashboard/src/api/modules/voice.ts`、`dashboard/src/pages/Settings/Voice/index.tsx` | 修改 | 见方案 #1b |
| `dashboard/src/pages/Admin/Users/UsersListPanel.tsx` | 修改 | 见方案 #2 |
| `dashboard/src/locales/intranet/{en,zh}.json` | 修改（`w0-04` 建立） | 新增 `adminUsers.adminTargetAdminOnly` |
| `CHANGELOG-intranet.md`、`docs/api-intranet.md` | 修改（`w0-04` 建立） | 见任务 10 |

关键签名：

```python
# src/octop/api/routers/providers.py
class ProviderFetchModelsBody(BaseModel):
    kind: str
    api_key: str | None = None
    base_url: str | None = None
    extra_json: str | None = None
    provider_id: int | None = None          # 新增：api_key 为空时取库内密钥

def _local_runtime(r: Any) -> Literal["onnx", "ollama"] | None: ...

# src/octop/infra/voice/credentials.py（新增）
def is_sensitive_extra_key(key: str) -> bool: ...
def redact_voice_extra(extra: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
    """返回（去掉敏感项的副本, 被去掉的项中是否有非空值）。"""
def merge_voice_extra_json(stored_json: str | None, incoming_json: str) -> str:
    """请求中缺失或为空串的敏感项沿用库内值；非敏感项以请求为准。"""

# src/octop/api/routers/users.py
def _assert_may_assign_role(actor: User, role: str) -> None: ...
def _assert_may_target(actor: User, row: Any) -> None: ...

# src/octop/infra/connectors/custom_mcp_gate.py（新增）
def reject_stdio_spec(name: str, spec: Any) -> None:
    """spec 为 stdio 时抛 OctopError(ErrorCode.CONNECTOR_KIND_UNSUPPORTED, details={"transport": "stdio", "server": name})。"""
def reject_stdio_servers(servers: Mapping[str, Any]) -> None: ...
def drop_non_http_configs(configs: dict[str, Any]) -> dict[str, Any]: ...
def unshare_non_admin_custom_servers(services: SharedServices) -> list[tuple[int, str]]:
    """返回被取消共享的 (owner_user_id, server_name)；ConnectorService 在函数内延迟导入以避免循环依赖。"""

# src/octop/infra/agents/acp_settings.py
def runtime_acp_runners(
    store: ACPSettingsStore, user_repo: UserRepo, user_id: int | None
) -> dict[str, Any]: ...

# src/octop/infra/setup/completion.py（新增）
SETUP_COMPLETED_KEY: Final = "setup.completed"
def is_setup_completed(settings_repo: SettingsRepo) -> bool: ...
def mark_setup_completed(settings_repo: SettingsRepo) -> None: ...
def clear_setup_completed(settings_repo: SettingsRepo) -> None: ...
def backfill_setup_completed(services: SharedServices) -> bool: ...
```

`server.py` 在 `start()`（≈L324 建服务之后、≈L329 `_boot_runtime` 之前）与 `bind_control_plane()`（≈L351 之后、≈L356 之前）各加：

```python
backfill_setup_completed(self.services)
unshare_non_admin_custom_servers(self.services)
```

导入沿用 `server.py` 已有的函数内延迟导入写法（`# noqa: PLC0415`）。

模块边界：`infra/setup/completion.py` 只依赖 `infra/db` 与 `infra/agents/default_agent` 的常量（函数内导入）；`infra/connectors/custom_mcp_gate.py` 依赖 `infra/connectors`、`infra/db`、`infra/errors`；`infra/voice/credentials.py` 只依赖标准库。三者都不读 `octop.config`，符合 AGENTS.md §5。

## 数据模型

- **fork 迁移 `forkNNN_purge_non_admin_acp_runners`**（号不预占，合入 fork 主干时取下一个可用号），SQLite 与 PostgreSQL 两份内容相同：

  ```sql
  DELETE FROM settings
  WHERE key IN (
    SELECT 'acp_runners:user:' || CAST(id AS TEXT) FROM users WHERE role <> 'admin'
  );
  ```

  `||` 与 `CAST(... AS TEXT)` 在两种方言中都可用；`DELETE` 天然幂等；不含 `BEGIN`/`COMMIT`，不在字面量里用 `?`，语句以 `;` 加换行结尾，符合 `w0-01` 的约定。该迁移不改 `_schema_version`，也不改任何 `assert v == 15` 断言。
- **settings 键 `setup.completed`**：值为 `"1"`，由 `completion.py` 读写。KV 表，无 DDL。
- **响应形状变化**（不涉及存储）：
  - providers 元素：删除 `api_key`；新增 `has_api_key: bool`、`local_runtime: "onnx" | "ollama" | null`。
  - voice providers 元素：删除 `api_key`；新增 `has_api_key: bool`、`has_secret_key: bool`；`extra` 去掉敏感项。
  - fetch-models 请求体：新增可选 `provider_id: int`。
- `providers.api_key`、`voice_providers.api_key` / `extra_json` 的存储不变，落库加密由 `w3-05` 负责。

## 配置

无。本 spec 不新增 `OctopConfig` 字段。源分析中的 `custom_mcp_stdio_allowlist`、`acp_runner_command_allowlist` 与环境变量 `OCTOP_CUSTOM_MCP_STDIO_ALLOWLIST`、`OCTOP_ACP_RUNNER_ALLOWLIST` 随白名单方案一并取消。

## 错误处理

不新增 `ErrorCode`，因此不改 `_DEFAULT_STATUS`，也不动四份 i18n 的 `errors` / `apiErrors`。

| 场景 | 错误码 | HTTP |
|---|---|---|
| 非授权用户读 `GET /api/providers`、`GET /api/voice/providers` | `FORBIDDEN`（`require_permission` 既有行为） | 403 |
| fetch-models 的 `provider_id` 不存在 | `NOT_FOUND` | 404 |
| fetch-models 的 `provider_id` 与不同的 `base_url` 同用、且无新密钥 | 不抛错，返回 `{"ok": false, "error": "api_key is required"}`（沿用该接口既有的 `ok:false` 约定与文本） | 200 |
| 非管理员授予 admin、以管理员为目标 | `FORBIDDEN` | 403 |
| stdio 保存或探测 | `CONNECTOR_KIND_UNSUPPORTED`，`details={"transport": "stdio", "server": <name>}` | 400 |
| 非管理员设置 `shared: true` | `FORBIDDEN` | 403 |
| 非管理员调 4 个 ACP 路由 | `FORBIDDEN`（`require_admin` 既有行为） | 403 |
| `resume-wizard` 无有效凭据 | `SETUP_TOKEN_INVALID`（`_extract_bearer` / `_authorize_setup_mid_wizard` 既有行为） | 401 |
| 安装已完成后访问令牌阶段接口 | `SETUP_REQUIRED`，显式 `status=410`（与 `_enforce_wizard_token_phase` 基线写法一致） | 410 |

`OctopError` 的 `message` 仍按基线约定写英文开发者信息；用户看到的是 dashboard `apiErrors.<CODE>` 的本地化文案。

## 安全考虑

- **脱敏的边界：** 本 spec 只保证 HTTP 响应不含凭据。库内仍是明文，拿到数据库或备份文件即可读到，这由 `w3-05` 解决，交付说明必须写明。
- **密钥跟随主机：** fetch-models 不允许把库内密钥发往与库内不同的 `base_url`。持 `providers` 权限的人仍可以"PATCH 改 base_url 后调 `/{id}/test`"，这是基线就有、且会留下持久改动的管理能力，本 spec 不改变它；是否需要把改 base_url 与重输密钥绑定，交给 `w3-05` 在落库契约里决定。
- **角色判定暂以 `admin` 为界：** `w3-03` 会让管理员退化为带显式权限键的角色，届时 `_assert_may_assign_role` / `_assert_may_target` 要改为基于角色实体的判定（例如"不能授予或操作比自己权限更高的角色"）。
- **运行时 fail-closed：** stdio 与非管理员 runner 的判定都放在运行时装配点，升级前已落库的载荷不会因为只挡住 HTTP 入口而继续可用。
- **审计不可信的问题仍在：** `audit_log` 是普通表，管理员可删改，防篡改由 `p2-03` 负责。本 spec 只补"有没有记"。
- **setup 鉴权实现约束：** `resume-wizard` 必须用手写 `Header` 加 `_authorize_setup_mid_wizard`，不能"简化"成 `Depends(require_admin())`，原因写进 docstring 与 PR 说明。
- **存量共享清理的副作用：** 非管理员此前共享给别人的 server 会被静默取消共享，别人的 agent 将看不到这些工具。这是修复的目的，必须写进 `CHANGELOG-intranet.md`。

## 测试策略

所有新增用例都放进 fork 自有的新文件，避免与上游测试文件冲突；唯一必须修改的上游用例是把漏洞钉成预期行为的 `test_resume_wizard_after_admin_created`。集成用例使用 `w0-03` 交付的 `tests/support/auth.py` 基线（`bootstrap_admin`、`create_user`、`create_agent`、`auth_header`）。

| 类别 | 文件 | 覆盖 | 本地命令 |
|---|---|---|---|
| 单测 | `tests/unit/test_voice_credentials.py`（新增） | 敏感键判定、脱敏、合并（缺失与空串沿用库内值、非敏感项以请求为准） | `uv run pytest tests/unit/test_voice_credentials.py -q` |
| 单测 | `tests/unit/connectors/test_custom_mcp_gate.py`（新增） | `reject_stdio_spec` 对 stdio 抛错、对 `streamable_http` / `http` 放行；`drop_non_http_configs`；`unshare_non_admin_custom_servers` 只取消非管理员的共享、幂等；库内有 stdio 时 `custom_harness_configs` 不含它（自有与共享两分支） | `uv run pytest tests/unit/connectors -q` |
| 单测 | `tests/unit/agents/test_acp_runtime_runners.py`（新增） | 管理员返回 `load_runners` 结果；非管理员与不存在的用户只返回内置默认、且 settings 中无迁移写入；`user_id=None` 返回 `{}` | `uv run pytest tests/unit/agents/test_acp_runtime_runners.py tests/unit/agents/test_acp_settings.py -q` |
| 单测 | `tests/unit/db/test_fork_purge_acp_runners.py`（新增） | 先把 `w0-01` 的 `octop.infra.db.fork_migrate._FORK_MIGRATIONS_DIR` 指向空目录跑 `run_migrations`，写入 1 个管理员与 1 个普通用户及各自的 `acp_runners:user:<id>`，恢复真实目录后调 `run_fork_migrations(db)`，断言只剩管理员的行；再调一次无变化 | `uv run pytest tests/unit/db/test_fork_purge_acp_runners.py -q` |
| 单测 | `tests/unit/infra/setup/test_completion.py`（新增） | 读写清除；回填的四种判据与"向导中途不回填" | `uv run pytest tests/unit/infra/setup/test_completion.py -q` |
| 集成 | `tests/integration/test_provider_secret_redaction.py`（新增） | 需求 1.1-1.3、2.1-2.3：admin 与持 `providers` 键的用户读两个列表不含 `api_key`、含 `has_api_key` / `local_runtime`；仅持 `channels` 的用户 403；fetch-models 的 `provider_id` 三种分支（mock `octop.api.routers.providers.fetch_openai_compatible_models`，断言 `api_key` 实参与调用次数） | `uv run pytest tests/integration/test_provider_secret_redaction.py -q` |
| 集成 | `tests/integration/test_voice_api.py`（新增，基线不存在该文件） | 需求 3.1-3.3：两个列表脱敏、`has_secret_key`、非 `voice` 用户 403、PATCH 合并后库内值不变 | `uv run pytest tests/integration/test_voice_api.py -q` |
| 集成 | `tests/integration/test_users_privilege_guard.py`（新增） | 需求 4.1-4.4：建 `permissions=["users"]` 的 carol，逐条断言 403 与 200 | `uv run pytest tests/integration/test_users_privilege_guard.py tests/integration/test_users_api.py -q` |
| 集成 | `tests/integration/test_custom_mcp_hotfix.py`（新增） | 需求 5.1-5.2、6.1-6.3：PUT / test / `connector-instances/{id}/test` 的 stdio 400 且 `mcp.client.stdio.stdio_client` 未被调用（monkeypatch 为会报错的替身）；shared 403 与管理员 200；审计经 `GET /api/admin/audit-log?action=…` 可查；存量共享：用 `ConnectorService.put_custom_servers` 给普通用户种入 `shared: true`，在同一 `tmp_octop_home` 上再进入一次 `octop_client` 后断言已取消共享 | `uv run pytest tests/integration/test_custom_mcp_hotfix.py tests/integration/test_connectors_api.py -q` |
| 集成 | `tests/integration/test_acp_admin_only.py`（新增） | 需求 7.1-7.2：普通用户用 `create_agent` 建自己的 agent，4 个路由 403、`GET /acp` 与 `PUT /acp/tool` 200 | `uv run pytest tests/integration/test_acp_admin_only.py tests/integration/test_acp_api.py -q` |
| 集成 | `tests/integration/test_setup_completion.py`（新增）；`tests/integration/test_setup_wizard.py::test_resume_wizard_after_admin_created`（修改：请求加 `initial-admin` 返回的 `access_token`） | 需求 8.1-8.6。start 路径：第一次 `octop_client` 走完 `bootstrap_admin` 后删除标记模拟旧库，第二次 `octop_client`（此时库文件已存在，走 `start()` 常规路径）后 `resume-wizard` 返回 410。bind 路径：`octop_client(home, bind_database=False)` 让 `start()` 延迟建库，再用 `SqlitePool` + `run_migrations` 在 `resolve_sqlite_db_path` 处建库、经 `UserRepo.create` 写 1 个管理员、经 `SettingsRepo.set_active_model` 写模型，然后 `await ensure_control_plane_bound(srv)`，断言 `resume-wizard` 返回 410 | `uv run pytest tests/integration/test_setup_completion.py tests/integration/test_setup_wizard.py tests/integration/test_setup_bootstrap.py tests/integration/test_setup_database.py -q` |
| PG | `tests/integration/test_postgresql_fork_purge_acp_runners.py`（新增，`@requires_postgresql` + `@pytest.mark.postgresql`，照抄 `_reset_public_schema`） | 需求 7.4 的 PostgreSQL 版 | `OCTOP_TEST_DATABASE_URL=postgresql://… make test-postgresql` |
| 前端 | `dashboard/src/pages/Settings/Models/presetUtils.test.ts`（新增） | `local_runtime` 为 `"onnx"` / `"ollama"` / `null` 时三个 `is*ProviderRow` 的结果，以及按名称与 base_url 的兜底 | `cd dashboard && npm run test -- src/pages/Settings/Models/presetUtils.test.ts` |
| 前端 | 类型与 lint | 全部 dashboard 改动 | `cd dashboard && npx tsc -b && npm run lint`，或 `make check-frontend` |
| 静态 | 需求 1.4、8.7、9.2 | `rg` / `git diff --stat` | 见 tasks.md |
| 手工 | 需求 2.4、3.4、4.6 | 在本地 `octop run` 的 dashboard 上逐项点验 | 见 tasks.md 任务 4、5、6 |

回归必须零修改通过：`tests/integration/test_users_api.py`、`test_providers_api.py`、`test_admin_providers.py`、`test_provider_fetch_models.py`、`test_provider_test_draft.py`、`test_provider_test_endpoint.py`、`test_connectors_api.py`、`test_acp_api.py`，`tests/unit/connectors/test_custom_mcp.py`、`tests/unit/agents/test_mcp_tool_cache.py`、`tests/unit/agents/test_acp_settings.py`。

## 与其他 spec 的交接

**依赖（均已合入）：**

- `w0-01-fork-migration-namespace`：`forkNNN_` 命名、`run_fork_migrations` 与测试钩子 `_FORK_MIGRATIONS_DIR`。
- `w0-02-ci-gates`：CI 的 frontend job 让 `presetUtils.test.ts` 真正执行；postgres job 执行 PG 用例。
- `w0-03-test-auth-baseline`：`bootstrap_admin` 在 `finish` 后以管理员身份 PATCH 自己的权限键，不受本 spec 的 `_assert_may_target` 影响（操作者是管理员）；本 spec 在 `finish` 后写入 `setup.completed`，`w0-03` 的夹具在 `finish` 之后不再调用任何令牌阶段接口。
- `w0-04-fork-isolation-points`：dashboard overlay、`CHANGELOG-intranet.md`、`docs/api-intranet.md`。

**交付给：**

- `w1-02-capability-trim`：删除 ACP 时，一并删除本 spec 加在 `acp.py` 的依赖改动、`acp_settings.py::runtime_acp_runners`、`manager.py` 的那一行调用与导入名，以及 `tests/integration/test_acp_admin_only.py`、`tests/unit/agents/test_acp_runtime_runners.py`；fork 迁移文件不可改也不删，settings 中管理员的 `acp_runners:user:*` 残值由 `w1-02` 自行决定清理。**`w1-02` 必须在任何行内部署之前合入**，否则 ACP 仍以"仅管理员可配"的形态存在。
- `w3-06-agent-execution-hardening`：移除 stdio 时删除 `custom_mcp_gate.py` 中的 `reject_stdio_*`，保留 `drop_non_http_configs` 的运行时兜底或改为在 `normalize_server_spec` 中不再接受 stdio；前端 stdio 表单与"添加 Stdio Server"按钮由它移除。
- `w3-03-authorization-foundation`：`users.py` 的两个 `_assert_*` 要改为基于角色实体的判定；自定义 MCP 路由是否要求 `connectors` 权限键、非自定义连接器的 `shared` 是否也收归管理员，由它统一决定。
- `w3-04-session-and-password`：消费 `octop.infra.setup.completion.is_setup_completed`，不自建标记。
- `w3-05-credential-encryption`：在本 spec 的响应契约（无 `api_key`、有 `has_api_key` / `local_runtime` / `has_secret_key`）下做落库加密；`presetUtils` 已不再依赖密钥值。
- `p2-06-intranet-integration`：在同一契约下为 providers 响应加字段，敏感字段一律以 `has_*` 形式输出。
- `w3-02-audit-baseline`：本 spec 新增的两个 action（`connector.custom_mcp.patch`、`connector.custom_mcp.probe`）按 `w3-02` 冻结的字段集迁移；供应商与用户写操作的审计由 `w3-02` 补。
- `w1-05-saas-decoupling`：删除腾讯等在线语音时无需改 `infra/voice/credentials.py`；`Settings/Voice/index.tsx` 中腾讯分支的改动随该分支一起删除。

**看似相关但不归本 spec：**

- `docs/api.md` 的过期记录（≈L77、≈L108-114、≈L227-234、≈L330-337、≈L382-384 的 Auth 列与不存在的 `/providers` 写路由）：fork 不改该文件，差异写进 `docs/api-intranet.md`。
- `dashboard/src/pages/Settings/octop/Providers.tsx` 死代码与 `dashboard/src/api/types/provider.ts` 中无人使用的 `current_api_key` 字段：`w1-04` 决定去留。
- `ProviderConfigModal` / `ModelListEditor` 的 `apiPrefix` 默认值 `"/providers"` 指向不存在的路由：所有调用点都显式传了 `/admin/providers`，本 spec 不动。

## 风险与回滚

| 风险 | 表现 | 缓解 |
|---|---|---|
| 外部脚本依赖 `GET /api/providers` 的 `api_key` 或匿名 `resume-wizard` | 升级后拿不到密钥或 401 | 这正是修复目标；写进 `CHANGELOG-intranet.md`「安全」小节与 `docs/api-intranet.md` |
| 用户已有 stdio 自定义 server | 该用户整份文档 PUT 返回 400，直到删掉 stdio 项；stdio 工具在 agent 中消失 | 错误信息带 `server` 名；可经 `DELETE /api/connector-instances/{id}` 删单个 server；写进变更记录 |
| 非管理员共享出去的 server 被取消共享 | 其他用户的 agent 少了这些工具 | 管理员可重新以自己的身份共享；写进变更记录 |
| 非管理员拥有的 agent 不再使用自定义 ACP runner | ACP 工具只剩内置运行器 | ACP 在 `w1-02` 整体删除；管理员拥有的 agent 不受影响 |
| 回填把单用户、已配模型、故意保留向导的实例关掉 | `resume-wizard` 永久 410 | 向导本就应在完成后关闭；如确需重开，可删除 settings 键 `setup.completed`（运维手册一句话） |
| 编辑语音供应商时"改了配置、没改凭据"却以为凭据也更新了 | 探测走库内配置 | 占位文案明确"留空保持原值"；`w1-05` 之后只剩 OpenAI 兼容语音，场景收窄 |
| 与上游冲突 | `users.py` 的 `patch_user`、`UsersListPanel.tsx`、`ProviderConfigModal.tsx` 是上游活跃区 | 每个漏洞一个提交；判定抽成独立函数；新增测试全部放 fork 自有文件 |

**回滚：** 每个顶层任务独立提交，可以逐个 `git revert`。fork 迁移不可回退，但它只删除非管理员的 runner 覆盖，回滚代码后这些用户回到内置默认运行器，不影响启动。`setup.completed` 回滚后成为无人读取的孤儿键，无害。

## 待行方确认

- **D6（Agent 命令执行）：** 默认假设"保留但收紧"，本 spec 在过渡期对 stdio 自定义 MCP 一律拒绝、不设开关。若行方要求过渡期也保留 stdio，需另加一个 `config.py` 三触点的布尔开关（约 0.25 人日），默认关闭；若答复"不保留"，本 spec 无需调整。
- **D10（语音能力）：** 默认保留 OpenAI 兼容语音。若语音整体下线，`w1-05` 会删除语音路由，本 spec 的 #1b 仍应先行合入，以免在删除前继续泄露。
- **D12（RBAC 终局）：** 默认三员分立、admin 退化为带显式权限键的角色。本 spec 的 #2 以 `admin` 角色为界是过渡口径，由 `w3-03` 按终局改写。
