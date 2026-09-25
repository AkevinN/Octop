# 上游同步手册

适用于行内 fork 从上游 `https://github.com/TencentCloud/Octop` 合入新版本。命令中的 `<…>` 是占位符；命令在 bash（Windows 上用 Git Bash）中执行。

## 1. 原则

- 长期 fork 分支加隔离点；放弃"vendor 镜像分支 + 补丁清单"（`.kiro/steering/intranet-transformation.md` 第 5 节，对应待确认项 D7）。
- fork 的改动尽量写进 fork 自有文件，上游文件里只留钩子：

| 隔离点 | 上游文件里的钩子 | fork 自有文件 |
|---|---|---|
| 后端文案 | `src/octop/i18n/loader.py::_load_all` 的 overlay 合并 | `src/octop/i18n/overlay.py`、`src/octop/i18n/intranet/{en,zh}.json` |
| 前端文案 | `dashboard/src/i18n.ts` 的 1 行 import 与 2 处 `applyIntranetOverlay(...)` | `dashboard/src/i18nIntranet.ts`、`dashboard/src/locales/intranet/{en,zh}.json` |
| 路由下线 | `src/octop/api/app.py::_mount_routers` 的 `without_fork_disabled(...)` | `src/octop/api/intranet_mounts.py`（`_FORK_DISABLED_MOUNTS`） |
| 连接器目录 | `src/octop/infra/connectors/catalog.py` 的 `_CATALOG = compose_catalog(_BASE)` | `src/octop/infra/connectors/catalog_intranet.py`（`_FORK_REMOVED`、`_fork_entries()`） |
| 迁移 | `src/octop/infra/db/migrate.py::run_migrations` 末尾的 fork 调用 | `src/octop/infra/db/fork_migrate.py`、`forkNNN_*.sql` |
| 构建与 CI | 根 `Makefile` 的 `include Makefile.intranet`；`ci.yml` 的 `frontend` / `postgresql` job | `Makefile.intranet` |
| 文档 | `docs/api.md` 第 3 行的指针 | `CHANGELOG-intranet.md`、`docs/api-intranet.md`、本手册 |

## 2. 一次性准备

按顺序执行：

```bash
git rev-parse --is-shallow-repository   # 输出 true 时继续下一步
git fetch --unshallow origin
git remote add upstream https://github.com/TencentCloud/Octop.git   # 行内环境换成上游镜像地址
git fetch upstream --tags
git merge-base --is-ancestor 757fd12 upstream/main && echo baseline-on-upstream
git rev-parse --is-shallow-repository   # 期望 false
git tag -l 'v*'                          # 期望非空
```

fork 基线 `757fd12` 就是上游 tag `v1.0.1`。首次同步前按第 9 节在完整历史上重测 churn，结果登记进 `CHANGELOG-intranet.md` 的"上游同步记录"表。

## 3. 同步节奏与目标

- 每 2-4 个上游 release（约 5-10 天）同步一次。依据是全局约束第 5 节的实测：1 个 release 命中 66 个 fork 文件，4 个 release 仅 81 个，13 个 release（约一个月）骤增到 203 个。
- 同步目标只取 main 上的正式版 `v*` tag，跳过 `v1.0.2b1` 这类预发布 tag。列出候选：

```bash
git tag -l 'v*' --merged upstream/main --sort=-v:refname | grep -Ev '[a-z][0-9]+$' | head -5
```

- 上次同步点以 `CHANGELOG-intranet.md` 同步记录表的最后一行为准。

## 4. hotfix 例外通道

- 发现：`git log --first-parent --merges --oneline --grep '/hotfix/' <上次同步点>..upstream/main`
- 触发条件：安全、构建、锁文件、数据损坏类热修；其余热修等下次跟 tag。
- 接入：如果 `git merge-base --is-ancestor <hotfix 合并提交>^1 HEAD` 成立（fork 已含其第一父），执行 `git merge --no-ff <hotfix 合并提交>`；否则执行 `git cherry-pick -x -m 1 <hotfix 合并提交>`。
- 下次跟 tag 时照常合并；与 cherry-pick 重复的改动通常自动消解，冲突时取上游。
- 同样登记进同步记录表，方式写"hotfix"。

## 5. 同步流程

1. `git switch -c sync/upstream-<tag> <fork 主干>`
2. `git merge --no-ff <tag>`
3. 按第 6 节解冲突，`git add` 后 `git commit`。
4. `make relock`（行内加 `PYPI_INDEX=<url> NPM_REGISTRY=<url>`），锁文件单独一个提交。
5. 按第 7 节核对、第 8 节验证。
6. 发 PR 合入 fork 主干，使用 merge commit，不要 squash。
7. 在 `CHANGELOG-intranet.md` 的同步记录表登记本次同步。

## 6. 冲突处理规则

| 文件 | 规则 |
|---|---|
| `uv.lock`、`dashboard/package-lock.json` | `git checkout --theirs -- <file>`，之后执行 `make relock PYPI_INDEX=<url> NPM_REGISTRY=<url>`，单独提交 |
| `src/octop/i18n/{en,zh}.json`、`dashboard/src/locales/{en,zh}.json` | 取上游。冲突里如果出现 fork 的改动，说明违反了全局约束 1.2，把它挪进 intranet overlay |
| `CHANGELOG.md` | 取上游；fork 变更只写 `CHANGELOG-intranet.md` |
| `docs/api.md` | 取上游，但保留第 3 行指向 `api-intranet.md` 的指针行 |
| `src/octop/infra/errors.py` | 两边都保留；fork 新码始终在 `ErrorCode` 枚举末尾与 `_DEFAULT_STATUS` 末尾 |
| `src/octop/infra/agents/manager.py`、`src/octop/infra/gateway/process/processor.py`、`src/octop/infra/db/migrate.py` | 取上游，再把 fork 的单行调用补回原位置；不接受多于单行的 fork 逻辑 |
| `loader.py`、`i18n.ts`、`app.py::_mount_routers`、`catalog.py` 的 `_CATALOG` | 取上游，再补回第 1 节表中的钩子行 |
| `.github/workflows/ci.yml`、根 `Makefile` | 不得整体取上游；保留 fork 的 `frontend` / `postgresql` job 与 `include Makefile.intranet` 行 |
| `pyproject.toml` | 两边都保留；上游多在文件尾追加 `[[tool.mypy.overrides]]` |
| 上游删除了 overlay 覆盖的键 | overlay 里的该键成为孤儿，合法；不再需要时从 overlay 删除 |

## 7. 同步后核对清单

- [ ] 四处隔离点钩子仍在：`tests/unit/test_fork_isolation_contract.py`（非 Python 钩子）与 i18n / 路由 / 连接器行为用例（第 8 节）全绿。
- [ ] `run_migrations` 末尾的 fork 调用仍在（`tests/unit/db/test_fork_migrate.py::test_run_migrations_ends_with_fork_runner`）。
- [ ] 上游新增的 `NNN_` 迁移与 fork 的表、列不重名。列出新增迁移：`git diff --name-only <旧 tag> <新 tag> -- src/octop/infra/db/migrations`
- [ ] `_FORK_DISABLED_MOUNTS` 与 `_FORK_REMOVED` 仍指向存在的对象（`test_intranet_mounts.py`、`test_catalog_intranet.py`），overlay 与上游没有形状冲突（`test_intranet_overlay.py`）。
- [ ] `ci.yml` 中 fork 的 `frontend` / `postgresql` 两个 job 与根 `Makefile` 的 `include Makefile.intranet` 行仍在。
- [ ] 第 8 节的 `make all`、`make check-frontend` 与设置 DSN 后的 `make test-postgresql` 全绿。
- [ ] 在 `CHANGELOG-intranet.md` 的同步记录表登记本次同步。

## 8. 验证命令

```bash
make install-frontend && make all
make check-frontend
OCTOP_TEST_DATABASE_URL=<专用库 DSN> make test-postgresql
uv run pytest tests/unit/i18n tests/unit/test_fork_isolation_contract.py tests/unit/api/test_intranet_mounts.py tests/unit/connectors/test_catalog_intranet.py tests/integration/test_connectors_catalog_intranet.py -q
uv lock --check
```

## 9. churn 测量

统一使用 `git log --full-history --no-merges` 口径（与全局约束第 5 节一致；shallow clone 上的数字只是下限）。

```bash
# 单文件
git log --full-history --no-merges --oneline <from>..<to> -- <path> | wc -l
# 上游窗口内的热点文件
git log --full-history --no-merges --format= --name-only <旧 tag>..<新 tag> | sort | uniq -c | sort -rn | head -30
# 上游窗口命中 fork 改动面的文件数（在 fork 主干上执行）
comm -12 <(git log --full-history --no-merges --format= --name-only <旧 tag>..<新 tag> | sort -u) \
  <(git log --full-history --no-merges --format= --name-only <旧 tag>..HEAD | sort -u) | wc -l
```

## 10. 失败回退

- 同步合并尚未提交：`git merge --abort`。
- 已合入 fork 主干：`git revert -m 1 <同步合并提交>`，再按第 5 节重做。

凭据不要写进 `PYPI_INDEX` / `NPM_REGISTRY` 的 URL，改用 uv 的 `UV_INDEX_*` 凭据环境变量、netrc 或用户级 `.npmrc`。提交锁文件前确认其中没有内嵌凭据：`! grep -nE '://[^/@ ]+:[^/@ ]+@' uv.lock dashboard/package-lock.json`
