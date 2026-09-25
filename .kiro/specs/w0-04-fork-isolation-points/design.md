# 设计文档：fork 隔离点与上游同步机制

> spec：`w0-04-fork-isolation-points` ｜ 波次：Wave 0 ｜ 基线：`757fd12` ｜ 预估：5 人日
> 前置：`w0-02-ci-gates`、`w0-01-fork-migration-namespace` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 概述

本 spec 建立四个代码隔离点、一个构建目标、三份 fork 专属文档，并做一次 AGENTS.md 勘误。

| # | 隔离点 | 上游文件里留下的钩子 | fork 自有的扩展文件 |
|---|---|---|---|
| 1 | 后端 i18n overlay | `loader.py::_load_all` 改 1 行、加 1 行 import | `src/octop/i18n/overlay.py`、`src/octop/i18n/intranet/{en,zh}.json` |
| 2 | 前端 i18n overlay | `dashboard/src/i18n.ts` 加 1 行 import、2 行调用 | `dashboard/src/i18nIntranet.ts`、`dashboard/src/locales/intranet/{en,zh}.json` |
| 3 | 路由下线 | `app.py::_mount_routers` 改 1 行、加 1 行 import | `src/octop/api/intranet_mounts.py`（`_FORK_DISABLED_MOUNTS`） |
| 4 | 连接器目录 | `catalog.py` 改名 1 行、末尾加约 4 行 | `src/octop/infra/connectors/catalog_intranet.py`（`_FORK_REMOVED`、`_fork_entries()`） |
| 5 | 锁文件 | 无（`Makefile.intranet` 是 `w0-02` 建的 fork 文件） | `Makefile.intranet` 的 `relock` 目标 |
| 6 | 文档 | `docs/api.md` 顶部加 1 行指针 | `CHANGELOG-intranet.md`、`docs/api-intranet.md`、`docs/intranet/upstream-sync.md` |

同批要做的配套工作：

- 三条 i18n 门禁改读合并后的 bundle；两对 overlay 各自做 en == zh 对等测试与形状测试。
- 用一个契约测试守住行为测试覆盖不到的非 Python 钩子（`i18n.ts`、`Makefile.intranet`、`docs/api.md`）。
- 勘误 AGENTS.md 中不存在的路径。

合入时所有 overlay 为 `{}`，`_FORK_DISABLED_MOUNTS` 与 `_FORK_REMOVED` 为空集，`_fork_entries()` 返回空元组，因此运行时行为与基线逐字节一致。本 spec 没有数据迁移、没有新配置键、没有新 `ErrorCode`。

## 现状

以下事实均在基线 `757fd12` 上核实。churn 统一用 `git log --full-history --no-merges --oneline 757fd12 -- <path> | wc -l` 测量（与全局约束第 5 节同一口径）。由于 clone 是 shallow，这些数字只是下限。

### 后端 i18n

- `src/octop/i18n/loader.py`（churn 7）：
  - `_load_all`（≈L24-30）带 `@lru_cache(maxsize=1)`，对 `("en", "zh")` 各执行一次 `resources.files("octop.i18n").joinpath(f"{loc}.json").read_text(encoding="utf-8")` 与 `json.loads`，没有任何合并或覆盖。
  - `lookup`（≈L33-41）在当前 locale 找不到键时回退到 `en`。
  - `all_keys_for_locale`（≈L63-64）返回 `flatten_keys(_load_all()[locale])`。
- 所有服务端文案都经过 `_load_all`：
  - `domains/tools.py::all_tool_labels`（≈L98-106）与 `domains/skills.py::all_skill_labels`（≈L20-28）直接调用 `_load_all()`；
  - 其余 domain 经 `tr` / `lookup` 间接调用；
  - `GET /api/i18n/tools` 与 `GET /api/i18n/skills`（`src/octop/api/routers/i18n.py` ≈L24-48）返回上述两个函数的结果。
  - 因此只要改 `_load_all` 一处，overlay 就会自动生效于 `tr()`、错误信封、HITL 工具目录与这两个 API。
- 打包：`pyproject.toml` 的 `[tool.hatch.build] include`（≈L102-115）含 `"src/octop/**/*.json"`，所以新增的 `src/octop/i18n/intranet/*.json` 无需改 `pyproject.toml` 即会进入 wheel。
- 实测 `resources.files("octop.i18n").joinpath("intranet").joinpath("en.json")` 返回 `PosixPath`，当前 `is_file()` 为 `False`（目录尚不存在）。

### i18n 门禁

基线 `uv run pytest tests/unit/i18n -q` 结果为 69 passed。

| 用例 | 读取方式 | 合并 overlay 后是否自动覆盖 |
|---|---|---|
| `test_catalog.py::test_en_and_zh_share_same_keys`（≈L11-15） | `all_keys_for_locale` → `_load_all` | 是，无需改代码 |
| `test_errors.py::test_dashboard_api_errors_match_backend`（≈L52-58） | 直接 `json.loads` 读 `dashboard/src/locales/en.json` 与 `src/octop/i18n/en.json` | 否 |
| `test_errors.py::test_dashboard_api_errors_use_i18next_placeholders`（≈L65-76） | 直接读 dashboard `en.json`、`zh.json` | 否 |
| `test_tools.py::test_dashboard_tools_match_backend`（≈L77-81） | 直接读两份 `en.json` | 否 |
| `test_skills.py::test_dashboard_skill_labels_match_backend`（≈L37-42） | 直接读两份 `en.json` | 否 |

另外，`test_admin_users_expert_naming.py` 也直接读 dashboard 的两份 locale，但它只断言几个具体键，不属于四条门禁，本 spec 不改它。

### 前端 i18n

`dashboard/src/i18n.ts`（churn 7）的结构如下：

- `loadLocaleBundle`（≈L13-18）动态 `import("./locales/<locale>.json")`。
- `ensureLocaleBundle`（≈L20-25）只在 `!i18n.hasResourceBundle(locale, "translation")` 时加载，并执行 `i18n.addResourceBundle(locale, "translation", bundle, true, true)`（≈L23）。
- `hydrateToolLabels`（≈L39-53）与 `hydrateSkillLabels`（≈L55-69）用同样的 `(…, true, true)` 叠加服务端标签，这是既有的分层叠加模式。
- `initI18n`（≈L83-124）把初始语言的 bundle 放进 `init({ resources: { [initial]: { translation: primaryBundle } } })`（≈L90-101），**不经过** `ensureLocaleBundle`。所以 overlay 必须在两处都叠加：只加在 `ensureLocaleBundle` 里，初始语言不会生效。
- `src/main.tsx` ≈L61-66 在 `initI18n()` resolve 之后才 `createRoot(...).render(<App />)`，所以在 `initI18n` 内部叠加 overlay 不会出现首屏闪烁。
- 其他语言切换路径都经过 `ensureLocaleBundle`：`utils/locale.ts` 的 `applyUserLocale` / `applyGuestLocale`（≈L27、L39），`pages/Setup/index.tsx` ≈L187，`pages/Invite/index.tsx` ≈L85，以及 `initI18n` 内的 `languageChanged` 回调（≈L117）和空闲预取（≈L106）。
- 顺序陷阱：如果先对某语言执行 overlay 的 `addResourceBundle`，再调用 `ensureLocaleBundle`，`hasResourceBundle` 会返回 true，上游 bundle 就永远不会被加载。所以 overlay 只能在上游 bundle 加载之后叠加。
- JSON 模块解析：`tsconfig.app.json` 用 `moduleResolution: "bundler"`，既有的 `import("./locales/zh.json")` 能通过 `tsc -b`，说明当前配置可以解析 JSON 模块。
- vitest：`src/test/setup.ts` 只 mock 了 `react-i18next`，没有 mock `i18next`。`vitest.config.ts` 的 `include` 为 `src/**/*.test.ts(x)`。
- Prettier：`npm run format:check` 覆盖整个 `dashboard/`，没有 `.prettierignore`，所以新增的 JSON 必须符合 Prettier 格式。

### 路由挂载

`src/octop/api/app.py`（churn 20）：

- `_RouterMount`（≈L25-30）是 frozen dataclass，字段为 `router`、`prefix`、`tags`。
- `_mount_routers`（≈L72-74）只有一个 `for spec in mounts: app.include_router(...)` 循环。
- `build_app`（≈L101）在 ≈L202 调用 `_mount_routers(app, [...])` 挂载主列表，并在 ≈L270-276 的 `if enable_mobile:` 块里再调用一次。全文共 57 处 `_RouterMount(` 构造。
- 多个 router 来自同一模块的不同属性，例如 `usage.router` / `usage.admin_router`、`invites.public_router` / `invites.admin_router`、`storage_backends` 的 `admin_router` / `user_router`、`voice.router` / `voice.admin_router`。所以按模块名、前缀或 tag 都无法唯一标识一次挂载，只有 router 对象本身是唯一的。
- 实测 `octop.api.routers.search.router.routes` 为 `['/search/{provider_id}/test']`，`octop.api.routers.usage.admin_router` 是有 2 条路由的 `APIRouter`。

### 连接器目录

`src/octop/infra/connectors/catalog.py`（churn 12，共 582 行）：

- `AuthKind`（≈L8-17）、`ConnectorCategory`（≈L21-29）、`ConnectorCatalogEntry`（≈L44 起，frozen dataclass）。
- `_CATALOG`（≈L96-531）是含 23 条 `ConnectorCatalogEntry` 的元组。
- `_CATALOG` 只在本文件内被读取：`mcp_oauth_remote_kinds`（≈L85-86）、`list_catalog`（≈L534-535）、`get_catalog_entry`（≈L538-542）。外部消费者（`api/routers/connectors.py` 的 `GET /api/connectors/catalog` ≈L480-491，以及 `builder.py`、`probe.py`、`service.py`、`oauth/registry.py`、`oauth/mcp.py`）都只调用这三个函数。
- `src/octop/infra/connectors/__init__.py` 只有一行 docstring，不会预先导入 `catalog`。

### 锁文件与 Makefile

- 根 `Makefile`（churn 14）：`.DEFAULT_GOAL := help`（≈L15），`UV := $(shell command -v uv 2>/dev/null)`（≈L26），`build-frontend` 固定使用 `npm ci`（≈L97-102）。`rg -n "uv lock|package-lock|relock" Makefile` 无命中，也就是说没有任何重生成锁文件的目标。
- `Makefile.intranet` 与根 `Makefile` 末尾的 `include Makefile.intranet` 在基线上尚不存在，由 `w0-02` 交付（见其 design.md "组件与接口"）；按实施顺序假设它已合入，届时该文件已定义 `NPM_REGISTRY ?=` 与 `help-intranet`。任务 1 会核实。
- `uv.lock`（churn 59）里有 241 条 `source = { registry = "https://pypi.org/simple" }` 和 1 条 editable。`uv lock --check --offline` 在基线上通过（Resolved 242 packages）。
- `dashboard/package-lock.json`（churn 14）里 1125 条 `resolved` 全部指向 `https://registry.npmjs.org`。`dashboard/.npmrc` 固定 `registry=https://registry.npmjs.org` 与 `replace-registry-host=always`，这是上游热修 ae43484（2026-09-19，即基线 757fd12 合入的 #792）加入的。
- 在草稿目录的副本上实测：默认 registry 下，`uv lock`（uv 0.8.17）与 `npm install --package-lock-only --ignore-scripts --no-audit --no-fund`（npm 10.9.7）都不改变锁文件，逐字节相同。`uv lock --help` 确认 `--default-index` 是现行参数（`--index-url` 已标为 deprecated）。

### 文档与仓库状态

- `CHANGELOG.md`（churn 106）采用 Keep a Changelog 格式，`## [Unreleased]` 在 ≈L7，`## [1.0.1] - 2026-09-18` 在 ≈L9。仓库里没有 `CHANGELOG-intranet.md`、`docs/api-intranet.md`，也没有 `docs/intranet/` 目录。
- `docs/api.md`（churn 24）L1 为 `# API Reference`，L2 为空行，L3 起是正文。
- git 状态：
  - `git rev-parse --is-shallow-repository` 输出 `true`，`.git/shallow` 有 7 个边界提交；
  - `git tag` 为空，远端只有 `origin`（fork 仓库）；
  - 上游仓库是 `https://github.com/TencentCloud/Octop`（README ≈L17-22 的徽章链接）；
  - 上游 main 的 first-parent 合并提交主要是 `release/*` 与 `hotfix/*` 的 PR 合并，例如 `757fd12 Merge pull request #792 from TencentCloud/hotfix/npm-lockfile-registry`、`4888268 … release/1.0.`；也有少量直接合入 main 的其他 PR（如 `9d9a501 … docs/trendshift-badge`）。`git log --merges --oneline --grep 'hotfix/' 757fd12` 命中 4 个 hotfix 合并。
- 本地 churn（`--full-history --no-merges`）：`dashboard/src/locales/zh.json` 108、`en.json` 106、`CHANGELOG.md` 106、`uv.lock` 59、`src/octop/i18n/zh.json` 43、`docs/api.md` 24、`app.py` 20、`AGENTS.md` 16、`Makefile` 14、`catalog.py` 12、`loader.py` 7、`i18n.ts` 7。不加 `--no-merges` 时数字更高（例如 `zh.json` 为 128），两种口径不能混用。

### AGENTS.md

逐条核实了 §4、§5、§7、§8、§9 中的反引号路径。以下路径不存在（行号均为基线）：

| 行 | 节 | 文中写法 | 实际 |
|---|---|---|---|
| ≈L115 | §5 `infra/` 子包表 | IM ingress (`processor.py`)；importers 中的 `api/routers/chat.py` | `infra/gateway/process/processor.py`；`api/routers/chat/`（包） |
| ≈L135 | §5 `api/` 表 | `api/deps.py`, `api/jwt_tokens.py` | 只有 `api/deps.py`（`sign_token` ≈L28、`decode_token` ≈L47、`get_server` ≈L100、`current_user` ≈L186）与 `api/middleware/jwt_auth.py` |
| ≈L138 | §5 `api/` 表 | `api/errors.py` 映射 `OctopError` | 不存在；映射在 `api/app.py::_install_exception_handlers`（≈L77），状态码表在 `infra/errors.py::_DEFAULT_STATUS`（≈L115） |
| ≈L147 | §5 `cli/` 表 | `cli/*_cmd.py` | `cli/commands/*.py`，由 `cli/registry.py` 的 `COMMANDS` 懒加载（`cli/main.py` ≈L11 导入） |
| ≈L154 | §5 `cli/` 表 | `cli/run_cmd.py` | `cli/commands/run.py`（≈L20-22 调 `launch.run_foreground_blocking`） |
| ≈L155 | §5 `cli/` 表 | `cli/init_cmd.py`, `cli/backup_cmd.py` | `cli/commands/init.py`, `cli/commands/backup.py` |
| ≈L344 | §8 | `cli/*_cmd.py` | `cli/commands/*.py` |
| ≈L354 | §9 | `api/jwt_tokens.py` | 删除该项 |
| ≈L357 | §9 | `cli/run_cmd.py` | `cli/commands/run.py` |
| ≈L358 | §9 | `infra/gateway/processor.py` | `infra/gateway/process/processor.py` |
| ≈L359 | §9 | `infra/agents/runtime.py` | 不存在；启停在 `infra/agents/manager.py`（`start` ≈L744、`stop` ≈L752、`_start_agent` ≈L2221） |

其余表格中的相对写法（例如 agents 行的 `manager.py`、`security/`）都能在对应目录下找到，不属于勘误对象。§7 的 i18n 清单（≈L286-291）要求把新键写进 `en.json` / `zh.json`，与全局约束 1.2 的规则二冲突，AI 代理照做会写进上游 bundle。§7 Database 段（≈L221-232）归 `w0-01`，本 spec 不碰。

## 方案

**1. 只在"冷"的扩展点留钩子，逻辑全部放进 fork 自有模块。**
四处钩子分别位于 `loader.py`（churn 7）、`i18n.ts`（7）、`app.py::_mount_routers`（`git log -L72,74:src/octop/api/app.py` 在可见历史里只有 shallow 边界提交 2af176b 一条）与 `catalog.py` 的 `_CATALOG` 定义处。上游文件里每处只留 1-4 行，合并解冲突时一眼可辨。

**2. overlay 语义与 i18next 的 `addResourceBundle(…, deep=true, overwrite=true)` 对齐。**
两侧都是：两边同为对象则递归合并；任一边是叶子，则 overlay 覆盖。后端 `deep_merge` 按这个语义实现，测试辅助函数也用它来模拟前端的合并结果，这样三方相等门禁在两端判定一致。形状冲突（叶子与对象互换）在运行时也能合并出结果，但会让键树与上游分叉，所以由测试拒绝。

**3. overlay 自身 en == zh 严格对等；上游 bundle 的存量不对等不在本 spec 处理。**
如果 fork 只想改 zh 的某条上游文案，也要在 en overlay 里放一份同键（可以照抄上游 en 的值）。这样"overlay 对等"就是一条无例外的规则。

**4. 路由按 router 对象身份过滤，引用写成 `"<模块>:<属性>"`。**
理由见"现状"：前缀、tag、模块名都不唯一。引用在 `build_app` 时解析；解析失败直接抛异常，实例起不来（fail closed）。因为拼写错误会让本该下线的路由继续暴露，这比静默跳过更安全。一个 router 如果被挂载多次，会整体下线；子 router 不能单独下线。

**5. 连接器目录用函数提供追加项，避免循环导入。**
全局约束第 3 节写的是 `_BASE + _FORK_ENTRIES`。但如果追加项是 `catalog_intranet.py` 的模块级常量，这个模块就必须在导入时 `from …catalog import ConnectorCatalogEntry`；而 `catalog.py` 又要在末尾导入 `catalog_intranet`。一旦 `catalog_intranet` 先被导入（例如测试直接导入它），`catalog.py` 执行到末尾时拿到的是半初始化的 `catalog_intranet`，会抛 `ImportError`。因此：
- 删除集 `_FORK_REMOVED` 仍是常量；
- 追加项改由函数 `_fork_entries()` 提供，函数内部再导入数据类；
- `catalog.py` 末尾执行 `_CATALOG = compose_catalog(_BASE)`，语义上等价于 `_BASE − _FORK_REMOVED + _FORK_ENTRIES`。
- 需求 5.5 用子进程按两种顺序导入来守住这一点。

**6. `make relock` 只重生成、不升级，registry 可配，不回显 URL。**
- `uv lock` 会把既有锁中的版本作为偏好，所以不传 `--upgrade`。
- npm 用 `--package-lock-only --ignore-scripts`：不装 `node_modules`，也不执行任何包脚本。
- registry 通过 `PYPI_INDEX` / `NPM_REGISTRY` 传入（后者复用 `w0-02` 已定义的变量）。
- 配方行用 `@` 前缀，echo 只打印占位符，避免把可能带凭据的 URL 打进日志。
- 锁文件里最终记录哪个 registry，由 `w2-01` 决定。

**7. 用行为测试守住 Python 钩子，用契约测试守住非 Python 钩子。**
- Python 侧的三处钩子，一旦在同步中丢失，行为用例（overlay 探针、下线过滤、目录合成）会直接变红。
- `i18n.ts` 的钩子有 vitest 用例，但它只在 `make check-frontend` 与 CI 的 frontend job 中执行。所以再加一条 pytest 契约测试，让 `make test` 在 Linux 与 Windows 上都能拦住。
- `Makefile.intranet` 的 `relock` 与 `docs/api.md` 的指针同理。

**8. 同步手册只写可执行命令，数据口径与全局约束一致。**
手册里的节奏数字（1 个 release 命中 66 个文件、4 个命中 81 个、13 个命中 203 个）引用全局约束第 5 节。手册同时要求首次同步前在完整历史上用同一口径重测一次，并把结果登记进 `CHANGELOG-intranet.md` 的同步记录表。

## 组件与接口

| 文件 | 类型 | 改动 |
|---|---|---|
| `src/octop/i18n/overlay.py` | 新增 | `_OVERLAY_ROOT`、`deep_merge`、`read_overlay` |
| `src/octop/i18n/intranet/en.json`、`zh.json` | 新增 | 内容为 `{}` |
| `src/octop/i18n/loader.py` | 修改 | 1 行 import；`_load_all` 循环体内 `out[loc] = json.loads(raw)` 改为 `out[loc] = deep_merge(json.loads(raw), read_overlay(loc))` |
| `dashboard/src/i18nIntranet.ts` | 新增 | `applyIntranetOverlay(locale)` |
| `dashboard/src/locales/intranet/en.json`、`zh.json` | 新增 | 内容为 `{}` |
| `dashboard/src/i18n.ts` | 修改 | 1 行 import；`ensureLocaleBundle` 的 if 块内、`addResourceBundle` 之后 1 行；`initI18n` 中 `await i18n.use(initReactI18next).init({...})` 之后 1 行 |
| `dashboard/src/i18nIntranet.test.ts` | 新增 | vitest：初始语言与后加载语言两条路径 |
| `tests/support/i18n_bundles.py` | 新增 | 合并后的 bundle 读取辅助函数 |
| `tests/unit/i18n/test_errors.py` | 修改 | 两个用例改用辅助函数（各 2-3 行） |
| `tests/unit/i18n/test_tools.py` | 修改 | `test_dashboard_tools_match_backend` 改用辅助函数 |
| `tests/unit/i18n/test_skills.py` | 修改 | `test_dashboard_skill_labels_match_backend` 改用辅助函数 |
| `tests/unit/i18n/test_intranet_overlay.py` | 新增 | 合并语义、探针（含用裸 `FastAPI` 挂 `i18n.router` 请求 `GET /api/i18n/tools`、`GET /api/i18n/skills`）、三种坏文件、两对 overlay 的对等与形状 |
| `src/octop/api/intranet_mounts.py` | 新增 | `_FORK_DISABLED_MOUNTS`、`resolve_router_ref`、`without_fork_disabled` |
| `src/octop/api/app.py` | 修改 | 1 行 import；`_mount_routers` 循环头 1 行 |
| `tests/unit/api/test_intranet_mounts.py` | 新增 | 过滤、fail closed、登记项有效性 |
| `src/octop/infra/connectors/catalog_intranet.py` | 新增 | `_FORK_REMOVED`、`_fork_entries`、`compose_catalog` |
| `src/octop/infra/connectors/catalog.py` | 修改 | 文件头 import 块加 1 行 import；≈L96 `_CATALOG` 改名 `_BASE`；≈L531 之后加 `_CATALOG = compose_catalog(_BASE)` |
| `tests/unit/connectors/test_catalog_intranet.py` | 新增 | 合成语义、删除集有效性、kind 唯一；子进程先改 `catalog_intranet` 再导入 `catalog`（守住合成钩子）与反向导入顺序 |
| `tests/integration/test_connectors_catalog_intranet.py` | 新增 | `GET /api/connectors/catalog` 过滤与追加 |
| `Makefile.intranet` | 修改 | `relock` 目标、`help-intranet` 增加两行 |
| `tests/unit/test_fork_isolation_contract.py` | 新增 | 非 Python 钩子的契约测试 |
| `CHANGELOG-intranet.md` | 新增（或统一已有格式） | 见下文 |
| `docs/api-intranet.md` | 新增 | 六节骨架 |
| `docs/api.md` | 修改 | L3 插入指针行与一个空行 |
| `docs/intranet/upstream-sync.md` | 新增 | 上游同步手册 |
| `AGENTS.md` | 修改 | §5 / §8 / §9 勘误；§7 i18n 清单加 1 条；§9 加 1 行 |

### `src/octop/i18n/overlay.py`（新增）

```python
"""Intranet fork i18n overlay (fork-owned module; upstream never edits it).

Fork-only strings live in ``octop/i18n/intranet/{en,zh}.json`` and are deep-merged
over the upstream bundles by ``loader._load_all``. Do not add or delete keys in the
upstream ``en.json`` / ``zh.json`` from the fork. Keep en/zh overlay key sets equal.
"""

_OVERLAY_ROOT: Traversable = resources.files("octop.i18n").joinpath("intranet")

def deep_merge(base: Mapping[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    """New dict: nested mappings merge recursively; otherwise the overlay value wins.

    Mirrors i18next ``addResourceBundle(lng, ns, bundle, deep=True, overwrite=True)``.
    Neither argument is mutated.
    """

def read_overlay(locale: str) -> dict[str, Any]:
    """Parse ``_OVERLAY_ROOT / f"{locale}.json"`` (``octop/i18n/intranet/<locale>.json``).

    Missing file / invalid JSON propagate; a non-object top level raises ``ValueError``.
    """
```

- 只依赖标准库，不导入 `loader`，因此没有循环导入。按 AGENTS.md §5，`octop.i18n` 可以依赖标准库与 `infra/utils/locale`，本模块符合要求。
- `_load_all` 直接调用 `deep_merge(json.loads(raw), read_overlay(loc))`，结果随 `lru_cache` 缓存；测试需要替换 overlay 时，把 `octop.i18n.overlay._OVERLAY_ROOT` monkeypatch 到 `tmp_path` 并写入真实文件（探针、缺失、非法、非对象都走同一条读取路径），前后各调用一次 `_load_all.cache_clear()`。`Traversable` 来自 `importlib.resources.abc`。

### `dashboard/src/i18nIntranet.ts`（新增）

```ts
import i18n from "i18next";
import intranetEn from "./locales/intranet/en.json";
import intranetZh from "./locales/intranet/zh.json";
import type { UiLocale } from "./utils/localePrefs";

const INTRANET_BUNDLES: Record<UiLocale, object> = { en: intranetEn, zh: intranetZh };

/** Deep-merge the intranet overlay over the already-loaded upstream bundle. */
export function applyIntranetOverlay(locale: UiLocale): void {
  i18n.addResourceBundle(locale, "translation", INTRANET_BUNDLES[locale], true, true);
}
```

- 选择静态导入：overlay 很小；同步函数也便于在 `ensureLocaleBundle` 与 `initI18n` 中各用一行调用。
- `i18nIntranet.ts` 不导入 `i18n.ts`，所以不会形成循环依赖。

`dashboard/src/i18n.ts` 的三处新增：

```ts
import { applyIntranetOverlay } from "./i18nIntranet";            // 新增
…
    i18n.addResourceBundle(locale, "translation", bundle, true, true);
    applyIntranetOverlay(locale);                                  // 新增，ensureLocaleBundle 的 if 块内
…
      await i18n.use(initReactI18next).init({ … });
      applyIntranetOverlay(initial);                               // 新增，initI18n 内
```

### `tests/support/i18n_bundles.py`（新增）

```python
REPO_ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_LOCALES = REPO_ROOT / "dashboard" / "src" / "locales"
DASHBOARD_OVERLAY_DIR = DASHBOARD_LOCALES / "intranet"

def read_json(path: Path) -> Any: ...
def merged_backend_bundle(locale: Locale) -> dict[str, Any]:
    """``_load_all()[locale]`` — exactly what the server serves."""
def merged_dashboard_bundle(locale: Locale) -> dict[str, Any]:
    """``deep_merge(<locales>/<locale>.json, <locales>/intranet/<locale>.json)``."""
```

形状冲突检查只有 `test_intranet_overlay.py` 一处使用，写成该文件内的私有函数。

叶子键集直接复用 `octop.i18n.loader.flatten_keys`，不另写一份。三个上游测试文件的改动都是把 `json.loads((repo / …).read_text(…))` 换成 `merged_dashboard_bundle("en")` / `merged_backend_bundle("en")`，断言本身不变。`test_dashboard_api_errors_use_i18next_placeholders` 的循环改为读 `merged_dashboard_bundle(locale)["apiErrors"]`。

### `src/octop/api/intranet_mounts.py`（新增）

```python
"""Upstream routers the intranet build does not mount (fork-owned).

List a router as "<module>:<attribute>" and name the owning spec in a trailing
comment, e.g. "octop.api.routers.search:router",  # w1-03
Physically deleted routers must instead drop their import + _RouterMount line.
"""

_FORK_DISABLED_MOUNTS: frozenset[str] = frozenset()

def resolve_router_ref(ref: str) -> APIRouter:
    """``ref.partition(":")`` → import module, getattr attribute; TypeError on non-APIRouter.

    ImportError / AttributeError propagate unchanged (fail closed at build_app); a
    missing ``:`` becomes ``getattr(module, "")`` → AttributeError.
    """

def without_fork_disabled(mounts: Sequence[_RouterMount]) -> list[_RouterMount]:
    """``mounts`` minus those whose ``router`` is (by identity) a disabled router."""
```

- `app.py` 中 `_mount_routers` 的循环头由 `for spec in mounts:` 改为 `for spec in without_fork_disabled(mounts):`。
- import 行按 ruff isort 顺序放在 `octop.api.middleware…` 之前。
- `_RouterMount` 只在 `TYPE_CHECKING` 下从 `octop.api.app` 导入，运行期没有循环导入，也不需要额外的协议类型。

### `src/octop/infra/connectors/catalog_intranet.py`（新增）

```python
"""Intranet connector catalog overrides (fork-owned).

catalog.py imports this module at its bottom. Do NOT import catalog at module
level here (circular); import ConnectorCatalogEntry / ConnectorCredentialField
inside _fork_entries().
"""
if TYPE_CHECKING:
    from octop.infra.connectors.catalog import ConnectorCatalogEntry

# Upstream kinds hidden in the intranet build; owner spec in a trailing comment.
_FORK_REMOVED: frozenset[str] = frozenset()

def _fork_entries() -> tuple[ConnectorCatalogEntry, ...]:
    """Intranet-only entries, appended after upstream ones (the steering's _FORK_ENTRIES)."""
    return ()

def compose_catalog(base: tuple[ConnectorCatalogEntry, ...]) -> tuple[ConnectorCatalogEntry, ...]:
    return tuple(e for e in base if e.kind not in _FORK_REMOVED) + _fork_entries()
```

`catalog.py` 的改动：

```python
from octop.infra.connectors.catalog_intranet import compose_catalog  # 文件头 import 块

_BASE: tuple[ConnectorCatalogEntry, ...] = (      # ≈L96，原名 _CATALOG
    …                                              # 23 条上游条目，一行不动
)

_CATALOG = compose_catalog(_BASE)
```

`catalog_intranet` 在模块级不导入 `catalog`，所以 import 放在文件头即可，不需要 `# noqa: E402`。

- `mcp_oauth_remote_kinds`、`list_catalog`、`get_catalog_entry` 都在调用时读取模块全局 `_CATALOG`，一行都不用改。
- `_FORK_REMOVED` 引用了不存在的 kind、合成后 kind 重复，这两类错误不在运行时校验，由单测在同步时拦截，理由见"错误处理"。

### `Makefile.intranet` 的 `relock` 目标（追加）

```make
.PHONY: relock
relock:
	@command -v uv >/dev/null 2>&1 || { echo "[relock] uv is required (pip cannot write uv.lock)"; exit 2; }
	@echo "[relock] uv lock$(if $(strip $(PYPI_INDEX)), --default-index <PYPI_INDEX>,)"
	@uv lock $(if $(strip $(PYPI_INDEX)),--default-index $(strip $(PYPI_INDEX)),)
	@echo "[relock] npm install --package-lock-only$(if $(strip $(NPM_REGISTRY)), --registry=<NPM_REGISTRY>,)"
	@cd $(DASHBOARD_DIR) && npm install --package-lock-only --ignore-scripts --no-audit --no-fund $(if $(strip $(NPM_REGISTRY)),--registry=$(strip $(NPM_REGISTRY)),)
```

- `help-intranet` 增加两行，列出 `relock` 与 `PYPI_INDEX=<url> NPM_REGISTRY=<url>`。不写 `PYPI_INDEX ?=`：未定义的 make 变量本来就展开为空（与 `w0-02` 对 `NPM_REGISTRY` 的处理一致）。
- `DASHBOARD_DIR` 由根 `Makefile` 定义，被 include 的文件可以直接使用。
- 在 make 的语义下，命令行变量与环境变量都会被 `?=` 接受。`make -n` 会展开 `@` 行，可以用来离线验证参数拼装。

### `CHANGELOG-intranet.md`（新增或统一格式）

```markdown
# 行内版变更记录

本文件只记录行内 fork 的变更；上游变更见 `CHANGELOG.md`（fork 不修改该文件）。
格式参照 Keep a Changelog；每条以 spec 目录名开头，写明用户可感知的变化与本地复现命令。

## [Unreleased]

### 新增
- `w0-01-fork-migration-namespace`：…
- `w0-02-ci-gates`：…
- `w0-03-test-auth-baseline`：…
- `w0-04-fork-isolation-points`：…

### 变更
### 移除
### 安全

## 上游同步记录

| 日期 | 上游区间 | 方式 | 命中 fork 改动面文件数 | 冲突文件 | 备注 |
|---|---|---|---|---|---|
| — | 基线 `757fd12`（1.0.1 + hotfix #792） | fork 起点 | — | — | — |
```

如果 `w0-02` 已经建过这个文件，就保留其条目，并改成上述结构。`w0-01` 的条目按其 tasks.md 任务 9 的约定，从其 PR 描述补录。

### `docs/api-intranet.md`（新增）

六节，每节是一张表，列为：对象、spec、说明、合入日期。

1. 已下线的上游路由（`_FORK_DISABLED_MOUNTS` 中的引用、原前缀、原 tag）
2. 已物理删除的上游路由
3. fork 新增或变更的端点
4. 鉴权与权限差异
5. fork 新增错误码（码、HTTP 状态、文案所在 overlay）
6. 连接器目录差异（`_FORK_REMOVED` 与 `_fork_entries()`）

本 spec 交付时各节均写"暂无"。`docs/api.md` 的指针行（L3）：

```markdown
> **Intranet fork:** routes this build removes or adds, auth differences and fork error codes are listed in [api-intranet.md](api-intranet.md).
```

### `docs/intranet/upstream-sync.md`（新增，中文）

手册按以下十节组织。命令中的 `<…>` 是占位符。

1. **原则**：长期 fork 加隔离点；放弃 vendor 镜像分支加补丁清单（全局约束第 5 节）；对应 D7。
2. **一次性准备**（按顺序执行）：
   - `git rev-parse --is-shallow-repository`（输出 `true` 时继续下一步）
   - `git fetch --unshallow origin`
   - `git remote add upstream https://github.com/TencentCloud/Octop.git`（行内环境用镜像地址替换）
   - `git fetch upstream --tags`
   - `git merge-base --is-ancestor 757fd12 upstream/main && echo baseline-on-upstream`
   - 首次按第 9 节在完整历史上重测 churn，并登记进 `CHANGELOG-intranet.md`。
3. **节奏与目标**：每 2-4 个上游 release（约 5-10 天）同步一次，引用全局约束第 5 节的 66 / 81 / 203 数据；只跟 main 上的 `v*` tag，候选 tag 用 `git tag -l 'v*' --merged upstream/main --sort=-v:refname` 列出；上次同步点以 `CHANGELOG-intranet.md` 的同步记录表为准。
4. **hotfix 例外通道**：
   - 发现：`git log --first-parent --merges --oneline --grep '/hotfix/' <上次同步点>..upstream/main`。
   - 触发条件：安全、构建、锁文件、数据损坏类热修。
   - 接入：如果 `git merge-base --is-ancestor <hotfix 合并提交>^1 HEAD` 成立（fork 已含其第一父），直接 `git merge --no-ff <hotfix 合并提交>`；否则 `git cherry-pick -x -m 1 <hotfix 合并提交>`。
   - 下次跟 tag 时照常合并；与 cherry-pick 重复的改动通常可以自动消解，冲突时取上游。
5. **同步流程**：`git switch -c sync/upstream-<tag> <fork 主干>` → `git merge --no-ff <tag>` → 按第 6 节解冲突 → `make relock`（锁文件单独一个提交）→ 按第 7、8 节核对与验证 → PR 合入 fork 主干（merge commit，不 squash）→ 登记同步记录。
6. **冲突规则**：见下表。
7. **同步后核对**：
   - 四处隔离点钩子仍在（契约测试加行为测试）；
   - `run_migrations` 末尾的 fork 调用仍在（`w0-01` 的 AST 守卫）；
   - 上游新增的 `NNN_` 迁移与 fork 的表、列不重名，新增迁移用 `git diff --name-only <旧 tag> <新 tag> -- src/octop/infra/db/migrations` 列出；
   - `_FORK_DISABLED_MOUNTS` 与 `_FORK_REMOVED` 仍指向存在的对象；overlay 与上游没有形状冲突；
   - `ci.yml` 中 fork 的 `frontend` / `postgresql` 两个 job 与根 `Makefile` 的 `include Makefile.intranet` 行仍在。
8. **验证命令**：
   - `make install-frontend && make all`
   - `make check-frontend`
   - `OCTOP_TEST_DATABASE_URL=<专用库 DSN> make test-postgresql`
   - `uv run pytest tests/unit/i18n tests/unit/test_fork_isolation_contract.py tests/unit/api/test_intranet_mounts.py tests/unit/connectors/test_catalog_intranet.py -q`
   - `uv lock --check`
9. **churn 测量**（统一使用 `--full-history --no-merges`，与全局约束第 5 节同一口径；shallow clone 上的数字只是下限）：
   - 单文件：`git log --full-history --no-merges --oneline <from>..<to> -- <path> | wc -l`
   - 窗口热点：`git log --full-history --no-merges --format= --name-only <旧 tag>..<新 tag> | sort | uniq -c | sort -rn | head -30`
   - 窗口命中 fork 改动面：`comm -12 <(git diff --name-only <旧 tag> <新 tag> | sort) <(git diff --name-only <旧 tag> HEAD | sort) | wc -l`
10. **失败回退**：尚未提交时 `git merge --abort`；已合入 fork 主干时 `git revert -m 1 <同步合并提交>`，再按第 5 节重做。

第 6 节冲突规则：

| 文件 | 规则 |
|---|---|
| `uv.lock`、`dashboard/package-lock.json` | `git checkout --theirs -- <file>`，之后执行 `make relock PYPI_INDEX=… NPM_REGISTRY=…`，单独提交 |
| `src/octop/i18n/{en,zh}.json`、`dashboard/src/locales/{en,zh}.json` | 取上游。如果冲突里出现 fork 的改动，说明违反了全局约束 1.2，把它挪进 overlay |
| `CHANGELOG.md` | 取上游 |
| `docs/api.md` | 取上游，但保留 L3 的指针行 |
| `src/octop/infra/errors.py` | 两边都保留；fork 新码始终在 `ErrorCode` 末尾与 `_DEFAULT_STATUS` 末尾 |
| `infra/agents/manager.py`、`infra/gateway/process/processor.py`、`infra/db/migrate.py` | 取上游，再把 fork 的单行调用补回原位置；不接受多于单行的 fork 逻辑 |
| `loader.py`、`i18n.ts`、`app.py::_mount_routers`、`catalog.py` 的 `_CATALOG` | 取上游，再补回钩子行；由契约测试与行为测试确认 |
| `.github/workflows/ci.yml`、根 `Makefile` | 不得整体取上游；保留 fork 的 `frontend` / `postgresql` job 与 `include Makefile.intranet` 行（`w0-02` 的合同测试会拦截） |
| `pyproject.toml` | 上游主要在文件尾追加 `[[tool.mypy.overrides]]`，两边都保留；fork 的依赖改动集中在 `dependencies` 与独立的 extra 块 |
| 上游删除了 fork overlay 覆盖的键 | overlay 中该键成为孤儿，这是合法的；如果不再需要就从 overlay 删除 |

### AGENTS.md（修改）

- §5：
  - `infra/` 子包表的 gateway 一行改为实际路径（见"现状"中的表）；
  - `api/` 表删除 `api/errors.py` 行，把它的"映射 `OctopError`"并入 `api/app.py` 行，把"新错误语义放 `infra/errors.py`"并入该行的 Must NOT 列；
  - `api/deps.py` 行去掉 `api/jwt_tokens.py`，补上 `api/middleware/jwt_auth.py` 的指向；
  - `cli/` 表中 `*_cmd.py` 系列改为 `cli/commands/*.py`，并注明由 `cli/registry.py` 懒加载。
- §8：`cli/*_cmd.py` 改为 `cli/commands/*.py`。
- §9：
  - 修正 auth、`octop run`、消息处理、agent 启停四行；
  - 新增一行："Intranet fork: isolation points, upstream sync | `docs/intranet/upstream-sync.md`, `CHANGELOG-intranet.md`, `docs/api-intranet.md`"。
- §7 "Adding strings (checklist)" 末尾新增一条：

  > 5. **Intranet fork:** put new or overridden strings in `src/octop/i18n/intranet/{en,zh}.json` and `dashboard/src/locales/intranet/{en,zh}.json` (deep-merged overlays, en/zh key sets must match); never add or delete keys in the upstream bundles.

## 数据模型

无。本 spec 不新增、不修改任何表，也没有 `forkNNN_` 迁移。

## 配置

无 `config.py` 键，不涉及配置三触点。

只新增一个 Make 变量 `PYPI_INDEX`（`Makefile.intranet`，默认为空）；`NPM_REGISTRY` 复用 `w0-02` 的定义。两者都只影响 `make relock`，不进入 `OctopConfig`。

## 错误处理

不新增 `ErrorCode`，也不改 `_DEFAULT_STATUS`。各类失败的表现与设计理由如下：

| 情形 | 表现 | 理由 |
|---|---|---|
| overlay 文件缺失、JSON 非法、顶层不是对象 | 首次 `_load_all()` 抛 `FileNotFoundError` / `json.JSONDecodeError` / `ValueError` | 文件随仓库提交、随 wheel 打包，现实中只会因开发者失误而出现；`tests/unit/i18n/test_intranet_overlay.py` 在 `make test` 中先暴露它。不加兜底，避免 overlay 被静默丢弃 |
| overlay 形状冲突、en / zh 不对等 | 运行时照常合并；测试失败 | 属于开发期错误，由测试在合入前拦截 |
| `_FORK_DISABLED_MOUNTS` 中的引用无效 | `build_app` 抛 `RuntimeError` / `ImportError` / `AttributeError`，实例启动失败 | fail closed：拼写错误不能导致本该下线的路由继续暴露 |
| `_FORK_REMOVED` 引用的 kind 已不存在、合成后 kind 重复 | 运行时不报错；单测失败 | 上游改名或新增同名 kind 只在同步时发生。在导入期抛错会让整个实例因一条目录项起不来，代价过高；单测在同步 PR 上一定会执行 |
| `make relock` 缺少 uv | 退出码 2，并给出提示 | 根 `Makefile` 在没有 uv 时会退回 pip，而 pip 不能写 `uv.lock` |
| registry 不可达或凭据错误 | uv 或 npm 自身报错，make 以非零退出码结束 | 不做重试 |

被下线的路由对外表现为：未带令牌时由 JWT 中间件先返回 401；带有效令牌时返回 404（没有注册该路由；对 `api/` 路径，dashboard 的 SPA 兜底也会抛 404）。这与"路由不存在"一致，不泄露它曾经存在。

## 安全考虑

- **overlay 可以改写任何上游文案，包括安全提示。** 这是有意为之，比如行内品牌化或合规措辞；但也意味着 overlay 的 diff 需要评审。形状测试与对等测试只保证结构正确，不保证语义正确。
- **`_FORK_DISABLED_MOUNTS` 只让路由不被挂载，不是完整的能力关停。** 同一能力如果还能通过 WebSocket 以外的内部调用、harness 工具或定时任务触达，需要由 `w1-02` 的 `forced_disabled_tools` 与 `require_capability` 兜住。下线路由的 spec 还应检查 `api/deps.py` 的 `_JWT_EXEMPT_PREFIXES` / `_JWT_EXEMPT_EXACT`（≈L66-88）里是否残留指向该路由的公开豁免项。
- **fail closed**：无效的下线引用会让实例起不来，而不是静默继续挂载。
- **`make relock` 的供应链面**：
  - `--ignore-scripts` 保证重生成锁文件时不执行任何包的生命周期脚本；
  - 不传 `--upgrade`，避免顺带升级；
  - uv 锁文件中的哈希与 npm 的 `integrity` 字段照常写入，完整性校验不被削弱。
- **凭据**：手册要求不要把凭据写进 `PYPI_INDEX` / `NPM_REGISTRY` 的 URL，改用 uv 的 `UV_INDEX_*` 凭据环境变量、netrc 或用户级 `.npmrc`。配方不回显 URL。提交前执行 `! rg -n '://[^/@ ]+:[^/@ ]+@' uv.lock dashboard/package-lock.json`，确认锁文件中没有内嵌凭据。
- **上游同步**：hotfix 例外通道专门用来及时接入安全与构建类热修。同步 PR 必须看到四处钩子与 `w0-01`、`w0-02` 的守卫全部通过才能合入。

## 测试策略

| 类别 | 用例 | 本地命令 |
|---|---|---|
| 单测：后端 overlay | `tests/unit/i18n/test_intranet_overlay.py`：`deep_merge` 语义与不修改入参；替身 overlay 下 `tr` / `lookup` / `all_keys_for_locale` / `all_tool_labels` / `all_skill_labels` 取到 overlay 值；缺文件、非法 JSON、非对象三种情形下首次 `_load_all()` 抛异常（`importlib.resources` 找不到 overlay 时全部 i18n 用例都会失败，不再单写打包用例）；两对 overlay 的 en == zh 叶子键集；两对 overlay 与上游的形状冲突 | `uv run pytest tests/unit/i18n -q` |
| 单测：门禁改读合并 bundle | `test_errors.py`、`test_tools.py`、`test_skills.py` 改用 `tests/support/i18n_bundles.py`；另在 `test_intranet_overlay.py` 中用替身 dashboard overlay 调用 `merged_dashboard_bundle`，证明合并确实生效 | 同上 |
| 单测：路由下线 | `tests/unit/api/test_intranet_mounts.py`：`without_fork_disabled` 在空集下原样返回；对 `_FORK_DISABLED_MOUNTS ∪ {"octop.api.routers.search:router"}` 的每一项参数化：空集下构建一次、只登记该项再构建一次，比较两次 `app.openapi()["paths"]`（即 `/api/openapi.json` 的内容），前者多出的路径非空（登记项确实会被挂载）、`/api/auth/login` 仍在，search 恰好少了 `/api/search/{provider_id}/test`；非法引用（缺冒号、模块不存在、属性不存在、非 APIRouter）时 `build_app` 抛异常。`build_app` 用 `SimpleNamespace(services=None)` 作替身 server，不启动 `OctopServer`；FastAPI 0.138 的 `app.routes` 里是 `_IncludedRouter` 包装，所以按路径比对走 OpenAPI | `uv run pytest tests/unit/api/test_intranet_mounts.py -q` |
| 单测：连接器目录 | `tests/unit/connectors/test_catalog_intranet.py`：`list_catalog()` 等于 `[e for e in _BASE if e.kind not in _FORK_REMOVED] + list(_fork_entries())`；`_FORK_REMOVED ⊆ {e.kind for e in _BASE}`；合成后 kind 唯一；子进程先导入 `catalog_intranet` 并改写 `_FORK_REMOVED = {"notion"}` 与 `_fork_entries`（函数内导入 `_BASE` 构造 `bank-probe`），再导入 `catalog`，断言 `list_catalog()`、`get_catalog_entry`、`mcp_oauth_remote_kinds()` 反映删除与追加——只 monkeypatch `_CATALOG` 的写法在钩子丢失时仍会通过，子进程写法才守得住合成钩子；另一个子进程按"先 catalog 后 catalog_intranet"导入并调用 `list_catalog()`（`subprocess.run([sys.executable, "-c", …])`，与平台无关） | `uv run pytest tests/unit/connectors/test_catalog_intranet.py tests/unit/test_connectors.py -q` |
| 单测：i18n API | 并入 `test_intranet_overlay.py` 的探针用例：两个路由不依赖鉴权与 server，用裸 `FastAPI` 挂 `octop.api.routers.i18n.router`，带 `Accept-Language: zh` 请求 `GET /api/i18n/tools` 与 `GET /api/i18n/skills`，断言返回探针值 | `uv run pytest tests/unit/i18n -q` |
| 集成：连接器目录 | `tests/integration/test_connectors_catalog_intranet.py`：用 `env` fixture，monkeypatch `octop.infra.connectors.catalog._CATALOG` 为合成结果后，`GET /api/connectors/catalog` 不含被删 kind、含追加 kind 且排在最后（只验 API 读的是 `_CATALOG`）；回归既有 `test_connectors_api.py` 与 `test_scalar.py` | `uv run pytest tests/integration/test_connectors_catalog_intranet.py tests/integration/test_connectors_api.py tests/integration/test_scalar.py -q` |
| 契约 | `tests/unit/test_fork_isolation_contract.py`：`i18n.ts` 从 `./i18nIntranet` 导入且 `applyIntranetOverlay(` 不少于 2 处；`Makefile.intranet` 以行首 `relock:` 定义目标，且 `help-intranet` 有 `relock` 一行；`docs/api.md` 前 5 行含 `api-intranet.md`。写成一个按（文件、正则、最少次数）参数化的用例 | `uv run pytest tests/unit/test_fork_isolation_contract.py -q` |
| 前端 | `dashboard/src/i18nIntranet.test.ts`：`vi.mock` 两份 overlay JSON（覆盖 `common.save`，新增 `intranetProbe.hello`）；在 `localStorage` 中写入 `UI_LOCALE_STORAGE_KEY = "en"` 后 `await initI18n()`，断言 en 覆盖生效、`common.reset` 仍是上游值；`await ensureLocaleBundle("zh")` 后断言 zh 覆盖生效，且 `common.reset` 等于上游 zh 的值（静态导入 `./locales/zh.json` 取期望值） | `cd dashboard && npx tsc -b && npm run lint && npm run test -- src/i18nIntranet.test.ts`，或 `make check-frontend` |
| 打包 | wheel 中包含两份后端 overlay | `d=$(mktemp -d) && uv build --wheel -o "$d" && uv run python -c "import sys,glob,zipfile; n=set(zipfile.ZipFile(glob.glob(sys.argv[1]+'/*.whl')[0]).namelist()); assert {'octop/i18n/intranet/en.json','octop/i18n/intranet/zh.json'} <= n; print('wheel-ok')" "$d"` |
| relock | 参数拼装与幂等 | 见表后命令 |
| PG | 无。本 spec 不触及数据库，`make test-postgresql` 的用例集合与结果不变 | — |

`make relock` 的验证命令：

- 参数拼装（离线可跑）：`make -n relock PYPI_INDEX=https://pypi.example/simple NPM_REGISTRY=https://npm.example/ | rg -e '--default-index https://pypi.example/simple' -e '--registry=https://npm.example/'`，期望两行都命中。
- 幂等（需要能访问默认 registry 或行内镜像）：`make relock && git diff --exit-code -- uv.lock dashboard/package-lock.json`，期望退出码为 0。

所有新增的 Python 测试都遵守 AGENTS.md §7 的跨平台约定：只用 `pathlib` 与 `tmp_path`，文本读取指定 `encoding="utf-8"`，子进程用 `sys.executable`，不断言 POSIX 路径。

## 与其他 spec 的交接

**依赖：**

- `w0-02-ci-gates`：`Makefile.intranet`（含 `NPM_REGISTRY`、`help-intranet`）与根 `Makefile` 的 `include` 行；vitest 门禁（`make check-frontend` 与 CI 的 frontend job），这是需求 2 能被机器验证的前提（全局约束 1.3）。
- `w0-01-fork-migration-namespace`：同步手册引用它的 AST 守卫与"上游新迁移不与 fork 表同名"核对项；`CHANGELOG-intranet.md` 要补录它的条目。
- `w0-03-test-auth-baseline`：集成用例使用的 `env` fixture 以它的新基线为准；`CHANGELOG-intranet.md` 要收录它的条目。

**交付给：**

| 消费方 | 交付物与用法 |
|---|---|
| 全部后续 spec | 新增或改写文案写进两对 overlay（en / zh 同键）；新增 `ErrorCode` 的文案可以放 overlay（`errors.X` 与 `apiErrors.X`），三方相等门禁读合并结果；API 变化写进 `docs/api-intranet.md`；变更写进 `CHANGELOG-intranet.md`；不改 `CHANGELOG.md` 与 `docs/api.md` 正文 |
| `w1-02-capability-trim` | 物理删除 acp / terminal / browser / desktop / mobile 路由时，同批删 import 与 mount 行（全局约束第 2 节）；只下线不删除的路由登记进 `_FORK_DISABLED_MOUNTS`。它的 `_mount_if_capable` 必须经过 `_mount_routers`（或调用 `without_fork_disabled`），使静态下线优先于能力开关。它删 playwright / `@xterm/*` 后用 `make relock` 重生成锁文件。能力开关的显示名写进 dashboard overlay |
| `w1-03-online-fetch-trim` | 联网搜索等下线路由可登记进 `_FORK_DISABLED_MOUNTS`（例如 `"octop.api.routers.search:router"`），并同批检查 JWT 豁免项 |
| `w1-05-saas-decoupling` | 21 个公网 SaaS 连接器的 kind 登记进 `_FORK_REMOVED`，不编辑 `_BASE`；数据库中存量的已删 kind 连接器行由它自己清理；删除 `edge-tts` 等依赖后执行 `make relock` |
| `w2-01-offline-build` | 在行内私服上实测 `make relock PYPI_INDEX=… NPM_REGISTRY=…`；决定提交到 fork 的锁文件记录公网还是私服 URL，以及路径前缀型 npm 镜像与 `replace-registry-host=always` 的兼容做法；确认私服能提供 `harness-*` 与 `orcakit-harness-agent`（`uv.lock` ≈L1332-1372、≈L2837） |
| `w2-02-supply-chain-compliance` | SBOM 与 SCA 以 `make relock` 之后的锁文件为输入 |
| `p2-06-intranet-integration` | 行内 OA / KB / 工单连接器写进 `_fork_entries()`（在函数内导入数据类，category 复用既有取值以免改 `ConnectorCategory`） |
| `w4-01-frontend-baseline` | 前端内网适配文案一律进 dashboard overlay |

**看似相关、但归别的 spec：**

| 事项 | 归属 |
|---|---|
| 能力开关框架、`_mount_if_capable`、`require_capability`、`forced_disabled_tools` | `w1-02` |
| AGENTS.md §7 Database 段 | `w0-01` |
| CI job、`Makefile.intranet` 文件本身 | `w0-02` |
| 锁文件记录哪个 registry、私服与镜像兼容 | `w2-01` |
| 删除任何 i18n 键 | 全局约束 1.2 禁止，任何 spec 都不做 |
| dashboard 上游两份 locale 的全量对等（存量相差 137 键） | 不在本轮任何 spec 内 |
| `docs/agent-call-agent.md`、`docs/agent-interop-mailbox.md`、`docs/agent-delegation.md`、`docs/adr/001-single-process-model.md` 中过期的 `infra/gateway/processor.py` 路径；`make docs-cli` 依赖的 `scripts/regen_cli_docs.py` 不存在 | 本 spec 只登记，不修 |

## 风险与回滚

| 风险 | 影响 | 缓解 |
|---|---|---|
| 上游同步解冲突时误删某处钩子 | overlay、下线、目录合成悄悄失效 | Python 钩子由行为用例拦截，非 Python 钩子由契约测试拦截，两者都在 `make test` 中执行；手册第 7 节单列核对项 |
| 上游改写 `_load_all` 或 `_mount_routers` 的结构（例如改为异步加载或按条件挂载） | 钩子需要重新落位 | 这两个函数的 churn 很低；手册要求同步时按"取上游、补回钩子"处理，行为用例确认补对了 |
| 上游改名或删除 `_FORK_REMOVED` 引用的 kind | 改名后的 SaaS 连接器重新出现 | `test_catalog_intranet.py` 的 `_FORK_REMOVED ⊆ _BASE.kinds` 在同步 PR 上变红 |
| 上游新增与 fork 追加项同名的 kind | `get_catalog_entry` 返回先出现的上游条目 | kind 唯一性用例变红；fork kind 建议带 `bank-` 前缀（由 `p2-06` 自定） |
| 上游删除或改名被 `_FORK_DISABLED_MOUNTS` 引用的 router | `build_app` 启动失败 | 这是预期的 fail closed；有效性用例在同步 PR 上先变红，同步者更新引用或删除该项 |
| overlay 覆盖的上游键被上游改成子树 | 形状冲突 | 形状用例变红，同步者调整 overlay |
| 首屏语言的 overlay 没有生效（钩子只加在 `ensureLocaleBundle`） | 初始语言显示上游文案 | 设计中两处都加；vitest 用例覆盖初始语言路径 |
| `make relock` 在私服上解析出与公网不同的版本 | 锁文件漂移 | 不传 `--upgrade`；锁文件单独一个提交，便于审阅与回退；具体策略由 `w2-01` 定 |
| 未 unshallow 就执行同步 | 合并基准错误，churn 数据偏低 | 手册第 2 节把 `--is-shallow-repository` 检查列为第一步 |

**回滚：**

- 本 spec 没有数据迁移、没有配置键，合入时所有集合为空，因此 `git revert` 合并提交即可完整回滚。
- 如果后续 spec 已经往 overlay、`_FORK_DISABLED_MOUNTS`、`_FORK_REMOVED` 里写了内容，要先回滚或迁出这些内容，再回滚本 spec；否则 overlay 文案会丢失，已下线的路由会重新暴露。
- 文档类改动（`CHANGELOG-intranet.md`、`docs/api-intranet.md`、手册、AGENTS.md 勘误）可以单独保留，不依赖代码钩子。

## 待行方确认

- **D7（是否长期跟上游）：** 本 spec 的全部设计以默认假设为前提：长期 fork，每 2-4 个上游 release 同步一次，跟 main 上的 `v*` tag，外加 hotfix 例外通道。如果行方决定不再跟上游，隔离点仍然降低 fork 内部的冲突，但同步手册作废。
- **D13（`harness-*` 源码可得、导入行内 Git）：** 这会影响 `make relock` 在行内能否解析出 `harness-gateway`、`harness-memory`、`harness-browser`、`orcakit-harness-agent`。本 spec 只提供机制，由 `w2-01` 落实。
- **非 D 编号的事项：** 行内是否有上游仓库（`https://github.com/TencentCloud/Octop`，含 tags）的只读镜像，以及同步在哪台可出网或可访问镜像的机器上执行。手册第 2 节的 `upstream` 地址以行方答复为准。
