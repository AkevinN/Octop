# 需求文档：单活租约与探针

> spec：`p2-08-ha-lease-probes` ｜ 波次：二期 ｜ 基线：`757fd12` ｜ 预估：18 人日
> 前置：`w2-03-database-adaptation` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 引言

一期（`w4-02-ops-minimum`）交付的是「单实例 + 冷备 + 手工切换」：值班人员发现 active 实例故障后手工拉起备机。本 spec 是二期升级，把手工切换换成秒级自动切换：同一 PG 系数据库上可以同时起两个 Octop 进程，只有抢到数据库租约的那个拉起 Agent/cron/IM/WS 等运行时（下称"数据面"），另一个保持 standby 且仍能正确响应 `/health` 与前端静态页；负载均衡据探针状态摘流；进程收到 `SIGTERM` 时先停接新会话、排空在途对话再退出。

本 spec 只取代码源 JSON `S12-database-ha.json` 与 `S15-ops-delivery.json` 中"单活租约 + standby 启动 + 存活/就绪探针 + 停机排空"这一部分。两份源材料原本各造了一套租约（`infra/db/lease.py` vs `infra/ha/lease.py`），本 spec 只保留一套，落地路径与设计取舍见 `design.md`。

**范围内**：数据库租约原语（fork 迁移新表）、`server.py::start/bind_control_plane/stop/_boot_runtime` 的控制面/数据面拆分、`setup_lockdown.py` 与租约状态解耦、standby 下 `app_runtime` 为空/部分为空时的处置、`GET /api/health/live`、`GET /api/health/ready` 拆分（保留旧 `GET /api/health` 向后兼容）、`AgentManager` 排空、`launch.py` 优雅停机接线、standby 下 CronManager/自动备份等进程级后台任务不重复注册。

**范围外**（归属见 design.md「与其他 spec 的交接」）：PG 方言家族收口、关闭运行期 DDL、DDL 导出、连接池参数化（`w2-03`）；Prometheus `/metrics`、K8s/双机部署清单、离线安装包、应急预案 runbook、压测基线（`p2-09-ops-observability`）；一期的单实例+冷备+手工切换本身、Docker 入口脚本幂等（`w4-02-ops-minimum`）；CI 增加 PostgreSQL 门禁（`w0-02-ci-gates`，本 spec 的 PG 集成测试以它已合入为前提）；`request_id` 贯穿与审计字段（`w3-02-audit-baseline`）；fork 迁移 runner 本身（`w0-01-fork-migration-namespace`，本 spec 只新增一对 fork 迁移文件）。

## 需求

### 需求 1：数据库租约

**用户故事：** 作为运维人员，我希望同一套 PG 系数据库上可以同时起两个 Octop 实例且只有一个处于工作状态，以便在不引入外部选主组件的前提下做秒级主备切换。

#### 验收标准
1. 当两个 Octop 进程连接同一个 PG 系数据库并先后启动时，系统应当只让先启动（先抢到租约）的一个进入 `active` 角色，另一个进入 `standby` 角色。
2. 如果 `active` 进程被 kill 或崩溃，那么在租约 TTL 与心跳周期之内，`standby` 进程应当自动升为 `active` 并拉起数据面运行时。
3. 在 SQLite 单机部署期间，系统应当恒定以 `standalone`（等价 `active`）角色运行，不引入跨进程互斥语义。
4. 系统应当始终通过池外独占连接或等价机制维护租约，使得连接池回收连接不会导致租约被静默释放。

### 需求 2：standby 启动不退化为未装机

**用户故事：** 作为运维人员，我希望 standby 实例的 HTTP 服务保持可用，以便负载均衡在 active 故障时能把流量切到已经在线的 standby 而不是等它冷启动。

#### 验收标准
1. 当实例处于 `standby` 角色时，`GET /api/health`、`/api/setup/status`、前端静态页应当正常返回，不得出现 `setup_required: true` 的误判。
2. 当实例处于 `standby` 角色且已有有效 JWT 时，鉴权相关接口应当正常放行，不得因 `server.user_manager is None` 而抛出未处理异常。
3. 在 `standby` 角色期间，系统应当不注册 cron 调度器任务、不连接 IM 渠道、不启动自动备份等进程级后台任务。
4. 当实例由 `standby` 升为 `active` 时，系统应当补齐上述被跳过的数据面初始化与任务注册。

### 需求 3：存活探针与就绪探针拆分

**用户故事：** 作为运维人员，我希望存活探针和就绪探针语义分离，以便数据库变慢时容器不会被误判为进程崩溃而重启。

#### 验收标准
1. 当调用 `GET /api/health/live` 时，系统应当始终不访问数据库，并在数据库连接异常（如 `connect()` 恒抛异常）的情况下仍在极短时间内返回 200。
2. 当调用 `GET /api/health/ready` 且 `SELECT 1` 探测失败时，系统应当返回 503。
3. 如果实例处于 `standby` 角色，那么 `GET /api/health/ready` 应当返回 503 且响应体包含角色标识为 `standby`；`active` 角色应当返回 200 且角色标识为 `active`。
4. 系统应当始终保留旧版 `GET /api/health` 的既有字段（`ok`/`started_at`/`db`/`users_loaded`/`agents_running`）不变，向后兼容现有集成测试与容器健康检查脚本。

### 需求 4：停机排空在途对话

**用户故事：** 作为运维人员，我希望进程收到停机信号后能排空在途会话再退出，以便发版或主备切换不会中断正在进行的对话。

#### 验收标准
1. 当进程收到 `SIGTERM` 时，系统应当立即停止接受新的 agent turn（`stream`/`call`/`resume_hitl` 三个入口）。
2. 在排空期间，系统应当持续等待所有 agent 的在途调用计数归零后才继续关闭流程。
3. 如果排空耗时超过 `OCTOP_DRAIN_TIMEOUT_SECONDS`（默认 60 秒），那么系统应当放弃继续等待并强制进入后续关闭步骤。
4. 系统应当在排空完成（或超时）之后才释放数据库租约、关闭连接池。
