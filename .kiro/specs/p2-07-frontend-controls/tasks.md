# 实施计划：前端管控

> spec：`p2-07-frontend-controls` ｜ 波次：二期 ｜ 基线：`757fd12` ｜ 预估：19 人日
> 前置：`w1-02-capability-trim`, `w3-02-audit-baseline`, `w3-04-session-and-password` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

每个顶层任务完成后可独立提交；提交前运行任务内的验证命令。

- [ ] 1. 确认前置 spec 已合入并记录基线
  - 改动：无代码改动；用 `rg` 重新核实本 design.md"现状"一节列出的关键锚点是否漂移——`api/common/download_guard.py::assert_download_allowed` 签名、`infra/users/sessions.py::SessionManager` 接口、`api/deps.py::sign_token` 真实签名、`w1-02` 的 `capabilities.<name>.enabled` 登记方式；漂移则先更新 design.md 对应段落再继续
  - 验证：`rg -n "assert_download_allowed|class SessionManager|def sign_token" src/octop`
  - _需求：（前置确认，不对应具体需求）_

- [ ] 2. 后端：`infra/ui_controls` 策略存储与 `SharedServices` 接线
  - 改动：新增 `src/octop/infra/ui_controls/policy_store.py`（`UiControlsPolicy`、`UiControlsStore`）；`infra/db/services.py::SharedServices` 加 `ui_controls` 只读 `@property`
  - 验证：`uv run pytest tests/unit/infra/test_ui_controls.py -q`（新增测试文件）
  - _需求：1.2, 5.2_

- [ ] 3. 后端：`ui-controls` 管理端与运行时下发端点
  - 改动：`api/routers/security.py` 新增 `GET/PUT /ui-controls`；`api/routers/settings.py` 新增 `GET /settings/ui-controls`
  - 验证：`uv run pytest tests/unit/api/test_security.py tests/unit/api/test_settings.py -q`
  - _需求：1.2, 4.1, 5.2_

- [ ] 4. 后端：`/auth/reauth` 与 `require_reauth` 双向隔离
  - 改动：`api/routers/auth.py` 新增 `POST /reauth`；`api/deps.py` 给令牌签发加 `scope` 扩展位、新增 `require_reauth()`、在解析普通令牌路径拒绝带 `scope` 声明的令牌；`infra/errors.py` 追加 `REAUTH_REQUIRED`（枚举 + `_DEFAULT_STATUS`）；`i18n/{en,zh}.json` 补文案
  - 验证：`uv run pytest tests/integration/test_reauth.py tests/unit/i18n -q`
  - _需求：6.2, 6.3, 6.4_

- [ ] 5. 后端：下载角色策略扩展 + `employee_id` 迁移
  - 改动：`api/common/download_guard.py` 内追加 `allow_roles` 判定分支（消费 `w3-02` 已有的 `assert_download_allowed`，不重建）；新增 `infra/db/migrations/forkNNN_user_employee_id.sql`/`.pg.sql`、`migrate.py` 幂等分支、`infra/db/repos/users.py` 字段映射、`api/routers/auth.py::_user_json` 补 `employee_id`
  - 验证：`uv run pytest tests/integration/test_download_guard.py tests/unit/db -q`
  - _需求：5.2, 1.2_

- [ ] 6. 前端：`useUiControls` 与 `SecurityWatermark`
  - 改动：新增 `hooks/useUiControls.ts`、`components/SecurityWatermark.tsx`；`components/AuthGuard.tsx` 挂载水印并处理"后端不可达"降级分支（≈L76-83）
  - 验证：`cd dashboard && npx vitest run src/components/SecurityWatermark.test.tsx`
  - _需求：1.1, 1.2, 1.3, 1.4, 2.1, 2.2_

- [ ] 7. 前端：`useIdleLogout`
  - 改动：新增 `hooks/useIdleLogout.ts`（活动侦测 + `localStorage` 跨标签页同步 + 到期登出）；`AuthGuard.tsx` 内接入
  - 验证：`cd dashboard && npx vitest run src/hooks/useIdleLogout.test.ts`
  - _需求：3.1, 3.2, 3.3_

- [ ] 8. 前端：复制管控收敛
  - 改动：`utils/copyText.ts` 读策略；新增 `utils/selectionGuard.ts`；`pages/Control/Terminal/components/TerminalView.tsx` 收敛 Ctrl+Shift+C 放行分支；`pages/Agent/Workspace/components/CodeEditor.tsx` 的 `onMount` 里屏蔽 Monaco 剪贴板 action；新增 `useCopyAllowed()` 并批量接入既有 `copyText` 调用点的按钮显隐
  - 验证：`cd dashboard && npx vitest run src/utils/copyText.test.ts`
  - _需求：4.1, 4.2, 4.3_

- [ ] 9. 前端：下载出口收敛
  - 改动：新增 `utils/downloadBlob.ts`；既有 `a.download` 调用点（以实施时 `rg "\.download\s*="` 结果为准）改用 `triggerDownload`
  - 验证：`cd dashboard && rg -n "\.download\s*=" src --glob '!**/utils/downloadBlob.ts'`（结果应为空）
  - _需求：5.1, 5.3_

- [ ] 10. 前端：高危二次确认
  - 改动：新增 `utils/dangerConfirm.tsx`（受控 Modal，打字校验 + 可选重认证）；至少接入删除专家、删除用户、恢复备份三处调用点
  - 验证：`cd dashboard && npx vitest run src/utils/dangerConfirm.test.tsx`
  - _需求：6.1, 6.2, 6.4_

- [ ] 11. 管理端 UI 与审计文案接入
  - 改动：`pages/Settings/Security/index.tsx` 新增 tab；`utils/permissions.ts` 补 tab 权限映射；`pages/Settings/Security/AuditLogPanel.tsx` 的 `ACTION_OPTIONS` 加 `security.ui_controls.update`、`auth.reauth.failed`；`dashboard/src/locales/{en,zh}.json` 补 `securityUiControls.*`、`security.tabUiControls`、`adminAudit.actions.*`、`apiErrors.REAUTH_REQUIRED`
  - 验证：`cd dashboard && npm run test -- AuditLogPanel`
  - _需求：6.3_

- [ ] 12. 收尾
  - 改动：`CHANGELOG-intranet.md` 追加本 spec 条目；`docs/api-intranet.md` 补 `/api/admin/security/ui-controls`、`/api/settings/ui-controls`、`/api/auth/reauth` 三个接口说明
  - 验证：`make all`；`cd dashboard && npx tsc -b && npm run lint && npm run test`
  - _需求：（收尾，覆盖全部需求的整体回归）_
