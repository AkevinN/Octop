# 实施计划：信创数据库适配

> spec：`w2-03-database-adaptation` ｜ 波次：Wave 2 ｜ 基线：`757fd12` ｜ 预估：28 人日（另加 25% 风险缓冲约 7 人日，上限 35 人日）
> 前置：`w0-01-fork-migration-namespace`、`w0-02-ci-gates`、`w0-03-test-auth-baseline`、`w0-04-fork-isolation-points`、`w1-02-capability-trim`、`w2-01-offline-build` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

每个顶层任务完成后可独立提交；提交前运行任务内的验证命令。

说明：各任务括号内为人日估算，合计约 28 人日；25% 风险缓冲不摊入任务，只在任务 18、19 发现国产库不兼容时动用。标注"PG"的命令需要一个专用 PostgreSQL 16（测试会 DROP SCHEMA 并创建临时角色），启动方式见设计文档"测试策略"；标注"行内环境"的命令只能在行方实例或行内仓库上执行。本 spec 不产生 fork 迁移。

- [ ] 1. 确认前置 spec 已合入并记录基线（0.5 人日）
  - 改动：核实 `src/octop/infra/db/fork_migrate.py` 与 `_FORK_PY_STEPS`、`tests/support/fork_migrations.py`（w0-01）、`make test-postgresql` 与 `pg_strict`（w0-02）、`tests/support/auth.py` 的 `bootstrap_admin` / `login` / `create_agent`（w0-03）、intranet overlay 与 `CHANGELOG-intranet.md`（w0-04）、`tests/unit/test_config_touchpoints.py`（w1-02）、`octop init --if-needed` 与 `docker/docker-entrypoint.sh` 的退出码分派（w2-01）均已存在。
  - 改动：在 PR 描述中记录基线：`_discover("postgresql")` 返回 15 个文件；`run_migrations` 在 `src/octop` 中的调用点共 10 处（`rg -n "run_migrations\(" src/octop`）；入口脚本对未列出的退出码按原码退出（需求 8.2 依赖此点，若不成立则回报 w2-01）。
  - 验证：`uv run pytest tests/unit/db tests/unit/backup tests/unit/test_config_touchpoints.py -q && rg -n "run_migrations\(" src/octop`
  - _需求：1.6, 8.2_

- [ ] 2. PG 方言家族：配置层接入 kingbase / opengauss（1 人日）
  - 改动：先写 `tests/unit/db/test_dialect_family.py` 的配置部分（四种驱动下 `load_config`、`is_postgresql`、`postgresql_conninfo()`；非法驱动名的 `ValueError` 列出四个允许值），确认在基线上失败。
  - 改动：`src/octop/config.py` 新增 `_PG_FAMILY_DRIVERS`，`_VALID_DRIVERS` 改为家族加 `sqlite`；`DatabaseConfig.is_postgresql` 改为家族判断；`postgresql_conninfo()` 守卫改为 `if not self.is_postgresql`；`parse_database_config` 的 PG 分支对三个家族驱动一视同仁；URL 仍只接受 `postgresql://` / `postgres://`。
  - 改动：`src/octop/api/routers/setup.py` 的 `DatabaseSetupBody.driver` 的 `Field(description=…)` 补全四个取值。
  - 验证：`uv run pytest tests/unit/db/test_dialect_family.py -q -k "config or driver"`
  - _需求：1.1, 1.3_

- [ ] 3. PG 方言家族：`dialect` 收敛为家族、备份记录产品名（1 人日）
  - 改动：先在 `tests/unit/db/test_dialect_family.py` 补齐：用假 `PostgresPool` 调 `open_database` 得到 `dialect == "postgresql"`；`_discover`、`_max_discovered_version`、`discover_fork_migrations`、`max_fork_version` 在四种驱动下与基线相等；`dialect` 比较字面量的 AST 守卫；SQLite 备份改写 manifest 驱动名后恢复得到 `BACKUP_DRIVER_MISMATCH`，且 `details` 仍为 `archive_driver`、`runtime_driver`。
  - 改动：`src/octop/infra/db/pool.py` 新增 `SqlDialect = Literal["sqlite", "postgresql"]`，Protocol 与两个实现类的 `dialect` 用它标注；不新增 `dialect_family`。
  - 改动：`src/octop/infra/backup/system_archive.py` 的 `create_system_backup` 记录 `db_config.driver`；`restore_system_backup` 的跨引擎判断与 `runtime_driver` 改取 `db_config.driver`。
  - 验证：`uv run pytest tests/unit/db/test_dialect_family.py tests/unit/db tests/unit/backup -q && make typecheck`
  - _需求：1.2, 1.4, 1.5, 1.6_

- [ ] 4. 连接池参数与迁移开关配置键（1.5 人日）
  - [ ] 4.1 七个配置键
    - 改动：先写 `tests/unit/db/test_pool_config.py` 的配置部分（env / 文件 / 默认值、非法值 WARNING 不回显原值、`min > max` 等关系校验 `ValueError` 指明键名、只设 `OCTOP_DB_*` 时 `database_env_configured()` 仍为假）。
    - 改动：`src/octop/config.py` 为 `db_auto_migrate` 与 6 个 `db_pool_*` 完成三触点（`OctopConfig` 字段、`load_config` 的 env 覆盖块、`return OctopConfig(...)`）；新增 `_DATABASE_RUNTIME_ENV_KEYS`；不加入 `_DATABASE_ENV_KEYS`。
    - 验证：`uv run pytest tests/unit/db/test_pool_config.py tests/unit/test_config_touchpoints.py -q`
    - _需求：2.3, 2.4, 2.5_
  - [ ] 4.2 透传到 `ConnectionPool`
    - 改动：先在 `tests/unit/db/test_pool_config.py` 追加：`open_database` 透传（沿用 `tests/unit/db/test_db_factory.py` 的假连接池手法）；`PostgresPool` 透传给假 `ConnectionPool`，`check=True` 时传 `ConnectionPool.check_connection`，未配置时逐值等于基线。
    - 改动：`src/octop/infra/db/pool.py` 的 `PostgresPool.__init__` 新增 `timeout`、`max_lifetime`、`max_idle`、`check` 关键字参数；`src/octop/infra/db/factory.py` 的 `open_database` 传入配置值。
    - 验证：`uv run pytest tests/unit/db/test_pool_config.py tests/unit/db/test_db_factory.py -q`
    - _需求：2.1, 2.2_

- [ ] 5. 新增两个错误码与 overlay 文案（0.5 人日）
  - 改动：`src/octop/infra/errors.py` 在 `ErrorCode` 末尾追加 `SCHEMA_OUT_OF_DATE`、`DATABASE_DDL_DISABLED`，同批在 `_DEFAULT_STATUS` 末尾登记 503 与 409。
  - 改动：`src/octop/i18n/intranet/{en,zh}.json` 与 `dashboard/src/locales/intranet/{en,zh}.json` 增加两个码的文案，以及 `BACKUP_DRIVER_MISMATCH` 的产品化措辞覆盖；不删除、不改动上游键。
  - 验证：`uv run pytest tests/unit/i18n -q`
  - _需求：3.7_

- [ ] 6. 迁移网关 `migrate_gate.py`（控制面组件）（2.5 人日）
  - 改动：先写 `tests/unit/db/test_migrate_gate.py`：auto 模式委托 `run_migrations`（spy）；verify 模式水位一致时不调用，并用 `sqlite3.Connection.set_trace_callback` 断言无 `CREATE` / `ALTER` / `DROP`；空库、上游落后、fork 落后（`tests/support/fork_migrations.py`）时抛 `SCHEMA_OUT_OF_DATE` 且 `details` 含组件名与两侧版本；库水位高于代码时 WARNING 放行且不回写水位。
  - 改动：新增 `src/octop/infra/db/migrate_gate.py`：`ComponentVersion`、`schema_status`、`verify_schema`、`maybe_run_migrations(db, *, auto_migrate)`、`migrate_all(db, *, conninfo)`；外部组件在此任务中留空列表挂点，由任务 11 接入。
  - 改动：`src/octop/infra/db/fork_migrate.py` 抽出 `FORK_VERSION_TABLE_DDL` 常量，`_ensure_fork_version_table` 改用它（行为不变）。
  - 验证：`uv run pytest tests/unit/db/test_migrate_gate.py tests/unit/db -q`
  - _需求：3.2, 3.5_

- [ ] 7. 十个迁移入口改走网关并加 AST 守卫（1.5 人日）
  - 改动：先在 `tests/unit/db/test_migrate_gate.py` 追加 AST 守卫：`src/octop` 中除 `infra/db/migrate_gate.py` 外不得导入或调用 `run_migrations`（`migrate.py` 只有定义）；确认在改动前失败。
  - 改动：`src/octop/infra/server.py` 的 `start` 与 `bind_control_plane`；`src/octop/infra/db/rebind.py` 的 `assert_control_plane_database_empty`（新增必填关键字参数 `auto_migrate`）与 `rebind_control_plane`；`src/octop/cli/support/db.py`、`src/octop/cli/commands/init.py`、`src/octop/cli/commands/admin.py`、`src/octop/cli/commands/backup.py`（两处）；`src/octop/infra/backup/system_archive.py` 的 `restore_system_backup`（新增 `auto_migrate: bool = True`）。全部改为 `maybe_run_migrations(db, auto_migrate=…)`。
  - 改动：`src/octop/api/routers/setup.py` 向 `assert_control_plane_database_empty` 传 `server.config.db_auto_migrate`；`src/octop/api/routers/backup.py` 的 `_restore_stored_backup` 透传 `auto_migrate`。
  - 验证：`uv run pytest tests/unit/db/test_migrate_gate.py tests/unit/cli tests/unit/backup tests/integration/test_setup_database.py -q && make typecheck`
  - _需求：3.1, 3.4_

- [ ] 8. verify-only 失败路径与 CLI 退出码（1 人日）
  - 改动：先写 `tests/integration/test_verify_only_startup.py` 的启动部分：预先迁移的 home 以 `db_auto_migrate=false` 启动成功且无 DDL；空库时 `srv.start()` 抛 `SCHEMA_OUT_OF_DATE`；`octop init --if-needed` 退出 5、不创建用户、不向 `~/.octop` 写凭据；`POST /api/setup/database` 返回 503 与 `SCHEMA_OUT_OF_DATE`。
  - 改动：`src/octop/cli/main.py` 的 `_LazyCLI` 新增 `invoke` 覆盖：`SCHEMA_OUT_OF_DATE` 打印 `error: <message>`（含组件名与"当前版本 < 期望版本"）后以 5 退出，`DATABASE_DDL_DISABLED` 以 1 退出，其余 `OctopError` 原样上抛。
  - 验证：`uv run pytest tests/integration/test_verify_only_startup.py tests/unit/cli -q`
  - _需求：3.2, 3.3, 8.2_

- [ ] 9. verify-only 下拒绝应用内恢复（0.5 人日）
  - 改动：先在 `tests/integration/test_verify_only_startup.py` 追加：HTTP `POST /api/backup/files/{filename}/restore` 与 `octop backup restore` 都得到 `DATABASE_DDL_DISABLED`（409 / 退出码 1），且库中的标记用户仍在；备份创建不受影响。
  - 改动：`src/octop/infra/backup/system_archive.py` 的 `restore_system_backup` 在解包与 manifest 校验之后、任何替换之前，`auto_migrate` 为假即抛 `DATABASE_DDL_DISABLED`；`src/octop/cli/commands/backup.py` 的 `restore` 透传 `auto_migrate`。
  - 验证：`uv run pytest tests/integration/test_verify_only_startup.py tests/unit/backup -q`
  - _需求：3.6_

- [ ] 10. harness-memory 行内补丁 `schema_bootstrap`（2.5 人日，仓库外，行内环境）
  - 改动：在 harness-memory 行内内部分支（w2-01 流程）提交补丁：`PostgresMemoryBackend.__init__` 接受 `schema_bootstrap`（不进入 `psycopg.connect`）；为假时跳过 `_init_schema` 与 `_migrate_legacy_schema`，改为校验 `harness_memory.meta` 的 `schema_version`；建表语句提为模块常量并暴露 `bootstrap_ddl()`、`checkpoint_tuning_ddl()`；`Memory._create_postgres_checkpointer` 在 `schema_bootstrap=False` 时不调用 `saver.setup()` 与 autovacuum 调整，只校验 `checkpoint_migrations` 最大版本；不一致时抛含期望值与实际值的 `RuntimeError`；为真时行为与 0.9.10 一致。补丁自带单测。
  - 改动：发布 `+intranet.N` 后，`pyproject.toml` 精确固定该版本，执行 `make relock` 重生成 `uv.lock`；把新版本告知 w2-02 进入 SBOM。
  - 验证：（行内环境）在 harness-memory 仓库运行其测试套件；在 Octop 执行 `uv run python -c "from harness_memory.storage.backends.postgres import bootstrap_ddl; print(len(bootstrap_ddl()))"`
  - _需求：5.2_

- [ ] 11. Octop 侧记忆层预置与外部结构校验（1 人日）
  - 改动：先写 `tests/unit/agents/test_memory_backend_preprovisioned.py`：verify 模式下三种 postgres 规格与 `open_memory_kwargs` 都带 `schema_bootstrap: False`；auto 模式与基线逐键相等；`supports_preprovisioned_memory()` 为假时 `verify_schema` 抛 `RuntimeError` 并提示 `+intranet` 构建。
  - 改动：`src/octop/infra/agents/memory_backend.py` 新增 `_postgres_spec`，`memory_backend_from_agent_config` 的三处 postgres 规格与 `open_memory_kwargs` 改用它。
  - 改动：新增 `src/octop/infra/db/external_schema.py`：`checkpoint_ddl`、`checkpoint_expected_version`（取 `langgraph.checkpoint.postgres.base.MIGRATIONS`）、`memory_ddl`、`memory_expected_version`、`supports_preprovisioned_memory`、`external_status`、`bootstrap_external`，外部包在函数内惰性导入；`migrate_gate.schema_status` 在 `db.dialect == "postgresql"` 时并入外部组件，`migrate_all` 调用 `bootstrap_external`。
  - 验证：`uv run pytest tests/unit/agents/test_memory_backend_preprovisioned.py tests/unit/db/test_migrate_gate.py -q`
  - _需求：5.1, 5.3, 5.4_

- [ ] 12. DDL 导出 `ddl_export.py`（2.5 人日）
  - 改动：先写 `tests/unit/db/test_ddl_export.py`：文件集合与顺序（`a*` / `b000` / `b*` / `c1` / `c2` / `d_grants.sql` / `apply_order.txt` / `MANIFEST.json`）；上游文件与 `_discover("postgresql")` 逐字节相同；fork 文件末尾有水位推进语句；`MANIFEST.json` 的 SHA256 与期望版本；`upstream_python_hook_versions() == {3, 7, 10}`；`_FORK_PY_STEPS` 进入 manifest 且 `apply_order.txt` 头部注明需用 `octop db migrate`；授权脚本不含 `CREATE`；导出过程不打开数据库（`open_database` 替换为抛异常的桩）；非法标识符拒绝且不写文件。
  - 改动：新增 `src/octop/infra/db/ddl_export.py`：`export_ddl(out_dir, *, driver, runtime_role, schema="public", force=False) -> ExportResult`、`upstream_python_hook_versions() -> set[int]`；checkpoint 与记忆层 DDL 只取自 `external_schema`，不手抄。
  - 验证：`uv run pytest tests/unit/db/test_ddl_export.py -q`
  - _需求：4.1, 4.4, 4.6, 5.4_

- [ ] 13. `octop db` 命令组（1 人日）
  - 改动：先写 `tests/unit/cli/test_db_cli.py`：`CliRunner` 下 `db export-ddl`（合法生成、非法 `--runtime-role` / `--schema` 退出 2 且不写文件、非空目录无 `--force` 拒绝）、`db check`（0 / 5 / 1）、`db migrate`（不受 `db_auto_migrate` 影响，打印前后版本）。
  - 改动：新增 `src/octop/cli/commands/db.py`（`export-ddl`、`check`、`migrate`）；`src/octop/cli/registry.py` 的 `COMMANDS` 注册 `"db"`。
  - 验证：`uv run pytest tests/unit/cli/test_db_cli.py -q && uv run octop db --help`
  - _需求：4.5, 4.6_

- [ ] 14. PG 集成：结构等价、DML 角色端到端与跨产品恢复（2.5 人日，PG）
  - 改动：新增 `tests/integration/test_postgresql_ddl_export.py`（同时带 `@requires_postgresql` 与 `@pytest.mark.postgresql`）：(a) 两个 schema 分别执行 `run_migrations` 加外部 bootstrap 与导出件，比较 `information_schema.columns`、`pg_indexes`、`information_schema.table_constraints`；(b) 临时 DML 角色加 `db_auto_migrate=false` 起服务、`bootstrap_admin`、登录、`create_agent`，并用 `Memory(..., schema_bootstrap=False)` 完成 `add_raw` / `get_raw` 与 `put` / `get_tuple`，同一角色在 auto 模式下启动因权限失败；(c) `octop db migrate` / `check`；(d) `driver=postgresql` 备份、`driver=kingbase` 恢复得到 `BACKUP_DRIVER_MISMATCH`。
  - 改动：修正本用例暴露的 `ddl_export.py` / `external_schema.py` 缺陷。
  - 验证：（PG）`OCTOP_TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:15432/octop_test make test-postgresql`
  - _需求：1.5, 4.2, 4.3, 5.2_

- [ ] 15. setup 锁定热点与 `UserManager` 索引（1.5 人日）
  - 改动：先写 `tests/unit/test_user_manager_index.py`（`UserCache` 在 `boot`、`create`、`register_cached_user`、SSO 登录缓存、`enable`、`disable`、`remove`、`shutdown_all` 之后的一致性；`get_by_id`；`has_users` 的缓存与 `remove` / `replace_services` 失效）与 `tests/integration/test_setup_lockdown_hotpath.py`（有用户后 20 个非豁免请求中 `UserRepo.count` 调用 0 次；`remove` 最后一个用户后重新进入锁定并返回 `503 {"setup_required": true}`）。
  - 改动：新增 `src/octop/infra/users/user_cache.py::UserCache`；`src/octop/infra/users/manager.py` 的 `_users` 改用它，新增 `has_users()`，`get_by_id` 走索引，`remove` 与 `replace_services` 清缓存；`src/octop/api/middleware/setup_lockdown.py` 改用 `has_users()`。
  - 验证：`uv run pytest tests/unit/test_user_manager_index.py tests/integration/test_setup_lockdown_hotpath.py tests/integration/test_setup_wizard.py -q`
  - _需求：6.1, 6.2, 6.3_

- [ ] 16. `/api/health` 去掉部署规模并脱离数据库（0.5 人日）
  - 改动：先写 `tests/integration/test_health_anonymous.py`：匿名响应键集合恰为 `ok`、`started_at`、`db`；把控制面连接池的 `connect` 换成抛异常的桩后 1 秒内返回 200；未绑定数据库时 `db: false`。
  - 改动：`src/octop/api/routers/health.py` 删除 `users_loaded`、`agents_running` 及相应查询，响应模型同步收窄；`dashboard/src/api/probeHealth.ts` 不改。
  - 验证：`uv run pytest tests/integration/test_health_anonymous.py tests/integration/test_auth_flow.py tests/integration/test_setup_database.py tests/integration/test_setup_wizard.py tests/integration/test_dashboard_serve.py -q`
  - _需求：6.4, 7.1, 7.2_

- [ ] 17. docker-compose 透传新变量（0.25 人日）
  - 改动：先在 `tests/unit/test_docker_compose_database_env.py` 增加对 `_DATABASE_RUNTIME_ENV_KEYS` 的断言；再在 `docker/docker-compose.yml` 的 `environment` 列表补 7 行 `- NAME=${NAME:-}`。
  - 验证：`uv run pytest tests/unit/test_docker_compose_database_env.py -q`
  - _需求：8.1_

- [ ] 18. psycopg 兼容探针与 DBA 核查文档（2.5 人日）
  - 改动：新增 `tests/integration/test_postgresql_family_compat.py`（PG 标记），需求 9.1 列出的每项特性一个用例，在 PostgreSQL 16 上全绿。
  - 改动：新增 `docs/intranet/database.md`：DBA 认证核查（口令加密方式、`pg_hba` 方法、兼容模式、编码与时区、改加密方式后重设口令）；应用侧核查命令（打印 psycopg 与 libpq 版本、连接后打印 `server_version`）；libpq 不支持的认证方式（sha256、SM3）登记为阻断项并写明"需 DBA 改用 md5 或 scram-sha-256，否则需要更换驱动"；逐项结果登记表；首装、升级、连接数估算式与 verify-only 下恢复关闭的说明。
  - 验证：（PG）`OCTOP_TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:15432/octop_test uv run pytest tests/integration/test_postgresql_family_compat.py -m postgresql -q`；`uv run python -c "import psycopg; print(psycopg.__version__, psycopg.pq.version())"`
  - _需求：9.1, 9.2, 9.3_

- [ ] 19. 真实国产库集成回归（3 人日，行内环境）
  - 改动：`tests/support/postgresql.py` 新增 `pg_test_driver()`（读 `OCTOP_TEST_DATABASE_DRIVER`，默认 `"postgresql"`）；`tests/integration/test_postgresql_control_plane.py` 等构造 Octop 配置处改取它。
  - 改动：在行方金仓或 openGauss 实例上执行 `make test-postgresql` 与人工验收链路（导出 DDL → DBA 执行 → 授权 → DML 角色加 verify-only 启动 → `octop db check` → 登录 → 建 Agent → 一轮对话；w2-04 未合入时对话一项标"待 w2-04"），逐条登记进 `docs/intranet/database.md`；不可用的 SQL 特性登记为阻断项并给出改写方案与工作量，不得以跳过用例求绿。
  - 验证：`uv run pytest tests/unit/db -q`；（行内环境）`OCTOP_TEST_DATABASE_URL=postgresql://<user>:<pw>@<host>:<port>/<db> OCTOP_TEST_DATABASE_DRIVER=kingbase make test-postgresql`
  - _需求：10.1, 10.2, 10.3_

- [ ] 20. 收尾（0.75 人日）
  - 改动：`CHANGELOG-intranet.md` 记录新驱动名、7 个配置键、`octop db` 命令组、两个新错误码、`/api/health` 字段收窄、verify-only 下恢复关闭；`docs/api-intranet.md` 记录 `GET /api/health` 响应变化、`POST /api/setup/database` 的 503 `SCHEMA_OUT_OF_DATE`、恢复接口的 409 `DATABASE_DDL_DISABLED`；清理本 spec 引入的孤立符号；抽查 `/api/docs` 中 health 与 setup 的响应模型。
  - 验证：`make all && cd dashboard && npx tsc -b && npm run lint`
  - _需求：1.6, 3.7, 7.2_
