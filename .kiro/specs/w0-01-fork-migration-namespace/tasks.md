# 实施计划：fork 独立迁移空间

> spec：`w0-01-fork-migration-namespace` ｜ 波次：Wave 0 ｜ 基线：`757fd12` ｜ 预估：4.5 人日
> 前置：无 ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

每个顶层任务完成后可独立提交；提交前运行任务内的验证命令。

- [x] 1. 确认前置 spec 已合入并记录基线（0.25 人日）
  - 改动：无代码改动。本 spec 没有前置 spec。确认工作分支基于 `757fd12`；复测上游正则确实不匹配 `forkNNN_` 文件名；确认迁移目录里还没有 `016_` 或 `fork*` 文件；把以下命令的输出贴进 PR 描述，作为基线记录。
  - 验证：`git merge-base --is-ancestor 757fd12 HEAD && echo baseline-ok`
  - 验证：`uv run python -c "import re; assert re.match(r'^(\d{3})_.*\.sql$', 'fork001_x.sql') is None; assert re.match(r'^(\d{3})_.*\.pg\.sql$', 'fork001_x.pg.sql') is None; print('regex-ok')"`
  - 验证：`! ls src/octop/infra/db/migrations | rg '^(016_|fork)'`
  - 验证：`uv run pytest tests/unit/db tests/unit/backup -q`
  - _需求：1.1, 1.6_

- [x] 2. fork 迁移发现与水位读写（测试先行，0.5 人日）
  - [x] 2.1 先写会失败的测试与测试辅助
    - 改动：新增 `tests/support/fork_migrations.py`，提供 `write_demo_fork_migrations(dir, versions=(1, 2))` 与 `use_fork_dir(monkeypatch, dir)`。前者写出 `fork001_demo` 与 `fork002_demo_ref` 两对文件（内容见 design.md "测试策略"，PG 版用 `BIGINT` 并带 `IF NOT EXISTS`）；后者 monkeypatch `octop.infra.db.fork_migrate._FORK_MIGRATIONS_DIR`。
    - 改动：新增 `tests/unit/db/test_fork_migrate.py`，写入以下用例：
      - 把基线迁移复制到 `tmp_path`、混入 fork 文件后，上游 `_discover` 与 `_max_discovered_version` 的结果不变（两种方言都测）；
      - `discover_fork_migrations` 的方言分流与升序；
      - 重号时抛 `RuntimeError`，消息里有两个文件名；
      - `forkX_bad.sql`、`fork01_a.sql`、`fork001_Bad.sql` 等畸形文件名抛 `RuntimeError`；
      - `current_fork_version` 在表不存在时返回 0；
      - `set_fork_version` 建表并 upsert，重复写入后仍只有一行，插入 `id = 2` 触发 CHECK 失败；
      - 仓库静态检查：真实 `migrations/` 目录里的 fork 文件成对；`.pg.sql` 的 `CREATE TABLE` / `CREATE INDEX` / `ADD COLUMN` 带 `IF NOT EXISTS`；`_FORK_PY_STEPS` 的每个键都有 SQL 对。当前为空集，应当通过。
    - 验证：`uv run pytest tests/unit/db/test_fork_migrate.py -q`（此时应因模块不存在而失败）
    - _需求：1.1, 1.2, 1.3, 1.4, 1.5, 2.7_
  - [x] 2.2 实现发现与水位函数
    - 改动：新增 `src/octop/infra/db/fork_migrate.py`，实现 `_FORK_MIGRATIONS_DIR`、`_FORK_FILE_RE`（`^fork(\d{3})_[a-z0-9_]+(\.pg)?\.sql$`）、`discover_fork_migrations`、`max_fork_version`、`current_fork_version`（经 `migrate._table_exists` 判断表是否存在）、`_ensure_fork_version_table`、`set_fork_version`，以及 `ForkPyStep` 类型与空的 `_FORK_PY_STEPS`。模块只依赖 `infra/db/migrate`、`infra/db/pool` 与标准库，不读取 `octop.config`。
    - 验证：`uv run pytest tests/unit/db/test_fork_migrate.py tests/unit/db/test_migrate_discovery.py -q`
    - 验证：`uv run mypy src/octop/infra/db/fork_migrate.py`
    - _需求：1.1, 1.2, 1.3, 1.4, 1.5, 2.7_

- [x] 3. 事务化 runner（测试先行，0.75 人日）
  - [x] 3.1 先写会失败的 runner 用例
    - 改动：在 `tests/unit/db/test_fork_migrate.py` 追加以下用例，均直接调用 `run_fork_migrations`。库由 `SqlitePool(tmp_path / "octop.db")` 加 `run_migrations` 建出；建库时 fork 目录要指向空目录，之后再切到示例目录，保证任务 4 接入后这些用例依然成立：
      - 先 `DROP TABLE IF EXISTS _fork_schema_version` 再执行：表被重建，水位为 2；
      - 每推进一版，`_schema_version` 仍为 15；
      - 第二次执行不执行语句（用 spy 统计 `conn.execute` 调用或比对表结构），水位不变；
      - `fork002` 中放一条会失败的语句：`fork002` 建的对象不存在，水位停在 1，异常上抛；
      - monkeypatch `_FORK_PY_STEPS` 登记步骤：该步骤在 SQL 之后、水位更新之前被调用，拿到的是同一事务连接；步骤抛错时 SQL 改动一并回滚；
      - 把水位手工置为 9：执行后水位仍为 9，没有文件被执行，`caplog` 中有一条包含 `9` 与 `2` 的 WARNING。
    - 验证：`uv run pytest tests/unit/db/test_fork_migrate.py -q`（新增用例应失败）
    - _需求：2.1, 2.2, 2.3, 2.4, 2.5, 2.6_
  - [x] 3.2 实现 `run_fork_migrations`
    - 改动：`src/octop/infra/db/fork_migrate.py` 的 `run_fork_migrations` 按以下顺序实现：
      1. 建表并写初始行；
      2. 发现文件，计算最大版本；
      3. 程序回退时记 WARNING 并返回；
      4. 逐版本在 `db.transaction()` 内完成：PG 取 `pg_advisory_xact_lock` 后重读水位→ 用 `migrate._split_pg_sql` 切分后逐条执行 → 调用可选的 Python 步骤 → `UPDATE _fork_schema_version SET version = ? WHERE id = 1`；
      5. 提交后记 INFO 日志（含文件名）。
    - 验证：`uv run pytest tests/unit/db/test_fork_migrate.py -q`
    - 验证：`uv run mypy src/octop/infra/db/fork_migrate.py`
    - _需求：2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

- [x] 4. 接入 `run_migrations` 并锁定执行顺序（测试先行，0.5 人日）
  - [x] 4.1 先写会失败的顺序、clamp 与守卫用例
    - 改动：在 `tests/unit/db/test_fork_migrate.py` 追加以下用例。除"全新库"外，其余用例建库时 fork 目录都指向空目录，先制造好上游状态，再切到示例目录执行 `run_migrations`：
      - 全新库上 `run_migrations` 之后，fork 水位为 2，`fork_demo_ref` 存在（它依赖上游 015 的 `user_sso_identities`）；
      - 照 `test_db_pool.py::test_v14_to_v15_adds_sso_provider_kind_without_rebuilding` 的手法，把库退回 `_schema_version = 14` 并删掉 `user_sso_identities`，再跑 `run_migrations`：上游回到 15，fork 水位为 2；
      - 把 `_schema_version` 置为 20，再跑 `run_migrations`：`_schema_version == 15`（既有 clamp 行为），fork 水位为 2；
      - AST 守卫：解析 `src/octop/infra/db/migrate.py`，断言 `run_migrations` 函数体的最后一条语句是对 `run_fork_migrations` 的调用。
    - 验证：`uv run pytest tests/unit/db/test_fork_migrate.py -q`（新增用例应失败）
    - _需求：3.1, 3.2, 3.3, 3.4_
  - [x] 4.2 在 `run_migrations` 末尾接入
    - 改动：`src/octop/infra/db/migrate.py` 的 `run_migrations`：在 `_ensure_sso_provider_kind_schema(db)`（≈L1713）之后加惰性导入 `from octop.infra.db.fork_migrate import run_fork_migrations` 与一行 `run_fork_migrations(db)`，总计不超过 3 行。不改 `_repair_legacy_schema`、`_apply_sqlite_migration`、`_reconcile_pre_squash_schema_version` 与任何 `_ensure_*`。
    - 验证：`uv run pytest tests/unit/db -q`（新用例通过，既有用例不改动全部通过）
    - 验证：`rg -n "fork" src/octop/infra/db/migrate.py`（输出只有 `run_migrations` 末尾的两行）
    - 验证：`git diff --stat 757fd12 -- src/octop/infra/db/migrate.py`
    - _需求：3.1, 3.2, 3.3, 3.4, 3.5, 1.6_

- [x] 5. 覆盖全部启动与迁移入口（0.5 人日）
  - 改动：新增 `tests/integration/test_fork_migration_entrypoints.py`，每个用例都先用 `tests/support/fork_migrations.py` 写出示例迁移并 monkeypatch 目录。覆盖以下入口：
    - `bind_control_plane`：`tests.support.app.octop_client(tmp_octop_home)` 首装绑定之后，读 `server.services.db` 的 fork 水位；
    - `start()`：第一次 `octop_client` 退出后，用同一 home 再进入一次 `octop_client`（此时 SQLite 文件已存在，`should_defer_control_plane_db` 为假，走 `start()` 中 ≈L323 的迁移）。第一次进入时 fork 目录只写 `versions=(1,)`，第二次进入前补写第 2 版，断言水位从 1 变为 2；
    - `assert_control_plane_database_empty(DatabaseConfig(sqlite_path=…), paths)`：检查目标文件的 fork 水位；
    - `rebind_control_plane(server)`：在零用户、已绑定的 server 上用 `persist_database_config` 把 `config.json` 指向新 SQLite 文件后调用，断言 `server.services.db` 的水位；
    - `open_cli_services(home)`：`with` 块内的 `services.db` 水位；
    - `octop init`：Click `CliRunner` 调用 `octop.cli.commands.init.init`，参数 `["--yes", "--admin-username", …, "--admin-password", …]`，`env={"OCTOP_HOME": str(tmp_path)}`，然后打开库检查水位。
  - 改动：src 的 10 个 `run_migrations` 调用点不做任何修改。
  - 验证：`uv run pytest tests/integration/test_fork_migration_entrypoints.py -q`
  - 验证：`rg -l "infra\.db\.fork_migrate" src/`（此时只输出 `src/octop/infra/db/migrate.py`；任务 6 之后再加 `system_archive.py`）
  - _需求：4.1, 4.2, 4.3, 4.4, 4.5_

- [x] 6. 备份导出与恢复携带 fork 水位（测试先行，0.75 人日）
  - [x] 6.1 先写会失败的备份用例
    - 改动：新增 `tests/unit/backup/test_fork_schema_backup.py`，写入以下用例：
      - `BackupManifest` 带 `fork_schema_version=3` 往返；不含该键的旧 dict 读为 0；`MANIFEST_VERSION == 1`；
      - `create_system_backup` 产出的 `manifest.json` 中 `fork_schema_version == 2`；
      - 恢复不含该键的旧包：先让 fork 目录为空，建库并备份，再从 manifest 里删掉该键；然后切换到含两版的 fork 目录，执行恢复。恢复后水位为 2，`fork_demo_ref` 存在；
      - 把 manifest 的 `fork_schema_version` 改成 99：恢复抛 `BACKUP_SCHEMA_INCOMPATIBLE`，`details` 为 `{"archive_schema_version": "15+fork99", "runtime_schema_version": "15+fork2", "archive_fork_schema_version": 99, "runtime_fork_schema_version": 2}`，恢复前插入的标记用户仍在；
      - 把 `octop.infra.backup.system_archive.restore_sqlite_into_pool` monkeypatch 为不替换库的桩，并让 manifest 的 `fork_schema_version` 为 0：断言在 `run_migrations` 之前水位被置为 0（对 `set_fork_version` 做 spy），最终被补跑到 2。
    - 验证：`uv run pytest tests/unit/backup/test_fork_schema_backup.py -q`（应失败）
    - _需求：5.1, 5.2, 5.3, 5.4, 5.6_
  - [x] 6.2 实现 manifest 字段、导出与恢复逻辑
    - 改动：`src/octop/infra/backup/manifest.py` 的 `BackupManifest`：在字段末尾追加 `fork_schema_version: int = 0`；`to_json` 输出该键；`from_dict` 用 `int(data.get("fork_schema_version", 0))` 读取；`MANIFEST_VERSION` 不变。
    - 改动：`src/octop/infra/backup/system_archive.py` 分三处修改：
      - 导入 `current_fork_version`、`max_fork_version`、`set_fork_version`；
      - `_build_manifest` 用"异常即 0"的方式读取 fork 水位并传入 manifest；
      - `restore_system_backup` 在既有上游预检（≈L477-487）之后加 fork 预检，details 按 design.md 构造；在库替换之后、≈L534 的 `run_migrations(pool)` 之前，在同一个 try 块内调用 `set_fork_version(pool, manifest.fork_schema_version)`。

      恢复结果字典不新增字段。
    - 验证：`uv run pytest tests/unit/backup -q`（新用例通过；`test_system_archive.py` 不改动全部通过，包括 ≈L1188 的两键 details 断言）
    - 验证：`rg -l "infra\.db\.fork_migrate" src/`（只输出 `migrate.py` 与 `system_archive.py`）
    - _需求：5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 4.5_

- [x] 7. PostgreSQL 门控用例（0.5 人日）
  - 改动：新增 `tests/integration/test_postgresql_fork_migrations.py`。每个用例都加 `@requires_postgresql` 与 `@pytest.mark.postgresql`，照抄 `test_postgresql_control_plane.py` 的 `_reset_public_schema` 与 `_pg_payload_from_url`，并写入以下用例：
    - 事务应用、失败整版本回滚、重复执行幂等；
    - `_schema_version` 置为 20 后走 clamp 的 PG 分支，fork 水位仍为 2；
    - 备份往返中 manifest 带 `fork_schema_version == 2`（`pg_dump` / `pg_restore` 不在 PATH 时 `pytest.skip`）；
    - 删除 `_fork_schema_version` 后备份，再跑 `run_migrations` 让当前库推进到 2，然后恢复：断言水位先被重置为 0，再被补跑到 2，`fork_demo_ref` 存在。
  - 验证（本地起专用库，行内环境把镜像换成内部源）：`docker run -d --name octop-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=octop_test -p 15432:5432 postgres:16`
  - 验证：`OCTOP_TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:15432/octop_test uv run pytest tests/integration/test_postgresql_fork_migrations.py tests/integration/test_postgresql_control_plane.py -m postgresql -q`
  - 验证：`uv run pytest tests/integration/test_postgresql_fork_migrations.py -q -rs`（未设置 URL 时全部 skip，并给出原因）
  - 说明：`w0-02` 合入前，CI 不执行这些用例，需要在 PR 描述中贴出本地运行结果；`w0-02` 合入后由 CI 的 postgres service 自动收集。
  - _需求：6.1, 6.2, 6.3, 6.4, 5.4_

- [x] 8. 更新 AGENTS.md §7 迁移段（0.25 人日）
  - 改动：`AGENTS.md` §7 "Database" 段：
    - 把 ≈L222-223 的 `v == 7` 表述替换为"当前 15、分布在 8 个测试文件、`test_db_pool.py` 的 `== 7` 不是水位断言"；
    - 在 ≈L232 之后插入 design.md 给出的 "Fork migrations (intranet fork only)" 段落。

    不改 §5 / §9，那部分归 `w0-04`。
  - 验证：`! rg -n "v == 7" AGENTS.md`
  - 验证：`rg -n "_fork_schema_version|forkNNN_description|_FORK_PY_STEPS" AGENTS.md`
  - _需求：7.1, 7.2, 7.3_

- [x] 9. 收尾（0.25 人日）
  - 改动：清理本 spec 引入但未使用的符号与导入。本 spec 不改 `dashboard/`，因此不需要前端 typecheck、lint 或 vitest；恢复接口的响应不变，因此不更新 `docs/api-intranet.md`。
  - 改动：若 `w0-04` 已合入，在 `CHANGELOG-intranet.md` 追加一条"fork 独立迁移空间（`forkNNN_*` + `_fork_schema_version`，备份 manifest 新增 `fork_schema_version`）"；若 `w0-04` 尚未合入，把这条写进 PR 描述，由 `w0-04` 建立该文件时补录。
  - 验证：`make all`
  - 验证：`git diff --name-only 757fd12 -- dashboard src/octop/infra/db/migrations`（应无输出）
  - 验证：`git diff --name-only --diff-filter=M 757fd12 -- tests/`（应无输出，说明没有改动既有测试与版本断言）
  - 验证：人工检查新增测试只使用 `tmp_path` / `pathlib`，没有 chmod 断言，也没有以 `/` 开头的字面路径（Windows CI 会跑同一批用例）。
  - _需求：8.1, 8.2, 8.3, 1.6_
