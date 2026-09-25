# 行内网改造 spec 索引

本目录把 Octop 的银行行内网改造拆成 33 个 Kiro spec，每个 spec 含 `requirements.md`（需求，EARS 验收标准）、`design.md`（设计）、`tasks.md`（实施计划）三份文档。

- **全局约束**：[`../steering/intranet-transformation.md`](../steering/intranet-transformation.md)。六条硬约束、代码层约定、共享资产归属、待拍板项的默认假设、上游同步策略都在这里，所有 spec 以它为准。
- **基线**：提交 `757fd12`（上游 1.0.1 之后的 npm lockfile 热修合并）。文档里的行号只作定位提示，实施时以路径加符号名为准。
- **顺序**：目录编号即推荐的实施顺序。起草时假设编号在前的 spec 均已合入。

## 怎么用

1. 先读 steering，再读目标 spec 的 requirements → design → tasks。
2. 按 tasks.md 的顺序实施，每个顶层任务完成后可独立提交；提交前运行任务里写明的验证命令，收尾任务要求 `make all` 全绿。
3. 各 spec 的"待行方确认"引用 steering 第 4 节的 D 编号。行方答复与默认假设不同时，按该节的"若…"列调整对应 spec。

## 一期：能进内网、能过评审（22 个，合计约 337 人日）

| 波次 | spec | 标题 | 预估人日 | 前置 |
|---|---|---|---|---|
| Wave 0 | [`w0-01-fork-migration-namespace`](w0-01-fork-migration-namespace/) | fork 独立迁移空间 | 4.5 | — |
| Wave 0 | [`w0-02-ci-gates`](w0-02-ci-gates/) | CI 前端与 PostgreSQL 门禁 | 2.5 | — |
| Wave 0 | [`w0-03-test-auth-baseline`](w0-03-test-auth-baseline/) | 测试鉴权基线 | 3.25 | — |
| Wave 0 | [`w0-04-fork-isolation-points`](w0-04-fork-isolation-points/) | fork 隔离点与上游同步机制 | 5 | w0-02 w0-01 |
| Wave 0 | [`w0-05-ssrf-intranet-allowlist`](w0-05-ssrf-intranet-allowlist/) | SSRF 守卫内网白名单 | 3 | — |
| Wave 1 | [`w1-01-security-hotfix`](w1-01-security-hotfix/) | 五个现成漏洞热修 | 7 | w0-01 w0-02 w0-03 w0-04 |
| Wave 1 | [`w1-02-capability-trim`](w1-02-capability-trim/) | 高危能力裁剪与横切框架 | 16 | w0-01 w0-02 w0-03 w0-04 w1-01 |
| Wave 1 | [`w1-03-online-fetch-trim`](w1-03-online-fetch-trim/) | 外网获取类功能裁剪 | 18 | w0-01 w0-02 w0-03 w0-04 w1-02 |
| Wave 1 | [`w1-04-content-trim`](w1-04-content-trim/) | C 端内容与非交付工程裁剪 | 8.5 | w0-02 w0-03 w0-04 w1-02 w1-03 |
| Wave 1 | [`w1-05-saas-decoupling`](w1-05-saas-decoupling/) | 公网 SaaS 断开 | 24 | w0-01 w0-02 w0-03 w0-04 w0-05 w1-01 w1-02 |
| Wave 2 | [`w2-01-offline-build`](w2-01-offline-build/) | 离线构建与依赖收敛 | 20 | w0-01 w0-02 w0-03 w0-04 w1-02 w1-03 w1-04 w1-05 |
| Wave 2 | [`w2-02-supply-chain-compliance`](w2-02-supply-chain-compliance/) | 许可证与供应链合规 | 15 | w0-02 w0-04 w1-02 w1-03 w1-04 w1-05 |
| Wave 2 | [`w2-03-database-adaptation`](w2-03-database-adaptation/) | 信创数据库适配 | 28 | w0-01 w0-02 w0-03 w0-04 w1-02 w2-01 |
| Wave 2 | [`w2-04-intranet-model-gateway`](w2-04-intranet-model-gateway/) | 行内大模型网关接入 | 4 | w0-02 w0-04 w1-05 w2-01 |
| Wave 3 | [`w3-01-web-security-baseline`](w3-01-web-security-baseline/) | Web 安全基线 | 27 | w0-02 w0-03 w0-04 w1-02 w1-05 w2-01 w2-02 |
| Wave 3 | [`w3-02-audit-baseline`](w3-02-audit-baseline/) | 审计与日志基线 | 34 | w0-01 w0-02 w0-03 w0-04 w1-02 w1-05 w3-01 |
| Wave 3 | [`w3-03-authorization-foundation`](w3-03-authorization-foundation/) | 授权地基与三员分立 | 31 | w0-01 w0-02 w0-03 w0-04 w1-01 w1-02 w1-03 w1-05 w3-02 |
| Wave 3 | [`w3-04-session-and-password`](w3-04-session-and-password/) | 会话与口令 | 33 | w0-01 w0-02 w0-03 w0-04 w1-01 w1-02 w1-04 w2-01 w3-01 w3-02 w3-03 |
| Wave 3 | [`w3-05-credential-encryption`](w3-05-credential-encryption/) | 凭据加密与主密钥 | 20 | w0-01 w0-02 w0-04 w1-01 w1-05 w3-02 w3-04 |
| Wave 3 | [`w3-06-agent-execution-hardening`](w3-06-agent-execution-hardening/) | Agent 执行面收紧 | 9.5 | w0-02 w0-03 w0-04 w0-05 w1-01 w1-02 w1-05 w2-01 |
| Wave 4 | [`w4-01-frontend-baseline`](w4-01-frontend-baseline/) | 前端内网适配 | 13.5 | w0-02 w0-04 w1-03 w1-04 w1-05 w2-01 w3-01 |
| Wave 4 | [`w4-02-ops-minimum`](w4-02-ops-minimum/) | 一期运维最小集 | 10 | w0-02 w0-04 w2-01 w2-02 w2-03 w3-02 w3-05 |

## 二期：按行方优先级取用（11 个，合计约 252 人日）

| 波次 | spec | 标题 | 预估人日 | 前置 |
|---|---|---|---|---|
| 二期 | [`p2-01-agent-sandbox`](p2-01-agent-sandbox/) | Agent 强制沙箱 | 10 | w3-06 |
| 二期 | [`p2-02-kms-sm-crypto`](p2-02-kms-sm-crypto/) | 密钥托管与国密 | 39 | w3-05 w3-04 |
| 二期 | [`p2-03-audit-tamper-proof`](p2-03-audit-tamper-proof/) | 审计防篡改与外发 | 26 | w3-02 w3-03 w0-01 |
| 二期 | [`p2-04-content-security-pii`](p2-04-content-security-pii/) | 内容安全与个人信息脱敏 | 33 | w0-01 w0-04 w1-02 w3-02 w3-03 w3-05 |
| 二期 | [`p2-05-knowledge-retrieval`](p2-05-knowledge-retrieval/) | 知识库检索重写与三级权限 | 35 | w3-03 w2-03 |
| 二期 | [`p2-06-intranet-integration`](p2-06-intranet-integration/) | 行内系统对接 | 34–40 | w0-01 w0-02 w0-04 w0-05 w1-01 w2-01 w2-04 w3-03 w3-05 |
| 二期 | [`p2-07-frontend-controls`](p2-07-frontend-controls/) | 前端管控 | 19 | w1-02 w3-02 w3-04 |
| 二期 | [`p2-08-ha-lease-probes`](p2-08-ha-lease-probes/) | 单活租约与探针 | 18 | w2-03 w0-01 w0-02 |
| 二期 | [`p2-09-ops-observability`](p2-09-ops-observability/) | 可观测与部署清单 | 14 | w4-02 p2-08 w2-03 w3-02 |
| 二期 | [`p2-10-office-skills-rewrite`](p2-10-office-skills-rewrite/) | Office 技能自研替换 | 12–16 | w2-02 |
| 二期 | [`p2-11-identity-adapters`](p2-11-identity-adapters/) | 统一认证适配器 | 7 | w3-04 |

**关于预估**：数字是各 spec 按代码重估的中位值，合计时区间取中点；不含 `w2-03` 自报的约 7 人日风险缓冲；`p2-11` 的 7 人日只含适配器共性框架，行方选定的协议另加 3-12 人日（CAS 3-5、LDAP 4-6、SAML 8-12）。一期有效并行度约 3-4 人，受 `config.py`、`errors.py`、`server.py`、`manager.py`、`deps.py` 等共享热点文件制约，再加约 20% 协调损耗。

## 文档状态

- 起草依据是经过对抗式复核的改造分析（22 个分析单元、1820 条文件级改动），并对照基线代码核实。
- 为节省用量，**没有做逐 spec 的 agent 复核**，改为用脚本对全部 33 个 spec 做机械检查：引用路径是否真实存在、是否违反 steering（上游号段迁移、裸 `pytest`、删 i18n 键）、每条验收标准是否被任务引用，以及跨 spec 冲突（重复新增同一文件、改动前序 spec 已删除的路径、依赖编号在后的 spec、fork 迁移 / ErrorCode / 配置键重复）。检查共发现 7 处问题，均已修正。
- 篇幅不一：`w0-*`、`w1-*`、`w2-01`、`w2-02` 是完整模式起草，每个 60-145KB；其余是精简模式，一期约 40KB、二期约 25KB。二期 spec 只核实了关键锚点，实施前要按一期落地后的代码重新定位。

## 待行方拍板

14 项待拍板事项及其默认假设见 steering 第 4 节（D1-D14）。影响面最大的几项：控制面数据库选型（D3）、是否保留 Agent 命令执行（D6）、国密与密评是否一期强制（D8）、`desktop/` 与 `fnos/` 是否交付（D9）、harness-* 源码能否导入行内（D13）。
