# 需求文档：一期运维最小集
> spec：`w4-02-ops-minimum` ｜ 波次：Wave 4 ｜ 基线：`757fd12` ｜ 预估：10 人日
> 前置：w0-02-ci-gates, w0-04-fork-isolation-points, w2-01-offline-build, w2-02-supply-chain-compliance, w2-03-database-adaptation, w3-02-audit-baseline, w3-05-credential-encryption ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 引言

**结论：** 本 spec 不改任何运行期代码，只交付"把已经能在内网跑起来的 Octop 装上去、升上去、备份恢复得回来、主机坏了能手工切到冷备"所需的四样东西：离线安装包、运维手册、应急预案、备份恢复演练脚本。全部新增文件都是 fork 自有文件（`scripts/intranet/`、`deploy/intranet/`、`docs/intranet/`、`tests/unit/intranet/`），与上游零冲突。

**背景：** Wave 0-3 之后，镜像能在行内私服构建（`w2-01`），制品能签名（`w2-02`），DDL 能导出交给 DBA（`w2-03`），日志与审计、主密钥各有落点（`w3-02`、`w3-05`）。但这些产物散落在各 spec 的 make 目标里，没有一个能用 U 盘摆渡、在断网目标机上一次装成的包；基线 `docs/` 下 14 个文档全面向开发者与终端用户，没有运维手册与应急预案；`w1-04` 删除了公网一键安装脚本，安装说明出现空白。等保三级要求有应急预案与演练记录。

**范围内：**
- 离线安装包：镜像 tar、`w2-03` 导出的 DDL 与授权脚本、配置模板、`MANIFEST.json`、`SHA256SUMS` 与 `w2-02` 的分离签名；包内附安装与校验脚本。
- 运维手册：安装、升级、备份恢复、主密钥托管、单活加冷备的手工切换步骤。
- 应急预案：一期可处置的故障场景，每个场景含判定、处置、回退、验证。
- 备份恢复演练脚本与演练记录格式。

**范围外：**
- Prometheus `/metrics`、K8s 与双机清单、压测基线、66 处 `app_runtime` 断言梳理 —— 归 `p2-09-ops-observability`。
- PG 租约、standby 被动模式、`/api/health` 的 `ready/role` 字段、cron/自动备份/TLS 续期的 active-only 门控 —— 归 `p2-08-ha-lease-probes`。一期冷备靠"同一时刻只启动一个实例"的人工纪律保证。
- request_id 贯穿与审计字段 —— 归 `w3-02-audit-baseline`。
- DDL 导出工具链、verify-only 迁移模式 —— 归 `w2-03-database-adaptation`；本 spec 只调用 `octop db export-ddl` 并打包其产物。
- 运行期下载关闭、镜像构建、Dockerfile 与 compose 改动、ONNX 模型打包 —— 归 `w2-01-offline-build`。
- 校验和与签名的实现（`make sign`、`make verify-signature`、`supply_chain.py checksums`）—— 归 `w2-02-supply-chain-compliance`。
- 上游 `README*`、`docs/cli.md`、`docs/user-guide.md` 的安装段落不改写（全局约束 §5：fork 内容不写进上游文档），由 `docs/intranet/ops-runbook.md` 取代。

## 需求

### 需求 1：离线安装包构建
**用户故事：** 作为发布工程师，我希望在行内构建机上用一条命令产出单个离线安装包，以便经 U 盘或内网文件服务器摆渡到断网目标机。

#### 验收标准
1. 当执行 `make offline-bundle IMAGE=<标签> ARCH=<amd64|arm64> DB_DRIVER=<驱动> DB_RUNTIME_ROLE=<角色>` 时，构建脚本应当产出 `dist/offline/octop-offline-<版本>-<架构>.tar.gz`，解包后的顶层目录含 `images/`、`ddl/`、`config/`、`scripts/`、`docs/`、`MANIFEST.json`、`SHA256SUMS`。
2. 当提供 `SIGNING_KEY` 时，构建脚本应当调用 `w2-02` 的 `make sign` 在包目录内生成 `SHA256SUMS.sig`；如果未提供 `SIGNING_KEY`，那么脚本应当以非零退出码终止并提示，除非显式传入 `UNSIGNED=1`（仅限测试环境），此时 `MANIFEST.json` 的 `signed` 字段为 `false`。
3. 如果 `IMAGE`、`ARCH`、`DB_DRIVER`、`DB_RUNTIME_ROLE` 任一缺失，或 `docker`、`uv`、`openssl` 任一不在 PATH 上，那么构建脚本应当在产生任何输出文件之前以退出码 2 终止。
4. 构建脚本应当始终只调用前序 spec 已交付的命令（`docker save`、`octop db export-ddl`、`make sign`），不重复实现镜像构建、DDL 生成与签名逻辑。

### 需求 2：清单与完整性校验
**用户故事：** 作为行内运维，我希望在摆渡前后都能独立核对安装包没有被篡改或缺件，以便留存可审计的完整性证据。

#### 验收标准
1. 当构建完成时，`MANIFEST.json` 应当包含 `schema_version`、`octop_version`、`git_commit`、`arch`、`image_ref`、`image_id`、`db_driver`、`db_runtime_role`、`signed`、`built_at`，以及 `files` 列表（每项含相对路径、字节数、sha256、类别）。
2. 当在目标机执行 `bash scripts/verify.sh --pubkey <公钥>` 时，校验脚本应当先用 openssl 验证 `SHA256SUMS.sig`，再逐项核对 `SHA256SUMS`，全部一致时退出码为 0。
3. 如果包内任意一个文件被修改、删除或新增了未登记文件，那么校验脚本应当以非零退出码终止并打印不一致的路径。
4. 如果 `MANIFEST.json` 缺少 1.1 列出的任一必需类别（镜像、DDL、授权脚本、配置模板、脚本、手册），那么 `offline_bundle.py check-manifest` 应当以非零退出码终止。

### 需求 3：目标机离线安装
**用户故事：** 作为行内运维，我希望在断网目标机上按固定步骤一次装成，以便安装过程可复现、可审计。

#### 验收标准
1. 当执行 `bash scripts/install.sh --pubkey <公钥> --env <env 文件>` 时，安装脚本应当依次执行：完整性校验、`docker load`、按模板生成 compose 文件、`octop db check` 确认 DBA 已执行 DDL、启动容器、轮询 `/api/health` 直到返回 200 或超时。
2. 如果完整性校验失败，那么安装脚本应当在执行 `docker load` 之前以非零退出码终止。
3. 如果 `octop db check` 返回非 0（DDL 未执行或版本不符），那么安装脚本应当不启动容器，并打印 `docs/intranet/ops-runbook.md` 中"DBA 执行 DDL"一节的位置。
4. 安装脚本应当始终不发起任何外网请求：脚本内不出现 `docker pull`、`pip`、`uv sync`、`npm`、`curl` 访问非回环地址的调用。

### 需求 4：配置模板
**用户故事：** 作为行内运维，我希望拿到一份列全了一期所需环境变量的模板，以便不依赖开发人员就能完成部署配置。

#### 验收标准
1. 当构建安装包时，`config/` 应当包含 `octop.env.example` 与 `docker-compose.intranet.yml`，模板中的每个 `OCTOP_*` 变量都带一行中文注释说明用途、默认值与归属 spec。
2. 如果模板中出现的某个 `OCTOP_*` 变量在 `src/octop` 源码中没有任何引用，那么契约测试应当失败。
3. `docker-compose.intranet.yml` 应当始终把所有容器内需要的变量显式列在 `environment:` 下（compose 的 `.env` 只做插值、不注入容器），且 `restart` 策略写为 `"no"` 或 `on-failure`，不使用 `always`（避免冷备机意外自启）。

### 需求 5：运维手册
**用户故事：** 作为行内运维，我希望有一份覆盖安装、升级、备份恢复、主密钥托管的中文手册，以便按手册而不是按源码操作。

#### 验收标准
1. 当运维查阅 `docs/intranet/ops-runbook.md` 时，手册应当包含"安装""升级""回滚""备份与恢复""主密钥托管""日志与审计""单活与冷备切换""配置项速查"八节。
2. 如果手册中出现形如 `octop <命令组> <子命令>` 的命令，那么契约测试应当确认该命令在 CLI 注册表中真实存在，不存在即失败。
3. 在升级流程描述中，手册应当要求"升级前先执行一次 `octop backup create` 并确认主密钥已另行托管"，并写明回滚方式是"旧镜像 + 升级前备份"。
4. 手册应当始终以 fork 文档（`docs/intranet/*.md`）为准，并列出已知过时的上游文档段落。

### 需求 6：单活加冷备手工切换
**用户故事：** 作为行内运维，我希望在主机故障时按步骤把服务切到冷备机，并有脚本防止两台同时运行，以便避免 cron、自动备份、TLS 续期双跑。

#### 验收标准
1. 当执行 `bash scripts/standby_precheck.sh --primary-url <主机地址>` 且主机 `/api/health` 仍返回 200 时，预检脚本应当以非零退出码终止并提示"主机仍在服务，禁止启动冷备"。
2. 当主机健康端点不可达时，预检脚本应当要求操作员输入主机名二次确认，确认后退出码为 0。
3. 在冷备机待命期间，冷备机上的 Octop 容器应当处于未启动状态（`docker ps` 中不存在），手册中写明核对命令。
4. 手册的切换一节应当始终包含：主机隔离（停容器、禁用自启）、数据就位（共享卷或最近备份恢复）、主密钥就位、预检、启动、验证、流量切换、回切八个步骤。

### 需求 7：应急预案
**用户故事：** 作为安全与运维负责人，我希望有覆盖一期常见故障的应急预案，以便满足等保对应急预案的要求并能照着处置。

#### 验收标准
1. 当查阅 `docs/intranet/emergency-plan.md` 时，预案应当至少覆盖：主机故障、控制面数据库不可用、磁盘满、大模型网关不可用、证书过期、主密钥丢失或泄露、误删数据恢复、疑似入侵八个场景。
2. 预案中的每个场景应当始终包含"判定""处置""回退""验证"四个小节，契约测试校验结构齐全。
3. 预案应当始终写明 RTO/RPO 的默认目标与其取值依据（一期冷备手工切换），并标注以行方答复为准。

### 需求 8：备份恢复演练
**用户故事：** 作为行内运维，我希望有一个可重复执行的演练脚本，以便定期证明备份真的恢复得回来并留下演练记录。

#### 验收标准
1. 当执行 `bash scripts/intranet/backup_drill.sh --source-home <目录> --scratch-home <目录>` 时，演练脚本应当依次执行 `octop backup create`、在隔离目录执行 `octop backup restore --no-config --yes`、比对两侧 `octop --json user list` 与 `octop --json agent list` 的输出，一致时退出码为 0。
2. 如果恢复后两侧的用户或 Agent 清单不一致，那么演练脚本应当以非零退出码终止并输出差异。
3. 如果演练目标数据库地址（`DRILL_DATABASE_URL`）与源实例的 `OCTOP_DATABASE_URL` 相同，或 `--scratch-home` 与 `--source-home` 指向同一目录，那么演练脚本应当在执行任何恢复动作之前以退出码 2 终止。
4. 当演练结束（无论成败）时，演练脚本应当在 `--record-dir` 下写一份 JSON 演练记录，含开始与结束时间、归档路径与 sha256、各步骤耗时、比对结果、退出码。

### 需求 9：交付登记与门禁
**用户故事：** 作为 fork 维护者，我希望本 spec 的脚本与文档受 `make all` 与契约测试保护，以便后续上游同步或前序 spec 改名时第一时间发现漂移。

#### 验收标准
1. 当运行 `uv run pytest tests/unit/intranet -q` 时，本 spec 新增的清单、脚本语法、模板变量、手册命令、预案结构五组契约测试应当全部通过。
2. 如果 `Makefile.intranet` 中缺少 `offline-bundle` 或 `backup-drill` 目标，或 `help-intranet` 未登记它们，那么契约测试应当失败。
3. 本 spec 合入时，`CHANGELOG-intranet.md` 应当始终有一条本 spec 条目，列出新增的 make 目标、脚本与文档。
