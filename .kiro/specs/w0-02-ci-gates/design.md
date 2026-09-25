# 设计文档：CI 前端与 PostgreSQL 门禁

> spec：`w0-02-ci-gates` ｜ 波次：Wave 0 ｜ 基线：`757fd12` ｜ 预估：2.5 人日
> 前置：无 ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 概述

**结论：** 门禁的契约是 Makefile 目标，CI 只是调用方。

- 前端：`make install-frontend`（`npm ci`，registry 可配置）加上 `make check-frontend`（`tsc -b`、ESLint、Prettier、vitest）。
- PostgreSQL：`make test-postgresql` 用 `-m postgresql -n 0` 串行执行，并加载 `tests/support/pg_strict.py` 插件，任何 `postgresql` 用例被跳过都会让会话失败。
- 所有 fork 目标都放在新文件 `Makefile.intranet` 里，根 `Makefile` 只在末尾加一行 `include`。
- `.github/workflows/ci.yml` 新增 `frontend` 和 `postgresql` 两个 job，既有三个 job 不改。
- 两条合同测试守住门禁本身，防止上游同步时 fork 的 job 被冲突解决悄悄丢掉。
- 基线上前端不绿（1 个 ESLint error、4 个 vitest 失败文件），本 spec 先清债再接门禁。

## 现状

以下事实都在基线 `757fd12` 上核实过。行号只作提示。

**CI 与 Makefile**

- `.github/workflows/ci.yml`：
  - `quality` job（≈L14-42）与 `test-windows` job（≈L44-66）的步骤都是 `make install` → `make lint` → `make typecheck` → `make test`。
  - `live-tests`（≈L68-129）只执行 `make test-live`。
  - `quality`（≈L19）与 `test-windows`（≈L47）带 `if: ${{ !startsWith(github.head_ref, 'chore/sync-develop-after-') }}`；`live-tests`（≈L72-74）把同一个判断与"只允许主仓库"合并在一起。
  - 全文件没有 `services:`，也没有 `setup-node`。
- `Makefile`：
  - `.DEFAULT_GOAL := help`（≈L15）。
  - `DASHBOARD_DIR`（≈L18）、`RUN`（≈L28）、`PYTHON`（≈L29，有 uv 时为 `uv run python`）。
  - `build-frontend` 在 ≈L99 硬编码 `npm ci`。
  - `all: format-all lint typecheck test`（≈L202）。
  - `test` 执行 `$(RUN) pytest -n $(PYTEST_JOBS) -m "not live"`（≈L222-225）。
  - `lint-frontend` = `npm run lint` + `npm run format:check`（≈L262-267）。
  - `typecheck-frontend` = `npx tsc -b`（≈L274-277）。
  - `check-all: lint-all typecheck-all test`（≈L290-291）。
  - 文件共 342 行，最后一个目标是 `version`（≈L340-342）。
  - 仓库里没有 `test-frontend`、`check-frontend`、`install-frontend`、`test-postgresql` 这几个目标。
- `.githooks/pre-commit`：执行 `make precommit`（≈L26）和 `npm run build`（≈L42-46），不跑 ESLint 和 vitest。
- `rg -n 'vitest|npm test|npm run test|postgres' Makefile .githooks/pre-commit .github/workflows/ci.yml` 零命中。
- 其他 workflow 与 Docker 用的 Node 版本：`release.yml` ≈L44-48 用 `actions/setup-node@v4`、`node-version: "20"`、`cache-dependency-path: dashboard/package-lock.json`；`docker/Dockerfile` ≈L36 为 `FROM node:20-slim`。

**前端**

- `dashboard/package.json`：`"lint": "eslint ."`（≈L14），`"test": "vitest run"`（≈L15），`"format:check"`（≈L13）。
- `dashboard/vitest.config.ts`：`environment: "jsdom"`、`setupFiles: ["./src/test/setup.ts"]`、`include: ["src/**/*.test.ts", "src/**/*.test.tsx"]`（≈L21-25），`pool: "threads"`。
- `dashboard/tsconfig.app.json` 把 `src/**/*.test.ts(x)` 排除在 `tsc -b` 之外。所以测试文件里未使用的导入只会被 ESLint 抓到。
- `dashboard/.npmrc`：`registry=https://registry.npmjs.org`（≈L6），`replace-registry-host=always`（≈L12）。注释（≈L1-4）说明路径前缀型镜像会有问题。
- 在 `dashboard/` 副本上（Node 22.22.2、npm 10.9.7）的实测结果：

| 命令 | 退出码 | 结果 |
|---|---|---|
| `npm ci` | 0 | 安装 1067 个包，约 22 秒 |
| `npx tsc -b` | 0 | 约 28 秒 |
| `npm run format:check` | 0 | 约 13 秒 |
| `npm run lint` | **1** | 1 个 error，67 个 warning。error 位于 `src/pages/Agent/Channels/components/constants.test.ts` ≈L5，未使用的导入 `DEFAULT_CHANNEL_DISPLAY_CONFIG` |
| `npm test` | **1** | 169 个文件中 4 个失败；877 个用例中 1 个失败；约 85 秒 |

- 4 个 vitest 失败文件的根因：
  - `src/components/DocumentPreviewCore.docxSanitize.test.ts`、`src/pages/Agent/Skills/skillMarkdown.test.ts`、`src/pages/Agent/Skills/components/SkillDrawer.test.ts` 三个套件在收集阶段抛出 `ReferenceError: DOMMatrix is not defined`。引用链为：`DocumentPreviewCore.tsx` ≈L20 导入 `PdfDocumentPreview`，后者 ≈L31 执行 `import { Document, Page, pdfjs } from "react-pdf"`，进而加载 `pdfjs-dist` 5.4.296，而 jsdom 25 不提供 `DOMMatrix`。`SkillDrawer.tsx` ≈L21 导入 `FileViewer`，再经 `Workspace/components/DocumentPreview.tsx` ≈L10 走到同一条链。仓库里已有两处用 `vi.mock("react-pdf", …)` 规避：`DocumentPreviewCore.pdfSkeleton.test.tsx` ≈L5-9 和 `PdfDocumentPreview.windowed.test.tsx` ≈L16。
  - `src/api/modules/publishedExperts.test.ts` ≈L41-47 断言第 3 次 `request` 调用只有 `{ method: "POST" }`。但测试在 ≈L21-25 传入了 body，而实现 `publishedExperts.ts` ≈L71-75 的 `refresh` 会在 body 存在时发送 `JSON.stringify(body)`；后端 `src/octop/api/routers/experts.py` 的 `refresh_published_expert`（≈L437-445）接受 `body: RefreshPublishedExpertBody | None`。所以过期的是测试，不是实现。
- 在副本上试做清债：给 3 个套件加 `vi.mock("react-pdf")`，把过期断言补上 body，删除未使用的导入。之后 `npx tsc -b`、`npm run lint`、`npm run format:check`、`npm test` 的退出码全为 0，结果为 169 个文件、889 个用例全部通过。

**PostgreSQL**

- `pyproject.toml` ≈L205-209 注册了 `postgresql` marker，没有 `addopts`。
- `tests/support/postgresql.py` 的 `requires_postgresql`（≈L14-17）是 `pytest.mark.skipif(not os.environ.get("OCTOP_TEST_DATABASE_URL"), …)`。
- 基线上 `uv run pytest -m postgresql --co -q` 的结果是 `7/3419 tests collected (3412 deselected)`：
  - `tests/integration/test_postgresql_control_plane.py`：`test_pg_migrate_and_user_roundtrip`（≈L52）、`test_pg_control_plane_repo_smoke`（≈L73）、`test_pg_probe_ok`（≈L153）、`test_pg_backup_roundtrip`（≈L173；≈L174-175 在 `pg_dump` / `pg_restore` 不在 PATH 时执行 `pytest.skip`）、`test_setup_database_postgresql_bind`（≈L239）、`test_pg_knowledge_base_max_documents_schema_and_crud`（≈L288）。
  - `tests/integration/test_postgresql_checkpoint_history.py`：`test_postgres_checkpoint_history_uses_graph_reader`（≈L18）。
  - `tests/unit/agents/test_memory_backend.py` **不带** `postgresql` 标记。S12 的 additions 中相反的说法不成立。
- 用例在 `_reset_public_schema`（≈L29-34）里执行 `DROP SCHEMA public CASCADE`，文件头注释（≈L3、L8）要求使用专用库。
- 用本地 PostgreSQL 16.13（Ubuntu 24.04 软件包，未安装 pgvector）实测：
  - `uv run pytest -m postgresql -n 0 -rs`：7 passed，约 36 秒，`test_pg_backup_roundtrip` 也实际执行了。
  - 同样的命令加 `-n 4`：**4 failed、3 passed**，错误为 `psycopg.errors.UniqueViolation`、`UndefinedTable: relation "users" does not exist`。根因是并行进程在同一个库上互相 `DROP SCHEMA`。
  - 未设置 DSN 时退出码为 0，7 个用例全部 skip。
- `uv run pytest -p tests.support.postgresql …` 会报 `ImportError: Error importing plugin "tests.support.postgresql": No module named 'tests'`，因为 `-p` 插件在 rootdir 被加入 `sys.path` 之前就要导入。换成 `uv run python -m pytest -p tests.support.postgresql …` 可以正常收集，因为 `python -m` 会把当前目录放进 `sys.path`。
- 在草稿目录用等价的 strict 插件实测：未设置 DSN 时退出码为 1，并列出 7 个被跳过的 nodeid；设置 DSN 后 7 passed，退出码为 0。
- `w0-01-fork-migration-namespace` 会新增 `tests/integration/test_postgresql_fork_migrations.py`。其中的用例同样带 `@requires_postgresql` + `@pytest.mark.postgresql`，并照抄 `_reset_public_schema`。本 spec 合入后，这些用例会按标记被自动收集，同样必须串行执行。

## 方案

**1. 以 Makefile 目标为契约，fork 目标集中放在 `Makefile.intranet`。**
根 `Makefile` 在本地 shallow clone 上用 `--full-history` 实测有 21 次改动（真实值只会更高），属于热文件。按 steering §5 的原则，热文件里只留一行调用：根 `Makefile` 末尾加 `include Makefile.intranet`。因为 `.DEFAULT_GOAL := help` 在 ≈L15 已经显式设定，被 include 的目标不会抢走默认目标。`w0-04` 的 `make relock` 等后续 fork 目标也可以追加到这个文件里。

**2. 不改变上游目标的语义。**
S13 曾建议把 vitest 接进 `check-all` 和 pre-commit，本方案不采纳，理由如下：
- `all`、`check-all` 和 pre-commit 是上游的 ship bar，改它们会在每次同步时制造冲突。
- vitest 单次约 85 秒，加进 pre-commit 会显著拖慢每次提交。
- 机器兜底由 CI 的 `frontend` job 负责；本地则由各前端 spec 的收尾任务显式执行 `make check-frontend`。

**3. PG 用例单独成目标、串行执行、跳过即失败。**
S15 曾建议"给 Linux job 加 postgres service"，本方案不采纳。实测表明，DSN 一旦暴露给 `make test`（`-n auto`），用例就会互相 `DROP SCHEMA`，导致失败；而且本 spec 的范围要求既有 job 不变。所以采用以下做法：
- 新增独立的 `postgresql` job。
- DSN 只写在 `make test-postgresql` 那一步的 `env` 里。
- 目标里固定使用 `-n 0`。
- 用 `pg_strict` 插件把 skip 变成失败，同时覆盖"DSN 缺失"和"`pg_dump` 缺失"两类静默跳过。
- 未选中任何用例时，由 pytest 自带的退出码 5 兜底。

**4. CI 用 `postgres:16`，不用 `pgvector/pgvector:pg16`。**
基线的 7 个用例在不含 pgvector 的 PG 16 上全部通过。而 D3 的目标库是人大金仓或 openGauss，不保证有 pgvector，所以 CI 不应依赖这个扩展。以后若有 spec 确实需要 pgvector，由该 spec 在 D2/D3 前提下论证并修改镜像。

**5. 先清债，再接门禁。**
清债只修测试，不修生产代码：
- 3 个 DOMMatrix 套件沿用仓库已有的 `vi.mock("react-pdf", …)` 写法。
- 过期断言按实现和后端契约补上 body。
- 未使用的导入直接删除。
- 67 个 warning 不影响退出码，不在本 spec 处理。

**6. 用合同测试守住门禁本身。**
`ci.yml` 在同一口径下有 11 次改动。同步时如果冲突被整体"取上游"，fork 的两个 job 会悄悄消失。`tests/unit/test_ci_gates_contract.py` 会随 `make test` 在 Linux 和 Windows 上执行，一旦门禁丢失就会变红。

## 组件与接口

| 文件 | 类型 | 内容 |
|---|---|---|
| `Makefile` | 修改 | 末尾（`version` 目标之后，≈L342 后）追加一行 `include Makefile.intranet`，其余不动 |
| `Makefile.intranet` | 新增 | 五个目标，见下文 |
| `tests/support/pg_strict.py` | 新增 | pytest 插件，只能通过 `-p tests.support.pg_strict` 显式加载，不自动注册 |
| `.github/workflows/ci.yml` | 修改 | 在 `test-windows`（≈L66）与 `live-tests`（≈L68）之间插入 `frontend` 与 `postgresql` 两个 job |
| `tests/unit/test_ci_gates_contract.py` | 新增 | CI 与 Makefile 的合同测试 |
| `tests/unit/test_pg_strict_plugin.py` | 新增 | 插件的钩子级单测 |
| `dashboard/src/components/DocumentPreviewCore.docxSanitize.test.ts` | 修改 | vitest 导入里加 `vi`，并加一行 `vi.mock("react-pdf", () => ({ pdfjs: { GlobalWorkerOptions: {} } }))`（这些套件不渲染 PDF，导入期只触碰 `pdfjs.GlobalWorkerOptions`） |
| `dashboard/src/pages/Agent/Skills/skillMarkdown.test.ts` | 修改 | 同上 |
| `dashboard/src/pages/Agent/Skills/components/SkillDrawer.test.ts` | 修改 | 同上 |
| `dashboard/src/api/modules/publishedExperts.test.ts` | 修改 | 第 3 次调用的期望（≈L41-47）补上 `body: JSON.stringify({...})` |
| `dashboard/src/pages/Agent/Channels/components/constants.test.ts` | 修改 | 删除 ≈L5 未使用的导入 |
| `CHANGELOG-intranet.md` | 不在本提交 | 文件由 `w0-04` 创建并补录本 spec 的条目 |

### `Makefile.intranet`（新增）

实现与下面的草稿等价，只是省掉了 `NPM_REGISTRY ?=`（未定义的变量本来就展开为空），并把五个 `.PHONY` 合成一行。

```make
# Intranet fork targets. Included from the root Makefile (one `include` line)
# so upstream Makefile merges stay trivial. See .kiro/specs/w0-02-ci-gates/.
#
#   make install-frontend [NPM_REGISTRY=https://npm.example/]   npm ci in dashboard/
#   make check-frontend                                          tsc -b + eslint + prettier + vitest
#   OCTOP_TEST_DATABASE_URL=postgresql://… make test-postgresql  serial PG suite; a skip is a failure
#
# PG tests DROP SCHEMA public: point the DSN at a dedicated database and never
# export it while running `make test` (-n auto runs them in parallel and they collide).

NPM_REGISTRY ?=

.PHONY: help-intranet
help-intranet:
	@echo "Intranet fork targets (Makefile.intranet):"
	@echo "  install-frontend   npm ci in dashboard/ (NPM_REGISTRY=<url> overrides .npmrc registry)"
	@echo "  test-frontend      vitest run"
	@echo "  check-frontend     typecheck-frontend + lint-frontend + test-frontend"
	@echo "  test-postgresql    pytest -m postgresql -n 0 with tests.support.pg_strict"
	@echo "                     needs OCTOP_TEST_DATABASE_URL (dedicated DB; do not export for make test)"

.PHONY: install-frontend
install-frontend:
	cd $(DASHBOARD_DIR) && npm ci --no-audit --no-fund $(if $(strip $(NPM_REGISTRY)),--registry=$(strip $(NPM_REGISTRY)),)

.PHONY: test-frontend
test-frontend:
	@echo "[test-frontend] vitest..."
	cd $(DASHBOARD_DIR) && npm run test

.PHONY: check-frontend
check-frontend: typecheck-frontend lint-frontend test-frontend

.PHONY: test-postgresql
test-postgresql:
	@if [ -z "$$OCTOP_TEST_DATABASE_URL" ]; then \
		echo "[test-postgresql] OCTOP_TEST_DATABASE_URL is not set (use a dedicated database: tests DROP SCHEMA public)"; \
		exit 2; \
	fi
	$(PYTHON) -m pytest -p tests.support.pg_strict -m postgresql -n 0 -rs
```

要点：

- 已在草稿里核实过 make 的变量语义：`NPM_REGISTRY` 无论来自命令行还是环境变量都能生效，空字符串时不会生成 `--registry`；`OCTOP_TEST_DATABASE_URL` 无论来自命令行还是环境变量都会被导出到 recipe 的 shell。
- 执行 pytest 的那一行不引用 DSN，所以 make 回显里不会出现口令。
- `$(PYTHON) -m pytest` 在有 uv 时展开为 `uv run python -m pytest`，这是 `-p tests.support.pg_strict` 能被导入的前提（见"现状"）。
- `-n 0` 显式关闭 xdist，因为 `make test` 默认是 `-n auto`。

### `tests/support/pg_strict.py`（新增）

```python
"""pytest plugin for ``make test-postgresql``: a skipped PostgreSQL test fails the run.

``requires_postgresql`` skips every ``postgresql``-marked test when
``OCTOP_TEST_DATABASE_URL`` is unset, and some tests skip when client tools
(``pg_dump``) are missing. Inside the dedicated PG gate a skip means "not
verified", so this plugin turns an otherwise green session red and lists the
skipped node ids. Load explicitly with ``-p tests.support.pg_strict``.
"""

from __future__ import annotations

import pytest

MARKER = "postgresql"
_skipped: list[str] = []


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if report.skipped and MARKER in report.keywords:
        _skipped.append(report.nodeid)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if _skipped and exitstatus == pytest.ExitCode.OK:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    if _skipped:
        terminalreporter.write_line(
            f"[pg-strict] {len(_skipped)} postgresql test(s) skipped; failing the run:", red=True
        )
        for nodeid in _skipped:
            terminalreporter.write_line(f"  {nodeid}")
```

- `report.keywords` 是按键名做精确匹配的字典。标记名 `postgresql` 会出现在里面，而 `test_use_control_plane_dsn_requires_postgresql` 这类函数名不会误中。
- `pytest.TerminalReporter`、`pytest.TestReport`、`pytest.ExitCode` 在当前 venv 的 pytest 9.1.1 中都已导出（已核实）。
- 模块级列表只在单次会话内使用；单测中用 `monkeypatch.setattr(pg_strict, "_skipped", [])` 隔离。

### `.github/workflows/ci.yml`（插入两个 job）

```yaml
  frontend:
    name: Frontend (tsc / eslint / prettier / vitest)
    runs-on: ubuntu-latest
    if: ${{ !startsWith(github.head_ref, 'chore/sync-develop-after-') }}
    env:
      NPM_REGISTRY: ${{ vars.NPM_REGISTRY }}
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: npm
          cache-dependency-path: dashboard/package-lock.json

      - name: Install npm dependencies
        run: make install-frontend

      - name: Frontend checks
        run: make check-frontend

  postgresql:
    name: PostgreSQL integration
    runs-on: ubuntu-latest
    if: ${{ !startsWith(github.head_ref, 'chore/sync-develop-after-') }}
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_USER: octop
          POSTGRES_PASSWORD: octop
          POSTGRES_DB: octop_test
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -U octop -d octop_test"
          --health-interval 5s
          --health-timeout 5s
          --health-retries 10
    steps:
      - uses: actions/checkout@v4

      - uses: astral-sh/setup-uv@v4
        with:
          enable-cache: true
          python-version: "3.12"

      - name: Install dependencies
        run: make install

      - name: PostgreSQL client tools
        run: pg_dump --version && pg_restore --version

      - name: PostgreSQL tests
        env:
          OCTOP_TEST_DATABASE_URL: postgresql://octop:octop@127.0.0.1:5432/octop_test
        run: make test-postgresql
```

- `quality`、`test-windows`、`live-tests` 不改。新 job 的写法与它们保持一致：`actions/checkout@v4`、`astral-sh/setup-uv@v4`、`enable-cache: true`。
- 未设置仓库变量时，`vars.NPM_REGISTRY` 为空字符串，`make install-frontend` 不会带 `--registry`。
- service 的口令只属于一次性容器，只在 runner 本机可达，所以可以明文写在 `ci.yml` 里。

### `tests/unit/test_ci_gates_contract.py`（新增）

```python
_REPO = Path(__file__).resolve().parents[2]

def _ci_jobs() -> dict[str, Any]: ...            # yaml.safe_load(.github/workflows/ci.yml)["jobs"]
def _step_runs(job: dict[str, Any]) -> list[str]: ...

@pytest.mark.parametrize(("job", "targets"), [("frontend", [...]), ("postgresql", [...])])
def test_ci_fork_job_runs_make_targets(job, targets) -> None: ...  # 调用对应 make 目标，带 sync-develop-after- 条件
def test_ci_postgresql_service_and_dsn_scoped_to_its_step() -> None: ...  # postgres service；DSN 只在 test-postgresql 那一步，不在 job 级、不在其他 job
def test_makefile_intranet_defines_gate_targets() -> None: ...  # include 行 + 按行首 "^<target>:" 查找五个目标
```

- 只读文本文件，用 `encoding="utf-8"` 和 `pathlib` 拼路径，与平台无关。
- `yaml` 由当前依赖树提供（venv 里是 6.0.3），它不是 `pyproject.toml` 的直接依赖。如果 `w2-01` 收窄依赖后 `yaml` 不再可用，就改成与 `tests/unit/test_docker_compose_database_env.py` 相同的纯文本解析。
- 断言故意写得宽松：只检查 fork job 存在、调用了对应目标、DSN 的作用域正确，不锁死上游 job 的全部步骤，以免上游正常修改 job 时误报。

### `tests/unit/test_pg_strict_plugin.py`（新增）

用 `types.SimpleNamespace` 伪造 `report`（字段 `skipped`、`keywords`、`nodeid`）和 `session`（字段 `exitstatus`），直接调用 `pytest_runtest_logreport` 与 `pytest_sessionfinish`（一个参数化用例，终端摘要由"门禁的负向验证"实跑覆盖）。覆盖以下四种情形：

1. `postgresql` 用例被跳过：退出码由 0 变为 1。
2. 非 `postgresql` 用例被跳过：退出码不变。
3. `postgresql` 用例通过：退出码不变。
4. 退出码原本就是 1：保持为 1，不被覆盖成别的值。

## 数据模型

无。本 spec 不新增 fork 迁移，也不触碰 `_schema_version` 或 `_fork_schema_version`。

## 配置

`config.py` 不新增键，不涉及三触点。

门禁只用到下面三个变量，它们都不是 `OctopConfig` 字段：

| 名称 | 所在层 | 作用 |
|---|---|---|
| `NPM_REGISTRY` | Makefile 变量或环境变量 | 非空时作为 `npm ci --registry` 的值；为空时沿用 `dashboard/.npmrc` |
| `OCTOP_TEST_DATABASE_URL` | 环境变量（已有，测试专用） | `make test-postgresql` 的必需项 |
| `vars.NPM_REGISTRY` | GitHub 仓库变量（可选） | 由 `frontend` job 转交给 `NPM_REGISTRY` |

## 错误处理

不新增 `ErrorCode`，也不修改 `_DEFAULT_STATUS`。门禁的失败语义完全由退出码表达：

| 情形 | 发生失败的位置 | 可观察结果 |
|---|---|---|
| 未设置 DSN | `test-postgresql` 的 shell 守卫 | 输出 `OCTOP_TEST_DATABASE_URL is not set …`，make 非零退出，不启动 pytest |
| `postgresql` 用例被跳过 | `pg_strict` 插件 | pytest 退出码 1，摘要中出现 `[pg-strict] N postgresql test(s) skipped` 和对应的 nodeid |
| 未选中任何用例 | pytest 自身 | 退出码 5 |
| 用例失败 | pytest 自身 | 退出码 1 |
| 前端任一步失败 | `check-frontend` 的前置目标 | make 在第一个失败的前置目标处停止，退出码非零 |

## 安全考虑

- **DSN 不进日志。** `test-postgresql` 的守卫语句用 `@` 静默，执行 pytest 的那一行不引用 DSN。CI 里 DSN 只写在一个 step 的 `env` 中。行内流水线（`w2-02`）接入时，DSN 应当来自流水线的密文变量，不要写进脚本。
- **registry 地址会被回显。** `install-frontend` 会回显 `--registry=<url>`。行内私服的凭据应当放在 npm 的 `_authToken` 配置或流水线密文里，不要写成 `https://user:pass@…` 的 URL 形式。
- **`npm ci --no-audit --no-fund`** 避免在安装时访问 audit / fund 端点。这些端点在断网环境不可达，而且本来就不属于门禁。
- **专用库。** PG 用例会执行 `DROP SCHEMA public CASCADE`。`Makefile.intranet` 的头注释和 `help-intranet` 都写明必须使用专用库，严禁指向任何业务库。
- **不放宽检查。** 清债不引入 skip、exclude、`eslint-disable` 或规则放宽（需求 6.4）。
- **边界说明。** 本 spec 不涉及生产代码，不改变任何运行期行为，也不新增出网点（CI 在公网 runner 上执行，与现状相同）。

## 测试策略

**单测（新增，随 `make test` 在 Linux 和 Windows 上执行）：**

```bash
uv run pytest tests/unit/test_ci_gates_contract.py tests/unit/test_pg_strict_plugin.py -q
```

**前端（本地复现 CI `frontend` job）：**

```bash
make install-frontend                                     # 或 make install-frontend NPM_REGISTRY=https://<行内私服>/
make check-frontend
cd dashboard && npx tsc -b && npm run lint && npm run test  # 等价的分步命令
```

**PostgreSQL（本地复现 CI `postgresql` job）：**

```bash
docker compose -f docker/docker-compose.postgres.yml up -d   # 或者任意一个专用的 PG 16 库
OCTOP_TEST_DATABASE_URL='postgresql://octop:octop@127.0.0.1:5432/octop' make test-postgresql
```

**门禁的负向验证（证明"跳过即失败"）：**

```bash
env -u OCTOP_TEST_DATABASE_URL make test-postgresql; echo "exit=$?"         # 期望非零，并提示 not set
env -u OCTOP_TEST_DATABASE_URL uv run python -m pytest -p tests.support.pg_strict -m postgresql -n 0 -q; echo "exit=$?"   # 期望 1，并列出被跳过的用例
make -n install-frontend NPM_REGISTRY=https://npm.example/                    # 期望回显里含 --registry=https://npm.example/
make -n install-frontend                                                      # 期望回显里不含 --registry
```

**CI 实跑验证：**
开 PR 后，`frontend` 与 `postgresql` 两个 check 都应为绿色，而且 `postgresql` 的日志摘要里 passed 数等于选中的用例数，没有 skip。另外建一个临时分支，故意在某个 vitest 用例里写一个失败断言，确认 `frontend` 变红；再临时删掉 PG step 的 `env`，确认 `postgresql` 变红。这两个临时分支验证完即删除，不合入。

**回归：** 执行 `make all`。注意 `format-all` 需要 `dashboard/node_modules`，所以要先执行一次 `make install-frontend`。

## 与其他 spec 的交接

**依赖：** 无。本 spec 与 `w0-01` 以及 `w0-03` 到 `w0-05` 互相独立，可以并行合入。`w0-01` 新增的 `tests/integration/test_postgresql_fork_migrations.py` 会按 `postgresql` 标记被本 spec 的目标自动收集。如果它先合入，任务 1 记录的 PG 用例数就相应增加。

**交付给谁：**

- **凡把验收写成 vitest 或 PG 用例的 spec**（steering §1.3），源分析里点名的有 `w1-02`、`w4-01`、`p2-04`、`p2-07`（vitest），以及 `w2-03`、`w4-02`、`p2-02`、`p2-03`、`p2-08`（PG 集成用例）：在 tasks.md 里写本地复现命令 `make check-frontend` 或 `OCTOP_TEST_DATABASE_URL=… make test-postgresql`。新增的 PG 用例必须同时带 `@requires_postgresql` 与 `@pytest.mark.postgresql`，并且假设它们串行执行、会独占 `public` schema。
- **`w0-03-test-auth-baseline`**：它会修改 setup 契约，改完之后 `test_setup_database_postgresql_bind`（≈L239，调用 `/api/setup/initial-admin`）要在 `make test-postgresql` 下保持绿色。
- **`w0-04-fork-isolation-points`**：
  - 上游同步手册里写明：`ci.yml` 发生冲突时不能整体取上游，必须保留 `frontend` / `postgresql` 两个 job（合同测试会拦截）；根 `Makefile` 的 `include Makefile.intranet` 行必须保留；同步之后要执行 `make check-frontend` 与 `make test-postgresql`。
  - `make relock` 可以追加到 `Makefile.intranet`。
  - `CHANGELOG-intranet.md` 由 `w0-04` 统一格式，本 spec 只追加条目。如果本 spec 先合入，就先建一个只含本条目的文件。
- **`w1-04-content-trim`**：删除 `.github/` 工作流时保留 `ci.yml`（steering §3 已规定）。它删除前端页面或组件时，要同批删除对应的 vitest 文件，不能用 skip 让门禁保持绿色。
- **`w2-01-offline-build`**：
  - 在行内 npm 私服上实测 `make install-frontend NPM_REGISTRY=…`，包括路径前缀型镜像与 `.npmrc` 的 `replace-registry-host=always` 能否兼容。本环境的出网策略拒绝访问第三方镜像，无法实测。
  - 负责把 `postgres:16`、`node:20` 镜像导入行内镜像仓库。
  - 如需把 `vite build` 纳入门禁，也由 `w2-01` 在 `Makefile.intranet` 里加目标。
  - 如果依赖收窄导致 `yaml` 不可用，要同批把合同测试改成纯文本解析。
- **`w2-02-supply-chain-compliance`**：用行内流水线替代 `ci.yml` 时，改为调用 `make install-frontend`、`make check-frontend`、`make test-postgresql` 这组契约，DSN 来自流水线密文。同时要改写 `tests/unit/test_ci_gates_contract.py` 的断言对象，让它校验行内流水线的定义文件，不能直接删除该测试。
- **`w2-03-database-adaptation`**：真实的金仓 / openGauss 回归由它负责。如果行内流水线能提供这些实例，可以复用 `make test-postgresql`，只需把 DSN 指向目标库。

**看起来相关、但归别的 spec 的事项：**

- dashboard locale 对等测试：steering §1.2，不在本 spec 范围。
- ESLint 的 67 个 warning：不影响退出码，谁改到对应文件谁顺手处理。
- `make build-frontend` 继续硬编码 `npm ci`，本 spec 不改（`w2-01`）。
- SAST 与 codeql 替代：`w2-02`。

## 风险与回滚

| 风险 | 影响 | 缓解 |
|---|---|---|
| runner 上 `pg_dump` 的主版本与 `postgres:16` 不一致（例如 runner 镜像升级到 17 客户端，而 17 的转储会带 PG16 不认识的 `SET transaction_timeout`） | `test_pg_backup_roundtrip` 失败，或者因客户端缺失而 skip，然后被 strict 插件判红 | job 里有单独一步打印 `pg_dump --version`，出问题时一眼可见。修正方式是让 service 镜像的 tag 跟随 runner 客户端的主版本，或者在 job 里安装匹配版本的客户端。本环境核实过 Ubuntu 24.04 自带 16.13 客户端；GitHub `ubuntu-latest` 的客户端版本需要在首次 CI 运行时确认 |
| CI 用 Node 20（与 `docker/Dockerfile` 一致），而清债是在 Node 22.22.2 上实测的 | vitest 或 jsdom 在 Node 20 上可能出现差异 | 以首次 CI 运行为准。若有差异，在任务 6 里补充修正，不降低门禁标准 |
| 开发者在 shell 里全局导出了 DSN，再执行 `make test` / `make all` | PG 用例在 `-n auto` 下互相 `DROP SCHEMA`，随机失败（已实测） | `Makefile.intranet` 的头注释和 `help-intranet` 给出警示。本 spec 不修改 `tests/support/postgresql.py` 的上游语义 |
| 上游同步时 `ci.yml` 或根 `Makefile` 冲突被整体取上游 | fork 门禁悄悄消失 | 合同测试会让 `make test` 变红；`w0-04` 的同步手册也会写明 |
| 上游新增的 vitest 用例或 ESLint 规则在同步后不绿 | `frontend` job 变红 | 这正是门禁该起的作用。同步 PR 里修正测试，或者在 `CHANGELOG-intranet.md` 里登记为同步债并在同一窗口清掉；不允许用 skip 保持绿色 |
| vitest 约 85 秒，加上 npm ci 与 tsc，`frontend` job 大约需要 3 分钟 | PR 反馈变慢 | 与既有后端 job 并行执行，不增加关键路径 |

**回滚：** 本 spec 不改任何生产代码，也没有数据迁移。需要回滚时，revert 合并提交即可：`include` 行、`Makefile.intranet`、两个 CI job、两个新测试文件和前端测试修正会一起撤回。只想临时停用某个 job 时，可以在该 job 上加 `if: false`，但必须同时在 `tests/unit/test_ci_gates_contract.py` 里显式放宽对应断言并写明原因，否则 `make test` 会变红。

## 待行方确认

steering 第 4 节的 D 编号里，没有需要为本 spec 单独拍板的项。以下两项默认假设会影响本 spec 的边界：

- **D3（控制面数据库为 PG 系）：** 本 spec 的 CI 只覆盖社区版 PostgreSQL 16。如果行方最终选定达梦、OceanBase 或 TiDB，PG 门禁仍然保留，但覆盖不到目标库，需要由 `w2-03` 另立门禁。
- **D7（长期 fork，每 2-4 个上游 release 同步一次）：** 本 spec 把 fork 目标隔离进 `Makefile.intranet`，并用合同测试守住 `ci.yml`，前提就是长期 fork。

另外还有两项工程侧的确认，不属于 D 编号：

- 在迁入行内流水线（`w2-02`）之前，fork 仓库是否仍然托管在 GitHub、使用 GitHub-hosted runner。本 spec 按"是"起草。
- 是否在分支保护里把 `frontend` 与 `postgresql` 设为必需检查。本 spec 建议设为必需；这属于仓库设置，不在代码里。
