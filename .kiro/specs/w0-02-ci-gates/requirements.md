# 需求文档：CI 前端与 PostgreSQL 门禁

> spec：`w0-02-ci-gates` ｜ 波次：Wave 0 ｜ 基线：`757fd12` ｜ 预估：2.5 人日
> 前置：无 ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 引言

**结论：** 本 spec 用两类 Makefile 目标给前端和 PostgreSQL 验收加上机器兜底。`make install-frontend` / `make check-frontend` 负责前端（可配置 registry 的 `npm ci`、`tsc -b`、ESLint、Prettier、vitest）；`make test-postgresql` 串行执行全部 `postgresql` 标记用例，而且任何跳过都算失败。`.github/workflows/ci.yml` 只作为调用方，新增 `frontend` 和 `postgresql` 两个 job，现有的 `quality`、`test-windows`、`live-tests` 三个 job 一行不改。基线上前端有 1 个 ESLint error 和 4 个 vitest 失败文件，本 spec 先把这些清掉，再接入门禁。

**背景（基线 `757fd12` 实测）：**

- `.github/workflows/ci.yml` 的 `quality` 与 `test-windows` 两个 job 都只执行 `make install / lint / typecheck / test`。`live-tests` 只执行 `make test-live`。全文件没有 npm 步骤，也没有 `services:`。`rg -n 'vitest|npm test|npm run test|postgres' Makefile .githooks/pre-commit .github/workflows/ci.yml` 零命中。
- `Makefile` 的 `all`（≈L202）是 `format-all lint typecheck test`，`check-all`（≈L291）是 `lint-all typecheck-all test`，两者都不跑 vitest。前端唯一的把关是本地 `.githooks/pre-commit` 的 `npm run build`（≈L42-46），而它可以用 `--no-verify` 或 `SKIP_PRECOMMIT=1` 绕过。
- `dashboard/package.json` 已经有 `"lint": "eslint ."`（≈L14）和 `"test": "vitest run"`（≈L15），不需要新增脚本。`dashboard/src` 下共有 169 个 `*.test.ts(x)` 文件。
- 在 Node 22.22.2 下对 `dashboard/` 的副本实测：`npm ci` 成功，`npx tsc -b` 退出码为 0，`npm run format:check` 退出码为 0。**`npm run lint` 退出码为 1**：1 个 error（`src/pages/Agent/Channels/components/constants.test.ts` ≈L5 有未使用的导入 `DEFAULT_CHANNEL_DISPLAY_CONFIG`），另有 67 个 warning。**`npm test` 退出码为 1**：4 个文件失败，另外 165 个通过；共 877 个用例，其中 1 个失败。3 个套件在导入 `react-pdf` 时抛出 `ReferenceError: DOMMatrix is not defined`，1 个断言已经与实现不一致。在副本上按本 spec 的清债方案修复后，169 个文件、889 个用例全部通过，lint 退出码也变为 0。
- `tests/support/postgresql.py` 的 `requires_postgresql`（≈L14-17）在缺少 `OCTOP_TEST_DATABASE_URL` 时 skip，pytest 退出码仍为 0。基线上 `-m postgresql` 选中 7 个用例：`tests/integration/test_postgresql_control_plane.py` 6 个，`tests/integration/test_postgresql_checkpoint_history.py` 1 个。源分析中"`tests/unit/agents/test_memory_backend.py` 也带 postgresql 标记"的说法经核实不成立，那个文件只是在函数名里含有 `postgresql`。
- 用本地 PostgreSQL 16.13（不含 pgvector）实测：`uv run pytest -m postgresql -n 0` 结果为 7 passed。**`-n 4` 并行时有 4 个用例失败**（`UniqueViolation` / `UndefinedTable`），原因是多个用例都在同一个库上执行 `DROP SCHEMA public CASCADE`（`_reset_public_schema` ≈L29-34）。所以 PG 用例必须串行执行，也不能把 DSN 暴露给 `make test`（`-n auto`）。

**为什么做：** steering §1.3 规定，凡把验收写成 vitest 用例或 PG 集成用例的 spec，都以本 spec 已合入为前提。否则这些验收"不写代码也能通过"：vitest 从来不执行，PG 用例会静默 skip 然后报绿。

**范围内：**

- 新增 fork 专属的 `Makefile.intranet`，定义 `install-frontend`、`test-frontend`、`check-frontend`、`test-postgresql`、`help-intranet` 五个目标。根 `Makefile` 只在末尾加一行 `include`。
- 新增 pytest 插件 `tests/support/pg_strict.py`：在 PG 门禁里，把任何 `postgresql` 标记用例的跳过变成失败。
- 在 `.github/workflows/ci.yml` 新增 `frontend` job 和带 `postgres:16` service 的 `postgresql` job。
- 新增门禁自身的回归测试（CI 合同测试、插件单测），防止上游同步时 fork 的 job 被冲突解决悄悄丢掉。
- 清理前端基线上的债：1 个 ESLint error、3 个 DOMMatrix 套件、1 个过期断言。

**范围外（归属）：**

- 用行内流水线替代 GitHub Actions，以及许可证、SBOM、SCA、SAST、制品签名：归 `w2-02-supply-chain-compliance`。本 spec 交付的 Makefile 目标就是它要调用的契约。
- 行内 npm 私服、PyPI 私服、`postgres` 镜像入 Harbor、路径前缀型 npm 镜像与 `dashboard/.npmrc` 的 `replace-registry-host` 是否兼容、`make build-frontend` 离线化、`vite build` 进门禁：归 `w2-01-offline-build`。
- 在人大金仓 / openGauss 上的真实回归、方言家族化及其专项测试：归 `w2-03-database-adaptation`。CI 只验证社区版 PostgreSQL 16。
- 单活租约、verify-only 迁移、DDL 快照等新增 PG 用例：分别归 `p2-08-ha-lease-probes`、`w2-03`、`w4-02-ops-minimum`。本 spec 只保证这些用例带上 `postgresql` 标记后会被执行。
- dashboard 两份 locale 的对等测试及其存量差异：不在本 spec 范围内（steering §1.2）。
- 67 个 ESLint warning：它们不影响退出码，本 spec 不清理，也不加 `--max-warnings`。
- `CHANGELOG-intranet.md` 的建立和上游同步手册：归 `w0-04-fork-isolation-points`。本 spec 只追加自己的条目。

## 需求

### 需求 1：前端检查的 Makefile 契约

**用户故事：** 作为 fork 维护者，我希望用两个 Makefile 目标完成前端依赖安装和全部前端检查，以便任何 CI（GitHub Actions 或行内流水线）都只需调用 make，不必各自拼 npm 命令。

#### 验收标准

1. 当执行 `make install-frontend NPM_REGISTRY=<url>` 时，Makefile 应当在 `dashboard/` 下执行 `npm ci --no-audit --no-fund --registry=<url>`。可以用 `make -n install-frontend NPM_REGISTRY=https://npm.example/` 的输出验证。
2. 如果 `NPM_REGISTRY` 未设置或为空字符串，那么 `make install-frontend` 应当执行不带 `--registry` 的 `npm ci`，沿用 `dashboard/.npmrc` 的 registry。可以用 `make -n install-frontend` 的输出验证。
3. 当执行 `make check-frontend` 时，Makefile 应当依次执行 `typecheck-frontend`（`npx tsc -b`）、`lint-frontend`（`npm run lint` 与 `npm run format:check`）和 `test-frontend`（`npm run test`）。任何一步退出码不为 0，目标就以非零退出码结束。
4. 根 `Makefile` 相对基线应当始终只多一行 `include Makefile.intranet`。`all`、`check-all`、`test`、`build-frontend` 的定义和 `.githooks/pre-commit` 保持不变。
5. 当执行 `make help-intranet` 时，应当列出本 spec 新增的全部目标、`NPM_REGISTRY` 与 `OCTOP_TEST_DATABASE_URL` 的用法，以及"PG 用例必须使用专用库、不要在 `make test` 时导出 DSN"的警示。

### 需求 2：PostgreSQL 集成测试的 Makefile 契约

**用户故事：** 作为依赖 PG 验收的 spec 的实施者，我希望有一个"跳过即失败"的 PG 测试目标，以便"PG 用例通过"真的代表用例被执行过，而不是 skip 以后报绿。

#### 验收标准

1. 当已设置 `OCTOP_TEST_DATABASE_URL` 并执行 `make test-postgresql` 时，目标应当以 `-m postgresql -n 0` 串行执行全部 `postgresql` 标记用例，退出码为 0，而且摘要里的 passed 数等于选中的用例数（基线为 7；`w0-01` 合入后还要加上它新增的 PG 用例）。
2. 如果没有设置 `OCTOP_TEST_DATABASE_URL`，那么 `make test-postgresql` 应当在启动 pytest 之前以非零退出码结束，并输出含有 `OCTOP_TEST_DATABASE_URL is not set` 的提示，要求使用专用库。
3. 如果执行期间有任何 `postgresql` 标记用例被跳过（例如 `pg_dump` / `pg_restore` 不在 PATH 上，导致 `test_pg_backup_roundtrip` 执行 `pytest.skip`），那么 pytest 会话应当以退出码 1 结束，并在终端摘要里列出每个被跳过用例的 nodeid。
4. 如果 `-m postgresql` 没有选中任何用例，那么 `make test-postgresql` 应当以非零退出码结束（pytest 退出码 5）。
5. `make test-postgresql` 应当始终不在 make 的命令回显里出现 DSN 字面值：检查语句用 `@` 静默，调用 pytest 的那一行不引用这个变量。
6. 在执行 `make test`（`-n auto`）期间，只要没有设置 `OCTOP_TEST_DATABASE_URL`，`postgresql` 用例的行为就应当与基线一致，仍然 skip。本 spec 不修改 `tests/support/postgresql.py`。

### 需求 3：CI frontend job

**用户故事：** 作为评审者，我希望每个 PR 都自动执行前端类型检查、lint 和 vitest，以便前端改动不再只靠可以绕过的本地 pre-commit。

#### 验收标准

1. 当 PR 触发 CI 时，`ci.yml` 应当执行名为 `frontend` 的 job。它的步骤依次是 `actions/checkout`、`actions/setup-node`（Node 20，npm 缓存键为 `dashboard/package-lock.json`）、`make install-frontend`、`make check-frontend`。
2. 如果 `make check-frontend` 的任一步失败，那么 `frontend` job 应当失败，PR 检查显示红色。
3. `frontend` job 应当始终带有与既有 job 相同的 `if: ${{ !startsWith(github.head_ref, 'chore/sync-develop-after-') }}` 条件。
4. 当仓库变量 `vars.NPM_REGISTRY` 已设置时，`frontend` job 应当通过 job 级环境变量 `NPM_REGISTRY` 把它交给 `make install-frontend`；未设置时行为与需求 1.2 相同。

### 需求 4：CI postgresql job

**用户故事：** 作为评审者，我希望每个 PR 都在真实的 PostgreSQL 上执行 PG 门控用例，以便控制面的 PG 路径不再在 CI 上零覆盖。

#### 验收标准

1. 当 PR 触发 CI 时，`ci.yml` 应当执行名为 `postgresql` 的 job。它的 `services.postgres` 使用 `postgres:16` 镜像，并配置 `pg_isready` 健康检查。步骤依次是 checkout、`astral-sh/setup-uv`（Python 3.12）、`make install`、打印 `pg_dump --version` 与 `pg_restore --version`、`make test-postgresql`。
2. 如果任何 `postgresql` 用例失败或被跳过，那么 `postgresql` job 应当失败。
3. `OCTOP_TEST_DATABASE_URL` 应当始终只出现在 `postgresql` job 执行 `make test-postgresql` 那一步的 `env` 里，不出现在 job 级 `env`，也不出现在 `quality`、`test-windows`、`live-tests` 的任何位置。
4. `quality`、`test-windows`、`live-tests` 三个既有 job 应当始终保持不变：`git diff -U0 757fd12 -- .github/workflows/ci.yml` 里没有任何删除行。
5. `postgresql` job 应当始终带有与既有 job 相同的 `sync-develop-after-` 跳过条件。

### 需求 5：门禁自身的回归保护

**用户故事：** 作为负责上游同步的人，我希望 fork 门禁一旦在 `ci.yml` 或 Makefile 上被冲突解决冲掉，`make test` 就会变红，以便"门禁悄悄消失"不会再变成新的静默失败。

#### 验收标准

1. 当执行 `uv run pytest tests/unit/test_ci_gates_contract.py -q` 时，测试应当断言以下事实并通过：`ci.yml` 含有 `frontend` 和 `postgresql` 两个 job；前者执行 `make install-frontend` 与 `make check-frontend`，后者执行 `make test-postgresql` 并声明 `postgres` service；`Makefile.intranet` 定义了需求 1、2 的全部目标；根 `Makefile` 含有 `include Makefile.intranet`。
2. 如果上游同步后 `ci.yml` 丢失了 `frontend` 或 `postgresql` job，或者 `OCTOP_TEST_DATABASE_URL` 出现在 `postgresql` 以外的 job 里，那么上述合同测试应当失败，从而让 `make test` 以及 CI 的 `quality` 与 `test-windows` 变红。
3. 当执行 `uv run pytest tests/unit/test_pg_strict_plugin.py -q` 时，应当验证以下行为：插件遇到被跳过的 `postgresql` 用例时把会话退出码从 0 改为 1；遇到非 `postgresql` 的跳过、已通过的用例、原本就非零的退出码时不做改动。
4. 合同测试和插件单测应当始终与平台无关，在 Linux 和 Windows 的 `make test` 下都通过。它们只读仓库文本文件、用 `pathlib` 拼路径，不调用 `make`、`npm` 或数据库（AGENTS.md §7）。

### 需求 6：前端基线清债

**用户故事：** 作为 fork 维护者，我希望门禁接入的那一刻前端检查在基线上就是绿的，以便门禁变红只可能是新改动造成的，而不是历史遗留。

#### 验收标准

1. 当在清债后的代码上执行 `make install-frontend && make check-frontend` 时，退出码应当为 0，其中 vitest 摘要为 169 个文件全部通过、0 失败（文件数以任务 1 记录的基线为准）。
2. 如果某个 vitest 套件因为 jsdom 缺少 `DOMMatrix`、在（直接或间接）导入 `react-pdf` 时崩溃，那么清债方式应当是沿用仓库已有的写法，在该测试文件里加 `vi.mock("react-pdf", …)`（参照 `src/components/DocumentPreviewCore.pdfSkeleton.test.tsx` ≈L5-9），而不是跳过或删除用例。
3. 如果测试断言与当前实现和后端契约不一致（`publishedExperts.test.ts` 对 `refresh` 的期望没有带 body，而 `publishedExperts.ts` ≈L71-75 与后端 `experts.py` 的 `refresh_published_expert` 都接受可选 body），那么应当修正测试断言，不改生产代码。
4. 清债应当始终不引入 `it.skip`、`describe.skip`、`test.exclude`、`--max-warnings`、`eslint-disable` 或 ESLint 规则的放宽。可以用 `git diff 757fd12 -- dashboard Makefile.intranet | rg -n '^\+.*(\.skip\(|exclude|max-warnings|eslint-disable)'` 无输出来验证。

### 需求 7：本地可复现与交接记录

**用户故事：** 作为后续 spec 的实施者，我希望本地复现门禁的命令明确而且与 CI 一致，以便在 tasks.md 里直接引用。

#### 验收标准

1. 当开发者在本地依次执行 `make install-frontend`、`make check-frontend` 时，得到的结果应当与 CI `frontend` job 一致（两者调用的是同一组目标）。
2. 当开发者设置 `OCTOP_TEST_DATABASE_URL` 指向专用库并执行 `make test-postgresql` 时，得到的结果应当与 CI `postgresql` job 一致。
3. 当本 spec 合入时，`CHANGELOG-intranet.md` 应当有一条记录，写明新增的目标、两个 CI job，以及"PG 用例串行、跳过即失败"的约定。
