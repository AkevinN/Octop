# 设计文档：可观测与部署清单
> spec：`p2-09-ops-observability` ｜ 波次：二期 ｜ 基线：`757fd12` ｜ 预估：14 人日
> 前置：w4-02-ops-minimum, p2-08-ha-lease-probes, w2-03-database-adaptation, w3-02-audit-baseline ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 概述

在一期 Wave 0-4 与二期 `p2-08`/`w4-02`/`w2-03`/`w3-02` 落地之后，行内环境已具备单活+冷备、request_id 贯穿、DDL 权威导出、离线安装能力。本 spec 补上最后一块：Prometheus 抓取端点、K8s/双机部署清单、压测基线、`app_runtime` 空引用的系统性梳理。

## 现状（本次核实，基线 `757fd12`）

- `src/octop/infra/metrics.py`：37 行，`Metrics` dataclass 只有 5 个 int 字段（`messages_total`/`stream_errors_total`/`cron_runs_total`/`cron_errors_total`/`agent_active`）+ `inc`/`set`/`snapshot`，无标签、无 Prometheus exposition 输出，模块级单例 `METRICS`。
- `src/octop/api/app.py`：≈L129 `CORSMiddleware(expose_headers=[ACCESS_TOKEN_RESPONSE_HEADER])`；≈L205 起是 `_RouterMount(...)` 平铺列表（`setup`/`auth`/`i18n`/`health` 等）；≈L292 `@app.get("/{full_path:path}", include_in_schema=False)` 是 SPA 兜底路由。未挂载的路径会落到这条兜底并返回 `index.html`（200），因此新增的 `/metrics` router 必须无条件挂载，由 handler 自身判 token 返回 401/404。
- `src/octop/api/routers/health.py`：≈L14-28，`health()` 恒返回 `ok: True`，无 `ready`/`role` 字段；`server.app_runtime` 判空后取 `agent_registry.list_rows()` 长度。`ready`/`role` 字段由 `p2-08` 交付，本 spec 只在 K8s/双机清单里消费。
- `src/octop/api/routers/admin.py`：`metrics()` 在 ≈L71，返回 JSON 且要求 admin JWT + `admin_console` 权限，Prometheus 无法直接抓取，是本 spec 要新增独立端点的原因（该 JSON 端点保留不动）。
- `src/octop/infra/errors.py`：`_DEFAULT_STATUS` 字典起始于 ≈L115。
- 全仓不存在 `deploy/` 目录、`docs/ops/` 目录（本次 `ls` 确认均不存在），K8s 清单、双机清单、压测基线文档均为新增。
- `rg 'prometheus'` 在代码里零命中（仅 subagent 提示词 markdown 里有非代码提及），指标能力当前完全空白。

其余路径（`app_runtime` 各解引用点的具体行号、`p2-08` 交付后 `/api/health` 的最终字段形态等）实施时以一期与 `p2-08` 落地后的代码重新定位，本次不逐一核实行号。

## 方案

1. **指标注册表**：`infra/metrics.py` 保留 `Metrics()` 可直接构造、5 个字段 `inc`/`set`/`snapshot` 的兼容 API（存量单测依赖），新增支持 `labels` 的 `Counter`/`Gauge`/`Histogram` 与 `render_prometheus()`，不引入 `prometheus-client` 依赖（避免改 `pyproject.toml`/`uv.lock` 带来的上游冲突面，手写约 60-80 行 exposition 格式化）。
2. **HTTP 指标中间件**：新增 `api/middleware/metrics.py`，按路由模板（非原始路径，避免 `agent_id`/`thread_id` 造成标签基数爆炸）记录方法/状态码/耗时；跳过 `/metrics` 自身与静态资源路径。
3. **`/metrics` 端点**：新增 `api/routers/metrics.py`，无条件挂载在根路径（不挂 `/api` 前缀），鉴权用 `hmac.compare_digest` 比较 `OCTOP_METRICS_TOKEN`（或 settings/secrets 表里的 scrape token），可选叠加源 IP CIDR 白名单；handler 只读 `METRICS` 单例与 `server.database_bound`，不解引用 `server.app_runtime`，保证 standby/延迟绑定期间仍可用。
4. **部署清单**：`deploy/k8s/` 单副本 + Recreate；`deploy/dual-host/` keepalived + VIP。两者的探针/VIP 判定都读 `p2-08` 交付的 `/api/health` 的 `role` 字段，本 spec 不实现该字段。
5. **压测基线**：新增 `make perf-baseline` 目标与脚本，工具选型见"待行方确认"；结果与 `docs/ops/perf-baseline.md` 登记值比对，超阈值非零退出。
6. **`app_runtime` 梳理**：一次性 `rg` 全仓枚举直接解引用 `server.app_runtime`（不经 `server.database_bound` 或等价判空）的调用点，产出 `docs/ops/app-runtime-null-refs.md`，分类为"观测/探针类"（本 spec 处理，确保不解引用）与"业务功能类"（列清单交给 `p2-08` 用 `require_active_runtime()` 统一收口，本 spec 不改这些调用点的代码）。

## 组件与接口

| 文件 | 改动 | 说明 |
|---|---|---|
| `src/octop/infra/metrics.py` | modify | 扩成标签化注册表，新增 `render_prometheus() -> str` |
| `src/octop/api/middleware/metrics.py` | add | HTTP 指标中间件 |
| `src/octop/api/routers/metrics.py` | add | `GET /metrics`，独立 token 鉴权 |
| `src/octop/api/app.py` | modify | 挂载 `metrics` router 到根路径；≈L292 SPA 兜底旁补注释锁定优先级 |
| `src/octop/api/openapi_meta.py` | modify | 新增 `metrics` tag |
| `deploy/k8s/*.yaml`、`deploy/k8s/README.md` | add | 单副本清单 |
| `deploy/dual-host/*` | add | keepalived 双机方案 |
| `scripts/perf/*`（或复用 `w4-02` 的 `scripts/intranet/`，实施时按当时目录约定确定）、`docs/ops/perf-baseline.md` | add | 压测基线脚本与登记文档 |
| `docs/ops/app-runtime-null-refs.md` | add | 空引用梳理清单，交给 `p2-08` |

关键函数签名（实施时按当时代码复核，此处为设计意图）：
- `infra/metrics.py::render_prometheus() -> str`
- `api/routers/metrics.py::metrics_endpoint(request: Request) -> Response`

## 数据模型

无新增数据库表；本 spec 不涉及 fork 迁移。

## 配置

| 配置键 | 说明 |
|---|---|
| `OCTOP_METRICS_TOKEN` | `/metrics` 鉴权 token；三触点：`OctopConfig` 字段、env 覆盖块、`return OctopConfig(...)` 逐字段构造，实施时在 `config.py` 落地 |
| `OCTOP_METRICS_ALLOW_CIDR`（可选） | `/metrics` 源 IP 白名单，同三触点 |

## 错误处理

不预期新增 `ErrorCode`：`/metrics` 的 401/404 直接由 handler 返回 JSON，不走 `OctopError` 信封（该端点不面向前端展示，无需 i18n 文案）。若实施时发现确需新增错误码，须同批登记 `_DEFAULT_STATUS`（`src/octop/infra/errors.py` ≈L115 起）与 `src/octop/i18n/{en,zh}.json` 的 `errors` 命名空间、`dashboard/src/locales/en.json` 的 `apiErrors`（`tests/unit/i18n/test_errors.py` 做三方精确相等断言）。

## 安全考虑

- `/metrics` 独立 token 而非 JWT，需在 `openapi_meta.py` 的 Public endpoints 段落写明"非无鉴权端点"，避免等保材料审查时被误判。
- K8s `NetworkPolicy` 默认拒绝出站，仅放行 PG/大模型网关/Prometheus，符合全局断网约束。
- 压测脚本不得针对生产库运行；`docs/ops/perf-baseline.md` 需注明仅限预发布环境。

## 测试策略

- 单测：`uv run pytest tests/unit/api/test_metrics_endpoint.py tests/unit/test_metrics.py -q`（新增用例用独立 `Metrics()` 实例，避免 `pytest -n auto` worker 间污染）。
- 集成：`uv run pytest tests/integration -k metrics -q`。
- 前端：本 spec 不涉及前端改动，若压测脚本产出被 dashboard 展示则另评估，默认不改 `dashboard/`。
- PG：本 spec 不新增 PG-only 用例；若 `app_runtime` 梳理涉及需要 PG 场景验证的调用点，复用 `w0-02` 交付的 CI PostgreSQL service，命令为 `OCTOP_TEST_DATABASE_URL=<dsn> uv run pytest -m postgresql -q`。

## 与其他 spec 的交接

- **依赖**：`w4-02`（离线安装包框架，本 spec 的 K8s 清单/压测脚本作为素材被其打包）、`p2-08`（`/api/health` 的 `ready`/`role` 字段与租约，本 spec 的探针配置直接消费）、`w2-03`（DDL 导出，本 spec 不重复）、`w3-02`（request_id/审计字段，本 spec 的指标标签不含 request_id）。
- **交付给谁**：K8s/双机清单交给 `w4-02` 打入离线包；`app_runtime` 空引用清单交给 `p2-08` 作为 `require_active_runtime()` 收口的输入。
- **看似相关但归别的 spec**：`/metrics` 的鉴权 token 与 `w3-05` 的 `CryptoProvider`/信封加密无关（scrape token 是明文比较的静态令牌，走 `settings`/`secrets` 表既有范式，不新增加密原语）；`/api/health` 的 `ready`/`role` 字段语义归 `p2-08`，本 spec 不改 `health.py` 的字段定义；CronManager/自动备份/TLS 续期的 active-only 门控归 `p2-08`，本 spec 不改 `infra/cron/manager.py`、`infra/backup/auto.py`、`infra/setup/tls/renewal.py`。

## 风险与回滚

- **风险**：`/metrics` 挂载顺序被后人误改为条件挂载，退化为 SPA 200（已在 app.py 注释与本 spec 的验收标准 1.2 里锁定，回归测试覆盖）。
- **风险**：压测工具选型（locust/httpx/k6）未定会阻塞压测基线任务，需求 3 验收标准 3 要求先在 design 阶段给出取舍。
- **回滚**：`/metrics` router、K8s/双机清单、压测脚本均为新增文件，回滚即物理删除对应文件与 `app.py` 里的一行 mount，不涉及数据库变更，无迁移回滚风险。

## 待行方确认

- D4（部署形态）：K8s 单副本 vs 双机 keepalived 二选一或并存，决定本 spec 优先完成哪套清单。
- D5（高可用）：一期单活+冷备，本 spec 的探针只反映 `role`，不做自动切换；若行方要求自动切换提前到一期，需与 `p2-08` 重新对齐工作量。
- 压测工具选型（locust 引入 uv.lock vs httpx 自写 vs k6 二进制）与行方内网 CI 是否可跑 PostgreSQL service（影响 `app_runtime` 相关 PG 场景用例能否在 CI 而非人工演练中验证）：均见 steering 第 4 节未列出的补充待办，实施前需与行方确认，否则任务 3 与任务 4 按最保守假设（httpx 自写、CI 无 PG service）起草。
