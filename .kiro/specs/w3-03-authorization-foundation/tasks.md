# 实施计划：授权地基与三员分立

> spec：`w3-03-authorization-foundation` ｜ 波次：Wave 3 ｜ 基线：`757fd12` ｜ 预估：31 人日
> 前置：`w0-01-fork-migration-namespace`、`w0-02-ci-gates`、`w0-03-test-auth-baseline`、`w0-04-fork-isolation-points`、`w1-01-security-hotfix`、`w1-02-capability-trim`、`w1-03-online-fetch-trim`、`w1-05-saas-decoupling`、`w3-02-audit-baseline` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

每个顶层任务完成后可独立提交；提交前运行任务内的验证命令。

- [ ] 1. 确认前置 spec 已合入并记录基线
  - 改动：无代码改动。确认已有 `infra/db/fork_migrate.py::_FORK_PY_STEPS`、两处 i18n overlay、`tests/support/auth.py::bootstrap_admins`、`AuditContext`，且 `api/routers/acp.py`、`infra/mobile/` 已删除；记录当前管理类键并与 design.md 的角色划分比对，有差异先改 design.md。
  - 验证：`make all && rg -n 'is_admin|user_is_admin' src/octop -g '*.py' -c`
  - _需求：1.2_

- [ ] 2. 权限模型测试先行
  - [ ] 2.1 新增 `tests/unit/users/test_admin_roles.py`：三角色键集两两不相交、并集 = 管理类键 − `impersonate`；仅授 `system_admin`、`permissions=[]` 时 `providers` 为真、`security` 为假、`effective_permissions` 等于系统管理员键集；显式列中的管理类键被忽略；`validate_permission_keys(["users"])` 抛 `ValueError`。
    - 验证：`uv run pytest tests/unit/users/test_admin_roles.py -q`（此时应失败）
    - _需求：2.3, 3.1, 3.3, 3.4_
  - [ ] 2.2 新增 `tests/unit/api/test_no_admin_bypass.py`：读源码断言 `is_admin`、`user_is_admin`、`require_admin` 零出现；需求 1.4 列出的四个文件无 `"admin"` 角色比较；`list_all(` 不出现在 `infra/knowledge/`、`infra/cron/delivery.py`、`infra/gateway/process/processor.py`。
    - 验证：`uv run pytest tests/unit/api/test_no_admin_bypass.py -q`（此时应失败）
    - _需求：1.2, 1.4, 7.3_

- [ ] 3. fork 迁移：角色表与存量清洗
  - 改动：新增 `src/octop/infra/db/migrations/forkNNN_admin_roles.sql` 与 `.pg.sql`（`roles`、`user_roles`、三条种子）；在 `fork_migrate.py::_FORK_PY_STEPS` 登记 `migrate_admin_roles`（放在新文件 `src/octop/infra/db/fork_steps_authz.py`）：`role='admin'` → `system_admin`，剥离快照管理类键并逐户写 `authz.migrate.strip` 审计，`_table_exists` 守卫。新增 `src/octop/infra/db/repos/roles.py::RoleRepo`，在 `src/octop/infra/db/services.py::RepoBundle` 照 `user_policy_repo` 接线。先写 `tests/unit/db/test_fork_admin_roles.py`（主键冲突、转换、剥离留痕、幂等、缺表跳过）。
  - 验证：`uv run pytest tests/unit/db/test_fork_admin_roles.py tests/unit/db -q`
  - _需求：2.1, 5.1, 5.2, 5.3_

- [ ] 4. 身份与用户行携带管理角色
  - 改动：`src/octop/infra/users/identity.py` 新增 `AdminRole`、`User.admin_role`，删除 `is_admin`；`src/octop/infra/db/repos/users.py` 的 `UserRow` 增加 `admin_role`，`get`/`get_by_username`/`list` LEFT JOIN；`src/octop/infra/users/manager.py` 8 处 `User(...)` 构造补 `admin_role`。本任务只让类型通过：其余 `is_admin` 使用点暂以 `user.admin_role is not None` 过渡，任务 7-11 逐一删除。同步改写 `tests/unit/test_identity.py`。
  - 验证：`make typecheck && uv run pytest tests/unit/test_identity.py tests/unit/db/test_repo_users.py tests/unit/test_user_manager.py -q`
  - _需求：3.2_

- [ ] 5. 角色派生与键目录
  - 改动：`src/octop/infra/users/permissions.py` 新增 `authorization`、`audit_log`、`impersonate`（`category="admin"`）、`ROLE_PERMISSIONS`、`permissions_for_role`、`is_role_derived_key` 与导入期断言；改写 `user_has_permission`、`effective_permissions`（删除 ≈L232、≈L253 分支）、`validate_permission_keys(allow_admin_keys=False)`。改写 `tests/unit/users/test_permissions.py` 的绕过用例与 `tests/unit/api/test_permissions_api.py` 的 admin 放行用例为拒绝断言。
  - 验证：`uv run pytest tests/unit/users tests/unit/api/test_permissions_api.py -q`
  - _需求：1.1, 2.3, 3.1, 3.2, 3.3, 3.4_

- [ ] 6. 新错误码与 overlay 文案
  - 改动：`src/octop/infra/errors.py` 在 `ErrorCode` 末尾追加 `AS_USER_DISABLED`、`ROLE_CONFLICT`、`ROLE_LAST_HOLDER`，在 `_DEFAULT_STATUS` 末尾追加 403/409/409；文案写进 `src/octop/i18n/intranet/{en,zh}.json` 的 `errors` 与 `dashboard/src/locales/intranet/{en,zh}.json` 的 `apiErrors`。在 `test_admin_roles.py` 加一条逐码构造 `OctopError` 的断言。
  - 验证：`uv run pytest tests/unit/i18n tests/unit/users/test_admin_roles.py -q`
  - _需求：6.4, 10.3_

- [ ] 7. 管理路由收口
  - 改动：`src/octop/api/deps.py` 删除 `require_admin`；`src/octop/api/routers/admin.py` 的 `/audit-log` 改为 `require_permission("audit_log")`；`src/octop/api/routers/usage.py` 的 `admin_summary`、`admin_export` 改为 `Depends(require_permission("admin_console"))`；`tests/unit/api/test_acl_gate_coverage.py` 的 `GATED_FILES` 追加 `"routers/usage.py"`，删除已失效的 `require_admin(` 允许项，`test_as_user_still_requires_admin` 改写为断言 `common/agent.py` 调用 `assert_impersonation_allowed`。
  - 验证：`uv run pytest tests/unit/api/test_acl_gate_coverage.py tests/integration/test_usage_api.py -q`
  - _需求：1.1, 1.2, 7.5_

- [ ] 8. 授权领域规则与 HTTP 端点
  - [ ] 8.1 先写 `tests/unit/users/test_authz.py`：互斥 → `ROLE_CONFLICT`；自授 → `FORBIDDEN` 且 `reason=self_assign`；三角色各自最后持有者 → `ROLE_LAST_HOLDER`；授予后 `users.role` 同步；CLI 路径（`actor_user=None`）跳过自授但保留其余规则。
    - 验证：`uv run pytest tests/unit/users/test_authz.py -q`（此时应失败）
    - _需求：2.2, 4.3, 4.4_
  - [ ] 8.2 新增 `src/octop/infra/users/authz.py`；`src/octop/infra/users/manager.py` 新增 `set_admin_role`，`create` 对 `Role.ADMIN` 拒绝、`permissions` 缺省为 `BASELINE_PERMISSIONS`，`set_role` 拒绝 `Role.ADMIN`，删除/停用前调 `assert_not_last_holder`。
    - 验证：`uv run pytest tests/unit/users -q`
    - _需求：2.2, 4.4_
  - [ ] 8.3 `src/octop/api/routers/users.py`：新增 `PUT /users/{user_id}/admin-role`（`require_permission("authorization")`，`summary` 与 Pydantic 模型齐全）；`patch_user` 的 `permissions` 改为要求 `authorization`、`role` 变更一律 403；`_assert_can_assign` 删除 admin 放行；`_can_manage_users` / `_assert_not_last_user_manager` 改为调 `authz.assert_not_last_holder`；`w1-01` 的 `_assert_may_assign_role`、`_assert_may_target` 改为查 `authorization` 键与目标 `admin_role`；`_row_to_dict` 与 `src/octop/api/routers/auth.py::_user_json` 返回 `admin_role`。
    - 验证：`uv run pytest tests/integration/test_users_api.py tests/integration/test_auth_flow.py -q`
    - _需求：4.1, 4.2, 4.3, 4.5_

- [ ] 9. as_user 默认禁止
  - 改动：`src/octop/config.py` 三触点新增 `allow_impersonation`（字段、`OCTOP_ALLOW_IMPERSONATION` 覆盖、`OctopConfig(...)` 构造）；新增 `src/octop/infra/users/impersonation.py::assert_impersonation_allowed`（拒绝时经 `AuditContext` 写 `impersonate.denied`）；`api/common/agent.py::require_agent_row` 与 `api/routers/usage.py::_resolve_user_scope` 的 as_user 分支改调它。先写 `tests/unit/users/test_impersonation.py`（三态）与 `tests/unit/test_config.py` 用例；`tests/integration/test_usage_api.py` 的 as_user 用例改为默认 403、开启并授键后 200。
  - 验证：`uv run pytest tests/unit/users/test_impersonation.py tests/unit/test_config.py tests/integration/test_usage_api.py -q`
  - _需求：6.1, 6.2, 6.3, 6.4_

- [ ] 10. 知识库可见性单点
  - 改动：新增 `src/octop/infra/knowledge/visibility.py::visible_bases`；删除 `src/octop/infra/knowledge/service.py` 全部 `is_admin` 形参与 `list_all` 分支，`src/octop/api/routers/knowledge_bases.py` 删除 `_is_admin` 及 19 处关键字参数；`infra/knowledge/retrieve.py`、`infra/gateway/process/processor.py::_attach_turn_knowledge_config`、`infra/cron/delivery.py`、`infra/agents/manager.py::validate_knowledge_base_ids`（单行改调）都走 `visible_bases`；删除 `configurable["user_is_admin"]` 的全部生产者与消费者（清单见 design.md"现状"）。同步改写 `tests/unit/knowledge/`、`tests/unit/gateway/` 的相关用例。
  - 验证：`uv run pytest tests/unit/knowledge tests/unit/gateway tests/unit/api/test_no_admin_bypass.py -q && make typecheck`
  - _需求：7.2, 7.3_

- [ ] 11. 专家、连接器、技能包数据域
  - 改动：`src/octop/api/common/agent.py` 的 `assert_agent_owner`、`_user_may_access` 删除绕过；`src/octop/api/routers/connectors.py` ≈L433、≈L517 删除 `user.role == "admin"`；`src/octop/infra/skills/skill_package_store.py::can_mutate` 与 `src/octop/infra/agents/experts/publish.py::assert_can_mutate_published` 改为 `user_has_permission(user, "skill_packages")`；`src/octop/api/routers/setup.py` ≈L148、≈L435 改为按 `admin_role`。`tests/integration/test_boundary_authz.py` 把 ≈L47 用例改名为 `test_system_admin_cannot_get_alices_agent` 并改期望为 403；改写 `tests/unit/api/test_agent_access.py`。
  - 验证：`uv run pytest tests/unit/api/test_agent_access.py tests/integration/test_boundary_authz.py tests/integration/test_connectors_api.py tests/integration/test_skill_packages_api.py tests/unit/api/test_no_admin_bypass.py -q`
  - _需求：1.4, 7.1, 7.4_

- [ ] 12. 安装向导三账号
  - 改动：`src/octop/api/routers/setup.py` 删除 `initial_admin`，新增 `initial_admins`（事务内建三账号并各授一角色，重复用户名或口令返回 422）；计数门槛 ≈L114、≈L145 按 3 个引导账号改写（以 `w1-01` 合入后的形态为准），`finish` 取系统管理员。`src/octop/cli/commands/init.py` 建号后授予 `system_admin` 并提示补齐另两角色。新增服务启动时 `RoleRepo.missing_roles()` 非空打印 WARNING（放在 `infra/users/authz.py`，`infra/server.py` 只加一行调用）。
  - 验证：`uv run pytest tests/integration/test_setup_wizard.py tests/integration/test_setup_bootstrap.py -q`
  - _需求：5.4, 8.1, 8.2, 8.3_

- [ ] 13. 测试鉴权基线切换为三个真实账号
  - 改动：`tests/support/auth.py` 的 `TEST_ADMIN_ACCOUNTS` 改为三个不同账号，`bootstrap_admin` / `bootstrap_admins` 改调 `/api/setup/initial-admins`，删除 `w0-03` 的全量键授予步骤，自测改为断言三账号互不相同；`tests/integration/conftest.py` 4 处建账调用槽位定为 `system`；`tests/support/scenarios.py::bootstrap_boundary_env` 相应调整；5 个 setup 契约文件（`test_setup_wizard.py`、`test_setup_database.py`、`test_setup_bootstrap.py`、`test_auth_flow.py`、`test_postgresql_control_plane.py`）改调新契约。
  - 验证：`uv run pytest tests/integration -q -m "not live"`
  - _需求：8.3, 8.4_

- [ ] 14. 三员横向越权矩阵
  - 改动：新增 `tests/integration/test_three_admin_separation.py`：3 角色 × 管理面的越权矩阵（审计管理员访问 `/api/admin/security`、系统管理员访问 `/api/admin/audit-log` 与 admin-role 端点、安全管理员 `POST /api/users` 均 403）；仅有角色、`permissions` 为空时本角色路由 200；授角色审计 actor 为真实用户名；撤销后下一次请求即 403。
  - 验证：`uv run pytest tests/integration/test_three_admin_separation.py -q`
  - _需求：3.1, 3.2, 4.1, 4.2_

- [ ] 15. CLI 离线授权
  - 改动：`src/octop/cli/commands/user.py` 新增 `assign-role`、`unassign-role`、`grant`、`revoke`、`permissions`；`role` 与 `create --role` 拒绝 `admin`。`src/octop/cli/support/offline_ops.py` 只做薄封装，调用 `infra/users/authz.py`，审计 actor 为 `_cli:<os-user>`（`AuditContext` 的 `actor_kind="cli"`）。先写 `tests/unit/cli/test_user_authz_cmd.py`（`CliRunner`，`monkeypatch.setenv("OCTOP_HOME", str(tmp_path))`）。
  - 验证：`uv run pytest tests/unit/cli/test_user_authz_cmd.py -q`
  - _需求：9.1, 9.2, 9.3_

- [ ] 16. 前端权限判定去短路
  - 改动：`dashboard/src/utils/permissions.ts` 删除 `userCan`、`userCanAny`、`canAccessKeys` 的 admin 短路与 `"admin"` 伪键；`/admin/` 兜底逐条映射 `/admin/storage`、`/admin/shared-models`、`/admin/agents`，其余返回空数组；`PERM` 增加 `authorization`、`auditLog`；`SECURITY_TAB_PERMISSIONS.audit` 改为 `"audit_log"`。新增 `dashboard/src/utils/permissions.test.ts`；改写 `dashboard/src/routes/controlAdminPath.test.ts` 与 `dashboard/src/layouts/sidebarNav.test.ts` 的 `permissions: ["*"]` 夹具。
  - 验证：`cd dashboard && npx vitest run src/utils/permissions.test.ts src/routes/controlAdminPath.test.ts src/layouts/sidebarNav.test.ts && npx tsc -b`
  - _需求：1.3, 10.1_

- [ ] 17. 前端用户页与业务页
  - 改动：`dashboard/src/pages/Admin/Users/UsersListPanel.tsx` 增加管理角色选择（仅持 `authorization` 可见），删除 ≈L1094、≈L1185 的 `permissions: []` 与 `permAll` 分支，勾选只列非管理类键；`dashboard/src/api/modules/invites.ts`（现有 `/users` 调用所在模块）新增 `setAdminRole`；`dashboard/src/pages/Control/TokenUsage/index.tsx` ≈L833 改为 `userCan(user, "admin_console")`；`SkillPackages/index.tsx` ≈L108 与 `Experts/index.tsx` ≈L101 改为 `userCan(user, "skill_packages")` 或创建者；`KnowledgeBases/index.tsx` ≈L176 只看属主。文案进 `dashboard/src/locales/intranet/{en,zh}.json`。
  - 验证：`cd dashboard && npx tsc -b && npm run lint`
  - _需求：10.2, 10.3_

- [ ] 18. 前端安装向导三账号
  - 改动：`dashboard/src/pages/Setup/steps/AdminStep.tsx` 改为三组账号录入并前端校验互不相同；`dashboard/src/pages/Setup/wizardClient.ts` ≈L156 与 `dashboard/src/api/modules/auth.ts` ≈L162 改调 `/setup/initial-admins`。
  - 验证：`cd dashboard && npx tsc -b && npm run lint && npm run test`
  - _需求：8.3, 10.3_

- [ ] 19. PostgreSQL 验证
  - 改动：新增 `tests/integration/test_postgresql_admin_roles.py`（用 `tests/support/postgresql.py` 门控）：fork 迁移建表、主键互斥、`role='admin'` 转换、剥离留痕、仅有角色时的权限生效。
  - 验证：`OCTOP_TEST_DATABASE_URL=postgresql://octop:octop@localhost:5432/octop_test uv run pytest tests/integration/test_postgresql_admin_roles.py -q`
  - _需求：2.1, 2.2, 5.1, 5.2_

- [ ] 20. 收尾
  - 改动：删除本 spec 引入的孤儿符号；`CHANGELOG-intranet.md` 记录破坏性变更（三员替代 admin、`/setup/initial-admin` 删除、`PATCH /users/{id}` 门禁变更、`/admin/audit-log` 改用 `audit_log` 键、as_user 默认禁止）；`docs/api-intranet.md` 新增 admin-role、initial-admins、as_user 章节与三角色键表；抽查 `/api/docs`。
  - 验证：`make all && cd dashboard && npx tsc -b && npm run lint && npm run test`
  - _需求：1.2, 1.3, 10.3_
