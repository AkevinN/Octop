# 实施计划：内容安全与个人信息脱敏

> spec：`p2-04-content-security-pii` ｜ 波次：二期 ｜ 基线：`757fd12` ｜ 预估：33 人日
> 前置：`w0-01-fork-migration-namespace`、`w0-04-fork-isolation-points`、`w1-02-capability-trim`、`w3-02-audit-baseline`、`w3-03-authorization-foundation`、`w3-05-credential-encryption` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

每个顶层任务完成后可独立提交；提交前运行任务内的验证命令。二期任务粒度比一期粗一级，实施时先用 `rg` 对本文件列出的路径/符号重新定位（一期落地后代码已变化，行号一律不写）。

- [ ] 1. 确认前置 spec 已合入并记录基线
  - 改动：确认 `w0-01`、`w0-04`、`w1-02`、`w3-02`、`w3-03`、`w3-05` 均已合入 `develop`；记录 `_fork_schema_version` 水位、`w1-02` 能力目录、`w3-02` 的 `register_redaction_pattern()` 签名
  - 验证：`git log --oneline -1`；`rg -n "def register_redaction_pattern" src/octop/infra/utils/log_redaction.py`；`rg -n "def assemble_agent_middleware" src/octop/infra/agents/middleware_registry.py`
  - _需求：无（前置条件）_

- [ ] 2. `infra/utils/pii_cn.py`：中文 PII 检测与金融口径掩码
  - 改动：新增 `detect_cn_pii`/`apply_cn_mask`（身份证 GB 11643、银行卡 Luhn+长度、手机号边界锚定、客户号可配正则；掩码后长度与原串一致；只依赖 stdlib）
  - 验证：先写会失败的 `tests/unit/security/test_cn_detectors.py`、`tests/unit/security/test_mask.py`（含长度不变与"不等于上游默认分支"断言）再实现；`uv run pytest tests/unit/security/test_cn_detectors.py tests/unit/security/test_mask.py -q`
  - _需求：1.1, 1.2, 1.3, 1.4_

- [ ] 3. 策略模型与独立持久化
  - 改动：`content/models.py`（`ContentSecurityPolicy`/`ScanRequest`/`ScanVerdict`/`CnPiiMatch`）；`content_settings_store.py`（settings 表 `key='content_security'`）；接线到 agent manager 的 `__init__`/`replace_persistence`/`boot`/属性四处；`security/__init__.py` 追加导出
  - 验证：新增/扩展测试断言往返不丢字段、不挂在上游 `SecurityPolicy.pii` 段下；`uv run pytest tests/unit/test_security_settings.py -k content -q`
  - _需求：3.4, 4.2_

- [ ] 4. 可插拔 Provider：本地规则 + HTTP 适配器
  - 改动：`content/providers.py`（注册表，照 `captcha/providers.py` 形态）、`local_rules.py`、`http_provider.py`（超时/熔断/`fail_open`\|`fail_closed`，凭据走 `w3-05` 的 `secret_repo`）、`rules_store.py`（照 `ToolGuardRulesStore`）、`rules/default_rules.yaml`；同批改 `pyproject.toml` `include` 加 `*.yaml`
  - 验证：先写 `tests/unit/security/test_content_providers.py`、`tests/unit/test_bundled_content_rules_layout.py` 再实现；`uv run pytest tests/unit/security/test_content_providers.py tests/unit/test_bundled_content_rules_layout.py -q`
  - _需求：3.1, 3.2, 3.3, 3.4_

- [ ] 5. 流式增量脱敏器与门面服务
  - 改动：`content/stream_redactor.py`（per-call lookback，state_snapshot 按消息 id 增量）、`content/detectors_cn.py`、`content/mask.py`、`content/service.py`（`scan_input`/`redact_value`/`redact_messages` dict+消息对象双分支/`redact_stream`/`audit`）
  - 验证：先写 `tests/unit/security/test_stream_redactor.py`（跨分片、lookback 边界、flush、block 抛 `OctopError`、`enabled=false` identity、state_snapshot 增量线性）后实现；`uv run pytest tests/unit/security/test_stream_redactor.py -q`
  - _需求：2.1, 2.2, 2.5, 2.6_

- [ ] 6. 接入 `w1-02` 能力开关与中间件注册式装配
  - 改动：`infra/agents/middleware/content_security.py`（四钩子 `before_model`/`abefore_model`/`after_model`/`aafter_model`）；经 `assemble_agent_middleware`/`FORK_AGENT_MIDDLEWARE` 接入，不直改上游列表；新增 `save_content_security()`，变更后调 `reload_harness_agents()`（无上游热设接口，与 `set_security_policy` 有意不对称）
  - 验证：先写 `tests/unit/agents/test_content_security_middleware.py`（四钩子均执行、关闭时不入链、相对顺序断言而非绝对链尾）后实现；`uv run pytest tests/unit/agents/test_content_security_middleware.py -q`
  - _需求：2.6, 4.1, 4.3, 4.4_

- [ ] 7. 六条路径的旁路补漏
  - 改动：用户输入轨迹写入（进模型调用前，不在流下游）先过 `redact_value()`；历史投影 `seed_messages` 回退路径先脱敏 `request['messages']`；工具结果二次富化补一次轻量脱敏；三个直连模型旁路各自在调用前后补扫描/脱敏，不塞进共享辅助函数
  - 验证：先写 `tests/unit/trajectory/test_redacted_payload.py`（tool_result 与用户输入轨迹均不含明文）、`tests/unit/gateway/test_history_redaction.py`（正常与阻断回退路径均已脱敏）、`tests/unit/gateway/test_stream_redaction.py`（三消费者一致性 + "无其它 `.stream`/`.resume_hitl`/`.call` 调用点"守卫）后实现；`uv run pytest tests/unit/trajectory/test_redacted_payload.py tests/unit/gateway/test_history_redaction.py tests/unit/gateway/test_stream_redaction.py -q`
  - _需求：2.2, 2.3, 2.4_

- [ ] 8. 向 `w3-02` 注册日志脱敏正则（不新建 Formatter）
  - 改动：在 `server.py`（或 `w3-02` 指定注入点）调用 `register_redaction_pattern()`，把 `pii_cn.py` 的检测正则注册进 `w3-02` 的日志 Formatter；不新增 Formatter/Filter 类
  - 验证：`uv run pytest tests/unit/infra/test_log_redaction.py -k content -q`（无扩展点则在该文件旁新增断言注册生效的用例）
  - _需求：2.4（属交接说明，仅确认注册调用生效）_

- [ ] 9. ErrorCode 与 i18n（overlay）
  - 改动：`infra/errors.py` 同批新增 `CONTENT_BLOCKED`/`CONTENT_SECURITY_UNAVAILABLE` 与 `_DEFAULT_STATUS`（403/503）；`i18n/domains/content_security.py` 新增并登记进 `domains/__init__.py`；`errors.*`/`apiErrors.*` 键名登记进四份 JSON；其余文案写入 `w0-04` 的 intranet overlay，不写上游 JSON 非 overlay 段
  - 验证：`uv run pytest tests/unit/i18n -q`
  - _需求：6.1, 6.2, 6.3, 6.4_

- [ ] 10. 数据库：内容安全事件表与 API
  - 改动：`forkNNN_content_security_events.sql`+`.pg.sql`（合入前按 `w0-01` 水位表定号）；`infra/db/repos/content_security_events.py`；`infra/db/services.py` 四处接线（import/`RepoBundle`/`from_pool`/`SharedServices` 属性）；`api/routers/security.py` 新增 `GET/PUT /content`、`GET/PUT /content/rules/raw`、`POST /content/rules/reset`、`GET /content/providers`、`POST /content/test`，`require_permission('security')`，写操作调 `AuditRepo.write(action='security.content.*')`
  - 验证：先写 `tests/integration/test_content_security_api.py`（往返一致、非法 YAML 400 不落盘、审计写入、无权限 403）后实现；`uv run pytest tests/integration/test_content_security_api.py -q`
  - _需求：5.1, 5.2, 5.3, 5.4, 5.5_

- [ ] 11. 前端面板
  - 改动：`dashboard/src/api/modules/security.ts` 扩展现有 `securityApi`（不新建平行导出）；新增 `ContentSecurityPanel.tsx`（自包含 load/save，走 `/content` 端点，不接入父页面保存流程）；`Settings/Security/index.tsx` 登记新 tab；`permissions.ts` tab 权限映射加一行
  - 验证：`cd dashboard && npx tsc -b && npm run lint`；如新增 `ContentSecurityPanel.test.tsx` 则加 `npm test`（非 CI 门禁，仅本地/pre-commit）
  - _需求：5.1, 5.2, 5.4_

- [ ] 12. 收尾：全绿回归与文档
  - 改动：更新 `CHANGELOG-intranet.md`；更新 `docs/api-intranet.md`（新增 `/content*` 端点）；新增 `docs/content-security.md`（六条路径图、规则语法、Provider 契约、已知限制）
  - 验证：`make all`；`cd dashboard && npx tsc -b && npm run lint`（有前端 vitest 用例则加 `npm run test`）；`uv run pytest tests/unit/i18n -q`
  - _需求：全部 1.1-6.4_
