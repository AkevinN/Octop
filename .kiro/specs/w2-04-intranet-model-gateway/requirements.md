# 需求文档：行内大模型网关接入
> spec：`w2-04-intranet-model-gateway` ｜ 波次：Wave 2 ｜ 基线：`757fd12` ｜ 预估：4 人日
> 前置：`w0-02-ci-gates`、`w0-04-fork-isolation-points`、`w1-05-saas-decoupling`、`w2-01-offline-build` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 引言

**结论**：本 spec 只交付"让 Octop 在断外网环境下用上行内大模型网关"的最小可用集：在 `w1-05` 建立的自维护预设清单 `provider_presets.json` 里加一条行内网关预设；核实并补齐"自定义请求头、拉取模型列表"两项现有能力；行内 CA 一律走进程级 `SSL_CERT_FILE`，给出配置方法与自动化验证；知识库 Embedding 指向行内网关并可验证。不新增配置键、不新增 ErrorCode、不做数据库迁移。

**背景**：按全局约束 D2，行内大模型平台是 OpenAI 兼容网关，含 Embedding。基线代码已经具备大部分能力：供应商行的 `extra_json.headers` 会被 `store.py`、`probe.py`、`knowledge/embed.py` 读取；`POST /api/admin/providers/fetch-models` 能列出 OpenAI 兼容端点的模型；所有出网点都是 `httpx` 默认客户端（`trust_env=True`），`httpx 0.28.1` 在该模式下读取 `SSL_CERT_FILE`。缺口是：没有行内网关预设；dashboard 模型设置的三个弹窗从不发送 `extra_json`，界面上无法填请求头；进程级 CA 从未被测试证明过。

**为什么做**：Wave 2 的目标是"能在内网跑起来"。没有可用的模型接入，整套系统在行内无法完成任何一轮对话。

**范围内**：
- 行内网关预设条目（含 logo 与 overlay 显示名）。
- 自定义请求头：后端全链路核实；在"新建供应商"两个弹窗里加只写的请求头输入。
- 拉取模型列表：对行内网关端点（含自定义请求头、行内 CA）可用。
- 进程级行内 CA：配置方法、失败与成功两态的自动化验证。
- Embedding 指向行内网关：知识库远程 Embedding 配置与验证。
- 运维配置文档 `docs/intranet/model-gateway.md`。

**范围外**：
| 事项 | 归属 |
|---|---|
| 按供应商配置 CA 与代理（`extra_json.tls` / `extra_json.proxy`）、`GET /api/providers` 响应体回传 `extra_json`、编辑弹窗回填请求头 | `p2-06-intranet-integration`（必须在 `w3-05` 落库加密之后） |
| 行内 IM 通道、行内 OA/知识库/工单连接器、多维配额、银行专家模板 | `p2-06-intranet-integration` |
| SSRF 内网白名单（模型 `base_url` 不经过 `ssrf_guard`，本 spec 不需要） | `w0-05-ssrf-intranet-allowlist` |
| `provider_presets.json` 本身与 `load_provider_presets` 改为显式路径 | `w1-05-saas-decoupling` |
| 镜像内置 CA、部署清单注入环境变量 | `w4-02-ops-minimum` / `p2-09-ops-observability` |
| `extra_json` 明文列加密 | `w3-05-credential-encryption` |
| 知识库检索重写、无 Embedding 时降级 | `p2-05-knowledge-retrieval` |

## 需求

### 需求 1：行内网关预设

**用户故事：** 作为行内平台管理员，我希望在模型设置页直接看到"行内模型网关"预设，以便不必手工拼装 OpenAI 兼容供应商。

#### 验收标准
1. 当调用 `load_provider_presets()` 或 `GET /api/providers/presets` 时，返回列表应当包含 `id == "intranet-gateway"`、`protocol == "openai"`、`logo_id == "intranet-gateway"`、`models == []` 的条目。
2. 该预设的 `base_url` 应当始终是不可解析的占位地址（`.invalid` 顶级域），以便未改地址时连接失败而不是落到任何公网默认端点。
3. 当 dashboard 渲染该预设卡片时，`getProviderLogo("intranet-gateway")` 应当返回专用 logo，`getProviderName` 应当从 intranet overlay 取到中英文显示名，而不是后端英文名。
4. `provider_presets.json` 中 `w1-05` 定义的既有条目（`ollama` 及其后注入的 `onnx`）的顺序与内容应当始终不变。

### 需求 2：自定义请求头

**用户故事：** 作为行内平台管理员，我希望给行内网关配置应用标识、租户号等自定义请求头，以便通过网关的鉴权与路由。

#### 验收标准
1. 当供应商行的 `extra_json` 为 `{"headers": {"X-App-Id": "a"}}` 时，`ProviderStore.build_harness_configs()` 产出的 `ProviderConfig.headers` 应当包含该头；`fetch_openai_compatible_models`、`_probe_embedding_endpoint`、`embed_knowledge_texts` 发出的请求也应当带该头。
2. 当用户在"预设供应商"或"自定义供应商"新建弹窗中填写请求头并执行"测试连接""拉取模型""保存"时，三次请求的 body 都应当携带 `extra_json`，其 `headers` 与填写一致。
3. 如果请求头输入不是合法的 `名称: 值` 行或 JSON 对象，那么弹窗应当阻止提交并在该字段下提示错误，不发出请求。
4. 编辑已有供应商（`ProviderConfigModal`，PATCH）应当始终不发送 `extra_json`，从而不覆盖已存的请求头；`GET /api/providers` 响应体应当始终不含 `extra_json`。

### 需求 3：拉取模型列表

**用户故事：** 作为行内平台管理员，我希望从行内网关一键拉取可用模型，以便不必手敲模型 ID。

#### 验收标准
1. 当 `POST /api/admin/providers/fetch-models` 的 `base_url` 指向一个 OpenAI 兼容的 HTTPS 端点、且进程已信任其 CA 时，响应应当为 `ok == true` 且模型列表与端点 `/models` 返回一致。
2. 如果端点要求的自定义请求头缺失而返回 401/403，那么响应应当为 `ok == false`，且错误信息为既有的友好文案（`_friendly_probe_error`）。

### 需求 4：进程级行内 CA

**用户故事：** 作为行内运维，我希望用一个进程级环境变量让 Octop 信任行内根证书，以便所有到行内网关的 HTTPS 调用无需逐个配置。

#### 验收标准
1. 当 `SSL_CERT_FILE` 指向含行内根 CA 的 PEM 文件时，对由该 CA 签发证书的 HTTPS 端点：拉取模型、Embedding 探测、聊天模型探测（经 harness `build_chat_model` 构造的 OpenAI 客户端）、知识库 `embed_knowledge_texts` 四条路径都应当成功。
2. 如果未设置 `SSL_CERT_FILE`，那么同一端点的上述四条路径应当失败，且底层异常为证书校验失败（`ssl.SSLCertVerificationError` 或其 httpx 包装）。
3. 在未设置 `SSL_CERT_FILE` 期间，Octop 的出网 TLS 行为应当与基线完全一致（仍用 `certifi`），本 spec 不改任何生产代码中的 `verify` / `trust_env` 参数。

### 需求 5：Embedding 指向行内

**用户故事：** 作为知识库管理员，我希望把知识库 Embedding 指到行内网关的 Embedding 模型，以便在断外网时建索引与检索。

#### 验收标准
1. 当行内网关供应商包含 `embedding: true` 的模型并被设为知识库 Embedding 供应商时，`get_capability()` 应当报告远程 Embedding 就绪，`embed_knowledge_texts` 应当调用 `{base_url}/embeddings` 并返回与输入等长的向量列表。
2. 当对该供应商执行 `POST /api/admin/providers/{provider_id}/test`（Embedding 模型）时，应当走 `_probe_embedding_endpoint` 并返回 `ok == true`。

### 需求 6：运维配置文档与自检

**用户故事：** 作为行内运维，我希望有一份照做即可的接入手册，以便在部署现场独立完成网关、CA 与 Embedding 的配置与自检。

#### 验收标准
1. `docs/intranet/model-gateway.md` 应当始终包含：CA 文件准备（整链拼接、替换 `certifi` 的影响）、`SSL_CERT_FILE` 与 `REQUESTS_CA_BUNDLE` 的设置位置（容器环境变量优先、`~/.octop/env` 兜底）、`NO_PROXY` 注意事项、预设创建步骤、请求头填写、拉取模型、Embedding 设置、以及一条可复制执行的 `openssl s_client` / `curl` 自检命令。
2. 当按文档完成配置后执行文档中的自检命令时，运维应当能观察到证书链校验通过（`Verify return code: 0 (ok)`）与 `/models` 返回 200。
