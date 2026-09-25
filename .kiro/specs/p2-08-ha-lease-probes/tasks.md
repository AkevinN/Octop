# 实施计划：单活租约与探针

> spec：`p2-08-ha-lease-probes` ｜ 波次：二期 ｜ 基线：`757fd12` ｜ 预估：18 人日
> 前置：`w2-03-database-adaptation` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

每个顶层任务完成后可独立提交；提交前运行任务内的验证命令。

- [ ] 1. 确认前置 spec 已合入并记录基线
  - 改动：无代码改动；用 `rg` 确认 `w2-03-database-adaptation`、`w0-02-ci-gates`、`w0-01-fork-migration-namespace` 已交付的符号（PG 方言家族属性、CI postgres service、fork 迁移 runner）在当前代码中存在，记录当前基线提交号到本任务的提交说明
  - 验证：`git log -1 --format=%H`；`rg -n "dialect_family" src/octop/infra/db`
  - _需求：全部（前置条件）_

- [ ] 2. 新增租约原语
  - [ ] 2.1 新增 `src/octop/infra/ha/lease.py`：`acquire`/`renew`/`release`/`role` 接口，PG 用 fencing-token + `runtime_lease` 表，SQLite 恒 `standalone`
    - 验证：`uv run pytest tests/unit/db/test_lease.py -q`
    - _需求：1.1, 1.3, 1.4_
  - [ ] 2.2 新增 `forkNNN_runtime_lease.sql` / `.pg.sql` 成对迁移文件（合入时定号）
    - 验证：`uv run pytest tests/unit/db -k fork -q`
    - _需求：1.1_
  - [ ] 2.3 PG 分支的抢占/心跳/双进程互斥/故障接管集成用例（`requires_postgresql`）
    - 验证：`uv run pytest tests/unit/db/test_lease.py -m postgresql -q`
    - _需求：1.1, 1.2, 1.4_

- [ ] 3. 拆分 `_boot_runtime` 控制面/数据面
  - 改动：`src/octop/infra/server.py` 的 `_boot_runtime`/`start`/`bind_control_plane`/`stop`（用 `rg _boot_runtime` 重新定位当前行号）——控制面段无条件执行，数据面段仅 `active` 角色执行，`stop()` 排空后释放租约
  - 验证：`uv run pytest tests/integration/test_health_probes.py -q`
  - _需求：1.2, 2.1, 2.2, 2.3, 2.4_

- [ ] 4. `setup_lockdown` 与 standby 状态解耦
  - 改动：`src/octop/api/middleware/setup_lockdown.py` 的判据不再把 `user_manager is None` 等同于未装机
  - 验证：`uv run pytest tests/integration/test_health_probes.py -k standby -q`
  - _需求：2.1, 2.2_

- [ ] 5. 拆分存活/就绪探针
  - 改动：`src/octop/api/routers/health.py` 新增 `GET /live`、`GET /ready`，保留 `GET ""` 原字段不变
  - 验证：`uv run pytest tests/integration/test_health_probes.py -q`；`uv run pytest tests/integration/test_setup_database.py -q`
  - _需求：3.1, 3.2, 3.3, 3.4_

- [ ] 6. 停机排空
  - [ ] 6.1 `src/octop/infra/agents/manager.py` 新增 `begin_drain()`/`drain(timeout)`，`stream`/`call`/`resume_hitl` 增加拒绝分支
    - 验证：`uv run pytest tests/unit/agents -k drain -q`
    - _需求：4.1, 4.2_
  - [ ] 6.2 `src/octop/launch.py` 三处 `uvicorn.Config` 加 `timeout_graceful_shutdown`，`finally` 块接入 `begin_drain_and_wait`（超时读 `OCTOP_DRAIN_TIMEOUT_SECONDS`，配置三触点）
    - 验证：`uv run pytest tests/unit -k launch -q`
    - _需求：4.1, 4.2, 4.3, 4.4_

- [ ] 7. standby 下后台任务门控
  - 改动：`src/octop/infra/cron/manager.py::boot()` 与自动备份注册点（`rg AUTO_BACKUP_JOB_ID` 重新定位）仅 `active` 角色执行，角色升级时重装载
  - 验证：`uv run pytest tests/integration/test_ha_lease.py -m postgresql -q`
  - _需求：2.3, 2.4_

- [ ] 8. 错误码（按需）
  - 改动：若 `w2-03` 未提供可复用码，追加 `ErrorCode.INSTANCE_STANDBY`/`LEASE_UNAVAILABLE` 到枚举与 `_DEFAULT_STATUS` 末尾，同批补 `src/octop/i18n/{en,zh}.json` 与 `dashboard/src/locales/intranet/{en,zh}.json`
    - 验证：`uv run pytest tests/unit/i18n -q`
    - _需求：3.3, 4.1_

- [ ] 9. 收尾
  - 改动：`make all` 全绿；`cd dashboard && npx tsc -b`（本 spec 若无前端改动可跳过 `npm run lint`/`npm run test`）；更新 `CHANGELOG-intranet.md`；`docs/api-intranet.md` 补 `GET /api/health/live`、`GET /api/health/ready` 两行接口说明
  - 验证：`make all`；`uv run pytest -m "not live"`；`cd dashboard && npx tsc -b`
  - _需求：3.1, 3.2, 3.3, 3.4_
