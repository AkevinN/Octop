---
inclusion: always
---

# 行内网改造：全局约束与归属

本文件是 `.kiro/specs/` 下全部改造 spec 的共同前提。任何 spec 的 requirements / design / tasks 与本文件冲突时，以本文件为准；需要改本文件的，先改本文件再改 spec。

- 基线提交：`757fd12`（上游 1.0.1 之后的 npm lockfile 热修合并）。
- 文中行号均基于基线提交，仅作定位提示。实施时一律以**文件路径 + 符号名**为准，先 `rg` 定位再改。
- 目标：把面向个人与家庭自托管的 Octop，改造成可部署在银行行内网络的版本——完全断外网、满足等保与密评、可落在信创软硬件上。

## 1. 六条全局硬约束

这六条不属于任何一个 spec，但任意两个 spec 并行时都会被它们卡住。

### 1.1 数据库迁移：一律走 fork 独立迁移空间，禁止占用上游数字号

- 上游迁移由 `src/octop/infra/db/migrate.py` 的 `_discover` 按 `^(\d{3})_.*\.sql$` 发现，**重复版本号直接 `raise RuntimeError`**，发生在 `run_migrations` 第一步，表现为实例启动失败而不是测试变红。上游下一个迁移必然是 `016`。
- `run_migrations` 用单值水位线（`if version <= _current_version(db): continue`），任何"高位号段"方案都会让上游后续迁移被永久静默跳过。
- `_reconcile_pre_squash_schema_version` 在 `current > max_version` 时跳过所有迁移文件、直接把版本写成 max_version，只跑阶梯里显式列出的 helper。往上游号段里加 `016` 会让这类库被 clamp 却从未回填。
- **规则**：fork 的表结构变更一律写成 `src/octop/infra/db/migrations/forkNNN_<描述>.sql` 与同名 `.pg.sql` 成对文件，由 `w0-01-fork-migration-namespace` 提供的独立 runner 与 `_fork_schema_version` 水位表执行。`forkNNN_` 不匹配上游正则，对上游循环不可见。
- fork 迁移号**不预占**，按合入 fork 主干的先后顺序取下一个可用号。spec 的 design.md 里写 `forkNNN_<描述>`，合入前再定号。
- fork 迁移不改 `_schema_version`，因此**不改**分布在 8 个测试文件里的 `assert v == 15` 类断言。

### 1.2 i18n：不删键；fork 新增文案走 intranet overlay

- 真实的机器门禁只有四条：后端 `src/octop/i18n/{en,zh}.json` 键集相等（`tests/unit/i18n/test_catalog.py`）；dashboard `en.json` 的 `apiErrors` 键集 == 后端 `en.json` 的 `errors` 键集 == `ErrorCode` 全集（`tests/unit/i18n/test_errors.py`）；`tools` 字典全等（`test_tools.py`）；`skills` 逐 slug 相等（`test_skills.py`）。
- dashboard 两份 locale **没有任何对等测试**（en 5059 键、zh 5178 键，长期不对等）。漏改 dashboard zh 不会让 `make all` 变红，只会在界面露裸 key。
- 没有任何测试禁止孤儿键。`dashboard/src/locales/{zh,en}.json` 是全仓 churn 最高的两个文件（`--full-history` 108/106 次）。
- **规则一：裁剪能力时不删 i18n 键。** 孤儿键合法且零成本；删键是零功能收益、最高冲突成本的操作。
- **规则二：fork 新增的文案写进 overlay，不写进上游 JSON。** 路径由 `w0-04-fork-isolation-points` 建立：后端 `src/octop/i18n/intranet/{en,zh}.json`，前端 `dashboard/src/locales/intranet/{en,zh}.json`。overlay 深合并覆盖上游 bundle。
- **规则三：新增 `ErrorCode` 必须同批改齐**：`ErrorCode` 枚举（追加到末尾）、`src/octop/infra/errors.py` 的 `_DEFAULT_STATUS`（追加到末尾）、后端 en/zh 文案、dashboard en/zh 的 `apiErrors`（可放 overlay，由 w0-04 让三方相等测试读合并后的 bundle）。**漏登记 `_DEFAULT_STATUS` 不是降级，是崩**：`OctopError.__post_init__` 对它做无保护的字典下标，构造即 `KeyError`。能复用既有码就复用。

### 1.3 CI 门禁现状是空的，验收必须建立在 w0-02 之上

- `.github/workflows/ci.yml` 三个 job 全是 `make install/lint/typecheck/test`，零 npm、零 postgres。`Makefile` 的 `all` 不含前端。
- vitest 在 CI 与 `make` 里**从不执行**；`tests/support/postgresql.py` 在缺 `OCTOP_TEST_DATABASE_URL` 时整模块 skip，CI 上 100% 静默跳过并报绿。
- **规则**：凡把验收写成 vitest 用例或 PG 集成用例的 spec，都以 `w0-02-ci-gates` 已合入为前提，并在 tasks.md 里写明本地复现命令。

### 1.4 测试鉴权基线是共同验证前提

- `tests/support/auth.py` 被 28 个测试文件直接引用，`tests/integration/conftest.py` 的基础 `env` fixture 链式依赖它。
- `bootstrap_admin` 建出的管理员 `permissions=[]`，全靠 admin 绕过拿权限；`setup.py` 创建初始管理员时不传 `permissions=`。删绕过而不先回填 = 全站锁死，且 CLI 没有设置权限键的命令。
- **规则**：`w0-03-test-auth-baseline` 一次性交付新基线（admin 显式全量键、验证码与重认证走测试专用豁免、setup 契约为三员分立预留），先于任何动权限、验证码、会话的生产代码合入。

### 1.5 先删后改

- 裁剪（Wave 1）必须排在加固（Wave 3）之前。已量化的收益：删掉 5 个将被移除的 WebSocket 后，会话改造的"令牌移出 URL"从 7 个 WS 降到 2 个；安全热修省下 5.5 人日注定作废的白名单工作。
- 裁剪 spec 只删功能与入口，不做加固；加固 spec 不为已删除的能力写任何代码。

### 1.6 删除权限键必须同批清洗存量值

- `PERMISSIONS`（`src/octop/infra/users/permissions.py`）共 26 个键。用户的 `permissions` 列存的是键名列表；删掉某个键的定义后，存量用户的残值会让 `validate_permission_keys` 抛 `ValueError`，表现为管理员编辑任何老用户直接 500。
- **规则**：凡删除权限键的 spec（`w1-02`、`w1-03`、`w1-05` 等），同批写一条 fork 迁移把该键从 `users.permissions` 存量值中剔除，并补一条"含已删键的老用户可被正常编辑"的集成用例。
- 新增权限键必须登记进 `ALL_PERMISSION_KEYS`，并把新增受控路由文件手工加入 `tests/unit/api/test_acl_gate_coverage.py` 的 `GATED_FILES`（该清单是硬编码的，新路由不会被自动纳入校验）。

## 2. 代码层约定（写 design.md 时必须遵守）

| 约定 | 事实 | 规则 |
|---|---|---|
| 配置三触点 | `src/octop/config.py` 新增一个键必须动三处：`OctopConfig` dataclass 字段、env 覆盖块、`return OctopConfig(...)` 逐字段构造。漏第三处 = "开关配了但永远取默认值"，mypy/lint/测试都可能全绿 | 每个新配置键在 tasks.md 里列出三处改动；`w1-02` 会加一条单测把第三触点变成 CI 门禁 |
| utils 层不得读配置 | `infra/utils/` 按 AGENTS.md §5 不得 import `octop.config` 与非 utils 的 infra 包 | utils 层策略（SSRF 白名单、加密套件、日志脱敏规则）只能由 `infra/server.py` / `launch.py` 注入 setter；CLI 离线路径 `cli/support/db.py::open_cli_services` 单独接线 |
| 中间件顺序 | Starlette `add_middleware` 是 `insert(0)`，安装顺序与执行顺序相反；`@app.middleware("http")` 同理。`api/middleware/jwt_auth.py` 有 `_INSTALL_ATTR` 幂等守卫，`setup_lockdown.py` 没有 | 中间件栈顺序由 `w3-01` 一次定死；新中间件照 `jwt_auth.py` 的幂等模式写 |
| 第二个 ASGI 应用 | `infra/setup/tls/http_companion.py` 由 `launch.py` 以第二个 uvicorn.Server 跑在 80 端口，`build_app` 注册的一切都不覆盖它 | 安全头、限流类改动必须显式覆盖它或证明它已下线 |
| Agent 中间件注入点 | `infra/agents/manager.py` 的 `agent_middleware` 是一条硬编码列表（≈L2811），在 `middleware=agent_middleware or None`（≈L2936）交给 harness | `w1-02` 把它改成注册式装配；其余 spec 只新增一个中间件模块 + 一行注册，不直接改该列表 |
| settings store 接线 | `manager.py::replace_persistence`（≈L390-413）在控制面 rebind 后重建 6 个 settings store | 新 settings store 必须在 `__init__`、`boot()`、`replace_persistence` 三处接线，漏掉即 rebind 后静默读旧 repo |
| 强制工具禁用 | 不存在 host 级强制禁用；`tool_catalog.py::effective_tools_disabled` 只读 per-agent cfg；同步路径有 `persist_tools_disabled`、`sync_tools_disabled`、`sync_effective_tools_disabled` 与组装 harness_cfg 多处 | 强制禁用只走 `w1-02` 的 `forced_disabled_tools`，所有同步路径都要经过它 |
| 模板范式 | settings store 照 `infra/agents/security/policy_store.py`（明文进 `settings`、密钥进 `secrets`） | 新策略 store 复用该范式，共用一个策略 store 基类 |
| 路由挂载 | `api/app.py` 是一条平铺的 `_RouterMount(...)` 列表 | 下线路由走 `w0-04` 的 `_FORK_DISABLED_MOUNTS`，或物理删除时同批删 mount 行 |
| 测试命令 | AGENTS.md：`uv run pytest`，不写裸 `pytest`；`rg` 没有 `--include` 参数 | 验收命令一律可直接执行；跨平台用例遵守 AGENTS.md §7 |

## 3. 共享资产归属

每项资产只有一个 owner spec；其余 spec 只消费、不重复实现。

| 资产 | owner | 说明 |
|---|---|---|
| fork 迁移 runner 与 `_fork_schema_version` | `w0-01` | 覆盖 `start()`、`bind_control_plane()`、rebind、CLI 离线、备份恢复全部启动路径 |
| CI frontend job 与 postgres service | `w0-02` | |
| `tests/support/auth.py` 新基线 | `w0-03` | |
| i18n overlay、`_FORK_DISABLED_MOUNTS`、连接器目录 `_BASE + _FORK_ENTRIES`、`make relock`、`CHANGELOG-intranet.md`、`docs/api-intranet.md`、上游同步手册、AGENTS.md §5/§9 勘误 | `w0-04` | AGENTS.md §7 迁移段由 `w0-01` 改 |
| SSRF 内网白名单 | `w0-05` | 四个放行点含最底层 `_parse_https_host`；默认空白名单 = 行为字节级不变 |
| 能力开关框架 `capabilities.<name>.enabled`、`require_capability`、`_mount_if_capable`、配置三触点单测、`config.py` 重复块修复、agent 中间件注册式装配、`forced_disabled_tools` | `w1-02` | 名字空间预留后续 spec 需要的键位 |
| 云验证码 provider 删除 | `w1-05` | 滑块保留为过渡态 |
| 验证码终态（服务端出题的本地图形验证码） | `w3-01` | |
| 在线语音删除（edge / 腾讯 / 小米）与 `edge-tts` 依赖 | `w1-05` | 保留可指向行内网关的 OpenAI 兼容语音 |
| `opencode_session.py` 删除 | `w1-05` | |
| 安装向导持久关闭标记与 resume-wizard 鉴权 | `w1-01` | `w3-04` 只消费 |
| 依赖收敛：`pyproject.toml` 收窄、harness-* 入行内 Git、harness-gateway 重打包去 IM SDK、运行期下载全部关闭、Monaco 与 Scalar 本地化、入口脚本幂等 | `w2-01` | 其余 spec 只声明需要的离线资产；lock 文件由改依赖的 spec 在末尾 commit 用 `make relock` 重生成 |
| 许可证、SBOM、SCA、SAST 替代 codeql、制品签名 | `w2-02` | `w1-04` 删 `.github/` 工作流时保留 `ci.yml` 与 `codeql.yml`，由 w2-02 提供替代后再删 |
| PG 方言家族、关闭运行期 DDL、DDL 导出、连接池参数、事件循环卸载热点 | `w2-03` | |
| 中间件栈顺序契约、唯一的 `api/common/client_ip.py`、per-server 限流器、安全响应头与 CSP、上传魔数与杀毒 | `w3-01` | |
| `audit_log` 字段集（冻结）、`AuditContext`、request_id contextvar 与响应头、唯一的日志脱敏 Formatter、`ACTOR_ADMIN` 14 处替换、线程软删除与保留期、syslog 单向外发、下载出口后端兜底与留痕 | `w3-02` | 哈希链由 `p2-03` 在冻结字段集之上做 |
| 权限判定收口（后端 14 处 + 前端 4 处绕过）、角色实体与三员互斥、存量 permissions 清洗、CLI 离线授权、知识库 `list_visible` 的 admin 绕过删除 | `w3-03` | 知识库三级 ACL 归 `p2-05` |
| 会话表、短时令牌、吊销、令牌移出 URL、口令策略、登录模式 | `w3-04` | 身份源适配器归 `p2-11` |
| `CryptoProvider` 接口、信封（二进制 + base64 文本双载体）、local provider、四张表明文列加密、四套既有加密实现收敛 | `w3-05` | KMS / SDF / 国密后端归 `p2-02` |
| providers 响应体脱敏契约 | `w1-01` 传输层 → `w3-05` 落库 → `p2-06` 在契约下加字段 | 顺序不可反；`w2-04` 只用进程级 CA，不动响应体 |

## 4. 待行方拍板项的默认假设

spec 按下列假设起草。行方答复与假设不同时，按"若…"列调整。

| # | 问题 | 默认假设 | 若答复不同 |
|---|---|---|---|
| D1 | 统一认证协议 | OIDC（现成通用 provider） | CAS / SAML / LDAP 走 `p2-11` |
| D2 | 行内大模型平台 | OpenAI 兼容网关，含 Embedding | 无 Embedding 则知识库降级为纯全文检索 |
| D3 | 控制面数据库 | PG 系（人大金仓或 openGauss），SQLite 仅用于开发测试 | 达梦 / OceanBase / TiDB 需新增第三方言，约 50-70 人日，另立项 |
| D4 | 部署形态 | 容器平台单副本 + 冷备手工切换；x86_64 与 arm64；不涉及龙芯 | 龙芯需全量自编译 wheel |
| D5 | 高可用 | 一期单活 + 冷备；秒级切换进二期 `p2-08` | |
| D6 | Agent 命令执行 | 保留但收紧（`w3-06`：工作区为根、执行需人工审批）；完整沙箱进二期 `p2-01` | 不保留则 `w3-06` 改为整体禁用执行工具，`p2-01` 取消 |
| D7 | 是否跟上游 | 长期 fork；每 2-4 个上游 release 同步一次；跟 main 上的 `v*` tag，外加 hotfix 例外通道 | |
| D8 | 国密与密评 | 要求，但进二期 `p2-02`；一期信封保留算法标识 `suite_id` | 一期强制则提前"SM4/SM3 软实现 + 算法标识"约 8 人日 |
| D9 | `desktop/`、`fnos/` | 不交付，`w1-04` 删除 | 交付则 w1-04 保留，w2-01/w2-02/w3-04/w3-05 各自补打包渠道改动 |
| D10 | 语音能力 | 保留 OpenAI 兼容 STT/TTS（可指向行内），删其余 | 整体下线则 w1-05 连同语音路由一并删除 |
| D11 | 验证码终态 | 服务端校验的本地图形验证码 | |
| D12 | RBAC 终局 | 三员分立，互斥角色；admin 退化为带显式权限键的角色 | |
| D13 | harness-* 源码 | 可得（纯 Python sdist），导入行内 Git 做内部分支 | 不可得则 `p2-06` 的行内 IM 不可执行 |
| D14 | 机构 / 部门数据域 | 不在本轮范围 | 要则另立 spec（代码零基础：`users` 表无任何组织列） |

## 5. 上游同步策略

- 放弃"vendor 镜像分支 + 补丁清单"：fork 声明面 240 个文件里 132 个上游 churn ≥ 10，每个上游 release 平均命中 51 个，补丁会反复 fuzz 失败，且承载不了大量新增文件。
- 用长期 fork 分支 + 第 3 节的隔离点。每 2-4 个上游 release（约 5-10 天）同步一次：1 个 release 命中 66 个 fork 文件，4 个 release 仅 81 个，13 个 release（约一个月）骤增到 203 个。
- `uv.lock` 与 `dashboard/package-lock.json` 不做 patch：冲突一律取上游，再在行内私服用 `make relock` 重生成。
- `CHANGELOG.md`、`docs/api.md` 不写 fork 内容，分别写进 `CHANGELOG-intranet.md` 与 `docs/api-intranet.md`。
- `errors.py` 的 fork 新码追加到枚举末尾与 `_DEFAULT_STATUS` 末尾，不按字母序插入。
- 不可约的热点内核串行处理：`infra/agents/manager.py`、`infra/gateway/process/processor.py`、`infra/db/migrate.py`。在这三个文件里只留单行调用，逻辑下沉到新模块。

## 6. 已知的文档漂移

写 spec 时不要照抄以下内容：

- AGENTS.md §7 写"bump the version assertion … (currently `v == 7`)"，实际是 15，且断言分布在 8 个测试文件。fork 迁移不需要改这些断言。
- AGENTS.md §5 / §9 引用的 `api/jwt_tokens.py` 不存在，JWT 逻辑在 `api/deps.py` 与 `api/middleware/jwt_auth.py`。
- README 说的 `~/.octop/secrets/` 目录不存在，JWT 密钥在数据库 `secrets` 表。
- 记忆层在 PG 下是共享 schema 加 namespace 列，不是每个 Agent 一个 schema。

## 7. 实施顺序

目录编号即推荐的实施顺序。同一波次内，列在同一行的可以并行。

| 波次 | 顺序 |
|---|---|
| Wave 0 闸门 | `w0-01` `w0-02` `w0-03` `w0-04` `w0-05`（互相独立，可并行） |
| Wave 1 先删后改 | `w1-01`（安全热修，可最先单独合入）→ `w1-02` → `w1-03` → `w1-04` → `w1-05` |
| Wave 2 能在内网跑起来 | `w2-01` 与 `w2-02` 并行 → `w2-03` → `w2-04` |
| Wave 3 合规最低集 | `w3-01` → `w3-02` → `w3-03` → `w3-04` → `w3-05`；`w3-06` 在 `w1-02`、`w0-05` 之后可与本波并行 |
| Wave 4 收口 | `w4-01` 与 `w4-02` 并行 |
| 二期 | `p2-01` … `p2-11`，彼此无功能耦合，按行方优先级取用；各自的前置写在 spec 头部 |

起草与实施时，假设编号在前的 spec 均已合入：不为前序 spec 已删除的文件规划改动；对后序 spec 将删除的文件只做最小必要改动。
