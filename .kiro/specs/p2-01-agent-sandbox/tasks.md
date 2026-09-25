# 实施计划：Agent 强制沙箱

> spec：`p2-01-agent-sandbox` ｜ 波次：二期 ｜ 基线：`757fd12` ｜ 预估：10 人日
> 前置：`w3-06-agent-execution-hardening` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

每个顶层任务完成后可独立提交；提交前运行任务内的验证命令。二期任务粒度较一期粗一级，具体文件路径与行号以一期（尤其 `w3-06`、`w2-01`）落地后的代码重新定位，不预先假设行号。

- [ ] 1. 确认前置 spec 已合入并记录基线
  - 改动：核实 `w3-06-agent-execution-hardening`、`w2-01-offline-build`、`w1-02-capability-trim` 已合入；核实 `src/octop/infra/mobile/docker_install.py` 是否已随 `w1-02` 删除；核实 `w2-01` 交付的 `ensure_bubblewrap()` 三分支契约、Dockerfile 非 root 用户是否仍是当时形态；若任一假设不成立，先在本文件顶部记录偏差再继续
  - 验证：`git log --oneline -5`；`rg -n "sandbox_scope|sandbox_prefix" src/octop/infra/backend/`；`ls src/octop/infra/mobile/docker_install.py 2>&1`
  - _需求：全部_

- [ ] 2. `config.py` 新增沙箱配置三触点
  - 改动：`OCTOP_SANDBOX_MODE`、`OCTOP_SANDBOX_ALLOW_FIXED_SCOPE`、`OCTOP_SANDBOX_DEPLOYMENT_ID`、`OCTOP_SANDBOX_EXEC_USER` 四个键，按 `OctopConfig` dataclass 字段 + env 覆盖块 + 构造调用三处补齐
  - 验证：`uv run pytest tests/unit/test_config.py -q`（若该文件不存在，先 `rg -n "class OctopConfig" src/octop/config.py` 定位对应测试文件）
  - _需求：1.1, 1.2_

- [ ] 3. 沙箱运行时状态探测扩展（内核前提）
  - 改动：`bwrap.py`（或届时的 `sandbox_policy` 模块）的探测函数，在二进制存在性之外新增 unprivileged user namespace 可用性自检，`degraded` 原因区分 `not_installed` 与 `userns_unavailable`
  - 验证：`uv run pytest tests/unit/infra/utils/test_bwrap.py -q`
  - _需求：3.1, 3.2, 3.3_

- [ ] 4. 启动期沙箱门禁接入 `launch.py`
  - 改动：`_ensure_linux_bubblewrap`/`_schedule_linux_bubblewrap_ensure`（或届时的等价入口）后，按 `OCTOP_SANDBOX_MODE` 决定 fail-fast 还是标记 degraded 后继续启动
  - 验证：`uv run pytest tests/unit/test_launch_bwrap.py -q`
  - _需求：1.1, 1.2, 1.3, 6.2_

- [ ] 5. Docker 沙箱作用域收紧
  - 改动：`infra/backend/docker_spec.py` 新增作用域与命名空间前缀校验，默认拒绝 `sandbox_scope="fixed"`
  - 验证：`uv run pytest tests/unit/backend/test_docker_spec.py -q`（文件名以届时实际测试文件为准，先 `rg -n "sandbox_scope" tests/unit -l` 定位）
  - _需求：4.1, 4.2, 4.3_

- [ ] 6. 镜像预装 bubblewrap
  - 改动：`docker/Dockerfile` 最终 apt 层加入 `bubblewrap`（与 `w2-01` 已交付的非 root 用户段落相邻但不重复其内容）；若 `fnos/docker/Dockerfile` 仍在交付范围则同步
  - 验证：`docker build -f docker/Dockerfile . -t octop:sandbox-check && docker run --rm octop:sandbox-check sh -c 'command -v bwrap'`
  - _需求：2.1, 2.2, 2.3_

- [ ] 7. 容器内 user namespace 与命令/服务进程 OS 用户分离
  - 改动：确认容器运行时允许 bwrap 在 uid 10001 非 root 容器内创建嵌套 user namespace（必要时补 `--cap-add`/`--security-opt` 说明进部署文档）；实现命令执行身份与服务进程身份的隔离校验
  - 验证：`uv run pytest tests/integration/test_bwrap_jail.py -q`
  - _需求：5.1, 5.3_

- [ ] 8. 裸机部署下独立执行账户的探测与降级
  - 改动：新增裸机形态下 `OCTOP_SANDBOX_EXEC_USER` 的存在性校验，缺失且 `enforce` 时拒启
  - 验证：`uv run pytest tests/unit/infra/backend/test_sandbox_policy.py -q`（文件名以届时实际落点为准）
  - _需求：5.2_

- [ ] 9. `ensure-bwrap`/`ensure-docker` 端点收口为统一沙箱状态端点
  - 改动：整合为单一只读状态端点（复用或替代现有端点），需要 `security` 权限
  - 验证：`uv run pytest tests/integration/test_filesystem_api.py -q`
  - _需求：1.4, 6.2_

- [ ] 10. 新增 `ErrorCode` 与审计事件接入
  - 改动：`SANDBOX_NOT_READY`、`SANDBOX_SCOPE_NOT_ALLOWED`（若确认无法复用既有码）追加进 `ErrorCode` 枚举与 `errors.py` 的 `_DEFAULT_STATUS` 末尾，补齐 en/zh 与 dashboard `apiErrors`；沙箱状态变化与拒绝写入审计事件
  - 验证：`uv run pytest tests/unit/i18n -q`
  - _需求：6.1_

- [ ] 11. 文档与回归
  - 改动：更新 `docs/agent-backend-file-io.md` 沙箱相关章节、`CHANGELOG-intranet.md`、`docs/api-intranet.md`（若有端点变更）
  - 验证：人工核对 `/api/docs` 对应路由的 summary/description 可读
  - _需求：1.4, 6.2_

- [ ] 12. 收尾：全绿门禁
  - 改动：无代码改动，仅验证
  - 验证：`make all`；`uv run pytest -m "not live"`；若有前端改动 `cd dashboard && npx tsc -b && npm run lint`（有 vitest 用例则加 `npm run test`）
  - _需求：全部_
