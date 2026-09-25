# 实施计划：测试鉴权基线

> spec：`w0-03-test-auth-baseline` ｜ 波次：Wave 0 ｜ 基线：`757fd12` ｜ 预估：3.25 人日
> 前置：无 ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

每个顶层任务完成后可独立提交；提交前运行任务内的验证命令。

本 spec 只改 `tests/`。下文中的 `$BASE` 指任务 1 记录的起点提交。

> 实施说明：为避免重复用例，下文列出的自测已按行为合并或参数化，覆盖的验收点不变——
> `test_bootstrap_admin_grants_all_permission_keys[default|custom]`（2.1 第一、三条，用 `patched_app_client` 直接取返回值与 id）；
> `test_captcha_seams_resolve` 打 `real_auth_guards`，兼作 3.1 的"退出后不替换"；
> 删去 `test_login_captcha_seam_exempt_by_default`（由单测 `test_captcha_seams_patched_by_default` 与每个 `env` 夹具的登录覆盖）；
> `test_dependency_overrides_follow_opt_out[200|403]`（4.1 单测两条）；
> `test_test_apps_apply_registered_overrides(env, env_terminal)`（4.1 集成三条合一，退出豁免由上面的单测覆盖）；
> `test_env_admins_reserve_three_slots(env, env_admins)`（5.1 前三条合一，别名断言留给 `w3-03` 翻转）；
> `test_boundary_env_routes_user_management[user_admin_auth|default]`（5.1 后两条）。

- [x] 1. 确认前置 spec 已合入并记录基线（0.25 人日）
  - 改动：无代码改动。本 spec 没有前置 spec。按下列步骤记录基线，并把各命令输出贴进 PR 描述：
    - 用 `BASE=$(git rev-parse HEAD)` 记录起点；
    - 复核引用面：28 个引用文件、5 个文件共 19 处裸 `initial-admin`、10 个文件共 31 处裸登录；
    - 确认 `setup.py` 创建初始管理员时不传 `permissions`；
    - 确认新名字在仓内没有占用；
    - 跑一次全量测试，记录基线失败集合。已知在 root 用户下，`tests/unit/infra/setup/test_service.py` 有 3 个环境性失败。
  - 验证：`git merge-base --is-ancestor 757fd12 HEAD && echo baseline-ok`
  - 验证：`rg -l "tests\.support\.auth" tests | wc -l`（应为 28）
  - 验证：`rg -c '"/api/setup/initial-admin"' tests`
  - 验证：`rg -c '"/api/auth/login"' tests --glob '!tests/support/**' --glob '!tests/unit/api/test_openapi_meta.py'`
  - 验证：`! rg -n "permissions" src/octop/api/routers/setup.py`
  - 验证：`! rg -n "env_admins|bootstrap_admins|AdminCredentials|auth_guards|real_auth_guards|all_permission_keys" tests src/octop`
  - 验证：`uv run pytest -m "not live" -n auto -q 2>&1 | tail -20`
  - _需求：5.1, 5.2_

- [x] 2. 管理员显式持有全量权限键（测试先行，0.5 人日）
  - [x] 2.1 先写会失败的测试
    - 改动：新增 `tests/integration/test_auth_baseline.py`，写入以下用例：
      - `test_bootstrap_admin_holds_all_permission_keys(env)`：先用 `GET /api/auth/me` 取 id，再断言 `GET /api/users/{id}` 的 `permissions == sorted(ALL_PERMISSION_KEYS)`。
      - `test_env_admin_survives_simulated_bypass_removal(env, monkeypatch)`：把 `octop.api.deps.user_has_permission` 替换为 `lambda user, key: key in PERMISSIONS and key in (user.permissions or [])`，断言 `GET /api/admin/providers`、`GET /api/users`、`GET /api/admin/audit-log` 都返回 200。
      - `test_bootstrap_admin_custom_username_gets_all_keys(app_client)`：`bootstrap_admin(c, home, username="root2")` 返回 201，并读回全量键。
      - `test_bootstrap_admin_raises_when_grant_fails(app_client, monkeypatch)`：把 `octop.api.routers.users._assert_can_assign` 替换为抛出 `OctopError(ErrorCode.FORBIDDEN, …)`，断言 `bootstrap_admin` 抛出 `httpx.HTTPStatusError`。
    - 验证：`uv run pytest tests/integration/test_auth_baseline.py -q`（此时前两条应以 `[] != [...]` 与 403 失败，第四条应因未抛错而失败）
    - _需求：1.1, 1.2, 1.4_
  - [x] 2.2 实现授予步骤
    - 改动：`tests/support/auth.py`：
      - 新增 `all_permission_keys()`，在函数内延迟导入 `ALL_PERMISSION_KEYS`，返回排序后的列表；
      - 在 `bootstrap_admin` 的 `finish.raise_for_status()` 之后，用 `r.json()["access_token"]` 调用 `PATCH /api/users/{r.json()['id']}`，请求体为 `{"permissions": all_permission_keys()}`，并 `raise_for_status()`；
      - 返回值仍然是 `r`，签名不变；
      - 在 docstring 里写明：键集在运行期计算，admin 显式持键是为 `w3-03` 删除绕过做的准备。
    - 验证：`uv run pytest tests/integration/test_auth_baseline.py -q`
    - 验证：`uv run pytest tests/integration/test_auth_flow.py tests/integration/test_setup_bootstrap.py tests/integration/test_setup_database.py tests/integration/test_e2e_golden_path.py tests/integration/test_users_api.py tests/integration/test_personas_admin_api.py tests/unit/api/test_jwt_auth_middleware.py -q`
    - 验证：`! rg -n '"(admin_console|storage_backends|knowledge_settings|ollama_models)"' tests/support`
    - _需求：1.1, 1.2, 1.3, 1.4, 1.5_

- [x] 3. 验证码测试豁免与生产隔离不变式（测试先行，0.75 人日）
  - [x] 3.1 先写会失败的测试
    - 改动：新增 `tests/unit/api/test_auth_guard_exemptions.py`，写入以下用例：
      - `test_captcha_seams_resolve`：用 `importlib` 逐个解析 `CAPTCHA_SEAMS`。
      - `test_captcha_seams_patched_by_default`：解析结果 `is auth_guards.captcha_exempt`。
      - `test_captcha_seams_untouched_when_opted_out`：打 `@pytest.mark.real_auth_guards`，断言解析结果不是 `captcha_exempt`。
      - `test_real_guard_modules_exist(repo_root)`：清单中每个路径都是文件。
      - `test_no_production_exemption_switch(repo_root)`：
        - `OctopConfig` 字段名不匹配 `(bypass|exempt|skip)_?(captcha|reauth)|(captcha|reauth)_?(bypass|exempt|skip)`；
        - `src/octop/**/*.py`（跳过 `dashboard/`）不含 `tests.support`，也不含该模式；
        - 用 `pathlib` 遍历，用 `read_text(encoding="utf-8")` 读取，用 `relative_to(...).as_posix()` 输出。
    - 改动：在 `tests/integration/test_auth_baseline.py` 追加以下用例：
      - `test_login_captcha_seam_exempt_by_default(env)`：断言 `octop.api.routers.auth.ensure_captcha is captcha_exempt`，且 `login(c)` 成功。
      - `test_captcha_seam_is_on_login_path(env, monkeypatch)`：打 `real_auth_guards`，把每个 seam 替换为抛出 `OctopError(ErrorCode.CAPTCHA_REQUIRED, …)` 的协程，断言 `POST /api/auth/login` 返回 400 且 `error.code == "CAPTCHA_REQUIRED"`。
    - 验证：`uv run pytest tests/unit/api/test_auth_guard_exemptions.py tests/integration/test_auth_baseline.py -q`（此时应因 `tests.support.auth_guards` 不存在而失败）
    - _需求：2.1, 2.2, 2.3, 2.4, 2.5_
  - [x] 3.2 实现豁免模块与 autouse 夹具
    - 改动：新增 `tests/support/auth_guards.py`，内容如下：
      - 常量：`REAL_AUTH_GUARDS_MARK`、`CAPTCHA_SEAMS = ("octop.api.routers.auth.ensure_captcha",)`、`REAL_AUTH_GUARD_MODULES = frozenset({"tests/integration/test_captcha_api.py"})`，以及模块级 `_active = False`；
      - 函数：`captcha_exempt`、`wants_real_guards(node)`（看 `node.get_closest_marker`，或看 `nodeid` 的模块段）、`relax_auth_guards(monkeypatch)`（逐个 `monkeypatch.setattr(seam, captcha_exempt)`，并 `monkeypatch.setattr(f"{__name__}._active", True)`）；
      - 模块 docstring 写明：生产代码不得出现对应的配置开关。
    - 改动：`tests/conftest.py`：
      - 新增 `pytest_configure(config)`，用 `config.addinivalue_line("markers", "real_auth_guards: …")` 登记标记，不改 `pyproject.toml`；
      - 新增 autouse 夹具 `_relax_auth_guards(request, monkeypatch)`：当 `wants_real_guards(request.node)` 为假时，调用 `relax_auth_guards(monkeypatch)`。
    - 验证：`uv run pytest tests/unit/api/test_auth_guard_exemptions.py tests/integration/test_auth_baseline.py -q`
    - 验证：`uv run pytest --markers | rg real_auth_guards`
    - 验证：`uv run pytest tests/integration/test_captcha_api.py tests/integration/test_auth_flow.py tests/integration/test_envs_api.py tests/integration/test_invites_api.py tests/unit/auth tests/unit/cli/test_captcha_cmd.py -q`（`test_captcha_api.py` 须继续跑真实校验并全绿）
    - 验证：`! rg -n -i "(bypass|exempt|skip)_?(captcha|reauth)|(captcha|reauth)_?(bypass|exempt|skip)" src/octop`
    - _需求：2.1, 2.2, 2.3, 2.4, 2.5_

- [x] 4. 依赖级测试豁免注册点（测试先行，0.5 人日）
  - [x] 4.1 先写会失败的测试
    - 改动：在 `tests/unit/api/test_auth_guard_exemptions.py` 追加以下用例：
      - 构造最小 FastAPI 应用，路由依赖一个抛出 `HTTPException(403)` 的 `_guard`。用 `monkeypatch.setitem(auth_guards.DEPENDENCY_OVERRIDES, _guard, _allow)` 登记放行替身后，调用 `apply_test_dependency_overrides(app)`，经 `httpx.ASGITransport` 请求应当返回 200。
      - 同一用例加 `real_auth_guards` 标记的版本应当返回 403。
    - 改动：在 `tests/integration/test_auth_baseline.py` 追加以下用例：
      - `test_octop_client_applies_registered_overrides(tmp_octop_home, monkeypatch)`：先登记模块内探针依赖，再进入 `octop_client`，断言 `client._octop_app.dependency_overrides[probe] is replacement`。
      - 打 `real_auth_guards` 的对照用例：断言探针不在 `dependency_overrides` 中。
      - `env_terminal` 应用的同类断言。探针要在 `env_terminal` 建立应用之前登记，所以用一个本地夹具 `probe_override(monkeypatch)` 完成登记，并在测试签名中把它写在 `env_terminal` 之前。
    - 验证：`uv run pytest tests/unit/api/test_auth_guard_exemptions.py tests/integration/test_auth_baseline.py -q`（此时应因 `apply_test_dependency_overrides` 未定义而失败）
    - _需求：3.1, 3.2, 3.3, 3.4_
  - [x] 4.2 实现注册表与接入点
    - 改动：`tests/support/auth_guards.py`：
      - 新增 `DEPENDENCY_OVERRIDES: dict[Callable[..., Any], Callable[..., Any]] = {}`；
      - 新增 `apply_test_dependency_overrides(app)`：仅在 `_active` 为真时执行 `app.dependency_overrides.update(DEPENDENCY_OVERRIDES)`；
      - 在注释里写明对登记方的约束：只能登记稳定的模块级依赖，工厂闭包内部须 `Depends` 一个稳定依赖（design.md "方案 3"）。
    - 改动：`tests/support/app.py::octop_client`：在 `app = build_app(srv)`（≈L63）之后调用 `apply_test_dependency_overrides(app)`。
    - 改动：`tests/integration/conftest.py::env_terminal`（≈L224-231）：把 `build_app(srv)` 提到局部变量 `app`，调用 `apply_test_dependency_overrides(app)` 后再 `yield`。
    - 验证：`uv run pytest tests/unit/api/test_auth_guard_exemptions.py tests/integration/test_auth_baseline.py tests/integration/test_terminal_ws.py tests/integration/test_terminal_context.py tests/integration/test_chat_ws.py tests/integration/test_notifications_ws.py -q`
    - 验证：`uv run python -c "from tests.support.auth_guards import DEPENDENCY_OVERRIDES as d; assert d == {}; print('empty')"`（合入时注册表为空；这一条只做命令核对，不写成永久测试，以免登记依赖的 spec 被迫删除它）
    - _需求：3.1, 3.2, 3.3, 3.4_

- [x] 5. 为三员分立预留管理员凭据形状（测试先行，0.75 人日）
  - [x] 5.1 先写会失败的测试
    - 改动：在 `tests/integration/test_auth_baseline.py` 追加以下用例：
      - `test_admin_credentials_reserve_three_slots(env_admins)`：`set(admins.usernames) == set(ADMIN_SLOTS)`，且每个槽位的 `GET /api/auth/me` 返回 `usernames[slot]`。
      - `test_slots_alias_single_admin_before_w303(env_admins)`：三个槽位的头相等，且 `TEST_ADMIN_ACCOUNTS` 三项都是 `("admin", TEST_PASSWORD)`。
      - `test_env_and_env_admins_share_server(env, env_admins)`：`env[1] is env_admins[1]`，且 `env[2] == env_admins[2].system`。
      - `test_boundary_env_routes_user_management(env_admins, monkeypatch)`：
        - 用 `monkeypatch` 包装 `tests.support.scenarios.create_user` 与 `tests.support.scenarios.resolve_user_id`。`scenarios.py` 是按名字导入这两个函数的，所以要 patch 它自己的模块属性，而不是 `tests.support.auth` 里的。
        - 包装函数记录收到的鉴权头对象。
        - 以 `bootstrap_boundary_env(client, srv, dict(admins.system), user_admin_auth=admins.security)` 调用，断言记录到的对象 `is admins.security`。这里用 `dict(...)` 复制出一个不同的对象，以便用 `is` 区分两个参数。
        - 另写一个用例 `test_boundary_env_defaults_to_admin_auth`，以不传 `user_admin_auth` 的方式调用，断言记录到的是传入的 `admin_auth` 对象。`bootstrap_boundary_env` 固定创建 alice、bob 与 `shared-openai`，同一个库里不能调用两次，所以必须分成两个用例。
    - 验证：`uv run pytest tests/integration/test_auth_baseline.py -q`（此时应因 `env_admins` 夹具不存在而报错）
    - _需求：4.1, 4.2, 4.3, 4.4_
  - [x] 5.2 实现 `tests/support/auth.py` 的形状
    - 改动：`tests/support/auth.py`：
      - 新增 `ADMIN_SLOTS = ("system", "security", "audit")`；
      - 新增 `TEST_ADMIN_ACCOUNTS = {slot: ("admin", TEST_PASSWORD) for slot in ADMIN_SLOTS}`；
      - 新增 `@dataclass(frozen=True) class AdminCredentials(system, security, audit, usernames)`；
      - 新增 `bootstrap_admins(client, home) -> AdminCredentials`：用 `TEST_ADMIN_ACCOUNTS["system"]` 调用一次 `bootstrap_admin` 与 `auth_header`，三个槽位共用同一个头，`usernames` 取自 `TEST_ADMIN_ACCOUNTS`；
      - 在 docstring 中写明：`w3-03` 上线三账号时只改 `TEST_ADMIN_ACCOUNTS` 与建号步骤。
    - 验证：`uv run python -c "from tests.support.auth import AdminCredentials, ADMIN_SLOTS, TEST_ADMIN_ACCOUNTS, bootstrap_admins; assert ADMIN_SLOTS == ('system', 'security', 'audit'); print('ok')"`
    - _需求：4.1, 4.2_
  - [x] 5.3 conftest 与 scenarios 接线
    - 改动：`tests/integration/conftest.py`：
      - 新增 `env_admins(tmp_octop_home)`：在 `octop_client` 内调用 `bootstrap_admins`，产出 `(client, srv, admins)`；
      - `env`（≈L54-62）改为依赖 `env_admins`，产出 `(client, srv, admins.system)`；
      - 以下夹具各增加 `env_admins` 参数，并把用户管理调用改走 `env_admins[2].security`：`env_alice_bob_agent`（`ensure_users`，≈L128）、`env_admin_alice`（`create_user`，≈L150）、`env_usage`（`resolve_user_id`，≈L161）、`env_boundary`（`bootstrap_boundary_env(..., user_admin_auth=...)`，≈L179）；
      - 删除不再使用的 `auth_header` 导入，保留 `__all__` 中的 `bootstrap_admin`。
    - 改动：`tests/support/scenarios.py::bootstrap_boundary_env`：增加 `*, user_admin_auth: dict[str, str] | None = None`，`create_user` 与 `resolve_user_id` 改用 `user_admin_auth or admin_auth`；provider 与 agent 的创建仍用 `admin_auth`。
    - 验证：`uv run pytest tests/integration/test_auth_baseline.py tests/integration/test_boundary_authz.py tests/integration/test_skill_packages_api.py tests/integration/test_usage_api.py tests/integration/test_personas_admin_api.py tests/integration/test_plugin_upload.py tests/integration/test_channels_api.py tests/integration/test_cron_api.py tests/integration/test_trajectory_api.py tests/integration/test_channel_probe_draft.py -q`
    - 验证：`rg -c "env_admins\[2\]\.security" tests/integration/conftest.py`（应为 4）
    - _需求：4.1, 4.2, 4.3, 4.4_

- [x] 6. 全量回归与零修改核对（0.25 人日）
  - 改动：无新增改动。跑全量测试，把失败集合与任务 1 记录的基线逐条比对；核对 `tests/` 下被修改的文件只有 5 个夹具文件，`src/`、`dashboard/`、依赖清单零改动。如果任何既有测试需要改动才能通过，回到对应任务修正实现，不得修改该测试。
  - 验证：`uv run pytest -m "not live" -n auto -q 2>&1 | tail -20`（失败集合应与基线相同）
  - 验证：`git diff --name-only --diff-filter=M "$BASE" -- tests/`（应只列出 `tests/conftest.py`、`tests/integration/conftest.py`、`tests/support/auth.py`、`tests/support/app.py`、`tests/support/scenarios.py`）
  - 验证：`git diff --name-only --diff-filter=A "$BASE" -- tests/`（应只列出 `tests/support/auth_guards.py`、`tests/integration/test_auth_baseline.py`、`tests/unit/api/test_auth_guard_exemptions.py`）
  - 验证：`git diff --name-only "$BASE" -- src dashboard pyproject.toml uv.lock`（应无输出）
  - _需求：5.1, 5.2, 5.3_

- [x] 7. 收尾（0.25 人日）
  - 改动：清理本 spec 引入但未使用的符号与导入，重点检查 `tests/integration/conftest.py` 的导入列表。
  - 改动：本 spec 不改 `dashboard/`，不需要前端 typecheck、lint 或 vitest。本 spec 不改任何 API，不更新 `docs/api-intranet.md`。
  - 改动：若 `w0-04` 已建立 `CHANGELOG-intranet.md`，追加一条"测试鉴权基线：`bootstrap_admin` 显式授予全量权限键；新增 `env_admins` / `AdminCredentials` 三员槽位；新增 `tests/support/auth_guards.py`（`CAPTCHA_SEAMS`、`DEPENDENCY_OVERRIDES`、`REAL_AUTH_GUARD_MODULES`、`real_auth_guards` 标记）"。若尚未建立，把这条写进 PR 描述，由 `w0-04` 补录；同时在 PR 描述中列出 design.md "与其他 spec 的交接"里给 `w3-01`、`w3-03`、`w3-02`、`w3-04`、`p2-07` 的要点。
  - 验证：`make all`（非 root 用户下应全绿；root 下只允许任务 1 记录的 3 个 `test_service.py` 环境性失败）
  - 验证：`uv run pytest tests/unit/api/test_auth_guard_exemptions.py tests/integration/test_auth_baseline.py -q`
  - 验证：人工确认新增测试只使用 `tmp_path` / `tmp_octop_home` / `pathlib`，不断言 chmod，不写以 `/` 开头的字面路径（Windows CI 会跑同一批用例）。
  - _需求：5.4, 5.5_
