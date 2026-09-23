# 设计文档：fork 独立迁移空间

> spec：`w0-01-fork-migration-namespace` ｜ 波次：Wave 0 ｜ 基线：`757fd12` ｜ 预估：4.5 人日
> 前置：无 ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 概述

**结论：** 新增 `src/octop/infra/db/fork_migrate.py`，负责 fork 迁移的发现、`_fork_schema_version` 水位的读写，以及按事务执行的 runner。改动上游的地方只有四处：

- `run_migrations` 末尾加一处惰性导入和一次调用（3 行）。这一处就覆盖了 src 里全部 10 个迁移入口和测试里的全部调用。
- `BackupManifest` 加一个整数字段。
- `restore_system_backup` 加一段 fork 水位预检和一行水位重置。
- AGENTS.md §7 改写迁移段。

fork 迁移不占上游版本号，也不改 `_schema_version`，所以不碰上游的 clamp 阶梯，也不碰 16 处版本断言。本 spec 不新增配置键、不新增 ErrorCode、不改 HTTP 响应、不改前端。

## 现状

以下事实均在基线 `757fd12` 上亲自核实。

### 迁移发现与水位

- `src/octop/infra/db/migrate.py` 的 `_MIGRATIONS_DIR`（≈L19）是 `Path(__file__).parent / "migrations"`。`_discover`（≈L39）在 PG 下用 `^(\d{3})_.*\.pg\.sql$`（≈L46），在 SQLite 下先排除 `.pg.sql` 再用 `^(\d{3})_.*\.sql$`（≈L50）。发现重复版本号时 `raise RuntimeError`（≈L57）。
- **实测：** 把基线全部 30 个迁移文件复制到草稿目录，再加入 `fork001_x.sql`、`fork001_x.pg.sql`、`fork016_y.sql`，然后把 `_MIGRATIONS_DIR` 指向该目录。结果真实的 `_discover("sqlite")` 与 `_discover("postgresql")` 都只返回 15 个文件，没有任何 fork 文件；`_max_discovered_version` 两种方言都是 15。原因是 `re.match` 从字符串开头匹配，`f` 不是数字。
- `_schema_version` 是单行单列表，由 `001_initial.sql`（≈L269）与 `001_initial.pg.sql`（≈L263）创建。每个迁移文件自己写水位，例如 `015_sso_provider_kind.sql` 末行是 `UPDATE _schema_version SET version = 15;`。`_current_version`（≈L65）遇到任何异常都返回 0。
- 基线 `migrations/` 下有 `001`–`015` 共 15 对、30 个文件，没有 `016`，也没有任何 `fork*` 文件。

### `run_migrations` 的执行顺序

- `run_migrations`（≈L1676）的顺序是：
  1. 仅 SQLite 先调 `_repair_legacy_schema`（≈L1678）；
  2. 上游编号循环，`if version <= _current_version(db): continue`（≈L1680）；
  3. `_reconcile_pre_squash_schema_version`（≈L1701）；
  4. 12 个无条件的 `_ensure_*`，止于 `_ensure_sso_provider_kind_schema`（≈L1713）。
- `_repair_legacy_schema`（≈L1411）在编号循环**之前**就会调用多种 `_ensure_*`。所以只要把新列折进既有 helper，就会出现"库先拿到列、随后编号迁移的裸 `ALTER` 重放时报 duplicate column"的顺序陷阱（`shared.txt` 第 10 节引用的 S20 结论）。
- `_reconcile_pre_squash_schema_version`（≈L1453）在 `current <= max_version` 时直接返回（≈L1462）。否则 PG 分支跑完 `if max_version >= 7 … >= 15` 阶梯（止于 ≈L1490），把水位写成 max（≈L1492）；SQLite 分支同样跑到 `>= 15`（≈L1528），写成 max（≈L1530）。这条路径**不执行任何迁移文件**。
- `_apply_sqlite_migration`（≈L1538）对版本 2–15 逐一走幂等分支（最后一个是 ≈L1666 的 `if version == 15`）。其余版本走 `conn.executescript(sql)` 兜底（≈L1671-1673）。sqlite3 的 `executescript` 会先隐式 COMMIT，所以这条兜底路径**不是事务化**的。
- 现有测试里没有真正让 `current > max` 的 clamp 用例：`tests/unit/db/test_db_pool.py::test_ahead_of_max_schema_version_clamps_to_max`（≈L342）实际把版本设成 8，`test_pre_squash_schema_version_clamped_and_knowledge_tables_filled`（≈L425）设成 13，两者都低于 15。

### 连接池与事务

- `src/octop/infra/db/pool.py`：`SqlitePool`（≈L33）用 `isolation_level=None`（≈L45）打开连接，`transaction()`（≈L60）显式执行 `BEGIN` / `COMMIT` / `ROLLBACK`；`PostgresPool.transaction()`（≈L164）用 psycopg 的 `conn.transaction()`。`_PgConnectionProxy.execute`（≈L114-115）会无条件把 `?` 改写成 `%s`。
- **实测：** 在 `SqlitePool.transaction()` 内依次执行 `CREATE TABLE IF NOT EXISTS fork_demo …`、`ALTER TABLE users ADD COLUMN fork_x TEXT`、一个会失败的语句。异常之后 `fork_demo` 表与 `fork_x` 列都不存在，说明 SQLite 的 DDL 在该事务里可以整体回滚。
- `migrate.py` 的 `_split_pg_sql`（≈L23）按 `;` + 换行切分语句，并剥掉每段开头的整行注释；上游 PG 迁移就用它。

### 迁移入口（src 内 10 个 `run_migrations` 调用点）

| 入口 | 位置 |
|---|---|
| `OctopServer.start()` | `src/octop/infra/server.py` ≈L323 |
| `OctopServer.bind_control_plane()` | `src/octop/infra/server.py` ≈L347 |
| `assert_control_plane_database_empty()` | `src/octop/infra/db/rebind.py` ≈L89 |
| `rebind_control_plane()` | `src/octop/infra/db/rebind.py` ≈L127（随后 ≈L140 调 `build_shared_services`） |
| `open_cli_services()` | `src/octop/cli/support/db.py` ≈L27 |
| `octop init` | `src/octop/cli/commands/init.py` ≈L84 |
| `octop admin rotate-jwt-secret` | `src/octop/cli/commands/admin.py` ≈L120 |
| `octop backup create` | `src/octop/cli/commands/backup.py` ≈L56 |
| `octop backup auto run` | `src/octop/cli/commands/backup.py` ≈L125 |
| `restore_system_backup()` | `src/octop/infra/backup/system_archive.py` ≈L534 |

打开了库但不迁移的只有两处：`src/octop/infra/db/probe.py`（≈L34，只执行 `SELECT 1`），以及 `octop backup restore`（`cli/commands/backup.py` ≈L178，迁移发生在 `restore_system_backup` 内部）。`src/octop/infra/history/store.py`（≈L64）打开的是独立的 history 库，不走控制面迁移。首装向导的 `POST /setup/database`（`src/octop/api/routers/setup.py` ≈L271）先调 `assert_control_plane_database_empty`，再按是否已绑定选择 `rebind_control_plane` 或 `bind_control_plane`（≈L296-301）。

### 备份与恢复

- `src/octop/infra/backup/manifest.py`：`MANIFEST_VERSION = 1`（≈L9）。`BackupManifest`（≈L20）有 `schema_version` 字段；`from_dict`（≈L58）对缺失键一律给默认值。`_extract_manifest_from_dir`（`system_archive.py` ≈L360）会拒绝 `manifest_version != 1` 的包，所以**不能**通过提升 `MANIFEST_VERSION` 来加字段。
- `system_archive.py`：`_build_manifest`（≈L140）用 `_current_version` 读取上游水位（≈L157）。四个备份入口（`api/routers/backup.py` ≈L112 手动备份、≈L162 导出、`infra/backup/auto.py` ≈L168 自动备份、`cli/commands/backup.py` ≈L62）都经过 `create_system_backup`（≈L187）。
- `restore_system_backup` 的流程：先校验驱动一致；再在**替换库之前**用 `_max_discovered_version(pool.dialect)` 预检（≈L477-487），不通过就抛 `BACKUP_SCHEMA_INCOMPATIBLE`，`details` 两键；然后替换库，PG 走 `restore_postgres`（≈L523），SQLite 走 `restore_sqlite_into_pool`（≈L526）；接着 `run_migrations(pool)`（≈L534），失败时包装成 `BACKUP_SCHEMA_INCOMPATIBLE`（≈L535-545）；最后在迁移之后才 `restore_preserved_chats`（≈L634）。
- SQLite 恢复用 sqlite 备份 API `src.backup(live)`（`infra/backup/snapshot.py` ≈L68），会整库覆盖。PG 恢复用 `pg_restore --clean --if-exists --no-owner`（`infra/backup/pg_dump.py` ≈L47-60），**只删除并重建转储中存在的对象**；转储里没有的表会原样留在当前库。PG 转储是整库 `pg_dump -Fc`，只用 `--exclude-table-data` 排除聊天表的数据（≈L23-35）。
- `ErrorCode.BACKUP_SCHEMA_INCOMPATIBLE`（`src/octop/infra/errors.py` ≈L19）已在 `_DEFAULT_STATUS` 中登记为 400（≈L121）。后端文案 `src/octop/i18n/{en,zh}.json` ≈L315 与前端 `dashboard/src/locales/{en,zh}.json` ≈L81 都只插值 `archive_schema_version` 与 `runtime_schema_version`。`tests/unit/backup/test_system_archive.py::test_refuse_newer_schema_backup_before_database_replace`（≈L1188）在 ≈L1233-1236 断言 `details` 恰为这两个键。
- 恢复接口 `POST /api/backup/files/{filename}/restore`（`api/routers/backup.py` ≈L317）直接返回 `{"ok": True, "name": …, **result}`。

### 测试与打包

- 16 处 `== 15` 类水位断言分布在 8 个文件：`tests/unit/db/test_db_pool.py`（≈L100/172/309/334/369/452/658）、`test_clip_thread_title.py` ≈L85、`test_agent_profile_columns.py` ≈L122、`test_skill_package_icons.py` ≈L94/113、`test_repo_knowledge.py` ≈L53、`test_skill_packages_repo.py` ≈L31、`test_published_experts_repo.py` ≈L30、`tests/unit/backup/test_system_archive.py` ≈L1181/1235。`test_db_pool.py` ≈L614 的 `== 7` 是"迁移到 v7 中途"的断言，不是水位断言。
- 枚举表名的既有用例都是子集或否定断言（如 `test_db_pool.py::test_run_migrations_creates_tables` ≈L36 用 `expected.issubset(names)`），新增 `_fork_schema_version` 表不会让它们变红。`tests/unit/db/test_migrate_discovery.py` 只断言 `.sql` / `.pg.sql` 分流。
- 存在只含 `users` 表的残缺库用例：`tests/unit/test_user_locale.py::test_legacy_users_table_gets_locale_column`（≈L36）在版本 8 的 users-only 库上跑 `run_migrations`。
- `pyproject.toml` ≈L106 的 `"src/octop/**/*.sql"` 会把同目录的 fork 文件一并打进 wheel；≈L208 已注册 `postgresql` marker。`tests/support/postgresql.py` 的 `requires_postgresql` 在缺少 `OCTOP_TEST_DATABASE_URL` 时 skip；`tests/integration/test_postgresql_control_plane.py` 已有 `_reset_public_schema` 与 `test_pg_backup_roundtrip` 可以照抄。
- AGENTS.md ≈L221-232 是迁移段，其中 ≈L223 写着 "`currently \`v == 7\``"。

## 方案

### 为什么选独立命名空间

| 方案 | 结论 | 原因 |
|---|---|---|
| fork 也写 `016_*` | 否决 | 与上游未来的 `016` 撞号，`_discover` 直接 `RuntimeError`，实例起不来；还必须在 clamp 两个分支和 `_apply_sqlite_migration` 里加钩子（S09 corrections[1]），并改 16 处断言（S12 corrections[1]）。 |
| 高位号段（如 `900_`） | 否决 | 单值水位记到 900 之后，上游的 `016`、`017` 会因 `version <= current` 被永久静默跳过。 |
| 折进 `run_migrations` 尾部的 `_ensure_*` | 否决 | 每个 spec 都要改热点文件 `migrate.py`（全局约束 §5 要求这里只留单行调用）；还会踩上面说的 `_repair_legacy_schema` 顺序陷阱；而且无法表达"建表 + 回填"这类一次性数据迁移。 |
| `forkNNN_*` + 独立 runner + 独立水位 | **采纳** | 对上游循环不可见；`migrate.py` 只留一处调用；fork 内部按合入顺序取号；上游断言与 clamp 逻辑都不受影响。 |

### 为什么能避开 clamp 问题

S08 corrections[2] 与 S09 corrections[1] 指出，往上游号段加 `016` 有三个后果：

1. `_max_discovered_version` 变成 16，`current > 16` 的旧库被 clamp 到 16，但 `016` 文件从未执行。管理员权限回填因此丢失，全部 admin 被锁死。
2. clamp 的 PG 与 SQLite 两个分支都必须各加一条 `if max_version >= 16` 阶梯。
3. `_apply_sqlite_migration` 必须加 `if version == 16` 幂等分支，否则 `_repair_legacy_schema` 先加过列之后，`016` 的裸 `ALTER` 经 `executescript` 重放会报错，`test_run_migrations_idempotent`（≈L74）立刻变红。

fork 命名空间逐条消除这三点：

- **不改变 clamp 的输入：** `forkNNN_` 不匹配 `_discover` 的正则（已实测），所以 `_max_discovered_version` 不受任何 fork 文件影响。clamp 的触发条件和写回值都与基线一致，阶梯不需要任何新分支。
- **不依赖 clamp 的输出：** fork runner 只读写 `_fork_schema_version`，完全不看 `_schema_version`。一个被 clamp 的库（`_schema_version` 从 20 写回 15）的 fork 水位仍是它自己的值，runner 照常补齐缺失的 fork 迁移。
- **不走 SQLite 兜底路径：** fork SQL 不经过 `_apply_sqlite_migration` 的 `executescript` 兜底，而是由 runner 在事务中执行；也不折进 `_repair_legacy_schema` 或 `_ensure_*`，所以不存在"修复链先加列、迁移再重放"的双重执行。
- **顺序固定在最后：** runner 排在 clamp 与尾部 `_ensure_*` 之后，看到的永远是上游的最终结构。

### runner 执行语义

`run_fork_migrations(db)` 的步骤：

1. `_ensure_fork_version_table(db)`：执行 `CREATE TABLE IF NOT EXISTS _fork_schema_version (id INTEGER PRIMARY KEY CHECK (id = 1), version INTEGER NOT NULL)`，再执行 `INSERT INTO _fork_schema_version(id, version) VALUES (1, 0) ON CONFLICT (id) DO NOTHING`。SQLite 3.24+ 与 PG 系都支持这一写法。
2. `migrations = discover_fork_migrations(db.dialect)`，`max_v` 取最大版本，没有文件时为 0。
3. 读取 `current = current_fork_version(db)`。如果 `current > max_v`，记一条 WARNING（含两个数字）后直接返回，不改水位，不执行文件。这是为了防止程序回退后再升级时重复执行已应用的迁移。
4. 对每个 `version > current` 的迁移，在 `with db.transaction() as conn:` 内依次完成：
   - 重读水位（PG 加 `FOR UPDATE` 锁住这一行，防止两个进程同时迁移）；如果已经 `>= version` 就跳过；
   - 用 `_split_pg_sql` 切分文件，逐条 `conn.execute(stmt)`；
   - 若 `_FORK_PY_STEPS` 登记了该版本的步骤，调用 `step(conn, db.dialect)`；
   - 执行 `UPDATE _fork_schema_version SET version = ? WHERE id = 1`。

   事务提交后记一条 INFO 日志（包含文件名）。任何异常都会让整个事务回滚，异常原样抛出。

**SQL 书写约束**（写进 AGENTS.md，并由静态测试部分兜住）：

- 不写 `BEGIN` / `COMMIT`，因为 runner 已经开了事务。
- 语句以 `;` + 换行结束。
- 不写触发器：触发器体里的 `;` + 换行会被切分器切断。确实需要触发器时，改用 Python 步骤整条执行。
- 字面量里不出现 `?`：PG 代理会把它改写成 `%s`。
- `.pg.sql` 里的 `CREATE TABLE` / `CREATE INDEX` / `ADD COLUMN` 一律带 `IF NOT EXISTS`，`INSERT` 用 `ON CONFLICT DO NOTHING`。这与上游 `.pg.sql` 的一贯写法一致（如 `015_sso_provider_kind.pg.sql`），并保证 PG 恢复后重放不失败（见"备份与恢复"）。
- SQLite 的 `ALTER TABLE … ADD COLUMN` 没有 `IF NOT EXISTS` 语法。runner 的事务保证它只会被成功执行一次；SQLite 恢复会整库覆盖，不会留下残余列。

**Python 步骤**只用于 SQL 无法跨方言可靠表达的回填，例如按 JSON 数组剔除 `users.permissions` 里已删除的键（全局约束 1.6），以及需要先用 `_table_exists` 判断上游表是否存在的改动（用来兼容上面提到的 users-only 残缺库用例）。步骤必须幂等，只能用 `?` 占位符，不能自行提交事务。本 spec 不登记任何步骤。

**限制：** SQLite 的 `PRAGMA foreign_keys` 在事务内是空操作，所以需要"关外键、重建表"的迁移不在 runner 的支持范围内。遇到这类需求，由提出方 spec 单独评审。

### 接入点

`run_migrations` 末尾，紧跟 `_ensure_sso_provider_kind_schema(db)`（≈L1713）之后：

```python
    from octop.infra.db.fork_migrate import run_fork_migrations  # noqa: PLC0415 — fork hook

    run_fork_migrations(db)
```

- 用惰性导入，是为了让 `fork_migrate` 可以在模块顶层导入 `migrate` 的 `_split_pg_sql` / `_table_exists` 而不形成循环；写法沿用本文件 ≈L213 的既有惰性导入风格。
- 改动集中在一个 hunk、3 行之内。上游每次在尾部追加 `_ensure_*` 时，冲突只会是"相邻两行"。
- 接在 `run_migrations` 里而不是 10 个调用点逐一接线，有三个原因：一是不会漏掉入口；二是测试里 83 个文件中共 157 处直接调用 `run_migrations` 的地方（基线实测）也自动带上 fork 结构，后续 spec 的 repo 单测无需额外步骤；三是 CLI 离线路径 `open_cli_services` 不需要单独接线（这与全局约束 §2 里 utils 层策略需要单独接线的情况不同，因为 runner 不读配置）。

### 入口覆盖

| 入口 | 覆盖方式 | 验证用例 |
|---|---|---|
| `OctopServer.start()` | ≈L323 的 `run_migrations` | 同一 home 第二次启动（此时 SQLite 文件已存在，`should_defer_control_plane_db` 为假，走 `start` 路径） |
| `bind_control_plane()` | ≈L347 | `tests.support.app.octop_client(bind_database=True)` 的首装路径 |
| `assert_control_plane_database_empty()` | `rebind.py` ≈L89 | 直接调用，检查目标库水位 |
| `rebind_control_plane()` | `rebind.py` ≈L127，先于 ≈L140 的 `build_shared_services` | 已绑定、零用户时改写 `config.json` 指向新 SQLite 文件后调用 |
| `open_cli_services()` | `cli/support/db.py` ≈L27 | 直接调用 |
| `octop init` | `cli/commands/init.py` ≈L84 | Click `CliRunner`，设置 `OCTOP_HOME` |
| `octop admin rotate-jwt-secret`、`octop backup create`、`octop backup auto run` | 各自的 `run_migrations` | 由第 3 项需求的 AST 守卫加上"调用点不改"间接覆盖，不单独建用例 |
| 备份恢复 | `system_archive.py` ≈L534，外加本 spec 新增的预检与水位重置 | `tests/unit/backup/test_fork_schema_backup.py` 与 PG 用例 |

### 备份与恢复

1. **导出：** `BackupManifest` 在**字段末尾**追加 `fork_schema_version: int = 0`。`to_json` 输出该键；`from_dict` 用 `int(data.get("fork_schema_version", 0))` 读取。`MANIFEST_VERSION` 保持 1。上游程序读到带新键的包时会忽略它，fork 程序读到旧包时按 0 处理。`_build_manifest` 在读取 `schema_version` 的 try 块旁边，用同样的"异常即 0"方式读取 `current_fork_version(pool)`。
2. **恢复预检：** 在既有上游预检（≈L477-487）之后、任何替换动作之前，计算 `runtime_fork = max_fork_version(pool.dialect)`。如果 `manifest.fork_schema_version > runtime_fork`，抛出 `OctopError(BACKUP_SCHEMA_INCOMPATIBLE, …, details=…)`，其中 `details` 为：
   - `archive_schema_version`：字符串 `f"{manifest.schema_version}+fork{manifest.fork_schema_version}"`；
   - `runtime_schema_version`：字符串 `f"{runtime_schema_version}+fork{runtime_fork}"`；
   - `archive_fork_schema_version` 与 `runtime_fork_schema_version`：两个整数。

   这样既有文案模板不改就能读出"15+fork3 / 最高支持 15+fork2"，也不需要新增 i18n 键（本 spec 先于 `w0-04` 的 overlay）。上游预检分支的 `details` 保持两键不变。
3. **恢复后重置水位：** 库替换完成后，在 ≈L533 的 try 块内、`run_migrations(pool)` 之前调用 `set_fork_version(pool, manifest.fork_schema_version)`，失败时同样包装成 `BACKUP_SCHEMA_INCOMPATIBLE`。
   - 理由：SQLite 整库覆盖后，水位本来就等于转储里的值（或者表不存在）。PG 的 `pg_restore --clean` 却不会删除转储里没有的 `_fork_schema_version`（例如备份来自上游或本 spec 之前的构建），当前库的水位会残留下来，runner 就会以为 fork 结构已经齐全。
   - manifest 与转储由同一次 `create_system_backup` 写出，所以以 manifest 为准。
   - 之后 `run_migrations` 中的 runner 会补跑缺失的 fork 迁移。由于迁移发生在 `restore_preserved_chats`（≈L634）与用户回写之前，保存下来的行与迁移后的列集合一致。
4. **不改恢复结果：** `restore_system_backup` 返回的字典不新增字段，所以 HTTP 响应和 `str(result)` 审计载荷都不变，不需要更新 `docs/api-intranet.md`。

### AGENTS.md §7

1. 把 ≈L222-223 的 "then bump the version assertion in `tests/unit/db/test_db_pool.py` (currently `v == 7`)" 改为：

   > then bump every `_schema_version` assertion (currently `15`, spread over 8 test files under `tests/unit/db/` plus `tests/unit/backup/test_system_archive.py`; the mid-upgrade `== 7` in `test_db_pool.py` is not a watermark assertion)

2. 在 ≈L232 之后新增一段：

   > **Fork migrations (intranet fork only):** never add an upstream-numbered `NNN_` file in this fork. Write schema changes as `infra/db/migrations/forkNNN_description.sql` **and** `forkNNN_description.pg.sql`. They are invisible to `_discover` and are applied by `run_fork_migrations()` (`infra/db/fork_migrate.py`), the last call in `run_migrations()`, against their own `_fork_schema_version` watermark — `_schema_version` and its test assertions never change for fork work. Specs write `forkNNN_<description>`; take the next free number when merging into the fork mainline. A merged fork file is immutable: fix forward with a new number. Each file runs in one transaction with its watermark bump: no `BEGIN`/`COMMIT`, end statements with `;` + newline, no triggers, no `?` inside literals; `.pg.sql` must use `IF NOT EXISTS` / `ON CONFLICT DO NOTHING`. Backfills that SQL cannot express portably, or that must guard against a missing upstream table, go in an idempotent Python step registered in `_FORK_PY_STEPS`. Never fold fork schema into `_repair_legacy_schema`, `_ensure_*` helpers, `_apply_sqlite_migration`, or the `_reconcile_pre_squash_schema_version` ladder.

§5 / §9 的勘误不在本 spec 内（归 `w0-04`），以免两个 spec 同时改这个文件的同一区域。

## 组件与接口

| 文件 | 类型 | 改动 |
|---|---|---|
| `src/octop/infra/db/fork_migrate.py` | 新增 | fork 迁移发现、水位、runner、Python 步骤登记表 |
| `src/octop/infra/db/migrate.py` | 修改 | `run_migrations` 末尾加惰性导入与一次调用（≤3 行） |
| `src/octop/infra/backup/manifest.py` | 修改 | `BackupManifest` 末尾加 `fork_schema_version`；`to_json` / `from_dict` 各加一行 |
| `src/octop/infra/backup/system_archive.py` | 修改 | 导入 fork 水位函数；`_build_manifest` 读取 fork 水位；`restore_system_backup` 加 fork 预检与水位重置 |
| `AGENTS.md` | 修改 | §7 迁移段（见上） |
| `tests/support/fork_migrations.py` | 新增 | 测试辅助：在 `tmp_path` 写出示例 fork 迁移对，并 monkeypatch `_FORK_MIGRATIONS_DIR` |
| `tests/unit/db/test_fork_migrate.py` | 新增 | 发现、水位、runner、接入顺序、clamp、AST 守卫、仓库静态检查 |
| `tests/unit/backup/test_fork_schema_backup.py` | 新增 | manifest 往返、导出携带、恢复预检、旧包补跑、水位重置 |
| `tests/integration/test_fork_migration_entrypoints.py` | 新增 | start / bind / assert_empty / rebind / open_cli_services / `octop init` |
| `tests/integration/test_postgresql_fork_migrations.py` | 新增 | PG 门控用例 |

`fork_migrate.py` 的公开接口：

```python
_FORK_MIGRATIONS_DIR: Path  # = Path(__file__).parent / "migrations"，与上游同目录；测试 monkeypatch 此属性
_FORK_FILE_RE: re.Pattern[str]  # ^fork(\d{3})_[a-z0-9_]+(\.pg)?\.sql$
ForkPyStep = Callable[[Any, str], None]  # (事务连接, dialect)；必须幂等、只用 ? 占位符
_FORK_PY_STEPS: dict[int, ForkPyStep] = {}  # 版本号 -> 步骤；本 spec 为空

def discover_fork_migrations(dialect: str) -> list[tuple[int, Path]]:
    """按方言返回 (版本, 路径)，升序；重号或以 fork 开头的畸形文件名 -> RuntimeError。"""

def max_fork_version(dialect: str) -> int: ...
def current_fork_version(db: DatabasePool) -> int:
    """表不存在（经 migrate._table_exists 判断）时返回 0。"""

def set_fork_version(db: DatabasePool, version: int) -> None:
    """建表（若缺）并 upsert id=1 行；供恢复路径使用。"""

def run_fork_migrations(db: DatabasePool) -> None: ...
```

模块边界：`fork_migrate.py` 位于 `infra/db/`，只依赖 `infra/db/migrate`、`infra/db/pool` 与标准库，不读 `octop.config`，符合 AGENTS.md §5。`system_archive.py` 的导入由 `infra/backup` 指向 `infra/db`，与它现有的 `from octop.infra.db.migrate import …`（≈L42）同向。

## 数据模型

- **水位表 `_fork_schema_version`**（基础设施表，由 runner 用 `CREATE TABLE IF NOT EXISTS` 自建，不是 `forkNNN_` 迁移）：
  - `id INTEGER PRIMARY KEY CHECK (id = 1)`
  - `version INTEGER NOT NULL`

  初始行为 `(1, 0)`，不需要回填。上游代码不认识该表，会忽略它。SQLite 备份整库带走它，PG 的 `pg_dump` 整库转储也包含它。
- **业务迁移：** 无。本 spec 不提交任何 `forkNNN_<描述>` 文件。第一个真实的 fork 迁移由最先合入 fork 主干、且需要改表的 spec 取 `fork001`。
- **备份 manifest：** `manifest.json` 新增整数键 `fork_schema_version`，缺省为 0。

## 配置

无。runner 没有开关，也不读 `octop.config`。

## 错误处理

- **不新增 ErrorCode。** 恢复预检复用既有的 `BACKUP_SCHEMA_INCOMPATIBLE`，它已在 `_DEFAULT_STATUS` 登记为 400（`errors.py` ≈L121）。details 的构造方式见"备份与恢复"。
- 发现阶段遇到 fork 重号或畸形文件名时抛 `RuntimeError`，与上游 `_discover` 对重号的处理一致：`run_migrations` 失败，实例拒绝启动，日志中有明确的文件名。
- 迁移执行失败时，数据库驱动抛出的异常原样上抛：启动路径表现为启动失败；恢复路径由 ≈L535-545 的既有逻辑包装成 `BACKUP_SCHEMA_INCOMPATIBLE`。
- 程序回退（库内 fork 水位高于程序的最大版本）时只记 WARNING，不抛异常，与上游 clamp"不阻塞启动"的取向一致。但与上游不同，runner 不回写水位，避免之后再升级时重复执行已经应用过的迁移。
- manifest 中的 `fork_schema_version` 不是整数时，`int()` 抛出的 `ValueError` 会被 `_extract_manifest_from_dir` 既有的 `except (json.JSONDecodeError, ValueError, TypeError, OSError)` 捕获，转成 `SLASH_BAD_ARGS "invalid manifest"`。

## 安全考虑

- **原子性：** 每个 fork 迁移连同水位推进在一个事务里完成，避免半迁移状态。这是对上游 SQLite `executescript` 兜底路径的改进，也是运维"失败可重试"的前提。
- **输入面：** runner 只执行随 wheel 打包、由代码评审把关的 SQL 文件；文件名受正则约束，不拼接任何外部输入。Python 步骤以代码形式登记，不从目录动态导入模块。
- **权限：** runner 需要控制面账号具备 DDL 权限，与上游迁移相同。行方若要求"运行账号无 DDL"，由 `w2-03` 的运行期 DDL 关闭与 DDL 导出统一处理，并且必须把 fork 迁移一并纳入（见交接）。
- **防回退误用：** 程序回退时不回写水位，恢复更新版本的 fork 备份时在替换库之前拒绝，二者共同避免"旧代码跑在新结构上、之后又被错误重放"的情况。
- **审计：** 迁移是启动期行为，不写 `audit_log`，只记应用日志（文件名、版本号）。审计字段集归 `w3-02`，本 spec 不动。

## 测试策略

测试先行：每个实现任务都先提交会失败的用例。示例 fork 迁移由 `tests/support/fork_migrations.py` 写到 `tmp_path`，并 monkeypatch `octop.infra.db.fork_migrate._FORK_MIGRATIONS_DIR`，**不向仓库的 `migrations/` 目录写入任何文件**。示例迁移为：

- `fork001_demo`：`CREATE TABLE IF NOT EXISTS fork_demo (id INTEGER PRIMARY KEY, note TEXT)`
- `fork002_demo_ref`：`CREATE TABLE IF NOT EXISTS fork_demo_ref (id INTEGER PRIMARY KEY, identity_id INTEGER REFERENCES user_sso_identities(id))`，用来证明 fork 迁移排在上游 `015` 之后

两者的 PG 版本都带 `IF NOT EXISTS`，引用列与主键使用 `BIGINT`，与上游 `015_sso_provider_kind.pg.sql` 的 `user_sso_identities.id BIGINT` 保持一致。

**单元（SQLite）：**

- `tests/unit/db/test_fork_migrate.py`：
  - 上游 `_discover` 与 `_max_discovered_version` 在混入 fork 文件的目录副本上结果不变；
  - fork 文件的方言分流与排序；重号；畸形文件名；
  - 建水位表并写初始行；逐版本推进；幂等；失败回滚（含 Python 步骤失败）；程序回退时的 WARNING（`caplog`）；单行约束；`_schema_version` 不变；
  - 接入顺序：全新库与 v14 库上 `fork002_demo_ref` 都成功；clamp：`_schema_version` 置为 20 之后，上游回到 15、fork 水位为 2；
  - AST 守卫：`run_migrations` 的最后一条语句是 `run_fork_migrations(db)`；
  - 仓库静态检查：真实 `migrations/` 目录的 fork 成对、`.pg.sql` 带 `IF NOT EXISTS`、`_FORK_PY_STEPS` 的每个键都有 SQL 对。
- `tests/unit/backup/test_fork_schema_backup.py`：
  - manifest 往返；旧 manifest 缺键时为 0；
  - `create_system_backup` 产出的 manifest 带水位；
  - 恢复不含该键的旧包之后，fork 迁移被补跑；
  - 恢复 `fork_schema_version` 更高的包时在替换之前被拒绝，`details` 四键齐全，标记行仍在；
  - 用 monkeypatch 把 `restore_sqlite_into_pool` 替换为"不替换库"的桩，模拟 PG `--clean` 留下当前库水位，断言水位先被重置为 manifest 值、再被 runner 推进到最大值。
- 回归：`tests/unit/db` 与 `tests/unit/backup` 的既有用例不改动，全部通过。

**集成：**

- `tests/integration/test_fork_migration_entrypoints.py` 覆盖入口表中的六个入口。使用 `tmp_octop_home`、`tests.support.app.octop_client`，`octop init` 用 Click `CliRunner`。

**PostgreSQL（门控）：**

- `tests/integration/test_postgresql_fork_migrations.py`，每个用例都加 `@requires_postgresql` 与 `@pytest.mark.postgresql`，并照抄 `_reset_public_schema`：
  - 事务应用、回滚与幂等；
  - clamp 的 PG 分支（`_schema_version` 置为 20）；
  - 备份往返携带 fork 水位；
  - 删除 `_fork_schema_version` 后备份，再让当前库推进到 2，然后恢复：断言水位先被重置为 0，再被补跑到 2，且 `fork_demo_ref` 存在。

  `w0-02` 合入前只在本地执行，合入后由 CI 的 postgres service 自动收集。

**前端：** 无改动，无用例。

**本地命令：**

```bash
uv run pytest tests/unit/db/test_fork_migrate.py -q
uv run pytest tests/unit/db tests/unit/backup -q
uv run pytest tests/integration/test_fork_migration_entrypoints.py -q
# PG：先起一个专用库（行内镜像源替换 postgres:16），测试会 DROP SCHEMA public
docker run -d --name octop-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=octop_test -p 15432:5432 postgres:16
OCTOP_TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:15432/octop_test uv run pytest tests/integration/test_postgresql_fork_migrations.py tests/integration/test_postgresql_control_plane.py -m postgresql -q
uv run pytest tests/integration/test_postgresql_fork_migrations.py -q -rs   # 未设 URL 时应全部 skip
make all
```

## 与其他 spec 的交接

**依赖：** 无。本 spec 属于 Wave 0，可以与 `w0-02` 到 `w0-05` 并行合入。

**交付给：**

- **全部需要改表的 spec**（`w1-02`、`w1-03`、`w1-05`、`w2-03`、`w3-02`、`w3-03`、`w3-04`、`w3-05`、`p2-03`、`p2-05`、`p2-08` 等）：
  - 提供 `forkNNN_` 命名、runner、水位与 `_FORK_PY_STEPS`；
  - 它们的 design.md 只写 `forkNNN_<描述>`，合入前再定号；
  - 它们不改上游版本断言，不在 clamp 阶梯或 `_apply_sqlite_migration` 里加分支。
- **`w1-02` / `w1-03` / `w1-05` / `w3-03`（删除权限键后清洗存量值，全局约束 1.6）：** 建议用 Python 步骤按 JSON 数组剔除键，并用 `_table_exists(db, "users")` 守卫，兼容 users-only 的残缺库用例。
- **`w3-05`：** 信封列用 fork 迁移添加。按 S09 corrections[1]，rewrap 保持为独立函数，由各入口显式调用，不放进 runner。
- **`w2-03`（方言家族）：** 把 `dialect` 改成真实驱动名时，必须同步家族化 `discover_fork_migrations(dialect)` / `max_fork_version(dialect)`（与 `_discover` 以及 `system_archive.py` ≈L477 同类，见 S12 corrections[0]）。本 spec 在 `system_archive.py` 新增的 `max_fork_version(pool.dialect)` 调用同样要传家族名。关闭运行期 DDL 或只校验模式时，要同时校验 `_fork_schema_version == max_fork_version`。DDL 导出要在上游文件之后按序输出 fork 文件。
- **`w0-02`：** CI 的 postgres service 需要收集本 spec 的 `tests/integration/test_postgresql_fork_migrations.py`（`-m postgresql`）。
- **`w0-04`：** 上游同步手册需要写入两条：
  1. 同步后确认 `run_migrations` 末尾的 fork 调用还在（AST 守卫会让 `make test` 变红）；
  2. 核对上游新增的 `NNN_` 迁移，看是否与 fork 已建的表或列同名。

  另外，在 `CHANGELOG-intranet.md` 建立时补录本 spec 的条目。
- **`p2-08`（单活租约）：** 迁移应当在拿到租约之后执行。runner 的 PG `FOR UPDATE` 只是兜底，不能替代租约。
- **`w4-02`（运维最小集）：** 升级与回滚手册中写明两点：用 `SELECT version FROM _fork_schema_version` 检查 fork 水位；PG 恢复优先恢复到空 schema（原因见风险）。

**看似相关、实际归别的 spec：**

| 内容 | 归属 |
|---|---|
| 源 JSON 里的 `016_admin_permission_backfill`、CLI `grant` / `revoke`、启动自愈（S08） | `w3-03`（测试侧基线归 `w0-03`） |
| `016_secret_envelopes` 与 rewrap（S09） | `w3-05` |
| `016_instance_lease`（S12） | `p2-08` |
| `migrate.py` 的 26 处方言判断家族化、`allow_ddl`、`qmark_to_pyformat` 转义、`_ensure_usage_cache_schema` 条件化（S12） | `w2-03` |
| AGENTS.md §5 / §9 勘误 | `w0-04` |

备份包加密、`.octbk` 后缀、`config.json` 口令落盘（S09）都不在本 spec 范围。本 spec 只在 manifest 里增加一个整数字段，将来变更备份格式时需要保留该字段。

## 风险与回滚

| 风险 | 影响 | 缓解 |
|---|---|---|
| 上游同步解冲突时丢掉 `run_migrations` 末尾的 fork 调用 | fork 迁移静默不执行 | AST 守卫与行为用例让 `make test` 直接变红；`w0-04` 的同步手册单列检查项 |
| 上游以后新增与 fork 同名的表或列 | 上游 `NNN_` 迁移报"已存在"，实例起不来 | 同步手册核对上游新迁移；fork 新表建议用领域前缀命名（由各 spec 自定） |
| PG `pg_restore --clean` 不删除转储之外的对象：恢复旧包后，较新 fork 迁移建的表连同其中的数据会残留 | `.pg.sql` 若没写 `IF NOT EXISTS` 会重放失败；残留行是恢复点之后的数据 | 静态测试强制 `.pg.sql` 使用 `IF NOT EXISTS`；恢复后水位按 manifest 重置；`w4-02` 的运维手册要求 PG 恢复到空 schema。这是上游 PG 恢复的既有语义，本 spec 不改 `pg_dump.py` |
| fork 迁移号按合入顺序确定，开发者本地库可能已用改号前的号码跑过 | 本地库跳过真正的 `forkNNN` | 仅影响开发环境；AGENTS.md 写明"合入后不可改"，改号后重建本地库 |
| 后续 fork 迁移 `ALTER` 上游表，碰上测试里的 users-only 残缺库 | 既有用例变红 | 交接中要求用 Python 步骤配合 `_table_exists` 守卫 |
| SQLite 事务内不能切换 `PRAGMA foreign_keys` | 需要关外键重建表的迁移无法通过 runner 执行 | 写明为 runner 限制，遇到时由提出方 spec 单独评审 |
| 多进程同时首次升级（CLI 离线命令与服务同时启动） | SQLite 出现 `database is locked`，或 PG 重复执行 | 事务内重读水位；PG 用 `FOR UPDATE`；与上游迁移的并发语义一致 |

**回滚：** 本 spec 的全部改动都是增量的，也不提交任何 fork 迁移文件，因此回滚就是 `git revert` 对应提交。已经建出的 `_fork_schema_version` 表对上游代码无害（未知表会被忽略，备份会带上它）。如果之后已有 spec 基于本 runner 提交了 fork 迁移，需要先回滚那些 spec，再回滚本 spec。

## 待行方确认

- **D3（控制面数据库）：** 默认 PG 系（人大金仓或 openGauss）。runner 依赖以下能力：事务化 DDL、`CREATE TABLE IF NOT EXISTS`、`INSERT … ON CONFLICT (id) DO NOTHING/UPDATE`、`SELECT … FOR UPDATE`，PG 系都支持。若答复为达梦 / OceanBase / TiDB，fork 发现需要识别第三种后缀，这属于 D3 的另立项范围。
- **D7（长期 fork）：** 独立迁移空间以"长期 fork、每 2–4 个上游 release 同步一次"为前提。若改为一次性冻结、不再跟随上游，本机制仍然成立，只是同步手册中的检查项可以删除。
