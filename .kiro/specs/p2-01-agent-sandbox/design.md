# 设计文档：Agent 强制沙箱

> spec：`p2-01-agent-sandbox` ｜ 波次：二期 ｜ 基线：`757fd12` ｜ 预估：10 人日
> 前置：`w3-06-agent-execution-hardening` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 概述

`w3-06` 把 Agent 的能力面（工具白名单、环境变量、SSRF、连接器权限）收紧，但没有触碰执行时的**隔离机制**本身；`w2-01` 把沙箱运行时的联网安装路径清空，但明确把"是否强制、是否预装、容器 user namespace 权限"移交给本 spec（`w2-01` design.md ≈L382；`w3-06` design.md ≈L107）。本 spec 在两者之上补最后一层：让沙箱从"配置对了才生效的可选项"变成"默认强制、缺失即拒启或明确降级"的地基，并处理信创内核前提与 OS 用户分离这两个此前完全没有代码基础的维度。

## 现状

以下事实均在仓库基线 `757fd12` 内核实：

- `src/octop/infra/utils/bwrap.py`（215 行）：模块 docstring 明确"harness only constructs `BubbledLocalShellBackend` when Linux + `virtual_mode` + non-host root + `bwrap`; otherwise plain `local_shell`"——即沙箱是否生效完全隐式依赖三个条件同时成立，不满足时默默回退裸执行，不拒绝、不告警。`w2-01` 已把该文件收窄为纯探测（三分支 `skipped`/`ready`/`degraded`，无安装逻辑）。
- `src/octop/launch.py` L16-39：`_ensure_linux_bubblewrap`/`_schedule_linux_bubblewrap_ensure` 在 `octop run` 启动时后台跑一次探测（L76 创建任务、L150 取消），探测结果目前**不影响启动流程**——即使 `degraded` 也照常起服务。
- `src/octop/infra/backend/docker_spec.py`：`DEFAULT_SANDBOX_PREFIX = "octop_sandbox"`（L8）；spec 字段含 `sandbox_scope`、`sandbox_prefix`（L24-25）；`sandbox_scope == "fixed"` 的判定在 L52；规范化函数（L63-73）里 `sandbox_prefix` 缺省取 `DEFAULT_SANDBOX_PREFIX`（L71），`sandbox_scope` 缺省取 `"agent"`（L72-73）。今天没有任何代码拒绝 `fixed` 作用域或校验前缀命名空间是否与其他部署冲突。
- `src/octop/infra/backend/probe.py`：L100-115 按 `sandbox_scope`（`user`/`fixed`/`agent`）构造探测用的候选 spec，L170 对 `sandbox_prefix` 同样取默认值——这是消费方，规则收紧应落在 `docker_spec.py`，`probe.py` 只随之受益。
- `docker/Dockerfile`：基线全文无 `USER` 指令；`w2-01` 已规划加 `groupadd/useradd` 非 root 用户（uid 10001）与 `USER 10001:10001`（`w2-01` design.md ≈L159），但**没有**在 apt 层加装 `bubblewrap`——`w2-01` design.md 明确把"镜像是否预装 bubblewrap"列为未决项移交 `w3-06`，`w3-06` 又转交本 spec。
- `tests/integration/test_bwrap_jail.py` 存在（源分析 blast_radius 核实为 13 个用例，其中 79、160 行专测 host-root 场景），说明仓库已有 bwrap jail 的集成测试骨架，本 spec 的强制化改动需要在其上扩展而非另起一套。
- `src/octop/infra/mobile/docker_install.py` 在基线仍存在（内置 `sudo -n` 提权安装 Docker 的第三条联网路径），但按 `w3-06` design.md ≈L108 的交接记录，该文件随远程手机功能整体删除，属 `w1-02`；实施本 spec 时应先确认 `w1-02` 是否已删除该文件，若仍在则说明假设不成立，需回退到 `w1-02` 处理而非在本 spec 顺手删除。
- `config.py`（626 行）今天没有任何沙箱相关字段；`OCTOP_SANDBOX_MODE` 等配置需求首现于本 spec。

## 方案

1. **强制门槛**：新增 `sandbox_policy.py`（或复用 `w3-06` 若已建立同名模块下沉的通用策略层——实施时以 `w3-06` 落地后的实际模块结构为准）里的 `sandbox_runtime_status()` 与 `assert_sandbox_ready(mode)`，在 `launch.py` 的启动路径里，把探测结果从"仅记日志"改为"按 `OCTOP_SANDBOX_MODE` 决定 fail-fast 或标记 degraded"。
2. **离线预装**：Dockerfile 最终层的 apt 列表加入 `bubblewrap`（与 `w2-01` 已加的非 root 用户属同一改动窗口内不同的具体项，不重复其 uid/USER 部分）。
3. **内核前提探测**：`bwrap.py` 的探测函数在"存在 `bwrap` 二进制"之外，新增一次轻量自检——实际尝试创建一个最小 user namespace（或读取 `/proc/sys/user/max_user_namespaces` 与内核提供的 sysctl），失败时把 `degraded` 的 `reason` 精确到 `userns_unavailable`，与 `not_installed` 区分，便于行方判断是缺包还是内核策略问题。
4. **Docker 沙箱边界**：`docker_spec.py` 新增校验函数，默认拒绝 `sandbox_scope=="fixed"`（除非显式部署级开关放行），并把 `sandbox_prefix` 与部署标识拼接，减少跨部署容器名冲突面。
5. **OS 用户分离**：容器形态下，命令执行通过 bwrap user namespace 映射与服务进程（uid 10001）区分身份；裸机形态下，新增一个独立低权限系统账户约定（文档 + 探测，而非本 spec 自建账户管理系统），`enforce` 模式下缺失该账户即拒启。
6. **端点收口**：`ensure-bwrap`/`ensure-docker` 在 `w3-06`/`w2-01` 之后已无副作用，本 spec 决定是否保留为只读状态端点或直接下线，改为统一的沙箱状态查询端点。

具体文件级改法待 `w3-06`/`w2-01` 落地后重新定位，此处不做逐行改动清单。

## 组件与接口

实施时以一期落地后的代码重新定位，此处只列预期新增/改动的模块边界（不含行号）：

- `src/octop/infra/backend/sandbox_policy.py`（新增或复用 `w3-06` 已建立的同名策略层）：`sandbox_runtime_status() -> SandboxStatus`、`assert_sandbox_ready(mode: str) -> None`。
- `src/octop/infra/utils/bwrap.py`：`ensure_bubblewrap()` 返回值的 `reason` 枚举扩展（新增 `userns_unavailable`）。
- `src/octop/infra/backend/docker_spec.py`：新增 `assert_sandbox_scope_allowed(spec, *, deployment_id)`。
- `src/octop/launch.py`：启动路径接入 `assert_sandbox_ready`。
- `src/octop/config.py`：新增 `OCTOP_SANDBOX_MODE` 等字段（见下节）。
- `docker/Dockerfile`（及若交付则同步 `fnos/docker/Dockerfile`）：apt 层加 `bubblewrap`。

## 数据模型

无新增数据表。沙箱状态与拒绝事件是运行期内存态 + 审计事件（写入格式由 `w3-02` 冻结的 `audit_log` 字段集承载），不涉及 schema 变更，因此无 `forkNNN_` 迁移。

## 配置

新增配置键需在 `config.py` 补齐三触点（`OctopConfig` dataclass 字段、`load_config` 内联 env 覆盖块、`return OctopConfig(...)` 逐字段构造）：

| 配置键 | 默认值 | 说明 |
|---|---|---|
| `OCTOP_SANDBOX_MODE` | `enforce` | `enforce`/`warn`/`off`；三值语义见需求 1 |
| `OCTOP_SANDBOX_ALLOW_FIXED_SCOPE` | `false` | 是否允许 `docker_spec.py` 的 `sandbox_scope="fixed"` |
| `OCTOP_SANDBOX_DEPLOYMENT_ID` | 空 | 拼入 `sandbox_prefix` 的部署标识，用于同宿主多实例隔离命名空间 |
| `OCTOP_SANDBOX_EXEC_USER`（裸机形态，可选） | 空 | 裸机部署下命令执行使用的独立系统账户名；为空且 `enforce` 时启动期拒启 |

## 错误处理

预期新增 `ErrorCode`（须同批登记枚举末尾与 `errors.py` 的 `_DEFAULT_STATUS` 末尾，并补齐 en/zh 与 dashboard `apiErrors`，能复用尽量复用）：

- `SANDBOX_NOT_READY`（建议映射 503）：`enforce` 模式下沙箱不可用导致的启动拒绝。
- `SANDBOX_SCOPE_NOT_ALLOWED`（建议映射 400）：`sandbox_scope="fixed"` 未被部署放行时的配置拒绝。

实施时优先复核 `w3-06`/`w0-05` 是否已引入语义相近的错误码（如通用的"部署策略拒绝"类错误），能复用则不新增。

## 安全考虑

- 强制沙箱的核心风险是"验收条件本身不可达成"：若信创目标内核禁用 unprivileged user namespace，bubblewrap 方案整体不成立，需退回 Docker 沙箱或 seccomp+chroot 等替代方案，工作量与本设计不同量级（详见风险）。
- OS 用户分离在容器形态下依赖 bwrap 的 user namespace 映射，而不是简单的"两个 Linux 用户"——需确认容器运行时（Docker/containerd）本身允许嵌套 user namespace，这与"容器以 uid 10001 非 root 运行"是两件不同的事，后者由 `w2-01` 完成，不能相互替代。
- `docker_spec.py` 的 `sandbox_scope="fixed"` 一旦允许，等于多个专家共享同一沙箱容器，是本 spec 收紧的主要目标之一，默认必须拒绝。

## 测试策略

以下命令均为一期落地后需要重新核实文件仍存在的前提下可执行；具体断言随届时代码结构调整。

- 单测：`uv run pytest tests/unit/infra/utils/test_bwrap.py tests/unit/backend/test_docker_spec.py -q`
- 集成：`uv run pytest tests/integration/test_bwrap_jail.py -q`
- 整体门禁：`uv run pytest -m "not live"` 与 `make all`
- 前端如涉及沙箱状态展示：`cd dashboard && npx tsc -b && npm run lint`
- i18n（若新增文案/错误码文案）：`uv run pytest tests/unit/i18n -q`

## 与其他 spec 的交接

- **依赖 `w3-06`**：`sandbox_policy` 若已建立同名模块，本 spec 复用；能力开关注册式装配（`agent_middleware`）由 `w1-02` 提供，本 spec 只新增模块与注册项。
- **依赖 `w2-01`**：`ensure_bubblewrap()` 三分支探测契约、Dockerfile 非 root 用户（uid 10001）、`ensure-bwrap`/`ensure-docker` 已无副作用，均由 `w2-01` 交付，本 spec 只加"强制"与"预装"。
- **依赖 `w1-02`**：`mobile/docker_install.py` 提权安装路径预期随远程手机功能删除；本 spec 不涉及该文件，实施前需确认假设成立。
- **交付给 `p2-02`（KMS 与国密）**：沙箱拒绝事件里若涉及密钥/凭据访问，`p2-02` 的密钥托管边界应与本 spec 的 OS 用户分离结果对齐（沙箱内不应能直接读到主密钥）。
- **交付给 `p2-03`（审计防篡改）**：本 spec 只产出沙箱状态变化与拒绝事件，落盘的哈希链与外发由 `p2-03` 在 `w3-02` 冻结字段集之上完成。
- **看似相关但归别处**：Docker 类后端（`opensandbox`/`[docker]` extra）是否保留是 `w3-06`/`w2-01` 的决策项，本 spec 不重新讨论去留，只在"保留"的前提下收紧其沙箱边界。

## 风险与回滚

- **【高】信创内核前提不满足**：若目标机型禁用 `kernel.unprivileged_userns_clone`，bubblewrap 整体不可用，需退回 Docker 沙箱或 seccomp+chroot，工作量不在同一量级（参考约 +8-15 人日）。回滚：`OCTOP_SANDBOX_MODE=warn` 可在探测失败时不阻断启动，用于分阶段灰度。
- **【中】Docker 沙箱后端需要 `/var/run/docker.sock` 或等价权限**：等保三级下通常不被接受；若行方不批准，Docker 沙箱路径需整体下线，只保留 bwrap。
- **【中】OS 用户分离在裸机部署下缺少现成机制**：仓库当前没有"为命令执行专门创建系统账户"的代码基础，是本 spec 唯一需从零设计的部分，工作量最不确定。
- **回滚**：所有新增行为均由 `OCTOP_SANDBOX_MODE`（及裸机 `OCTOP_SANDBOX_EXEC_USER`）开关控制，设为 `warn`/`off` 或留空即可整体回退到 `w3-06` 交付时的行为，不需要代码回滚。

## 待行方确认

无（六条全局硬约束与 D1-D14 均未直接覆盖"信创内核是否支持 unprivileged user namespace"这一技术性未知项；该项不是需要行方拍板的政策决策，而是需要在目标机型上实测的前提条件，已在"风险与回滚"中列出，不作为 D 编号提出）。
