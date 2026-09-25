# 实施计划：可观测与部署清单
> spec：`p2-09-ops-observability` ｜ 波次：二期 ｜ 基线：`757fd12` ｜ 预估：14 人日
> 前置：w4-02-ops-minimum, p2-08-ha-lease-probes, w2-03-database-adaptation, w3-02-audit-baseline ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

每个顶层任务完成后可独立提交；提交前运行任务内的验证命令。

- [ ] 1. 确认前置 spec 已合入并记录基线
  - 改动：无代码改动；核对 `w4-02`/`p2-08`/`w2-03`/`w3-02` 已合入主干，记录合入后的基线 commit 与 `/api/health` 实际字段形态（`ready`/`role` 由 `p2-08` 交付，若字段名与本文档假设不符，先更新 design.md 再继续）。
  - 验证：`git log --oneline -1`；`rg -n "role|ready" src/octop/api/routers/health.py`
  - _需求：无（前置校验）_

- [ ] 2. 指标注册表：`infra/metrics.py` 扩成标签化 Counter/Gauge/Histogram
  - 改动：`src/octop/infra/metrics.py` 保留 `Metrics()`/`inc`/`set`/`snapshot` 兼容 API，新增标签支持与 `render_prometheus()`
  - 验证：`uv run pytest tests/unit/test_metrics.py -q`
  - _需求：1.3_

- [ ] 3. HTTP 指标中间件
  - 改动：新增 `src/octop/api/middleware/metrics.py`，按路由模板记录 method/status/耗时，跳过 `/metrics` 自身
  - 验证：`uv run pytest tests/unit/api -k metrics_middleware -q`
  - _需求：1.3_

- [ ] 4. `GET /metrics` 端点与挂载
  - 4.1 新增 `src/octop/api/routers/metrics.py`，token 鉴权（`hmac.compare_digest`），不解引用 `server.app_runtime`
    - 验证：`uv run pytest tests/unit/api/test_metrics_endpoint.py -q`
    - _需求：1.1, 1.2, 4.3_
  - 4.2 `src/octop/api/app.py` 无条件挂载 `metrics` router 到根路径，≈L292 SPA 兜底旁补注释锁定优先级；`api/openapi_meta.py` 增加 `metrics` tag
    - 验证：`curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8088/metrics` 未配置 token 时非 200；`cd dashboard && npx tsc -b`（若涉及前端类型无变化可跳过并注明）
    - _需求：1.1, 1.2_
  - 4.3 补 `config.py` 三触点：`OCTOP_METRICS_TOKEN`、`OCTOP_METRICS_ALLOW_CIDR`
    - 验证：`uv run pytest tests/unit -k config_roundtrip -q`（或当时等价的三触点门禁用例，若 `w1-02` 已交付该门禁则直接复用）
    - _需求：1.1_

- [ ] 5. K8s 单副本部署清单
  - 改动：新增 `deploy/k8s/{namespace,configmap,secret.example,pvc,deployment,service,networkpolicy,servicemonitor}.yaml` 与 `README.md`，`replicas: 1`、`strategy.type: Recreate`，探针消费 `p2-08` 的 `role` 字段
  - 验证：`kubectl apply --dry-run=client -f deploy/k8s/`（无集群时用 `kubeconform` 或等价 schema 校验替代，若行内环境均不可用则在 README 注明改为人工 review）
  - _需求：2.1, 2.2, 2.4_

- [ ] 6. 双机 keepalived 部署清单
  - 改动：新增 `deploy/dual-host/{keepalived.conf,octop.service,check_octop.sh,README.md}`，`check_octop.sh` 读 `/api/health` 的 `role` 字段决定 VIP 漂移
  - 验证：`shellcheck deploy/dual-host/check_octop.sh`
  - _需求：2.3_

- [ ] 7. 压测基线脚本与文档
  - 改动：新增 `make perf-baseline` 目标 + 压测脚本（工具选型按 design.md「待行方确认」的最保守假设：`httpx` 自写，若行方确认可用 `locust`/`k6` 则改用并在 `uv.lock`/`README` 注明）、`docs/ops/perf-baseline.md` 登记 p50/p95/p99 基线
  - 验证：`make perf-baseline`（首次执行仅登记基线，不做比对；文档中说明二次执行起比对）
  - _需求：3.1, 3.2, 3.3_

- [ ] 8. `app_runtime` 空引用梳理
  - 改动：`rg -n "app_runtime" src/octop` 全仓核对（实施时以当时代码为准，本文档不预写行号），产出 `docs/ops/app-runtime-null-refs.md`，分类"观测/探针类"（确认本 spec 新增代码均不解引用）与"业务功能类"（列清单，标注移交 `p2-08`）
  - 验证：`rg -n "server\.app_runtime" src/octop` 输出与文档清单条目数一致（人工核对，无自动化门禁）
  - _需求：4.1, 4.2_

- [ ] 9. 收尾：全绿与文档同步
  - 改动：更新 `CHANGELOG-intranet.md` 记录本 spec 交付；若新增 API（`/metrics`）则同步 `docs/api-intranet.md`
  - 验证：`make all`；`cd dashboard && npx tsc -b && npm run lint`（本 spec 预期无前端改动，若确无改动则在提交说明中注明并跳过）；`uv run pytest tests/unit/i18n -q`
  - _需求：1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3, 4.1, 4.2, 4.3_
