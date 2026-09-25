# 实施计划：五个现成漏洞热修

> spec：`w1-01-security-hotfix` ｜ 波次：Wave 1 ｜ 基线：`757fd12` ｜ 预估：7 人日
> 前置：`w0-01-fork-migration-namespace`、`w0-02-ci-gates`、`w0-03-test-auth-baseline`、`w0-04-fork-isolation-points` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

每个顶层任务完成后可独立提交；提交前运行任务内的验证命令。

约定：每个漏洞一个顶层任务、一个提交，便于上游同步时逐条重放或回退。新增测试一律放进 fork 自有的新文件；唯一允许修改的上游用例是任务 8.1 中的 `test_resume_wizard_after_admin_created`。括号里的人日是估算。

- [ ] 1. 确认前置 spec 已合入并记录基线（0.25 人日）
  - 改动：无代码改动。确认 `w0-01` 的 `src/octop/infra/db/fork_migrate.py`（`run_fork_migrations`、`_FORK_MIGRATIONS_DIR`）、`w0-02` 的 `make install-frontend` / `make check-frontend` / `make test-postgresql`、`w0-03` 的 `tests/support/auth.py` 新基线、`w0-04` 的 `dashboard/src/locales/intranet/{en,zh}.json`、`CHANGELOG-intranet.md`、`docs/api-intranet.md` 均已在当前分支；执行 `export W101_BASE=$(git rev-parse HEAD)`，把该值与下列命令中已有的失败用例（如 root 用户下 `tests/unit/infra/setup/test_service.py` 的环境性失败）记入 PR 描述。
  - 验证：`test -f src/octop/infra/db/fork_migrate.py && rg -n "def run_fork_migrations|_FORK_MIGRATIONS_DIR" src/octop/infra/db/fork_migrate.py && test -f dashboard/src/locales/intranet/en.json && test -f dashboard/src/locales/intranet/zh.json && test -f CHANGELOG-intranet.md && test -f docs/api-intranet.md && git rev-parse HEAD`
  - 验证：`make install-frontend && uv run pytest tests/integration/test_setup_wizard.py tests/integration/test_users_api.py tests/integration/test_providers_api.py tests/integration/test_acp_api.py tests/integration/test_connectors_api.py tests/unit/connectors tests/unit/agents/test_acp_settings.py tests/unit/i18n -q`
  - _需求：9.1, 9.2_

- [ ] 2. 大模型供应商凭据脱敏与 fetch-models 取库内密钥（后端，0.75 人日）
  - [ ] 2.1 先写会失败的集成用例
    - 改动：新增 `tests/integration/test_provider_secret_redaction.py`。用例：管理员与"只持 `providers` 键"的用户分别读 `GET /api/providers` 与 `GET /api/admin/providers`，断言每个元素 `"api_key" not in p`、`p["has_api_key"] is True`、`"local_runtime" in p`；以 `api_key="onnx"` 建的供应商 `local_runtime == "onnx"`；只持 `channels` 键的用户读 `GET /api/providers` 得 403 且 `error.code == "FORBIDDEN"`；`POST` / `PATCH /api/admin/providers` 的返回体不含 `api_key`，而 `srv.services.provider_repo.get(id).api_key` 等于提交值；fetch-models 三个分支（mock `octop.api.routers.providers.fetch_openai_compatible_models`）：只带 `provider_id` 时实参 `api_key` 等于库内值；带 `provider_id` 与不同的 `base_url` 时返回 `ok: false` 且 mock 未被调用；`provider_id` 不存在时 404 `NOT_FOUND`。
    - 验证：`uv run pytest tests/integration/test_provider_secret_redaction.py -q`（此时应失败）
    - _需求：1.1, 1.2, 1.3, 2.1, 2.2, 2.3_
  - [ ] 2.2 修改 providers 路由
    - 改动：`src/octop/api/routers/providers.py` 的 `_row_to_dict` —— 删除 `api_key`，新增 `has_api_key` 与 `local_runtime`；新增私有函数 `_local_runtime`，调用 `octop.infra.agents.providers.model_flags` 的 `is_onnx_local_provider` / `is_ollama_local_provider`。
    - 改动：同文件 `list_providers` —— 依赖改为 `Depends(require_permission("providers"))`，docstring 改为"requires the providers permission"。
    - 改动：同文件 `ProviderFetchModelsBody` 与 `admin_fetch_provider_models` —— 新增 `provider_id: int | None = None`；`api_key` 为空且带 `provider_id` 时按设计文档"方案 #1 第 3 点"取库内密钥，并执行"密钥跟随主机"检查（`base_url` 去首尾空白与末尾 `/` 后比较）。
    - 验证：`uv run pytest tests/integration/test_provider_secret_redaction.py tests/integration/test_providers_api.py tests/integration/test_admin_providers.py tests/integration/test_provider_fetch_models.py tests/integration/test_provider_test_draft.py tests/integration/test_provider_test_endpoint.py tests/integration/test_boundary_authz.py tests/unit/api/test_acl_gate_coverage.py -q`
    - 验证：`! rg -n '"api_key": r\.api_key' src/octop/api/routers/providers.py`
    - _需求：1.1, 1.2, 1.3, 2.1, 2.2, 2.3, 2.5_

- [ ] 3. 模型设置页同批改造（前端，0.75 人日）
  - [ ] 3.1 先写会失败的 vitest 用例并改共享类型
    - 改动：新增 `dashboard/src/pages/Settings/Models/presetUtils.test.ts`，覆盖 `local_runtime` 为 `"onnx"`、`"ollama"`、`null` 时 `isOnnxProviderRow`、`isOllamaProviderRow`、`isLocalProviderRow` 的结果，以及 `local_runtime` 为 `null` 时按名称（`"onnx (local)"`、`"ollama"`）与 base_url（含 `11434`）的兜底。
    - 改动：`dashboard/src/pages/Settings/Models/useProviders.ts` 的 `ProviderRow` —— `api_key` 换成 `has_api_key: boolean` 与 `local_runtime: "onnx" | "ollama" | null`。
    - 改动：`dashboard/src/pages/Settings/Models/presetUtils.ts` 的 `localPresetApiKey` —— 改读 `local_runtime`；三个 `is*ProviderRow` 的参数类型把 `api_key?` 换成 `local_runtime?`。
    - 验证：`cd dashboard && npm run test -- src/pages/Settings/Models/presetUtils.test.ts`
    - _需求：1.5_
  - [ ] 3.2 改组件与请求封装
    - 改动：`components/cards/ProviderCard.tsx` —— `hasApiKey` 改读 `provider.has_api_key`；`maskedKey` 在 `has_api_key` 为真时返回固定掩码 `••••••••`。
    - 改动：`components/modals/ProviderConfigModal.tsx` —— `hasApiKey`（≈L95）改读 `provider.has_api_key`；测试流程（≈L768-799）与拉取模型流程（≈L867-880）按设计文档"方案 #1 第 4 点"改写：Base URL 变了而没有新密钥时 `message.warning(t("models.pleaseEnterApiKey"))` 并返回；有新密钥只传 `draftApiKey`；没有新密钥时测试走 `${apiPrefix}/${provider.id}/test`，拉取模型传 `provider_id: provider.id`。
    - 改动：`components/modals/ModelListEditor.tsx`（≈L207、≈L367）与 `components/sections/ActiveModelPool.tsx`（≈L60）—— 改读 `has_api_key`。
    - 改动：`providerApi.ts` 的 `FetchProviderModelsParams` 与 `fetchProviderModels` —— 接口加 `provider_id?: number`，并写进 `JSON.stringify` 的请求体。
    - 验证：`cd dashboard && npx tsc -b && npm run lint && npm run test -- src/pages/Settings/Models/presetUtils.test.ts`
    - 验证：`! rg -n '(provider|p)\.api_key' dashboard/src/pages/Settings/Models`
    - 验证（手工）：`uv run octop run` 后以管理员登录「模型」页：已配置密钥的卡片显示"已授权"、不显示任何密钥字符；不重输密钥点「测试」与「拉取模型」均成功；改 Base URL 不输密钥时提示"请输入 API Key"；本地 Ollama / ONNX 卡片仍显示本地服务控件。
    - _需求：1.5, 2.4_

- [ ] 4. 语音供应商凭据脱敏（后端 + 前端，1.0 人日）
  - [ ] 4.1 先写会失败的单测与集成用例
    - 改动：新增 `tests/unit/test_voice_credentials.py`（敏感键判定、`redact_voice_extra` 的返回值、`merge_voice_extra_json` 对缺失与空串沿用库内值、非敏感项以请求为准）。
    - 改动：新增 `tests/integration/test_voice_api.py`：以管理员建 `kind="tencent"` 的供应商（`api_key="sid:sk"`，`extra_json` 含 `secret_id`、`secret_key`、`region`），断言 `GET /api/voice/providers` 与 `GET /api/admin/voice/providers` 的元素无 `api_key`、`has_api_key is True`、`has_secret_key is True`、`extra == {"region": "ap-guangzhou"}`；只持 `channels` 键的用户读 `GET /api/voice/providers` 得 403；`PATCH` 只带 `{"extra_json": "{\"region\": \"ap-guangzhou\"}"}` 与 `{"note": "x"}` 后，`srv.services.voice_provider_repo.get(id)` 的 `api_key` 与 `get_extra()` 中的 `secret_id` / `secret_key` 不变。
    - 验证：`uv run pytest tests/unit/test_voice_credentials.py tests/integration/test_voice_api.py -q`（此时应失败）
    - _需求：3.1, 3.2, 3.3_
  - [ ] 4.2 后端实现
    - 改动：新增 `src/octop/infra/voice/credentials.py`，实现 `is_sensitive_extra_key`、`redact_voice_extra`、`merge_voice_extra_json`（签名见设计文档）。
    - 改动：`src/octop/api/routers/voice.py` 的 `_row_to_dict` —— 删除 `api_key`，新增 `has_api_key`、`has_secret_key`，`extra` 用脱敏副本；`list_voice_providers` —— 依赖改为 `Depends(require_permission("voice"))`；`admin_patch_voice_provider` —— `body.extra_json` 不为 `None` 时先与 `row.extra_json` 合并。
    - 验证：`uv run pytest tests/unit/test_voice_credentials.py tests/integration/test_voice_api.py tests/integration/test_voice_probe_http.py tests/unit/test_voice_manager.py tests/unit/test_voice_probe.py tests/unit/api/test_acl_gate_coverage.py -q`
    - 验证：`! rg -n '"api_key": r\.api_key' src/octop/api/routers/`
    - _需求：1.4, 3.1, 3.2, 3.3_
  - [ ] 4.3 语音设置页
    - 改动：`dashboard/src/api/modules/voice.ts` 的 `VoiceProviderRow` —— `api_key` 换成 `has_api_key: boolean` 与 `has_secret_key: boolean`，注释说明 `extra` 已脱敏。
    - 改动：`dashboard/src/pages/Settings/Voice/index.tsx` —— `openConfigure` 不预填凭据；已有凭据时输入框占位用 `t("models.apiKeyPlaceholderKeep")`；`validateCredentials` 在"已有凭据且未重输"时放行；`buildProviderPayload` 未重输时下发 `api_key: null`，腾讯分支的 `extra` 省略空的 `secret_id` / `secret_key`；`handleProbe` 在"已有凭据且未重输"时改调 `voiceApi.testProvider(existing.id, mode)`。
    - 验证：`cd dashboard && npx tsc -b && npm run lint`
    - 验证（手工）：`uv run octop run` 后打开「模型 → 语音」，编辑一个已配置的供应商：凭据框为空并显示"留空保持原 key"；不重输凭据点「测试」与「保存」均成功，保存后再次测试仍成功。
    - _需求：3.4_

- [ ] 5. 持 users 权限的非管理员不能越权到管理员（后端 + 前端，1.0 人日）
  - [ ] 5.1 先写会失败的集成用例
    - 改动：新增 `tests/integration/test_users_privilege_guard.py`：管理员经 `create_user(..., permissions=["users"])` 建 carol；断言 carol `POST /api/users` 带 `role="admin"` 得 403 且 `GET /api/users` 的数量不变；carol `PATCH /api/users/{carol_id}` 带 `role="admin"` 得 403，随后 carol 的 `GET /api/auth/me` 仍为 `role == "user"`；carol 对管理员账号的 `PATCH`（`{"disabled": true}`、`{"display_name": "x"}`）、`POST reset-password`、`POST unlock-login`、`DELETE` 全部 403，管理员仍能用原口令登录；carol 编辑另一个普通用户并带 `role: "user"` 与新显示名得 200。
    - 验证：`uv run pytest tests/integration/test_users_privilege_guard.py -q`（此时应失败）
    - _需求：4.1, 4.2, 4.3, 4.4_
  - [ ] 5.2 后端实现
    - 改动：`src/octop/api/routers/users.py` —— 在 `_assert_can_assign` 之后新增 `_assert_may_assign_role` 与 `_assert_may_target`；`create_user` 在 `Role(body.role)` 之前调前者；`patch_user` 取到 `row` 后调后者，`body.role is not None` 时再调前者；`unlock_user_login`、`reset_password`、`delete_user` 取到 `row` 后调后者。保留原有的"不能降级自己""不能删除自己""不能移除最后一个用户管理者"判断。
    - 验证：`uv run pytest tests/integration/test_users_privilege_guard.py tests/integration/test_users_api.py tests/integration/test_personas_admin_api.py tests/unit/users -q`
    - _需求：4.1, 4.2, 4.3, 4.4, 4.5_
  - [ ] 5.3 用户管理页
    - 改动：`dashboard/src/locales/intranet/en.json` 与 `zh.json` —— 新增 `adminUsers.adminTargetAdminOnly`（en："Only administrators can manage administrator accounts."；zh："只有管理员可以管理管理员账号。"）。
    - 改动：`dashboard/src/pages/Admin/Users/UsersListPanel.tsx` —— 用 `useUserRole()` 得到 `actorIsAdmin`；`createRoleOptions` 在非管理员时去掉 `admin` 项；新增 `guardAdminTarget(row)`，在 `togglePatch`、`onDelete`、`onUnlockLogin`、`onEditSubmit`、`onResetSubmit` 开头各调用一次；文件头注释（≈L10）改为"require the `users` permission; admin accounts are admin-only"。
    - 验证：`cd dashboard && npx tsc -b && npm run lint && npm run test`
    - 验证：`uv run pytest tests/unit/i18n -q`
    - 验证（手工）：`uv run octop run`，以持 `users` 权限的普通用户登录「用户」页：新建与编辑弹窗的角色下拉里没有"管理员"；对管理员行点停用、编辑、改密、解锁、删除都只弹出"只有管理员可以管理管理员账号"，不发请求。
    - _需求：4.6, 9.3_

- [ ] 6. 自定义 MCP 临时闸门（0.75 人日，与任务 7 合计约 1 人日）
  - [ ] 6.1 先写会失败的单测与集成用例
    - 改动：新增 `tests/unit/connectors/test_custom_mcp_gate.py`：`reject_stdio_spec` 对 `transport` 为 `"stdio"`、`" stdio "` 抛 `OctopError` 且 `code is ErrorCode.CONNECTOR_KIND_UNSUPPORTED`，对 `streamable_http`、`http` 放行；`drop_non_http_configs` 只保留 `streamable_http`；用 `ConnectorService.put_custom_servers` 给用户种入 stdio server 后，`custom_harness_configs` 不含它（本人与共享两个分支）；`unshare_non_admin_custom_servers` 只取消非管理员的 `shared`、管理员的保留、第二次调用返回空列表。
    - 改动：新增 `tests/integration/test_custom_mcp_hotfix.py`：把 `mcp.client.stdio.stdio_client` monkeypatch 为一被调用就失败的替身；管理员与普通用户 `PUT /api/connectors/custom-mcp` 带 `{"transport": "stdio", "command": "/bin/sh", "args": ["-c", "id"]}` 均 400、`error.code == "CONNECTOR_KIND_UNSUPPORTED"`、`GET` 结果不变；`POST /api/connectors/custom-mcp/test` 带同一内联 spec 得 400；经 `ConnectorService.put_custom_servers` 直接种入 stdio 项后，按 `name` 探测与经 `POST /api/connector-instances/{id}/test` 探测均 400；普通用户 PUT 带 `shared: true`、PATCH 带 `{"shared": true}` 均 403，管理员 200；PATCH 与探测（含被拒的一次）后 `GET /api/admin/audit-log?action=connector.custom_mcp.patch` 与 `?action=connector.custom_mcp.probe` 各有记录；给普通用户种入 `shared: true` 的 streamable_http server，在同一 `tmp_octop_home` 上再进入一次 `octop_client` 后，另一用户的 `custom_harness_configs` 不含它。
    - 验证：`uv run pytest tests/unit/connectors/test_custom_mcp_gate.py tests/integration/test_custom_mcp_hotfix.py -q`（此时应失败）
    - _需求：5.1, 5.2, 5.3, 6.1, 6.2, 6.3_
  - [ ] 6.2 闸门模块与运行时过滤
    - 改动：新增 `src/octop/infra/connectors/custom_mcp_gate.py`，实现 `reject_stdio_spec`、`reject_stdio_servers`、`drop_non_http_configs`、`unshare_non_admin_custom_servers`（`ConnectorService` 在函数内导入）。模块 docstring 写明"过渡实现：stdio 由 w3-06 移除"。
    - 改动：`src/octop/infra/connectors/service.py` 的 `custom_harness_configs` —— 返回前经 `drop_non_http_configs`。
    - 验证：`uv run pytest tests/unit/connectors -q`
    - _需求：5.3, 5.4_
  - [ ] 6.3 路由接入与启动清理
    - 改动：`src/octop/api/routers/connectors.py` 的 `put_custom_mcp` —— 调 `svc.put_custom_servers` 前先 `reject_stdio_servers(body.servers)`，任一项 `shared is True` 且 `not user.is_admin` 时抛 `FORBIDDEN`；`patch_custom_mcp_server` —— `body.shared is True` 且非管理员时抛 `FORBIDDEN`，成功后写 `connector.custom_mcp.patch` 审计；`test_custom_mcp` —— 组装好 `spec` 后先写 `connector.custom_mcp.probe` 审计，再 `reject_stdio_spec`，再探测；`test_instance` 的自定义分支同样先审计、再闸门、再探测。
    - 改动：`src/octop/infra/server.py` 的 `start()`（≈L328 `_ensure_jwt_secret` 之后、≈L329 `_boot_runtime` 之前）与 `bind_control_plane()`（≈L355 之后、≈L356 之前）—— 各加一行 `unshare_non_admin_custom_servers(self.services)`，用函数内延迟导入。
    - 验证：`uv run pytest tests/unit/connectors tests/unit/agents/test_mcp_tool_cache.py tests/integration/test_custom_mcp_hotfix.py tests/integration/test_connectors_api.py tests/unit/api/test_acl_gate_coverage.py -q`
    - 验证：`git diff --exit-code "$W101_BASE" -- tests/unit/connectors/test_custom_mcp.py tests/unit/agents/test_mcp_tool_cache.py tests/integration/test_connectors_api.py`
    - _需求：5.1, 5.2, 5.4, 6.1, 6.2, 6.3, 6.4_

- [ ] 7. ACP 运行器临时闸门（0.35 人日）
  - [ ] 7.1 先写会失败的用例
    - 改动：新增 `tests/integration/test_acp_admin_only.py`：普通用户经 `create_user` 与 `create_agent` 拿到自己的 agent，`GET` / `PUT` / `DELETE /api/agents/{aid}/acp/opencode` 与 `PUT /api/agents/{aid}/acp` 均 403，且事后管理员 `GET /api/acp` 结果不变；同一用户 `GET /api/agents/{aid}/acp` 与 `PUT /api/agents/{aid}/acp/tool` 均 200。
    - 改动：新增 `tests/unit/agents/test_acp_runtime_runners.py`：用 `ACPSettingsStore` 与真实 `UserRepo`（SQLite 临时库）；管理员返回 `store.load_runners` 的结果（含自定义 runner）；普通用户即使 settings 中有自定义 runner、其 agent `config_json` 中有遗留 `acp.runners`，也只返回内置默认，且 settings 中未新增该用户的键；`user_id=None` 返回 `{}`。
    - 改动：新增 `tests/unit/db/test_fork_purge_acp_runners.py`（SQLite）与 `tests/integration/test_postgresql_fork_purge_acp_runners.py`（`@requires_postgresql` + `@pytest.mark.postgresql`，照抄 `_reset_public_schema`）：先把 `octop.infra.db.fork_migrate._FORK_MIGRATIONS_DIR` 指向空目录跑 `run_migrations`，写入管理员与普通用户及各自的 `acp_runners:user:<id>`，恢复真实目录后调 `run_fork_migrations(db)`，断言只剩管理员的行；再调一次无变化。
    - 验证：`uv run pytest tests/integration/test_acp_admin_only.py tests/unit/agents/test_acp_runtime_runners.py tests/unit/db/test_fork_purge_acp_runners.py -q`（此时应失败）
    - _需求：7.1, 7.2, 7.3, 7.4_
  - [ ] 7.2 路由、运行时与迁移
    - 改动：`src/octop/api/routers/acp.py` 的 `get_acp_runner`、`put_acp_runner`、`delete_acp_runner`、`put_acp_config` —— 依赖改为 `Depends(require_admin())`；`get_acp_config` 与 `put_acp_tool_toggle` 不动。
    - 改动：`src/octop/infra/agents/acp_settings.py` —— 新增 `runtime_acp_runners(store, user_repo, user_id)`，docstring 写明"过渡实现：ACP 由 w1-02 删除"。
    - 改动：`src/octop/infra/agents/manager.py` —— ≈L23 的 `from octop.infra.agents.acp_settings import ACPSettingsStore` 加上 `runtime_acp_runners`；≈L2843-2845 的三行赋值换成 `runners_dict = runtime_acp_runners(self._acp_settings, self._repos.user_repo, acp_user_id)`。
    - 改动：新增 `src/octop/infra/db/migrations/forkNNN_purge_non_admin_acp_runners.sql` 与同名 `.pg.sql`（内容见设计文档"数据模型"），合入前按 fork 主干顺序定号。
    - 验证：`uv run pytest tests/integration/test_acp_admin_only.py tests/integration/test_acp_api.py tests/unit/agents/test_acp_runtime_runners.py tests/unit/agents/test_acp_settings.py tests/unit/agents/test_agent_manager.py tests/unit/db -q`
    - 验证：`OCTOP_TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:15432/octop_test make test-postgresql`（需本地 PG；`w0-02` 的 CI postgres job 执行同一用例）
    - 验证：`git diff --exit-code "$W101_BASE" -- tests/integration/test_acp_api.py tests/unit/agents/test_acp_settings.py`
    - _需求：7.1, 7.2, 7.3, 7.4, 7.5_

- [ ] 8. 安装向导：resume-wizard 鉴权与持久关闭（1.0 人日）
  - [ ] 8.1 先写会失败的用例，并改掉把漏洞钉成预期的旧断言
    - 改动：新增 `tests/unit/infra/setup/test_completion.py`：`is_setup_completed` / `mark_setup_completed` / `clear_setup_completed` 往返；`backfill_setup_completed` 在"0 用户""1 用户无模型无 main"时不写，在"2 用户""1 用户 + active model""1 用户 + `main` agent"时写入，已有标记时返回 `False`。
    - 改动：新增 `tests/integration/test_setup_completion.py`：
      - 建好 initial-admin 后不带 Authorization 调 `POST /api/setup/resume-wizard` 得 401 且 `error.code == "SETUP_TOKEN_INVALID"`；带 `access_token` 或 wizard token 得 200；
      - 走完 `finish` 后 settings 有 `setup.completed`，随后带有效凭据调 `resume-wizard`、`finish`、`test-provider`、`validate-token` 全部 410；零用户时 `finish` 不写标记；
      - start 路径：第一次 `octop_client` 内走完 `bootstrap_admin`，删除 `setup.completed` 模拟旧库；在同一 `tmp_octop_home` 上第二次进入 `octop_client`（走 `start()` 常规路径）后 `resume-wizard` 返回 410；
      - bind 路径：`octop_client(home, bind_database=False)` 让 `start()` 延迟建库，再用 `SqlitePool` + `run_migrations` 在 `resolve_sqlite_db_path(...)` 处建库，经 `UserRepo.create(role="admin", ...)` 写 1 个管理员、经 `SettingsRepo.set_active_model` 写模型，然后 `await ensure_control_plane_bound(srv)`，断言 `resume-wizard` 返回 410；
      - 向导中途（1 个管理员、无模型、无 `main`）重启后，带管理员 JWT 调 `resume-wizard` 仍 200；
      - 零用户时手工写入 `setup.completed`，再走 verify-password → initial-admin → finish，`finish` 返回 200。
    - 改动：`tests/integration/test_setup_wizard.py` 的 `test_resume_wizard_after_admin_created` —— 保存 `initial-admin` 的响应，把 ≈L267 的请求改为带 `Authorization: Bearer <access_token>`，其余断言不变。
    - 验证：`uv run pytest tests/unit/infra/setup/test_completion.py tests/integration/test_setup_completion.py tests/integration/test_setup_wizard.py -q`（此时应失败）
    - _需求：8.1, 8.2, 8.3, 8.4, 8.5, 8.6_
  - [ ] 8.2 标记模块与 setup 路由
    - 改动：新增 `src/octop/infra/setup/completion.py`，实现 `SETUP_COMPLETED_KEY`、`is_setup_completed`、`mark_setup_completed`、`clear_setup_completed`、`backfill_setup_completed`（签名与判据见设计文档）。
    - 改动：`src/octop/api/routers/setup.py` 的 `_enforce_wizard_token_phase` —— 增加"用户数 ≥ 1、`server.services` 已就绪且 `is_setup_completed(...)`"时抛 `SETUP_REQUIRED`（`status=410`）；`resume_wizard` —— 增加 `authorization: str | None = Header(default=None)`，在 `require_database` 之后调 `_authorize_setup_mid_wizard(authorization, server)`，docstring 写明不能改为 `Depends(require_admin())` 的原因；`finish` —— 返回前在用户数 ≥ 1 时 `mark_setup_completed`；`initial_admin` —— 创建成功后 `clear_setup_completed`。
    - 验证：`uv run pytest tests/unit/infra/setup/test_completion.py tests/integration/test_setup_wizard.py tests/integration/test_setup_bootstrap.py tests/integration/test_setup_database.py tests/integration/test_auth_flow.py tests/integration/test_e2e_golden_path.py -q`
    - _需求：8.1, 8.2, 8.3, 8.6_
  - [ ] 8.3 两条启动路径回填
    - 改动：`src/octop/infra/server.py` 的 `start()` 与 `bind_control_plane()` —— 在任务 6.3 加入的那一行之前，各加一行 `backfill_setup_completed(self.services)`（函数内延迟导入）。
    - 验证：`uv run pytest tests/integration/test_setup_completion.py tests/integration/test_setup_wizard.py tests/unit/test_launch_deferred.py -q`
    - 验证：`test "$(rg -l 'setup\.completed' src/octop --glob '*.py')" = "src/octop/infra/setup/completion.py"`
    - _需求：8.4, 8.5, 8.7_

- [ ] 9. 收尾：全量门禁与变更记录（0.5 人日）
  - 改动：`CHANGELOG-intranet.md` 的 `## [Unreleased]` →「安全」小节，以 `w1-01-security-hotfix` 开头逐条记录：providers / voice 响应删除 `api_key`、新增 `has_api_key` / `local_runtime` / `has_secret_key`，语音 `extra` 去掉敏感项；两个列表接口改为需要 `providers` / `voice` 权限；fetch-models 新增 `provider_id` 且库内密钥只发往库内主机；非管理员不能授予 admin 或操作管理员账号；自定义 MCP 拒绝 stdio（含已存配置不再加载）、共享只限管理员、启动时收回非管理员的共享；ACP 4 个 agent 作用域路由只限管理员、非管理员不再加载自定义 runner、fork 迁移清理其存量；`resume-wizard` 需要凭据、安装完成后令牌阶段永久 410，存量实例启动时回填。每条附本地复现命令。
  - 改动：`docs/api-intranet.md` 第 3 节（fork 变更的端点：providers / voice 响应字段、fetch-models 请求体）与第 4 节（鉴权差异：`GET /api/providers`、`GET /api/voice/providers`、`/api/users` 写路由、`/api/connectors/custom-mcp*` 与 `/api/connector-instances/{id}/test`、4 个 ACP 路由、`/api/setup/resume-wizard` 与令牌阶段接口）；第 5 节写"本 spec 无新增错误码"。
  - 验证：`make all`
  - 验证：`cd dashboard && npx tsc -b && npm run lint && npm run test`
  - 验证：`uv run pytest tests/unit/i18n tests/unit/api/test_acl_gate_coverage.py tests/unit/test_fork_isolation_contract.py -q`
  - 验证：`test -z "$(git diff --stat "$W101_BASE" -- src/octop/infra/errors.py src/octop/config.py src/octop/infra/users/permissions.py src/octop/i18n/en.json src/octop/i18n/zh.json dashboard/src/locales/en.json dashboard/src/locales/zh.json CHANGELOG.md docs/api.md)"`
  - 验证：`! rg -n '"api_key": r\.api_key' src/octop/api/routers/`
  - 验证：`rg -n "w1-01-security-hotfix" CHANGELOG-intranet.md docs/api-intranet.md`
  - _需求：1.4, 9.1, 9.2, 9.3, 9.4_
