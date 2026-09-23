# 需求文档：Agent 强制沙箱

> spec：`p2-01-agent-sandbox` ｜ 波次：二期 ｜ 基线：`757fd12` ｜ 预估：10 人日
> 前置：`w3-06-agent-execution-hardening` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 引言

`w3-06` 交付的是"收紧但不隔离"的一期底线：execute 仍以服务进程的 OS 用户执行，是否套 bubblewrap 取决于 `root_dir` 是否非宿主根、`bwrap` 是否恰好存在（`src/octop/infra/utils/bwrap.py` 模块 docstring：harness 只在 Linux + `virtual_mode` + 非宿主根 + 有 `bwrap` 时才用隔离 backend，否则回退纯 `local_shell`，即"缺了就不隔离"而非"缺了就拒绝"）。`w2-01` 只把 bubblewrap/Docker 的"运行期缺了就装"改成"运行期缺了就报错"（三分支 `skipped`/`ready`/`degraded`，见 `w2-01` design.md ≈L103-106），既没有把镜像预装 bubblewrap，也没有处理容器内跑 bubblewrap 需要的 unprivileged user namespace 权限，且没有让"沙箱不可用"这件事阻断 Agent 启动——这两项决策权都显式移交给了本 spec（`w3-06` design.md ≈L107："交付给 p2-01：执行进程的文件系统与网络隔离、镜像预装 bubblewrap、容器 user namespace、`ensure-bwrap` 等端点的最终去留"）。

本 spec 把"能力"补成"强制"：Agent 执行面在一期收紧的基础上，加上不可绕过的 bubblewrap/Docker 沙箱、镜像预装、信创内核前提的探测与降级、Docker 沙箱边界（`sandbox_scope`/`sandbox_prefix`）收紧、以及命令执行与服务进程的 OS 用户分离。

**范围内：**
- Agent execute 强制走沙箱（bwrap 或 Docker），无法降级为裸执行，除非部署方显式选择 `warn`/`off` 模式。
- 离线沙箱供给：镜像构建期预装 bubblewrap（`w2-01` 已把运行期装包路径清空，本 spec 补上构建期安装），运行期只探测不安装（沿用 `w2-01` 的 `ensure_bubblewrap()` 三分支契约）。
- 信创内核前提（`kernel.unprivileged_userns_clone` 等）的探测与降级路径，含容器内 user namespace 权限的处理。
- `infra/backend/docker_spec.py` 的 `sandbox_scope`/`sandbox_prefix` 边界收紧：默认作用域、跨专家/跨部署穿越的拒绝。
- 命令执行进程与服务进程的 OS 用户隔离（容器与裸机两种部署形态）。
- `OCTOP_SANDBOX_MODE` 配置项与启动期 fail-fast / 降级逻辑，及 `ensure-bwrap`/`ensure-docker` 端点的最终去留。

**范围外（归属见 `.kiro/steering/` 第 3 节与各 spec 头部）：**
- 默认 backend 从 host-root 改为 workspace 根、`create()` 时显式落盘 backend、execute 环境变量白名单化、`hitl`/`tool_guard` 默认值与策略锁、实例级强制禁用工具、自定义 MCP 收敛、SSRF 内网白名单、`/api/filesystem/*` 权限收紧——均属 `w3-06`（已假设合入）。
- `bwrap.py`/`docker_env.py` 运行期去安装化、Dockerfile 非 root 用户（uid 10001）、离线制品仓——均属 `w2-01`（已假设合入）。
- `mobile/docker_install.py` 的提权安装路径——随远程手机功能整体删除，属 `w1-02`（已假设合入）。
- KMS/国密后端、审计防篡改——属二期 `p2-02`/`p2-03`，本 spec 只产生沙箱拒绝事件供其消费，不实现落盘细节之外的加固。

## 需求

### 需求 1：Agent execute 强制走沙箱，不可静默降级为裸执行

**用户故事：** 作为行方安全负责人，我希望 Agent 的命令执行工具默认必须在沙箱内运行，以便一次配置错误或环境缺失不会让命令直接落在宿主或服务容器的完整权限下。

#### 验收标准
1. 当 `OCTOP_SANDBOX_MODE=enforce`（默认值）且沙箱运行时（bwrap 或 Docker 引擎）不可用时，Agent 启动应当拒绝启动带 execute 能力的实例，而不是静默回退为裸 `local_shell`。
2. 如果 `OCTOP_SANDBOX_MODE=warn`，那么系统应当允许降级执行但在启动日志与 `/api/health` 的 sandbox 字段中标记为 `degraded`。
3. 在沙箱运行时状态为 `ready` 期间，Agent execute 工具应当始终经由沙箱后端（bwrap jail 或 Docker sandbox）执行，不存在绕过沙箱直接调用宿主 shell 的路径。
4. 系统应当始终把沙箱可用性状态暴露在一个管理员可查询的端点（复用或替代现有 `ensure-bwrap`/`ensure-docker`），供部署自检与监控使用。

### 需求 2：离线镜像预装 bubblewrap，运行期只探测不安装

**用户故事：** 作为运维人员，我希望容器镜像在构建期就带好 bubblewrap，以便断网部署下沙箱能力开箱可用，不依赖运行期联网或提权安装。

#### 验收标准
1. 当执行 `docker build -f docker/Dockerfile .` 时，产出镜像应当在 `command -v bwrap` 下有输出。
2. 系统应当始终保持 `w2-01` 已交付的 `ensure_bubblewrap()` 三分支契约（`skipped`/`ready`/`degraded`）不变，本 spec 不新增运行期安装分支。
3. 如果 `fnos/docker/Dockerfile` 仍在交付范围内（`w1-04` 默认删除；若行方答复为交付则 `w2-01` 已补齐非 root 化），那么本 spec 应当在该镜像的最终层同步预装 bubblewrap。

### 需求 3：探测信创内核前提，不满足时按策略降级

**用户故事：** 作为部署工程师，我希望系统在启动时探测目标内核是否支持 unprivileged user namespace，以便在信创 OS（麒麟/统信/欧拉等）上提前发现沙箱不可用，而不是等到某次命令执行才报错。

#### 验收标准
1. 当服务在 Linux 上启动时，系统应当探测 `kernel.unprivileged_userns_clone`（或等价的 `/proc/sys/user/max_user_namespaces` 等信号）与 bubblewrap 实际创建 jail 的能力，而不是只探测二进制是否存在。
2. 如果内核不支持 unprivileged user namespace，那么系统应当把沙箱状态标记为 `degraded`（原因含 `userns_unavailable`），并按 `OCTOP_SANDBOX_MODE` 决定拒绝启动还是降级放行。
3. 系统应当始终把探测结果（含内核前提检查项）记录进启动日志，便于行方在信创机型验收时留证。

### 需求 4：收紧 Docker 沙箱作用域，禁止跨专家/跨部署穿越

**用户故事：** 作为平台管理员，我希望使用 Docker 后端的沙箱容器名严格按作用域隔离，以便一个专家的沙箱容器不会被另一个专家或另一套部署复用、探测或接管。

#### 验收标准
1. 当 `infra/backend/docker_spec.py` 规范化一个 Docker 类型的 backend spec 时，`sandbox_scope` 与 `sandbox_prefix` 缺省应当分别取 `agent` 与 `octop_sandbox`（保持现有默认值不变）。
2. 如果 `sandbox_scope` 取值为 `fixed`（跨专家共享容器）且当前部署未显式允许该模式，那么系统应当拒绝该配置并返回可读错误，而不是静默创建共享沙箱。
3. 系统应当始终以 `sandbox_prefix` + 部署标识组成的命名空间前缀命名沙箱容器，防止不同部署（如同一台宿主机上的测试与生产实例）的沙箱容器名冲突或被互相探测到。

### 需求 5：命令执行与服务进程使用不同的 OS 用户身份

**用户故事：** 作为安全审计人员，我希望 Agent 执行的命令不与 Octop 服务进程共享同一个 OS 用户身份，以便命令执行面被攻陷时不能直接读写服务进程的凭据与数据库文件。

#### 验收标准
1. 当容器内启动服务进程时，服务进程应当以 `w2-01` 已建立的非 root 用户（uid 10001）运行；执行 Agent 命令时，系统应当通过 bwrap 的 user namespace 映射或独立的执行身份，使命令进程在文件系统与凭据可见性上与服务进程隔离。
2. 如果部署形态为裸机（非容器）且 `OCTOP_SANDBOX_MODE=enforce`，那么系统应当要求存在一个独立于服务进程运行账户的低权限系统账户用于命令执行，并在该账户缺失时拒绝启动或明确降级。
3. 系统应当始终保证命令执行身份对服务进程的 `~/.octop`（含 `secrets` 表所在的数据库文件、`env` 文件）不具备直接读写权限，除沙箱显式放行的挂载点之外。

### 需求 6：沙箱状态与拒绝事件可观测、可审计

**用户故事：** 作为运维与合规人员，我希望沙箱降级、拒绝启动、内核前提不满足等事件被记录，以便等保测评与故障排查有据可查。

#### 验收标准
1. 当沙箱状态从 `ready` 变为 `degraded`，或因 `enforce` 模式拒绝启动某个 Agent 时，系统应当写一条可被 `audit_repo`（`w3-02` 冻结的字段集）消费的事件（本 spec 只产出事件，落盘格式与保留期由 `w3-02`/`p2-03` 定）。
2. 系统应当始终把当前沙箱运行时状态（`ready`/`degraded`/`skipped` 及原因）通过管理端点暴露，且该端点需要 `security` 权限而非任意登录用户可查（对齐 `w3-06` 已确立的端点收权模式）。
