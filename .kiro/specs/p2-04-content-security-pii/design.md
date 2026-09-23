# 设计文档：内容安全与个人信息脱敏

> spec：`p2-04-content-security-pii` ｜ 波次：二期 ｜ 基线：`757fd12` ｜ 预估：33 人日
> 前置：`w0-01-fork-migration-namespace`、`w0-04-fork-isolation-points`、`w1-02-capability-trim`、`w3-02-audit-baseline`、`w3-03-authorization-foundation`、`w3-05-credential-encryption` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 概述

Fork 内独立实现内容安全子系统，替代上游名不副实的 `pii` 中间件（只识别 API Key，无中文 PII 能力，且其流式增量脱敏在 Octop 实际走的 `astream(version='v2')` 路径下从不执行）。核心：(1) `infra/utils/pii_cn.py` 纯函数层做中文 PII 检测/掩码；(2) `infra/agents/security/content/` 编排层承载策略、可插拔 Provider、流式增量脱敏、门面服务；(3) 经 `w1-02` 的能力开关与中间件注册式装配接入，不碰上游硬编码列表；(4) 向 `w3-02` 的日志 Formatter 注册中文 PII 正则，不自建 Formatter。

## 现状（基线 `757fd12`，已核实）

- `infra/errors.py`：`ErrorCode` 枚举结束于 ≈L112；`_DEFAULT_STATUS` 起于 ≈L115；`OctopError.__post_init__`（≈L227）直接下标取值，漏配即 `KeyError`。
- `infra/agents/security/__init__.py`（全文件 6 行，已读全文）：只导出 `SecuritySettingsStore`、`ToolGuardRulesStore`，需追加本 spec 两个 store。
- `infra/auth/captcha/providers.py`：可插拔注册表先例，符号已核实——`_REGISTRY`/`_ALIASES`（≈L305-306）、`register()`（≈L314）、`get_provider()`（≈L327）、`list_providers()`（≈L331）、`parse_slug()`（≈L335）、`_register_builtins()`（≈L345）；不是 `get()`/`available_slugs()`（不存在）。
- `infra/utils/paths.py`：`tool_guard_rules_dir`（≈L101）、`tool_guard_rules_file`（≈L106-107）先例，本 spec 的 dir/file 属性照此追加。
- `i18n/domains/`：已核实现存 11 个模块，无 `content_security.py`。
- `w1-02`/`w3-02` 设计文档（均尚未实施）：`w1-02` 规划 `assemble_agent_middleware`/`FORK_AGENT_MIDDLEWARE`；`w3-02` 规划 `RedactingFormatter`/`register_redaction_pattern()`，文档原文明确"PII 规则由 `p2-04` 追加"。本 spec 对接二者接口，不重复实现。
- Wave 1-3 会显著改动 `manager.py`/`processor.py`/`api/app.py` 的行号与符号名，本设计只给职责与方案，不给行号；实施时先 `rg` 重新定位。

## 方案

1. **纯函数下沉**：PII 检测（身份证 GB 11643、银行卡 Luhn+长度、手机号边界锚定、客户号可配正则）与金融口径掩码只放 `infra/utils/pii_cn.py`（只依赖 stdlib）；`content/detectors_cn.py`/`mask.py` 是薄编排层；`w3-02` 日志脱敏同样调用它，不重复实现。
2. **策略与 Provider**：`ContentSecurityPolicy` 独立持久化在 settings 表 `key='content_security'`，不挂上游 `SecurityPolicy.pii`（其 `from_dict` 五段白名单会静默丢弃额外字段）。Provider 协议 `scan(text, surface) -> ScanVerdict`，内置 `LocalRulesProvider`（零依赖）与 `HttpJsonProvider`（超时/熔断/`fail_open`|`fail_closed`，凭据走 `w3-05` 的 `secret_repo`）。
3. **流式增量脱敏**：`StreamRedactor` 按 `(chunk_type, block_index)` 维护 per-call lookback 缓冲，包装 `stream`/`resume_hitl` 内层迭代器；`enabled=false` 时 `return` 同一迭代器对象。`tool_result.messages` 需同时支持 dict 与消息对象；`state_snapshot` 按消息 id 增量识别，不对每个 superstep 全量重扫（否则 O(N×会话长度)）。
4. **中间件接入**：`ContentSecurityMiddleware` 实现四钩子（全程异步 `astream`），经 `assemble_agent_middleware`/`FORK_AGENT_MIDDLEWARE` 接入，不直改中间件列表；开关读 `capabilities.<name>.enabled`；策略变更后调 `reload_harness_agents()`（无上游热设接口，与 `set_security_policy` 有意不对称）。
5. **旁路补漏**：用户输入轨迹写入（进模型调用前，不在流下游）与历史投影 `seed_messages` 回退路径（阻断/异常时落原始消息）需单独脱敏；三个直连模型旁路各自在调用前后补扫描/脱敏，不塞进共享辅助函数（§5 边界）；工具结果二次富化需在脱敏点之后再补一次轻量脱敏。具体文件/函数名以实施时代码为准。

## 组件与接口

| 路径 | 类型 | 职责 |
|---|---|---|
| `infra/utils/pii_cn.py` | 新增 | `detect_cn_pii()`/`apply_cn_mask()`，只依赖 stdlib |
| `infra/agents/security/content/models.py` | 新增 | `ContentSecurityPolicy`/`ScanRequest`/`ScanVerdict`/`CnPiiMatch` |
| `.../content/detectors_cn.py`、`mask.py` | 新增 | 薄编排层，注入策略与客户号正则 |
| `.../content/providers.py` | 新增 | 注册表，照 `captcha/providers.py` 形态 |
| `.../content/local_rules.py`、`http_provider.py` | 新增 | 本地 Provider；行内 HTTP 适配器 |
| `.../content/rules_store.py`、`rules/default_rules.yaml` | 新增 | YAML 读写校验，接口对齐 `ToolGuardRulesStore` |
| `.../content/stream_redactor.py` | 新增 | `StreamRedactor.feed`/`flush` |
| `.../content/service.py` | 新增 | `ContentSecurityService` 门面：`scan_input`/`redact_value`/`redact_messages`/`redact_stream`/`audit` |
| `infra/agents/security/content_settings_store.py` | 新增 | `ContentSecuritySettingsStore`，接线到 agent manager 三处 |
| `infra/agents/middleware/content_security.py` | 新增 | `ContentSecurityMiddleware`，四钩子，经 `w1-02` 登记表接入 |
| `infra/db/repos/content_security_events.py` | 新增 | `write`/`list_by_thread`/`list_recent`，只存哈希与位置 |
| `api/routers/security.py` | 修改 | 新增 `/content` 系列端点，`require_permission('security')`（以 `w3-03` 落地实现为准） |
| `dashboard/.../ContentSecurityPanel.tsx` | 新增 | 自包含 load/save，不参与父表单提交（父提交五段白名单会丢弃 content 段） |
| `pyproject.toml` | 修改 | `include` 加 `*.yaml`，否则内置规则被 wheel 排除 |

## 数据模型

fork 迁移 `forkNNN_content_security_events`（编号合入时按 `w0-01` 水位表实际取号）：表 `content_security_events`，字段 `ts, agent_id, thread_id, surface, provider, rule_id, pii_type, action, value_hash, char_offset`（不存原文；`char_offset` 避开 SQL 保留字倾向）。同名 `.sql`/`.pg.sql` 成对，由 `w0-01` runner 执行，不改上游 `_schema_version`。

## 配置

策略字段（enabled/mode/surfaces/pii_types 等）走 `ContentSecuritySettingsStore` 持久化，不进 `config.json`。若需要独立于策略内 `timeout_ms` 的进程级 Provider 超时默认值，则新增 `content_security_provider_timeout_ms` 需补齐三触点（`OctopConfig` 字段、env 覆盖块、`OctopConfig(...)` 构造），由 `w1-02` 三触点单测覆盖；否则本 spec 无新增 `config.json` 键。

## 错误处理

新增两个 `ErrorCode`（复用现有码不新增其它），同批登记枚举与 `_DEFAULT_STATUS`：`CONTENT_BLOCKED` → 403（`mode=block` 命中拦截，中止当轮流式输出）；`CONTENT_SECURITY_UNAVAILABLE` → 503（`fail_closed` 下 Provider 不可达）。前端不需要新增 chunk 类型——`block` 直接抛 `OctopError`，走既有流式错误映射转成 `{type:'error', error_code}`，前端 `error` 分支已解析。

## 安全考虑

HTTP Provider 凭据走 `w3-05` 的 `secret_repo`，不明文落库、不落日志；审计事件表只存哈希与位置，不存原文（与内置专家 `ai-safety-guardian` 的"留原文"主张冲突，见待确认）；`block` 模式下半截 turn 落历史/轨迹必须是脱敏后内容；日志脱敏正则通过 `w3-02` 的 `register_redaction_pattern()` 注册，本 spec 不碰日志 Formatter/Filter。

## 测试策略

- 单测：`uv run pytest tests/unit/security -q`（该目录不加 `__init__.py`，模块 basename 需全局唯一）。
- 中间件/旁路：`uv run pytest tests/unit/agents -k content_security -q`、`uv run pytest tests/unit/gateway -k redaction -q`。
- 集成：`uv run pytest tests/integration/test_content_security_api.py -q`（`w0-02` PG 门禁合入后另跑 `OCTOP_TEST_DATABASE_URL` 场景）。
- i18n：`uv run pytest tests/unit/i18n -q`。
- 前端：`cd dashboard && npx tsc -b && npm run lint`（`ci.yml` 不跑前端检查，仅 pre-commit 的 `npm run build` 带 `tsc -b`）。
- 打包：新增断言内置 YAML 被打包清单覆盖的单测。

## 与其他 spec 的交接

- 依赖 `w0-01`：fork 迁移 runner 与取号；本 spec 只按格式写迁移文件。
- 依赖 `w0-04`：i18n overlay 路径与三方键集相等测试；新增文案写 overlay。
- 依赖 `w1-02`：能力开关框架与中间件注册式装配，本 spec 不重新发明。
- 依赖 `w3-02`：日志脱敏 Formatter 与 `AuditRepo.write` 上下文补齐；本 spec 只是调用方，不交付 Formatter/Filter 本体。
- 依赖 `w3-03`：`require_permission` 最终实现与三员分立后的角色语义。
- 依赖 `w3-05`：`CryptoProvider`/`secret_repo`。
- 交付给 `p2-05`：`scan_input`/`redact_value` 可被知识库检索复用，是否接入由 `p2-05` 决定。
- 归别的 spec：providers 响应体脱敏契约（`w1-01`传输层→`w3-05`落库→`p2-06`加字段）；国密/KMS（`p2-02`）；审计防篡改哈希链（`p2-03`，在 `w3-02` 字段集之上，本 spec 表结构需保持稳定）；附件/语音转写文本脱敏（若纳入需另行拍板）。

## 风险与回滚

- 最高风险：包装 `stream`/`resume_hitl` 影响全部流式输出；缓解：关闭时 identity 直通，开关可热切。
- lookback 增加首 token 延迟，规则误报破坏正常业务对话（银行数字串易误命中）；缓解：客户号正则默认关闭，先 `warn` 模式跑影子流量。
- `block` 与历史投影回退路径交互复杂，需配套输入侧脱敏。
- 与上游高频文件合并冲突概率高；缓解：新逻辑收进独立文件。
- 回滚：能力开关一键关闭即恢复；fork 迁移回滚走 `w0-01` 水位表机制，不影响上游 `_schema_version`。

## 待行方确认

- D8：审计事件表默认只存哈希不存原文，与内置专家 `ai-safety-guardian` 的"留原文、留存 ≥6 个月"主张冲突，需裁决留痕口径与留存期限。
- 客户号确切格式（长度/前缀/是否含字母/校验位）未定，默认给可配置且默认关闭的正则占位。
- Provider 不可达时 `fail_open`/`fail_closed` 默认策略：steering 未覆盖，默认假设 `fail_closed`（金融合规惯例）。
- 提示词注入处置强度、误杀容忍度、是否按机构/部门/用户维度配置策略：默认全局一套 + agent 级 override（对应 D14，当前判定不在本轮范围）。
- 知识库文档/附件/语音转写文本是否纳入本 spec：默认不纳入，若需要须重新估算。
