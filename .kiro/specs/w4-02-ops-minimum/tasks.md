# 实施计划：一期运维最小集
> spec：`w4-02-ops-minimum` ｜ 波次：Wave 4 ｜ 基线：`757fd12` ｜ 预估：10 人日
> 前置：w0-02-ci-gates, w0-04-fork-isolation-points, w2-01-offline-build, w2-02-supply-chain-compliance, w2-03-database-adaptation, w3-02-audit-baseline, w3-05-credential-encryption ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

每个顶层任务完成后可独立提交；提交前运行任务内的验证命令。

- [ ] 1. 确认前置 spec 已合入并记录基线
  - 改动：无代码改动。核实 `Makefile.intranet` 存在且有 `help-intranet`、`sign`、`verify-signature`、`image`、`airgap-smoke` 目标；`make sign` 的 `SIGN_DIR` 可由命令行覆盖；`scripts/intranet/supply_chain.py checksums` 生成的 `SHA256SUMS` 能被 `sha256sum -c` 直接读取；`octop db export-ddl`、`octop db check`、`octop keys status` 已注册；`CHANGELOG-intranet.md` 与 `docs/intranet/` 存在。结论记入本 spec 的提交说明，发现不符先回到对应前置 spec。
  - 验证：`rg -n '^(help-intranet|sign|verify-signature|image|airgap-smoke):' Makefile.intranet && uv run octop db --help && uv run octop keys --help && uv run octop backup --help && test -f CHANGELOG-intranet.md && test -d docs/intranet`
  - _需求：1.4, 9.2_

- [ ] 2. 清单工具 `offline_bundle.py`（测试先行）
  - [ ] 2.1 先写失败用例
    - 改动：新增 `tests/unit/intranet/__init__.py` 与 `tests/unit/intranet/test_offline_bundle.py`：用 `tmp_path` 造一个包目录，断言 `build_manifest` 的必需字段与 `files` 条目（路径用 `Path.as_posix()` 序列化）；删除 `ddl/` 后 `check_manifest` 报缺 `ddl` 类别；修改任一文件或新增未登记文件后 `main(["check-manifest", …])` 返回 1；缺参数返回 2。用 `importlib.util.spec_from_file_location` 加载脚本。
    - 验证：`uv run pytest tests/unit/intranet/test_offline_bundle.py -q`（此时应失败）
    - _需求：2.1, 2.3, 2.4_
  - [ ] 2.2 实现
    - 改动：新增 `scripts/intranet/offline_bundle.py`（仅标准库）：`REQUIRED_CATEGORIES`、`build_manifest`、`check_manifest`、`main`；类别按顶层目录与 `ddl/d_grants.sql` 推断；`check-manifest` 同时比对磁盘文件集合与清单，排除 `SHA256SUMS`、`SHA256SUMS.sig` 自身。
    - 验证：`uv run pytest tests/unit/intranet/test_offline_bundle.py -q`
    - _需求：2.1, 2.3, 2.4_

- [ ] 3. 配置模板
  - 改动：新增 `deploy/intranet/octop.env.example`（一期全部 `OCTOP_*` 变量，含 `OCTOP_DATABASE_URL`、日志三变量、`w2-03`/`w2-04`/`w3-01`/`w3-02`/`w3-05` 交接的变量，每个一行中文注释：用途、默认值、归属 spec；口令与密钥字段留空）与 `deploy/intranet/docker-compose.intranet.yml`（`image` 用 `${OCTOP_IMAGE}` 插值，`restart: "no"`，全部变量显式列在 `environment:` 下，数据卷与主密钥文件、CA 证书、`workspace_root_dir` 挂载点注释说明）。新增 `tests/unit/intranet/test_ops_docs.py` 的模板用例：模板中每个 `OCTOP_*` 在 `src/octop` 下至少被引用一次（Python 遍历 `*.py` 文本搜索）；compose 不含 `restart: always`/`unless-stopped`；`environment:` 覆盖 env 模板中的全部变量；模板中无长度 ≥ 16 的非占位值。先写用例再写模板。
  - 验证：`uv run pytest tests/unit/intranet/test_ops_docs.py -q -k template`
  - _需求：4.1, 4.2, 4.3_

- [ ] 4. 目标机校验脚本 `verify.sh`
  - 改动：新增 `scripts/intranet/bundle/verify.sh`：`--pubkey` 必填（缺失退出 2）；若存在分卷先 `cat` 合并；`openssl dgst -sha256 -verify <公钥> -signature SHA256SUMS.sig SHA256SUMS`；`sha256sum -c --strict SHA256SUMS`；再用 `find` 比对磁盘文件集合与 `SHA256SUMS` 条目，发现未登记文件退出 1 并打印路径。`MANIFEST.json` 未签名（`"signed": false`）时要求显式 `--allow-unsigned`。在 `tests/unit/intranet/test_ops_scripts.py`（`posix_only`）加用例：用 openssl 临时生成 EC P-256 密钥对签一个假包，完好时退出 0，改一个字节、删一个文件、加一个文件各退出 1，缺 `--pubkey` 退出 2。
  - 验证：`uv run pytest tests/unit/intranet/test_ops_scripts.py -q -k verify`
  - _需求：2.2, 2.3_

- [ ] 5. 构建脚本与 `make offline-bundle`
  - [ ] 5.1 参数守卫与目录装配（测试先行）
    - 改动：在 `test_ops_scripts.py` 加用例：缺 `IMAGE`/`ARCH`/`DB_DRIVER`/`DB_RUNTIME_ROLE` 任一时 `build_offline_bundle.sh` 退出 2 且输出目录不存在；未给 `SIGNING_KEY` 且未设 `UNSIGNED=1` 时退出 2。新增 `scripts/intranet/build_offline_bundle.sh`：参数与工具检查（`docker`、`uv`、`openssl`）；`docker pull --platform linux/<arch>` + `docker save` + `docker image inspect` 取 `image_id`；`uv run octop db export-ddl --out <包>/ddl --runtime-role … --driver …`；复制模板、脚本、`docs/intranet/{ops-runbook,emergency-plan,offline-build,database}.md`、可选 `EXTRA_DIR`；调用 `offline_bundle.py manifest` 与 `check-manifest`。
    - 验证：`uv run pytest tests/unit/intranet/test_ops_scripts.py -q -k build`
    - _需求：1.1, 1.3, 1.4_
  - [ ] 5.2 签名、打包与分卷
    - 改动：`build_offline_bundle.sh` 调用 `make sign SIGN_DIR=<包> SIGNING_KEY=…`；`UNSIGNED=1` 时改调 `supply_chain.py checksums` 并在清单写 `signed: false`；`tar -czf` 输出到 `dist/offline/`，包外写 `<包名>.sha256`；`SPLIT_SIZE` 非空时用 `split -b` 分卷。`Makefile.intranet` 新增 `offline-bundle` 目标（转发变量）并在 `help-intranet` 登记。`test_ops_docs.py` 加用例断言 `offline-bundle` 目标与 help 行存在。
    - 验证：`uv run pytest tests/unit/intranet/test_ops_docs.py -q -k makefile && make -n offline-bundle IMAGE=x ARCH=amd64 DB_DRIVER=postgresql DB_RUNTIME_ROLE=octop_app UNSIGNED=1`
    - 验证（行内构建机）：`make offline-bundle IMAGE=<Harbor 标签> ARCH=amd64 DB_DRIVER=<驱动> DB_RUNTIME_ROLE=<角色> SIGNING_KEY=<私钥文件>`，再对产物执行 `make verify-signature SIGN_DIR=<解包目录> SIGNING_PUBKEY=<公钥>`
    - _需求：1.1, 1.2, 2.1_

- [ ] 6. 目标机安装脚本 `install.sh`
  - 改动：新增 `scripts/intranet/bundle/install.sh`：`--pubkey`、`--env` 必填；先调 `verify.sh`，失败即停；`docker load -i images/*.tar`；用 env 文件与 `config/docker-compose.intranet.yml` 生成部署目录；`docker compose run --rm octop octop db check`，非 0 时不启动并打印"见 docs/ops-runbook.md 安装 §DBA 执行 DDL"；`docker compose up -d`；轮询容器内健康端点（默认 180 秒，`--timeout` 可调）。`test_ops_scripts.py` 加用例：脚本文本不含 `docker pull`、`pip `、`uv sync`、`npm `，`curl` 仅出现在 `127.0.0.1` 或 `localhost` 目标上；用 PATH 前置的假 `docker` 桩（`tests.support.fakes.fake_bin_path` 风格）断言校验失败时 `docker load` 未被调用、`db check` 返回 5 时 `up` 未被调用。
  - 验证：`uv run pytest tests/unit/intranet/test_ops_scripts.py -q -k install`
  - 验证（行内断网目标机）：`bash scripts/verify.sh --pubkey <公钥> && bash scripts/install.sh --pubkey <公钥> --env <env 文件>`，同时 `tcpdump -n 'not host 127.0.0.1 and not net <行内网段>'` 零外联
  - _需求：3.1, 3.2, 3.3, 3.4_

- [ ] 7. 冷备预检脚本 `standby_precheck.sh`
  - 改动：新增 `scripts/intranet/standby_precheck.sh`：`--primary-url` 必填；`curl -fsS --max-time 5 <url>/api/health` 成功则退出 1 并打印"主机仍在服务，禁止启动冷备"；不可达时要求输入主机名二次确认（`--confirm <主机名>` 供非交互使用），不一致退出 1，一致退出 0；另检查本机 `docker ps` 中无 Octop 容器。`test_ops_scripts.py` 加用例：本地起 `python -m http.server` 返回 200 的桩 → 退出 1；指向未监听端口并带正确 `--confirm` → 退出 0；带错误 `--confirm` → 退出 1。
  - 验证：`uv run pytest tests/unit/intranet/test_ops_scripts.py -q -k precheck`
  - _需求：6.1, 6.2_

- [ ] 8. 备份恢复演练脚本
  - [ ] 8.1 安全守卫（测试先行）
    - 改动：`test_ops_scripts.py` 加用例：`--source-home` 与 `--scratch-home` 相同、或 `DRILL_DATABASE_URL` 等于 `OCTOP_DATABASE_URL` 时，`backup_drill.sh` 退出 2 且 scratch 目录未被写入。新增 `scripts/intranet/backup_drill.sh` 的参数解析与守卫。
    - 验证：`uv run pytest tests/unit/intranet/test_ops_scripts.py -q -k drill_guard`
    - _需求：8.3_
  - [ ] 8.2 演练流程与记录
    - 改动：`backup_drill.sh` 依次执行 `OCTOP_HOME=<源> octop backup create -o <归档>`、`OCTOP_HOME=<scratch> [OCTOP_DATABASE_URL=$DRILL_DATABASE_URL] octop backup restore <归档> --no-config --yes`、两侧 `octop --json user list` 与 `octop --json agent list` 并 `diff`；结束时（`trap EXIT`）在 `--record-dir` 写 JSON 记录（起止时间、归档路径与 sha256、各步耗时、比对结果、退出码）。`Makefile.intranet` 新增 `backup-drill` 目标并登记 help。`test_ops_scripts.py` 加 SQLite 全流程用例：`monkeypatch.setenv("OCTOP_HOME", …)`，`uv run octop init` 建源实例并建一个用户，演练退出 0 且记录文件字段齐全；在 scratch 中篡改后重跑比对步骤退出 1。
    - 验证：`uv run pytest tests/unit/intranet/test_ops_scripts.py -q -k drill && uv run pytest tests/unit/intranet/test_ops_docs.py -q -k makefile`
    - 验证（行内演练环境，PG）：`DRILL_DATABASE_URL=<演练库> OCTOP_DATABASE_URL=<源库> bash scripts/intranet/backup_drill.sh --source-home <源> --scratch-home <临时> --record-dir <记录目录>`
    - _需求：8.1, 8.2, 8.4, 9.2_

- [ ] 9. 运维手册：安装、升级、回滚、备份恢复
  - 改动：新增 `docs/intranet/ops-runbook.md` 的前四节。安装：摆渡交接、验签、DBA 执行 `ddl/` 与 `d_grants.sql`（引用 `docs/intranet/database.md`）、`install.sh`、首次管理员与三员账号、`chown -R 10001:10001` 旧卷说明。升级：`octop backup create` → 确认主密钥另行托管 → 停容器 → DBA 执行新版 DDL 或以 DDL 账号 `octop db migrate` 并重跑授权 → `docker load` 新镜像、改标签 → 启动 → `octop db check` 与健康检查。回滚：旧镜像 + 升级前备份（fork 与上游迁移只进不退）。备份与恢复：文件归档用 `octop backup create/restore`，PG 模式需运维主机有 `pg_dump`/`pg_restore`，verify-only 下恢复需 DDL 账号，`octop backup auto status`。新增 `test_ops_docs.py` 的手册命令用例：抽取反引号内 `octop <组> <子命令>`，按 `src/octop/cli/registry.py` 的组名与各命令组的 click 子命令名校验存在（加载 click 组对象的 `commands`）。
  - 验证：`uv run pytest tests/unit/intranet/test_ops_docs.py -q -k runbook`
  - _需求：5.1, 5.2, 5.3_

- [ ] 10. 运维手册：主密钥、日志审计、冷备切换、配置速查
  - 改动：补齐 `docs/intranet/ops-runbook.md` 后四节。主密钥托管：`octop keys status`、`octop keys rotate-master --new-key-file`、与备份分开保管（`w3-05`）。日志与审计：日志目录与 `OCTOP_LOG_*`、`w3-02` 的 stdout/JSON 日志、审计保留期与 syslog、用 request_id 串链路。单活与冷备切换：八步（隔离、数据就位、主密钥就位、`standby_precheck.sh`、启动、验证、流量切换、回切）与"冷备机 `docker ps` 无 Octop 容器"的日常核对命令，显著标注双跑后果（cron、自动备份 `octop_auto_backup`、TLS 续期）。配置速查：指向 `config/octop.env.example`，列出 `w3-01` 的 `trusted_proxies`、`upload_scan`、`csp_mode` 与 `w3-06` 的 `workspace_root_dir` 挂载要求；列出已知过时的上游文档段落（`docker/README*.md` 构建参数、`docs/agent-backend-file-io.md` 自动安装 bubblewrap、README 一键安装）。`test_ops_docs.py` 加用例断言八节标题齐全、切换一节含八个步骤关键字。
  - 验证：`uv run pytest tests/unit/intranet/test_ops_docs.py -q -k runbook`
  - _需求：5.1, 5.4, 6.3, 6.4_

- [ ] 11. 应急预案
  - 改动：新增 `docs/intranet/emergency-plan.md`：总则（分级、联系人占位、RTO 默认 30 分钟与 RPO 为备份间隔，标注以行方答复为准）；八个场景（主机故障、控制面数据库不可用、磁盘满、大模型网关不可用、证书过期、主密钥丢失或泄露、误删数据恢复、疑似入侵），每个场景含"判定""处置""回退""验证"四小节，处置步骤引用手册与脚本；演练记录归档要求（`backup_drill.sh` 的 JSON 记录）。`test_ops_docs.py` 加用例：八个场景标题存在，每个场景下四个小节齐全，RTO/RPO 段存在。
  - 验证：`uv run pytest tests/unit/intranet/test_ops_docs.py -q -k emergency`
  - _需求：7.1, 7.2, 7.3_

- [ ] 12. 断网全流程实测（行内环境）
  - 改动：无代码改动。amd64 与 arm64 各出一个包；摆渡到断网目标机执行校验、安装、`backup_drill.sh`、一次冷备切换与回切演练；实测数字（包体积、安装耗时、切换耗时）与演练记录写入 `docs/intranet/ops-runbook.md` 附录与 `emergency-plan.md` 的演练记录表。发现的缺件回到任务 5 补清单类别。
  - 验证（行内环境）：`bash scripts/verify.sh --pubkey <公钥> && bash scripts/install.sh --pubkey <公钥> --env <env 文件>`；`bash scripts/standby_precheck.sh --primary-url <主机地址>`；`bash scripts/intranet/backup_drill.sh …`；本机：`uv run pytest tests/unit/intranet -q`
  - _需求：1.1, 3.1, 3.4, 6.4, 8.4_

- [ ] 13. 收尾
  - 改动：`CHANGELOG-intranet.md` 追加本 spec 条目（新增 make 目标 `offline-bundle`、`backup-drill`，脚本、模板与两份文档）；本 spec 无 API 变更，`docs/api-intranet.md` 不改；无前端改动；删除本 spec 引入的孤儿符号。
  - 验证：`make all && uv run pytest tests/unit/intranet -q && rg -n 'w4-02' CHANGELOG-intranet.md`
  - _需求：9.1, 9.3_
