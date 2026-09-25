# 需求文档：测试鉴权基线

> spec：`w0-03-test-auth-baseline` ｜ 波次：Wave 0 ｜ 基线：`757fd12` ｜ 预估：3.25 人日
> 前置：无 ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 引言

**结论：** 本 spec 一次性改造测试侧的共享鉴权夹具，不改 `src/` 下任何文件，交付四件事：

1. `bootstrap_admin` 建出的管理员在库里显式持有全部权限键。
2. 验证码的测试豁免只靠 `monkeypatch` 实现，只在测试进程里生效，验证码专项测试可以退出豁免。
3. 为后续的重认证类依赖预留 `app.dependency_overrides` 注册点。
4. 按"系统管理员 / 安全管理员 / 审计管理员"三个槽位预留管理员凭据的形状。

合入时，既有测试一行不改，全部通过。

### 背景

- `tests/support/auth.py` 是唯一的共享鉴权夹具模块。实测有 28 个文件直接引用它：26 个测试模块，加上 `tests/integration/conftest.py` 与 `tests/support/scenarios.py`。
- `tests/integration/conftest.py` 的基础夹具 `env` 调用 `bootstrap_admin` 与 `auth_header`，13 个派生夹具都链式依赖它。按 AST 统计，约 51 个集成测试文件经这条链拿到管理员令牌。另有 12 个测试文件直接调用 `bootstrap_admin`。
- 已核实 `src/octop/api/routers/setup.py` 的 `initial_admin` 在调用 `user_manager.create(...)` 时不传 `permissions=`，所以初始管理员在库里的 `permissions` 是 `[]`，全靠 `permissions.py` 里 `user_has_permission` 的 `is_admin` 短路拿到权限。已实测：把该判定换成忽略 `is_admin` 的严格版本后，`env` 夹具的管理员访问 `/api/users`、`/api/admin/providers`、`/api/admin/audit-log` 全部返回 403。
- 登录验证码是 `api/routers/auth.py::login` 里的内联调用 `ensure_captcha(...)`，不是 FastAPI 依赖。除 `tests/support/auth.py::login()` 外，还有 10 个测试文件共 31 处直接 `POST /api/auth/login`。只改 `login()` 辅助函数，覆盖不到这些调用。

### 为什么做

全局约束 1.4 规定：测试鉴权基线是共同验证前提，必须先于任何动权限、验证码、会话的生产代码合入。不先交付它，就会出现以下情况：

- `w3-03` 删除 admin 绕过的那一刻，约 51 个集成文件同时变红，失败信息全部指向 403，而不是真实缺陷。
- `w3-01` 把本地图形验证码设为默认后，所有走密码登录的测试（含 31 处裸调用）都会收到 `CAPTCHA_REQUIRED`。
- `w3-03` 把 `/setup/initial-admin` 改成三账号时，需要改的地方散落在 28 个文件里。

四个 spec 各改一次同一个文件，就是三次返工加一次合并冲突。

### 范围内

1. `tests/support/auth.py`：
   - `bootstrap_admin` 在 `/api/setup/finish` 之后，通过 `PATCH /api/users/{id}` 授予 `sorted(ALL_PERMISSION_KEYS)`；
   - 新增 `all_permission_keys()`、`ADMIN_SLOTS`、`TEST_ADMIN_ACCOUNTS`、`AdminCredentials`、`bootstrap_admins()`。
2. 新增 `tests/support/auth_guards.py`，集中放测试进程专用的护栏豁免：`CAPTCHA_SEAMS`、`DEPENDENCY_OVERRIDES`、`REAL_AUTH_GUARD_MODULES`、`captcha_exempt`、`wants_real_guards`、`relax_auth_guards`、`apply_test_dependency_overrides`。
3. `tests/conftest.py`：
   - 在 `pytest_configure` 里注册 `real_auth_guards` 标记；
   - 新增 autouse 夹具 `_relax_auth_guards`。
4. `tests/support/app.py::octop_client` 与 `tests/integration/conftest.py::env_terminal`：在 `build_app` 之后应用登记的依赖替身。
5. `tests/integration/conftest.py`：
   - 新增 `env_admins` 夹具，`env` 改为从它派生；
   - 夹具内部的建账与查账调用改走 `security` 槽位；
   - `tests/support/scenarios.py::bootstrap_boundary_env` 增加仅限关键字参数 `user_admin_auth`。
6. 新增自测：
   - `tests/integration/test_auth_baseline.py`；
   - `tests/unit/api/test_auth_guard_exemptions.py`（含"生产代码无豁免开关"不变式）。

### 范围外（归属）

- **生产侧的 admin 权限回填、删除 14 处后端绕过、三员互斥角色、`/setup/initial-admin` 改为三账号、存量 `users.permissions` 清洗、CLI 离线授权：** 归 `w3-03`。源分析 S08 的 `016` 回填迁移已被全局约束 1.1 否决，改由 `w3-03` 用 `forkNNN_<描述>` 实现。
- **迁移 5 个 setup 契约测试文件里 19 处裸 `/api/setup/initial-admin` 调用，以及处理 21 个直接创建 `Role.ADMIN` 用户的单元测试文件：** 归 `w3-03`。本 spec 只登记清单，见 design.md "与其他 spec 的交接"。
- **本地图形验证码本身、限流、可信代理、上传杀毒，以及它们在 `octop_client` 里的测试默认值：** 归 `w3-01`。源分析 S14 changes 中给 `tests/support/app.py` 加 `rate_limit` / `upload_scan` / `trusted_proxies` / `client_addr` 的条目，也归 `w3-01`。
- **云验证码 provider 删除（含 `test_captcha_api.py` 中云 provider 用例的去留）：** 归 `w1-05`。
- **会话表、短时令牌、吊销、令牌移出 URL、口令策略：** 归 `w3-04`。
- **高危操作重认证的 `/api/auth/reauth` 与 `require_reauth` 依赖：** 按源分析 S22 归 `p2-07`。本 spec 只提供注册点，不为尚不存在的生产依赖写替身。
- **CI 前端 job 与 postgres service：** 归 `w0-02`。本 spec 不新增 vitest 或 PG 用例。
- **AGENTS.md §9 "Test layout & shared helpers" 一行的补充，以及 `CHANGELOG-intranet.md` 的建立：** 归 `w0-04`。

## 需求

### 需求 1：管理员显式持有全量权限键

**用户故事：** 作为删除 admin 绕过的 `w3-03` 的实施者，我希望共享夹具建出的管理员在库里显式持有全部权限键，以便删掉绕过之后，集成测试验证的仍然是业务逻辑，而不是一律返回 403。

#### 验收标准

1. 当测试调用 `bootstrap_admin(client, home)` 时，`bootstrap_admin` 应当在 `/api/setup/finish` 成功后把该管理员的 `permissions` 设为 `sorted(ALL_PERMISSION_KEYS)`。传入自定义 `username` / `password` 时同样生效。经 `GET /api/users/{id}` 读回的 `permissions` 应当与之逐项相等。
2. 当 `octop.api.deps.user_has_permission` 被 monkeypatch 为忽略 `is_admin` 的严格判定时，用 `env` 夹具产出的管理员鉴权头访问 `GET /api/admin/providers`、`GET /api/users`、`GET /api/admin/audit-log`，应当全部返回 200。基线下这三个请求都返回 403。
3. `tests/support/` 应当始终在运行期从 `ALL_PERMISSION_KEYS` 计算键集，不以字面量硬编码权限键名：`rg -n '"(admin_console|storage_backends|knowledge_settings|ollama_models)"' tests/support` 无输出。
4. 如果授予步骤的 `PATCH /api/users/{id}` 返回非 2xx，那么 `bootstrap_admin` 应当抛出 `httpx.HTTPStatusError`，让依赖它的夹具在建立阶段就失败，而不是带着空权限继续运行。
5. `bootstrap_admin` 的签名与返回值应当始终保持不变：仍然返回 `/api/setup/initial-admin` 的响应对象，`status_code == 201`，响应体含 `id` 与 `access_token`。`test_auth_flow.py`、`test_setup_bootstrap.py`、`test_e2e_golden_path.py` 中对返回值的既有断言无需修改。

### 需求 2：验证码测试豁免只在测试进程内生效

**用户故事：** 作为把本地图形验证码设为默认的 `w3-01` 的实施者，我希望既有测试的密码登录在测试进程内自动免验证码，同时验证码专项测试仍然走真实校验，以便验证码上线时不会打死整个套件，生产环境也不会留下后门。

#### 验收标准

1. 在未标记 `real_auth_guards`、且所在模块不在 `REAL_AUTH_GUARD_MODULES` 中的测试运行期间，`CAPTCHA_SEAMS` 的每个目标（基线仅 `octop.api.routers.auth.ensure_captcha`）应当被 monkeypatch 为 `tests.support.auth_guards.captcha_exempt`。
2. 当测试标记了 `@pytest.mark.real_auth_guards`，或位于 `REAL_AUTH_GUARD_MODULES`（基线仅含 `tests/integration/test_captcha_api.py`）时，豁免不应生效，`CAPTCHA_SEAMS` 应当解析到原函数。此时把该 seam 替换为抛出 `CAPTCHA_REQUIRED` 的桩，`POST /api/auth/login` 应当返回 400 且 `error.code == "CAPTCHA_REQUIRED"`，以此证明该 seam 位于真实的登录路径上。
3. 如果 `CAPTCHA_SEAMS` 中任一目标在代码中无法解析（例如后续 spec 移动了登录路由里的验证码调用），那么 `tests/unit/api/test_auth_guard_exemptions.py::test_captcha_seams_resolve` 应当失败。
4. 如果 `REAL_AUTH_GUARD_MODULES` 中列出的模块文件不存在，那么 `test_real_guard_modules_exist` 应当失败，提示维护该清单。
5. `src/octop` 应当始终不包含验证码或重认证的豁免开关。具体由单测 `test_no_production_exemption_switch` 固化为三条：
   - `OctopConfig` 没有字段名匹配 `(bypass|exempt|skip)_?(captcha|reauth)` 或其反序；
   - `src/octop`（不含 `src/octop/dashboard/`）下任何 `.py` 文件都不引用 `tests.support`，也不含上述模式；
   - `rg -n -i "(bypass|exempt|skip)_?(captcha|reauth)|(captcha|reauth)_?(bypass|exempt|skip)" src/octop` 无输出。

### 需求 3：依赖级测试豁免注册点

**用户故事：** 作为引入高危操作重认证依赖（`require_reauth`）的 spec 的实施者，我希望已经有一个只在测试进程生效的 `dependency_overrides` 注册点，以便新增依赖时只需登记一行，既有测试就不受影响。

#### 验收标准

1. 当 `DEPENDENCY_OVERRIDES` 中登记了 `{dep: replacement}`、且当前测试未退出豁免时，`octop_client` 构造的应用与 `env_terminal` 夹具构造的应用，其 `app.dependency_overrides` 都应当包含该映射。
2. 在标记 `real_auth_guards` 的测试运行期间，`apply_test_dependency_overrides(app)` 应当不向 `app.dependency_overrides` 写入任何映射。
3. 当用一个抛出 403 的依赖构造最小 FastAPI 应用、并在 `DEPENDENCY_OVERRIDES` 中登记放行替身时，经 `apply_test_dependency_overrides` 处理后，请求应当返回 200；退出豁免时应当返回 403。
4. 当本 spec 合入时，`DEPENDENCY_OVERRIDES` 应当是空字典：本 spec 不为 `src/` 中尚不存在的依赖写任何替身，替身由引入该依赖的 spec 登记。

### 需求 4：为三员分立预留管理员凭据形状

**用户故事：** 作为实施三员分立的 `w3-03` 的实施者，我希望共享夹具已经按系统管理员、安全管理员、审计管理员三个槽位提供凭据，夹具内部的建账调用也已固定走某个槽位，以便三账号上线时只改 `tests/support/auth.py` 一处。

#### 验收标准

1. 当测试请求 `env_admins` 夹具时，它应当产出 `(client, srv, AdminCredentials)`。`AdminCredentials` 含 `system`、`security`、`audit` 三个 Authorization 头，以及键集等于 `ADMIN_SLOTS` 的 `usernames` 映射。用每个槽位的头访问 `GET /api/auth/me`，返回的 `username` 应当等于 `usernames[slot]`。
2. 在 `w3-03` 合入之前，三个槽位应当始终指向同一个由 `bootstrap_admin` 建出的全量键管理员：`TEST_ADMIN_ACCOUNTS` 三项相同，均为 `("admin", TEST_PASSWORD)`。
3. 当同一测试同时请求 `env` 与 `env_admins` 时，二者应当共享同一个 `OctopServer` 实例，`env` 产出的鉴权头应当等于 `env_admins` 的 `system` 槽位。
4. `tests/integration/conftest.py` 中夹具内部的用户管理调用应当始终经 `security` 槽位发出，包括：`env_alice_bob_agent` 的 `ensure_users`、`env_admin_alice` 的 `create_user`、`env_usage` 的 `resolve_user_id`、`env_boundary` 经 `bootstrap_boundary_env` 的建账与查账。静态检查：`rg -c "env_admins\[2\]\.security" tests/integration/conftest.py` 输出 4。`bootstrap_boundary_env` 新增仅限关键字参数 `user_admin_auth`：传入时，`create_user` 与 `resolve_user_id` 收到的正是该对象；缺省时回落到 `admin_auth`。

### 需求 5：既有测试零修改通过，并登记交付

**用户故事：** 作为 fork 维护者，我希望本 spec 合入时既有测试一行不改就全部通过，并且新夹具契约有据可查，以便新基线本身不引入回归，后续 spec 出现红灯时只可能来自它们自己的改动。

#### 验收标准

1. 当本 spec 合入时，`git diff --name-only --diff-filter=M "$BASE" -- tests/` 的输出应当只包含 `tests/conftest.py`、`tests/integration/conftest.py`、`tests/support/auth.py`、`tests/support/app.py`、`tests/support/scenarios.py`。`tests/` 下其余改动只能是新增文件（`$BASE` 为任务 1 记录的提交）。
2. 当运行 `uv run pytest -m "not live" -n auto -q` 时，失败集合应当与任务 1 记录的基线失败集合相同，本 spec 新增的用例全部通过。已知基线在 root 用户下有 `tests/unit/infra/setup/test_service.py` 的 3 个环境性失败。
3. 本 spec 应当始终不改生产代码、前端与依赖：`git diff --name-only "$BASE" -- src dashboard pyproject.toml uv.lock` 无输出。
4. 当在非 root 用户下运行 `make all` 时，结果应当全绿，其中 `ruff check src tests` 与 `ruff format --check src tests` 覆盖本 spec 新增与修改的测试文件。
5. 当本 spec 合入时，新夹具契约（`env_admins`、`AdminCredentials`、`real_auth_guards`、`REAL_AUTH_GUARD_MODULES`、`CAPTCHA_SEAMS`、`DEPENDENCY_OVERRIDES`）应当已登记：若 `w0-04` 已建立 `CHANGELOG-intranet.md`，写进该文件；否则写进 PR 描述，由 `w0-04` 补录。
