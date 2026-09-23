# 设计文档：前端管控

> spec：`p2-07-frontend-controls` ｜ 波次：二期 ｜ 基线：`757fd12` ｜ 预估：19 人日
> 前置：`w1-02-capability-trim`, `w3-02-audit-baseline`, `w3-04-session-and-password` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 概述

在既有一期加固（能力开关、下载后端校验、会话吊销）之上，为 dashboard 补齐水印、空闲登出触发、复制/下载前端出口收敛、高危操作二次确认与重认证。本 spec 只消费一期已交付的基础设施，不重建它们。

## 现状（基线 `757fd12`，已核实的关键锚点）

- `dashboard/src/utils/copyText.ts::copyText()`（≈L13）是全仓唯一的写剪贴板实现（`navigator.clipboard.writeText` 优先，失败回退 `textarea` + `execCommand("copy")`），当前无策略判断。
- `dashboard/src/components/AuthGuard.tsx` 的 `check()` 有一条 catch 分支（≈L76-83）：`/auth/status` 失败时仍 `setAuthed(true)`，注释自述"Backend unreachable — let the user through"，此时 `user===null`；渲染出口在 `CurrentUserProvider`（≈L107-111）。
- `dashboard/src/pages/Control/Terminal/components/TerminalView.tsx::attachCustomKeyEventHandler`（≈L123，放行注释在 ≈L126）对 Ctrl+Shift+C 直接放行。
- `dashboard/src/pages/Agent/Workspace/components/CodeEditor.tsx` 是全仓唯一的 Monaco 挂载点（`lazy` import ≈L19、`OnMount` 类型 ≈L15、`handleMount` ≈L83）。
- `src/octop/api/deps.py::sign_token`（≈L28）当前签名为 `sign_token(secret, *, sub, uname, role, ttl_seconds=86400)`，无扩展位；**`w3-04` 会把它改成去掉默认 TTL、加入 `sid`**（`w3-04-session-and-password/design.md` ≈L11、≈L26），本 spec 落地时以 `w3-04` 合入后的真实签名为准。
- `src/octop/infra/errors.py` 的 `ErrorCode`（≈L13）与 `_DEFAULT_STATUS` 是两处必须同批改的位置，`OctopError.__post_init__` 无保护字典取值，漏登记即 `KeyError`。
- `src/octop/api/routers/settings.py` 的 `get_capabilities`（≈L72）与 `CaptchaPairView`（≈L85）之间是插入新端点的位置，不要追加到文件尾。
- `w3-02-audit-baseline` 已交付 `api/common/download_guard.py::assert_download_allowed(server, user, *, action, target)`，其 design.md 明确写"`p2-07` 之后在同一函数里加按角色的策略"（≈L38）。
- `w3-04-session-and-password` 已交付 `infra/users/sessions.py::SessionManager`（`create`/`validate`/`revoke`/`revoke_all`），`logout → revoke(sid)`，配置键 `session_idle_timeout_seconds`（`OCTOP_SESSION_IDLE_TIMEOUT`，默认 1800）（≈L27、≈L74）。

> 二期实施纪律：一期落地后代码会有明显漂移，下文除上述已核实锚点外均写"实施时以一期落地后的代码重新定位"，不写具体行号。

## 方案

1. 新增 fork 归属的 `infra/ui_controls` 策略子包，承载水印/空闲登出/复制/下载/高危确认五组策略，照抄 `infra/agents/security/policy_store.py` 的 KV 模式。
2. 管理端读写走 `GET/PUT /api/admin/security/ui-controls`（复用 `security` 权限键），运行时下发走 `GET /api/settings/ui-controls`（任意已登录用户可读）。
3. 水印用 `createPortal` 挂到 `document.body`，绕开 React 子树位置限制，自建 `MutationObserver` 做防摘除兜底。
4. 空闲登出用前端活动侦测 + `localStorage` 广播做跨标签页同步，到期调用既有登出接口触发 `w3-04` 的会话吊销，不重建吊销逻辑。
5. 复制/下载分别收敛到 `copyText.ts` / 新增 `downloadBlob.ts` 两个唯一出口，并对终端、Monaco、文本选区三类特殊路径单独处理；下载后端强制校验只读取本 spec 新增的 `allow_roles` 字段，写入 `w3-02` 已有的判定分支。
6. 高危二次确认用自建受控 `Modal`（`.tsx`）实现打字校验；重认证走新增 `POST /api/auth/reauth`，签发 `scope` 受限、TTL ≤120s 的短令牌，服务端双向拒绝误用。

## 组件与接口

**后端：**

| 路径 | 改动 | 说明 |
|---|---|---|
| `src/octop/infra/ui_controls/policy_store.py`（新增，含 `__init__.py`） | 新增子包 | `UiControlsPolicy` 冻结 dataclass（`watermark`/`idle_logout`/`copy`/`download{enabled, allow_roles}`/`danger_confirm`）+ `UiControlsStore`（`settings` 表 KV） |
| `src/octop/infra/db/services.py` | 修改 | `SharedServices` 加 `ui_controls` 只读 `@property`；`frozen dataclass`，不得用 `__post_init__` 缓存 |
| `src/octop/api/routers/settings.py` | 修改 | 新增 `GET /settings/ui-controls`（`Depends(current_user)`），按角色计算生效策略，不回显密钥字段 |
| `src/octop/api/routers/security.py` | 修改 | 新增 `GET/PUT /ui-controls`（`Depends(require_permission('security'))`），PUT 写审计 `action='security.ui_controls.update'` |
| `src/octop/api/routers/auth.py` | 修改 | 新增 `POST /reauth`：SSO-only 返回明确错误码；否则校验口令，成功签发 `scope='reauth'`、TTL ≤120s 短令牌；失败 401 且不进登录失败计数路径 |
| `src/octop/api/deps.py` | 修改 | 给签发令牌函数补 `scope` 扩展位（扩展 `sign_token` 还是新增 `sign_scoped_token`，以 `w3-04` 合入后签名决定）；新增 `require_reauth()` 校验 `X-Octop-Reauth` 头 `scope=='reauth'`；普通令牌解析路径拒绝带 `scope` 的令牌 |
| `src/octop/api/common/download_guard.py` | 修改（消费方） | 在 `w3-02` 的 `assert_download_allowed` 内追加读取 `ui_controls.download.allow_roles` 的判定分支 |
| `src/octop/infra/errors.py` | 修改 | `ErrorCode` 末尾追加 `REAUTH_REQUIRED`，`_DEFAULT_STATUS` 同批追加 `403`（`COPY_FORBIDDEN` 无可靠服务端强制点，不登记） |
| `src/octop/i18n/{en,zh}.json` | 修改 | `errors.REAUTH_REQUIRED` 中英文案 |
| `src/octop/infra/db/migrations/forkNNN_user_employee_id.sql` / `.pg.sql`（新增） | 新增 | `users` 加 `employee_id TEXT`（可空），水印缺失时降级为 user id |
| `src/octop/infra/db/repos/users.py`、`api/routers/auth.py::_user_json` | 修改 | 映射并返回 `employee_id` |

**前端：**

| 路径 | 改动 | 说明 |
|---|---|---|
| `dashboard/src/hooks/useUiControls.ts`（新增） | 拉取 `GET /api/settings/ui-controls`，模块级单飞缓存 + `getUiControlsSync()`，未加载完成时默认"全允许" |
| `dashboard/src/components/SecurityWatermark.tsx`（新增） | `createPortal` 挂 `document.body`；自建 `MutationObserver` 防摘除；`@media print` 补样式；`user===null` 降级渲染 |
| `dashboard/src/components/AuthGuard.tsx` | 修改 | 渲染出口挂 `<SecurityWatermark />` + `useIdleLogout()`；离线降级分支（`user===null`）下两者仍生效 |
| `dashboard/src/hooks/useIdleLogout.ts`（新增） | 活动事件侦测 + `localStorage` 广播同步 + 到期调用既有登出接口 |
| `dashboard/src/utils/copyText.ts` | 修改 | 入口读 `getUiControlsSync()`，禁用时直接 `return false` |
| `dashboard/src/utils/selectionGuard.ts`（新增） | 禁用复制时对 `document` 的 `copy`/`cut` 事件 `preventDefault` |
| `TerminalView.tsx` / `CodeEditor.tsx` | 修改 | 分别收敛 Ctrl+Shift+C 放行分支、Monaco `onMount` 里屏蔽剪贴板 action |
| `dashboard/src/utils/downloadBlob.ts`（新增） | 唯一下载出口 `triggerDownload(blob|url, filename)`，与现状实现行为等价 |
| 既有 14 处 `a.download` 调用点（清单以实施时 `rg "\.download\s*="` 结果为准） | 修改 | 改用 `triggerDownload` |
| `dashboard/src/utils/dangerConfirm.tsx`（新增） | 自建受控 `Modal`：打字校验资源名 + 可选重认证，至少接入删除专家/用户、恢复备份三处 |
| `pages/Settings/Security/index.tsx`、`utils/permissions.ts`、`AuditLogPanel.tsx` | 修改 | 新增管理 tab；`ACTION_OPTIONS` 加 `security.ui_controls.update`、`auth.reauth.failed`（`ui.download*` 已由 `w3-02` 登记） |
| `dashboard/src/locales/{en,zh}.json` | 修改 | `securityUiControls.*`、`security.tabUiControls`、`adminAudit.actions.*`、`apiErrors.REAUTH_REQUIRED` |

## 数据模型

`forkNNN_user_employee_id`（号不预占，按合入顺序取号）：

- `users.employee_id TEXT`，可空，无默认值；不回填存量数据（新员工号在行方身份系统对接后由后续维护流程补齐）。
- SQLite 走 `migrate.py` 的幂等 `_ensure_column` 分支（不走 `.sql` 直接 `executescript`，避免重复执行报 duplicate column）；PostgreSQL 走 `.pg.sql` 的 `ADD COLUMN IF NOT EXISTS`。
- 不改 `_schema_version`；不改 `tests/unit/db/test_db_pool.py` 的 `assert v == 15` 类断言（fork 迁移走独立的 `_fork_schema_version` 水位表，由 `w0-01` 提供）。

`ui_controls_policy`（`settings` 表 KV，key 固定，JSON 值）：字段见"组件与接口"表 `UiControlsPolicy`；无需新表。

## 配置

无新增 `config.py` 键。策略走 `settings` 表 KV（管理端可改），不是启动期静态配置；空闲阈值默认值由 `w3-04` 的 `session_idle_timeout_seconds`（`OCTOP_SESSION_IDLE_TIMEOUT`）提供参考，前端倒计时阈值应不大于该值，避免"前端还没提示、服务端已判定超时"的体验断层。

## 错误处理

新增 `ErrorCode.REAUTH_REQUIRED`，`_DEFAULT_STATUS[REAUTH_REQUIRED] = 403`，同批加 `src/octop/i18n/{en,zh}.json` 的 `errors.REAUTH_REQUIRED` 与 `dashboard/src/locales/en.json` 的 `apiErrors.REAUTH_REQUIRED`（`dashboard/src/locales/zh.json` 无机器约束，但必须人工同步，保持 `apiErrors` 现状键集一致）。`DOWNLOAD_FORBIDDEN` 已由 `w3-02` 登记，本 spec 不重复添加。复用已有码：口令锁定复用现有登录失败相关码，不新造。

## 安全考虑

- 水印/复制/下载均为**威慑与事后溯源手段**，不是访问控制：挡不住拍屏、采集卡、F12 读 DOM、直接调用 API、OCR；真正闭环依赖网络出口管控、终端准入（EDR/DLP）与审计追责，不得宣称"已完全闭环"。
- 重认证令牌必须与普通访问令牌互斥：签发带 `scope='reauth'`，校验强制核对；两个方向（普通令牌冒充重认证、重认证令牌冒充 Bearer）都要专门集成用例覆盖，不能只测正向。
- 重认证失败不得累加登录失败计数（避免撞上 `login_max_attempts`/`login_lockout_seconds`）。
- SSO-only 用户（`password_hash` 可空）的重认证必须显式降级，不得 500 或无声放行。

## 测试策略

- 单测：`uv run pytest tests/unit/api/test_auth.py tests/unit/api/test_settings.py tests/unit/api/test_security.py -q`（文件名以实施时布局为准，覆盖 reauth 签发/校验、ui_controls 策略读写）。
- 集成：`uv run pytest tests/integration/test_reauth.py -q`（新增，双向隔离两条 + SSO-only 降级一条）；下载角色策略追加进 `w3-02` 已有的 `tests/integration/test_download_guard.py`（不新建文件）。
- i18n：`uv run pytest tests/unit/i18n -q`（新增 `REAUTH_REQUIRED` 键门禁）。
- 前端：`cd dashboard && npm run test`（新增 `SecurityWatermark.test.tsx`、`useIdleLogout.test.ts`、`copyText.test.ts` 策略分支）；`make lint-frontend typecheck-frontend`。
- PG：随 `w0-02` 的 CI PostgreSQL job 复跑集成用例，本地需设置 `OCTOP_TEST_DATABASE_URL`。

## 与其他 spec 的交接

- **依赖 `w3-02`：** 消费 `assert_download_allowed` 与 `file_download` 能力位，只追加 `allow_roles` 判定分支，不重建后端强制校验与 `ui.download*` 审计动作。
- **依赖 `w3-04`：** 消费 `SessionManager.revoke`/`logout` 语义与 `session_idle_timeout_seconds`；空闲登出前端只负责触发登出调用，服务端吊销正确性验收在 `w3-04`；`sign_token` 签名以其合入后代码为准，重认证扩展位需重新核实。
- **依赖 `w1-02`：** 若需要"策略整体开关"，走其 `capabilities.<name>.enabled` 登记方式。
- **交付：** `docs/api-intranet.md` 记录三个新接口；等保材料引用"安全考虑"一节的边界说明。
- **看似相关但不归本 spec：** 下载/复制后端强制点重建（`w3-02`）；会话吊销与服务端空闲判定（`w3-04`）；验证码（`w3-01`）；国密/KMS（`p2-02`）；Agent 强制沙箱（`p2-01`）；知识库三级权限（`p2-05`）。

## 风险与回滚

- 【高】重认证令牌若不做 `scope` 双向隔离，整套二次确认形同虚设；实施时先写双向隔离的失败用例再改实现。
- 【中】水印 body 级 `fixed` 覆盖层在全屏 API 下不参与渲染，需把水印节点一并移入全屏元素，或在策略启用时禁用全屏入口，需与相关页面负责人确认取舍。
- 【中】复制/下载一刀切禁用会误伤 Terminal、Monaco、Markdown 复制等高频路径，建议默认按 `allow_roles` 白名单落地。
- 回滚：策略存储与端点是纯新增，整体禁用（`UiControlsPolicy` 回到"允许"默认值）即回退到当前行为；`employee_id` 迁移是可空加列，回滚不删列，与 i18n/迁移章节"删除代价高、保留代价低"同一原则。

## 待行方确认

- 沿用 `.kiro/steering/intranet-transformation.md` 第 4 节：
  - D11（验证码终态）与本 spec 的重认证流程若并存，需确认重认证是否也要过图形验证码——默认假设不需要（重认证已有口令 + 短 TTL 两重约束）。
  - D12（RBAC 终局：三员分立）落地后，`allow_roles` 的角色取值需与 `w3-03-authorization-foundation` 的角色实体对齐，届时重新核实角色命名。
