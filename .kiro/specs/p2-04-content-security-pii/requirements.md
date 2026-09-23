# 需求文档：内容安全与个人信息脱敏

> spec：`p2-04-content-security-pii` ｜ 波次：二期 ｜ 基线：`757fd12` ｜ 预估：33 人日
> 前置：`w0-01-fork-migration-namespace`、`w0-04-fork-isolation-points`、`w1-02-capability-trim`、`w3-02-audit-baseline`、`w3-03-authorization-foundation`、`w3-05-credential-encryption` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 引言

Octop 现有 `pii` 中间件只识别 7 条 API Key 形态正则，零中文个人信息能力，且上游流式增量脱敏机制在 Octop 实际使用的 `astream(version='v2')` 路径下从未执行（已核实 `stream_transformers` 零命中）。本 spec 交付 fork 自研、独立于上游的内容安全子系统：输入侧敏感词与提示词注入检测、输出侧合规审核、覆盖输入/输出/工具结果/轨迹/历史投影的中文 PII（身份证、银行卡、手机号、行方客户号）识别与掩码，含流式跨分片脱敏。审核能力做成可插拔 Provider，内置零依赖本地规则，预留行内服务 HTTP 适配位点。

**范围内**：`infra/utils/pii_cn.py` 检测/掩码；`infra/agents/security/content/` 策略、编排、本地与 HTTP Provider、流式脱敏器、门面服务；接入 `w1-02` 能力开关与注册式中间件装配；输入侧中间件；轨迹用户输入写入、历史投影 `seed_messages` 回退路径的脱敏补漏；三个直连模型旁路的脱敏；内容安全事件审计表与管理 API/前端面板；向 `w3-02` 注册中文 PII 正则。

**范围外**：日志 Formatter/Filter 本体归 `w3-02`（本 spec 只是调用方）；能力开关与中间件注册式装配归 `w1-02`；权限判定收口归 `w3-03`；providers 响应体脱敏契约传输层归 `w1-01`、落库归 `w3-05`；`CryptoProvider`/密钥托管归 `w3-05`（本 spec 只消费其 `secret_repo`）；国密算法归 `p2-02`；知识库检索侧脱敏归 `p2-05`（不覆盖知识库/附件/语音转写，除非另行拍板）；fork 迁移编号与 runner 归 `w0-01`；i18n overlay 与四方键集测试归 `w0-04`。

## 需求

### 需求 1：中文个人信息识别与金融口径掩码

**用户故事：** 作为合规负责人，我希望系统能识别对话中出现的中文个人信息并按金融口径掩码，而不是套用上游的通用掩码规则，以便满足等保与密评对客户信息保护的要求。

#### 验收标准

1. 当输入文本出现符合 GB 11643 校验位的身份证号、Luhn 校验通过且长度 16-19 的银行卡号、边界锚定的手机号、或行方客户号（正则由配置注入）时，检测函数应当命中并返回类型、位置与原始片段。
2. 如果掩码后字符串长度与原串不相等，那么测试应当判定失败——身份证保前 6 后 4、银行卡保前 6 后 4、手机号保前 3 后 4，不套用上游 `****+末4位` 默认分支。
3. 在同一份规则配置中，各 PII 类型的开关、保留位数与客户号正则应当可独立配置，默认来自内置 `default_rules.yaml`。
4. 系统应当始终把中文 PII 检测与掩码纯函数放在 `infra/utils/pii_cn.py`，不依赖任何非 utils 的 `infra` 子包，供 `content/` 编排层与 `w3-02` 日志 Formatter 共同复用。

### 需求 2：六条路径的脱敏覆盖（含流式跨分片）

**用户故事：** 作为安全运营人员，我希望用户输入、模型输出、工具结果、轨迹与历史投影都经过脱敏，不留任何明文旁路，以便审计与留痕不会二次泄露客户信息。

#### 验收标准

1. 当 `stream`/`resume_hitl` 产出的模型输出、reasoning 或 `tool_call_chunk.args` 分片跨越 PII 边界时，流式脱敏器应当在 lookback 窗口内累积后再掩码，下游累积输出不出现完整明文，流结束后累积文本等于整体脱敏后文本。
2. 如果 `tool_result` 分片的 `messages` 是消息对象而非 dict，那么脱敏门面应当同时支持两种形态。
3. 当用户输入在进入模型调用前就被写入轨迹时，该写入路径应当单独脱敏，不依赖流包装自动覆盖。
4. 如果一轮对话因阻断或异常走历史投影的 `seed_messages` 回退路径，那么落入 `thread_messages` 的历史内容应当同样已脱敏，不落原始 `request['messages']`。
5. 在 `state_snapshot` 型分片（每个 superstep 推全量消息快照）下，脱敏器应当按消息 id 增量识别，不重复全量扫描，使总扫描字符量与会话长度呈线性关系。
6. 系统应当始终保证 `enabled=false` 时脱敏门面对流式迭代器的包装是恒等操作，使输出字节流逐字节不变。

### 需求 3：可插拔审核 Provider 与断网可用性

**用户故事：** 作为运维人员，我希望内容安全能力默认零外部依赖运行，并能在行方接入自有内容安全中台时热切换，以便断网内网环境下开箱即用且预留升级空间。

#### 验收标准

1. 当系统在断网环境下启动并使用内置本地规则 Provider 时，敏感词、提示词注入特征与 PII 检测应当正常工作。
2. 如果配置切换到 HTTP JSON Provider 且目标服务不可达，那么系统应当按 `fail_open`/`fail_closed` 分别执行：`fail_closed` 产出不可用错误并终止该轮，`fail_open` 放行并记录一条降级事件。
3. 在 Provider 调用过程中，系统应当对请求施加超时与熔断，且敏感凭据不落日志。
4. 系统应当始终通过统一 Provider 协议（`scan(text, surface) -> ScanVerdict`）接入内置规则与行内 HTTP 服务，二者可通过配置切换。

### 需求 4：接入 w1-02 能力开关与中间件注册式装配

**用户故事：** 作为架构维护者，我希望内容安全中间件通过统一的能力开关与注册式装配接入，而不是直接改动 `manager.py` 里的硬编码中间件列表，以便后续 spec 与上游同步不因这一处产生冲突。

#### 验收标准

1. 当内容安全能力通过 `capabilities.<name>.enabled` 关闭时，`ContentSecurityMiddleware` 不应当出现在最终装配给 harness 的中间件链中。
2. 如果新增内容安全相关配置键，那么该键必须在 `config.py` 完成三触点（字段/env/构造）配套，并被 `w1-02` 提供的三触点单测覆盖。
3. 系统应当通过 `w1-02` 的 `assemble_agent_middleware`/登记表接入中间件，不直接修改上游 `agent_middleware` 硬编码列表。
4. 系统应当在 `before_model`/`abefore_model`/`after_model`/`aafter_model` 四个钩子上都实现扫描逻辑，因为 Octop 全程走异步 `astream`。

### 需求 5：管理 API、审计与合规回归

**用户故事：** 作为管理员，我希望能查看和配置内容安全策略、试跑规则命中效果，并让每次变更留痕，以便满足内部审计要求。

#### 验收标准

1. 当具备 `security` 权限的管理员调用 `GET/PUT /api/admin/security/content` 时，系统应当返回并接受当前策略，往返一致。
2. 当管理员提交非法 YAML 规则时，系统应当返回 400 且不落盘。
3. 当策略或规则发生变更时，系统应当在 `audit_log` 写入一条 `security.content.*` 记录，复用 `w3-02` 已收口的 `AuditRepo.write` 上下文补齐机制。
4. 如果调用者不具备 `security` 权限，那么系统应当返回 403。
5. 系统应当始终把内容安全事件（命中类型、规则、位置、值哈希）写入独立审计表，不存储命中片段原文。

### 需求 6：新增 ErrorCode 与 i18n 文案的合规登记

**用户故事：** 作为国际化维护者，我希望新增的错误码与文案严格遵循仓库既有的四方键集相等测试与 fork overlay 规则，以便 `make all` 与 `tests/unit/i18n` 始终全绿。

#### 验收标准

1. 当新增 `ErrorCode.CONTENT_BLOCKED`/`CONTENT_SECURITY_UNAVAILABLE` 时，系统应当在同一批改动中同时登记 `_DEFAULT_STATUS`，缺一即会在构造 `OctopError` 时 `KeyError`。
2. 系统应当始终把内容安全新增文案写入 `w0-04` 提供的 intranet i18n overlay，不直接写入上游 JSON 非 overlay 段（`errors.*`/`apiErrors.*` 键名登记除外，键名须在四份 bundle 中一致）。
3. 当运行 `uv run pytest tests/unit/i18n -q` 时，键集相等与占位符格式测试应当全绿。
4. 如果内容安全命名空间被多个调用点使用，那么系统应当提供 `src/octop/i18n/domains/content_security.py` domain helper，照现有 11 个同类模块的模式。
