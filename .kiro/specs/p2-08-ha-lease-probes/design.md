# 设计文档：单活租约与探针

> spec：`p2-08-ha-lease-probes` ｜ 波次：二期 ｜ 基线：`757fd12` ｜ 预估：18 人日
> 前置：`w2-03-database-adaptation` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 概述

在 `w2-03` 已完成 PG 方言收口、关闭运行期 DDL 的基础上，本 spec 让同一数据库上的两个 Octop 进程通过数据库租约分出 `active`/`standby` 角色，拆分存活/就绪探针供负载均衡摘流，并在停机时排空在途对话。设计以 `S12-database-ha.json` 为主干，租约原语吸收 `S15-ops-delivery.json` 的 fencing-token 方案（比 `pg_try_advisory_lock` 更不受连接池回收影响）。

## 现状（基线 `757fd12` 已核实）

- `src/octop/infra/server.py`：`user_manager` 是 `app_runtime.user_manager` 的只读属性代理（≈L257-260，`return self.app_runtime.user_manager if self.app_runtime else None`）；`database_bound`（≈L278）依赖 `app_runtime` 非空；`start()`（≈L281）与 `bind_control_plane()`（≈L334）都会走到 `_boot_runtime()`（≈L362）；`stop()`（≈L522）目前直接关闭，不等待在途请求。
- `src/octop/api/middleware/setup_lockdown.py:36`：`if server.user_manager is None or server.user_manager.count() == 0` 对每个非豁免 `/api/*` 请求同步查库，且把 `user_manager is None` 直接等同于"未装机"。
- `src/octop/api/routers/health.py`（现 28 行）：唯一的 `GET ""` 路由同步调用 `server.user_manager.count()` 与 `server.app_runtime.agent_registry.list_rows()`，数据库故障时会挂在这两个调用上；没有 `/live`、`/ready` 子路由。
- `src/octop/infra/agents/manager.py`：`_active_invocations` 计数器（≈L352）已由 `_begin_invocation`/`_end_invocation`/`_track_invocation`（≈L1026-1046）在 `stream`（≈L1048）、`call`（≈L1060）、`resume_hitl`（≈L1073）三处维护；`shutdown()`（≈L452）不等待该计数归零。
- `src/octop/infra/db/migrate.py::_discover`（≈L39）对重复版本号直接 `raise RuntimeError("Duplicate migration version ...")`；当前最新迁移为 `015_sso_provider_kind`。
- `src/octop/launch.py`：三处 `uvicorn.Config` 构造（≈L106/117/135，TLS 双端口模式下会有两个 Server 实例）与 `finally` 块（≈L149，`await srv.stop()` 在 ≈L151）目前不等待排空。
- `src/octop/infra/cron/manager.py`：`AsyncIOScheduler`（≈L65）在 `boot()`（≈L75）里无条件 `start()`；`schedule_system_job`/`unschedule_system_job`（≈L290/302）已存在，可供角色切换时复用。
- `src/octop/infra/errors.py`：`ErrorCode`（L13）与 `_DEFAULT_STATUS`（L115）两处需成对追加新码。

以上锚点均以关键字/符号在仓库中核实过存在；具体行号会随一期（Wave 1-4）改动漂移，实施时以 `rg` 重新定位为准，不依赖本文档的行号。

## 方案

1. **租约原语**：新增 `src/octop/infra/ha/lease.py`（吸收 S15 的模块路径与 fencing-token 设计，弃用 S12 的 `pg_try_advisory_lock` 方案，理由见下）。PG 系数据库新建 `runtime_lease` 表，持有者写入 `owner`/`fencing_token`/`heartbeat_at`/`expires_at`；`acquire()`/`renew()`/`release()` 走一条独立连接的 `UPDATE ... WHERE expires_at < now() OR owner = $1` 条件更新 + 心跳续租，不依赖会话级 advisory lock（该锁在 `psycopg_pool` 回收连接时会静默释放，且部分信创库版本不支持）。SQLite 恒返回 `standalone` 角色，不做跨进程互斥。
2. **控制面/数据面拆分**：把 `_boot_runtime()` 拆成两段——控制面段（`UserManager`、`TrajectoryService`、`AppRuntime` 组装）在 `start()`/`bind_control_plane()` 里无条件执行；数据面段（`AgentManager` 启动、`Gateway.boot`、`CronManager.boot`、`ProactiveScheduler`）只在拿到租约（`active`）时执行。`AppRuntime` 增加 `activated: bool` 标记，供 `database_bound`、探针、`setup_lockdown` 读取，避免"`app_runtime is None` ⇒ 未装机"这条旧短路逻辑在 standby 下被误触发。
3. **探针拆分**：`health.py` 新增 `GET /live`（只返回 `ok`+`started_at`，不碰数据库）与 `GET /ready`（`db_offload` 里跑 `SELECT 1` + 查租约角色，`role=active` 时 200、`role=standby` 或 `SELECT 1` 失败时 503）；保留 `GET ""` 原有字段与状态码不变。
4. **停机排空**：`AgentManager` 新增 `begin_drain()`（置位后 `stream`/`call`/`resume_hitl` 直接拒绝新 turn）与 `await drain(timeout)`（等待 `_active_invocations` 与在途 history backfill 归零）；`launch.py` 在 `finally` 块 `await srv.stop()` 之前先 `await srv.begin_drain_and_wait(timeout)`，`timeout` 取 `OCTOP_DRAIN_TIMEOUT_SECONDS`；三处 `uvicorn.Config` 都传 `timeout_graceful_shutdown`。
5. **standby 后台任务门控**：`CronManager.boot()` 与自动备份注册点只在 `active` 角色执行；角色由 standby 切换为 active 时补跑 `reload_from_db` 等价路径重新装载任务。

## 组件与接口

| 文件 | 改动 |
|---|---|
| `src/octop/infra/ha/lease.py`（新增） | `acquire()`/`renew()`/`release()`/`role: Literal["active","standby","standalone"]`，PG 用 `runtime_lease` 表 + fencing token，SQLite 恒 `standalone` |
| `src/octop/infra/db/migrations/forkNNN_runtime_lease.sql` / `.pg.sql`（新增，号不预占） | 新建 `runtime_lease` 表：`owner TEXT`、`fencing_token BIGINT`、`heartbeat_at`、`expires_at` |
| `src/octop/infra/server.py` | `_boot_runtime` 拆控制面/数据面两段；`start()`/`bind_control_plane()` 在迁移后、数据面段之前调用 `lease.acquire()`；`stop()` 排空后释放租约；`AppRuntime.activated` 标记 |
| `src/octop/api/middleware/setup_lockdown.py` | L36 判据从 `user_manager is None` 改为读 `server.app_runtime is not None`（控制面已组装即可放行），不再与 standby 状态耦合 |
| `src/octop/api/routers/health.py` | 新增 `/live`、`/ready`；`/ready` 用 `db_offload` 跑 `SELECT 1` + 读 `lease.role` |
| `src/octop/infra/agents/manager.py` | 新增 `begin_drain()`/`drain(timeout)`，`stream`/`call`/`resume_hitl` 增加排空态拒绝分支 |
| `src/octop/launch.py` | `finally` 块调用顺序：`begin_drain_and_wait` → `srv.stop()`；三处 `uvicorn.Config` 加 `timeout_graceful_shutdown` |
| `src/octop/infra/cron/manager.py` | `boot()` 增加角色判断；新增角色切换后重装载入口 |
| `src/octop/infra/backup/auto.py` | 自动备份 job 仅 `active` 角色注册（注册/注销点以实施时 `rg AUTO_BACKUP_JOB_ID` 重新定位） |
| `src/octop/infra/errors.py` | 追加 `ErrorCode.INSTANCE_STANDBY`、`ErrorCode.LEASE_UNAVAILABLE`（或与 `w2-03` 已加的 `DATABASE_UNAVAILABLE` 复用，实施时先查是否已存在再决定是否新增） |

## 数据模型

`forkNNN_runtime_lease`（号不预占，合入 fork 主干时按 `.kiro/steering` §1.1 取下一个可用号）：

```sql
CREATE TABLE runtime_lease (
    id INTEGER PRIMARY KEY,            -- 单行租约，固定 id=1
    owner TEXT NOT NULL,
    fencing_token INTEGER NOT NULL,
    heartbeat_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
```
PG 版本对应把 `fencing_token` 设为 `BIGINT`、`heartbeat_at`/`expires_at` 设为 `TIMESTAMPTZ`，并遵守 ADR 002 硬规则（不得含 `CREATE EXTENSION`）。字段无需回填，新表直接建空。

## 配置

| 键 | 默认值 | 说明 |
|---|---|---|
| `OCTOP_DRAIN_TIMEOUT_SECONDS` | 60 | 排空最长等待秒数，超时后强制继续关闭流程 |
| `OCTOP_LEASE_TTL_SECONDS` | 待实施时定（建议 15） | 租约过期时长，需与心跳周期配套 |

每个新配置键须在 `src/octop/config.py` 补齐三触点：`OctopConfig` dataclass 字段、env 覆盖块、`return OctopConfig(...)` 逐字段构造；实施时补一条单测校验第三触点（`w1-02` 已把此项做成通用门禁的话直接复用）。

## 错误处理

新增 `ErrorCode` 成员前先 `rg` 确认 `w2-03`/`w1-01` 等前置 spec 是否已注册同语义的码（如 `DATABASE_UNAVAILABLE`）可复用。若需新增：

| 码 | `_DEFAULT_STATUS` | 触发场景 |
|---|---|---|
| `INSTANCE_STANDBY` | 503 | standby 角色拒绝写操作 |
| `LEASE_UNAVAILABLE` | 503 | 租约获取/续约失败 |

新增码必须同批完成：`ErrorCode` 枚举追加到末尾、`_DEFAULT_STATUS` 追加到末尾、`src/octop/i18n/en.json`+`zh.json` 的 `errors` 命名空间、`dashboard/src/locales/intranet/{en,zh}.json`（overlay，由 `w0-04` 的合并测试兜底相等性）。漏登记 `_DEFAULT_STATUS` 会让 `OctopError.__post_init__` 无保护字典下标直接 `KeyError`。

## 安全考虑

- `/api/health/live`、`/api/health/ready` 走既有 `_JWT_EXEMPT_PREFIXES`/`_OPEN_PREFIXES` 前缀自动豁免，不新增鉴权面；实施时补测试锁住豁免范围，避免探针路径意外收紧或放宽。
- standby 角色下鉴权、审计、租户隔离等安全判定不得降级——standby 只是不跑数据面后台任务，已签发 token 的用户请求仍要走完整鉴权链路（对应需求 2 AC2）。
- 排空期间拒绝新 turn 的响应需给出明确状态码（复用 `INSTANCE_STANDBY` 或既有的服务不可用码），不得让客户端把它误判为鉴权失败。

## 测试策略

- 单测：`uv run pytest tests/unit/db/test_lease.py -q`（SQLite 恒 `standalone`；PG 分支用 `tests/support/postgresql.py::requires_postgresql` 覆盖抢占/心跳/释放/双进程互斥，需 `OCTOP_TEST_DATABASE_URL`，前置 `w0-02` 已在 CI 接入 postgres service）。
- 集成：`uv run pytest tests/integration/test_health_probes.py -q`（live 在假 pool 抛异常时仍 200 且快、ready 在 `SELECT 1` 失败时 503、standby 的 `/api/setup/status` 不误判、`/api/auth/me` 带有效 token 不 500）；`uv run pytest tests/integration/test_ha_lease.py -m postgresql -q`（双实例互斥、standby 不注册 cron/自动备份、active 退出后 standby 接管、排空期间拒绝新 turn）。
- 全量门禁：`uv run pytest -m "not live"`；`uv run pytest tests/unit/db -q`（含新 fork 迁移的版本断言，不改 `== 15` 断言，因为 fork 迁移不改 `_schema_version`）；`uv run pytest tests/unit/i18n -q`（新增 `ErrorCode` 时）。
- 手工验收：在两台机器（或两个容器）上同时以同一 `OCTOP_DATABASE_URL` 启动，kill 掉 active 后记录 standby 接管耗时是否在 `lease_ttl + 心跳周期` 内；对 active 发 `SIGTERM`，观察在途对话是否完整收到回复后进程才退出。

## 与其他 spec 的交接

- **依赖 `w2-03-database-adaptation`**：本 spec 假设 PG 方言家族已收口、运行期 DDL 已关闭、连接池参数已可配；租约表的建表脚本复用 `w2-03` 提供的 fork 迁移执行链路（由 `w0-01` 提供的 runner）。
- **依赖 `w0-02-ci-gates`**：PG 集成测试假设 CI 已有 `postgres` service 与 `OCTOP_TEST_DATABASE_URL`，本 spec 不重复建。
- **交付给 `p2-09-ops-observability`**：探针的 `role` 字段与租约状态是该 spec 的 Prometheus `/metrics`、K8s/双机部署清单、`servicemonitor.yaml`readiness 探针配置的依赖输入；本 spec 不涉及 `/metrics`、`deploy/k8s/`、`deploy/dual-host/`、`docs/ops/emergency.md`、压测基线，这些看似相关但归 `p2-09`。
- **交付给 `w4-02-ops-minimum`**（若尚未合入，属于其自身范围而非本 spec 反向依赖）：一期的"单实例 + 冷备 + 手工切换"文档与容器 `HEALTHCHECK` 指向不属于本 spec；本 spec 只在探针语义上向后兼容，不改一期已定的手工切换 runbook。
- **不属于本 spec**：`docs/adr/002-database-backends.md`/`docs/architecture.md` 的存储章节更正、`docs/configuration.md` 数据库环境变量表补充——这些文档更正随对应技术 spec（`w2-03`）走；本 spec 只在 `docs/api-intranet.md` 补 `/live`、`/ready` 两行接口说明。
- **看似相关但归别的 spec**：源 JSON 中 `src/octop/cli/commands/db.py` 的 `export-ddl`/`current-version`/`check` 属于 `w2-03`；`AUTO_BACKUP_JOB_ID` 的具体注册/注销行号改动仅在"按角色门控"这一层归本 spec，备份本身的策略归其所在的备份能力 spec（若存在）。

## 风险与回滚

- **风险**：fencing-token 方案要求 `runtime_lease` 表的更新是原子的 `UPDATE ... WHERE` 条件写；若信创库（金仓/openGauss）在隔离级别或行锁语义上与标准 PG 有差异，需要在目标库上实测后再定稿，不能只凭文档假设。
- **风险**：`_boot_runtime` 拆分涉及十余处依赖 `app_runtime` 非空的旧断言（如 `deps.py` 的 JWT 鉴权 `assert server.user_manager is not None`），拆分不彻底会让 standby 直接 500；需要为该场景补专门的回归测试而不是人工走查。
- **回滚**：租约与探针拆分是新增能力，可通过配置开关（`OCTOP_HA_LEASE_ENABLED`，默认关闭）整体关闭退回一期的单实例语义；`GET /api/health` 旧接口保持不变，回滚不影响现有监控接入。

## 待行方确认

- 对应 steering 第 4 节 `D5`：一期单活 + 冷备，秒级切换在二期本 spec 落地——本 spec 假设行方认可"数据库租约 + 心跳"作为选主机制，不引入额外的外部协调组件（如 etcd/ZooKeeper）。若行方要求脑裂防护达到更高等级，需另行评估。
