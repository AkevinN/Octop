# 需求文档：fork 隔离点与上游同步机制

> spec：`w0-04-fork-isolation-points` ｜ 波次：Wave 0 ｜ 基线：`757fd12` ｜ 预估：5 人日
> 前置：`w0-02-ci-gates`、`w0-01-fork-migration-namespace` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 引言

**结论：** 本 spec 在上游高频文件里只留下约 10 行"钩子"，换来一组 fork 自有的扩展文件。之后的 spec 可以用"加文件"代替"改上游文件"：新增文案写进 i18n overlay，下线路由登记进 `_FORK_DISABLED_MOUNTS`，删除或追加连接器写进 `catalog_intranet.py`，锁文件冲突取上游后用 `make relock` 重生成，变更记录与 API 差异写进 fork 自己的文档。本 spec 同时交付上游同步手册，并勘误 AGENTS.md 中不存在或已过期的路径。本 spec 不改变任何运行时行为：所有 overlay 与登记集合初始都为空，合入后的行为与基线逐字节一致。

### 背景

- 全局约束第 5 节已经决定采用"长期 fork 分支 + 隔离点"，放弃"vendor 镜像分支 + 补丁清单"。按 `--full-history --no-merges` 口径实测，fork 声明面的热文件包括：`dashboard/src/locales/zh.json` 108 次、`en.json` 106 次，`CHANGELOG.md` 106 次，`uv.lock` 59 次，`src/octop/i18n/zh.json` 43 次，`docs/api.md` 24 次，`src/octop/api/app.py` 20 次，`AGENTS.md` 16 次，`src/octop/infra/connectors/catalog.py` 12 次。
- 这些热文件的对应扩展点本身都很"冷"：`src/octop/i18n/loader.py` 只改过 7 次，`dashboard/src/i18n.ts` 也只有 7 次。`app.py` 的 `_mount_routers` 是一个 3 行函数，`catalog.py` 的 `_CATALOG` 只在本文件内被引用。
- 全局约束 1.2 规定：裁剪能力时不删 i18n 键，fork 新增的文案写进 overlay。这条规则要落地，前提是 overlay 真实存在，而且四条 i18n 机器门禁（`test_catalog` / `test_errors` / `test_tools` / `test_skills`）读的是合并后的 bundle。基线上有三条门禁直接读原始 JSON 文件，fork 一旦在 overlay 里新增 `ErrorCode` 文案，这三条门禁就会变红。
- 本地 clone 是 shallow（`.git/shallow` 有 7 个边界提交），没有任何 tag，也没有 `upstream` 远端。所以手册要求的"跟 main 上的 `v*` tag"在当前 clone 上连基线都取不到。
- AGENTS.md §5 / §9 引用的 `api/jwt_tokens.py`、`api/errors.py`、`cli/*_cmd.py`、`cli/run_cmd.py`、`infra/gateway/processor.py`、`infra/agents/runtime.py` 等路径在仓库里都不存在。AI 代理按这些路径导航会直接落空。

### 为什么做

Wave 1 起，几乎每个 spec 都要新增文案（全部）、下线路由（`w1-02` / `w1-03` / `w1-05`）、删除或追加连接器（`w1-05`、`p2-06`）、重生成锁文件（`w1-02`、`w1-05`、`w2-01`），并记录变更与 API 差异。没有隔离点时，这些改动会各自落在全仓 churn 最高的文件上，每次上游同步都要重解数百行冲突。本 spec 把冲突面压缩成"每次同步确认 4 处钩子仍在"，并用测试守住这 4 处钩子。

### 范围内

1. 后端 i18n overlay：新增 `src/octop/i18n/overlay.py` 与 `src/octop/i18n/intranet/{en,zh}.json`，`src/octop/i18n/loader.py` 的 `_load_all` 改为深合并 overlay。
2. 前端 i18n overlay：新增 `dashboard/src/i18nIntranet.ts` 与 `dashboard/src/locales/intranet/{en,zh}.json`，`dashboard/src/i18n.ts` 在两处加载点追加 `addResourceBundle(locale, "translation", intranetBundle, true, true)`。
3. i18n 门禁：`test_errors` / `test_tools` / `test_skills` 改读合并后的 bundle（`test_catalog` 经 loader 已自动读合并结果，不改代码）；为两对 overlay 各加 en == zh 对等测试与形状冲突测试。
4. `src/octop/api/app.py` 的 `_mount_routers` 加 `_FORK_DISABLED_MOUNTS` 过滤，登记集合放在 fork 自有模块 `src/octop/api/intranet_mounts.py`。
5. `src/octop/infra/connectors/catalog.py` 的 `_CATALOG` 改为由上游条目 `_BASE` 与 fork 模块 `catalog_intranet.py` 中的 `_FORK_REMOVED`（删除集）、`_fork_entries()`（追加项）合成。
6. `Makefile.intranet` 新增 `relock` 目标：重生成 `uv.lock` 与 `dashboard/package-lock.json`，registry 可配置。
7. 新建 `CHANGELOG-intranet.md`、`docs/api-intranet.md`，并在 `docs/api.md` 顶部加一行指针。
8. 新建上游同步手册 `docs/intranet/upstream-sync.md`：unshallow、添加 upstream 远端、每 2-4 个 release 同步一次、跟 `v*` tag 加 hotfix 例外通道、冲突处理规则、用 `--full-history` 测 churn。
9. AGENTS.md 勘误：§5 / §9（以及同类的 §8 一行）中不存在的路径。另在 §7 的 i18n 清单补一条 overlay 规则，在 §9 补一行 fork 文档入口。
10. 守住上述钩子的契约测试 `tests/unit/test_fork_isolation_contract.py`。

### 范围外（归属）

- AGENTS.md §7 迁移段、fork 迁移 runner：`w0-01-fork-migration-namespace`。本 spec 不碰 AGENTS.md 的 Database 段。
- CI frontend job、postgres service、`Makefile.intranet` 文件本身与 `include` 行：`w0-02-ci-gates`。本 spec 只在该文件里追加 `relock` 目标。
- 能力开关框架 `capabilities.<name>.enabled`、`require_capability`、`_mount_if_capable`、`forced_disabled_tools`：`w1-02-capability-trim`。`_FORK_DISABLED_MOUNTS` 只是静态的"不挂载"，不是运行期开关，也拦不住 harness 侧工具。
- 往 `_FORK_DISABLED_MOUNTS`、`_FORK_REMOVED`、`_fork_entries()`、overlay 里填写具体内容：由各消费方 spec 负责（`w1-02` / `w1-03` / `w1-05` 下线路由与连接器，`p2-06` 追加行内连接器，全部 spec 新增文案）。本 spec 交付时这些集合全部为空。
- 锁文件里最终记录公网还是行内私服 URL、私服能否提供 `harness-*` 包、`.npmrc` 的 `replace-registry-host` 与路径前缀型镜像是否兼容：`w2-01-offline-build`。本 spec 只提供可配置 registry 的机制。
- dashboard 上游两份 locale 的全量对等测试（存量相差 137 键）：全局约束 1.2 已确认它不是门禁，本 spec 不补。本 spec 只对 overlay 做对等测试。
- 新增或删除任何 `ErrorCode`：本 spec 不涉及。以后的新码按全局约束 1.2 规则三执行，文案可放 overlay。
- `docs/` 下其他文档里的过期路径（如 `docs/agent-call-agent.md` 中的 `infra/gateway/processor.py`）、`make docs-cli` 调用的脚本 `scripts/regen_cli_docs.py` 不存在：只登记，不修。

## 需求

### 需求 1：后端 i18n overlay

**用户故事：** 作为 fork 开发者，我希望把新增或改写的服务端文案写进 `src/octop/i18n/intranet/{en,zh}.json`，由 loader 深合并到上游 bundle 之上，以便从此不再编辑上游的 `src/octop/i18n/{en,zh}.json`。

#### 验收标准

1. 当 `octop.i18n.loader._load_all()` 首次加载某个 locale 时，loader 应当把 `src/octop/i18n/intranet/<locale>.json` 深合并到上游 `src/octop/i18n/<locale>.json` 之上：同一路径上的叶子取 overlay 的值，同名子树递归合并，上游中未被覆盖的键原样保留。
2. 当 overlay 提供某个键时，`tr()`、`lookup()`、`all_keys_for_locale()`、`all_tool_labels()`、`all_skill_labels()`，以及 `GET /api/i18n/tools`、`GET /api/i18n/skills` 应当返回 overlay 中的值。由新增用例用替身 overlay 验证。
3. 如果 overlay 文件缺失、不是合法 JSON，或者顶层不是 JSON 对象，那么首次调用 `_load_all()` 应当抛出异常（`FileNotFoundError`、`json.JSONDecodeError` 或 `ValueError`），而不是静默忽略 overlay。
4. 在两份后端 overlay 都为 `{}` 期间，`_load_all()` 的结果应当与基线逐键相等，基线上 `uv run pytest tests/unit/i18n -q` 的 69 个用例应当全部通过。
5. `deep_merge` 应当始终返回新的字典，不修改传入的 base 与 overlay。构建出的 wheel 应当始终包含 `octop/i18n/intranet/en.json` 与 `octop/i18n/intranet/zh.json`。

### 需求 2：前端 i18n overlay

**用户故事：** 作为 fork 前端开发者，我希望把界面新增或改写的文案写进 `dashboard/src/locales/intranet/{en,zh}.json`，由 i18next 以深合并、覆盖的方式叠加到上游 bundle 之上，以便不再编辑全仓 churn 最高的 `dashboard/src/locales/{en,zh}.json`。

#### 验收标准

1. 当 `initI18n()` 用初始语言完成 `i18n.init(...)` 时，dashboard 应当在 `initI18n()` 返回之前（也就是首次渲染之前）对该语言执行一次 `i18n.addResourceBundle(locale, "translation", <该语言的 intranet bundle>, true, true)`。
2. 当 `ensureLocaleBundle(locale)` 首次加载某个语言的上游 bundle 时，dashboard 应当在上游 bundle 加载后立即叠加该语言的 overlay。如果该语言已经加载过，那么 dashboard 应当既不重复加载上游 bundle，也不重复叠加 overlay。
3. 在 overlay 覆盖某个键期间，`i18n.t(<该键>)` 应当返回 overlay 的值，同一命名空间下未被覆盖的兄弟键仍返回上游的值。由 vitest 用例 `dashboard/src/i18nIntranet.test.ts` 验证初始语言与后加载语言两条路径。
4. 在本 spec 合入时，`dashboard/src/i18n.ts` 相对基线应当只有新增行、没有删除行，新增行只有一行 import 与两处 `applyIntranetOverlay(...)` 调用：`git diff --numstat 757fd12 -- dashboard/src/i18n.ts` 输出 `3	0`。

### 需求 3：i18n 门禁读合并后的 bundle，overlay 自身对等

**用户故事：** 作为 fork 维护者，我希望四条 i18n 机器门禁检查的是"上游 + overlay"合并后的真实 bundle，并且 overlay 自己的 en / zh 严格对等，以便 fork 在 overlay 里新增 `ErrorCode` 文案或工具名时门禁仍然成立，漏写一种语言时 `make test` 直接变红。

#### 验收标准

1. 当运行 `tests/unit/i18n/test_errors.py::test_dashboard_api_errors_match_backend` 时，该用例应当断言：合并后的 dashboard en `apiErrors` 键集 == 合并后的后端 en `errors` 键集 == `ErrorCode` 全集。`test_dashboard_api_errors_use_i18next_placeholders` 应当检查合并后的 en 与 zh 两份 dashboard `apiErrors`。
2. 当运行 `tests/unit/i18n/test_tools.py::test_dashboard_tools_match_backend` 与 `tests/unit/i18n/test_skills.py::test_dashboard_skill_labels_match_backend` 时，它们应当分别断言：合并后的 dashboard 与合并后的后端 `tools` 字典全等；合并后的后端 `skills` 中每个 slug 在合并后的 dashboard 中取值相同。
3. 当后端 overlay 含一个探针键时，`all_keys_for_locale()` 的结果应当包含该键。以此证明 `tests/unit/i18n/test_catalog.py::test_en_and_zh_share_same_keys` 不改代码即覆盖合并后的 bundle。
4. 如果后端 overlay 的 en 与 zh 叶子键集不相等，或者 dashboard overlay 的 en 与 zh 叶子键集不相等，那么 `tests/unit/i18n/test_intranet_overlay.py` 应当失败，并在失败信息里列出差异键。
5. 如果任一 overlay 在上游为字符串叶子的路径上给出对象，或者在上游为对象的路径上给出字符串，那么 `tests/unit/i18n/test_intranet_overlay.py` 应当失败，并列出冲突路径。
6. 本 spec 应当始终不删除、不改写上游四份 locale JSON 中的任何键：`git diff --stat 757fd12 -- src/octop/i18n/en.json src/octop/i18n/zh.json dashboard/src/locales/en.json dashboard/src/locales/zh.json` 输出为空。

### 需求 4：路由下线过滤 `_FORK_DISABLED_MOUNTS`

**用户故事：** 作为负责裁剪能力的 spec 作者，我希望把"不在行内版暴露的上游路由"登记到 fork 自有模块里的一个集合，由 `_mount_routers` 统一过滤，以便不再逐行编辑 `app.py` 的 57 处 `_RouterMount(...)` 与 import 块。

#### 验收标准

1. 当 `_FORK_DISABLED_MOUNTS` 含 `"<模块路径>:<属性名>"` 形式的引用时，`build_app` 应当跳过该引用解析出的 router 对象的所有挂载（主挂载列表和 `if enable_mobile:` 块都经过 `_mount_routers`），该 router 的路径应当不出现在 `app.routes` 与 `/api/openapi.json` 中。
2. 如果某个引用缺少 `:`、模块无法导入、属性不存在，或属性不是 `fastapi.APIRouter`，那么 `build_app` 应当抛出异常、使实例启动失败，而不是继续挂载该 router。
3. 在 `_FORK_DISABLED_MOUNTS` 为空期间，`without_fork_disabled(mounts)` 应当原样返回输入（顺序相同、对象相同），`uv run pytest tests/unit/api tests/integration/test_scalar.py -q` 应当全部通过。
4. `_FORK_DISABLED_MOUNTS` 中的每个引用应当始终指向 `build_app` 在集合为空时确实会挂载的 router。单测对集合中每一项检查：清空集合后，该 router 的路径出现在 `app.routes` 中。
5. 在本 spec 合入时，`src/octop/api/app.py` 相对基线的改动应当只有一行 import 与 `_mount_routers` 循环头一行：`git diff --numstat 757fd12 -- src/octop/api/app.py` 输出 `2	1`。

### 需求 5：连接器目录的 fork 删除集与追加项

**用户故事：** 作为负责连接器的 spec 作者，我希望在 fork 自有模块里声明"要隐藏的上游 kind"与"要追加的行内条目"，以便删除 21 个公网 SaaS 连接器或新增行内连接器时，不再编辑 `catalog.py` 里 435 行的 `_CATALOG` 元组。

#### 验收标准

1. 当 `_FORK_REMOVED` 含某个上游 kind 时，`list_catalog()`、`get_catalog_entry(kind)`、`mcp_oauth_remote_kinds()` 以及 `GET /api/connectors/catalog` 应当不再返回该条目。
2. 当 `_fork_entries()` 返回条目时，`list_catalog()` 应当把它们排在全部上游条目之后返回，`get_catalog_entry(<fork kind>)` 应当返回对应条目。
3. 如果 `_FORK_REMOVED` 含上游 `_BASE` 中不存在的 kind，或者合成后的目录出现重复 kind，那么 `tests/unit/connectors/test_catalog_intranet.py` 应当失败，并指出具体 kind。
4. 在 `_FORK_REMOVED` 与 `_fork_entries()` 都为空期间，`list_catalog()` 应当与基线逐条相同（23 条，顺序不变），`uv run pytest tests/unit/test_connectors.py tests/integration/test_connectors_api.py -q` 应当全部通过。
5. `octop.infra.connectors.catalog_intranet` 与 `octop.infra.connectors.catalog` 应当始终可以按任意顺序在全新解释器里首次导入，不出现循环导入错误（子进程分别按两种顺序导入并调用 `list_catalog()`，退出码为 0）。

### 需求 6：`make relock`

**用户故事：** 作为执行上游同步的维护者，我希望锁文件冲突时一律取上游版本，再用一条 `make relock` 按当前清单在指定 registry 上重生成两份锁文件，以便不再手工修补 `uv.lock` 与 `dashboard/package-lock.json`。

#### 验收标准

1. 当执行 `make relock` 时，Makefile 应当先执行 `uv lock`，再在 `dashboard/` 下执行 `npm install --package-lock-only --ignore-scripts --no-audit --no-fund`，重生成 `uv.lock` 与 `dashboard/package-lock.json`。任一步失败时 make 以非零退出码结束。
2. 当 `PYPI_INDEX=<url>` 或 `NPM_REGISTRY=<url>` 通过命令行或环境变量给出时，`make relock` 应当分别以 `--default-index <url>` 与 `--registry=<url>` 传给 uv 与 npm。变量为空时不传该参数，沿用 uv 默认值与 `dashboard/.npmrc`。由 `make -n relock PYPI_INDEX=… NPM_REGISTRY=…` 的输出验证。
3. 如果执行环境中没有 `uv`，那么 `make relock` 应当以退出码 2 失败并提示需要 uv，而不是退回 pip。
4. 在清单未变且使用默认 registry 期间，`make relock` 应当不改变两份锁文件：执行后 `git diff --exit-code -- uv.lock dashboard/package-lock.json` 的退出码为 0。
5. `make relock` 自身打印的 `[relock]` 提示行应当始终只显示 `<PYPI_INDEX>` / `<NPM_REGISTRY>` 占位符，不回显 registry URL（URL 里可能带凭据）；`make help-intranet` 应当列出 `relock` 及其两个变量。

### 需求 7：fork 专属的变更记录与 API 差异文档

**用户故事：** 作为 fork 维护者，我希望 fork 的变更与 API 差异写在 fork 自己的文件里，以便上游 `CHANGELOG.md` 与 `docs/api.md` 在同步时可以一律取上游版本。

#### 验收标准

1. 仓库根目录应当存在 `CHANGELOG-intranet.md`，包含 `## [Unreleased]` 与"新增 / 变更 / 移除 / 安全"分类、一张"上游同步记录"表（首行记录基线 `757fd12`），以及 `w0-01`、`w0-02`、`w0-03`、`w0-04` 的条目，每条以 spec 目录名开头。
2. 应当存在 `docs/api-intranet.md`，包含六节：已下线的上游路由（`_FORK_DISABLED_MOUNTS`）、已物理删除的上游路由、fork 新增或变更的端点、鉴权与权限差异、fork 新增错误码、连接器目录差异。暂无内容的节写"暂无"。
3. `docs/api.md` 的前 5 行应当始终包含一行指向 `api-intranet.md` 的指针；在本 spec 合入时，`git diff --numstat 757fd12 -- docs/api.md` 输出 `2	0`（一行指针加一个空行，没有删除行）。
4. 本 spec 应当始终不修改 `CHANGELOG.md`：`git diff --stat 757fd12 -- CHANGELOG.md` 输出为空。

### 需求 8：上游同步手册

**用户故事：** 作为执行上游同步的维护者，我希望有一份可以逐条照做的手册，覆盖从 shallow clone 恢复完整历史、确定同步目标、处理冲突到同步后核对的全过程，以便每 2-4 个上游 release 的同步可以由任何一名维护者在半天内完成。

#### 验收标准

1. `docs/intranet/upstream-sync.md` 应当依次覆盖以下内容：原则（长期 fork 加隔离点，放弃补丁清单）；一次性准备（`git fetch --unshallow`、`git remote add upstream …`、`git fetch upstream --tags`）；同步节奏（每 2-4 个上游 release，约 5-10 天）与同步目标（main 上的 `v*` tag）；hotfix 例外通道；逐步同步流程；按文件分类的冲突处理规则；同步后核对清单；验证命令；churn 测量方法；失败回退。
2. 当维护者在能访问上游的环境里执行手册"一次性准备"一节的命令后，`git rev-parse --is-shallow-repository` 应当输出 `false`，`git tag -l 'v*'` 应当输出非空。
3. 手册的冲突规则应当至少覆盖：`uv.lock` / `dashboard/package-lock.json` 取上游后执行 `make relock`；上游四份 locale JSON、`CHANGELOG.md`、`docs/api.md` 取上游（`docs/api.md` 保留指针行）；`src/octop/infra/errors.py` 中 fork 新码保持在枚举末尾与 `_DEFAULT_STATUS` 末尾；`manager.py`、`processor.py`、`migrate.py` 只保留单行调用；`ci.yml` 不得整体取上游，根 `Makefile` 的 `include Makefile.intranet` 行必须保留。
4. 手册的同步后核对清单应当包含：四处隔离点钩子仍在（由契约测试与行为测试保证）；`run_migrations` 末尾的 fork 调用仍在；上游新增的 `NNN_` 迁移与 fork 表、列不重名；`_FORK_DISABLED_MOUNTS` 与 `_FORK_REMOVED` 仍指向存在的对象；执行 `make all`、`make check-frontend`，以及设置 DSN 后的 `make test-postgresql`；在 `CHANGELOG-intranet.md` 的同步记录表里登记本次同步。
5. 手册中的 churn 测量应当统一使用 `git log --full-history --no-merges` 口径，并给出"某个上游窗口命中 fork 改动面多少文件"的可执行命令。手册中的所有命令应当始终可以直接执行：不写裸 `pytest`，不用 `rg --include`。

### 需求 9：AGENTS.md 勘误

**用户故事：** 作为在本仓库工作的 AI 代理或新成员，我希望 AGENTS.md 引用的路径都真实存在，i18n 清单与 fork 规则一致，以便按导航找到正确的文件，并且新增文案时不会写进上游 bundle。

#### 验收标准

1. 当执行 `rg -n 'jwt_tokens|_cmd\.py|api/errors\.py|gateway/processor\.py|agents/runtime\.py|routers/chat\.py' AGENTS.md` 时，应当没有任何输出。
2. §5、§8、§9 中本 spec 改写或新增的每个路径都应当在仓库中存在（由任务中的检查脚本逐一验证）。
3. §7 "Adding strings (checklist)" 应当新增一条 fork 规则：新增文案写进两对 intranet overlay，不写进、也不删除上游 bundle 的键。§9 应当新增一行，指向 `docs/intranet/upstream-sync.md`、`CHANGELOG-intranet.md` 与 `docs/api-intranet.md`。
4. 本 spec 对 AGENTS.md 的改动应当始终不触及 §7 的 Database 段（该段归 `w0-01`）：`git diff -U0 757fd12 -- AGENTS.md` 中没有落在 Database 段内的 hunk。

### 需求 10：隔离点的同步守卫

**用户故事：** 作为执行上游同步的维护者，我希望合并冲突时误删任一隔离点钩子后，`make test` 在 Linux 和 Windows 上都会变红，以便钩子不会在某次同步里悄悄消失。

#### 验收标准

1. 如果 `dashboard/src/i18n.ts` 不再从 `./i18nIntranet` 导入，或 `applyIntranetOverlay(` 少于 2 处，那么 `tests/unit/test_fork_isolation_contract.py` 应当失败。
2. 如果 `Makefile.intranet` 不再以行首 `relock:` 定义目标，或 `docs/api.md` 前 5 行不再包含 `api-intranet.md`，那么同一测试文件应当失败。
3. 如果 `_load_all` 不再应用 overlay、`_mount_routers` 不再过滤、`_CATALOG` 不再由 `_BASE` 合成，那么需求 1.2、4.1、5.1 对应的行为用例应当失败。
4. 契约测试应当始终与平台无关：只以 `encoding="utf-8"` 读取仓库文本文件，用 `pathlib` 拼路径，不调用 `make`、`npm` 或网络，在 `make test` 的 Linux 与 Windows job 中都通过。
