# 设计文档：授权地基与三员分立

> spec：`w3-03-authorization-foundation` ｜ 波次：Wave 3 ｜ 基线：`757fd12` ｜ 预估：31 人日
> 前置：`w0-01-fork-migration-namespace`、`w0-02-ci-gates`、`w0-03-test-auth-baseline`、`w0-04-fork-isolation-points`、`w1-01-security-hotfix`、`w1-02-capability-trim`、`w1-03-online-fetch-trim`、`w1-05-saas-decoupling`、`w3-02-audit-baseline` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 概述

唯一的授权强制点是 `infra/users/permissions.py::user_has_permission`：`key ∈ 显式非管理类键 ∪ permissions_for_role(user.admin_role)`。角色存在 fork 表 `user_roles`（主键 `user_id`，数据库层保证一人至多一个管理角色）；派生键不落库，改角色即时生效（`deps.py` 每次请求都从库加载用户）。`User.is_admin` 属性被删除，由 mypy `--strict` 把全部使用点逼出来逐一改写：授权类改为查键，数据域类改为"只看自己与共享"。`as_user` 保留参数但默认拒绝。

合并说明：S08 的"回填默认键到 `users.permissions`"与 S16 的"角色派生"冲突，本设计采用派生（D12），不做 S08 的回填、启动自愈与 `acp` 键（ACP 已由 `w1-02` 删除）。

## 现状

- `src/octop/infra/users/permissions.py`：`ALL_PERMISSION_KEYS`（≈L218）、`BASELINE_PERMISSIONS`（≈L222，settings 类 4 键）、`user_has_permission`（≈L225，≈L232 `if user.is_admin`）、`validate_permission_keys`（≈L237）、`effective_permissions`（≈L251，≈L253 admin 返回全目录）。基线 26 键：settings 4、control 4、admin 18；`w1-02` 删 control 4 键，`w1-03` 删 `update` 增 `service_control`，`w1-05` 删 `search`。
- `infra/users/identity.py`：`Role`、`User`、`is_admin`（≈L27-29）；`api/deps.py`：`require_permission`（≈L201）、`require_admin`（≈L222，唯一使用者 `acp.py` 已由 `w1-02` 删除）。
- `src/octop/api/common/agent.py`：`assert_agent_owner`（≈L18，≈L20 `is_admin`）、`_user_may_access`（≈L26，≈L27）、`require_agent_row`（≈L39，≈L51-53 as_user 仅校验 `is_admin`）。
- `src/octop/api/routers/usage.py`：`_resolve_user_scope`（≈L42，≈L53）、`admin_summary`（≈L244，≈L254）、`admin_export`（≈L270，≈L278）均为 `if not user.is_admin`。
- `src/octop/api/routers/knowledge_bases.py`：`_is_admin(user)` 19 处调用；`infra/knowledge/service.py` 中 `is_admin` 出现 34 次，`list_visible_bases`（≈L129-134）按 `is_admin` 走 `list_all()`；`infra/knowledge/retrieve.py` ≈L76-80、`infra/gateway/process/processor.py` ≈L1316-1321、`infra/cron/delivery.py` ≈L240-243 同样二选一；`infra/agents/manager.py::validate_knowledge_base_ids`（≈L1907-1912）只用 `list_visible`，与前三处不一致。
- 角色位 `user_is_admin` 进入 harness `configurable`：生产者 `infra/knowledge/default_open.py`、`api/routers/chat/turn.py`（≈L313/319）、`infra/gateway/cli/turn.py`（≈L54/60）、`api/routers/chat/ws.py` ≈L165（`getattr(user, "is_admin", False)`，删属性后静默为假）、`cli/repl/runtime.py` ≈L78（`user_row.role == "admin"`）；消费者 `infra/knowledge/tools.py`、`processor.py` ≈L1291。
- 其他角色直判：`infra/skills/skill_package_store.py` ≈L191、`infra/agents/experts/publish.py` ≈L80、`api/routers/connectors.py` ≈L433 与 ≈L517、`api/routers/users.py::_assert_can_assign`（≈L83，≈L85 admin 直接放行）与 `_can_manage_users`（≈L96-97 字符串比较）、`patch_user`（≈L200，≈L218 只拦自降级、放行自升）、`api/routers/setup.py` ≈L148 与 ≈L435。`w1-01` 在 `users.py` 新增的 `_assert_may_assign_role`、`_assert_may_target` 也读 `is_admin`。
- `api/routers/setup.py`：`initial_admin`（≈L341，`user_manager.create` ≈L355 不传 `permissions=`）；账号计数门槛 ≈L107、≈L114、≈L145、≈L238、≈L384。`/setup/initial-admin` 的调用：前端 `wizardClient.ts` ≈L156 与 `api/modules/auth.ts` ≈L162；测试 `tests/support/auth.py` 与 5 个契约文件。
- `api/routers/admin.py`：`/overview`、`/audit-log`（≈L53）、`/metrics` 都挂 `require_permission("admin_console")`。
- `infra/users/manager.py`：`create`（≈L122，≈L138 `validate_permission_keys(permissions or [])`）、`set_permissions`（≈L519）、`set_role`（≈L589）。
- `infra/errors.py`：`ErrorCode`（≈L13）、`_DEFAULT_STATUS`（≈L115），`__post_init__` ≈L227 无保护下标。
- 前端 `dashboard/src/utils/permissions.ts`：`PermissionKeys` 含 `"admin"`（≈L9）、`userCan` ≈L83、`userCanAny` ≈L93、`canAccessKeys` ≈L102、`pathPermissionKeys` 的 `/admin/` 兜底 ≈L159、`SECURITY_TAB_PERMISSIONS.audit = "admin_console"`（≈L74）。`UsersListPanel.tsx` ≈L1094/1185 对 admin 提交 `permissions: []`；`TokenUsage/index.tsx` ≈L833、`SkillPackages/index.tsx` ≈L108、`KnowledgeBases/index.tsx` ≈L176、`Experts/index.tsx` ≈L101 按角色判定。
- 测试守卫：`tests/unit/api/test_acl_gate_coverage.py` 的 `GATED_FILES` 未含 `routers/usage.py`；`test_as_user_still_requires_admin`（≈L78-83）固化旧契约。`tests/integration/test_boundary_authz.py::test_admin_can_get_alices_agent_via_as_user`（≈L47）实际未传 `as_user`，测的是 `_user_may_access` 的绕过。

## 方案

1. **键目录。** 新增 `authorization`（授予角色与权限）、`audit_log`（读审计，从 `admin_console` 拆出）、`impersonate`（代操作），均为 `category="admin"`。
2. **角色派生（定义在 `permissions.py`，避免循环导入）。** 按 `w1` 波次后的目录划分：
   - `system_admin`：`users`、`providers`、`ollama_models`、`onnx_models`、`storage_backends`、`plugins`、`admin_console`、`envs`、`knowledge_settings`、`voice`、`observability`、`backup`、`tls`、`service_control`；
   - `security_admin`：`authorization`、`security`、`sso`、`captcha`；
   - `audit_admin`：`audit_log`。
   `impersonate` 不属于任何角色，只能显式授予。模块导入时断言两两不相交且覆盖全部管理类键减 `impersonate`；键目录此后再变，该断言会先红。
3. **显式列只存非管理类键。** `validate_permission_keys` 新增 `allow_admin_keys=False` 形参，拒绝管理类键（`impersonate` 除外）；`user_has_permission` 与 `effective_permissions` 对显式列先过滤再并入派生键。
4. **数据域。** 删除全部 `list_all` 分支与 `is_admin` 形参（不做改名），知识库可见性统一走新函数 `infra/knowledge/visibility.py::visible_bases(repo, user_id)`，5 个调用点（service、retrieve、processor、delivery、`validate_knowledge_base_ids`）都调它，`p2-05` 在此函数内实现三级 ACL。`configurable["user_is_admin"]` 整条链删除。专家与连接器只对属主与共享可见；技能包、已发布专家的跨创建者改写按 `skill_packages` 键。
5. **授权 API。** `PUT /api/users/{id}/admin-role`（`require_permission("authorization")`，body `{"role": "system_admin"|"security_admin"|"audit_admin"|null}`）；`PATCH /api/users/{id}` 的 `permissions` 字段改由 `authorization` 守卫，`role` 字段变更一律 403。建号（`users` 键）只允许 `permissions ⊆ BASELINE_PERMISSIONS`。领域规则（互斥、自授、最后持有者、键校验）集中在新模块 `infra/users/authz.py`，HTTP 与 CLI 共用。
6. **兼容列 `users.role`。** 保留：授予任一管理角色时同事务写 `admin`，撤销时写 `user`，仅供展示与上游代码兼容；授权代码不读它（守卫测试钉住）。
7. **as_user。** 新模块 `infra/users/impersonation.py`，默认拒绝，见"组件与接口"。
8. **安装向导。** 删除 `/setup/initial-admin`，新增 `/setup/initial-admins` 一次创建三账号；计数门槛从"1 个账号"改为"3 个引导账号"；`finish` 取系统管理员。

## 组件与接口

| 文件 | 类型 | 内容 |
|---|---|---|
| `src/octop/infra/users/identity.py` | 修改 | 新增 `AdminRole(StrEnum)`；`User.admin_role: AdminRole \| None = None`；删除 `is_admin` |
| `src/octop/infra/users/permissions.py` | 修改 | 三个新键、`ROLE_PERMISSIONS`、`permissions_for_role`、`is_role_derived_key`；改写 `user_has_permission` / `effective_permissions` / `validate_permission_keys` |
| `src/octop/infra/users/authz.py` | 新增 | 授权领域规则 |
| `src/octop/infra/users/impersonation.py` | 新增 | as_user 守卫 |
| `src/octop/infra/knowledge/visibility.py` | 新增 | 知识库可见性单点 |
| `src/octop/infra/db/repos/roles.py` | 新增 | `RoleRepo` |
| `src/octop/infra/db/repos/users.py` | 修改 | `UserRow.admin_role`；`get`/`get_by_username`/`list` LEFT JOIN `user_roles`、`roles` |
| `src/octop/infra/db/services.py` | 修改 | `RepoBundle.role_repo` 照 `user_policy_repo` 接线 |
| `src/octop/infra/users/manager.py` | 修改 | 8 处 `User(...)` 构造补 `admin_role`；新增 `set_admin_role`；`set_role` 对 `Role.ADMIN` 拒绝 |
| `src/octop/api/deps.py` | 修改 | 删除 `require_admin` |
| `src/octop/api/common/agent.py` | 修改 | 删两处绕过；as_user 分支调 `assert_impersonation_allowed` |
| 其余路由与 infra 调用点 | 修改 | 见“现状”所列文件；`agents/manager.py` 只改 `validate_knowledge_base_ids` 一行调用 |
| `src/octop/cli/commands/user.py`、`src/octop/cli/support/offline_ops.py`、`src/octop/cli/commands/init.py` | 修改 | 离线授权命令；`init` 建号后授予 `system_admin` |
| `src/octop/config.py` | 修改 | `allow_impersonation` |
| `src/octop/infra/errors.py` | 修改 | 三个新码 |

关键签名：

```python
# infra/users/permissions.py
ROLE_PERMISSIONS: dict[AdminRole, frozenset[str]]
def permissions_for_role(role: AdminRole | str | None) -> frozenset[str]: ...
def is_role_derived_key(key: str) -> bool: ...
def validate_permission_keys(keys: list[str], *, allow_admin_keys: bool = False) -> list[str]: ...

# infra/users/authz.py
async def assign_admin_role(services: SharedServices, *, actor: str, actor_user: User | None,
                            target_user_id: int, role: AdminRole | None) -> None: ...
async def set_explicit_permissions(services: SharedServices, *, actor: str, actor_user: User | None,
                                   target_user_id: int, keys: list[str]) -> None: ...
def assert_not_last_holder(role_repo: RoleRepo, *, leaving_user_id: int) -> None: ...
# actor_user=None 表示 CLI 离线路径：跳过自授与持键检查，其余规则相同

# infra/users/impersonation.py
def assert_impersonation_allowed(*, user: User, as_user: int, server: Any, target: str) -> None:
    # 1 config.allow_impersonation 为假 → 写 impersonate.denied，抛 AS_USER_DISABLED
    # 2 "impersonate" 不在显式键 → 写 impersonate.denied，抛 FORBIDDEN
    # 3 目标用户不存在 → NOT_FOUND；成功时由 w3-02 既有的 impersonate.access 钩子记录

# infra/knowledge/visibility.py
def visible_bases(repo: KnowledgeRepo, user_id: int) -> list[KnowledgeBaseRow]: ...

# infra/db/repos/roles.py：RoleRepo.get_for_user / set_for_user / clear_for_user / count_holders / missing_roles
```

HTTP：新增 `PUT /api/users/{user_id}/admin-role`、`POST /api/setup/initial-admins`（body `{system, security, audit}`），删除 `POST /api/setup/initial-admin`；`_user_json` 返回 `admin_role`。

## 数据模型

`forkNNN_admin_roles.sql` / `forkNNN_admin_roles.pg.sql`：

- `roles(id INTEGER PK AUTOINCREMENT | GENERATED BY DEFAULT AS IDENTITY, role_id TEXT UNIQUE NOT NULL, builtin INTEGER NOT NULL DEFAULT 1, created_at INTEGER NOT NULL)`，种子 `system_admin`、`security_admin`、`audit_admin`（PG 用 `ON CONFLICT DO NOTHING`）。
- `user_roles(user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, role_id TEXT NOT NULL REFERENCES roles(role_id), granted_by INTEGER, granted_at INTEGER NOT NULL)`。`users` 的整数主键是 `id`（`001_initial.sql` ≈L17）。
- 同版本在 `_FORK_PY_STEPS` 登记 Python 步骤 `migrate_admin_roles(conn, dialect)`（`w0-01` 机制）：`_table_exists(users)` 守卫；`role='admin'` 且无 `user_roles` 行 → 插入 `system_admin`；对每户 `permissions` 剥离快照键集 `{users, sso, providers, ollama_models, onnx_models, storage_backends, plugins, security, admin_console, envs, knowledge_settings, voice, observability, backup, tls, captcha, service_control, update, search, authorization, audit_log}`（写死，不导入上层包），有剥离时写 `audit_log` 一行 `actor='_migration'`、`action='authz.migrate.strip'`。可复用 `w1-02` 的 `infra/db/fork_steps.py::strip_permission_keys` 做剥离，但逐户留痕需自行遍历。

不改 `_schema_version`，不改任何 `== 15` 断言。

## 配置

| 键 | 默认 | env | 三触点 |
|---|---|---|---|
| `allow_impersonation` | `False` | `OCTOP_ALLOW_IMPERSONATION` | ① `OctopConfig` 字段（照 `enable_api_docs` ≈L135）；② env 覆盖块用 `_coerce_bool`（照 ≈L484-485）；③ `return OctopConfig(...)` 构造（照 ≈L602）。`w1-02` 的三触点单测自动覆盖 |

## 错误处理

| ErrorCode | `_DEFAULT_STATUS` | 场景 |
|---|---|---|
| `AS_USER_DISABLED` | 403 | 开关关闭时使用 `as_user` |
| `ROLE_CONFLICT` | 409 | 已持角色者再授另一角色；`user_roles` 主键冲突同样映射到此码 |
| `ROLE_LAST_HOLDER` | 409 | 删除/停用/撤销导致某角色持有者归零 |

三码追加到枚举末尾与 `_DEFAULT_STATUS` 末尾；后端文案进 `src/octop/i18n/intranet/{en,zh}.json` 的 `errors`，前端进 `dashboard/src/locales/intranet/{en,zh}.json` 的 `apiErrors`（`w0-04` 的三方相等测试读合并 bundle）。自授、越权授予、`PATCH role` 复用 `FORBIDDEN`（`details.reason` 区分）；非法角色值由 Pydantic `Literal` 返回 422；显式写管理类键沿用 `ValueError` → 400。

## 安全考虑

- 授权只有一个强制点；派生键不落库，撤销即时生效。
- 显式列拒收并忽略管理类键，堵住"把角色键直接塞进 permissions"的旁路。
- 自授守卫对 HTTP 生效；CLI 视为本机特权通道，不做自授判断但强制审计 `_cli:<os-user>`，且规则（互斥、最后持有者）与 HTTP 相同。
- `impersonate` 不属于任何角色，不能自授；开关默认关，关闭时拒绝也留痕。
- 管理角色不附带数据域：系统管理员看不到他人的专家、知识库、连接器。

## 测试策略

- 单测（先写，初始应失败）：新增与改写的文件见 tasks.md 任务 2-11，含"仅有角色、permissions 为空时生效"的正向断言。命令：`uv run pytest tests/unit/users tests/unit/api tests/unit/db/test_fork_admin_roles.py -q`。
- 集成：`tests/integration/test_three_admin_separation.py`（越权矩阵）及 tasks.md 所列既有文件。命令：`uv run pytest tests/integration -q -m "not live"`。
- PG（依赖 `w0-02`）：`tests/integration/test_postgresql_admin_roles.py`。命令：`OCTOP_TEST_DATABASE_URL=postgresql://octop:octop@localhost:5432/octop_test uv run pytest tests/integration/test_postgresql_admin_roles.py -q`。
- 前端：`cd dashboard && npx vitest run src/utils/permissions.test.ts src/routes/controlAdminPath.test.ts src/layouts/sidebarNav.test.ts && npx tsc -b && npm run lint`。
- i18n：`uv run pytest tests/unit/i18n -q`。

## 与其他 spec 的交接

- **依赖：** `w0-01` 的 `run_fork_migrations` 与 `_FORK_PY_STEPS`；`w0-03` 的 `AdminCredentials`、`bootstrap_admins`、`TEST_ADMIN_ACCOUNTS`（本 spec 改为三个真实账号，conftest 4 处建账槽位定为 `system`，因为建号归 `users` 键）；`w0-04` 的 i18n overlay、`CHANGELOG-intranet.md`、`docs/api-intranet.md`；`w1-01` 的 `_assert_may_assign_role` / `_assert_may_target`（本 spec 改为查 `authorization` 键与目标的 `admin_role`）与 `setup.completed` 标记；`w1-02` 已删除 ACP、mobile、control 四键，`fork_steps.strip_permission_keys` 可复用；`w1-03` 的 `service_control` 键；`w3-02` 的 `AuditContext`、`AuditRepo.write`、`impersonate.access` 钩子与 `ACTOR_ADMIN` 替换。
- **交付：** `w3-04` 使用 `admin_role` 做会话策略区分；`p2-03` 的审计员视图以 `audit_log` 键与 `audit_admin` 角色为门禁；`p2-05` 在 `visible_bases` 内实现三级 ACL；`p2-07` 按 `admin_role` 做前端管控；`p2-11` 把外部身份的角色映射落到 `authz.assign_admin_role`。
- **看似相关但不归本 spec：** `ACTOR_ADMIN` 替换与审计字段（`w3-02`）；审计保留期与删除端点（`w3-02`）；审计导出（`p2-03`）；`docs/api.md` 的 35 行 `| admin |` 不改（上游文档，fork 内容写 `docs/api-intranet.md`）；备份迁移式恢复对 `user_roles` 的捕获（`infra/backup/snapshot.py`）列为风险，由 `w4-02` 的备份演练覆盖。

## 风险与回滚

- **升级锁死：** 迁移漏把 `role='admin'` 转成 `system_admin`，则无人能管理。缓解：Python 步骤幂等、PG 与 SQLite 双测；CLI `assign-role` 离线自救。
- **授权者缺位：** 老库升级后没有安全管理员；启动 WARNING + CLI 补齐。
- **委派键丢失：** 被授予管理类键的普通用户升级后失去这些能力；按 `authz.migrate.strip` 审计清单补授角色。
- **静默回归：** `getattr` 带默认值与角色字符串比较删属性后不报错；由 `test_no_admin_bypass.py` 钉住。
- **上游冲突：** `permissions.ts`、`UsersListPanel.tsx`、`deps.py`、`setup.py` 上游改动频繁；逻辑下沉到新模块，上游文件只留小改。
- **回滚：** 按提交逆序 revert。`user_roles` 表保留无害；老代码下原管理员靠 `users.role='admin'` 仍有全权；被剥离的委派键需从升级前备份恢复。

## 待行方确认

- **D12（三员分立）：** 按默认假设实施。三个角色的键划分（尤其 `knowledge_settings`、`captcha`、`admin_console` 与全局用量的归属）请行方确认；管理角色持有者是否允许同时持有业务键（本设计允许）。
- **D14（机构/部门数据域）：** 不在本轮；管理角色一律无跨用户数据域。
- **D3（控制面数据库）：** 迁移只写 SQLite 与 PG 两份；达梦等第三方言另立项。
- **新增待确认（无 D 编号）：** 是否保留 `as_user` 通道（默认保留且关闭）；CLI 离线授权是否符合内控（若不符合，需改为双人口令方案）；升级后被剥离的委派键是否需要交付对照表。
