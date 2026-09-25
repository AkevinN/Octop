# 实施计划：CI 前端与 PostgreSQL 门禁

> spec：`w0-02-ci-gates` ｜ 波次：Wave 0 ｜ 基线：`757fd12` ｜ 预估：2.5 人日
> 前置：无 ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

每个顶层任务完成后可独立提交；提交前运行任务内的验证命令。

本地 PG 实例可以用 `docker compose -f docker/docker-compose.postgres.yml up -d` 启动（DSN 为 `postgresql://octop:octop@127.0.0.1:5432/octop`），也可以是任意一个专用的 PG 16 库。PG 用例会执行 `DROP SCHEMA public CASCADE`，严禁指向业务库。下文用 `$PG_DSN` 指代这个专用库的 DSN，执行命令前先 `export PG_DSN=…`。注意只导出 `PG_DSN`，不要全局导出 `OCTOP_TEST_DATABASE_URL`。

- [x] 1. 确认前置 spec 已合入并记录基线（0.25 人日）
  - 改动：不改代码。把以下结果贴进 PR 描述，作为后续任务的对照。
    - `git rev-parse HEAD`。本 spec 没有前置 spec；记录 `w0-01` 是否已经合入（看 `tests/integration/test_postgresql_fork_migrations.py` 是否存在），因为它会增加 PG 用例数。
    - `postgresql` 标记用例数。基线为 `7/3419`；`w0-01` 合入后要加上它的用例。
    - vitest 文件数。基线为 169。
    - 前端基线结果。预期：`tsc -b` 为 0；lint 为 1（1 个 error，67 个 warning）；vitest 为 1（4 个文件失败，877 个用例中 1 个失败）。
    - 本地 PG 串行运行结果（基线预期 7 passed）。
  - 验证：`git rev-parse HEAD; ls tests/integration/test_postgresql_fork_migrations.py`（文件不存在说明 `w0-01` 尚未合入，只需记录下来，不阻塞本 spec）
  - 验证：`uv run pytest -m postgresql --co -q | tail -1`
  - 验证：`rg --files -g '*.test.ts' -g '*.test.tsx' dashboard/src | wc -l`
  - 验证：`cd dashboard && npm ci --no-audit --no-fund && npx tsc -b; echo "tsc=$?"; npm run lint; echo "lint=$?"; npm run test; echo "vitest=$?"`
  - 验证：`OCTOP_TEST_DATABASE_URL="$PG_DSN" uv run pytest -m postgresql -n 0 -rs -q`
  - _需求：2.1, 6.1_

- [x] 2. 前端基线清债（0.5 人日）
  - [x] 2.1 清掉唯一的 ESLint error
    - 改动：`dashboard/src/pages/Agent/Channels/components/constants.test.ts` 的导入块（≈L3-9）——删除未使用的 `DEFAULT_CHANNEL_DISPLAY_CONFIG`（≈L5）。不加 `eslint-disable`，也不改 `eslint.config.js`。
    - 验证：`cd dashboard && npm run lint; echo "lint=$?"`（期望 `lint=0`，warning 数仍为 67）
    - _需求：6.1, 6.4_
  - [x] 2.2 修复 3 个因 `DOMMatrix` 崩溃的套件
    - 先确认它们是红的：`cd dashboard && npx vitest run src/components/DocumentPreviewCore.docxSanitize.test.ts src/pages/Agent/Skills/skillMarkdown.test.ts src/pages/Agent/Skills/components/SkillDrawer.test.ts`（期望 `ReferenceError: DOMMatrix is not defined`）。
    - 改动：在下面三个文件里，把 `import { describe, expect, it } from "vitest"` 改为同时导入 `vi`，并在导入块之后加一行 `vi.mock("react-pdf", () => ({ pdfjs: { GlobalWorkerOptions: {} } }))`。沿用 `src/components/DocumentPreviewCore.pdfSkeleton.test.tsx` ≈L5-9 的写法；这些套件不渲染 PDF，导入期只触碰 `pdfjs.GlobalWorkerOptions`，所以 factory 只给这一项。
      - `dashboard/src/components/DocumentPreviewCore.docxSanitize.test.ts`
      - `dashboard/src/pages/Agent/Skills/skillMarkdown.test.ts`
      - `dashboard/src/pages/Agent/Skills/components/SkillDrawer.test.ts`
    - 验证：`cd dashboard && npx vitest run src/components/DocumentPreviewCore.docxSanitize.test.ts src/pages/Agent/Skills/skillMarkdown.test.ts src/pages/Agent/Skills/components/SkillDrawer.test.ts`（期望 3 个文件、12 个用例通过）
    - _需求：6.2, 6.4_
  - [x] 2.3 修正过期断言
    - 改动：`dashboard/src/api/modules/publishedExperts.test.ts` 中，第 3 次 `toHaveBeenNthCalledWith`（≈L41-47，路径 `/experts/published/expert%2F1/refresh`）的期望对象补上 `body: JSON.stringify({ name: "Updated", description: "New description", welcome_message: { zh: "欢迎", en: "Welcome" } })`，与 ≈L21-25 传入的参数一致。不改 `publishedExperts.ts`，因为它 ≈L71-75 的实现与后端 `refresh_published_expert` 可选 body 的契约一致。
    - 验证：`cd dashboard && npx vitest run src/api/modules/publishedExperts.test.ts`（期望 2 个用例通过）
    - _需求：6.3_
  - [x] 2.4 前端全量回归
    - 改动：无新增改动，只做确认。
    - 验证：`cd dashboard && npx tsc -b && npm run lint && npm run format:check && npm run test`（期望全部退出码为 0；vitest 为 169 个文件通过、0 失败）
    - 验证：`git diff 757fd12 -- dashboard | rg -n '^\+.*(\.skip\(|exclude|max-warnings|eslint-disable)'; echo "rg=$?"`（期望 `rg=1`，即没有放宽）
    - _需求：6.1, 6.4_

- [x] 3. PG "跳过即失败"插件（0.5 人日）
  - [x] 3.1 先写单测（此时应为红）
    - 改动：新增 `tests/unit/test_pg_strict_plugin.py`。用 `types.SimpleNamespace` 伪造 report（`skipped`、`keywords`、`nodeid`）和 session（`exitstatus`），并用 `monkeypatch.setattr(pg_strict, "_skipped", [])` 隔离模块状态。覆盖四种情形：`postgresql` 用例被跳过时退出码 0→1；非 `postgresql` 的跳过不改退出码；`postgresql` 用例通过时不改退出码；原本就是 1 的退出码保持为 1。
    - 验证：`uv run pytest tests/unit/test_pg_strict_plugin.py -q`（期望因 `ModuleNotFoundError: tests.support.pg_strict` 失败）
    - _需求：5.3, 5.4_
  - [x] 3.2 实现插件
    - 改动：新增 `tests/support/pg_strict.py`，包含 `pytest_runtest_logreport`、`pytest_sessionfinish`、`pytest_terminal_summary` 三个钩子。签名与语义见 design.md"组件与接口"。插件不在任何 conftest 里注册，只通过 `-p tests.support.pg_strict` 显式加载。
    - 验证：`uv run pytest tests/unit/test_pg_strict_plugin.py -q`（期望通过）
    - 验证：`env -u OCTOP_TEST_DATABASE_URL uv run python -m pytest -p tests.support.pg_strict -m postgresql -n 0 -q; echo "exit=$?"`（期望 `exit=1`，并列出全部被跳过的 nodeid）
    - 验证：`OCTOP_TEST_DATABASE_URL="$PG_DSN" uv run python -m pytest -p tests.support.pg_strict -m postgresql -n 0 -rs -q; echo "exit=$?"`（期望 `exit=0`，passed 数等于任务 1 记录的用例数）
    - 验证：`uv run ruff check tests/support/pg_strict.py tests/unit/test_pg_strict_plugin.py && uv run ruff format --check tests/support/pg_strict.py tests/unit/test_pg_strict_plugin.py`
    - _需求：2.3, 5.3, 5.4_

- [x] 4. Makefile 契约：`Makefile.intranet`（0.5 人日）
  - [x] 4.1 先写合同测试的 Makefile 部分（此时应为红）
    - 改动：新增 `tests/unit/test_ci_gates_contract.py`，先写 `test_makefile_intranet_defines_gate_targets`（用行首的 `^<target>:` 匹配 `install-frontend`、`test-frontend`、`check-frontend`、`test-postgresql`、`help-intranet`）和 `test_root_makefile_includes_intranet`。只用 `pathlib` 读文本，`encoding="utf-8"`。
    - 验证：`uv run pytest tests/unit/test_ci_gates_contract.py -q -k makefile`（期望因文件或 include 行不存在而失败）
    - _需求：5.1, 5.4_
  - [x] 4.2 前端目标
    - 改动：新增 `Makefile.intranet`，内容包括头注释、`install-frontend`（`npm ci --no-audit --no-fund`，`NPM_REGISTRY` 非空时追加 `--registry=…`）、`test-frontend`（`npm run test`）、`check-frontend: typecheck-frontend lint-frontend test-frontend`。在根 `Makefile` 末尾（`version` 目标之后，≈L342 后）追加一行 `include Makefile.intranet`，其余一行不动。
    - 验证：`make -n install-frontend NPM_REGISTRY=https://npm.example/ | rg -- '--registry=https://npm.example/'`（期望命中）
    - 验证：`make -n install-frontend | rg -- '--registry'; echo "rg=$?"`（期望 `rg=1`）
    - 验证：`make install-frontend && make check-frontend; echo "exit=$?"`（期望 `exit=0`；日志依次出现 `[typecheck-frontend]`、`[lint-frontend]`、`[test-frontend]`）
    - _需求：1.1, 1.2, 1.3, 7.1_
  - [x] 4.3 PostgreSQL 目标
    - 改动：在 `Makefile.intranet` 里新增 `test-postgresql`。先用 `@if [ -z "$$OCTOP_TEST_DATABASE_URL" ]` 守卫，缺失时输出 `OCTOP_TEST_DATABASE_URL is not set …` 并 `exit 2`；再执行 `$(PYTHON) -m pytest -p tests.support.pg_strict -m postgresql -n 0 -rs`。执行 pytest 的那一行不引用 DSN。
    - 验证：`env -u OCTOP_TEST_DATABASE_URL make test-postgresql; echo "exit=$?"`（期望非零，输出含 `OCTOP_TEST_DATABASE_URL is not set`，而且没有启动 pytest）
    - 验证：`OCTOP_TEST_DATABASE_URL="$PG_DSN" make test-postgresql; echo "exit=$?"`（期望 `exit=0`，passed 数等于任务 1 记录的用例数，没有 skip）
    - 验证：`OCTOP_TEST_DATABASE_URL='postgresql://octop:SECRETMARK@127.0.0.1:5432/x' make -n test-postgresql | rg SECRETMARK; echo "rg=$?"`（期望 `rg=1`，即 DSN 不出现在回显里）
    - 验证：`uv run python -m pytest -p tests.support.pg_strict -m postgresql -n 0 -q tests/unit/test_config.py; echo "exit=$?"`（期望 `exit=5`，即未选中用例时不会报绿）
    - 验证：`env -u OCTOP_TEST_DATABASE_URL uv run pytest -m postgresql -q | tail -1`（期望与基线相同，仍为 skip 且退出码 0，说明 `tests/support/postgresql.py` 的语义没变）
    - _需求：2.1, 2.2, 2.4, 2.5, 2.6, 7.2_
  - [x] 4.4 帮助信息与对上游文件的最小改动
    - 改动：在 `Makefile.intranet` 里新增 `help-intranet`，列出全部目标、`NPM_REGISTRY` 与 `OCTOP_TEST_DATABASE_URL` 的用法，以及"专用库、不要为 `make test` 导出 DSN"的警示。
    - 验证：`make help-intranet`（期望列出五个目标，并出现 `dedicated` 与 `do not export` 字样）
    - 验证：`git diff -U0 757fd12 -- Makefile | rg '^[+-][^+-]'`（期望只有一行 `+include Makefile.intranet`）
    - 验证：`git diff --quiet 757fd12 -- .githooks/pre-commit && echo pre-commit-unchanged`
    - 验证：`uv run pytest tests/unit/test_ci_gates_contract.py -q -k makefile`（期望通过）
    - _需求：1.4, 1.5, 5.1_

- [ ] 5. CI 调用方：`ci.yml` 两个新 job（0.5 人日）
  - [x] 5.1 先补齐合同测试的 CI 部分（此时应为红）
    - 改动：在 `tests/unit/test_ci_gates_contract.py` 中新增以下测试：
      - `test_ci_fork_job_runs_make_targets`（按 job 参数化）：`frontend` job 的 run 步骤包含 `make install-frontend` 与 `make check-frontend`，`postgresql` job 包含 `make test-postgresql`，两者都带 `sync-develop-after-` 条件。
      - `test_ci_postgresql_service_and_dsn_scoped_to_its_step`：`services.postgres.image` 以 `postgres:` 开头；DSN 只出现在执行 `make test-postgresql` 那一步的 `env` 里，不在 job 级 `env`；其他 job 序列化后不含 `OCTOP_TEST_DATABASE_URL`。
      - 用 `yaml.safe_load` 读取 `.github/workflows/ci.yml`。
    - 验证：`uv run pytest tests/unit/test_ci_gates_contract.py -q`（期望 CI 相关用例失败）
    - _需求：5.1, 5.2, 5.4_
  - [x] 5.2 插入 `frontend` 与 `postgresql` job
    - 改动：`.github/workflows/ci.yml`——在 `test-windows`（≈L44-66）与 `live-tests`（≈L68）之间插入两个 job，YAML 见 design.md"组件与接口"。
      - `frontend`：使用 `actions/setup-node@v4`、Node 20、npm 缓存键 `dashboard/package-lock.json`，job 级 `env.NPM_REGISTRY: ${{ vars.NPM_REGISTRY }}`，然后执行 `make install-frontend`、`make check-frontend`。
      - `postgresql`：`services.postgres` 使用 `postgres:16` 并配置 `pg_isready` 健康检查；执行 `make install`；打印 `pg_dump --version && pg_restore --version`；最后在该步 `env` 中设置 `OCTOP_TEST_DATABASE_URL` 并执行 `make test-postgresql`。
      - 两个 job 都带既有的 `sync-develop-after-` 条件。`quality`、`test-windows`、`live-tests` 一行不改。
    - 验证：`uv run pytest tests/unit/test_ci_gates_contract.py -q`（期望全部通过）
    - 验证：`git diff -U0 757fd12 -- .github/workflows/ci.yml | rg '^-[^-]'; echo "rg=$?"`（期望 `rg=1`，即没有删除行）
    - 验证：`uv run python -c "import yaml; jobs = yaml.safe_load(open('.github/workflows/ci.yml', encoding='utf-8'))['jobs']; print(sorted(jobs))"`（期望输出 `['frontend', 'live-tests', 'postgresql', 'quality', 'test-windows']`）
    - _需求：3.1, 3.3, 3.4, 4.1, 4.3, 4.4, 4.5_
  - [ ] 5.3 在 CI 上实跑，并做负向验证
    - 改动：推送分支并开 PR（base 为 fork 主干）。另外开两个临时分支，只用于验证，验证完删除、不合入：
      - (a) 在任一 vitest 用例里加一个必然失败的断言；
      - (b) 删掉 PG step 的 `env`。
    - 验证：`gh pr checks --watch`（期望 `frontend`、`postgresql`、`Python 3.12`、`Windows / Python 3.12` 全部通过）
    - 验证：`gh run view "$(gh run list --workflow ci.yml --branch "$(git branch --show-current)" --limit 1 --json databaseId -q '.[0].databaseId')" --log | rg 'PostgreSQL integration.*(passed|skipped|pg-strict)'`（期望 passed 数等于任务 1 的用例数，并且没有 `skipped` 和 `[pg-strict]`）
    - 验证：在临时分支 (a) 上执行 `gh pr checks`，期望 `frontend` 失败；在 (b) 上执行，期望 `postgresql` 失败，日志含 `OCTOP_TEST_DATABASE_URL is not set`。
    - 验证：记录 runner 上 `pg_dump --version` 的主版本。如果它与 `postgres:16` 不一致，按 design.md"风险与回滚"处理。
    - _需求：3.2, 4.2, 7.1, 7.2_
    - 状态：远端 CI 无法在本地执行，待开 PR 后完成；本地以 YAML 合同测试与"改坏 ci.yml / Makefile 即变红"的变异验证代替。

- [x] 6. 收尾（0.25 人日）
  - 改动：
    - `CHANGELOG-intranet.md`：追加 `w0-02-ci-gates` 条目，写明新增的目标（`install-frontend` / `test-frontend` / `check-frontend` / `test-postgresql` / `help-intranet`）、两个 CI job、"PG 用例串行、跳过即失败、只能用专用库"的约定，以及本地复现命令。该文件由 `w0-04` 统一格式；如果本 spec 先合入，就只新建文件并写入这一条。
    - `docs/api-intranet.md`：本 spec 没有 API 变更，不更新。
    - 在 PR 描述里提醒仓库管理员：把 `frontend` 与 `postgresql` 加入分支保护的必需检查。这是仓库设置，不在代码里。
  - 验证：`make install-frontend && make all`（`format-all` 需要 `dashboard/node_modules`；期望全绿，并且 `git status --short` 里没有被格式化工具改出的额外文件）
  - 验证：`cd dashboard && npx tsc -b && npm run lint && npm run test`
  - 验证：`OCTOP_TEST_DATABASE_URL="$PG_DSN" make test-postgresql`
  - 验证：`uv run pytest tests/unit/test_ci_gates_contract.py tests/unit/test_pg_strict_plugin.py -q`
  - 验证：`rg -n 'w0-02' CHANGELOG-intranet.md`
  - 状态：`CHANGELOG-intranet.md` 由 `w0-04` 创建并补录本条目，本 spec 的提交不建该文件；其余验证（`make all` 除外，按分项命令执行）已在本地通过。
  - _需求：1.4, 6.1, 7.3_
