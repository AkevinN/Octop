# 需求文档：行内系统对接

> spec：`p2-06-intranet-integration` ｜ 波次：二期 ｜ 基线：`757fd12` ｜ 预估：34–40 人日
> 前置：`w0-01-fork-migration-namespace`、`w0-02-ci-gates`、`w0-04-fork-isolation-points`、`w0-05-ssrf-intranet-allowlist`、`w1-01-security-hotfix`、`w2-01-offline-build`、`w2-04-intranet-model-gateway`、`w3-03-authorization-foundation`、`w3-05-credential-encryption` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 引言

**背景：** 一期（Wave 0–4）交付了断网可跑、合规最低集的 Octop；本 spec 是二期第 6 项，把"让行内系统真正接得上"补齐：供应商级 TLS/代理、行内 IM、行内 OA/知识库/工单连接器、多维配额、银行场景专家模板。源材料 `S21-intranet-integration.json` 的估算（40–52 人日）覆盖了本 spec 与 `w2-04` 共用的整块"模型网关"工作，已按 [§3 共享资产归属](../../steering/intranet-transformation.md#3-共享资产归属) 与用户圈定范围拆分。

**为什么做：** 一期只保证系统断网启动、合规运行，尚不能对接行方 IM/OA/知识库/工单与多模型网关，配额也只有"终身总量"一维，无法按部门/项目管理成本。

**范围内（本 spec）：**
1. 供应商级 TLS（CA）与代理：`w2-04` 之外的部分——按供应商在 `providers.extra_json` 里配置 CA bundle / 跳过校验 / 代理地址，并在 `w1-01` 的脱敏契约、`w3-05` 的加密落库之上把该配置回传给前端。
2. 行内 IM 通道：以 `harness-gateway` 新增一个内置通道实现（依赖全局约束 D13"harness-* 源码可得"的默认假设）+ Octop 侧注册/表单/i18n。
3. 行内 OA、知识库、工单三类 REST 连接器：以 `gateway` 型适配器接入，经 `w0-04` 提供的 `catalog_intranet.py::_fork_entries()` 登记目录项。
4. 多维配额：把"按用户终身总 token"扩展为"按用户 × 周期 × Agent × 模型"，复用既有 `ErrorCode.TOKEN_QUOTA_EXCEEDED`。
5. 银行场景专家模板：3 个内置专家（manifest + SOUL + 头像）。

**范围外（归属见 [`.kiro/steering/intranet-transformation.md` §3](../../steering/intranet-transformation.md#3-共享资产归属)，均已合入不重复实现）：**
- 模型网关预设条目、logo、请求头全链路、进程级 `SSL_CERT_FILE`、Embedding 网关指向 —— `w2-04`。
- SSRF 内网白名单机制本身（配置键、注入点、四处放行点、字节级不变回归）—— `w0-05`；本 spec 只**配置**行内域名/网段并写连接器专用联调用例。
- `_FORK_DISABLED_MOUNTS`、`catalog_intranet.py` 框架本身、i18n overlay 目录、`CHANGELOG-intranet.md`/`docs/api-intranet.md` 骨架、上游同步手册 —— `w0-04`；本 spec 只在登记表里加条目。
- providers/voice 响应脱敏契约（`has_api_key`、敏感键掩码规则）—— `w1-01`；本 spec 遵守，不重新定义。
- `extra_json` 敏感字段加密落库、`CryptoProvider`、信封格式 —— `w3-05`；本 spec 只在其编解码接口之上读写。
- fork 迁移 runner、`_fork_schema_version`、`forkNNN_` 命名与执行 —— `w0-01`；本 spec 只按规则新增一个 `forkNNN_usage_quotas` 迁移对。
- 权限判定收口、角色三员分立 —— `w3-03`；本 spec admin 配额路由沿用当时已收口的鉴权方式，不新增权限模型。
- Agent 强制沙箱、KMS/国密、审计防篡改、知识库三级权限检索重写、统一身份适配器 —— 分别是 `p2-01`/`p2-02`/`p2-03`/`p2-05`/`p2-11`，与本 spec 并列、无功能耦合。

## 需求

### 需求 1：供应商级 CA 与代理配置

**用户故事：** 作为平台管理员，我希望为每个模型供应商单独配置 CA 与代理，以便同时接入自签证书的行内网关和走公司代理的第三方端点，而不必设全局 `SSL_CERT_FILE`。

#### 验收标准
1. 当管理员在某供应商的 `extra_json.tls.ca_bundle` 配置自签 CA 路径后，对该供应商发起 `POST /api/providers/{id}/test`、`POST /api/admin/providers/fetch-models` 与 embedding 探测时，系统应当对该自签 HTTPS 端点返回成功。
2. 如果供应商未配置 `extra_json.tls`，那么系统应当保持现有行为（使用默认 CA），对同一自签端点返回证书校验失败错误。
3. 当管理员在 `extra_json.proxy.url` 配置代理后，该供应商的探测请求应当经配置的代理发出；未配置代理的供应商不应受宿主进程 `HTTPS_PROXY` 环境变量影响。
4. 当前端读取 `GET /api/providers` 时，响应应当在 `w1-01` 的脱敏契约下回传该供应商的 CA/代理配置（敏感字段掩码，不回传明文密钥类值），使编辑弹窗可正确回填且保存不清空已有 `headers`。
5. 系统应当始终提供纯函数级别的 TLS 解析与 httpx 客户端构造能力，供 store/probe 层与未来消费方共用。

### 需求 2：行内 IM 通道

**用户故事：** 作为行内业务方，我希望 Agent 能通过行内自有 IM 系统收发消息，以便员工在熟悉的办公 IM 里直接使用 Octop。

#### 验收标准
1. 当行方提供的 D13 假设成立（harness-* 源码可得）时，系统应当新增一个行内 IM 的 `BaseChannel` 实现并在上游枚举与 Octop 两侧同步登记，使 `POST /api/agents/{id}/channels {"kind": "<bank_im>"}` 返回 201。
2. 当该通道已配置凭据并探测时，`POST /api/agents/{id}/channels/probe` 应当返回连接成功；网关启动后 `GET /api/agents/{id}/channels` 中该行的运行时状态应当为已连接。
3. 在 dashboard 通道页展示该通道期间，`ChannelKey` 联合类型与四个穷尽 `Record`（label/图标/颜色/键值）都应当包含该通道，使 `npx tsc -b` 保持通过。
4. 如果 D13 假设不成立（harness-* 源码不可得），那么本需求应当退化为复用现有 MQTT 通道桥接行内 IM 网关，不改动 `harness-gateway`。

### 需求 3：行内 OA / 知识库 / 工单连接器

**用户故事：** 作为 Agent 使用者，我希望 Agent 能查询行内 OA 审批、知识库文档与工单系统，以便把日常事务性查询交给 Agent 处理。

#### 验收标准
1. 当系统列出连接器目录时，`get_catalog_entry('bank-oa'/'bank-kb'/'bank-ticket')` 均应当非空且 `mcp_mode='gateway'`。
2. 当用户创建这三类连接器实例时，`validate_create_credentials` 不应当再抛出"不支持的 custom_fields 连接器 kind"错误，且应当产出内部调用令牌。
3. 当行内网段已通过 `w0-05` 提供的机制放行后，三个适配器对配置的 OA/KB/工单端点的 `list_tools()`/`call_tool()`/`probe_credentials()` 应当可正常调用；白名单为空时应当保持现有拒绝行为不变（回归验证委托给连接器专用测试，不重复 `w0-05` 已覆盖的白名单机制测试）。

### 需求 4：多维配额

**用户故事：** 作为平台管理员，我希望能按周期（周/月/终身）、按 Agent、按模型分别设置用量上限，以便按部门或项目控制成本，而不是只能设一个全局终身上限。

#### 验收标准
1. 当管理员为某用户配置 `{period: "month", scope: "agent", agent_id: X, limit: N}` 且该 Agent 当月用量达到 N 时，用户对该 Agent 发起对话应当返回 HTTP 403 且 `error.code = TOKEN_QUOTA_EXCEEDED`。
2. 在该限制生效期间，用户对其他 Agent 的对话不应当受影响。
3. 当按模型配置配额时，系统应当在模型调用钩子（`wrap_model_call`/`awrap_model_call`）从 `ModelRequest.model` 取实际模型标识判定，不应当依赖 `configurable["model"]` 是否存在。
4. 如果某用户未配置任何多维配额、仅有旧版 `user_policies` 的 `token_quota`，那么其行为应当与改造前完全一致（等价于一条 `scope=user, period=lifetime` 规则），并应当有专门的回归用例覆盖。
5. 配额相关的数据库结构变更应当以 `forkNNN_usage_quotas` 的形式通过 `w0-01` 提供的 fork 迁移 runner 执行，不应当占用上游 `NNN_` 迁移号，不应当改动 `tests/unit/db/test_db_pool.py` 里既有的 `assert v == 15` 类断言。
6. 系统应当始终复用已存在的 `ErrorCode.TOKEN_QUOTA_EXCEEDED`（及其 `_DEFAULT_STATUS`），不应当新增配额相关 `ErrorCode`。

### 需求 5：银行场景专家模板

**用户故事：** 作为最终用户，我希望首次使用时能直接选用贴合银行业务场景的专家模板，以便更快获得可用的 Agent 而不必从零配置人设。

#### 验收标准
1. 当系统扫描 `experts/library/*/manifest.json` 时，应当发现 3 个新增的银行场景专家模板，且各自的 `task_examples` 中/英数组等长、条数为 3 或 6。
2. 当前端请求 `GET /api/experts` 时，响应应当包含这 3 个新专家的 id；对应的头像应当同时存在于 `dashboard/public/experts/avatars/` 与打包场景的 `_FALLBACK_BUNDLED_AVATAR_IDS` 回退集合中。

## 与其他 spec 交接及回归约束

见 [design.md「与其他 spec 的交接」](./design.md#与其他-spec-的交接)。所有验收标准不得依赖前序 spec 已删除的能力，不为 `w1-01`/`w1-03`/`w1-05` 已裁剪的功能编写任何代码。
