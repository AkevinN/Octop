# 需求文档：可观测与部署清单
> spec：`p2-09-ops-observability` ｜ 波次：二期 ｜ 基线：`757fd12` ｜ 预估：14 人日
> 前置：w4-02-ops-minimum, p2-08-ha-lease-probes, w2-03-database-adaptation, w3-02-audit-baseline ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 引言

**结论：** 本 spec 交付 Wave 0-4 之后遗留的可观测与部署闭环——Prometheus 文本格式指标端点、K8s 单副本（或双机 keepalived）部署清单、可复算的压测基线、以及 `app_runtime` 空引用点的系统性梳理，供后续代码在 standby/延迟绑定场景下有据可依地做防护。

**背景：** 源分析 `S15-ops-delivery.json` 把指标、request_id 贯穿、单活/冷备（租约）、DDL 导出、离线安装包五件事捆在一起估了 40-50 人日。这五件事已按 `.kiro/steering/intranet-transformation.md` 第 3 节归属表拆给不同 spec：request_id 与审计字段归 `w3-02`，PG 租约与 standby 角色/`ready`/`role` 字段与 cron/备份/TLS 续期的 active-only 门控归 `p2-08`，DDL 导出工具链与 verify-only 迁移模式归 `w2-03`，离线安装包构建/校验/运维手册归 `w4-02`（`w4-02-ops-minimum/requirements.md` 引言已明确把这四类划出、留给本 spec 的正是指标端点、K8s/双机清单、压测基线、`app_runtime` 空引用梳理）。本 spec 只取剩下这部分。

**范围内：**
- `GET /metrics`：Prometheus text exposition 格式，独立 scrape token 鉴权，且不被 `src/octop/api/app.py` 的 SPA 兜底路由（`@app.get("/{full_path:path}")`，≈L292）截胡。
- `src/octop/infra/metrics.py` 从 5 字段 dataclass 扩成支持标签的最小指标注册表（Counter/Gauge/Histogram + `render_prometheus()`）。
- `deploy/k8s/`（单副本 + Recreate）与 `deploy/dual-host/`（keepalived 双机）两套部署清单，二选一或并存，取决于 D4/D5 拍板结果。
- 压测基线：可重复执行的压测脚本 + `docs/ops/perf-baseline.md` 登记基线，跑完与登记值比对。
- `app_runtime` 空引用点梳理：枚举 standby / 延迟绑定 DB 场景下直接解引用 `server.app_runtime` 的调用点，产出清单与统一防护建议，作为 `p2-08` 落地 standby 门控与 `w4-02` 手工切换纪律的输入。

**范围外（归其他 spec，本 spec 不写代码）：**
- `X-Request-Id` 贯穿、日志 Filter、`audit_log.request_id`/`client_ip` 字段、错误信封 `request_id`、CryptoProvider 相关 ErrorCode —— 归 `w3-02-audit-baseline`。
- PG 租约表与心跳续租、`/api/health` 的 `ready`/`role` 字段语义、CronManager/自动备份/TLS 续期的 active-only 门控 —— 归 `p2-08-ha-lease-probes`。本 spec 的 K8s/双机清单只消费 `p2-08` 交付的 `role` 字段做探针判定，不实现租约本身。
- DDL 导出工具链（`deploy/dba/generate_ddl.py`）、verify-only 迁移模式（`OCTOP_DB_MIGRATE_MODE`）—— 归 `w2-03-database-adaptation`。
- 离线安装包构建/校验脚本（`deploy/offline/*.sh`、`make offline-bundle`）、运维手册、应急预案、备份恢复演练 —— 归 `w4-02-ops-minimum`；本 spec 的 K8s 清单与压测脚本作为素材被 `w4-02` 打包引用，不重复实现打包逻辑。
- `runtime_packages.py` 的 `OCTOP_OFFLINE` 离线开关、chromium/ONNX/OCR 运行期依赖预置 —— 归 `w2-01-offline-build`。

## 需求

### 需求 1：Prometheus 指标端点
**用户故事：** 作为行内运维，我希望 Octop 在根路径暴露标准 Prometheus 文本格式指标，以便行内 Prometheus 用独立 scrape token 直接拉取，无需出网访问 Langfuse。

#### 验收标准
1. 当请求携带合法 `Authorization: Bearer $OCTOP_METRICS_TOKEN` 访问 `/metrics` 时，端点应当返回 `Content-Type: text/plain; version=0.0.4; charset=utf-8` 的 Prometheus exposition 格式文本，`promtool check metrics` 对输出零告警。
2. 如果请求未携带合法 token，那么 `/metrics` 应当返回 401/404 JSON，且响应体不得是 dashboard 的 `index.html`（即 metrics router 必须无条件挂载，不能靠"未配置 token 就不挂 router"实现，否则会被 `app.py` ≈L292 的 SPA 兜底路由接住并返回 200）。
3. `/metrics` 输出应当始终包含 `octop_http_requests_total{method,route,status}` 与 `octop_http_request_duration_seconds_bucket{route,le}`，其中 `route` 取 FastAPI 路由模板而非含 ID 的原始路径。
4. 新增的 `tests/unit/api/test_metrics_endpoint.py` 应当使用独立 `Metrics()` 实例或显式重置全局 `METRICS`，避免 `pytest -n auto` 下同 worker 内用例互相污染。

### 需求 2：部署清单（单副本 K8s 或双机）
**用户故事：** 作为发布工程师，我希望有一套经过审阅的部署清单，以便在 K8s 集群或两台物理机上把单活 Octop 部署起来，而不必手写。

#### 验收标准
1. 当采用 K8s 部署时，`deploy/k8s/deployment.yaml` 应当声明 `replicas: 1`、`strategy.type: Recreate`，且 `README.md` 说明为何不能多副本（ADR 002 单写入者约束）。
2. `deploy/k8s/deployment.yaml` 的 `readinessProbe` 应当使用 `/api/health` 并接受 `p2-08` 定义的 503（standby）语义，`livenessProbe` 应当使用与 readiness 不同的、更宽松的存活判定，不得让 standby 副本被反复杀死。
3. 如果采用双机方案，那么 `deploy/dual-host/` 下的 keepalived 配置与 `check_octop.sh` 应当依据 `/api/health` 的 `role` 字段决定 VIP 是否漂移，目录名应当使用英文路径（不使用中文目录名，避免 Windows checkout 与 tar 摆渡的编码问题）。
4. `deploy/k8s/networkpolicy.yaml` 应当默认拒绝出站，仅放行 PG、行内大模型网关、Prometheus 三类目标。

### 需求 3：压测基线
**用户故事：** 作为发布工程师，我希望有一条可重复执行的压测命令，以便每次发布前确认性能没有劣化。

#### 验收标准
1. 当执行压测基线命令时，系统应当输出 p50/p95/p99 与错误率，并与 `docs/ops/perf-baseline.md` 登记的基线数值比对。
2. 如果本次结果劣化超过预先登记的阈值，那么压测命令应当以非零退出码终止。
3. 压测工具的选型（新增 `locust` 依赖 或 复用 `httpx` 自写 或 引入 `k6` 二进制）应当在 design.md 中给出取舍并对齐 `.kiro/steering/` D 编号待确认项，不得静默改动 `uv.lock` 而不记录理由。

### 需求 4：`app_runtime` 空引用梳理
**用户故事：** 作为负责 standby/延迟绑定场景的后续开发者，我希望有一份 `server.app_runtime` 空引用点的清单与统一处理建议，以便 `p2-08` 落地门控时不必逐个 grep 全仓。

#### 验收标准
1. 梳理产出应当枚举当前直接解引用 `server.app_runtime`（不经过 `server.database_bound` 或等价判空）的调用点，并按"观测/探针类"与"业务功能类"分类。
2. 梳理产出应当给出统一处理建议（例如集中的 `require_active_runtime()` 依赖），并明确标注该建议的落地实现属于 `p2-08` 的范围，本 spec 不改动业务功能类调用点。
3. 本 spec 自身新增的观测代码（`metrics.py` 的 handler）应当始终不解引用 `app_runtime`（沿用 `snapshot()` 兼容 API 或直接读 `METRICS` 单例），使指标端点在 standby / 延迟绑定 DB 期间仍可用。

## 需求覆盖说明

上述 4 组需求共 15 条验收标准，覆盖 tasks.md 全部顶层任务；每个任务在"验证"之后标注对应需求编号。
