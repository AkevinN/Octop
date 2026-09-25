# 需求文档：授权地基与三员分立

> spec：`w3-03-authorization-foundation` ｜ 波次：Wave 3 ｜ 基线：`757fd12` ｜ 预估：31 人日
> 前置：`w0-01-fork-migration-namespace`、`w0-02-ci-gates`、`w0-03-test-auth-baseline`、`w0-04-fork-isolation-points`、`w1-01-security-hotfix`、`w1-02-capability-trim`、`w1-03-online-fetch-trim`、`w1-05-saas-decoupling`、`w3-02-audit-baseline` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 引言

**结论：** 交付后，Octop 的授权只由"账号的显式权限键 ∪ 其管理角色派生的权限键"决定，不再存在"admin 角色检查恒通过"的短路。`admin` 退化为三个互斥的管理角色：系统管理员、安全管理员、审计管理员。三个角色的权限键两两不相交，一个账号至多持有一个管理角色，授予角色与权限只能由安全管理员执行且不能授予自己。管理角色不附带任何跨用户数据可见性。

**背景。** 基线上 `user_has_permission` 对 `is_admin` 直接返回真，十余处代码直判角色，前端也有同样短路。任一管理员可读写全部用户的数据、给自己授予任意键，与等保三级的"三员分立、最小授权"冲突（D12）。

**为什么做。** 权限判定先收口成一个强制点，`w3-04`、`p2-05`、`p2-07`、`p2-11` 才有授权地基可依赖。

**范围内。**
- 删除 admin 绕过：后端 14 处（清单见 design.md"现状"），外加 `connectors.py` 两处角色字符串直比；前端 `permissions.ts` 4 处。
- 角色实体 `roles`、`user_roles`（fork 迁移），三员互斥，角色到权限键的派生。
- 存量数据清洗：存量 `role='admin'` 账号转为系统管理员；`users.permissions` 中的管理类键剥离并逐户留痕。
- 授权端点、自授守卫、最后持有者保护；CLI 离线授权命令。
- `as_user` 默认禁止；开启时要求独立的 `impersonate` 键，并经 `w3-02` 的 `AuditContext` 写审计。
- 知识库 `list_visible` 的 admin 绕过删除，含第四个调用点 `AgentManager.validate_knowledge_base_ids`。
- 安装向导一次创建三个管理员账号；测试鉴权基线从 `w0-03` 的"三槽位别名"切换为三个真实账号。
- 新受控路由登记进 `GATED_FILES`。

**范围外。**
- 审计字段集、`AuditContext`、`ACTOR_ADMIN` 14 处替换、`impersonate.access` 审计写入、审计保留期：`w3-02-audit-baseline`。
- 审计员视图、审计导出与防篡改：`p2-03-audit-tamper-proof`。
- 知识库三级 ACL（私有/授权/机构）：`p2-05-knowledge-retrieval`。
- 会话表、吊销、口令策略：`w3-04-session-and-password`。
- 统一认证与外部身份源的角色映射：`p2-11-identity-adapters`。
- 前端按角色的下载/复制/水印管控：`p2-07-frontend-controls`。
- 机构/部门数据域：不在本轮（D14）。
- ACP、远程手机、终端等已被 `w1-02` 删除的能力：不为其写任何代码。

## 需求

### 需求 1：删除角色短路授权
**用户故事：** 作为安全管理员，我希望任何操作是否放行只由账号实际持有的权限键决定，以便授权可被审查和收敛。
#### 验收标准
1. 当一个 `admin_role` 为空、`permissions=[]` 的账号调用任一 `require_permission(<键>)` 守卫的路由时，系统应当返回 403 且错误码为 `FORBIDDEN`。
2. 系统应当始终满足：`rg -n 'is_admin|user_is_admin' src/octop -g '*.py'` 零命中，`api/deps.py` 中不存在 `require_admin`。
3. 系统应当始终满足：`dashboard/src/utils/permissions.ts` 中不存在 `role === "admin"` 与 `"admin"` 伪键；`userCan({role:"admin",permissions:[]}, "users")` 为 `false`。
4. 系统应当始终满足：`api/routers/users.py`、`api/routers/connectors.py`、`infra/cron/delivery.py`、`cli/repl/runtime.py` 中不存在与 `"admin"` 的角色字符串比较。

### 需求 2：角色实体与三员互斥
**用户故事：** 作为合规负责人，我希望系统管理员、安全管理员、审计管理员由三个不同的人担任，以便满足三员分立。
#### 验收标准
1. 当 SQLite 与 PostgreSQL 各自跑完迁移后，系统应当存在 `roles` 表（含三条内置角色）与以 `user_id` 为主键的 `user_roles` 表，且 `_schema_version` 不变。
2. 如果对已持有某管理角色的账号再授予另一个管理角色，那么系统应当返回 409 `ROLE_CONFLICT`，且数据库中该账号仍只有一行 `user_roles`。
3. 系统应当始终满足：三个角色的派生键集两两交集为空，且并集等于全部 `category == "admin"` 的键减去 `impersonate`。

### 需求 3：角色到权限键的派生
**用户故事：** 作为系统管理员，我希望被授予角色后立即获得该角色的全部权限，而不需要逐个勾选权限键。
#### 验收标准
1. 当一个账号只被授予 `system_admin`、`users.permissions` 列为空时，`user_has_permission(user, "providers")` 应当为真，`user_has_permission(user, "security")` 应当为假，`GET /api/admin/security` 返回 403，`GET /api/auth/me` 的 `permissions` 等于系统管理员键集，且数据库里该账号的 `permissions` 列仍为 `[]`。
2. 当账号的管理角色被撤销时，其下一次请求应当立即失去派生键，不需要重新登录。
3. 如果写入显式权限的请求包含管理类键（`impersonate` 除外），那么系统应当返回 400 并拒绝写入。
4. 系统应当始终忽略 `users.permissions` 中残留的管理类键：它们不参与 `user_has_permission` 与 `effective_permissions`。

### 需求 4：授权操作、自授守卫与最后持有者
**用户故事：** 作为安全管理员，我希望只有我能授予角色和权限且不能给自己授权，以便不存在自我提权路径。
#### 验收标准
1. 当持有 `authorization` 键的账号调用 `PUT /api/users/{id}/admin-role` 或修改他人的 `permissions` 时，系统应当成功，并写一条 actor 为该账号用户名的审计。
2. 如果不持有 `authorization` 键的账号（含系统管理员、审计管理员）授予角色或修改权限，那么系统应当返回 403。
3. 如果操作者修改自己的管理角色或显式权限，那么系统应当返回 403，`error.details.reason == "self_assign"`。
4. 如果删除、停用或撤销角色会让任一管理角色的持有者归零，那么系统应当返回 409 `ROLE_LAST_HOLDER`，三个角色各有一条用例。
5. 当 `PATCH /api/users/{id}` 携带与现值不同的 `role` 字段时，系统应当返回 403，提示改用 admin-role 端点。

### 需求 5：存量数据清洗与升级不锁死
**用户故事：** 作为运维，我希望升级后原管理员仍能登录并继续管理，以便升级不造成停机。
#### 验收标准
1. 当一个含 `role='admin'` 账号的旧库升级后，这些账号应当各有一行 `system_admin` 的 `user_roles`，登录后能访问 `GET /api/admin/overview`。
2. 当旧库中某账号的 `permissions` 含管理类键时，迁移应当把这些键剥离，只留下非管理类键与 `impersonate`，并为每个被剥离的账号写一条 `action='authz.migrate.strip'` 的审计，payload 列出被剥离的键。
3. 迁移步骤应当始终幂等：重复执行不改变数据，缺 `users` 表时跳过。
4. 在安全管理员或审计管理员持有者为零期间，系统应当在启动日志打印一条 WARNING，指明用 CLI `octop user assign-role` 补齐。

### 需求 6：as_user 默认禁止
**用户故事：** 作为合规负责人，我希望跨用户代操作默认不存在，开启时必须显式授权并留痕。
#### 验收标准
1. 在默认配置期间，任何账号以 `?as_user=<他人 id>` 调用 `/api/agents/{aid}/…` 或 `/api/usage/summary` 时，系统应当返回 403 `AS_USER_DISABLED`，并经 `AuditContext` 写一条 `action='impersonate.denied'` 的审计。
2. 如果 `allow_impersonation=true` 但账号不持显式 `impersonate` 键，那么系统应当返回 403 `FORBIDDEN`。
3. 当开关开启且账号持有 `impersonate` 键时，请求应当成功，且 `GET /api/admin/audit-log?action=impersonate.access` 至少返回一行，actor 为调用者用户名。
4. 系统应当始终满足：`OctopError(ErrorCode.AS_USER_DISABLED, "x").status == 403`，`impersonate` 不属于任何角色的派生键集。

### 需求 7：管理权与数据域分离
**用户故事：** 作为业务用户，我希望管理员不能因为角色就读写我的专家、知识库和连接器。
#### 验收标准
1. 当系统管理员不带 `as_user` 请求 `GET /api/agents/{alice 的非共享 agent}` 或其 `workspace/tree` 时，系统应当返回 403。
2. 当系统管理员调用 `GET /api/knowledge-bases` 时，系统应当只返回自己拥有的与可见的库；以 alice 的私有库 id 调用 `AgentManager.validate_knowledge_base_ids` 应当抛 `KNOWLEDGE_NOT_FOUND`。
3. 系统应当始终满足：知识库可见性（HTTP、对话检索、cron 投递、agent 绑定校验）全部经同一个 `list_visible` 判定，不存在 `list_all` 分支；`rg -n 'user_is_admin' src/octop` 零命中。
4. 当系统管理员列出他人的连接器实例时，`can_manage` 应当为 `false`；修改他人技能包或已发布专家时，仅持 `skill_packages` 键者成功。
5. 当持 `admin_console` 键的账号调用 `GET /api/admin/usage/*` 时，系统应当成功；不持键者返回 403。

### 需求 8：安装向导三账号
**用户故事：** 作为实施人员，我希望安装时一次建好三个管理员，以便系统从第一天起就三员分立。
#### 验收标准
1. 当向导调用 `POST /api/setup/initial-admins` 且三个用户名、三个口令互不相同时，系统应当在一个事务里创建三个账号并各授予一个管理角色，返回 201。
2. 如果三个用户名或口令有重复，那么系统应当返回 422 且不创建任何账号。
3. 系统应当始终不再提供 `POST /api/setup/initial-admin`（返回 404），前端两个调用点改调新端点。
4. 当 `bootstrap_admins` 建立测试环境时，三个槽位应当是三个互不相同的账号，经 `env` 链的集成用例全绿。

### 需求 9：CLI 离线授权
**用户故事：** 作为运维，我希望在 HTTP 不可用或无安全管理员时仍能离线补齐角色，并且留痕。
#### 验收标准
1. 当执行 `octop user assign-role <u> security_admin`、`octop user unassign-role <u>`、`octop user grant <u> <键>…`、`octop user revoke <u> <键>…` 时，系统应当执行与 HTTP 相同的互斥、键校验与最后持有者规则，并写一条 actor 形如 `_cli:<os-user>` 的审计。
2. 如果执行 `octop user role <u> admin` 或 `octop user create --role admin`，那么命令应当以非 0 退出并提示改用 `assign-role`。
3. 当执行 `octop user permissions <u>` 时，命令应当打印显式键、管理角色与派生键三部分。

### 需求 10：前端适配
**用户故事：** 作为管理员，我希望界面只展示我实际有权的入口，并能在用户页管理角色。
#### 验收标准
1. 当 `cd dashboard && npx vitest run src/utils/permissions.test.ts` 执行时，`role="admin"`、`permissions=[]` 的用户对 `userCan`、`userCanAny`、`canAccessPath` 全部返回 `false`，`/admin/storage`、`/admin/shared-models`、`/admin/agents` 按各自映射的键判定。
2. 当安全管理员在用户页为他人选择管理角色时，界面应当调用 admin-role 端点；编辑管理员账号不会再提交 `permissions: []`。
3. 系统应当始终满足：新增文案只写进 `dashboard/src/locales/intranet/{en,zh}.json` 与 `src/octop/i18n/intranet/{en,zh}.json`，`cd dashboard && npx tsc -b && npm run lint` 通过。
