# 设计文档：审计防篡改与外发

> spec：`p2-03-audit-tamper-proof` ｜ 波次：二期 ｜ 基线：`757fd12` ｜ 预估：26 人日
> 前置：`w3-02-audit-baseline`、`w3-03-authorization-foundation`、`w0-01-fork-migration-namespace` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 概述

在 `w3-02` 冻结的 `audit_log` 字段集与既有 `AuditContext`/syslog 外发之上，追加四块能力：哈希链完整性、库层禁改删触发器、Kafka 第二外发通道、导出与保留归档，并把新增的只读/配置端点接到 `w3-03` 交付的 `audit_admin` 角色。二期启动时一期已落地，故本设计只钉死"做什么、按什么顺序做、边界在哪"，具体文件行号以实施时重新核实为准。

## 现状（基线 `757fd12` 核实）

- `audit_log` 建表仅六列，无哈希链字段、无触发器、无索引之外的治理：`src/octop/infra/db/migrations/001_initial.sql`（≈L231-238，`CREATE TABLE audit_log (id, ts, actor, action, target, payload)`，四个索引 ≈L239-242）。
- 唯一的写入入口是 `AuditRepo.write()`；`src/octop/infra/db/repos/audit.py` 现有 `class AuditRow`（≈L15）、`write()`（≈L39）、`query()`（≈L81）、`delete_before()`（≈L109，全仓零调用方，是死代码，保留径直复用）。
- `PERMISSIONS`/`effective_permissions` 在 `src/octop/infra/users/permissions.py`（`PERMISSIONS` 字典起始 ≈L50、`user_has_permission` ≈L225、`effective_permissions` ≈L251），基线上尚无 `audit_admin` 键，也无 `ADMIN_EXCLUSIVE_PERMISSIONS` 概念——两者由 `w3-03` 交付，本 spec 实施时以 `w3-03` 落地后的实际签名为准。
- `_DEFAULT_STATUS` 位于 `src/octop/infra/errors.py`（≈L115），`OctopError` 对未登记的码做无保护字典下标（`__post_init__` 附近 ≈L227）。
- 基线迁移最新为 `015_sso_provider_kind.sql`/`.pg.sql`；`016` 起归上游占用，fork 侧改动一律不占用该数字号（详见"数据模型"）。
- SQLite 触发器技术可行性已由源分析独立复现：`CREATE TRIGGER ... BEGIN SELECT RAISE(ABORT, ...); END;` 经 `executescript` 可正确建立，`UPDATE`/`DELETE` 均被拦截并抛 `sqlite3.IntegrityError`；窗口守卫 `WHEN (SELECT purge_open FROM audit_maintenance WHERE k=1)=0` 开合有效。这是本设计"先回填、后建触发器"顺序约束的直接依据。

## 方案

1. **哈希链**：`infra/audit/chain.py` 提供 canonical 序列化与可插拔哈希算法（默认 SHA-256，预留 SM3 接口）；`AuditRepo.write()` 在写入事务内计算并串联 `prev_hash`/`row_hash`；新增 `verify_chain()`、`iter_range()`。
2. **触发器**：随 fork 迁移新增列与辅助表，但**迁移文件本身不建触发器**；触发器由一个幂等助手在"建表加列 → 分批链回填 → 建触发器"三段顺序的最后一段创建，避免触发器抢在回填之前生效导致 `UPDATE` 全部失败。
3. **Kafka 外发**：新增独立通道 `infra/audit/kafka_forwarder.py`，复用/对齐 `w3-02` 已建立的 spool-and-retry 模式（后台线程、指数退避、溢出丢弃入链），不重复实现 syslog。
4. **导出与归档**：`infra/audit/export.py`（流式 XLSX/CSV + 链校验摘要页）、`infra/audit/retention.py`（归档段签名、cron 系统作业、维护窗口）。
5. **只读视图**：新增/扩展审计路由，全部挂 `require_permission("audit_admin")`（该键由 `w3-03` 定义），不新增权限模型逻辑。

## 组件与接口

| 文件 | 动作 | 要点 |
|---|---|---|
| `src/octop/infra/db/migrations/forkNNN_audit_chain.sql` + `.pg.sql` | 新增（fork 迁移，号不预占） | 仅建表加列：`audit_log` 加 `prev_hash TEXT`/`row_hash TEXT`；新建 `audit_chain_head`、`audit_maintenance`；**不建触发器**。按 `w0-01` 交付的 fork 迁移 runner 接入方式登记（实施时以 `w0-01` 落地后的 API 为准）。 |
| `src/octop/infra/audit/chain.py` | 新增 | `HashAlgo` 协议 + `sha256` 实现；`canonical_row()`；`verify_sequence(rows) -> (ok, first_broken_id)`。 |
| `src/octop/infra/audit/kafka_forwarder.py` | 新增 | Kafka producer 封装、spool 消费、指数退避、溢出策略、`start()`/`stop()`。禁止在写请求路径做网络 IO。 |
| `src/octop/infra/audit/retention.py` | 新增 | 归档段写盘（`jsonl.gz` + `.sha256`）、维护窗口开合、`install_audit_retention_job(cron_manager, server)` 注册系统作业。 |
| `src/octop/infra/audit/export.py` | 新增 | XLSX（openpyxl，零新依赖）/CSV 流式导出，分批游标，链校验摘要页。 |
| `src/octop/infra/db/repos/audit.py` | 修改 | `AuditRow` 加 `prev_hash`/`row_hash`；`write()` 入链；新增 `verify_chain()`/`iter_range()`；`delete_before()` 改为仅维护窗口内可调用。 |
| `src/octop/infra/utils/paths.py` | 修改 | 新增 `audit_archive_dir` property（遵循该文件既有 property 约定，不用字面量路径）。 |
| `src/octop/api/routers/audit.py` | 新增或扩展（视 `w3-02` 是否已建同名路由，实施时先 `rg` 确认） | `GET /verify`、`GET /export`、`GET /archive`、`GET|PUT /kafka-config`、`GET /kafka-status`，全部挂 `require_permission("audit_admin")`（PUT 额外校验）。 |
| `src/octop/config.py` | 修改 | 新增 `AuditConfig`（见"配置"）。 |
| `dashboard/src/pages/Settings/Security/AuditForwardPanel.tsx`（或与 `w3-02` 的等价面板合并） | 新增/扩展 | Kafka 外发状态、导出按钮、链校验横幅。挂 `audit_admin` 门控，复用 `w3-03` 交付的权限判定，不新增前端短路逻辑。 |

## 数据模型

fork 迁移 `forkNNN_audit_chain`（编号在合入前由 `w0-01` 的 fork 迁移空间分配，不预占）：

- `audit_log` 加列：`prev_hash TEXT`、`row_hash TEXT`。
- `audit_chain_head(k INTEGER PRIMARY KEY CHECK(k=1), last_id INTEGER, last_hash TEXT)`。
- `audit_maintenance(k INTEGER PRIMARY KEY CHECK(k=1), purge_open INTEGER NOT NULL DEFAULT 0)`。
- 若 Kafka spool 不能复用 `w3-02` 已有的外发队列表结构，另加 `audit_kafka_spool(id, audit_id, payload, attempts, next_attempt_ts)`（实施时先确认 `w3-02` 的 spool 表是否可通用，能复用则不新建）。
- 回填：存量 `audit_log` 行按批次（建议 5000 行/批，避免 `SqlitePool` 单连接长事务阻塞全部请求）计算并写入 `prev_hash`/`row_hash`，**必须先于**触发器创建完成；回填仅证明"回填之后未被篡改"，不能追溯回填之前的完整性，需写入合规文档。
- 触发器创建、`_fork_schema_version` 水位更新均由 `w0-01` 的 fork 迁移机制驱动，本 spec 不直接改动上游 `infra/db/migrate.py`。

## 配置

在 `w3-02` 已建立的 `AuditConfig`（`src/octop/config.py`）上追加归档与 Kafka 字段。`retention_days` 及其 ≥180 下限校验由 `w3-02` 定义，本 spec 复用、不重复声明。新增字段同样走三触点：

1. `AuditConfig` dataclass 追加下列字段（`audit` 配置段本身由 `w3-02` 建立）。
2. env 覆盖块新增 `OCTOP_AUDIT_*`（`ARCHIVE_ENABLED`、`ARCHIVE_DIR`、`HASH_ALGO`、`KAFKA_ENABLED`、`KAFKA_BOOTSTRAP_SERVERS`、`KAFKA_TOPIC`、`KAFKA_TLS`、`SPOOL_MAX`）。
3. `return OctopConfig(...)` 逐字段构造处补上 `audit=...`。

字段：`archive_enabled: bool = True`、`archive_dir: str = ""`、`hash_algo: str = "sha256"`、`kafka_enabled: bool = False`、`kafka_bootstrap_servers: str = ""`、`kafka_topic: str = ""`、`kafka_tls: bool = False`、`spool_max: int = 100000`。启动时 `retention_days < 180` 且 `allow_short_retention=False` 应拒绝启动。

## 错误处理

不新增 `ErrorCode`：403（无 `audit_admin`）与配置校验失败复用既有的权限拒绝码与配置校验码（实施时先 `rg _DEFAULT_STATUS` 确认可复用的现成码，能复用就不新增）。若确需新增（例如链校验失败的专用响应码），追加到 `ErrorCode` 枚举末尾，并同批在 `src/octop/infra/errors.py` 的 `_DEFAULT_STATUS`（≈L115）末尾登记，同时补齐后端 en/zh 与 dashboard `apiErrors` 四处——漏登记 `_DEFAULT_STATUS` 会导致 `OctopError` 构造期 `KeyError`（非降级，是崩）。

## 安全考虑

- 触发器不是防篡改的充分条件：应用自身连接可 `DROP TRIGGER` 后放行 `DELETE`；SQLite `backup` API 的整库覆盖式恢复按页替换、完全绕过触发器；PostgreSQL 的 `REVOKE ... FROM PUBLIC` 对表 owner 无效（Octop 连接角色通常即 owner），不得作为第二道防线写入合规材料。真正的防篡改保证来自哈希链（可检测）+ 外发到独立系统（可比对）；`docs/audit-tamper-evidence.md` 必须写明该边界。
- 恢复旧备份后必须强制触发一次全链校验，并把结果写入审计；归档目录是否纳入系统备份范围需在实施前确认（不落在 `BackupConfig` 现有 `include_*` 开关内）。
- `audit_admin` 只读视图完全依赖 `w3-03` 的权限判定收口与自授权守卫；本 spec 不重复实现，只在新路由上正确声明权限键，并把该文件加入既有的权限门控覆盖清单。

## 测试策略

- 单测（哈希链、触发器时序、Kafka 外发不阻塞、保留期校验）：
  `uv run pytest tests/unit/db/test_audit_chain.py -x -q`
  `uv run pytest tests/unit/audit -x -q`
- 集成（权限门控、维护窗口、PostgreSQL 触发器与迁移切分，后者依赖 `w0-02` 的 PG CI 门禁，本地跑需设 `OCTOP_TEST_DATABASE_URL`）：
  `uv run pytest tests/integration -k audit -x -q`
- i18n（若新增 `audit_export`/Kafka 面板文案键）：
  `uv run pytest tests/unit/i18n -q`
- 前端（面板改动后）：
  `cd dashboard && npx tsc -b`
- 端到端：`make all`（`format-all` + `lint` + `typecheck` + `test`），Linux 与 Windows 两条 CI 均须全绿。

## 与其他 spec 的交接

- **依赖 `w3-02`**：`audit_log` 冻结字段集、`AuditContext`、syslog 外发基础设施、审计事件覆盖面。本 spec 的哈希链 canonical 序列化建立在其冻结结果之上；Kafka 外发对齐其 spool 模式而不重建。
- **依赖 `w3-03`**：`audit_admin` 权限键、`ADMIN_EXCLUSIVE_PERMISSIONS`、`effective_permissions` 排除逻辑、`PUT /api/users/{id}` 自授权守卫、前端 `userCan`/`userCanAny` 例外短路——这些是本 spec"审计管理员只读视图"的前提，全部只消费不重做。
- **依赖 `w0-01`**：fork 迁移空间与 `_fork_schema_version` runner；本 spec 的迁移文件按其约定命名 `forkNNN_` 并接入其 runner，不改动上游 `infra/db/migrate.py`。
- **看似相关但归别处**：`ACTION_OPTIONS`/`adminAudit.actions` 动作标签补齐、`AuditLogPanel.tsx` 服务端分页与基础字段展示——归 `w3-02`（其审计面板范围）；权限模型短路修复——归 `w3-03`；CI 加 PostgreSQL service——归 `w0-02`（本 spec 假设已合入，仅消费）。
- **交付给下游**：`p2-02`（国密落地时替换 `chain.py` 的哈希算法实现，接口已预留）。

## 风险与回滚

- 高风险：回填与建触发器顺序颠倒会导致存量库升级第一步即失败（触发器建好后任何 `UPDATE` 都会抛错，而哈希只能在 Python 侧计算），本设计已将其钉死为迁移文件不建触发器、幂等助手最后一步才建。
- 中风险：Kafka 若需要新增二进制依赖，需先完成离线依赖镜像与信创架构 wheel 可用性验证（归 `w2-01` 的离线构建约束），实施前需确认对应 Kafka 客户端库已入行内私服。
- 中风险：170~180 天量级在线保留无容量上限，需与行方确认实际事件速率后调整分批策略。
- 回滚：fork 迁移可通过 `w0-01` 的 runner 提供的回滚路径处理（若存在）；触发器可显式 `DROP TRIGGER` 临时禁用（不影响历史哈希链，仅暂停新的库层拦截），链校验作为独立可随时重跑的只读操作，不依赖触发器状态。

## 待行方确认

- `D8`（国密与密评）：默认一期信封保留算法标识 `suite_id`，本 spec 的 `hash_algo` 配置同理只做标识预留，SM3 落地归 `p2-02`。
- 归档目录是否纳入系统备份 `include_*` 范围：steering 未给默认假设，需实施前与行方/架构确认（非 D 编号问题，按"待行方拍板项"补充处理）。
