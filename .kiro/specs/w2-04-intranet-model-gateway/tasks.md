# 实施计划：行内大模型网关接入
> spec：`w2-04-intranet-model-gateway` ｜ 波次：Wave 2 ｜ 基线：`757fd12` ｜ 预估：4 人日
> 前置：`w0-02-ci-gates`、`w0-04-fork-isolation-points`、`w1-05-saas-decoupling`、`w2-01-offline-build` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

每个顶层任务完成后可独立提交；提交前运行任务内的验证命令。

- [ ] 1. 确认前置 spec 已合入并记录基线
  - 改动：无代码改动。确认 `src/octop/infra/agents/providers/provider_presets.json` 存在且 `load_provider_presets` 已按 `w1-05` 显式读取它；确认 `dashboard/src/locales/intranet/{en,zh}.json`、`CHANGELOG-intranet.md`、`docs/intranet/` 存在（`w0-04`）；确认 CI 已跑 vitest 与 PG（`w0-02`）。在 PR 描述记录当前提交号与下列命令结果。
  - 验证：`test -e src/octop/infra/agents/providers/provider_presets.json && test -e dashboard/src/locales/intranet/zh.json && test -e CHANGELOG-intranet.md && uv run pytest tests/unit/test_provider_preset_expansion.py tests/unit/test_provider_fetch_models.py -q`
  - _需求：1.4, 4.3_

- [ ] 2. 行内网关预设条目（0.5 人日）
  - [ ] 2.1 先写失败用例
    - 改动：新增 `tests/unit/test_provider_intranet_gateway.py::test_intranet_gateway_preset`，断言 `load_provider_presets()` 含 `id == "intranet-gateway"`、`protocol == "openai"`、`logo_id == "intranet-gateway"`、`models == []`、`base_url` 主机以 `.invalid` 结尾；在 `tests/unit/test_provider_preset_expansion.py` 追加断言：`ollama`、`onnx` 相对顺序不变。
    - 验证：`uv run pytest tests/unit/test_provider_intranet_gateway.py -q -k preset`（预期失败）
    - _需求：1.1, 1.2, 1.4_
  - [ ] 2.2 追加预设
    - 改动：`src/octop/infra/agents/providers/provider_presets.json` 末尾追加 design 所列条目；若 harness `load_provider_templates` 对空 `models` 或缺省字段报错，补齐可选字段而不改 `presets.py`。
    - 验证：`uv run pytest tests/unit/test_provider_intranet_gateway.py tests/unit/test_provider_preset_expansion.py -q`
    - _需求：1.1, 1.2, 1.4_

- [ ] 3. 预设卡片的 logo 与显示名（0.25 人日）
  - 改动：新增 `dashboard/src/assets/providers/intranet-gateway.svg`；`dashboard/src/assets/providers/index.ts` 增加 import 与 `PROVIDER_LOGOS["intranet-gateway"]` 一行；`dashboard/src/locales/intranet/{en,zh}.json` 增加 `providers.intranet-gateway`（"Intranet LLM Gateway" / "行内模型网关"）。不改上游 `dashboard/src/locales/{en,zh}.json`。
  - 验证：`cd dashboard && npx tsc -b && npm run lint && rg -n "intranet-gateway" src/assets/providers/index.ts src/locales/intranet/en.json src/locales/intranet/zh.json`，并在 `npm run dev` 下人工确认卡片图标与中英文名称。
  - _需求：1.3_

- [ ] 4. 后端请求头链路核实（0.5 人日）
  - 改动：在 `tests/unit/test_provider_intranet_gateway.py` 新增用例：`extra_json={"headers":{"X-App-Id":"a"}}` 的行经 `ProviderStore.build_harness_configs` 后 `ProviderConfig.headers` 含该头；`_probe_embedding_endpoint` 与 `embed_knowledge_texts` 用 `httpx.MockTransport`（或 monkeypatch 客户端）断言请求头到达；`fetch_openai_compatible_models` 已有 `test_fetch_models_merges_extra_headers`，只补 401 分支断言 `ok is False`。若发现任一路径丢头，就地修复该路径。另在 `tests/integration/test_providers_api.py` 追加断言：`GET /api/providers` 响应不含 `extra_json`。
  - 验证：`uv run pytest tests/unit/test_provider_intranet_gateway.py -q -k header && uv run pytest tests/integration/test_providers_api.py -q`
  - _需求：2.1, 2.4, 3.2_

- [ ] 5. 新建弹窗的只写请求头输入（1 人日）
  - [ ] 5.1 解析函数与 vitest
    - 改动：新增 `dashboard/src/pages/Settings/Models/providerHeaders.ts`（`parseHeadersInput`、`headersToExtraJson`）与 `providerHeaders.test.ts`：覆盖 `名称: 值` 多行、JSON 对象、空输入返回 `null`、非法行报错、头名含空格报错。先写测试。
    - 验证：`cd dashboard && npx vitest run src/pages/Settings/Models/providerHeaders.test.ts`
    - _需求：2.2, 2.3_
  - [ ] 5.2 接入两个新建弹窗
    - 改动：`PresetProviderModal.tsx` 在调用 `fetchProviderModels`（≈L108）、`testProviderDraft`（≈L160）与保存 payload（≈L222）处带上 `extra_json`；`CustomProviderModal.tsx` 在 `testProviderDraft`（≈L88）、`fetchProviderModels`（≈L111）与保存处同样处理；新增表单项 `extra_headers`，校验失败阻止提交；文案 `models.customHeaders`、`models.customHeadersExtra`、`models.customHeadersInvalid` 写入 `dashboard/src/locales/intranet/{en,zh}.json`。`ProviderConfigModal.tsx` 不改。
    - 验证：`cd dashboard && npx tsc -b && npm run lint && rg -c "extra_json" src/pages/Settings/Models/components/modals/ProviderConfigModal.tsx || echo "ProviderConfigModal 未发送 extra_json"`；人工在浏览器 DevTools 确认测试、拉取、保存三次请求 body 均含 `extra_json.headers`。
    - _需求：2.2, 2.3, 2.4_

- [ ] 6. 本地 TLS 伪端点测试支撑（0.5 人日）
  - 改动：新增 `tests/support/tls_endpoint.py`：`make_ca_and_leaf(tmp_path)` 用 `cryptography` 生成自签 CA 与 `127.0.0.1` 叶证书；`serve_fake_openai(cert, key, require_headers=None)` 以线程运行 `http.server` + `ssl`，实现 `GET /v1/models`、`POST /v1/embeddings`、`POST /v1/chat/completions`，`require_headers` 不满足时返回 401。自测用例放 `tests/unit/test_provider_intranet_gateway.py::test_tls_endpoint_smoke`（用 `httpx.Client(verify=<CA>)` 直连）。
  - 验证：`uv run pytest tests/unit/test_provider_intranet_gateway.py -q -k tls_endpoint`
  - _需求：4.1, 4.2_

- [ ] 7. 进程级 CA 两态验证（0.5 人日）
  - 改动：在 `tests/unit/test_provider_intranet_gateway.py` 新增参数化用例，路径为 `fetch_openai_compatible_models`、`_probe_embedding_endpoint`、`build_probe_chat_model(...).ainvoke`、`embed_knowledge_texts`：`monkeypatch.setenv("SSL_CERT_FILE", ca_pem)` 时成功；`monkeypatch.delenv("SSL_CERT_FILE", raising=False)` 时失败且异常链或错误信息含证书校验失败。再加一条断言：生产代码中这四处未显式传 `verify=`（`rg` 结果写进用例注释，不做运行期断言）。
  - 验证：`uv run pytest tests/unit/test_provider_intranet_gateway.py -q -k ca && rg -n "verify=|trust_env" src/octop/infra/agents/providers/probe.py src/octop/infra/knowledge/embed.py || echo "无显式 verify/trust_env，与基线一致"`
  - _需求：4.1, 4.2, 4.3, 3.1_

- [ ] 8. 经 HTTP 路由的集成验证（0.5 人日）
  - 改动：新增 `tests/integration/test_intranet_model_gateway.py`：设置 `SSL_CERT_FILE` 后，(a) `POST /api/admin/providers/fetch-models`（带 `extra_json.headers`）返回伪端点模型列表；缺头返回 `ok == false`；(b) 以 `POST /api/providers` 创建含 `embedding: true` 模型的行内网关供应商，`POST /api/admin/providers/{provider_id}/test` 对 Embedding 模型返回 `ok == true`；(c) 通过 `knowledge_bases.py` 中调用 `set_feature_enabled` 的路由把它设为知识库 Embedding 供应商后，`GET` capability 报告就绪，`embed_knowledge_texts` 返回等长向量。使用 `tests/support/auth.py`（`w0-03` 基线）拿管理员令牌。
  - 验证：`uv run pytest tests/integration/test_intranet_model_gateway.py -q`；PG 复跑：`OCTOP_TEST_DATABASE_URL=postgresql://octop:octop@127.0.0.1:5432/octop_test uv run pytest tests/integration/test_intranet_model_gateway.py -q`
  - _需求：3.1, 3.2, 5.1, 5.2, 2.1_

- [ ] 9. 运维手册（0.25 人日）
  - 改动：新增 `docs/intranet/model-gateway.md`，含：CA 整链拼接与 `openssl verify -CAfile` 自检；`SSL_CERT_FILE` / `REQUESTS_CA_BUNDLE` 设置位置（容器环境优先，`~/.octop/env` 兜底，改后重启）；`NO_PROXY`；预设创建、请求头填写（及过渡期用 `PATCH /api/providers/{id}` 修改请求头）、拉取模型、Embedding 设置步骤；自检命令 `openssl s_client -connect <host>:443 -CAfile <ca.pem> </dev/null | rg "Verify return code"` 与 `curl --cacert <ca.pem> -H "Authorization: Bearer <key>" https://<host>/v1/models`。
  - 验证：`rg -n "SSL_CERT_FILE|REQUESTS_CA_BUNDLE|NO_PROXY|Verify return code|/v1/models|knowledge" docs/intranet/model-gateway.md`；在测试环境按手册执行一遍，记录 `Verify return code: 0 (ok)` 与 HTTP 200。
  - _需求：6.1, 6.2_

- [ ] 10. 收尾
  - 改动：清理本 spec 引入的孤儿符号；`CHANGELOG-intranet.md` 记录"行内模型网关预设、新建供应商请求头输入、进程级 CA 验证与手册"；本 spec 无 API 变更，不改 `docs/api-intranet.md`。
  - 验证：`make all && cd dashboard && npx tsc -b && npm run lint && npm run test && cd .. && uv run pytest tests/unit/i18n -q`
  - _需求：1.4, 4.3, 6.1_
