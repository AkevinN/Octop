# 实施计划：审计防篡改与外发

> spec：`p2-03-audit-tamper-proof` ｜ 波次：二期 ｜ 基线：`757fd12` ｜ 预估：26 人日
> 前置：`w3-02-audit-baseline`、`w3-03-authorization-foundation`、`w0-01-fork-migration-namespace` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

每个顶层任务完成后可独立提交；提交前运行任务内的验证命令。二期任务，实施时代码已因一期落地而变化，路径与符号以当时的 `rg` 结果为准；本文件不写具体行号。

- [ ] 1. 确认前置 spec 已合入并记录基线
  - 改动：无代码改动。用 `rg` 确认 `w3-02` 已冻结 `audit_log` 字段集与 syslog 外发、`w3-03` 已交付 `audit_admin` 权限键与 `ADMIN_EXCLUSIVE_PERMISSIONS`、`w0-01` 已交付 fork 迁移 runner；把三者的实际文件路径与关键符号记入本 spec 的实施笔记。
  - 验证：`rg -n "audit_admin" src/octop/infra/users/permissions.py`、`rg -n "fork" src/octop/infra/db/migrate.py`（或 `w0-01` 落地后的新模块路径）均有命中。
  - _需求：全部（前置确认）_

- [ ] 2. 哈希链算法与 canonical 序列化
  - 改动：新增 `src/octop/infra/audit/chain.py`（`HashAlgo` 协议、`sha256` 实现、`canonical_row()`、`verify_sequence()`）。
  - 验证：`uv run pytest tests/unit/audit/test_chain.py -x -q`（先写失败用例：篡改任一字段应使 `verify_sequence` 定位到该行）。
  - _需求：1.1, 1.2, 1.4_

- [ ] 3. fork 迁移：哈希链列与辅助表
  - 改动：新增 `src/octop/infra/db/migrations/forkNNN_audit_chain.sql` 与 `.pg.sql`（`audit_log` 加 `prev_hash`/`row_hash`，新建 `audit_chain_head`、`audit_maintenance`；不建触发器），按当时 `w0-01` 的 fork runner 接入方式注册。
  - 验证：`uv run pytest tests/unit/db -k fork_audit_chain -x -q`；本地 SQLite 库执行迁移后 `PRAGMA table_info(audit_log)` 含新列。
  - _需求：1.3_

- [ ] 4. AuditRepo：入链、校验、回填顺序
  - 改动：`src/octop/infra/db/repos/audit.py` 的 `write()` 入链、新增 `verify_chain()`/`iter_range()`；新增回填幂等助手，严格按"建表加列 → 分批回填 → 建触发器"顺序执行（触发器创建放最后一步）。
  - 验证：`uv run pytest tests/unit/db/test_audit_chain.py -x -q`（先写会失败的用例：触发器建好后回填必须已完成，否则回填步骤本身应能检测并报错，而不是让 `UPDATE` 抛出未处理异常）。
  - _需求：1.1, 1.2, 1.3, 1.4_

- [ ] 5. 库层禁改删触发器（SQLite + PostgreSQL）
  - 改动：在上一任务的幂等助手最后一步创建 `audit_log_no_update`/`audit_log_no_delete`（SQLite）与等价 `plpgsql` 函数+触发器（PostgreSQL，函数体单行书写）；维护窗口守卫读 `audit_maintenance.purge_open`。
  - 验证：`uv run pytest tests/unit/db/test_audit_chain.py -k trigger -x -q`；`uv run pytest tests/integration -k audit_postgresql -x -q`（需 `OCTOP_TEST_DATABASE_URL`，依赖 `w0-02` 的 PG 门禁）。
  - _需求：2.1, 2.2, 2.3_

- [ ] 6. Kafka 外发通道
  - 改动：新增 `src/octop/infra/audit/kafka_forwarder.py`（producer 封装、spool 消费、指数退避、溢出丢弃入链、独立后台线程、`start()`/`stop()`）；对齐 `w3-02` 已有的 spool 模式，能复用其表结构则不新建。
  - 验证：`uv run pytest tests/unit/audit/test_kafka_forwarder.py -x -q`（先写失败用例：目标不可达时 200 次 `write()` 全部在 1 秒内返回且不抛异常；仅用 `127.0.0.1` 临时端口，不碰 Unix socket）。
  - _需求：3.1, 3.2, 3.3, 3.4, 6.1_

- [ ] 7. 保留期与归档
  - 改动：新增 `src/octop/infra/audit/retention.py`（归档段 `jsonl.gz` + `.sha256`、维护窗口开合、`install_audit_retention_job`）；`src/octop/infra/utils/paths.py` 新增 `audit_archive_dir` property；`src/octop/config.py` 在 `w3-02` 的 `AuditConfig` 上追加归档与 Kafka 字段（三触点）。
  - 验证：`uv run pytest tests/unit/audit/test_retention.py -x -q`（`monkeypatch.setenv("OCTOP_HOME", str(tmp_path))` + `Path` 拼接）；`uv run pytest tests/unit/test_config.py -k audit -x -q`（新增的归档与 Kafka 字段经三触点生效；`retention_days` 的下限校验沿用 w3-02，不在本 spec 重复测试）。
  - _需求：4.2, 4.3, 6.2_

- [ ] 8. 导出
  - 改动：新增 `src/octop/infra/audit/export.py`（XLSX/CSV 流式导出，分批游标，链校验摘要页）。
  - 验证：`uv run pytest tests/unit/audit/test_export.py -x -q`（大量行场景下断言不整表读入内存，例如用可数迭代器 mock 校验批次调用次数）。
  - _需求：4.1_

- [ ] 9. API 路由与权限门控
  - 改动：新增或扩展 `src/octop/api/routers/audit.py`（`GET /verify`、`GET /export`、`GET /archive`、`GET|PUT /kafka-config`、`GET /kafka-status`），全部挂 `require_permission("audit_admin")`；挂载进 `src/octop/api/app.py`；把该路由文件加入 `tests/unit/api/test_acl_gate_coverage.py` 的 `GATED_FILES`。
  - 验证：`uv run pytest tests/integration -k audit_readonly -x -q`（先写失败用例：`audit_admin` 读 200、系统管理员未授 `audit_admin` 读 403）；`uv run pytest tests/unit/api/test_acl_gate_coverage.py -x -q`。
  - _需求：5.1, 5.2, 5.3_

- [ ] 10. 前端：Kafka 外发面板与导出/校验入口
  - 改动：新增或扩展 `dashboard/src/pages/Settings/Security/AuditForwardPanel.tsx`（Kafka 目标、TLS、spool 深度、最后成功时间）与导出按钮、链校验横幅；新增所需 i18n 键（后端 `audit_export.*`、前端对应命名空间），后端 en/zh 成对、dashboard en/zh 成对，不删既有键，新增文案按 steering 走 intranet overlay（若 `w0-04` 已交付该机制）或与既有 locale 文件同结构追加。
  - 验证：`cd dashboard && npx tsc -b`；`uv run pytest tests/unit/i18n -q`。
  - _需求：4.1, 5.1, 6.3_

- [ ] 11. 收尾：全绿与文档
  - 改动：更新 `CHANGELOG-intranet.md`；若有 API 变更，更新 `docs/api-intranet.md`；新增 `docs/audit-tamper-evidence.md`（哈希算法与 canonical 定义、能防什么不能防什么、外发可靠性模型、保留归档策略、现场校验步骤、备份恢复的补偿控制）。
  - 验证：`make all` 全绿；`cd dashboard && npx tsc -b && npm run lint`；`uv run pytest -m "not live"` 全量跑一遍确认无既有用例回归。
  - _需求：6.3_
