# 行内版变更记录

本文件只记录行内 fork 的变更；上游变更见 `CHANGELOG.md`（fork 不修改该文件）。
格式参照 Keep a Changelog；每条以 spec 目录名开头，写明用户可感知的变化与本地复现命令。

## [Unreleased]

### 新增

- `w0-01-fork-migration-namespace`：fork 独立迁移空间：`forkNNN_*.sql` / `forkNNN_*.pg.sql` + `run_fork_migrations` + `_fork_schema_version` 水位；备份 manifest 新增 `fork_schema_version`（commits 943652f, b7cd9fd）。
- `w0-02-ci-gates`：新增 `Makefile.intranet`（根 Makefile 只加一行 include），提供 `install-frontend`（可用 `NPM_REGISTRY` 指定 registry）、`test-frontend`、`check-frontend`（tsc + ESLint + Prettier + vitest）、`test-postgresql`、`help-intranet`；ci.yml 新增 `frontend`（Node 20）与 `postgresql`（postgres:16）两个 job，既有 job 不变；PG 用例约定为只用专用库、串行执行（`-n 0`），并由 `tests.support.pg_strict` 把任何跳过判为失败，DSN 只放在 CI 的 step 级 env；合同测试防止门禁在上游同步时丢失；清理了前端基线债（1 个 ESLint error、3 个 DOMMatrix 套件、1 个过期断言）。本地复现：`make install-frontend && make check-frontend`，`OCTOP_TEST_DATABASE_URL=<专用库> make test-postgresql`。
- `w0-03-test-auth-baseline`：bootstrap_admin now explicitly grants every permission key (computed at runtime from ALL_PERMISSION_KEYS). Adds the env_admins fixture and AdminCredentials with system/security/audit slots (aliases of one admin until w3-03); in-fixture user management goes through the security slot. Adds tests/support/auth_guards.py, test-process-only (CAPTCHA_SEAMS, DEPENDENCY_OVERRIDES, REAL_AUTH_GUARD_MODULES, the real_auth_guards marker). Login captcha is exempt by default in tests; captcha-specific tests opt out. Existing tests are unchanged.
- `w0-04-fork-isolation-points`：fork 隔离点，合入时全部为空、运行时行为不变。文案 overlay：后端 `src/octop/i18n/intranet/{en,zh}.json`、前端 `dashboard/src/locales/intranet/{en,zh}.json`，深合并覆盖上游 bundle，en / zh 必须同键，不增删上游 bundle 的键；i18n 门禁改读合并后的 bundle。路由下线：在 `src/octop/api/intranet_mounts.py` 的 `_FORK_DISABLED_MOUNTS` 登记 `"<模块>:<属性>"`，引用无效时启动失败。连接器目录：`src/octop/infra/connectors/catalog_intranet.py` 的 `_FORK_REMOVED`（隐藏上游 kind）与 `_fork_entries()`（追加行内条目）。锁文件：`make relock [PYPI_INDEX=<url>] [NPM_REGISTRY=<url>]` 按当前清单重生成 `uv.lock` 与 `dashboard/package-lock.json`。文档：本文件、`docs/api-intranet.md`、同步手册 `docs/intranet/upstream-sync.md`；AGENTS.md 路径勘误。本地复现：`uv run pytest tests/unit/i18n tests/unit/test_fork_isolation_contract.py tests/unit/api/test_intranet_mounts.py tests/unit/connectors/test_catalog_intranet.py tests/integration/test_connectors_catalog_intranet.py -q`，`cd dashboard && npx vitest run src/i18nIntranet.test.ts`。

### 变更

### 移除

### 安全

- `w0-05-ssrf-intranet-allowlist`：SSRF 守卫支持内网白名单（`intranet_allow_cidrs` / `intranet_allow_host_suffixes` / `intranet_allow_http`，默认空 = 行为不变；按解析后的 IP 比对防 DNS 重绑定，配置非法时启动失败）。

## 上游同步记录

| 日期 | 上游区间 | 方式 | 命中 fork 改动面文件数 | 冲突文件 | 备注 |
|---|---|---|---|---|---|
| — | 基线 `757fd12`（1.0.1 + hotfix #792） | fork 起点 | — | — | — |
