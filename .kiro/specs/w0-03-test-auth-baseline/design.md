# 设计文档：测试鉴权基线

> spec：`w0-03-test-auth-baseline` ｜ 波次：Wave 0 ｜ 基线：`757fd12` ｜ 预估：3.25 人日
> 前置：无 ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 概述

本 spec 只改 `tests/`，不碰 `src/`、`dashboard/` 和依赖清单。做法分四块：

1. **管理员显式全量键。** 在 `bootstrap_admin` 的 `finish` 之后，用 `initial-admin` 返回的令牌调用 `PATCH /api/users/{id}`，把 `permissions` 设为运行期算出的 `sorted(ALL_PERMISSION_KEYS)`。
2. **验证码豁免。** 根 `tests/conftest.py` 新增一个 autouse 夹具，默认把登录路由绑定的 `ensure_captcha` monkeypatch 成空操作。退出豁免有两种方式：给用例打 `real_auth_guards` 标记，或把模块登记进 `REAL_AUTH_GUARD_MODULES`。
3. **依赖级豁免注册点。** 新增 `DEPENDENCY_OVERRIDES` 注册表，由 `octop_client` 与 `env_terminal` 在 `build_app` 之后写入 `app.dependency_overrides`。基线的注册表为空。
4. **三员形状。** 新增 `AdminCredentials(system, security, audit, usernames)` 与 `env_admins` 夹具。三个槽位在 `w3-03` 之前都是同一个全量键管理员的别名。夹具内部的建账调用固定走 `security` 槽位。

方案已在仓库副本上做过原型验证，结果如下：

- 按上述改动修改 5 个夹具文件，并加入两个新测试文件；
- `tests/integration` 与 `tests/unit/api` 全量 794 个用例通过，12 个跳过；
- 其余 `tests/unit` 的失败只有基线本来就有的 3 个 root 环境性失败。

## 现状

以下事实都在基线仓库里用 `rg` / `sed -n` / AST 统计或运行探针核实过。

### 共享夹具 `tests/support/auth.py`

- 模块提供 `TEST_PASSWORD` 与 11 个辅助函数：`wizard_token`、`bootstrap_admin`、`login`、`bearer`、`auth_header`、`seed_openai_provider`、`create_agent`、`create_user`、`ensure_users`、`resolve_user_id`、`create_provider`。
- `bootstrap_admin`（≈L32-56）依次调用三个接口：`/api/setup/verify-password` → `/api/setup/initial-admin`（≈L44-48）→ `/api/setup/finish`（≈L50-55），最后返回 `initial-admin` 的响应对象。有 3 个文件断言 `r.status_code == 201`：`test_auth_flow.py` ≈L21-22、`test_setup_bootstrap.py` ≈L21-22 与 ≈L72-73、`test_e2e_golden_path.py` ≈L28-29。
- `login`（≈L59-67）只发送 `{username, password}`，不带任何验证码字段；`auth_header`（≈L74-80）在它外面包一层。
- `create_user`（≈L129-154）默认 `permissions = sorted(BASELINE_PERMISSIONS)`（4 个 settings 类键，≈L144-146）。

### 依赖面（实测）

- **直接引用：** `rg -l "tests\.support\.auth" tests` 命中 28 个文件，包括 26 个测试模块、`tests/integration/conftest.py` 和 `tests/support/scenarios.py`。
- **直接调用 `bootstrap_admin` 的测试文件（12 个）：**
  - 集成测试 11 个：`test_auth_flow`、`test_auth_oauth`、`test_auth_oidc`、`test_captcha_api`、`test_chat_ws`、`test_connectors_api`、`test_e2e_golden_path`、`test_notifications_ws`、`test_scalar`、`test_setup_bootstrap`、`test_setup_database`；
  - 单元测试 1 个：`tests/unit/api/test_jwt_auth_middleware.py`。
- **`tests/integration/conftest.py` 的夹具链：**
  - `env`（≈L54-62）在 `octop_client` 内调用 `bootstrap_admin`（≈L60）与 `auth_header`（≈L61）。
  - 派生夹具内部的用户管理调用有四处：`env_alice_bob_agent` 的 `ensure_users`（≈L128）、`env_admin_alice` 的 `create_user`（≈L150）、`env_usage` 的 `resolve_user_id`（≈L161）、`env_boundary` 的 `bootstrap_boundary_env`（≈L179）。
  - `env_terminal`（≈L224-231）另外调用一次 `build_app(srv)`，得到第二个应用。
  - 用 AST 统计测试函数参数：54 个集成文件使用 `env` 链上的夹具名。其中 `test_chat_ws`、`test_notifications_ws`、`test_e2e_golden_path` 自建 `env`，所以经 conftest `env` 链取得管理员令牌的约为 **51 个文件**。源分析写的"约 28 个 / 约 35 个"偏低。
- **源分析勘误：** conftest 的 `__all__`（≈L30-33）只列了 `bootstrap_admin` 与 `patch_harness`，全仓没有任何文件从 `tests.integration.conftest` 导入。源分析说它"重导出 `auth_header`"，与事实不符。
- **`tests/support/scenarios.py::bootstrap_boundary_env`（≈L13-55）** 用同一个 `admin_auth` 建 provider、建 alice 与 bob、查用户 id、建 agent。
- **裸 `/api/setup/initial-admin` 调用：** 5 个文件共 19 处。
  - `test_setup_wizard.py` 12 处（≈L60/72/88/101/196/214/263/280/307/367/407/421）；
  - `test_setup_database.py` 3 处（≈L94/114/141）；
  - `test_setup_bootstrap.py` 2 处（≈L49/75）；
  - `test_auth_flow.py` 1 处（≈L37）；
  - `test_postgresql_control_plane.py` 1 处（≈L277）。
- **裸 `/api/auth/login` 调用：** 除 `tests/support/auth.py` 与只读 OpenAPI 路径的 `test_openapi_meta.py` 外，10 个文件共 31 处：`test_captcha_api` 10、`test_auth_flow` 7、`test_e2e_golden_path` 4、`test_users_api` 3、`test_jwt_auth_middleware` 2，`test_admin_providers`、`test_envs_api`、`test_invites_api`、`test_providers_api`、`test_workspace_api` 各 1。
- **直接调用 `build_app` 的 7 个文件：** `tests/support/app.py`（≈L63）、`tests/integration/conftest.py`（≈L231）、`test_dashboard_serve.py`、`test_scalar.py`、`tests/unit/api/test_openapi_meta.py`、`test_jwt_auth_middleware.py`、`test_exception_handlers.py`。
- **直接创建 `Role.ADMIN` 或 `role="admin"` 用户的测试文件：** 共 21 个（大多是单元测试），它们不经共享夹具。
- **测试密码字面量：** `"TestPass12"` 在 19 个测试文件中出现 101 次。

### 生产侧事实

- **初始管理员不带权限键：** `src/octop/api/routers/setup.py::initial_admin`（≈L341-375）调用 `server.user_manager.create(...)`（≈L355-362）时不传 `permissions=`，`rg -n "permissions" src/octop/api/routers/setup.py` 无命中。`UserManager.create`（`infra/users/manager.py` ≈L122-183）的 `permissions` 缺省为 `None`，最终落库为 `[]`。
- **探针实测：** 基线下 `GET /api/users/{id}` 读回的管理员 `permissions == []`。
- **admin 绕过：** `src/octop/infra/users/permissions.py` 共有 26 个键。
  - `user_has_permission`（≈L225-234）在 ≈L232-233 对 `is_admin` 直接放行；
  - `effective_permissions`（≈L251-255）对 admin 返回全量目录，经 `/api/auth/me` 暴露出去。
  - 因此 `/auth/me` 会掩盖库里的空值，验证"显式持有"必须读 `GET /api/users/{id}`。
- **依赖都是工厂函数：** `src/octop/api/deps.py` 在 ≈L13 按名字导入 `user_has_permission`（所以 monkeypatch 目标是 `octop.api.deps.user_has_permission`）。`require_permission`（≈L201-219）与 `require_admin`（≈L222-230）都是工厂函数，每次调用返回新闭包，`dependency_overrides` 无法以它们为键。
- **探针实测：** 把 `octop.api.deps.user_has_permission` 换成忽略 `is_admin` 的严格判定后，基线 `env` 管理员访问以下三个端点全部返回 403；授予全量键后全部返回 200。
  - `GET /api/users`（`require_permission("users")`，`users.py` ≈L150-152）；
  - `GET /api/admin/providers`（`require_permission("providers")`，`providers.py` ≈L201-203）；
  - `GET /api/admin/audit-log`（`require_permission("admin_console")`，`admin.py` ≈L47-54）。
- **授予通道：** `src/octop/api/routers/users.py::patch_user`（≈L199-239）受 `require_permission("users")` 保护，可以修改 `permissions`。
  - `_assert_can_assign`（≈L83-93）在 ≈L85 对 admin 直接放行；
  - `_assert_not_last_user_manager`（≈L102-123）在新键集含 `users` 时直接返回。
  - `UserManager.set_permissions`（≈L519-537）会同步内存缓存，并写一条 `action="user.set_permissions"`、`actor=ACTOR_ADMIN` 的审计记录。`ACTOR_ADMIN == "_admin"`，定义在 `infra/db/repos/audit.py` ≈L11。
- **验证码是内联调用：** `src/octop/api/routers/auth.py` 在 ≈L11 按名字导入 `ensure_captcha`，`login`（≈L93-117）在 ≈L105 内联调用它，而不是经 `Depends`。
  - `infra/auth/captcha/verify.py::ensure_captcha`（≈L39-49）只在 provider 的 `requires_token` 为真时才抛 `CAPTCHA_REQUIRED`，该码的状态为 400（`infra/errors.py` ≈L212）。
  - 基线默认 provider 是滑块，`requires_token=False`，所以当前只有 `test_captcha_api.py` 会真正触发验证码：它通过 `settings_repo` 启用 turnstile。
- **生产代码里既有的测试 seam：** `verify.py` ≈L25 的 `set_test_siteverify_url` 是一个模块级 setter，不能通过配置打开。它随云 provider 一起由 `w1-05` 处理，本 spec 不动它。
- **重认证依赖尚不存在：** `src/octop` 里没有 `require_reauth` 或 `X-Octop-Reauth`。现有的 `reauth` 字样都属于连接器 OAuth，与本 spec 无关。
- **`dependency_overrides` 已有先例：** `tests/unit/gateway/test_channels_qr.py` ≈L40-41。

### 测试基础设施

- `tests/conftest.py` 已有两个可沿用的约定：
  - 用模块路径集合做分类，如 `_SLOW_TEST_MODULES`（≈L15-28）与 `pytest_collection_modifyitems`（≈L35-39）；
  - autouse 夹具 `_isolated_user_home` 会清除 `OCTOP_CAPTCHA_*` 环境变量（≈L86-92）。
- `pyproject.toml` 用 `markers` 列表登记标记，未启用 `--strict-markers`。`make test` 的命令是 `pytest -n $(PYTEST_JOBS) -m "not live"`（`Makefile` ≈L223-225）。
- mypy 只检查 `src/octop`；`ruff check` 与 `ruff format --check` 覆盖 `tests`。
- wheel 只打包 `src/octop`（`pyproject.toml` ≈L98-99），`tests/` 不随产物分发。
- 在 root 用户下，基线的 `tests/unit/infra/setup/test_service.py` 有 3 个环境性失败（断言 `User=<当前用户>`），与本 spec 无关，任务 1 需要把它们记入基线。

## 方案

### 1. 管理员显式全量键：夹具经 HTTP 授予

在 `bootstrap_admin` 的 `finish.raise_for_status()` 之后追加授予步骤：

```python
grant = await client.patch(
    f"/api/users/{r.json()['id']}",
    json={"permissions": all_permission_keys()},
    headers=bearer(r.json()["access_token"]),
)
grant.raise_for_status()
return r
```

**为什么走 HTTP，不直接写库：**

- `bootstrap_admin` 只有 `client` 与 `home`，拿不到服务器句柄；
- 经真实的 `patch_user` 授予，能同时验证授予通道本身；
- 授予失败会在夹具建立阶段直接报错，定位清楚。

**为什么不采用源分析 S08 的"服务端回填、夹具零改动"：**

- S08 依赖 `016` 迁移与 `impersonate` 键，`016` 已被全局约束 1.1 否决；
- 夹具的"全量键"应当是测试侧的前提，不应依赖被测的生产改动，否则 `w3-03` 回填出错时，测试基线会和被测代码一起错；
- 全局约束 1.4 要求本基线先于任何权限类生产代码合入。

**键集在运行期计算：** 用 `all_permission_keys()` 返回 `sorted(ALL_PERMISSION_KEYS)`，不硬编码键名。这样 `w1-02` / `w1-03` / `w1-05` 删键、`w3-03` 增键时，夹具无需任何改动。

**副作用（已评估）：**

- 每次 bootstrap 会多一条 `user.set_permissions` 审计记录；
- 管理员行的 `permissions` 从 `[]` 变为 26 个键。

基线下没有测试断言管理员行的 `permissions`，也没有测试断言审计条数：`test_personas_admin_api.py` 的审计用例只断言类型与 `limit`。原型全量回归通过。

### 2. 验证码豁免：进程内 monkeypatch，默认生效，按标记或模块退出

**为什么必须在进程级做：** 有 10 个文件共 31 处裸 `POST /api/auth/login` 绕过了 `login()` 辅助函数，只改 `login()` 覆盖不到它们。另外，基线的验证码不是 FastAPI 依赖，只能在调用点所在的模块属性上 patch。

**机制：**

- `tests/support/auth_guards.py` 维护 `CAPTCHA_SEAMS = ("octop.api.routers.auth.ensure_captcha",)`。
- 根 `tests/conftest.py` 的 autouse 夹具 `_relax_auth_guards` 对每个用例执行判断：如果 `wants_real_guards(request.node)` 为假，就调用 `relax_auth_guards(monkeypatch)`，把每个 seam 替换为 `captcha_exempt`（一个返回 `None` 的协程），并把模块级 `_active` 置为 `True`。monkeypatch 在用例结束时自动还原。
- autouse 夹具先于同作用域的非 autouse 夹具建立，所以 `env` 等夹具建立时登录已经处于豁免状态。
- **退出豁免：** 用例或类标记 `@pytest.mark.real_auth_guards`，或者模块路径在 `REAL_AUTH_GUARD_MODULES` 中。基线清单只有 `tests/integration/test_captcha_api.py`，它不需要任何修改就继续跑真实校验。这里沿用 `_SLOW_TEST_MODULES` 的做法，用模块路径集合实现零修改退出。
- **标记登记位置：** 在 `tests/conftest.py::pytest_configure` 中用 `config.addinivalue_line("markers", ...)` 登记，不改 `pyproject.toml`（上游热点文件）。

**如何让豁免不会悄悄失效：**

- `test_captcha_seams_resolve`：每个 seam 必须能解析到。后续 spec 删除或改名调用点时，这个用例会变红。
- `test_captcha_seam_is_on_login_path`（`real_auth_guards`）：把 seam 替换为抛出 `CAPTCHA_REQUIRED` 的桩，真实登录返回 400。后续 spec 把登录改成调用别的函数、却留着旧名字时，这个用例会变红。
- 两条合起来，保证"seam 在真实登录路径上"并且"默认已被替换"，于是在任意 provider 下默认都能豁免。自测不依赖任何具体 provider，所以 `w1-05` 删除云 provider 时不需要改这些自测。

**为什么默认生效，而不是按需开启：** 目标就是让 `w3-01` 把验证码设为默认后，既有测试零修改仍然通过。在基线阶段，默认生效是无副作用的：只有 `test_captcha_api.py` 会启用 `requires_token` 的 provider，而它已登记退出。

### 3. 依赖级豁免注册点

- `DEPENDENCY_OVERRIDES: dict[Callable[..., Any], Callable[..., Any]] = {}`，基线为空。
- `apply_test_dependency_overrides(app)` 在 `_active` 为真时，把注册表写入 `app.dependency_overrides`。
- **两个接入点：**
  - `octop_client` 在 `build_app(srv)`（≈L63）之后调用它，`tests.support.http.ws_connect` 复用的 `client._octop_app` 是同一个应用对象；
  - `env_terminal` 自建的第二个应用同样调用它。
- 另外 5 个直接调用 `build_app` 的测试文件（`test_dashboard_serve`、`test_scalar`、`test_openapi_meta`、`test_jwt_auth_middleware`、`test_exception_handlers`）不访问受重认证保护的端点，本 spec 不改它们。将来如有需要，调用同一个函数即可。

**给后续 spec 的约束：** 被登记的依赖必须是稳定的模块级可调用对象。`require_permission` 这类工厂闭包每次调用都返回新对象，无法作为键。如果重认证依赖需要按动作参数化，工厂返回的闭包内部应当 `Depends(<稳定的模块级依赖>)`，登记的是这个内层依赖。FastAPI 会在依赖树的任意层级替换被覆盖的依赖。

### 4. 三员分立形状预留

- 在 `tests/support/auth.py` 中新增：
  - `ADMIN_SLOTS = ("system", "security", "audit")`；
  - `TEST_ADMIN_ACCOUNTS: dict[str, tuple[str, str]]`，基线三项都是 `("admin", TEST_PASSWORD)`；
  - `AdminCredentials(system, security, audit, usernames)`；
  - `bootstrap_admins(client, home)`：调用 `bootstrap_admin` 与 `auth_header` 各一次，三个槽位共用同一个鉴权头。
- `tests/integration/conftest.py`：
  - 新增 `env_admins`，它持有 `octop_client`，产出 `(client, srv, admins)`；
  - `env` 改为依赖 `env_admins`，产出 `(client, srv, admins.system)`；
  - pytest 在同一用例内缓存函数级夹具，所以同时请求两者时共享同一个服务器。
- 四处建账或查账调用改走 `admins.security`；`bootstrap_boundary_env` 增加 `*, user_admin_auth: dict[str, str] | None = None`。
- 在基线阶段，`admins.security is admins.system`，所以行为与现在逐字节一致。
- `w3-03` 上线三账号时，只需做两件事：
  - 把 `TEST_ADMIN_ACCOUNTS` 改成三个互不相同的账号；
  - 把 `bootstrap_admin` / `bootstrap_admins` 的建号步骤改调新的 setup 契约。

  所有经 `env` 链的用例会自动拿到系统管理员，夹具内的建账会自动走安全管理员。建账归安全管理员还是系统管理员，按源分析 S16 的 changes[59] 暂取 `security`，最终由 `w3-03` 决定，只需改 conftest 里这 4 处。

### 5. 生产隔离不变式

`test_no_production_exemption_switch` 固化三条：

- `dataclasses.fields(OctopConfig)` 中没有字段名匹配 `(bypass|exempt|skip)_?(captcha|reauth)` 或其反序；
- `src/octop/**/*.py`（不含 `src/octop/dashboard/`）中没有任何文件引用 `tests.support`；
- 上述文件中也没有任何文件含该模式。

基线下三条均成立。

## 组件与接口

| 文件 | 类型 | 改动 |
|---|---|---|
| `tests/support/auth_guards.py` | 新增 | 测试进程专用的护栏豁免，全部 fork 逻辑集中在这里 |
| `tests/support/auth.py` | 修改 | 新增全量键授予、三员形状；既有 11 个函数的签名与返回值不变 |
| `tests/support/app.py` | 修改 | `octop_client` 在 `build_app` 后增加一行 `apply_test_dependency_overrides(app)`，外加一行导入 |
| `tests/support/scenarios.py` | 修改 | `bootstrap_boundary_env` 增加仅限关键字参数 `user_admin_auth` |
| `tests/conftest.py` | 修改 | 新增 `pytest_configure` 登记标记，新增 autouse 夹具 `_relax_auth_guards` |
| `tests/integration/conftest.py` | 修改 | 新增 `env_admins`；`env` 改为派生；4 处建账或查账改走 `security` 槽位；`env_terminal` 应用依赖替身 |
| `tests/integration/test_auth_baseline.py` | 新增 | 需求 1-4 的集成自测 |
| `tests/unit/api/test_auth_guard_exemptions.py` | 新增 | seam 解析、注册表、隔离不变式的单测 |

`tests/support/auth_guards.py` 的接口：

```python
REAL_AUTH_GUARDS_MARK = "real_auth_guards"
CAPTCHA_SEAMS: tuple[str, ...] = ("octop.api.routers.auth.ensure_captcha",)
DEPENDENCY_OVERRIDES: dict[Callable[..., Any], Callable[..., Any]] = {}
REAL_AUTH_GUARD_MODULES: frozenset[str] = frozenset({"tests/integration/test_captcha_api.py"})

async def captcha_exempt(*_args: Any, **_kwargs: Any) -> None: ...
def wants_real_guards(node: pytest.Item) -> bool: ...          # 看标记，或看 nodeid 的模块段是否在清单里
def relax_auth_guards(monkeypatch: pytest.MonkeyPatch) -> None: ...  # patch 各 seam，并置 _active = True
def apply_test_dependency_overrides(app: FastAPI) -> None: ...  # 仅在 _active 为真时 update
```

`tests/support/auth.py` 新增的接口：

```python
ADMIN_SLOTS: tuple[str, ...] = ("system", "security", "audit")
TEST_ADMIN_ACCOUNTS: dict[str, tuple[str, str]]   # slot -> (username, password)

def all_permission_keys() -> list[str]: ...       # sorted(ALL_PERMISSION_KEYS)，函数内延迟导入

@dataclass(frozen=True)
class AdminCredentials:
    system: dict[str, str]
    security: dict[str, str]
    audit: dict[str, str]
    usernames: dict[str, str]

async def bootstrap_admin(client, home, *, username="admin", password=TEST_PASSWORD) -> httpx.Response: ...  # 签名不变
async def bootstrap_admins(client: httpx.AsyncClient, home: Path) -> AdminCredentials: ...
```

`tests/integration/conftest.py` 新增的夹具：

```python
@pytest.fixture
async def env_admins(tmp_octop_home: Path) -> AsyncIterator[tuple[httpx.AsyncClient, OctopServer, AdminCredentials]]: ...
```

## 数据模型

无。本 spec 不新增 fork 迁移，不改任何表结构，也不改 `_schema_version` 断言。

## 配置

无。本 spec 不新增 `OctopConfig` 键，也不新增环境变量。按需求 2.5，豁免不得以任何配置形式出现在生产代码中。

## 错误处理

无新增 `ErrorCode`。自测中复用既有的 `ErrorCode.CAPTCHA_REQUIRED`（`_DEFAULT_STATUS` 映射 400）与 `ErrorCode.FORBIDDEN`（映射 403）。

## 安全考虑

- **豁免只存在于测试进程：** 只用 `monkeypatch` 与 `app.dependency_overrides`，二者都要求在同一进程里执行 Python 代码，外部无法通过配置、环境变量或请求打开。`tests/` 不进 wheel。隔离不变式单测把"生产代码里不许有豁免开关"变成 CI 门禁。
- **退出豁免的办法同样只存在于测试源码里：** `real_auth_guards` 标记与 `REAL_AUTH_GUARD_MODULES`。
- **验证码专项测试不受影响：** `test_captcha_api.py` 继续跑真实校验。后续 spec 新增的验证码或重认证专项测试必须退出豁免，见交接。
- **不削弱生产护栏：** 本 spec 不改 `src/` 下任何护栏，也不改变 admin 绕过的生产行为。夹具授予的全量键只写入测试进程创建的临时库。

## 测试策略

| 类别 | 内容 | 本地命令 |
|---|---|---|
| 单测 | seam 解析；默认替换与退出后还原；`REAL_AUTH_GUARD_MODULES` 文件存在；最小 FastAPI 应用上的注册表生效与退出；生产隔离不变式 | `uv run pytest tests/unit/api/test_auth_guard_exemptions.py -q` |
| 集成（自测） | 全量键读回；严格判定下三个端点返回 200；自定义用户名同样授予；授予失败时抛错；三槽位形状与别名；`env` 与 `env_admins` 共享服务器；`bootstrap_boundary_env` 的槽位路由与缺省回落；seam 在登录路径上；默认免验证码；`octop_client` 与 `env_terminal` 应用替身及退出 | `uv run pytest tests/integration/test_auth_baseline.py -q` |
| 集成（重点回归） | 返回值断言、setup 契约、验证码真实校验、边界鉴权 | `uv run pytest tests/integration/test_captcha_api.py tests/integration/test_auth_flow.py tests/integration/test_setup_bootstrap.py tests/integration/test_setup_database.py tests/integration/test_setup_wizard.py tests/integration/test_boundary_authz.py tests/integration/test_users_api.py tests/integration/test_usage_api.py tests/unit/api/test_jwt_auth_middleware.py -q` |
| 全量 | 零修改通过，失败集合与基线相同 | `uv run pytest -m "not live" -n auto -q` |
| 前端 | 不涉及。本 spec 不改 `dashboard/` | 无 |
| PG | 不涉及方言。`test_postgresql_control_plane.py` 不经共享夹具，本 spec 不新增 PG 用例，也不依赖 `w0-02` | 无 |

跨平台：

- pytest 的 `nodeid` 在 Windows 上同样使用 `/`，与 `_SLOW_TEST_MODULES` 的既有用法一致；
- 隔离不变式用 `pathlib` 遍历，用 `read_text(encoding="utf-8")` 读取，用 `relative_to(...).as_posix()` 输出；
- 不涉及 chmod、符号链接，也不写字面 POSIX 路径。

xdist：monkeypatch 与模块级 `_active` 都按进程、按用例生效，并自动还原。

## 与其他 spec 的交接

**依赖：** 无。本 spec 属于 Wave 0，可以与 `w0-01`、`w0-02`、`w0-04`、`w0-05` 并行，唯一的假设是它们不改本 spec 的 5 个夹具文件。

**交付给：**

- **`w3-03`（授权地基与三员分立）：**
  1. **删绕过时：** 如果 `setup.py` 的回填正确，`bootstrap_admin` 的授予步骤会幂等成功。如果回填缺失，授予步骤会因 `require_permission("users")` 返回 403 而在夹具建立时统一失败，报错集中在一处，而不是约 51 个文件各自报 403。
  2. **三员互斥或"角色派生键不落 `users.permissions`"时：** `w3-03` 在 `tests/support/auth.py` 一处调整。具体是把授予步骤改为断言或删除，把 `TEST_ADMIN_ACCOUNTS` 改成三个账号，把建号改调新契约，并把自测 `test_env_admins_reserve_three_slots` 末尾的别名断言改为断言三个账号互不相同。conftest 里 4 处建账调用的槽位也由 `w3-03` 最终确定。
  3. **仍需 `w3-03` 自己迁移的内容：**
     - 5 个 setup 契约测试文件里的 19 处裸 `/api/setup/initial-admin` 调用（清单见"现状"）；
     - 前端 `dashboard/src/pages/Setup/wizardClient.ts` ≈L156 与 `dashboard/src/api/modules/auth.ts` ≈L162 两个调用点；
     - 21 个直接创建 `Role.ADMIN` 用户的单元测试文件，可复用 `all_permission_keys()`；
     - `tests/unit/api/test_acl_gate_coverage.py` 中对 `is_admin` 字样的硬性断言。
  4. **新增的权限类用例：** 用 `env_admins` 的具体槽位，不再用笼统的 `env` 管理员。
- **`w3-01`（Web 安全基线，含验证码终态）：**
  1. 如果登录路由里的验证码调用点改名、移动或新增（例如邀请注册、OIDC 回跳也加验证码），同批更新 `CAPTCHA_SEAMS`。`test_captcha_seams_resolve` 与 `test_captcha_seam_is_on_login_path` 会在漏改时变红。
  2. 如果把验证码改成 FastAPI 依赖，就把对应条目从 `CAPTCHA_SEAMS` 移到 `DEPENDENCY_OVERRIDES`。
  3. 本地图形验证码的专项测试文件加入 `REAL_AUTH_GUARD_MODULES`，或者打上 `real_auth_guards` 标记。
  4. 限流、可信代理、上传杀毒的测试默认值由 `w3-01` 自己写进 `octop_client`（源分析 S14 changes[58]），同样只能用测试进程内的手段，不新增生产侧的"测试模式"开关。
- **重认证依赖的实施方（按 S22 归 `p2-07`；若 `w3-04` 先落地短时 scope 令牌，由它接手）：**
  - 在 `DEPENDENCY_OVERRIDES` 中登记"稳定依赖 → 放行替身"，约束见"方案 3"；
  - 重认证专项测试（如 `tests/integration/test_reauth.py`）加入 `REAL_AUTH_GUARD_MODULES`。
- **`w3-04`（会话与口令）：**
  - 如果登录响应形状变化（令牌字段、Cookie、短时令牌加刷新），只需改 `login()` / `auth_header()`。
  - 如果强化口令策略，要么保证 `TEST_PASSWORD = "TestPass12"` 仍然合规，要么同批机械替换 19 个文件中的 101 处字面量。
  - `env_terminal` 从鉴权头里取裸令牌给 WebSocket 用，令牌移出 URL 时由 `w3-04` 处理。
- **`w3-02`（审计与日志基线）：**
  - 每次 bootstrap 会产生一条 `user.set_permissions` 审计记录，actor 在 `w3-02` 替换 `ACTOR_ADMIN` 之前为 `_admin`。断言审计条数的新用例应当按 `action` 过滤。
  - 读取审计日志的新用例用 `env_admins` 的 `audit` 槽位。
- **`w1-02` / `w1-03` / `w1-05`（删除权限键）：** 夹具的键集在运行期计算，无需改动。
- **`w1-05`（云验证码删除）：** 如果删除或重写 `test_captcha_api.py`，同步维护 `REAL_AUTH_GUARD_MODULES`。`test_real_guard_modules_exist` 会在清单与文件不一致时变红。
- **`w0-04`：**
  - 在 `CHANGELOG-intranet.md` 补录本 spec 的条目；
  - 在 AGENTS.md §9 "Test layout & shared helpers" 一行补上 `tests/support/auth_guards.py` 与 `env_admins`；
  - 上游同步手册写入一条：同步后运行 `uv run pytest tests/unit/api/test_auth_guard_exemptions.py tests/integration/test_auth_baseline.py -q`。

**看似相关、实际归别的 spec：**

| 内容 | 归属 |
|---|---|
| 源分析 S08 的 `016` 管理员回填迁移、启动自愈、CLI `grant` / `revoke` | `w3-03`（用 `forkNNN_<描述>`） |
| 源分析 S16 的 `/setup/initial-admins`、`test_setup_wizard.py` 等 5 个契约文件的改写 | `w3-03` |
| 源分析 S14 给 `octop_client` 加限流、杀毒、可信代理默认值与 `client_addr` 参数 | `w3-01` |
| 源分析 S22 的 `/api/auth/reauth`、`require_reauth`、`sign_token` 扩展位 | `p2-07` |
| 生产代码里既有的 `set_test_siteverify_url` 测试 seam | 随云 provider 由 `w1-05` 处理 |

## 风险与回滚

| 风险 | 影响 | 缓解 |
|---|---|---|
| 默认生效的验证码豁免掩盖后续 spec 的验证码回归 | 验证码坏了，但全量测试仍然是绿的 | 专项测试必须退出豁免（交接给 `w3-01`）；seam 解析与"seam 在登录路径上"两条自测防止豁免与真实路径脱节 |
| 授予步骤多写一条审计记录，管理员行的 `permissions` 由 `[]` 变为 26 个键 | 断言审计条数或管理员行的用例会变红 | 基线已核实没有这类断言，原型全量回归通过；已交接给 `w3-02` |
| `w3-03` 的三员互斥拒绝"单账号持全量键" | `bootstrap_admin` 在建立阶段失败 | 失败点集中在一处；形状已预留，`w3-03` 只改 `tests/support/auth.py` 与 conftest 4 处 |
| 上游同步时，5 个夹具文件发生冲突 | 同步变慢 | fork 逻辑集中在新文件 `tests/support/auth_guards.py`；5 个上游文件各自只改几行（历史 churn 为 7-10 次提交）；冲突时先取上游再重放这几行 |
| `env` 改为依赖 `env_admins`，与用例自定义的同名夹具冲突 | 夹具解析出错 | 基线已核实 `env_admins`、`AdminCredentials`、`bootstrap_admins`、`auth_guards` 在仓内均无同名 |

**回滚：** revert 本 spec 的提交即可。本 spec 不涉及生产代码、数据和配置，回滚没有迁移或兼容问题。新增的两个测试文件随提交一起删除。

## 待行方确认

本 spec 本身不需要行方拍板，可以直接实施。它所依据的默认假设及其影响如下：

- **D12（RBAC 终局：三员分立）：** 三槽位形状按 D12 的默认假设预留。如果行方答复不做三员分立，`AdminCredentials` 的三个槽位就一直保持别名，不产生返工。
- **D11（验证码终态：服务端校验的本地图形验证码）：** 豁免机制按调用点 seam 设计，与验证码的具体形态无关。无论最终是哪种验证码，`w3-01` 只需维护 `CAPTCHA_SEAMS`。
