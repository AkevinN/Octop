# 设计文档：一期运维最小集
> spec：`w4-02-ops-minimum` ｜ 波次：Wave 4 ｜ 基线：`757fd12` ｜ 预估：10 人日
> 前置：w0-02-ci-gates, w0-04-fork-isolation-points, w2-01-offline-build, w2-02-supply-chain-compliance, w2-03-database-adaptation, w3-02-audit-baseline, w3-05-credential-encryption ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 概述

本 spec 是"胶水 + 文档"：把前序 spec 的产物（`w2-01` 的镜像、`w2-03` 的 `octop db export-ddl`、`w2-02` 的 `make sign`）按固定目录打成一个离线包，配上目标机的校验与安装脚本、一份运维手册、一份应急预案和一个备份恢复演练脚本。

设计取舍：

1. **不改运行期代码。** `src/octop/` 零改动；`/api/health`、Dockerfile、compose 保持现状。健康探针的 `ready/role` 语义归 `p2-08`，镜像内容归 `w2-01`。
2. **全部新增文件放在 fork 自有目录。** 脚本进 `scripts/intranet/`（沿用 `w2-01`、`w2-02` 的约定），模板进 `deploy/intranet/`，文档进 `docs/intranet/`，测试进 `tests/unit/intranet/`，make 目标进 `Makefile.intranet`。上游同步零冲突。
3. **目标机只依赖 `bash`、`docker`、`sha256sum`、`openssl`。** 目标机不一定有 Python，因此包内校验与安装脚本是纯 shell；`MANIFEST.json` 的结构校验在构建机上由 Python 完成，校验结果通过 `SHA256SUMS` 与签名固化。
4. **冷备靠人工纪律加预检脚本。** 一期没有租约（D5），双跑风险用"冷备容器默认不启动 + `restart` 不用 `always` + 启动前预检主机健康端点"三道人工闸挡住。
5. **文档由契约测试守住。** 手册里的 `octop …` 命令、模板里的 `OCTOP_*` 变量、预案的四段结构都有机器校验，防止上游改名后文档静默过时。

## 现状

- 仓库根下不存在 `deploy/`、`docs/ops/`、`docs/intranet/`、`scripts/intranet/`、`Makefile.intranet`（基线核实）。后三者由前序 spec 建立（`w0-02` 建 `Makefile.intranet`，`w0-04` 建 `docs/intranet/upstream-sync.md`，`w2-01` 建 `scripts/intranet/`）。
- `docs/` 下为 `acp.md`、`agent-*.md`、`api.md`、`architecture.md`、`cli.md`、`configuration.md`、`personas.md`、`user-guide.*`、`versioned-history.md` 与 `adr/`，没有运维类文档。
- 备份 CLI：`src/octop/cli/commands/backup.py` 的 `create`（≈L29，选项 `-o/--output`、`--home`、`--no-config`、`--no-workspaces` 等）与 `restore`（≈L149，参数 `archive`，选项 `--home`、`--no-config`、`--yes`），另有 `auto status`（≈L95）与 `auto run`（≈L116）。
- PG 备份依赖外部工具：`src/octop/infra/backup/pg_dump.py` 的 `_require_tool`（≈L13）、`dump_postgres`（≈L23）、`restore_postgres`（≈L47）；`docker/Dockerfile` 中没有 `postgresql-client`（`rg pg_dump docker/Dockerfile` 零命中）。因此 PG 模式的 `octop backup create` 在基线镜像内无法执行，只能在装有 wheel 与 PG 客户端的运维主机上执行。
- 系统归档：`src/octop/infra/backup/system_archive.py` 的 `create_system_backup`（≈L187）、`restore_system_backup`（≈L419）。`w2-03` 规定 verify-only 模式下应用内恢复抛 `DATABASE_DDL_DISABLED`。
- 自动备份：`src/octop/infra/backup/auto.py` 的 `AUTO_BACKUP_JOB_ID = "octop_auto_backup"`（≈L36）；TLS 续期 system job 在 `src/octop/infra/setup/tls/renewal.py`。两者都是进程内 job，两个实例同时运行会双跑——这是冷备必须"不启动"的原因。
- `docker/Dockerfile`：`HEALTHCHECK`（≈L136）打 `/api/health`；基础镜像在 ≈L36、≈L64。`docker/docker-compose.yml`：`restart: unless-stopped`（≈L29），数据卷 `${OCTOP_DATA:-~/.octop}:/data/.octop`（≈L33）。
- 健康端点：`src/octop/api/routers/health.py` 的 `health`（≈L15），基线恒返回 200。
- CLI 注册表 `src/octop/cli/registry.py` 含 `init`、`run`、`service`、`user`、`agent`、`backup`、`plugin`、`version` 等；`service` 有 `start/stop/restart/status`；根选项 `--json` 在 `src/octop/cli/main.py`（≈L108）；`user list` 走 `list_users_offline`，`--json` 时输出 JSON。
- 日志环境变量 `OCTOP_LOG_COMPRESS`、`OCTOP_LOG_RETENTION_DAYS`、`OCTOP_LOG_MAX_BYTES` 在 `src/octop/infra/server.py`（≈L107、≈L141、≈L151）读取；`OCTOP_DATABASE_URL` 在 `src/octop/config.py`（≈L23）。

## 方案

### 1. 离线包目录结构

```
octop-offline-<version>-<arch>/
  images/octop-<version>-<arch>.tar      docker save 产物
  ddl/                                    octop db export-ddl 的完整输出（含 d_grants.sql 与 MANIFEST.json）
  config/octop.env.example
  config/docker-compose.intranet.yml
  scripts/verify.sh  install.sh  standby_precheck.sh  backup_drill.sh
  docs/ops-runbook.md  emergency-plan.md  （以及 w2-01/w2-03 的 offline-build.md、database.md 副本）
  extra/                                   可选：EXTRA_DIR 指定的离线资产（如 w2-01 打包的 ONNX 模型）
  MANIFEST.json
  SHA256SUMS
  SHA256SUMS.sig
```

每个架构一个包（D4：x86_64 与 arm64）。`ddl/` 与驱动绑定，驱动名由 `DB_DRIVER` 指定（D3：默认假设 PG 家族）。

### 2. 构建流程（构建机，`make offline-bundle`）

1. 参数与工具检查，失败退出码 2，不产生文件。
2. `docker pull --platform linux/<arch> <IMAGE>`（从行内 Harbor）后 `docker save -o images/…tar`；记录 `docker image inspect` 得到的 `image_id`。
3. `uv run octop db export-ddl --out ddl --runtime-role <ROLE> --driver <DRIVER>`（`w2-03` 交付）。
4. 复制 `deploy/intranet/*` 到 `config/`，`scripts/intranet/bundle/*.sh` 与 `backup_drill.sh`、`standby_precheck.sh` 到 `scripts/`，`docs/intranet/` 下手册到 `docs/`，可选 `EXTRA_DIR` 到 `extra/`。
5. `python scripts/intranet/offline_bundle.py manifest --dir <包目录> …` 生成 `MANIFEST.json`，随后 `check-manifest` 校验必需类别。
6. `make sign SIGN_DIR=<包目录> SIGNING_KEY=…`（`w2-02` 交付，生成 `SHA256SUMS` 与 `SHA256SUMS.sig`）；`UNSIGNED=1` 时只调用 `supply_chain.py checksums` 生成 `SHA256SUMS`。
7. `tar -czf dist/offline/octop-offline-<version>-<arch>.tar.gz`，并在包外另写一份 `<包名>.sha256` 供摆渡交接单使用。

### 3. 目标机安装（`scripts/install.sh`）

`verify.sh` → `docker load -i images/*.tar` → 用 env 文件渲染 compose → `docker compose run --rm octop octop db check`（运行账号，`w2-03` 退出码 0/5/1）→ 非 0 则停止并指向手册 → `docker compose up -d` → 轮询容器内 `curl -fsS http://127.0.0.1:8088/api/health`，默认 180 秒超时。脚本只用 `docker load`，不含任何拉取与包管理命令。

### 4. 冷备切换

一期拓扑：主机运行容器；冷备机已 `docker load` 同版本镜像、放好 env 文件与主密钥文件（`w3-05`），容器不启动。控制面库是行方 PG 家族数据库，主备共用同一个库（数据库自身高可用由 DBA 负责）；`OCTOP_HOME` 数据卷（工作区、配置、密钥文件）二选一：共享存储挂载，或由最近一次 `octop backup create --no-config` 归档恢复。切换八步写进手册；第 4 步由 `standby_precheck.sh` 执行。

### 5. 备份恢复演练

`backup_drill.sh` 在隔离的 scratch home 中恢复并比对。PG 模式下 scratch home 的 `OCTOP_DATABASE_URL` 取 `DRILL_DATABASE_URL`（演练专用库，由 DBA 提供并以 DDL 账号预置结构），恢复使用 `--no-config` 以防归档内的生产连接串被带入；两个地址相同时拒绝执行。演练记录写 JSON，供等保"演练记录"留档。

## 组件与接口

| 路径 | 类型 | 内容 |
|---|---|---|
| `scripts/intranet/offline_bundle.py` | 新增 | 仅标准库；子命令 `manifest`、`check-manifest` |
| `scripts/intranet/build_offline_bundle.sh` | 新增 | 构建流程第 1-7 步 |
| `scripts/intranet/bundle/verify.sh` | 新增 | 目标机校验（openssl + `sha256sum -c`） |
| `scripts/intranet/bundle/install.sh` | 新增 | 目标机安装 |
| `scripts/intranet/standby_precheck.sh` | 新增 | 冷备启动前预检 |
| `scripts/intranet/backup_drill.sh` | 新增 | 备份恢复演练 |
| `deploy/intranet/octop.env.example` | 新增 | 一期环境变量模板 |
| `deploy/intranet/docker-compose.intranet.yml` | 新增 | 目标机 compose 模板（`restart: "no"`，显式 `environment:`） |
| `docs/intranet/ops-runbook.md` | 新增 | 运维手册 |
| `docs/intranet/emergency-plan.md` | 新增 | 应急预案 |
| `Makefile.intranet` | 修改 | 新增 `offline-bundle`、`backup-drill` 目标，`help-intranet` 登记 |
| `tests/unit/intranet/test_offline_bundle.py` | 新增 | 清单生成与校验、篡改检测 |
| `tests/unit/intranet/test_ops_scripts.py` | 新增 | 脚本语法、禁用命令扫描、预检与演练参数守卫 |
| `tests/unit/intranet/test_ops_docs.py` | 新增 | 模板变量、手册命令、预案结构、make 目标登记 |
| `CHANGELOG-intranet.md` | 修改 | 本 spec 条目 |

关键签名（`offline_bundle.py`）：

```python
REQUIRED_CATEGORIES: frozenset[str]  # {"image", "ddl", "grants", "config", "script", "doc"}
def build_manifest(bundle_dir: Path, *, octop_version: str, git_commit: str, arch: str,
                   image_ref: str, image_id: str, db_driver: str, db_runtime_role: str,
                   signed: bool) -> dict[str, Any]: ...
def check_manifest(bundle_dir: Path) -> list[str]: ...  # 返回问题列表，空表示通过
def main(argv: list[str] | None = None) -> int: ...     # 0 通过 / 1 校验失败 / 2 参数或输入错误
```

脚本退出码统一：0 成功，1 校验或比对失败，2 参数、前置工具或安全守卫拒绝。

## 数据模型

无。本 spec 不新增表、不写 fork 迁移。`MANIFEST.json` 为包内文件格式，`schema_version` 从 1 起。

## 配置

无。本 spec 不新增 `config.py` 配置键。make 变量（`IMAGE`、`ARCH`、`DB_DRIVER`、`DB_RUNTIME_ROLE`、`SIGNING_KEY`、`UNSIGNED`、`EXTRA_DIR`）与脚本参数只在 `Makefile.intranet` 与脚本内生效。

## 错误处理

无新增 `ErrorCode`。脚本以退出码与中文提示表达错误；安装脚本引用 `w2-03` 的 `octop db check` 退出码（0 一致 / 5 结构过期 / 1 其他错误）。

## 安全考虑

- **完整性与来源：** 目标机先验签再核对摘要，签名失败即停；公钥由行方经独立渠道分发，不随包携带（随包携带的公钥无法证明来源）。
- **私钥：** `SIGNING_KEY` 只在构建机以文件形式提供，脚本不回显、不写入包内。
- **敏感信息不进包：** 模板只含占位符；`octop.env.example` 中所有口令与密钥字段为空值并注释"由部署方填写"；契约测试扫描模板，禁止出现长度 ≥ 16 的非占位值。
- **演练隔离：** 演练恢复使用 `--no-config`，并拒绝源库与演练库地址相同，防止把生产库覆盖。
- **双跑：** compose 模板不用 `restart: always`/`unless-stopped`，冷备启动前必须通过预检；该约束是一期唯一的双跑防线，在手册与预案中显著标注。
- **最小权限：** 运行账号只持 `d_grants.sql` 授予的 DML 权限；DDL 仅在变更窗口由 DBA 账号执行（沿用 `w2-03`）。

## 测试策略

| 类别 | 内容 | 命令 |
|---|---|---|
| 单测（跨平台） | 清单生成、必需类别缺失、篡改与新增文件检测；模板变量在 `src/octop` 中被引用；手册命令存在于 CLI 注册表；预案四段结构；`Makefile.intranet` 目标与 help 登记 | `uv run pytest tests/unit/intranet/test_offline_bundle.py tests/unit/intranet/test_ops_docs.py -q` |
| 单测（`posix_only`） | `bash -n` 全部脚本；安装脚本不含 `docker pull`、`pip `、`uv sync`、`npm `；预检脚本在本地起一个返回 200 的 `http.server` 时退出非 0；演练脚本在同目录、同 DSN 时退出 2；SQLite 模式下 `octop init` → 演练全流程退出 0 | `uv run pytest tests/unit/intranet/test_ops_scripts.py -q` |
| 集成 | 无新增；演练全流程用例放在单测文件里，使用 `tmp_path` 与 `monkeypatch.setenv("OCTOP_HOME", …)` | 同上 |
| PG | 演练脚本的 PG 模式需要两个库与 PG 客户端，不进 CI，在行内演练环境人工执行并留档 | `DRILL_DATABASE_URL=<演练库> OCTOP_DATABASE_URL=<源库> bash scripts/intranet/backup_drill.sh --source-home <源> --scratch-home <临时> --record-dir <记录目录>` |
| 前端 | 无前端改动 | 不适用 |
| 行内环境 | 断网目标机全流程 | `make offline-bundle …`；摆渡后 `bash scripts/verify.sh --pubkey <公钥>`、`bash scripts/install.sh --pubkey <公钥> --env <env>`；构建机上 `bash scripts/intranet/airgap_smoke.sh <标签>`（`w2-01`） |

Windows CI：跑 bash 的用例全部标 `posix_only = pytest.mark.skipif(os.name != "posix", reason="bash scripts")`；读文件类契约测试不限平台，路径用 `Path` 拼接。

## 与其他 spec 的交接

**依赖（消费）：**

| spec | 消费内容 |
|---|---|
| `w0-02` | `Makefile.intranet` 与 `help-intranet` |
| `w0-04` | `CHANGELOG-intranet.md`、`docs/intranet/` 目录、上游同步手册（手册"升级"一节引用） |
| `w2-01` | 行内镜像标签与 `make image`、`scripts/intranet/airgap_smoke.sh`、`docs/intranet/offline-build.md`、ONNX 模型包（经 `EXTRA_DIR`）；手册写入其交接项：升级旧数据卷需 `chown -R 10001:10001`，上游 `docker/README*.md` 与 `docs/agent-backend-file-io.md` 的过时描述以 fork 文档为准 |
| `w2-02` | `make sign`、`make verify-signature`、`scripts/intranet/supply_chain.py checksums` |
| `w2-03` | `octop db export-ddl`、`octop db check`、`octop db migrate`、`docs/intranet/database.md`（首装、升级、连接数预算、verify-only 下恢复需 DDL 账号） |
| `w2-04` | 手册与模板中的行内模型网关环境变量与 CA 挂载要求 |
| `w3-01` | 模板与手册中 `trusted_proxies`、`upload_scan`、`csp_mode` 的生产取值与巡检 |
| `w3-02` | `OCTOP_LOG_STDOUT`、`OCTOP_LOG_FORMAT`、审计保留期与 syslog 外发的运维说明；手册"故障定位"用 request_id 串链路 |
| `w3-05` | 主密钥托管、`octop keys status`、`octop keys rotate-master` 的手册章节；"升级前先备份"的要求 |
| `w3-06` | 容器部署下 `workspace_root_dir` 必须挂载进容器的手册说明 |
| `w1-03`、`w1-04` | 升级 = 换镜像标签 + 重启；插件用 `octop plugin install <目录或 .zip>`；被删一键安装脚本与 README 安装段落由本 spec 手册取代（不改上游文件） |

**交付给：**
- `p2-08`：手册"单活与冷备切换"一节与 `standby_precheck.sh` 是租约上线前的过渡方案；租约合入后改写该节并保留预检作为人工兜底。
- `p2-09`：离线包目录结构与 `MANIFEST.json` 格式；其 K8s 与双机清单、压测脚本可作为 `extra/` 或新类别加入清单。
- `w2-01`：建议镜像加入与目标库兼容的 PG 客户端，使 PG 模式 `octop backup` 能在容器内执行（见待行方确认）。

**看似相关但不归本 spec：** `/metrics`、K8s 清单、压测（`p2-09`）；租约与 `ready/role` 探针、cron 与 TLS 续期 active-only 门控（`p2-08`）；request_id（`w3-02`）；DDL 导出实现与 verify-only（`w2-03`）；运行期 pip 开关与 Dockerfile（`w2-01`）；`w3-06` 登记的"部署锁"等未认领项不并入本 spec（本 spec 不改运行期代码），建议归 `p2-01`。

## 风险与回滚

| 风险 | 影响 | 缓解 |
|---|---|---|
| 冷备误启动导致 cron、自动备份、TLS 续期双跑 | 重复执行任务、重复归档、证书覆盖 | compose 不自启；预检脚本；手册与预案显著标注；`p2-08` 租约为终态 |
| 基线镜像无 PG 客户端 | PG 模式 `octop backup create` 在容器内失败 | 手册规定在运维主机执行；向 `w2-01` 提出镜像补客户端 |
| 前序 spec 的命令或 make 变量改名 | 构建脚本或手册失效 | 手册命令契约测试；任务 1 核实 `make sign` 的 `SIGN_DIR` 可覆盖、`SHA256SUMS` 与 `sha256sum -c` 格式兼容 |
| 包体积（镜像 + 模型数 GB） | 摆渡受单文件上限限制 | 构建脚本支持 `SPLIT_SIZE` 用 `split` 分卷，`verify.sh` 先合并再校验 |
| 主备共用控制面库时，共享卷或备份恢复的工作区与库不同步 | 工作区文件比库新或旧 | 手册要求优先共享存储；用备份恢复时以最近一次完整归档为准并登记 RPO |

**回滚：** 每个顶层任务独立提交，可单独 `git revert`；本 spec 不改运行期代码、不写迁移，回滚不影响已部署实例。

## 待行方确认

- **D3**：驱动名决定 `DB_DRIVER` 与 DDL 版本；若为达梦等第三方言，本 spec 的 DDL 打包随 `w2-03` 另立项调整。
- **D4**：默认出 amd64 与 arm64 两个包；若含龙芯，另需其镜像与 wheel。
- **D5**：一期单活 + 冷备手工切换，RTO 默认按 30 分钟、RPO 按"最近一次备份间隔"写入预案，以行方答复为准。
- 其余不在 steering §4 中的问题：摆渡单文件大小上限与杀毒审查流程；签名公钥的分发渠道；PG 模式备份由行方数据库平台负责还是由 `octop backup` 负责；演练频率（默认每季度一次）。
