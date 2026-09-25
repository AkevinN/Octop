# 设计文档：行内大模型网关接入
> spec：`w2-04-intranet-model-gateway` ｜ 波次：Wave 2 ｜ 基线：`757fd12` ｜ 预估：4 人日
> 前置：`w0-02-ci-gates`、`w0-04-fork-isolation-points`、`w1-05-saas-decoupling`、`w2-01-offline-build` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 概述

本 spec 以"加数据 + 加测试 + 加文档"为主，生产代码改动只有两处：`provider_presets.json` 追加一条预设；dashboard 两个新建弹窗增加只写的请求头输入。进程级 CA 不改任何 `verify` / `trust_env` 参数，而是用一组真实 TLS 握手的测试证明 `SSL_CERT_FILE` 在四条出网路径上生效，再把配置方法写成运维手册。按供应商 CA/代理与 `extra_json` 回传整体留给 `p2-06`。

## 现状

- 预设：`src/octop/infra/agents/providers/presets.py` 的 `load_provider_presets`（基线 ≈L214）用 harness 包内 `provider_template.json` 生成列表，再注入 `openai-codex` 与 `onnx`。`w1-05` 将其改为显式读取 fork 自维护的 `src/octop/infra/agents/providers/provider_presets.json`（本 spec 前置，新文件由 `w1-05` 建），格式同 harness 模板：数组元素字段 `id/name/base_url/protocol/api_key_env/api_key_prefix/logo/models/vendor/vendor_name/variant`（已核实包内模板第一条）。harness `serialize_provider_preset` 的 `_logo_id` 取 `logo` 文件名去扩展名，缺省取 `id`（`harness_agent/providers/api.py` ≈L50）。模板不承载请求头。
- 请求头读取：`probe.py::provider_headers`（≈L24）从 `extra_json.headers` 取字典；`store.py::ProviderStore.build_harness_configs`（≈L134，解析在 ≈L146-153）把它放进 `ProviderConfig.headers`，harness `llm/factory.py` ≈L276 转为 `default_headers`；`_probe_embedding_endpoint`（≈L161）、`fetch_openai_compatible_models`（≈L264）、`knowledge/embed.py::embed_knowledge_texts`（≈L16，≈L29 调 `provider_headers`）都合并该头。已有单测 `tests/unit/test_provider_fetch_models.py::test_fetch_models_merges_extra_headers`。
- 请求头写入：`api/routers/providers.py` 的 Create/Patch/TestDraft/FetchModels 四个 body 都有 `extra_json: str | None`（≈L52/61/89/97）；`_row_to_dict`（≈L118）不输出 `extra_json`；`_PROVIDER_REHYDRATE_FIELDS`（≈L68）含 `extra_json`。dashboard `providerApi.ts` 的 `testProviderDraft`（≈L19）与 `fetchProviderModels`（≈L54）支持 `extra_json`，但 `Settings/Models/components/modals/` 下 `PresetProviderModal.tsx`（调用 ≈L108、≈L160，保存 payload ≈L222）、`CustomProviderModal.tsx`（≈L88、≈L111）、`ProviderConfigModal.tsx`（≈L784、≈L876）均不传 `extra_json`；全仓 tsx 里只有 `Settings/Voice/index.tsx` ≈L144 写 `extra_json`。CLI `octop provider create`（`cli/commands/provider.py` ≈L52）也没有请求头选项。结论：后端链路完整，界面与 CLI 无入口，只能直接调 API。
- 路由：`GET /api/providers/presets`（≈L139）、`POST /api/admin/providers/test-draft`（≈L298）、`POST /api/admin/providers/fetch-models`（≈L328）、`POST /api/admin/providers/{provider_id}/test`（≈L465）。
- TLS：`probe.py` 两处 `httpx.AsyncClient(timeout=_FETCH_MODELS_TIMEOUT_S)`（≈L171、≈L278），`embed.py` ≈L32 `httpx.Client(timeout=60.0)`，均未传 `verify`/`trust_env`。已核实 `httpx 0.28.1` `_config.py` ≈L34-40：`trust_env` 且有 `SSL_CERT_FILE` 时 `create_default_context(cafile=...)`，否则用 `certifi.where()`。`openai 2.44.0` / `anthropic 0.125.0` 底层同为 httpx 客户端。注意 `SSL_CERT_FILE` 是**替换** `certifi` 而非追加。
- 环境变量：`infra/utils/env_file.py` 的 `_PROTECTED_EXACT`（≈L12）只保护 `HOME/USER/USERNAME/LOGNAME/SHELL/PWD`，另保护 `OCTOP_` 前缀（≈L111）；`infra/server.py` ≈L290-292 启动时 `apply_env_file`；`api/routers/envs.py` 提供 `/api/envs` 读写并在保存后 `_after_env_sync`（≈L48）。因此 `SSL_CERT_FILE` 可通过容器环境或 `~/.octop/env` 设置。
- Embedding：`knowledge/gate.py` 以 settings 键 `knowledge_embedding_provider_id`（≈L21）选择供应商，`set_feature_enabled`（≈L96）写入，`get_capability`（≈L63）报告就绪；HTTP 面在 `api/routers/knowledge_bases.py`（`GET …/capability` ≈L310，写入调用在 ≈L393 附近）。`embed.py` 在供应商缺 `base_url` 或 `api_key` 时抛 `RuntimeError`（≈L26-27）。
- dashboard：`assets/providers/index.ts` 的 `PROVIDER_LOGOS`（≈L27）是 `Record<string,string>`，缺键回落 `customProviderLogo`；`getProviderName`（≈L141）查 `providers.${providerId}`；`presetUtils.ts::presetLogoId`（≈L64）。上游 `dashboard/src/locales/{en,zh}.json` 的 `providers` 命名空间各 14 键。

## 方案

1. **预设**：在 `provider_presets.json` 末尾追加一条：`id="intranet-gateway"`、`name="Intranet LLM Gateway"`、`base_url="https://llm-gateway.intranet.invalid/v1"`、`protocol="openai"`、`api_key_env=""`、`api_key_prefix=""`、`logo="intranet-gateway.svg"`、`models=[]`。`.invalid` 保证未改地址即连接失败（需求 1.2）。模型由"拉取模型"填充。
2. **请求头入口**：在 `PresetProviderModal` 与 `CustomProviderModal` 加一个多行文本字段"自定义请求头"（每行 `名称: 值`，也接受 JSON 对象），由新增纯函数解析为 `{headers: {...}}` 并序列化进 `extra_json`，用于测试、拉取、保存三次请求。`ProviderConfigModal`（PATCH）不动：不发 `extra_json` 即不触发覆盖。修改已存请求头的界面回填归 `p2-06`；过渡期用"删除后重建"或 `PATCH /api/providers/{id}` 直接调 API（写进运维手册）。
3. **进程级 CA**：不改生产代码。新增测试支撑模块在本机起一个由测试自签 CA 签发证书的 HTTPS 伪 OpenAI 端点，分别在"设置/不设置 `SSL_CERT_FILE`"两态下调用四条路径断言成败。
4. **Embedding**：用同一伪端点实现 `/embeddings`，端到端验证 `set_feature_enabled` → `get_capability` → `embed_knowledge_texts`，以及供应商测试路由走 Embedding 探测。
5. **文档**：`docs/intranet/model-gateway.md`（`docs/intranet/` 由 `w0-04` 建立）。

## 组件与接口

| 文件 | 类型 | 内容 |
|---|---|---|
| `src/octop/infra/agents/providers/provider_presets.json` | 修改（`w1-05` 新建） | 追加 `intranet-gateway` 条目 |
| `dashboard/src/assets/providers/intranet-gateway.svg` | 新增 | 中性网关图标，无外链资源 |
| `dashboard/src/assets/providers/index.ts` | 修改 | import 一行 + `PROVIDER_LOGOS` 一行 |
| `dashboard/src/locales/intranet/{en,zh}.json` | 修改（`w0-04` 新建） | `providers.intranet-gateway`、`models.customHeaders*` 文案 |
| `dashboard/src/pages/Settings/Models/providerHeaders.ts` | 新增 | `parseHeadersInput(text: string): { headers: Record<string,string> } \| { error: "format" }`；`headersToExtraJson(h: Record<string,string>): string \| null`（空字典返回 `null`） |
| `dashboard/src/pages/Settings/Models/components/modals/PresetProviderModal.tsx`、`CustomProviderModal.tsx` | 修改 | 新增 `extra_headers` 表单项与校验；三处请求携带 `extra_json` |
| `tests/support/tls_endpoint.py` | 新增 | `make_ca_and_leaf(tmp_path) -> tuple[Path, Path, Path]`（CA PEM、叶证书、私钥，用 `cryptography` 生成，SAN 含 `127.0.0.1`）；`serve_fake_openai(cert, key, *, require_headers: dict[str,str] \| None = None) -> contextmanager[str]`（线程内 `http.server` + `ssl`，实现 `GET /models`、`POST /embeddings`、`POST /chat/completions`，返回 `https://127.0.0.1:<port>/v1`） |
| `tests/unit/test_provider_intranet_gateway.py` | 新增 | 预设、请求头链路、CA 两态、Embedding 单测 |
| `tests/integration/test_intranet_model_gateway.py` | 新增 | 经 HTTP 路由的拉取模型、供应商测试、知识库 Embedding |
| `dashboard/src/pages/Settings/Models/providerHeaders.test.ts` | 新增 | vitest（依赖 `w0-02` 让 vitest 进 CI） |
| `docs/intranet/model-gateway.md` | 新增 | 运维手册 |

## 数据模型

无。`extra_json` 沿用既有列与 `{"headers": {...}}` 结构；不新增 fork 迁移。

## 配置

无新配置键。仅使用进程环境变量 `SSL_CERT_FILE`（httpx / OpenSSL）、`REQUESTS_CA_BUNDLE`（少量 `requests` 调用点）、`NO_PROXY`，均不进 `config.py`。

## 错误处理

不新增 ErrorCode。证书失败、401/403 沿用 `probe.py::_friendly_probe_error` 的既有文案；前端请求头格式错误是表单校验提示，走 dashboard intranet overlay 文案，不是 API 错误。

## 安全考虑

- `SSL_CERT_FILE` 替换默认信任库：只放行内根与中间证书时，所有出网 TLS 只信任行内 CA，符合断外网目标；手册要求整链拼接并说明对其它出网（如语音）同样生效。
- `~/.octop/env` 可由管理员经 `/api/envs` 写入 `SSL_CERT_FILE`，可被用于植入恶意 CA；手册把容器环境变量定为标准做法，`/api/envs` 仅作应急。收紧 `/api/envs` 可写键归 `w3-06` / `w3-03`，本 spec 不改。
- 请求头可能含网关密钥：前端只写不读；`GET /api/providers` 继续不回传 `extra_json`；落库加密归 `w3-05`。日志中不打印请求头（沿用现状）。
- 预设 `base_url` 使用 `.invalid`，杜绝误连公网。
- 宿主若设置 `HTTPS_PROXY`，httpx `trust_env` 会把网关流量送往代理；手册要求把网关域名写入 `NO_PROXY`。

## 测试策略

| 类别 | 内容 | 本地命令 |
|---|---|---|
| 单测 | 预设条目与顺序；请求头进入 `ProviderConfig.headers`、拉取模型、Embedding 探测、`embed_knowledge_texts`；CA 两态 × 四路径 | `uv run pytest tests/unit/test_provider_intranet_gateway.py tests/unit/test_provider_preset_expansion.py tests/unit/test_provider_fetch_models.py tests/unit/knowledge/test_embed.py -q` |
| 集成 | `POST /api/admin/providers/fetch-models`、`POST /api/admin/providers/{id}/test`、知识库 capability 设置后建索引向量 | `uv run pytest tests/integration/test_intranet_model_gateway.py tests/integration/test_provider_fetch_models.py tests/integration/test_providers_api.py -q` |
| 前端 | `parseHeadersInput` 解析与报错；tsc 与 lint | `cd dashboard && npx tsc -b && npm run lint && npx vitest run src/pages/Settings/Models/providerHeaders.test.ts` |
| PG | 本 spec 无 SQL 改动；集成用例在 PG 下复跑一遍即可 | `OCTOP_TEST_DATABASE_URL=postgresql://… uv run pytest tests/integration/test_intranet_model_gateway.py -q` |

CA 用例跨平台：证书写入 `tmp_path`，服务绑定 `127.0.0.1` 随机端口；`SSL_CERT_FILE` 用 `monkeypatch.setenv`/`delenv`，不假设 POSIX 路径。

## 与其他 spec 的交接

- 依赖 `w1-05`：`provider_presets.json` 与显式路径加载（其 design 已写明"行内网关条目由 `w2-04` 追加到这份 JSON"），`openai-codex` 注入已删；`test_provider_preset_expansion.py` 已由其重写，本 spec 只追加断言。
- 依赖 `w0-04`：dashboard intranet overlay、`CHANGELOG-intranet.md`、`docs/intranet/`。本 spec 无 API 变更，不写 `docs/api-intranet.md`。
- 依赖 `w0-02`：vitest 与 PG 进 CI。
- 依赖 `w2-01`：离线构建；本 spec 的 logo 为本地 svg，不引入新依赖，`cryptography` 已在环境中。
- 与 `w0-05`：模型 `base_url` 不经过 `ssrf_guard`，无交集；`safe_request` 不读 `HTTPS_PROXY`，本 spec 不改 transport。
- 交付给 `w4-02` / `p2-09`：手册中的环境变量与 CA 挂载要求，供部署清单落地。
- 交付给 `p2-06`：`providerHeaders.ts` 解析函数可复用于编辑回填；按供应商 CA/代理、`extra_json` 回传、行内 IM、连接器、配额均归 `p2-06`（且须在 `w3-05` 之后）。
- 交付给 `p2-05`：行内 Embedding 可用性结论（D2）。
- `w1-05` 保留的 OpenAI 兼容语音与本 spec 共用同一进程级 CA。

## 风险与回滚

| 风险 | 缓解 |
|---|---|
| harness `load_provider_templates` 对 `models: []` 或缺字段报错 | 任务 2 先写失败用例验证；必要时补 `vendor` 等可选字段 |
| `SSL_CERT_FILE` 覆盖 `certifi`，漏拼中间证书导致全部出网失败 | 手册给整链拼接与 `openssl verify` 自检 |
| 修改 `SSL_CERT_FILE` 后已缓存的 Agent 客户端仍用旧上下文 | 手册要求重启服务；`/api/envs` 路径需重载 Agent |
| 宿主代理劫持网关流量 | `NO_PROXY` |
| 本地 HTTPS 伪端点在 Windows CI 不稳定 | 只用 stdlib `ssl` + `http.server`，线程服务，随机端口，显式关闭 |

回滚：删除预设条目与前端请求头字段即可，均为纯追加，无数据迁移。

## 待行方确认

- D2：默认假设行内平台为 OpenAI 兼容网关且含 Embedding。若无 Embedding，需求 5 改为"验证知识库在无远程 Embedding 时的行为"，并由 `p2-05` 做纯全文降级。
