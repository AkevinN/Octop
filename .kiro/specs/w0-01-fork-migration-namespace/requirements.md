# 需求文档：fork 独立迁移空间

> spec：`w0-01-fork-migration-namespace` ｜ 波次：Wave 0 ｜ 基线：`757fd12` ｜ 预估：4.5 人日
> 前置：无 ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 引言

**结论：** 本 spec 给行内 fork 建一套与上游 `NNN_` 编号完全隔离的迁移空间，包括 `forkNNN_*.sql` / `forkNNN_*.pg.sql` 成对文件、独立 runner `run_fork_migrations`、独立水位表 `_fork_schema_version`。runner 挂在 `run_migrations` 的最末尾，因此 src 里全部 10 个迁移入口和测试里的全部调用都会自动经过它。备份 manifest 同时带上 fork 水位，恢复前做预检，恢复后重置水位。最后更正 AGENTS.md §7 的迁移说明。本 spec 自身不新增任何业务表。

### 背景

- 上游迁移由 `src/octop/infra/db/migrate.py` 的 `_discover` 按 `^(\d{3})_.*\.sql$` / `^(\d{3})_.*\.pg\.sql$` 发现。遇到重复版本号时，`_discover` 会在 `run_migrations` 第一步直接 `raise RuntimeError`，表现为实例起不来，而不是测试变红。上游下一个迁移必然是 `016`。在源分析里，有 11 个以上的改造 spec 都各自声明了 `016`。
- `run_migrations` 用单值水位线 `_schema_version` 判断是否跳过，所以任何"高位号段"方案都会让上游以后的迁移被永久静默跳过。
- `_reconcile_pre_squash_schema_version` 遇到 `current > max_version` 的库时，会跳过全部迁移文件，只跑阶梯里显式列出的 `_ensure_*`，然后把水位直接写成上游最大版本。往上游号段里加 `016`，会让这类库被 clamp 到 16，却从未执行过 016 的回填（S08 corrections[2]、S09 corrections[1] 已详细论证）。
- 已实测：把 `fork001_x.sql`、`fork001_x.pg.sql`、`fork016_y.sql` 放进迁移目录副本后，真实的 `_discover("sqlite")` 与 `_discover("postgresql")` 都只返回 15 个上游文件，`_max_discovered_version` 仍为 15。

### 为什么做

全局约束 1.1 规定：fork 的表结构变更一律走本 spec 提供的独立迁移空间。Wave 1 之后所有需要建表、加列、清洗存量数据的 spec（`w1-02`、`w1-03`、`w1-05`、`w3-02`、`w3-03`、`w3-04`、`w3-05`、`p2-*` 等）都以它为地基。不先交付它，任意两个 spec 并行写迁移都会撞号，而撞号的后果是服务起不来。

### 范围内

1. 新模块 `src/octop/infra/db/fork_migrate.py`：负责 fork 迁移文件的发现、`_fork_schema_version` 水位的读写，以及按事务执行的 runner（含可选的 Python 步骤登记表）。
2. `run_migrations` 末尾的单处接入，以及 SQLite `_repair_legacy_schema`、clamp 路径与 fork runner 之间的顺序保证。
3. 覆盖全部启动与迁移入口的测试：`OctopServer.start()`、`bind_control_plane()`、`assert_control_plane_database_empty()` / `rebind_control_plane()`、CLI 离线 `open_cli_services()` 与 `octop init`、备份导出与恢复。
4. 备份 manifest 增加 `fork_schema_version`，并在 `restore_system_backup` 中加 fork 水位预检与恢复后水位重置。
5. PostgreSQL 方言的门控用例（设置 `OCTOP_TEST_DATABASE_URL` 时执行）。
6. AGENTS.md §7 迁移段：更正过期的 `v == 7`，写入 fork 迁移规则。

### 范围外（归属）

- 任何业务表、业务列、存量数据清洗。它们由各自的 spec 以 `forkNNN_<描述>` 提交，例如删权限键后的 `users.permissions` 清洗归 `w1-02` / `w1-03` / `w1-05` / `w3-03`，会话表归 `w3-04`，信封列归 `w3-05`，实例租约表归 `p2-08`。
- 分布在 8 个测试文件里的 16 处上游 `_schema_version == 15` 类断言。fork 迁移不改 `_schema_version`，所以这些断言一律不动（全局约束 1.1）。
- `migrate.py` 的方言家族化、关闭运行期 DDL、DDL 导出、连接池参数，归 `w2-03`。
- CI 的 postgres service 与前端 job 归 `w0-02`。本 spec 的 PG 用例在 `w0-02` 合入前只做本地门控执行。
- AGENTS.md §5 / §9 的勘误（不存在的 `api/jwt_tokens.py` 等）、`CHANGELOG-intranet.md` 的建立、上游同步手册，归 `w0-04`。
- 源 JSON 里的 `016_*` 方案（S08 管理员权限回填、S09 密钥信封、S12 实例租约）已被全局约束否决，本 spec 不实现，也不在上游 clamp 阶梯里加任何分支。

## 需求

### 需求 1：fork 迁移文件的命名与发现隔离

**用户故事：** 作为 fork 维护者，我希望 fork 的表结构变更使用 `forkNNN_` 独立命名，并由独立的发现函数识别，以便它们与上游 `NNN_` 迁移同放一个目录，却互不可见、永不撞号。

#### 验收标准

1. 当迁移目录中同时存在上游 `NNN_*.sql` 与 `forkNNN_*.sql` / `forkNNN_*.pg.sql` 时，上游 `_discover(dialect)` 与 `_max_discovered_version(dialect)` 应当返回与只有上游文件时完全相同的结果（`sqlite` 与 `postgresql` 各断言一次）。
2. 当调用 `discover_fork_migrations("sqlite")` 时，`fork_migrate` 应当只返回形如 `forkNNN_<描述>.sql` 且不以 `.pg.sql` 结尾的文件，并按版本号升序排列；调用 `discover_fork_migrations("postgresql")` 时应当只返回 `forkNNN_<描述>.pg.sql`。
3. 如果同一方言下有两个文件使用同一个 fork 版本号，那么 `discover_fork_migrations` 应当抛出 `RuntimeError`，消息里包含这两个文件名。
4. 如果迁移目录中存在以 `fork` 开头、以 `.sql` 结尾、但不符合 `^fork\d{3}_[a-z0-9_]+(\.pg)?\.sql$` 的文件，那么 `discover_fork_migrations` 应当抛出 `RuntimeError`，而不是静默忽略该文件。
5. 仓库中的 fork 迁移应当始终成对出现：每个 `forkNNN_<描述>.sql` 都有同名的 `forkNNN_<描述>.pg.sql`，反之亦然；`.pg.sql` 中的 `CREATE TABLE`、`CREATE INDEX`、`ADD COLUMN` 语句都带 `IF NOT EXISTS`；`_FORK_PY_STEPS` 的每个键都有对应的 SQL 对。以上由静态测试检查，本 spec 合入时目录里没有 fork 文件，该测试以空集通过。
6. 本 spec 的改动应当始终不新增任何 `NNN_*` 或 `forkNNN_*` 迁移文件，也不修改既有测试文件：`git diff --name-only 757fd12 -- src/octop/infra/db/migrations` 与 `git diff --name-only --diff-filter=M 757fd12 -- tests/` 的输出都为空。

### 需求 2：独立水位表与按事务执行

**用户故事：** 作为运维人员，我希望每个 fork 迁移要么完整生效并推进水位，要么完全不生效，以便升级失败时库不会停在半迁移状态，重启后也能从断点继续。

#### 验收标准

1. 当 `run_fork_migrations(db)` 在不存在 `_fork_schema_version` 的库上执行时，runner 应当创建该表并写入唯一一行（`id = 1`、`version = 0`），然后按版本升序应用全部 fork 迁移。
2. 当某个 fork 迁移执行成功时，runner 应当在同一事务内把 `_fork_schema_version.version` 更新为该版本号，并且 `_schema_version` 的值保持不变。
3. 如果某个 fork 迁移的任一语句或它登记的 Python 步骤抛出异常，那么该版本的全部改动与水位更新应当一并回滚，水位停在上一个成功的版本，异常向上抛出，使 `run_migrations` 失败。
4. 当 runner 在水位已经等于最大 fork 版本的库上再次执行时，runner 应当不执行任何迁移语句，水位保持不变。
5. 如果库中的 fork 水位高于当前程序发现的最大 fork 版本（程序被回退），那么 runner 应当不修改水位、不执行任何文件，并记录一条 WARNING 日志，日志中包含库内水位与程序最大版本。
6. 当某个版本在 `_FORK_PY_STEPS` 中登记了 Python 步骤时，runner 应当在该版本的 SQL 执行之后、水位更新之前，在同一个事务连接上调用该步骤。
7. `_fork_schema_version` 应当始终最多只有一行（主键 `id` 且带 `CHECK (id = 1)` 约束）。

### 需求 3：接入 `run_migrations` 与既有修复链路的顺序

**用户故事：** 作为 fork 维护者，我希望 fork runner 固定在上游全部迁移与修复之后执行，并且上游 clamp 逻辑完全感知不到 fork 迁移，以便 fork 迁移总能基于上游最终结构，也不需要在上游 clamp 阶梯里加任何分支。

#### 验收标准

1. 当 `run_migrations(db)` 执行时，fork runner 应当排在 SQLite 的 `_repair_legacy_schema`、上游编号迁移循环、`_reconcile_pre_squash_schema_version` 以及尾部全部 `_ensure_*` 之后，最后一个执行。
2. 当一个 fork 迁移引用由上游 `015` 新建的对象（如 `user_sso_identities`）时，在全新库和 `_schema_version = 14` 的库上执行 `run_migrations` 都应当成功，并且 fork 水位等于该迁移的版本号。
3. 如果库的 `_schema_version` 高于上游最大版本（例如被手工置为 20），那么执行 `run_migrations` 之后，`_schema_version` 应当被 clamp 为上游最大版本（既有行为不变），同时全部 fork 迁移都已应用，fork 水位等于最大 fork 版本。
4. `run_migrations` 的函数体应当始终以一次 `run_fork_migrations(db)` 调用结束。由 AST 静态守卫测试检查，防止上游同步解冲突时丢掉这一行。
5. `migrate.py` 相对基线的改动应当始终只出现在 `run_migrations` 末尾，且新增不超过 3 行；`_repair_legacy_schema`、`_apply_sqlite_migration`、`_reconcile_pre_squash_schema_version` 与各 `_ensure_*` 中不出现任何 fork 逻辑（`git diff 757fd12 -- src/octop/infra/db/migrate.py` 与 `rg -n fork src/octop/infra/db/migrate.py` 可观察）。

### 需求 4：覆盖全部启动与迁移入口

**用户故事：** 作为运维人员，我希望无论实例从哪条路径打开控制面库（正常启动、首装向导、向导内换库、CLI 离线命令、备份恢复），fork 迁移都已经应用，以便任何路径都不会拿到缺少 fork 结构的库。

#### 验收标准

1. 当 `OctopServer.start()` 在已有 SQLite 控制面库的 home 上启动时，`_fork_schema_version` 应当等于测试 fork 目录中的最大版本，且测试 fork 迁移建出的对象存在。
2. 当 `OctopServer.bind_control_plane()` 在首装向导中首次绑定控制面库时，新库的 fork 水位应当等于测试 fork 目录中的最大版本。
3. 当 `assert_control_plane_database_empty()` 检查目标库，以及 `rebind_control_plane(server)` 把控制面切换到新库时，新库在交给 `build_shared_services` 之前应当已应用全部 fork 迁移。
4. 当 CLI 离线路径 `open_cli_services()` 或 `octop init` 打开库时，库的 fork 水位应当等于测试 fork 目录中的最大版本。
5. fork runner 应当始终只经由 `run_migrations` 进入：src 里的 10 个 `run_migrations` 调用点不做改动；`rg -l "infra\.db\.fork_migrate" src/` 的输出只包含 `src/octop/infra/db/migrate.py` 与 `src/octop/infra/backup/system_archive.py`。

### 需求 5：备份导出与恢复携带 fork 水位

**用户故事：** 作为运维人员，我希望备份包记录 fork 水位，恢复时据此拒绝来自更新 fork 版本的包、补齐较旧包缺少的 fork 结构，以便"升级可回滚、备份可恢复"在 fork 迁移存在时依然成立。

#### 验收标准

1. 当通过任一入口（HTTP 手动备份、导出下载、自动备份、`octop backup` CLI，它们都经过 `create_system_backup`）创建系统备份时，`manifest.json` 应当包含整数字段 `fork_schema_version`，其值等于备份时库的 fork 水位。
2. 当恢复一个不含 `fork_schema_version` 字段的备份（上游产物，或本 spec 合入前的 fork 产物）时，系统应当按 0 处理；恢复完成后全部 fork 迁移都已应用，恢复成功。
3. 如果备份的 `fork_schema_version` 大于当前程序的最大 fork 版本，那么恢复应当在替换数据库之前以 `BACKUP_SCHEMA_INCOMPATIBLE`（HTTP 400）拒绝，`details` 含 `archive_fork_schema_version` 与 `runtime_fork_schema_version`，当前库中的数据保持不变。
4. 当数据库已经被备份内容替换、`run_migrations` 尚未执行时，系统应当把 `_fork_schema_version` 设为 manifest 中的值。这是为了覆盖 PostgreSQL `pg_restore --clean` 不删除转储之外对象、导致当前库水位残留的情况。
5. 上游 schema 较新时的拒绝路径应当保持原样：`details` 仍只有 `archive_schema_version` 与 `runtime_schema_version` 两个键，`tests/unit/backup/test_system_archive.py` 不做改动且全部通过。
6. `MANIFEST_VERSION` 应当始终保持为 1；含新字段的 manifest 与不含新字段的旧 manifest 都应当能被 `BackupManifest.load_text` 读取。

### 需求 6：PostgreSQL 方言验证

**用户故事：** 作为 fork 维护者，我希望 fork runner 与备份恢复在 PostgreSQL 上有真实的门控用例，以便 PG 系控制面（D3）不会只在 SQLite 上"看起来是绿的"。

#### 验收标准

1. 在设置了 `OCTOP_TEST_DATABASE_URL` 的期间，PG 用例应当验证：fork 迁移在 PG 上按事务应用；失败时整版本回滚；重复执行幂等。
2. 在设置了 `OCTOP_TEST_DATABASE_URL` 的期间，PG 用例应当验证：`_schema_version` 高于上游最大版本、走 clamp 的 PG 分支之后，fork 迁移仍然被应用。
3. 在设置了 `OCTOP_TEST_DATABASE_URL` 且 `pg_dump` / `pg_restore` 在 PATH 上的期间，PG 用例应当验证：备份往返携带 fork 水位；恢复一个转储中不含 `_fork_schema_version` 表的备份后，水位被重置为 0 并补跑全部 fork 迁移。
4. 如果未设置 `OCTOP_TEST_DATABASE_URL`，那么这些 PG 用例应当被 skip 并给出原因，不得报错。

### 需求 7：AGENTS.md §7 迁移段

**用户故事：** 作为在本仓库工作的开发者或 AI 代理，我希望导航文件里的迁移说明是准确的，并写明 fork 迁移规则，以便后续 spec 不再照抄过期的 `v == 7`，也不再往上游号段里写 `016`。

#### 验收标准

1. AGENTS.md §7 的迁移段应当不再出现 `currently \`v == 7\``，改为说明当前上游水位是 15、水位断言分布在 8 个测试文件中，并说明 `test_db_pool.py` 里"迁移到 v7 中途"的 `== 7` 断言不属于水位断言。
2. AGENTS.md §7 应当新增 fork 迁移规则段，覆盖以下各点：命名与成对；由 `run_migrations` 末尾的 `run_fork_migrations` 执行、使用 `_fork_schema_version` 水位；迁移号不预占，按合入顺序取号；合入 fork 主干后的文件不可修改；fork 工作不改上游版本断言；不得折进 `_ensure_*`、`_repair_legacy_schema`、`_apply_sqlite_migration` 或 clamp 阶梯；SQL 书写约束与 `.pg.sql` 幂等写法；Python 步骤的用途。
3. 当执行 `rg -n "v == 7" AGENTS.md` 时应当没有输出；执行 `rg -n "_fork_schema_version" AGENTS.md` 时应当至少输出一行。

### 需求 8：交付质量

**用户故事：** 作为评审人，我希望本 spec 的交付满足仓库的发版门槛并能在 Windows CI 上通过，以便它能作为后续 spec 的可靠地基合入。

#### 验收标准

1. 当本 spec 的全部任务完成时，`make all`（format-all + lint + typecheck + test，含对新模块的 `mypy --strict`）应当全绿。
2. 新增测试应当始终不依赖 POSIX 专有行为：只使用 `tmp_path` / `pathlib`，不断言 chmod 位，不写以 `/` 开头的字面路径，以便按 AGENTS.md §7 的跨平台约定在 Windows CI 上通过。
3. 本 spec 应当始终不改动 `dashboard/` 与任何 HTTP 响应结构：`git diff --name-only 757fd12 -- dashboard` 输出为空，恢复接口返回的字段集合不变。
