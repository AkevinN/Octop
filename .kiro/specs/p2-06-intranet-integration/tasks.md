# 实施计划：行内系统对接

> spec：`p2-06-intranet-integration` ｜ 波次：二期 ｜ 基线：`757fd12` ｜ 预估：34–40 人日
> 前置：`w0-01-fork-migration-namespace`、`w0-02-ci-gates`、`w0-04-fork-isolation-points`、`w0-05-ssrf-intranet-allowlist`、`w1-01-security-hotfix`、`w2-01-offline-build`、`w2-04-intranet-model-gateway`、`w3-03-authorization-foundation`、`w3-05-credential-encryption` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

每个顶层任务完成后可独立提交；提交前运行任务内验证命令。

- [ ] 1. 确认前置 spec 已合入并记录基线
  - 改动：核实 Wave 0–4 已合入；记录实际基线提交号；重新核实 design.md 里"实施时定位"锚点的真实行号。
  - 验证：`rg -n "class GatewayAdapter" src/octop/infra/connectors/gateway/registry.py`
  - _需求：全部_

- [ ] 2. 供应商 CA/代理：后端纯函数与出网点
  - 改动：新增 `providers/tls.py`（`parse_provider_tls`/`build_ssl_context`/`build_httpx_clients`）；改 `store.py::build_harness_configs` 与 `probe.py` 三处出网点；如需先补 `harness_agent.ProviderConfig` 的透传字段。
  - 验证：`uv run pytest tests/unit/providers/test_provider_tls.py -q`
  - _需求：1.1, 1.2, 1.3, 1.5_

- [ ] 3. 供应商 CA/代理：路由脱敏回传
  - 改动：`_row_to_dict` 按 `w1-01` 脱敏契约补 `extra_json`；`admin_fetch_provider_models` 与 test 路由传 TLS 给 probe 层。
  - 验证：`uv run pytest tests/unit/api -k providers -q`
  - _需求：1.4_

- [ ] 4. 供应商 CA/代理：dashboard 表单
  - 改动：三个供应商弹窗 + `useProviders.ts::ProviderRow` + `Settings/octop/Providers.tsx` 新增 CA/跳过校验/代理字段，与既有 `headers` 合并。
  - 验证：`cd dashboard && npx tsc -b`
  - _需求：1.4_

- [ ] 5. 行内 IM 通道：上游实现 + Octop 侧注册
  - 改动：确认 D13 结论；成立则在内部 fork 新增 `harness_gateway/channels/<bank_im>.py` 并在 `channels/__init__.py` 三处登记；不成立则改用既有 `mqtt` kind 桥接。
  - 验证：`uv run pytest tests/unit/gateway -k channel -q`
  - _需求：2.1, 2.4_

- [ ] 6. 行内 IM 通道：API、CLI、dashboard
  - 改动：`channels.py` 的 `ChannelKind` 随上游扩展；`cli/commands/channel.py` 的 `kinds` 加新项；`constants.ts` 的 `ChannelKey` 与四个穷尽 `Record` 各补一条；overlay 新增 `channels.label_<bank_im>`。
  - 验证：`uv run pytest tests/integration/test_channels_api.py -q && cd dashboard && npx tsc -b`
  - _需求：2.1, 2.2, 2.3_

- [ ] 7. 行内连接器：三个适配器与目录登记
  - 改动：新增 `gateway/adapters/{bank_oa,bank_kb,bank_ticket}.py`；`registry.py::_ADAPTERS` 登记；`catalog_intranet.py::_fork_entries()` 追加三条目录项；`builder.py` 的 `custom_fields` 分支产出 `internal_token`；补连接器图标。
  - 验证：`uv run pytest tests/unit/connectors/test_bank_adapters.py tests/integration/test_connectors_api.py -q`
  - _需求：3.1, 3.2, 3.3_

- [ ] 8. 多维配额：fork 迁移与数据层（测试先行）
  - 改动：新增 `forkNNN_usage_quotas.sql`+`.pg.sql`（`usage_quotas` 表 + `idx_usage_log_user_model` 索引，合入前定号）；新增 `UsageQuotaRepo`；`services.py` 三处接线。
  - 验证：`uv run pytest tests/unit/db/test_usage_quotas.py -q`
  - _需求：4.5_

- [ ] 9. 多维配额：判定模块与中间件
  - 改动：新增 `infra/users/quota.py::assert_quotas_available`（含 legacy 桥接）；补 `resolve_usage_window` 的 `week`/当期 `month`；`TokenQuotaMiddleware` 加 `wrap_model_call`/`awrap_model_call`；挂载点注入 repo 与时区。
  - 验证：`uv run pytest tests/unit/agents/test_token_quota_middleware.py -q`
  - _需求：4.1, 4.2, 4.3, 4.4, 4.6_

- [ ] 10. 多维配额：admin API 与 dashboard
  - 改动：`usage.py` 新增 `GET`/`PUT`/`DELETE /api/admin/usage/quotas`；`UsersListPanel.tsx` 扩展为多条规则表单；overlay 新增配额文案。
  - 验证：`uv run pytest tests/integration/test_usage_quotas_api.py -q && cd dashboard && npx tsc -b`
  - _需求：4.1, 4.2_

- [ ] 11. 银行场景专家模板
  - 改动：新增 3 套 `experts/library/<bank-expert-*>/`（manifest.json + SOUL.md，按需补 IDENTITY.md/USER.md/skills/）+ 3 张头像；`_FALLBACK_BUNDLED_AVATAR_IDS` 加新 id。
  - 验证：`uv run pytest tests/unit/agents/test_library_task_examples.py tests/unit/agents/test_expert_catalog.py -q`
  - _需求：5.1, 5.2_

- [ ] 12. 收尾：全绿与文档
  - 改动：更新 `CHANGELOG-intranet.md`（本 spec 五项能力）与 `docs/api-intranet.md`（新增路由、连接器 kind、配额端点）；巡检 `/api/docs` 新路由。
  - 验证：`make all && cd dashboard && npx tsc -b && npm run lint && npm run test && uv run pytest tests/unit/i18n -q`
  - _需求：全部_
