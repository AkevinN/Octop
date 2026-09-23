# 设计文档：信创数据库适配

> spec：`w2-03-database-adaptation` ｜ 波次：Wave 2 ｜ 基线：`757fd12` ｜ 预估：28 人日（另加 25% 风险缓冲约 7 人日，上限 35 人日）
> 前置：`w0-01-fork-migration-namespace`、`w0-02-ci-gates`、`w0-03-test-auth-baseline`、`w0-04-fork-isolation-points`、`w1-02-capability-trim`、`w2-01-offline-build` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 概述

**结论：** 本 spec 的核心设计有三点。

1. **`dialect` 永远表示方言家族。** `kingbase`、`opengauss` 只是 `DatabaseConfig.driver` 的新取值，`DatabasePool.dialect` 在它们下面仍是 `"postgresql"`。因此 `migrate.py` 的 31 行方言引用、备份模块的 42 行、repos 的 6 行一行都不用改，只需要一个 `Literal` 类型、一条不变式测试和一条静态守卫。
2. **迁移统一经过新增的 `infra/db/migrate_gate.py`。** `db_auto_migrate=false` 时完全不调用 `run_migrations`，只读四个水位（上游 `_schema_version`、fork `_fork_schema_version`、`checkpoint_migrations`、`harness_memory.meta`）来校验。表结构交给 `octop db export-ddl` 导出、DBA 预置；升级走 `octop db migrate`，由 DDL 账号在变更窗口执行。
3. **记忆层与 checkpoint 的运行期建表必须改外部包。** 在 harness-memory 行内内部分支（w2-01 建立）上加一个 `schema_bootstrap` 开关并暴露 DDL 函数；Octop 只在 verify-only 下传 `schema_bootstrap: false`。

此外有三处小改动：

- 连接池 6 个参数可配，默认值与基线实际生效值逐值相同。
- `setup_lockdown` 改用"已有用户"缓存，`UserManager.get_by_id` 改为按 id 索引。
- `/api/health` 删除 `users_loaded` 与 `agents_running` 两个字段，从而不再访问数据库。

本 spec **不新增 fork 迁移**。新增 2 个 ErrorCode 与 7 个配置键；只改 `/api/health` 这一个 HTTP 响应形状；前端源码不改，只改 intranet overlay。

## 现状

以下事实均在基线 `757fd12` 上核实。前序 spec 交付、基线中尚不存在的符号已单独注明。

### 驱动与方言

- `src/octop/config.py`：
  - `_VALID_DRIVERS = frozenset({"sqlite", "postgresql"})`（≈L20）；
  - `_DATABASE_ENV_KEYS`（≈L22-31）列 8 个 `OCTOP_DATABASE_*`，`database_env_configured()`（≈L34-36）对这 8 个做 `any`；
  - `DatabaseConfig.is_postgresql`（≈L56-58）为 `driver == "postgresql"`；
  - `postgresql_conninfo()`（≈L65-73）在 `driver != "postgresql"` 时抛 `ValueError`（≈L67）；
  - `_parse_database_url`（≈L295）只接受 `postgresql` / `postgres` 两种 scheme，并把 `driver` 置为 `"postgresql"`；
  - `_apply_database_env`（≈L374-392）先解析 `OCTOP_DATABASE_URL`，再由 `OCTOP_DATABASE_DRIVER` 覆盖 `driver`，所以"URL 用 `postgresql://`、驱动名单独指定"已经可以组合；
  - `parse_database_config`（≈L327）对 SQLite 提前返回（≈L339），对 PG 在 ≈L363 返回。
- `src/octop/infra/db/pool.py`：
  - `DatabasePool` Protocol 只声明 `dialect: str`（≈L22）；
  - `SqlitePool.dialect = "sqlite"`（≈L36）是类属性，连接由 `threading.RLock` 保护（≈L50）；
  - `PostgresPool.dialect = "postgresql"`（≈L145）；
  - `PostgresPool.__init__(conninfo, *, min_size=1, max_size=8)`（≈L147）只把这两个值传给 `ConnectionPool`（≈L150-156）。
- `src/octop/infra/db/factory.py`：`should_defer_control_plane_db`（≈L27）与 `open_database`（≈L41-42）都用 `is_postgresql` 分流；`PostgresPool(db_cfg.postgresql_conninfo())` 不传任何池参数。
- 全仓 `src/octop` 引用 `dialect` 的代码共 82 行：
  - `infra/db/migrate.py` 31 行，其中 `_discover`（≈L39，≈L45 按 `dialect == "postgresql"` 选 `.pg.sql`）、`_max_discovered_version`（≈L1448）、`_reconcile_pre_squash_schema_version`（≈L1461）、`run_migrations`（≈L1677、≈L1679、≈L1682）；
  - `infra/backup/chats.py` 21 行，`snapshot.py` 14 行，`system_archive.py` 7 行；
  - `repos/thread_messages.py` 3 行（≈L94、L247、L293 的 `FOR UPDATE` 分支），`repos/_base.py` 2 行（`sql_unix_day_bucket` ≈L67-69），`repos/usage.py` 1 行（≈L268），`pool.py` 3 行。

  这些值全部来自 `pool.dialect`；比较时用到的字符串字面量只有 `"sqlite"` 与 `"postgresql"` 两个。
- `src/octop/infra/backup/system_archive.py`：
  - `create_system_backup`（≈L187）在 `pool.dialect == "postgresql"` 时把 manifest 的 `database_driver` 写死为 `"postgresql"`（≈L212-214）；
  - `restore_system_backup`（≈L419）用 `archive_driver != pool.dialect` 判断跨引擎（≈L467-475）；
  - 用 `_max_discovered_version(pool.dialect)` 预检版本（≈L477）；
  - 在 ≈L534 调 `run_migrations(pool)`；
  - 两个函数都带 `db_config: DatabaseConfig` 参数。

### 迁移入口与运行期 DDL

- `src/octop` 中 `run_migrations(` 的调用点正好 10 个：`infra/server.py` ≈L323（`start`）与 ≈L347（`bind_control_plane`）、`infra/db/rebind.py` ≈L89（`assert_control_plane_database_empty`）与 ≈L127（`rebind_control_plane`）、`infra/backup/system_archive.py` ≈L534、`cli/support/db.py` ≈L27（`open_cli_services`）、`cli/commands/init.py` ≈L84、`cli/commands/admin.py` ≈L120、`cli/commands/backup.py` ≈L56 与 ≈L125。
- `run_migrations`（≈L1676-1713）：
  - PG 分支对版本 3、7、10 有 Python 钩子（≈L1686、L1690、L1697）；
  - 尾部固定调用 `_reconcile_pre_squash_schema_version` 与 12 个 `_ensure_*`。其中 `_ensure_trajectory_events_schema` 在 PG 下进入 `_ensure_trajectory_events_postgresql`（≈L1080），无条件执行 `CREATE TABLE IF NOT EXISTS trajectory_events`、`CREATE INDEX IF NOT EXISTS` 与一个 `DO $$` 块。

  也就是说，库结构完整时，每次启动仍会发出 DDL 语句。
- `_current_version`（≈L65-74）遇到任何异常都返回 0；`_table_exists`（≈L96）在 PG 下查 `information_schema.tables`。
- `rebind.py`：
  - `assert_control_plane_database_empty`（≈L82-99）自己构造 `OctopConfig(database=db_config, database_in_file=True)`，先迁移，再 `SELECT COUNT(*) FROM users`（≈L91）；
  - `rebind_control_plane`（≈L102-150）用 `load_config` 重读配置，同样先迁移再计数（≈L129）；
  - 首装向导 `POST /setup/database`（`api/routers/setup.py` ≈L272-306）依次调用 `probe_database`、`assert_control_plane_database_empty`、`persist_database_config`，然后调用 `rebind_control_plane` 或 `bind_control_plane`。
- `cli/main.py` 的 `_LazyCLI` 没有 `invoke` 覆盖，全仓 CLI 没有统一的 `OctopError` 处理；`cli/commands/run.py` 调用 `_run_uvicorn(...)` 时也不捕获 `OctopError`。`cli/support/errors.py::fail_octop`（≈L12）打印 `error: <message>` 后以 1 退出。
- **w0-01 交付（基线中不存在）：** `src/octop/infra/db/fork_migrate.py` 提供 `discover_fork_migrations(dialect)`、`max_fork_version(dialect)`、`current_fork_version(db)`、`run_fork_migrations(db)`、`_FORK_PY_STEPS`、`_FORK_MIGRATIONS_DIR`，由 `run_migrations` 最后一行调用。水位表 `_fork_schema_version` 由 runner 的 `_ensure_fork_version_table` 自建，**不是**迁移文件。

### 迁移文件的方言特性（决定国产库兼容面）

- `migrations/` 下有 `001`-`015` 共 15 对文件。`001_initial.pg.sql` 在 ≈L263-264 建 `_schema_version` 并写入 1，`015_sso_provider_kind.pg.sql` 末尾把水位写成 15。`.pg.sql` 中没有 `$$` 块。
- `GENERATED BY DEFAULT AS IDENTITY` 在 8 个 `.pg.sql` 文件中共出现 23 次，其中 `001_initial.pg.sql` 13 次。
- 带 `WHERE` 的部分索引：`001_initial.pg.sql` ≈L42、L125 两处，`005_shared_experts_sso_knowledge.pg.sql` 四处，`013_connector_instances.pg.sql` 两处以上（源 JSON 计 8 处 / 3 个文件）。
- `006_user_permissions.pg.sql` ≈L1 用 `JSONB` 与 `'[]'::jsonb`。
- `ON CONFLICT` 在 repos 下 8 个文件共 9 处，在 `migrate.py` 3 处。`INSERT … RETURNING id` 统一经 `repos/_base.py::insert_returning_id`（≈L74-81）；`repos/sso.py` ≈L315、L337 有 `UPDATE … RETURNING`；`thread_messages.py` 有 3 处 `SELECT … FOR UPDATE`。
- `backup/chats.py` ≈L352-354 用 `setval(pg_get_serial_sequence(...))`。

### 记忆层与 checkpoint（外部包，`.venv` 中核实）

- `pyproject.toml`：`harness-memory>=0.9.10`（≈L25）、`psycopg[binary]>=3.2`（≈L38）、`langgraph-checkpoint-postgres>=2.0`（≈L39）。已安装版本为 harness-memory 0.9.10、psycopg 3.3.4（二进制实现，自带 libpq 18）、psycopg-pool 3.3.1、langgraph-checkpoint-postgres 3.1.0。
- `psycopg_pool.ConnectionPool.__init__` 的实际签名含 `min_size`、`max_size`、`timeout=30.0`、`max_lifetime=3600.0`、`max_idle=600.0`、`check=None`，并且有 `ConnectionPool.check_connection`。基线只传 min/max，其余参数取上述默认值。
- `src/octop/infra/agents/memory_backend.py`：
  - PG 控制面下默认记忆后端为 `{"type": "postgres", "dsn": postgresql_conninfo()}`（≈L33-39）；
  - `use_control_plane_dsn` 分支同样取控制面 DSN（≈L54-63）；
  - `open_memory_kwargs`（≈L68-87）对 postgres 只回传 `{"dsn": …}`（≈L84-85）。

  harness-agent 的 `_construct_memory` 把 dict 规格中除 `type` 外的键原样交给 `Memory(backend_config=…)`。harness-memory 的 `_resolve_memory_backend` 以 `PostgresMemoryBackend(namespace=…, **config)` 构造后端，多余的键会被当作 `psycopg.connect` 的参数。
- harness-memory 0.9.10：
  - `storage/backends/postgres.py` 中 `SHARED_SCHEMA = "harness_memory"`（≈L44）、`SCHEMA_VERSION = "1"`（≈L48）；
  - `PostgresMemoryBackend.__init__`（≈L109-130）无条件调用 `_init_schema()` 与 `_migrate_legacy_schema()`。`_init_schema`（≈L272）执行 `pg_advisory_xact_lock`、`CREATE SCHEMA IF NOT EXISTS harness_memory`、一组 `CREATE TABLE IF NOT EXISTS`，以及 `INSERT INTO meta … ON CONFLICT DO UPDATE`；
  - `core.py::_create_postgres_checkpointer`（≈L1764-1820）为每个 `Memory` 单独建一个 `ConnectionPool(min_size=1, max_size=4)`，调用 `PostgresSaver(pool).setup()`（≈L1813），再尽力执行 `tune_checkpoint_autovacuum`（对 checkpoint 表 `ALTER TABLE … SET (…)`）。
- langgraph-checkpoint-postgres 3.1.0：
  - `PostgresSaver.setup()`（`langgraph/checkpoint/postgres/__init__.py` ≈L85-110）无条件执行 `MIGRATIONS[0]`（`CREATE TABLE IF NOT EXISTS checkpoint_migrations`），然后补跑缺失的版本；
  - `MIGRATIONS`（`base.py` ≈L43）当前 10 条，含 3 条 `CREATE INDEX CONCURRENTLY IF NOT EXISTS`，也是 `BasePostgresSaver.MIGRATIONS`。
- harness-agent 的记忆中间件会周期性调用 `nudge_vacuum(memory)`（`harness_agent/middleware/memory.py` ≈L736），失败时只记 warning。

### 请求路径上的同步查库

- `api/middleware/setup_lockdown.py` ≈L36：对每个非豁免的 `/api/*` 请求执行 `server.user_manager.count()`，即 `repos/users.py` ≈L316-318 的 `SELECT COUNT(*) FROM users`。
- `api/routers/health.py`（≈L14-28）同步调用 `user_manager.count()` 与 `agent_registry.list_rows()`，并匿名返回 `users_loaded`、`agents_running`。全仓（含 dashboard 与 tests）没有任何地方读取这两个字段。dashboard 的 `probeHealth.ts` 只读 `ok` 与 `started_at`（≈L29-37）。
- `infra/users/manager.py`：`_users: dict[str, User]`（≈L90）以用户名为键，只装未禁用的用户（`boot` ≈L101-114）；`get_by_id`（≈L215-219）线性扫描；`count()`（≈L232）直查库。`api/deps.py::resolve_user_from_token`（≈L142-148）对每个已鉴权请求调用 `get_by_id`。
- 另有一处未列入本 spec 范围的热点：`api/deps.py::_decode`（≈L129-132）对每个已鉴权请求执行 `secret_repo.get("jwt")`（一次 `SELECT`）。

### 部署与测试现状

- `docker/docker-compose.yml`：文件头 ≈L16-17 说明变量必须列在 `environment` 中才会进入容器；`environment` 在 ≈L34-55，其中 8 个 `OCTOP_DATABASE_*` 在 ≈L42-49。`tests/unit/test_docker_compose_database_env.py` 按 `_DATABASE_ENV_KEYS` 逐个校验（≈L28）。
- `tests/support/postgresql.py` 只提供 `requires_postgresql`（≈L14-17）。`tests/integration/test_postgresql_control_plane.py::_pg_payload_from_url` 把 `driver` 写死为 `"postgresql"`，`_reset_public_schema` 只重建 `public`。
- **w0-02 交付：** `make test-postgresql`（`-m postgresql -n 0`，加载 `tests.support.pg_strict`，任何 postgresql 用例被跳过即失败）。
- **w1-02 交付：** `tests/unit/test_config_touchpoints.py`（`return OctopConfig(...)` 缺字段即失败）。
- **w0-04 交付：** intranet overlay，以及让三方相等门禁读取合并后 bundle 的测试辅助。
- **w2-01 交付：** harness-* 行内内部分支、`<上游版本>+intranet.<N>` 精确固定与 `make relock`，以及 `octop init --if-needed` 的退出码契约（0/3/4/2/1）。

## 方案

### 1. 方言家族：`dialect` 即家族，`driver` 即产品

| 方案 | 结论 | 原因 |
|---|---|---|
| 源 JSON：`dialect` 改为真实驱动名，另加 `dialect_family`，逐处改为家族判断 | 否决 | 要改 `migrate.py` 的 26 处判断和 `_discover`、`_max_discovered_version` 两个文件选择点，还要改 `system_archive.py` ≈L477、备份模块 35 行、repos 4 处。上游每次同步带来的新 `db.dialect == "postgresql"` 都会在国产库上静默走 SQLite 分支。w0-01 的 `discover_fork_migrations` 也得跟着改。 |
| **`dialect` 恒为家族（`"sqlite"` / `"postgresql"`），产品名只在 `DatabaseConfig.driver`** | **采纳** | 上述 82 行零改动；上游新代码天然正确；只有真正需要区分产品的地方（备份 manifest、跨产品恢复判断）读 `db_config.driver`。 |

实现要点：

- `config.py` 新增 `_PG_FAMILY_DRIVERS = frozenset({"postgresql", "kingbase", "opengauss"})`；`_VALID_DRIVERS = _PG_FAMILY_DRIVERS | {"sqlite"}`；`is_postgresql` 改为 `driver in _PG_FAMILY_DRIVERS`，docstring 说明"PG 家族"；`postgresql_conninfo()` 的守卫改为 `if not self.is_postgresql`。`parse_database_config` 的 PG 分支对三个家族驱动一视同仁。
- URL 仍只接受 `postgresql://` / `postgres://`（libpq 不认识 `kingbase://`）。国产库写成 `OCTOP_DATABASE_URL=postgresql://…` 加 `OCTOP_DATABASE_DRIVER=kingbase`，这是基线已经支持的组合方式；向导载荷中显式的 `driver` 同样优先于 URL 推导的值（`database_config_from_payload` 用 `setdefault`）。
- `pool.py` 新增 `SqlDialect = Literal["sqlite", "postgresql"]`。Protocol 改为 `dialect: SqlDialect`，两个实现类的类属性同样标注为 `SqlDialect`。`mypy --strict` 自带的 `--strict-equality` 会在 `db.dialect == "kingbase"` 这类比较上报错。**不新增 `dialect_family` 属性，也不给连接池加 `driver` 属性**，因为需要产品名的两个函数本来就带 `db_config` 参数。
- `system_archive.py`：`create_system_backup` 的 PG 分支把 `database_driver = "postgresql"` 改为 `database_driver = db_config.driver`；`restore_system_backup` 的跨引擎判断由 `archive_driver != pool.dialect` 改为 `archive_driver != db_config.driver`，`details` 的 `runtime_driver` 同样取 `db_config.driver`。SQLite 下 `db_config.driver == "sqlite" == pool.dialect`，行为不变；旧的 PG 备份（`"postgresql"`）恢复到 `postgresql` 时行为也不变。
- 守卫：
  - 不变式测试：对四种驱动，`open_database` 返回的 `dialect` 与 `_discover`、`_max_discovered_version`、`discover_fork_migrations`、`max_fork_version` 的结果与 `postgresql` 或 `sqlite` 相同；
  - 静态测试：遍历 `src/octop/**/*.py` 的 AST，凡是 `Compare` 的一侧为属性名 `dialect` 或变量名 `dialect`、另一侧为字符串常量的，常量必须属于 `{"sqlite", "postgresql"}`。

### 2. 连接池参数

- 7 个新配置键放在 `OctopConfig` 顶层（见"配置"一节），不放进 `DatabaseConfig`。原因有三：
  - `assert_control_plane_database_empty` 与向导载荷会重新构造 `DatabaseConfig`，放在里面会丢值；
  - `persist_database_config` 会整体重写 `database` 段，同样会丢值；
  - 放在顶层可以直接被 w1-02 的三触点门禁覆盖。
- 环境变量用 `OCTOP_DB_*` 前缀，**不**加入 `_DATABASE_ENV_KEYS`。原因是 `database_env_configured()` 为真会改变 SQLite 路径解析与首装延迟建库的判定（`factory.py` ≈L15、≈L29），而池参数不应改变连接目标。另外新增 `_DATABASE_RUNTIME_ENV_KEYS` 元组，供 compose 透传测试使用。
- `PostgresPool.__init__(conninfo, *, min_size=1, max_size=8, timeout=30.0, max_lifetime=3600.0, max_idle=600.0, check=False)`：`check=True` 时传 `ConnectionPool.check_connection`，否则传 `None`。默认值与 psycopg-pool 3.3.1 一致，所以未配置时行为逐值不变。`open_database` 是唯一的构造点，负责把配置传进去。
- `check` 默认关闭：它会在每次借出连接时多一次往返。需要承受主备切换的部署建议打开，或者调小 `max_lifetime` / `max_idle`。

### 3. 迁移网关与只校验模式

新增 `src/octop/infra/db/migrate_gate.py`：

```python
@dataclass(frozen=True)
class ComponentVersion:
    component: str   # "control_plane" | "langgraph_checkpoint" | "harness_memory"
    current: str     # 如 "15+fork3"、"9"、"1"，表或行不存在时为 "missing"
    expected: str
    ok: bool         # current >= expected
    ahead: bool      # current > expected

def schema_status(db: DatabasePool) -> list[ComponentVersion]: ...
def verify_schema(db: DatabasePool) -> None:            # 首个 not ok 的组件 -> OctopError(SCHEMA_OUT_OF_DATE)
def maybe_run_migrations(db: DatabasePool, *, auto_migrate: bool) -> None:
def migrate_all(db: DatabasePool, *, conninfo: str | None) -> list[ComponentVersion]:  # octop db migrate
```

- `control_plane` 组件：
  - `current` 取 `_current_version(db)` 与 `current_fork_version(db)`；
  - `expected` 取 `_max_discovered_version(db.dialect)` 与 `max_fork_version(db.dialect)`；
  - 两个分量都 ≥ 期望才算 ok，任一 > 期望记为 ahead。
- 外部组件只在 `db.dialect == "postgresql"` 时加入（见第 5 条）：
  - `langgraph_checkpoint`：`SELECT max(v) FROM checkpoint_migrations`，期望值为 `len(MIGRATIONS) - 1`；
  - `harness_memory`：`SELECT value FROM harness_memory.meta WHERE key = 'schema_version'`，期望值为 harness-memory 的 `SCHEMA_VERSION`。

  查询失败（表不存在、权限不足）一律记为 `"missing"`，与 `_current_version` "异常即 0" 的取向一致。
- `maybe_run_migrations`：
  - `auto_migrate=True`：只调用 `run_migrations(db)`，其中已含 w0-01 的 fork runner。外部结构仍由 harness 在运行期自建，行为与基线一致。
  - `auto_migrate=False`：只调用 `verify_schema(db)`。有 ahead 时记 WARNING（含两侧版本）后放行，不回写任何水位；这与 w0-01 runner 对程序回退的处理方式一致。
  - `auto_migrate` 是**必填的关键字参数**，由 mypy 保证每个调用点都显式传值。
- `migrate_all`：先 `run_migrations(db)`，如果是 PG 家族，再调用 `external_schema.bootstrap_external(conninfo)`，最后返回 `schema_status(db)`。
- 10 个调用点逐一改为 `maybe_run_migrations(db, auto_migrate=config.db_auto_migrate)`：

| 调用点 | 取值来源 |
|---|---|
| `server.py` `start`、`bind_control_plane` | 局部变量 `config` |
| `rebind.py` `assert_control_plane_database_empty` | 新增必填关键字参数 `auto_migrate`；`setup.py` 传 `server.config.db_auto_migrate`（`start()` 已赋值） |
| `rebind.py` `rebind_control_plane` | 该函数内 `load_config` 的结果 |
| `cli/support/db.py`、`init.py`、`admin.py`、`backup.py` ×2 | 各自的 `load_config` 结果 |
| `system_archive.py` ≈L534 | `restore_system_backup` 新增关键字参数 `auto_migrate: bool = True`（默认值保证 16 处测试调用不变；两个 src 调用方显式传值） |

- 在 verify-only 下，库结构"表不存在"的情形会被 `_current_version` 返回 0 覆盖，从而在执行 `SELECT COUNT(*) FROM users` 之前就抛出 `SCHEMA_OUT_OF_DATE`，不会再出现"表不存在导致 500"。
- **应用内恢复：** `restore_system_backup` 在解包与 manifest 校验之后、任何替换动作之前，如果 `auto_migrate` 为假就抛 `DATABASE_DDL_DISABLED`。原因：PG 家族恢复依赖 `pg_restore --clean`，本身就是 DDL，在只有 DML 权限的账号下会中途失败并留下半恢复状态；SQLite 恢复后需要迁移补齐结构。verify-only 是生产配置，恢复交给 DBA 的备份平台（见交接中的 `w4-02`）。
- **CLI 退出码：** 在 `cli/main.py::_LazyCLI` 上新增 `invoke` 覆盖，只捕获两个新码：`SCHEMA_OUT_OF_DATE` 打印 `error: <message>` 后以 5 退出，`DATABASE_DDL_DISABLED` 打印后以 1 退出，其余 `OctopError` 原样上抛，不改变既有命令的行为。`octop run` 在 `srv.start()` 中抛出的异常会穿过 `asyncio.run` 到达这里，所以不必单独改 `run.py`。`octop init --if-needed` 因此获得 w2-01 契约之外的新码 5，含义为"库结构未预置或落后，且已关闭自动迁移"。
- **守卫：** AST 测试扫描 `src/octop/**/*.py`，断言 `run_migrations` 的导入与调用只出现在 `infra/db/migrate_gate.py`（`migrate.py` 只有定义）。`tests/` 下仍有 83 个文件直接调用它，不受约束。

### 4. DDL 导出、授权脚本与显式迁移

新增 `src/octop/infra/db/ddl_export.py` 与 CLI 组 `octop db`（`src/octop/cli/commands/db.py`，在 `cli/registry.py` 的 `COMMANDS` 中注册）。

**`octop db export-ddl --out DIR --runtime-role ROLE [--schema public] [--driver postgresql|kingbase|opengauss] [--force]`**，纯离线执行，不打开数据库：

| 文件 | 内容 |
|---|---|
| `a001_<描述>.sql` … `a015_<描述>.sql` | `_discover("postgresql")` 返回的上游 `.pg.sql` 原文，逐字复制 |
| `b000_fork_version_table.sql` | `_fork_schema_version` 的建表语句与初值 `(1, 0)`。SQL 文本取自 w0-01 `fork_migrate.py` 抽出的模块常量 `FORK_VERSION_TABLE_DDL`（本 spec 把 `_ensure_fork_version_table` 改为使用该常量，避免两处手写） |
| `b001_<描述>.sql` … | `discover_fork_migrations("postgresql")` 的原文，每个文件末尾追加 `UPDATE _fork_schema_version SET version = N WHERE id = 1;` |
| `c1_langgraph_checkpoint.sql` | `MIGRATIONS` 全部语句，外加 `INSERT INTO checkpoint_migrations (v) VALUES (0), …, (N-1) ON CONFLICT DO NOTHING;`。文件头注明含 `CREATE INDEX CONCURRENTLY`，必须在 autocommit 下逐条执行（psql 默认如此，不要加 `-1`） |
| `c2_harness_memory.sql` | 行内版 harness-memory `bootstrap_ddl()` 返回的语句（含 `CREATE SCHEMA IF NOT EXISTS harness_memory` 与 `SET search_path`）、`meta` 初值，以及 `checkpoint_tuning_ddl()` 的 autovacuum 调整（可选段，带注释） |
| `d_grants.sql` | 对 `--schema` 与 `harness_memory` 两个 schema：`GRANT USAGE ON SCHEMA`、`GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA`、`GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA`，授予 `--runtime-role`。不含任何 `CREATE` 权限。文件头注明每次执行 DDL 之后都要重跑本文件 |
| `apply_order.txt` | 执行顺序，头部写明执行方式、需要重跑授权，以及含 Python 步骤版本的升级规则 |
| `MANIFEST.json` | 生成时间、Octop 版本、`driver`、`upstream_version`、`fork_version`、`checkpoint_version`、`harness_memory_version`、`python_step_versions: {"upstream": [...], "fork": [...]}`、每个文件的 SHA256 |

- `python_step_versions.upstream` 由 `upstream_python_hook_versions()` 得到：解析 `migrate.py` 的 AST，在 `run_migrations` 函数体内收集 `if version == <int>` 的常量，基线为 `{3, 7, 10}`。`fork` 取 `_FORK_PY_STEPS` 的键。这两类版本的数据修复只有 Python 能做，所以增量升级跨越它们时必须用 `octop db migrate`。全新安装不受影响，因为空库上这些步骤都是空操作（由第 4.2 条的结构等价用例证明）。
- `--runtime-role` / `--schema` 用 `^[a-z_][a-z0-9_]{0,62}$` 校验，不合法时以 Click 用法错误（退出码 2）拒绝。输出目录非空且没有 `--force` 时同样拒绝。导出件不含任何口令或 DSN。

**`octop db check`**：打开库（离线 transport）并打印 `schema_status` 表格。全部 ok 时退出 0；有组件落后时退出 5；打开库或查询时出现连接错误则退出 1。退出码与第 3 条的约定一致，入口脚本与运维巡检都可以复用。

**`octop db migrate`**：调用 `migrate_all`，打印迁移前后的状态，不受 `db_auto_migrate` 影响。用法是在变更窗口内临时以 DDL 账号执行，例如 `OCTOP_DATABASE_URL=<DDL 账号 DSN> octop db migrate`，完成后重跑 `d_grants.sql`。

### 5. 记忆层与 checkpoint 预置

在 harness-memory 行内内部分支（w2-01 的"补丁以普通提交叠加、发布 `+intranet.N`"流程）上提交一个补丁，内容如下：

1. `PostgresMemoryBackend.__init__(namespace, dsn, *, schema_bootstrap: bool = True, **kwargs)`：先从 kwargs 取出 `schema_bootstrap`，不让它进入 `psycopg.connect`。
   - 为 `False` 时：跳过 `_init_schema` 与 `_migrate_legacy_schema`，改为 `_verify_schema()`：执行 `SET search_path TO harness_memory, public`，读 `meta.schema_version`，与 `SCHEMA_VERSION` 不一致或读不到时抛 `RuntimeError`（消息含期望值与实际值）。
   - 为 `True` 时：行为与 0.9.10 逐字节一致。
2. 把 `_init_schema` 中的建表语句提到模块级常量，并由它自己循环执行；另暴露 `bootstrap_ddl() -> tuple[str, ...]`，保证导出件与运行期不会出现两份手写。同时暴露 `checkpoint_tuning_ddl()`。
3. `Memory._create_postgres_checkpointer`：当后端的 `schema_bootstrap` 为 `False` 时，不调用 `saver.setup()` 与 `tune_checkpoint_autovacuum`，改为校验 `SELECT max(v) FROM checkpoint_migrations` 等于 `len(saver.MIGRATIONS) - 1`，不一致即抛 `RuntimeError`。
4. 补丁自带的测试放在 harness-memory 仓库中；Octop 侧由第 4.3 条的 PG 集成用例做端到端验收。

Octop 侧改动：

- `memory_backend.py` 新增内部函数 `_postgres_spec(dsn, octop_config) -> dict[str, Any]`，在 `octop_config.db_auto_migrate` 为假时追加 `"schema_bootstrap": False`。`memory_backend_from_agent_config` 中三处生成 postgres 规格的地方（默认、`use_control_plane_dsn`、显式 `dsn`）都改用它；`open_memory_kwargs` 的 postgres 分支把 `schema_bootstrap` 一并带回，覆盖 `api/common/memory_client.py` 与 `memory_portable.py` 这两条直接构造 `Memory` 的路径。`db_auto_migrate` 为真时生成的规格与基线逐键相同。
- 新增 `src/octop/infra/db/external_schema.py`：
  - `checkpoint_ddl()`、`checkpoint_expected_version()`：取 `langgraph.checkpoint.postgres.base.MIGRATIONS`；
  - `memory_ddl()`、`memory_expected_version()`：取行内版 harness-memory 的 `bootstrap_ddl()` 与 `SCHEMA_VERSION`；
  - `supports_preprovisioned_memory()`：判断 `harness_memory.storage.backends.postgres` 是否有 `bootstrap_ddl` 属性；
  - `external_status(db) -> list[ComponentVersion]`；
  - `bootstrap_external(conninfo)`：以 `schema_bootstrap=True` 构造一次后端并执行 `PostgresSaver.setup()`，供 `octop db migrate` 使用。

  所有外部包都在函数内惰性导入。
- `verify_schema` 在 PG 家族下先检查 `supports_preprovisioned_memory()`，为假时抛 `RuntimeError("installed harness-memory lacks schema_bootstrap; install the +intranet build")`。这是打包错误而不是库结构问题，所以不使用 ErrorCode。

**否决的替代方案：**

- 在 Octop 中 monkeypatch `PostgresSaver.setup` 与 `PostgresMemoryBackend._init_schema`：依赖私有方法，升级时会静默失效，并且带全局副作用。
- 给运行账号授予 schema 级 `CREATE`：`CREATE SCHEMA IF NOT EXISTS` 需要库级 `CREATE`，等于重新给出 DDL 权限。

### 6. 事件循环热点

- **`setup_lockdown`：**
  - `UserManager` 新增 `has_users() -> bool`：内部布尔 `_has_users` 为假时查一次 `user_repo.count() > 0` 并缓存结果；
  - `remove()` 与 `replace_services()` 把缓存清为假；
  - 中间件 ≈L36 改为 `server.user_manager is None or not server.user_manager.has_users()`。

  setup 完成后，锁定判断不再查库。零用户阶段每个请求仍会查一次，这是首装期的正常行为。已知限制：服务运行期间用离线 CLI 删光全部用户后，需要重启才会重新进入锁定。
- **`/api/health`：** 删除 `users_loaded` 与 `agents_running`，只返回 `ok`、`started_at`、`db`（`db` 仍取 `server.database_bound`）。这样处理函数完全不访问数据库，同时满足需求 7。探针拆分（`/live`、`/ready`）归 `p2-08`。
- **`UserManager.get_by_id`：** 新增 `src/octop/infra/users/user_cache.py::UserCache`，采用组合而非继承 `dict`，以免 mypy 与 `dict.update` 等方法绕过索引。它以用户名为主键、同时维护 id 索引，只提供 `manager.py` 实际用到的方法：`__setitem__`、`get`、`pop`、`clear`、`values`、`__len__`、`__contains__`，外加 `get_by_id`。`manager.py` 只改两处：`self._users = UserCache()`（≈L90）和 `get_by_id` 的函数体（≈L215-219）。其余 11 处 `self._users[...] = ...` / `.pop` / `.clear` 不改。同一 id 以新用户名写入时，id 索引指向最新的对象。
- 不新增 `db_offload` 通用模块。本 spec 的三个热点都是把数据库访问移出请求路径，而不是换线程执行；`/ready` 需要的带超时线程卸载，由 `p2-08` 按交接中的约束实现。

## 组件与接口

| 文件 | 类型 | 改动 |
|---|---|---|
| `src/octop/config.py` | 修改 | `_PG_FAMILY_DRIVERS`、`_VALID_DRIVERS`、`is_postgresql`、`postgresql_conninfo` 守卫；7 个新键的三触点、`_DATABASE_RUNTIME_ENV_KEYS`、校验 |
| `src/octop/infra/db/pool.py` | 修改 | `SqlDialect`；Protocol 与两个实现类的 `dialect` 标注；`PostgresPool.__init__` 新增 4 个关键字参数 |
| `src/octop/infra/db/factory.py` | 修改 | `open_database` 传入池参数 |
| `src/octop/infra/db/migrate_gate.py` | 新增 | `ComponentVersion`、`schema_status`、`verify_schema`、`maybe_run_migrations`、`migrate_all` |
| `src/octop/infra/db/external_schema.py` | 新增 | checkpoint 与 harness-memory 的 DDL、期望版本、状态、bootstrap |
| `src/octop/infra/db/ddl_export.py` | 新增 | `export_ddl(out_dir, *, driver, runtime_role, schema="public", force=False) -> ExportResult`、`upstream_python_hook_versions() -> set[int]` |
| `src/octop/infra/db/fork_migrate.py`（w0-01 交付） | 修改 | 抽出 `FORK_VERSION_TABLE_DDL` 常量，`_ensure_fork_version_table` 改用它 |
| `src/octop/infra/db/rebind.py` | 修改 | 两处迁移改走网关；`assert_control_plane_database_empty` 新增必填关键字参数 `auto_migrate` |
| `src/octop/infra/server.py` | 修改 | ≈L323、≈L347 两行 |
| `src/octop/infra/backup/system_archive.py` | 修改 | manifest 驱动名、跨产品判断、`auto_migrate` 参数与 verify-only 拒绝、≈L534 改走网关 |
| `src/octop/infra/agents/memory_backend.py` | 修改 | `_postgres_spec`；`open_memory_kwargs` 带回 `schema_bootstrap` |
| `src/octop/infra/users/user_cache.py` | 新增 | `UserCache` |
| `src/octop/infra/users/manager.py` | 修改 | `_users` 类型、`get_by_id`、`has_users`、`remove` 与 `replace_services` 清缓存 |
| `src/octop/infra/errors.py` | 修改 | 两个 ErrorCode 与 `_DEFAULT_STATUS` |
| `src/octop/api/routers/health.py` | 修改 | 删除两个字段与相应的查询 |
| `src/octop/api/middleware/setup_lockdown.py` | 修改 | ≈L36 改用 `has_users()` |
| `src/octop/api/routers/setup.py` | 修改 | 向 `assert_control_plane_database_empty` 传 `auto_migrate`；`DatabaseSetupBody.driver` 的 `Field(description=…)`（≈L73）补全四个取值 |
| `src/octop/api/routers/backup.py` | 修改 | `_restore_stored_backup` 透传 `auto_migrate` |
| `src/octop/cli/main.py` | 修改 | `_LazyCLI.invoke` 退出码映射 |
| `src/octop/cli/registry.py` | 修改 | 注册 `"db": (".commands.db", "db", "Control-plane schema: export DDL, check, migrate.")` |
| `src/octop/cli/commands/db.py` | 新增 | `export-ddl`、`check`、`migrate` |
| `src/octop/cli/support/db.py`、`cli/commands/init.py`、`admin.py`、`backup.py` | 修改 | 迁移改走网关；`backup restore` 透传 `auto_migrate` |
| `src/octop/i18n/intranet/{en,zh}.json`、`dashboard/src/locales/intranet/{en,zh}.json` | 修改 | 两个新码的文案，以及 `BACKUP_DRIVER_MISMATCH` 的产品化措辞覆盖 |
| `docker/docker-compose.yml` | 修改 | `environment` 列表补 7 行 |
| `pyproject.toml`、`uv.lock` | 修改 | `harness-memory` 固定到新的 `+intranet.N`，用 `make relock` 重生成锁文件 |
| `docs/intranet/database.md` | 新增 | DBA 交接、兼容核查、回归登记 |
| `tests/support/postgresql.py` | 修改 | 新增 `pg_test_driver()`，读取 `OCTOP_TEST_DATABASE_DRIVER`，默认 `"postgresql"` |
| 仓库外：harness-memory 行内内部分支 | 补丁 | 见方案第 5 条 |

关键签名：

```python
# config.py
_PG_FAMILY_DRIVERS: frozenset[str]
_DATABASE_RUNTIME_ENV_KEYS: tuple[str, ...]  # 7 个 OCTOP_DB_*

# pool.py
SqlDialect = Literal["sqlite", "postgresql"]
class PostgresPool:
    dialect: SqlDialect = "postgresql"
    def __init__(self, conninfo: str, *, min_size: int = 1, max_size: int = 8,
                 timeout: float = 30.0, max_lifetime: float = 3600.0,
                 max_idle: float = 600.0, check: bool = False) -> None: ...

# rebind.py
def assert_control_plane_database_empty(db_config: DatabaseConfig, paths: PathLayout,
                                        *, auto_migrate: bool) -> None: ...

# system_archive.py
def restore_system_backup(source, *, paths, pool, db_config, restore_config=True,
                          preserve_users=None, owner_user_id=None,
                          auto_migrate: bool = True) -> dict[str, Any]: ...

# users/manager.py
def has_users(self) -> bool: ...
```

## 数据模型

无 fork 迁移，不改任何表结构。

- `_fork_schema_version` 仍由 w0-01 的 runner 自建。本 spec 只把它的 DDL 文本抽成常量，并写进导出件。
- 外部结构（`harness_memory` schema、checkpoint 四张表）的结构由外部包定义，本 spec 只负责导出与校验。
- 备份 manifest 不新增字段。`database_driver` 的取值域从 `{sqlite, postgresql}` 扩大到四个驱动名。

## 配置

7 个新键全部位于 `OctopConfig` 顶层，环境变量优先于 `config.json` 中的同名键。

| 字段 | 类型 / 默认 | 环境变量 | 校验 |
|---|---|---|---|
| `db_auto_migrate` | `bool` / `True` | `OCTOP_DB_AUTO_MIGRATE` | `_coerce_bool` |
| `db_pool_min_size` | `int` / `1` | `OCTOP_DB_POOL_MIN` | ≥ 0 且 ≤ max |
| `db_pool_max_size` | `int` / `8` | `OCTOP_DB_POOL_MAX` | ≥ 1 |
| `db_pool_timeout_seconds` | `int` / `30` | `OCTOP_DB_POOL_TIMEOUT` | > 0 |
| `db_pool_max_lifetime_seconds` | `int` / `3600` | `OCTOP_DB_POOL_MAX_LIFETIME` | > 0 |
| `db_pool_max_idle_seconds` | `int` / `600` | `OCTOP_DB_POOL_MAX_IDLE` | > 0 |
| `db_pool_check` | `bool` / `False` | `OCTOP_DB_POOL_CHECK` | `_coerce_bool` |

`config.py` 的三触点（每个键都要改齐）：

1. `OctopConfig` dataclass 中新增 7 个字段。
2. env 覆盖块：在 `load_config` 中调用新增的 `_apply_db_runtime_env(merged)`，其中用 `_coerce_bool` / `_coerce_int` 处理 7 个环境变量；随后调用 `_validate_db_runtime(merged)`，关系类约束（如 min ≤ max）不满足时抛 `ValueError` 并指明键名。
3. `return OctopConfig(...)` 中逐字段传入这 7 个键。

`_DATABASE_RUNTIME_ENV_KEYS` 列出这 7 个环境变量名，供 compose 透传测试使用；它与 `_DATABASE_ENV_KEYS` 互不包含。`_defaults_for_file` 会把 7 个默认值写进新生成的 `config.json`，`tests/unit/test_config.py` 只断言默认文件不含 `password`，不受影响。驱动名的新取值不是新键，只是扩大了既有键 `database.driver` 的取值域。

## 错误处理

| ErrorCode | `_DEFAULT_STATUS` | 触发点 | `details` |
|---|---|---|---|
| `SCHEMA_OUT_OF_DATE` | 503 | `verify_schema`：任一组件落后或缺失 | `component`、`current`、`expected`（字符串） |
| `DATABASE_DDL_DISABLED` | 409 | verify-only 下的 `restore_system_backup` | 无 |

- 两个码都追加到 `ErrorCode` 枚举末尾与 `_DEFAULT_STATUS` 末尾，不按字母序插入（全局约束 §1.2、§5）。
- 文案写进 intranet overlay（全局约束 §1.2 规则二）：后端 `src/octop/i18n/intranet/{en,zh}.json` 的 `errors.*`，用 `{component}` 这类 Python 占位符；dashboard `dashboard/src/locales/intranet/{en,zh}.json` 的 `apiErrors.*`，用 `{{component}}` 这类 i18next 占位符（`test_dashboard_api_errors_use_i18next_placeholders` 会检查）。中文文案示例："数据库结构未就绪（{component}：当前 {current}，要求 {expected}）。已关闭自动迁移（OCTOP_DB_AUTO_MIGRATE=false），请由 DBA 执行 `octop db export-ddl` 导出的 DDL，或在变更窗口用有 DDL 权限的账号执行 `octop db migrate`。"
- 同时在两份 overlay 中覆盖 `BACKUP_DRIVER_MISMATCH` 的措辞。上游文案写的是"SQLite vs PostgreSQL"，改为按 `{archive_driver}` / `{runtime_driver}` 说明产品不一致。键集不变，三方相等门禁不受影响。
- 复用既有错误码：跨产品恢复仍用 `BACKUP_DRIVER_MISMATCH`（400）；driver 非法、池参数非法沿用 `load_config` 抛 `ValueError` 的既有方式；harness-memory 不支持预置模式时抛 `RuntimeError`（打包错误）。
- CLI 退出码：5 表示结构未就绪（新增，`octop run`、`init`、离线命令、`db check` 统一）；1 表示其他错误；2 表示用法错误。

## 安全考虑

- **最小权限：** verify-only 加上 `d_grants.sql`，运行账号只持表 DML 与序列权限，没有任何 `CREATE` / `ALTER` / `DROP`。第 4.3 条的用例反向证明该角色在 `auto_migrate=true` 下起不来。
- **结构变更留痕：** DDL 从应用启动中移出，改由 DBA 在变更流程中执行。`MANIFEST.json` 的 SHA256 可以用来核对执行的文件与发布件一致。应用审计表不记录 DDL，由行内既有审计通道兜底。
- **输入面：** `export-ddl` 只拼接随 wheel 打包的 SQL 与校验过的标识符，不接受任意 SQL；角色名和 schema 名用白名单正则校验，杜绝注入进授权脚本。
- **信息泄露：** `/api/health` 不再匿名返回用户数与 Agent 数。`/api/health/` 前缀豁免（`api/deps.py` ≈L66-72，`setup_lockdown.py` ≈L15-18）保持不变。
- **数据完整性：** verify-only 下拒绝应用内恢复，避免只有 DML 权限的账号执行 `pg_restore --clean` 中途失败、留下半恢复的库。
- **口令与传输：** DSN 不写进导出件与日志。数据库口令在向导绑定时仍会写入 `config.json`（`rebind.py::persist_database_config`，基线行为）。行内部署应当用环境变量注入 `OCTOP_DATABASE_URL` / `OCTOP_DATABASE_PASSWORD`，落盘加密归 `w3-05`。数据库连接是否强制国密 TLS 见 D8。
- **周期性 VACUUM：** harness-agent 的记忆中间件会对记忆表执行 `VACUUM`。非属主角色在 PostgreSQL 上只会得到警告而被跳过；目标库上的行为需要在回归中登记，由 DBA 的维护计划承担。

## 测试策略

所有新增的 PG 用例同时带 `@requires_postgresql` 与 `@pytest.mark.postgresql`，假定串行执行并独占 `public` 与 `harness_memory` 两个 schema，由 `w0-02` 的 `make test-postgresql` 收集，跳过即失败。

**单元测试：**

| 文件 | 覆盖 |
|---|---|
| `tests/unit/db/test_dialect_family.py` | 四种驱动下 `load_config` / `is_postgresql` / `postgresql_conninfo`；用假 `PostgresPool` 调 `open_database` 得到 `dialect`；`_discover`、`_max_discovered_version`、`discover_fork_migrations`、`max_fork_version` 的结果与基线相等；非法驱动名；`dialect` 比较字面量的 AST 守卫；SQLite 备份改写 manifest 驱动名后恢复，得到 `BACKUP_DRIVER_MISMATCH` |
| `tests/unit/db/test_pool_config.py` | 七个键的 env / 文件 / 默认值、非法值 WARNING、关系校验 `ValueError`；`open_database` 透传（沿用 `test_db_factory.py` 的假连接池手法）；`PostgresPool` 透传给假 `ConnectionPool`（`check=True` 时传 `check_connection`，未配置时逐值等于基线）；`database_env_configured()` 不受影响 |
| `tests/unit/db/test_migrate_gate.py` | auto 模式委托 `run_migrations`（spy）；verify 模式下水位一致时不调用、并用 `sqlite3.Connection.set_trace_callback` 断言无 `CREATE`/`ALTER`/`DROP`；空库、上游落后、fork 落后（用 w0-01 的 `tests/support/fork_migrations.py`）时抛 `SCHEMA_OUT_OF_DATE` 且 `details` 正确；程序回退时 WARNING 且放行；`run_migrations` 调用点的 AST 守卫 |
| `tests/unit/db/test_ddl_export.py` | 文件集合与顺序、上游文件逐字节相同、fork 水位推进语句、`MANIFEST.json` 的 SHA256、`upstream_python_hook_versions() == {3, 7, 10}`、`_FORK_PY_STEPS` 进入 manifest、授权脚本不含 `CREATE`、非法标识符拒绝、导出过程不打开数据库（把 `open_database` 替换为抛异常的桩） |
| `tests/unit/cli/test_db_cli.py` | `CliRunner` 下 `db export-ddl`、`db check`（0 / 5 / 1）、`db migrate`；`_LazyCLI` 把 `SCHEMA_OUT_OF_DATE` 映射为 5 |
| `tests/unit/agents/test_memory_backend_preprovisioned.py` | verify 模式下三种 postgres 规格与 `open_memory_kwargs` 都带 `schema_bootstrap: False`；auto 模式与基线逐键相等；`supports_preprovisioned_memory()` 为假时 `verify_schema` 抛 `RuntimeError` |
| `tests/unit/test_user_manager_index.py` | `UserCache` 在各类变更之后的一致性；`get_by_id`；`has_users` 的缓存与失效 |
| `tests/unit/test_docker_compose_database_env.py`（修改） | 增加 `_DATABASE_RUNTIME_ENV_KEYS` 的透传断言 |

**集成测试（SQLite）：**

| 文件 | 覆盖 |
|---|---|
| `tests/integration/test_verify_only_startup.py` | 预先迁移的 home 以 `db_auto_migrate=false` 启动成功；空库启动时 `srv.start()` 抛 `SCHEMA_OUT_OF_DATE`；`octop init --if-needed` 退出 5 且无用户；向导 `POST /api/setup/database` 返回 503；HTTP 与 CLI 恢复都返回 `DATABASE_DDL_DISABLED`，且库中的标记用户仍在 |
| `tests/integration/test_setup_lockdown_hotpath.py` | 20 个请求中 `UserRepo.count` 调用 0 次；`remove` 之后重新进入锁定 |
| `tests/integration/test_health_anonymous.py` | 键集合恰为三个；连接池 `connect` 抛异常时 1 秒内返回 200 |

**PostgreSQL：**

| 文件 | 覆盖 |
|---|---|
| `tests/integration/test_postgresql_ddl_export.py` | (a) 两个 schema（conninfo 带 `options=-csearch_path=<schema>`）对比 `run_migrations` 加 `PostgresSaver.setup()` 与执行导出件的结果，比较 `information_schema.columns`、`pg_indexes`（去掉 schema 名后比较 `indexdef`）、`information_schema.table_constraints`；`harness_memory` 顺序比对；(b) 创建临时 DML 角色（名称带随机后缀，结束时删除），按导出件与授权脚本预置后，用该角色和 `db_auto_migrate=false` 起服务、`bootstrap_admin`、登录、`create_agent`，并用 `Memory(backend="postgres", backend_config={"dsn": …, "schema_bootstrap": False})` 完成 `add_raw`/`get_raw` 与 `put`/`get_tuple`；同一角色在 auto 模式下 `srv.start()` 以权限错误失败；(c) `octop db migrate` / `check`；(d) 同一个 PG 上以 `driver=postgresql` 备份、以 `driver=kingbase` 恢复，得到 `BACKUP_DRIVER_MISMATCH` |
| `tests/integration/test_postgresql_family_compat.py` | 需求 9.1 列出的全部特性，每项一个用例，便于在国产库上逐项登记 |
| `tests/integration/test_postgresql_control_plane.py`（修改） | `_pg_payload_from_url` 的 `driver` 改取 `pg_test_driver()` |

**前端：** 源码不改，没有 vitest 用例。overlay JSON 的对等与形状由 w0-04 的测试覆盖。收尾时运行 `cd dashboard && npx tsc -b && npm run lint`。

**本地命令：**

```bash
uv run pytest tests/unit/db/test_dialect_family.py tests/unit/db/test_pool_config.py tests/unit/db/test_migrate_gate.py tests/unit/db/test_ddl_export.py -q
uv run pytest tests/unit/cli/test_db_cli.py tests/unit/agents/test_memory_backend_preprovisioned.py tests/unit/test_user_manager_index.py tests/unit/test_docker_compose_database_env.py -q
uv run pytest tests/integration/test_verify_only_startup.py tests/integration/test_setup_lockdown_hotpath.py tests/integration/test_health_anonymous.py -q
uv run pytest tests/unit/i18n tests/unit/test_config_touchpoints.py -q
# PG：专用库（行内镜像源替换 postgres:16），测试会 DROP SCHEMA public / harness_memory 并创建临时角色
docker run -d --name octop-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=octop_test -p 15432:5432 postgres:16
OCTOP_TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:15432/octop_test make test-postgresql
# 国产库回归（行方实例；账号需能建库内 schema 与临时角色）
OCTOP_TEST_DATABASE_URL=postgresql://<user>:<pw>@<host>:<port>/<db> OCTOP_TEST_DATABASE_DRIVER=kingbase make test-postgresql
make all
```

## 与其他 spec 的交接

**依赖：**

| spec | 本 spec 依赖的交付物 |
|---|---|
| `w0-01` | `fork_migrate.py` 的公开函数与 `_FORK_PY_STEPS`、`tests/support/fork_migrations.py`。w0-01 交接中"把 `dialect` 改成真实驱动名时必须同步家族化 `discover_fork_migrations`"一条，因本方案让 `dialect` 恒为家族而自然满足。本 spec 新增 `migrate_gate.py`、`ddl_export.py` 两个只读导入方（读水位与发现文件），runner 仍只经 `run_migrations` 进入；w0-01 任务中 `rg -l "infra\.db\.fork_migrate" src/` 的预期输出相应增加这两个文件 |
| `w0-02` | `make test-postgresql`、`pg_strict`；本 spec 的 PG 用例自动被收集 |
| `w0-03` | `tests/support/auth.py` 的 `bootstrap_admin`、`login`、`create_agent` 基线 |
| `w0-04` | 后端与前端 intranet overlay、合并后的 bundle 参与三方相等门禁、`CHANGELOG-intranet.md`、`docs/api-intranet.md` |
| `w1-02` | `tests/unit/test_config_touchpoints.py`；`config.py` 重复块已删除 |
| `w2-01` | harness-memory 行内仓库、`+intranet.N` 发布与精确固定、`make relock`；`octop init --if-needed` 契约（本 spec 新增退出码 5）；入口脚本对未列出的退出码按原码退出（任务 1 核实）；compose 文件在 w2-01 改动之后的形态 |

**交付给：**

| spec | 交付内容 |
|---|---|
| 全部后续需要改表的 spec（`w3-02`、`w3-03`、`w3-04`、`w3-05`、`p2-03`、`p2-05`、`p2-08` 等） | fork 迁移自动进入 DDL 导出；登记了 `_FORK_PY_STEPS` 的版本会在 `MANIFEST.json` 中标注，升级必须走 `octop db migrate`。判断 SQL 方言一律用 `db.dialect`（只取 `sqlite` / `postgresql`）；只有需要区分金仓、openGauss 产品差异时才读 `config.database.driver`；仓库中没有 `dialect_family` |
| `w3-04-session-and-password` | `api/deps.py::_decode` 对每个已鉴权请求查一次 `secrets` 表，是本 spec 未处理的第四个热点，建议在改造令牌时一并做进程内缓存与轮换失效。`resolve_user_from_token` 仍只信进程内缓存；本 spec 只把 `get_by_id` 改成索引，没有改语义 |
| `w3-05-credential-encryption` | 向导绑定会把数据库口令明文写入 `config.json`（`persist_database_config`） |
| `w4-02-ops-minimum` | 运维手册引用 `docs/intranet/database.md`：首装（导出 → DBA 执行 → 授权 → `octop db check`）、升级（`octop db migrate` + 重跑授权）、连接数预算、verify-only 下应用内恢复关闭；PG 家族备份工具名（金仓 `sys_dump` / `sys_restore`、openGauss `gs_dump` / `gs_restore`，`infra/backup/pg_dump.py` 写死 `pg_dump` / `pg_restore`）与恢复流程由 DBA 平台接管还是改造应用侧，由 w4-02 决定；`probe.py` 用 `SLASH_BAD_ARGS` 表达连接失败、默认 30 秒等待，建议一并评估 |
| `p2-08-ha-lease-probes` | 租约（源 JSON 的 `016_instance_lease` 须改写为 `forkNNN_instance_lease`）、`/live` 与 `/ready`、standby、排空、`HEALTHCHECK`。约束：`/ready` 的 `SELECT 1` 用 `asyncio.to_thread` 并带超时；在 SQLite 下不得在持有 `SqlitePool` 的 `RLock`（`pool.py` ≈L50）时 `await` 另一线程的查库；standby 下 `server.user_manager is None` 会让 `setup_lockdown` 返回 503，需要与本 spec 的 `has_users()` 一起解耦；verify-only 下启动不迁移，所以租约与迁移之间没有竞态 |
| `w2-02-supply-chain-compliance` | harness-memory 新的 `+intranet.N` 版本进入 SBOM / SCA 输入 |

**看似相关、实际归别处：**

| 内容 | 归属 |
|---|---|
| 源 JSON 的 `016_instance_lease`、`lease.py`、standby 拆分 `_boot_runtime`、`launch.py` 优雅停机、`AgentManager` 排空 | `p2-08` |
| `docker-entrypoint.sh`、`fnos/native/app/bin/octop` 的判据，`docker/Dockerfile`、`fnos/docker/Dockerfile` 的 `HEALTHCHECK` | `w2-01`（入口脚本）/ `p2-08`（探针）；fnOS 按 D9 由 `w1-04` 删除 |
| `.github/workflows/ci.yml` 的 PG job | `w0-02` |
| AGENTS.md `v == 7` | `w0-01` |
| history_v2 与 PG 控制面互斥（`server.py` ≈L397-399 硬抛）；共享存储上遗留的 `history_v2.sqlite` 会让 PG 部署起不来 | 本 spec 不处理，建议 `p2-08` 在共享存储方案中一并解决（见待确认） |
| `qmark_to_pyformat` 的 `%` 转义 | 不做：源 JSON 复核已证明收益为零，且在 `params=None` 路径上会引入新 bug |
| `_ensure_usage_cache_schema` 的无条件 `UPDATE` 条件化 | 不做：verify-only 下根本不调用 `run_migrations`，auto 模式下保持上游语义 |
| `docs/adr/002-database-backends.md` 等上游文档订正 | 不改上游文档；以 `docs/intranet/database.md` 为准 |

## 风险与回滚

| 风险 | 影响 | 缓解 |
|---|---|---|
| openGauss 内核较旧，`GENERATED BY DEFAULT AS IDENTITY`（23 处，001 占 13 处）、`ON CONFLICT`、部分索引、`CREATE INDEX CONCURRENTLY` 等可能不被支持 | 需要为国产库另写一套 fork 方言迁移，工作量超出 25% 缓冲 | 需求 9 的兼容探针在回归前就给出结论；D3 优先选择 PG 兼容度更高的一款；不可用项按需求 10.3 登记为阻断项并单独估算 |
| psycopg / libpq 不支持目标库的认证方式（openGauss 的 sha256、SM3） | 连不上库，本 spec 需要换驱动，工作量翻倍 | 需求 9.2、9.3 的 DBA 核查；首选 md5 或 scram-sha-256；换驱动另行立项 |
| 导出件与 `run_migrations` 的结果漂移（例如上游在 Python 钩子里建结构） | DBA 预置的库缺表或缺列 | 结构等价用例在 CI 的 PG job 中常驻；Python 步骤在 `MANIFEST.json` 中标注，升级走 `octop db migrate` |
| harness-memory 补丁在上游升级时需要重新挑选 | 版本升级时预置模式失效 | 补丁小而独立；启动时的 `supports_preprovisioned_memory()` 检查会立即失败；PG 用例覆盖端到端 |
| 连接数：每个 Agent 的记忆后端占 1 个连接，checkpoint 连接池最多 4 个，另加 Octop 连接池 | 超出 DBA 配额后连接被拒 | `docs/intranet/database.md` 给出估算式 `db_pool_max_size + Agent 数 × 5`；连接池参数可配；harness 侧连接池参数化列为后续事项 |
| `db_pool_check=true` 时每次借出连接多一次往返 | 跨机房延迟可感知 | 默认关闭；文档说明适用场景 |
| `has_users` 缓存在离线删光用户后不会失效 | 需要重启才重新进入锁定 | 文档注明；运行中的 `remove` 会正确失效 |
| 10 个调用点与上游同步冲突 | 解冲突时可能漏改 | AST 守卫让直接调用 `run_migrations` 的新调用点在 `make test` 中变红 |

**回滚：**

- 运行期回滚：设 `OCTOP_DB_AUTO_MIGRATE=true`（即默认值）即可回到基线的迁移行为；不设任何 `OCTOP_DB_POOL_*` 时，连接池参数与基线逐值相同。
- 代码回滚：每个顶层任务单独提交，可以逐个 `git revert`。harness-memory 回滚方式是把 `pyproject.toml` 的固定版本退回上一个 `+intranet.N`，然后执行 `make relock`。
- 本 spec 不产生 fork 迁移，所以没有需要回滚的库结构。

## 待行方确认

- **D3（控制面数据库）：** 默认为 PG 系。需要确认最终选金仓 KES 还是 openGauss（或 GaussDB）、具体版本与兼容模式。这决定需求 9 的探针能否全部通过，以及是否需要为 23 处 IDENTITY 与 8 处部分索引另写方言迁移（超出本 spec 的缓冲）。若为达梦、OceanBase、TiDB，按 D3 另立项。
- **D4（部署形态）：** psycopg-binary 自带 libpq 18，并提供 x86_64 与 arm64 的 wheel；龙芯需自编译，不在本 spec 内。
- **D5（高可用）：** 一期单活加冷备。verify-only 下两个实例都不迁移，不存在迁移竞态；租约归 `p2-08`。
- **D8（国密与密评）：** 数据库连接若在一期就必须使用国密 TLS 或厂商专有认证，libpq 无法满足，需要换驱动，超出本 spec。
- **D13（harness-* 源码）：** 记忆层与 checkpoint 的预置依赖 harness-memory 源码可得并能进入 w2-01 的内部分支流程。若不可得，一期只能在两个方案中选一个：给运行账号库级 `CREATE`（等于保留 DDL 权限），或者让记忆层与 checkpoint 退回本地 SQLite。两者都需要行方拍板。
- 其余不在 steering §4 中、需要行方回答的问题：应用内备份恢复是否整体交给 DBA 平台；运行账号的连接配额；是否同时需要"会话可追溯留档"（history_v2）与 PG 控制面。
