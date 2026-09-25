# 需求文档：信创数据库适配

> spec：`w2-03-database-adaptation` ｜ 波次：Wave 2 ｜ 基线：`757fd12` ｜ 预估：28 人日（另加 25% 风险缓冲约 7 人日，上限 35 人日）
> 前置：`w0-01-fork-migration-namespace`、`w0-02-ci-gates`、`w0-03-test-auth-baseline`、`w0-04-fork-isolation-points`、`w1-02-capability-trim`、`w2-01-offline-build` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 引言

**结论：** 本 spec 让 Octop 控制面能以"PG 系国产库（人大金仓或 openGauss）+ 只持 DML 权限的运行账号"运行，并在做到这一点的同时，不改动上游 `migrate.py` 里任何一处方言判断。具体交付七件事：

1. 把 `kingbase`、`opengauss` 作为驱动名接入，并归入 PostgreSQL 方言家族。
2. 连接池参数可配（基线写死 `min_size=1`、`max_size=8`）。
3. 自动迁移开关与只校验（verify-only）模式。
4. DDL 导出、DBA 授权脚本与显式迁移命令。
5. 记忆层与 LangGraph checkpoint 的建表从运行期改为预置。
6. 把三个同步查库的热点移出请求路径，并让 `/api/health` 不再匿名暴露用户数与 Agent 数。
7. 给出 psycopg 连接金仓与 openGauss 的兼容核查步骤，并在真实国产库上做集成回归。

### 背景

- 控制面只认 `sqlite` 与 `postgresql` 两个驱动名（`src/octop/config.py` 的 `_VALID_DRIVERS`）。`DatabaseConfig.postgresql_conninfo()` 对 `driver != "postgresql"` 直接抛 `ValueError`，是国产库驱动名的第一个必炸点。
- 启动路径与离线 CLI 共有 10 处直接调用 `run_migrations`。`run_migrations` 的尾部在 PG 下每次都会执行 `CREATE TABLE IF NOT EXISTS`、`CREATE INDEX IF NOT EXISTS` 这类语句（例如 `_ensure_trajectory_events_postgresql`）。所以即使库结构已经完整，运行账号也必须持有 DDL 权限。行内 DBA 通常不会给应用账号 DDL 权限。
- 记忆层（harness-memory）和 LangGraph checkpoint 也在运行期建表：`PostgresMemoryBackend._init_schema` 会执行 `CREATE SCHEMA IF NOT EXISTS harness_memory`，`PostgresSaver.setup()` 会执行 `CREATE TABLE IF NOT EXISTS checkpoint_migrations`。按 PostgreSQL 的实现，权限检查先于存在性检查，所以只持 DML 权限的账号即使面对已经建好的表也会失败。以上结论仍需在目标库上实测确认。
- `setup_lockdown` 中间件对每个非豁免的 `/api/*` 请求都要同步执行一次 `SELECT COUNT(*) FROM users`；`/api/health` 同步查用户数和 Agent 全表，并且匿名返回这两个数字。数据库一旦变慢，整站都会被拖住。

### 为什么这样做

- 默认假设 D3 是：控制面库为 PG 系（金仓或 openGauss），SQLite 只用于开发与测试。
- 本 spec 不采用源分析中"`dialect` 改为真实驱动名，另加 `dialect_family`"的方案，改为**让 `dialect` 始终表示方言家族，产品名只保存在 `DatabaseConfig.driver`**。理由如下：
  - 全仓引用 `dialect` 的代码共 82 行：`migrate.py` 31 行，备份模块（`chats.py`、`snapshot.py`、`system_archive.py`）42 行，repos 6 行，`pool.py` 3 行。按源方案，其中的比较都得逐行改成家族判断，而 `migrate.py` 是全局约束 §5 所列的三个不可约热点之一。
  - 上游今后新写的每一处 `db.dialect == "postgresql"`，在每次同步时都会在国产库上静默失效。
  - 反过来，只要让 `dialect` 在金仓和 openGauss 下也取 `"postgresql"`，这些判断以及 `_discover`、`_max_discovered_version`、w0-01 的 `discover_fork_migrations` 就都天然正确。只需要一条不变式测试和一个 `Literal` 类型来守住。

### 范围内

| 项 | 说明 |
|---|---|
| PG 方言家族 | 驱动白名单、`is_postgresql` 改为家族判断、`postgresql_conninfo` 驱动校验、`DatabasePool.dialect` 取值域以 `Literal` 固定；备份 manifest 记录真实驱动，恢复时按真实驱动拒绝跨产品恢复；覆盖 `migrate.py` 的方言判断、`_discover` / `_max_discovered_version`、`system_archive.py` 的版本计算、repos 内的方言分支（以不变式测试证明无需逐行修改） |
| 连接池参数 | 6 个池参数可配，默认值与基线实际生效值逐值相同 |
| 关闭运行期 DDL | `db_auto_migrate` 开关与 verify-only 模式，10 个迁移入口统一经 `migrate_gate`；verify-only 下拒绝应用内恢复 |
| DDL 工具链 | `octop db export-ddl`（含 DBA 授权脚本）、`octop db check`、`octop db migrate`（原 S15 的 DDL 工具链归入本 spec） |
| 记忆层与 checkpoint 预置 | 在 harness-memory 行内内部分支上补丁（仓库外，经 w2-01 的发布流程），Octop 侧在 verify-only 下传 `schema_bootstrap: false`，DDL 导出包含两者 |
| 事件循环热点 | `setup_lockdown` 每请求 `count()`、`/api/health`、`UserManager.get_by_id` 线性扫描 |
| health | 删除匿名返回的 `users_loaded` 与 `agents_running` |
| 容器透传 | `docker/docker-compose.yml` 的 `environment` 列表补 7 个新变量；`octop init --if-needed` 在 verify-only 下的退出码 |
| 兼容验证 | psycopg 对金仓/openGauss 的认证与 SQL 特性探针、DBA 侧核查步骤 |
| 集成回归 | 在行方提供的金仓/openGauss 实例上运行全部 PG 用例与人工验收脚本并登记结果 |
| 风险缓冲 | 沿用 S12 自报的 25% 风险缓冲，覆盖 psycopg 认证兼容与国产库 SQL 特性兼容两项不确定性 |

### 范围外

| 事项 | 归属 |
|---|---|
| 实例租约（源 JSON 的 `016_instance_lease`）、standby、`/api/health/live` 与 `/ready` 拆分、停机排空、`uvicorn` 优雅停机、`HEALTHCHECK` 改指向 | `p2-08-ha-lease-probes` |
| `docker/docker-entrypoint.sh`、`fnos/native/app/bin/octop` 的首启判据与幂等初始化，`octop init --if-needed` 本身 | `w2-01-offline-build`（本 spec 只补"schema 未预置"时的退出码） |
| CI 的 postgres service 与 `make test-postgresql` | `w0-02-ci-gates` |
| AGENTS.md §7 `v == 7` 勘误 | `w0-01-fork-migration-namespace` |
| 数据库口令在 `config.json` 明文落盘 | `w3-05-credential-encryption`（本 spec 要求行内以环境变量注入） |
| 数据库连接国密 TLS、KMS | `p2-02-kms-sm-crypto`（见 D8） |
| 备份工具名（`sys_dump` / `gs_dump`）与 PG 家族备份恢复的运维流程 | `w4-02-ops-minimum` |
| 达梦 / OceanBase / TiDB 等第三方言 | D3 另立项 |
| 源 JSON 中 `qmark_to_pyformat` 的 `%` 转义、`_ensure_usage_cache_schema` 无条件 `UPDATE` 的条件化、`probe.py` 错误码更正、`db_offload` 通用模块 | 不做：前两项已被源 JSON 自身复核推翻，或在 verify-only 下根本不会执行；后两项不在本 spec 列出的范围内，理由见设计文档"与其他 spec 的交接" |
| 上游文档（`docs/adr/002-database-backends.md`、`docs/configuration.md`、`docs/api.md`、`docker/README.md`）的订正 | 不改上游文档，fork 内容写进 `docs/intranet/database.md`、`docs/api-intranet.md`、`CHANGELOG-intranet.md` |

## 需求

### 需求 1：PG 方言家族

**用户故事：** 作为行内部署运维，我希望把控制面指向金仓或 openGauss 时 Octop 自动走 PostgreSQL 的迁移与 SQL 分支，以便不因驱动名不同而在国产库上执行 SQLite 的 DDL。

#### 验收标准

1. 当 `OCTOP_DATABASE_DRIVER` 为 `kingbase` 或 `opengauss`、其余 `OCTOP_DATABASE_*` 连接字段齐备时，`load_config` 应当接受该驱动，`DatabaseConfig.is_postgresql` 为真，`postgresql_conninfo()` 返回以 `postgresql://` 开头的 conninfo 而不抛异常。
2. 当以上述驱动调用 `open_database` 时，返回的连接池的 `dialect` 应当为 `"postgresql"`；用该值调用 `_discover` 应当只返回 `.pg.sql` 文件（基线为 15 个），`_max_discovered_version`、`discover_fork_migrations` 与 `max_fork_version` 的结果应当与 `driver=postgresql` 时逐项相同。
3. 如果 `database.driver` 不是 `sqlite`、`postgresql`、`kingbase`、`opengauss` 之一，那么 `load_config` 应当抛出 `ValueError`，消息中列出这四个允许值。
4. 系统应当始终保证 `DatabasePool.dialect` 只取 `"sqlite"` 或 `"postgresql"`：Protocol 以 `Literal` 声明，`make typecheck` 通过；静态测试断言 `src/octop` 中与 `dialect` 做相等比较的字符串字面量只有这两个。
5. 当在 PG 家族库上创建系统备份时，`manifest.json` 的 `database_driver` 应当记录 `DatabaseConfig.driver` 的实际值；如果恢复时备份的驱动与运行驱动不同（例如 `kingbase` 备份恢复到 `opengauss` 或 `postgresql`），那么应当在替换任何数据之前抛出 `BACKUP_DRIVER_MISMATCH`，`details` 仍为 `archive_driver`、`runtime_driver` 两键。
6. 系统应当始终在 `driver=postgresql` 与 `sqlite` 下保持基线行为：`tests/unit/db`、`tests/unit/backup` 的既有用例与 `make test-postgresql` 不改即通过。

### 需求 2：连接池参数可配

**用户故事：** 作为行内 DBA，我希望按数据库的连接配额与主备切换要求调整连接池，以便应用既不超配额，也能在主备切换后丢弃陈旧连接。

#### 验收标准

1. 当设置 `OCTOP_DB_POOL_MIN`、`OCTOP_DB_POOL_MAX`、`OCTOP_DB_POOL_TIMEOUT`、`OCTOP_DB_POOL_MAX_LIFETIME`、`OCTOP_DB_POOL_MAX_IDLE`、`OCTOP_DB_POOL_CHECK`（或 `config.json` 中同名的顶层键 `db_pool_*`）时，`open_database` 应当把对应值传给 `PostgresPool`，`PostgresPool` 应当原样传给 `psycopg_pool.ConnectionPool` 的 `min_size`、`max_size`、`timeout`、`max_lifetime`、`max_idle`；`OCTOP_DB_POOL_CHECK=true` 时应当传 `check=ConnectionPool.check_connection`。
2. 如果未设置任何池参数，那么传给 `ConnectionPool` 的值应当为 `min_size=1`、`max_size=8`、`timeout=30`、`max_lifetime=3600`、`max_idle=600`、`check=None`，与基线实际生效的值一致。
3. 如果出现 `min > max`、`max < 1`、`min < 0` 或任一时长 ≤ 0，那么 `load_config` 应当抛出 `ValueError` 并指明键名；如果环境变量不是合法的整数或布尔值，那么应当记一条不回显原值的 WARNING，并回落到文件值或默认值（与既有 `_coerce_int` / `_coerce_bool` 一致）。
4. 系统应当始终让 7 个新键（6 个池参数与 `db_auto_migrate`）同时出现在 `OctopConfig` 字段、`load_config` 的 env 覆盖块与 `return OctopConfig(...)` 三处，`uv run pytest tests/unit/test_config_touchpoints.py -q` 通过。
5. 如果只设置了 `OCTOP_DB_*` 而没有设置任何 `OCTOP_DATABASE_*`，那么 `database_env_configured()` 应当仍返回假，SQLite 路径解析与首装延迟建库的行为不变。

### 需求 3：自动迁移开关与只校验模式

**用户故事：** 作为行内 DBA，我希望应用启动时不执行任何 DDL，只校验库结构是否已由我预置到位，以便运行账号只需要 DML 权限，结构变更全部走 DBA 的变更流程。

#### 验收标准

1. 在 `db_auto_migrate` 为真（默认）期间，src 中全部迁移入口（`OctopServer.start`、`bind_control_plane`、`assert_control_plane_database_empty`、`rebind_control_plane`、`open_cli_services`、`octop init`、`octop admin rotate-jwt-secret`、`octop backup create`、`octop backup auto run`、`restore_system_backup`）的行为应当与基线一致，包括 fork runner 的执行。
2. 当 `OCTOP_DB_AUTO_MIGRATE=false`，且上游水位、fork 水位与（PG 家族下）外部结构水位都不低于代码期望时，服务应当正常启动，并且启动期间发往控制面库的语句中不出现 `CREATE`、`ALTER`、`DROP`。
3. 如果 `OCTOP_DB_AUTO_MIGRATE=false` 且任一水位落后或相关表不存在，那么 `octop run`、`octop init`（含 `--if-needed`）以及使用离线库的 CLI 命令应当以退出码 5 结束，并在 stderr 打印组件名以及"当前版本 < 期望版本"；`POST /api/setup/database` 应当返回 503 与 `SCHEMA_OUT_OF_DATE`。两种情况下都不执行任何 DDL。
4. 系统应当始终只经由 `src/octop/infra/db/migrate_gate.py` 调用 `run_migrations`：AST 测试断言 `src/octop` 中的其他模块既不导入也不调用它（`tests/` 不受此约束）。
5. 如果库的水位高于代码期望（程序回退），那么 verify-only 应当记一条含两侧版本的 WARNING 后放行，并且不回写任何水位。
6. 在 verify-only 期间，应用内恢复（`POST /api/backup/files/{filename}/restore` 与 `octop backup restore`）应当在替换任何数据之前以 `DATABASE_DDL_DISABLED`（409）拒绝；备份创建不受影响。
7. 系统应当始终把新增的 `SCHEMA_OUT_OF_DATE`（503）与 `DATABASE_DDL_DISABLED`（409）同批登记在 `ErrorCode` 末尾、`_DEFAULT_STATUS` 末尾，以及后端与 dashboard 的 intranet overlay（en/zh）中，`uv run pytest tests/unit/i18n -q` 通过。

### 需求 4：DDL 导出、DBA 授权脚本与显式迁移命令

**用户故事：** 作为行内 DBA，我希望拿到一份可审核、可离线生成、带授权脚本的完整 DDL，以及一条在变更窗口内执行升级的命令，以便首装和升级都由我掌控。

#### 验收标准

1. 当执行 `octop db export-ddl --out <DIR> --runtime-role <ROLE>` 时，应当在不连接任何数据库的前提下生成以下内容：上游 `.pg.sql` 原文（每个版本一个文件）；`_fork_schema_version` 的建表与初值；fork `.pg.sql` 及其水位推进语句；LangGraph checkpoint 的 DDL 与 `checkpoint_migrations` 初值；harness-memory 的 DDL 与 `meta` 初值；授权脚本；`apply_order.txt`；`MANIFEST.json`（含各文件的 SHA256，以及上游、fork、外部结构的期望版本）。
2. 当在空 schema 上按 `apply_order.txt` 执行导出件后，所得结构应当与在另一个空 schema 上执行 `run_migrations` 加外部 bootstrap 的结构一致，比较范围是表、列的类型、默认值与可空性、索引定义、约束。由 PG 集成用例断言。
3. 当使用仅持授权脚本所授权限（表的 SELECT/INSERT/UPDATE/DELETE、序列的 USAGE/SELECT/UPDATE、schema 的 USAGE，无 CREATE）的角色，并设置 `OCTOP_DB_AUTO_MIGRATE=false` 时，服务应当能启动、完成初始管理员创建与登录、经 API 创建 Agent 记录，并能用 harness-memory 的 `Memory` 完成一次 `add_raw` / `get_raw` 与一次 `put` / `get_tuple`；同一角色在 `OCTOP_DB_AUTO_MIGRATE=true` 下启动应当因权限不足而失败。
4. 如果导出范围内存在登记了 Python 步骤的版本（fork 的 `_FORK_PY_STEPS` 键，或上游 `run_migrations` 中 `if version == N` 分支对应的版本），那么 `MANIFEST.json` 应当列出这些版本，并在 `apply_order.txt` 头部注明：跨越这些版本的升级必须用 `octop db migrate` 执行。
5. 当执行 `octop db migrate` 时，应当不受 `db_auto_migrate` 影响，完成上游、fork 与外部结构的迁移，并打印迁移前后的各组件版本；当执行 `octop db check` 时，水位一致则退出 0，落后则退出 5，库不可达则退出 1。
6. 如果 `--runtime-role` 或 `--schema` 不是合法的未加引号标识符（`^[a-z_][a-z0-9_]{0,62}$`），那么 `export-ddl` 应当以用法错误（退出码 2）拒绝，并且不写任何文件。

### 需求 5：记忆层与 LangGraph checkpoint 预置

**用户故事：** 作为行内 DBA，我希望记忆层与对话检查点的表也由我预置，以便运行账号在 Agent 启动与首轮对话时同样不需要 DDL 权限。

#### 验收标准

1. 在 `db_auto_migrate` 为假且控制面为 PG 家族期间，`memory_backend_from_agent_config` 与 `open_memory_kwargs` 生成的 postgres 规格应当含 `schema_bootstrap: false`；`db_auto_migrate` 为真时，生成的规格应当与基线逐键相同。
2. 当行内版 harness-memory 以 `schema_bootstrap=False` 构造 PG 后端时，应当不执行 `CREATE SCHEMA` / `CREATE TABLE`，不调用 `PostgresSaver.setup()` 与 checkpoint 的 autovacuum 调整，不执行遗留 schema 迁移，只校验 `harness_memory.meta` 中的 `schema_version` 与 `checkpoint_migrations` 的最大版本；不一致时应当抛出含期望版本与实际版本的异常。
3. 如果 `db_auto_migrate` 为假、控制面为 PG 家族，而已安装的 harness-memory 不支持 `schema_bootstrap`，那么服务启动应当立即失败，并提示需要 `+intranet` 构建。
4. 系统应当始终让导出件中的 checkpoint DDL 与 harness-memory DDL 来自当前已安装的版本：checkpoint 取 `langgraph.checkpoint.postgres.base.MIGRATIONS`，记忆层取行内版 harness-memory 暴露的 DDL 函数，而不是在 Octop 中手抄。

### 需求 6：事件循环热点移出

**用户故事：** 作为行内运维，我希望数据库变慢时整站不被逐请求的同步查库拖住，以便故障影响限定在真正需要数据库的接口上。

#### 验收标准

1. 当至少存在一个用户之后，连续 20 个非豁免 `/api/*` 请求经过 setup 锁定中间件时，`UserRepo.count` 被调用的次数应当为 0。
2. 如果 `UserManager.remove` 删除了用户，或控制面经 `replace_services` 换库，那么"已有用户"缓存应当失效，下一个请求重新查询；零用户时锁定中间件仍返回 `503 {"setup_required": true}`，`tests/integration/test_setup_wizard.py` 中既有的锁定用例不改即通过。
3. `UserManager.get_by_id` 应当始终按 id 索引查找，并且在 `boot`、`create`、`register_cached_user`、SSO 登录缓存、`enable`、`disable`、`remove`、`shutdown_all` 之后与按用户名的缓存保持一致。
4. 当把控制面连接池的 `connect` 替换为抛异常的桩时，`GET /api/health` 应当仍在 1 秒内返回 200。

### 需求 7：health 不再匿名暴露部署规模

**用户故事：** 作为行内安全管理员，我希望免鉴权的健康检查接口不泄露用户数与 Agent 数，以便满足等保对信息泄露的要求。

#### 验收标准

1. 当匿名请求 `GET /api/health` 时，响应体的键集合应当恰好为 `ok`、`started_at`、`db`，不含 `users_loaded` 与 `agents_running`。
2. 系统应当始终保持 `GET /api/health` 免鉴权，并且在未绑定数据库时返回 `db: false`；`tests/integration/test_auth_flow.py`、`test_setup_database.py`、`test_setup_wizard.py`、`test_dashboard_serve.py` 中的 health 断言不改即通过，`dashboard/src/api/probeHealth.ts` 不改。

### 需求 8：容器部署透传与入口脚本契约

**用户故事：** 作为容器平台运维，我希望在 `docker/.env` 里写的新开关确实进入容器，并且库结构未预置时入口脚本给出明确退出码，以便部署问题可以被识别，而不是静默失效。

#### 验收标准

1. 系统应当始终让 `docker/docker-compose.yml` 的 `environment` 列表包含 7 个新变量（`OCTOP_DB_AUTO_MIGRATE` 与 6 个 `OCTOP_DB_POOL_*`），写法为 `- NAME=${NAME:-}`；`tests/unit/test_docker_compose_database_env.py` 同时校验 `_DATABASE_ENV_KEYS` 与新增的 `_DATABASE_RUNTIME_ENV_KEYS`。
2. 如果在 verify-only 下执行 `octop init --if-needed` 时库结构未预置或落后，那么应当以退出码 5 结束，不创建用户，不向 `~/.octop` 写凭据；`w2-01` 的入口脚本对该码按"其他错误"原码退出，不进入改密重试。

### 需求 9：psycopg 对金仓/openGauss 的兼容验证

**用户故事：** 作为项目负责人，我希望在投入回归之前就知道 psycopg 能否连上目标库、Octop 用到的 SQL 特性是否都可用，以便尽早决定选型或换驱动。

#### 验收标准

1. 当以 `OCTOP_TEST_DATABASE_URL` 指向目标库运行 `tests/integration/test_postgresql_family_compat.py` 时，应当逐项执行并报告以下特性：认证握手与 `server_version`、`INSERT … RETURNING id`、`UPDATE … RETURNING`、`ON CONFLICT … DO UPDATE` / `DO NOTHING`、`SELECT … FOR UPDATE`、`GENERATED BY DEFAULT AS IDENTITY`、带 `WHERE` 的部分索引、`JSONB` 与 `::jsonb`、`information_schema` 的表与列查询、`setval(pg_get_serial_sequence(...))`、同一语句执行次数超过 psycopg 预备阈值（5 次）、事务内 DDL 回滚、autocommit 下的 `CREATE INDEX CONCURRENTLY`。这些用例在 PostgreSQL 16 上应当全部通过。
2. `docs/intranet/database.md` 应当给出 DBA 侧的认证核查步骤（口令加密方式、`pg_hba` 认证方法、兼容模式、编码与时区、调整加密方式后须重设运行账号口令）、应用侧的核查命令（打印 psycopg 与 libpq 版本，连接后打印 `server_version`），以及逐项结果登记表。
3. 如果目标库只支持 libpq 不支持的认证方式（例如 openGauss 的 sha256 或 SM3），那么核查步骤应当给出明确结论："需 DBA 为运行账号改用 md5 或 scram-sha-256，否则需要更换驱动"，并登记为阻断项。

### 需求 10：真实国产库集成回归

**用户故事：** 作为项目负责人，我希望在行方真实的金仓/openGauss 实例上跑完全部 PG 用例与人工验收脚本，以便交付前掌握每一项兼容结论。

#### 验收标准

1. 当设置 `OCTOP_TEST_DATABASE_URL` 指向行方实例、`OCTOP_TEST_DATABASE_DRIVER` 为 `kingbase` 或 `opengauss` 并执行 `make test-postgresql` 时，全部 `postgresql` 用例应当以该驱动构造 Octop 配置执行，结果逐条登记进 `docs/intranet/database.md`。
2. 当在行方实例上执行人工验收（导出 DDL → DBA 执行 → 授权 → DML 角色加 verify-only 启动 → `octop db check` → 登录 → 建 Agent → 一轮对话）时，每一步的结果都应当登记；"一轮对话"依赖可用的 OpenAI 兼容模型端点，`w2-04` 合入前可以标为"待 w2-04"。
3. 如果回归发现某项 SQL 特性在目标库上不可用，那么应当登记为阻断项并给出处置（改写方案与工作量），不得通过跳过用例让 `make test-postgresql` 变绿（`pg_strict` 插件会让跳过直接判为失败）。
