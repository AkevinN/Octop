# 实施计划：离线构建与依赖收敛

> spec：`w2-01-offline-build` ｜ 波次：Wave 2 ｜ 基线：`757fd12` ｜ 预估：20 人日
> 前置：`w0-01-fork-migration-namespace`、`w0-02-ci-gates`、`w0-03-test-auth-baseline`、`w0-04-fork-isolation-points`、`w1-02-capability-trim`、`w1-03-online-fetch-trim`、`w1-04-content-trim`、`w1-05-saas-decoupling` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

每个顶层任务完成后可独立提交；提交前运行任务内的验证命令。

说明：标注"行内环境"的验证命令只能在能访问行内 Harbor、PyPI 私服、npm 私服与行内 Git 的机器上执行；其余命令在任意检出上都可执行。任务 11 之后，锁文件契约用例只在行内提交的锁上为绿，这是预期（fork 仓库只存在于行内）。

- [ ] 1. 确认前置 spec 已合入并记录基线（0.25 人日）
  - 改动：新增 `docs/intranet/offline-build.md`，先只写"§0 基线"：`757fd12` 上的实测数字（`files.pythonhosted.org` 2715、`pypi.org/simple` 241、`registry.npmjs.org` 1125、锁中 242 个包、运行时闭包 203、带两个镜像 extra 223），以及本 spec 开工时用同样命令复测的数字。
  - 改动：用设计文档附录 A 的黑名单试扫一次（可临时用 `rg`），把前序合入后的实际命中与设计文档"公网域名在仓库中的分布"一表对照；表外命中按归属处理（本 spec 负责的记入对应任务；属于前序 spec 的在 PR 中回报其 owner，并在任务 2 中按设计文档附录 B 的规则登记或修复）；修正附录 B 的初始登记。
  - 改动：记录两项条件分支的判定结果：`src/octop/infra/connectors/gateway/cli_install.py` 是否仍存在；`lark-oapi`、`edge-tts` 是否仍在 `pyproject.toml` 且 `src/` 中是否仍有导入。
  - 验证：`test -f Makefile.intranet && rg -n '^(relock|install-frontend|check-frontend|test-postgresql):' Makefile.intranet`
  - 验证：`test -f CHANGELOG-intranet.md && test -f docs/api-intranet.md && test -d src/octop/i18n/intranet && test -d dashboard/src/locales/intranet`
  - 验证：`test ! -e desktop && test ! -e fnos && test ! -e scripts/install.sh && test ! -e .github/workflows/docker-publish.yml && test ! -e src/octop/infra/setup/self_update.py && test ! -e src/octop/infra/agents/providers/onnx_download.py && test ! -e src/octop/infra/agents/providers/opencode_session.py && test -f src/octop/infra/agents/harness_removed_tools.py`
  - 验证：`! rg -n '"(playwright|acme|josepy)' pyproject.toml && ! rg -n 'extra browser|PLAYWRIGHT_BROWSERS_PATH' docker/Dockerfile`
  - 验证：`grep -c files.pythonhosted.org uv.lock; grep -c registry.npmjs.org dashboard/package-lock.json; uv export --frozen --no-dev --no-hashes --no-emit-project | grep -c '=='; uv export --frozen --no-dev --no-hashes --no-emit-project --extra local-embedding --extra knowledge-ocr | grep -c '=='`
  - 验证：`test -e src/octop/infra/connectors/gateway/cli_install.py && echo CLI_INSTALL_PRESENT || echo CLI_INSTALL_ABSENT; rg -n "import lark_oapi|from lark_oapi|import edge_tts|from edge_tts" src || echo NO_IMPORTS`
  - _需求：16.3_

- [ ] 2. 源码出网静态门禁（1 人日）
  - [ ] 2.1 先写会失败的用例
    - 改动：新增 `tests/unit/test_no_public_endpoints.py`，以 `importlib.util.spec_from_file_location` 加载 `scripts/intranet/public_hosts.py`。用例：(a) 在 `tmp_path` 下放探针文件，断言 `https://huggingface.co/x`、`api.skills.sh` 命中而 `install_skills.sh`、`myskills.shop` 不命中；(b) locale JSON 中的命中只在键路径登记时放行；(c) 构造一条找不到命中的白名单登记，断言报"陈旧登记"；(d) 每条 `CODE_ALLOWLIST` 登记都有非空的归属 spec 与理由；(e) 真实仓库上 `scan_sources(repo_root)` 返回空列表；(f) 黑名单包含 `opencode.ai`。
    - 验证：`uv run pytest tests/unit/test_no_public_endpoints.py -q`（此时应失败：脚本不存在）
    - _需求：1.1, 1.2, 1.3_
  - [ ] 2.2 实现脚本并登记白名单
    - 改动：新增 `scripts/intranet/public_hosts.py`：`DENYLIST`（附录 A 三组）、`LOCALE_ALLOWLIST`、`CODE_ALLOWLIST`、`PENDING_FIXES`（附录 B，经任务 1 修正）、`scan_sources(repo_root: Path) -> list[Violation]`、`main(argv) -> int`（子命令 `sources`）。扫描范围与匹配规则按设计文档方案第 1 条。
    - 改动：`Makefile.intranet` 新增 `check-public-hosts` 目标（执行 `$(PYTHON) scripts/intranet/public_hosts.py sources`），`help-intranet` 增加一行。
    - 验证：`uv run pytest tests/unit/test_no_public_endpoints.py -q && make check-public-hosts`
    - _需求：1.1, 1.2, 1.3, 1.6_

- [ ] 3. 运行期不安装任何软件包（1 人日）
  - [ ] 3.1 先写会失败的用例
    - 改动：`tests/unit/utils/test_runtime_packages.py`：把 `test_install_packages_uses_uv_then_pip`、`test_install_packages_bootstraps_pip_on_missing_module`、`test_install_packages_extra_fallback` 三个"会安装"的用例改写为：未满足时抛 `RuntimeInstallDisabledError`，且被替换为"调用即失败"桩的 `subprocess.run` 从未被调用；保留 `test_install_packages_noop_when_satisfied` 与纯函数用例。
    - 改动：`tests/unit/backend/test_opensandbox_deps.py::test_ensure_opensandbox_deps_installs` 改为断言在 SDK 不可导入时抛 `RuntimeError` 且不建子进程。
    - 改动：新增 `tests/unit/api/test_knowledge_error_mapping_intranet.py`：`_map_knowledge_error(RuntimeInstallDisabledError(<实际消息>), locale="zh")` 的 `code` 为 `KNOWLEDGE_PREREQUISITES_FAILED`；设 `OCTOP_ALLOW_RUNTIME_PIP=1` 后在 `fastembed` 不可导入（monkeypatch `local_embedding_deps_available` 为假）时 `ensure_local_embedding_deps()` 抛 `RuntimeInstallDisabledError`。
    - 改动：新增 `tests/unit/test_plugins_no_runtime_deps.py`：monkeypatch `octop.infra.agents.plugins.manager.load_plugin_dir` 记录 `install_deps`，断言 `PluginManager.load_installed()`（默认参数）与 `install_path()` 都传 `False`；再以 `octop_client` 启动服务并调用 `POST /api/plugins/reload`，断言记录中没有 `True`。
    - 验证：`uv run pytest tests/unit/utils/test_runtime_packages.py tests/unit/backend/test_opensandbox_deps.py tests/unit/api/test_knowledge_error_mapping_intranet.py tests/unit/test_plugins_no_runtime_deps.py -q`（此时应失败）
    - _需求：2.1, 2.2, 2.3, 2.4, 2.5_
  - [ ] 3.2 实现
    - 改动：`src/octop/infra/utils/runtime_packages.py` 新增 `RuntimeInstallDisabledError(RuntimeError)`；`install_packages` 在"已满足即 `ready`"之后直接抛出，消息按设计文档方案第 2 条（不含 `disabled`）；其余内部函数不删。
    - 改动：`src/octop/infra/server.py` ≈L310、`src/octop/api/routers/plugins.py` ≈L116、`src/octop/infra/agents/plugins/manager.py` ≈L445 的 `install_deps=True` 改为 `False`；`PluginManager.load_installed` 默认值（≈L214）改为 `False`。
    - 改动（仅当任务 1 判定 `cli_install.py` 仍存在）：`install_connector_cli` 在未安装时直接返回 `_fail(status, …)`，不再调用 `npm`，并在 `tests/unit/connectors/` 补一条"不建子进程"的用例。
    - 验证：`uv run pytest tests/unit/utils/test_runtime_packages.py tests/unit/backend/test_opensandbox_deps.py tests/unit/api/test_knowledge_error_mapping_intranet.py tests/unit/test_plugins_no_runtime_deps.py tests/unit/test_plugin_manager.py tests/unit/agents/test_onnx_service.py -q && ! rg -n "install_deps=True" src`
    - _需求：2.1, 2.2, 2.3, 2.4, 2.5_

- [ ] 4. bubblewrap 与 Docker 引擎只探测不安装（1 人日）
  - [ ] 4.1 先写会失败的用例
    - 改动：`tests/unit/infra/utils/test_bwrap.py`：删除 `test_ensure_degraded_when_no_package_manager`、`test_ensure_degraded_when_no_privilege`、`test_ensure_installed_after_successful_install`、`test_ensure_degraded_when_install_fails` 与三个 `_install_argv` 用例；新增"Linux 且 `which` 为空时返回 `degraded`/`not_installed`，且被替换为'调用即失败'桩的 `subprocess.run` 从未被调用"。
    - 改动：`tests/unit/infra/utils/test_docker_env.py`：删除 `test_install_script_linux`、`test_install_script_darwin`、`test_agent_prompt_missing_vs_daemon_down`、`test_ensure_installs_on_linux`；`test_status_daemon_down` 去掉对脚本与提示词内容的断言，`test_status_missing` 改为断言 `can_auto_install is False`，`test_ensure_skips_non_linux` 改为断言 `ensure_docker()` 与 `docker_status()` 结果相同（`missing`）；新增"三个文本字段恒为空字符串、不建安装子进程"。
    - 改动：`tests/integration/test_filesystem_api.py` 增加 `POST /api/filesystem/ensure-docker` 的响应断言（`install_script == ""`、`can_auto_install is False`）。
    - 验证：`uv run pytest tests/unit/infra/utils/test_bwrap.py tests/unit/infra/utils/test_docker_env.py tests/integration/test_filesystem_api.py -q`（此时应失败）
    - _需求：3.1, 3.2_
  - [ ] 4.2 实现与文案
    - 改动：`src/octop/infra/utils/bwrap.py`：删除 `_PKG_MANAGERS`、`_detect_package_manager`、`_can_install_without_password`、`_run_install`、`_install_argv`、`_install_bubblewrap`；`ensure_bubblewrap` 只保留三分支。
    - 改动：`src/octop/infra/utils/docker_env.py`：删除 `_PKG_MANAGERS`、`_DOCS_BY_PLATFORM`、安装相关函数、`install_script`、`agent_prompt`；`docker_status` 忽略 `attempt_install`，三个文本字段为空、`can_auto_install` 为 `False`；`__all__` 同步。
    - 改动：`scripts/intranet/public_hosts.py` 删除 `docker_env.py` 的三条 `PENDING_FIXES`。
    - 改动：`dashboard/src/locales/intranet/{en,zh}.json` 覆盖 `experts.ensureBwrap.degraded`、`storage.dockerEnv.manualDesc`、`storage.dockerEnv.octopDesc`、`storage.dockerEnv.status.missing`，说明运行期不会自动安装、需由管理员在镜像或宿主机预置。
    - 验证：`uv run pytest tests/unit/infra/utils/test_bwrap.py tests/unit/infra/utils/test_docker_env.py tests/unit/test_launch_bwrap.py tests/integration/test_filesystem_api.py tests/unit/test_no_public_endpoints.py tests/unit/i18n -q`
    - 验证：`! rg -n "apt-get|dnf|yum|pacman|zypper|get\.docker\.com|docs\.docker\.com" src/octop/infra/utils/bwrap.py src/octop/infra/utils/docker_env.py`
    - _需求：3.1, 3.2, 3.3, 3.4, 1.3, 16.4_

- [ ] 5. 存储后端 SDK 可用性闸门（0.5 人日）
  - 改动：先写 `tests/unit/backend/test_sdk_availability.py`（映射表五项、未登记类型恒为可用、以 monkeypatch `importlib.util.find_spec` 模拟缺失）与 `tests/integration/test_storage_backend_sdk_gate.py`（管理员以 `kind="cos"` 创建、以 `kind="oss"` 修改既有 `s3` 行，均得 503 与 `error.code == "STORAGE_BACKEND_DEPS_FAILED"`，`storage_backends` 行数与内容不变；带 `Accept-Language: zh-CN` 时 `message` 等于 overlay 文案；SDK 可导入时创建成功）。
  - 改动：新增 `src/octop/infra/backend/sdk_availability.py`（`KIND_SDK_MODULES`、`backend_sdk_available`）；`src/octop/api/routers/storage_backends.py` 的 `_ensure_opensandbox_sdk`（≈L17-25）改为 `_ensure_backend_sdk`，≈L106 与 ≈L133 两处调用同步。
  - 改动：`src/octop/i18n/intranet/{en,zh}.json` 覆盖 `errors.STORAGE_BACKEND_DEPS_FAILED`，`dashboard/src/locales/intranet/{en,zh}.json` 覆盖 `apiErrors.STORAGE_BACKEND_DEPS_FAILED`。
  - 验证：`uv run pytest tests/unit/backend/test_sdk_availability.py tests/integration/test_storage_backend_sdk_gate.py tests/unit/i18n -q`
  - _需求：5.1, 5.2, 5.3, 16.4_

- [ ] 6. 入口脚本幂等（1.5 人日）
  - [ ] 6.1 `octop init --if-needed`（0.5 人日）
    - 改动：先在 `tests/unit/cli/test_init_cmd.py` 追加用例：空目录 → 0 且建出管理员；再次执行 → 3，且 `~/.octop` 下所有文件的相对路径与 mtime 快照不变；目录非空但库无用户 → 0；弱口令 → 4 且无用户；与 `--force` 同用 → 退出码 2；不带 `--if-needed` 的既有用例保持不变。
    - 改动：`src/octop/cli/commands/init.py` 新增 `--if-needed` 选项与 `EXIT_ALREADY_INITIALIZED = 3`、`EXIT_PASSWORD_REJECTED = 4`；流程按设计文档方案第 9 条（迁移并数用户 → 校验口令 → 播种插件 → 建管理员）。
    - 验证：`uv run pytest tests/unit/cli/test_init_cmd.py -q`
    - _需求：11.1, 11.2, 11.3_
  - [ ] 6.2 PostgreSQL 用例（0.25 人日）
    - 改动：新增 `tests/integration/test_init_if_needed_postgresql.py`（`@requires_postgresql` 与 `@pytest.mark.postgresql`）：以 `OCTOP_DATABASE_URL` 指向测试库，首次 0、再次 3，且 `~/.octop` 下不生成 `octop.db`。
    - 验证：`OCTOP_TEST_DATABASE_URL=<专用库 DSN> uv run pytest tests/integration/test_init_if_needed_postgresql.py -q`（或 `make test-postgresql`）
    - _需求：11.1_
  - [ ] 6.3 重写入口脚本（0.75 人日）
    - 改动：先新增 `tests/unit/test_docker_entrypoint.py`（模块级 `posix_only`）：在 `tmp_path` 放假 `octop` 可执行文件，按环境变量给出的序列返回退出码并把参数与 `OCTOP_ADMIN_PASSWORD` 是否出现在参数中写入日志；场景：0 → 写出 600 权限的 `credential.txt` 并 `exec octop run`；3 → 不写凭据；4 然后 0 → 第二次调用使用新密码并写凭据；1 → 脚本以 1 退出且不再调第二次；数据目录不可写（`chmod 500`；以 root 运行测试时该场景 `pytest.skip`，因为 root 不受权限位限制）→ 以 78 退出；任何场景下密码都不出现在 `octop` 的命令行参数中。
    - 改动：`docker/docker-entrypoint.sh`：删除 `DB_FILE` 判据（≈L23、≈L47）与无保护的兜底重试（≈L62-66）；按设计文档方案第 9 条实现可写检测、`octop init --if-needed` 与退出码分派；密码经 `OCTOP_ADMIN_PASSWORD` 传入。
    - 验证：`bash -n docker/docker-entrypoint.sh && uv run pytest tests/unit/test_docker_entrypoint.py -q`
    - _需求：11.4, 11.6, 10.3_

- [ ] 7. Monaco 本地打包（1 人日）
  - 改动：先写 `dashboard/src/utils/monacoLocal.test.ts`：`vi.mock("@monaco-editor/react")` 提供假的 `loader.config` 与默认组件，`vi.mock("./monacoEnvironment")` 导出哨兵对象；断言 `loadMonacoEditor()` 返回的 `default` 为该组件、`loader.config` 恰被调用一次且参数为 `{ monaco: <哨兵> }`、参数序列化后不含 `cdn.jsdelivr.net`。
  - 改动：`dashboard/package.json` 在 `dependencies` 中加 `"monaco-editor": "0.55.1"`；新增 `dashboard/src/utils/monacoEnvironment.ts` 与 `dashboard/src/utils/monacoLocal.ts`（设计文档方案第 10 条）；`dashboard/src/pages/Agent/Workspace/components/CodeEditor.tsx` ≈L19 与 `dashboard/src/pages/Experts/components/FileEditModal.tsx` ≈L10 改为 `lazy(loadMonacoEditor)`。
  - 改动：在行内执行 `make relock` 的 npm 半步 `cd dashboard && npm install --package-lock-only --ignore-scripts --no-audit --no-fund --registry <行内 npm>`，只更新 `dashboard/package-lock.json`（`monaco-editor` 由 `peer` 变为直接依赖），作为本任务最后一个单独提交，保证 `npm ci` 与锁一致。
  - 验证：`cd dashboard && npx vitest run src/utils/monacoLocal.test.ts && npx tsc -b && npm run lint`
  - 验证（行内环境）：`make install-frontend NPM_REGISTRY=<行内 npm> && (cd dashboard && npm run build:docker) && ! rg -q "MonacoEnvironment" src/octop/dashboard/assets/index-*.js`
  - _需求：12.1, 12.2, 12.4_

- [ ] 8. Scalar API 文档页本地化（1 人日）
  - [ ] 8.1 随包交付 Scalar 独立脚本（0.5 人日）
    - 改动：新增 `scripts/intranet/vendor_scalar.sh <版本>`：用 `npm pack @scalar/api-reference@<版本> --registry "$NPM_REGISTRY"` 取 tarball，核对 npm 返回的 `integrity`，解出 `package/dist/browser/standalone.js` 与 `package/LICENSE` 到 `src/octop/api/vendor/scalar/`，写 `SOURCE.json`（包名、版本、tarball 名、`integrity`、`standalone.js` 的 SHA256）。
    - 改动：执行脚本生成三个文件（版本 1.71.0，与设计时核对的版本一致）；`pyproject.toml` 的 `[tool.hatch.build].include` 加 `"src/octop/api/vendor/**/*"`；`Makefile.intranet` 新增 `vendor-scalar` 目标。
    - 改动：`tests/unit/test_offline_build_contract.py`（本任务新建该文件）加 Scalar 用例：`standalone.js` 的 SHA256 等于 `SOURCE.json` 登记值，`LICENSE` 含 `MIT`。
    - 验证：`bash -n scripts/intranet/vendor_scalar.sh && uv run pytest tests/unit/test_offline_build_contract.py -q`
    - 验证（行内环境）：`uv build --wheel && unzip -l dist/octop-*.whl | rg -c "octop/api/vendor/scalar/(standalone\.js|LICENSE)"`（期望输出 2）
    - _需求：13.2, 13.4_
  - [ ] 8.2 文档路由（0.5 人日）
    - 改动：先在 `tests/integration/test_scalar.py` 增加断言：`/api/docs` 的 HTML 不含 `cdn.jsdelivr.net` 与 `fastapi.tiangolo.com`，含 `/api-docs-assets/scalar.js`、`"withDefaultFonts": false`、`"telemetry": false`、`"agent": {"disabled": true}`；未带令牌 `GET /api-docs-assets/scalar.js` 得 200、`content-type` 含 `javascript`、内容 SHA256 与 `SOURCE.json` 一致；在 `test_api_docs_disabled_by_default` 中追加 `/api-docs-assets/scalar.js` 为 404。
    - 改动：新增 `src/octop/api/intranet_docs.py::install_api_docs(app)`；`src/octop/api/app.py` 的 `if enable_api_docs:` 分支（≈L278-285）改为调用它，删除 ≈L13 的 `HTMLResponse` 与 ≈L14 的 `get_scalar_api_reference` 导入。
    - 验证：`uv run pytest tests/integration/test_scalar.py tests/unit/test_offline_build_contract.py -q`
    - _需求：13.1, 13.2, 13.3_

- [ ] 9. 进程内断网运行用例（1 人日）
  - 改动：新增 `tests/integration/test_airgap_runtime.py`，夹具按设计文档方案第 13 条拦截非回环 socket 连接、非本地域名解析与安装类子进程并记录。用例以 `write_octop_config(enable_api_docs=True)` 与 `octop_client` 启动服务、`bootstrap_admin` 登录，依次请求 `GET /api/health`、`GET /api/auth/me`、`GET /api/agents`、`GET /api/settings/capabilities`、`GET /api/settings/timezone`、`GET /api/docs`、`GET /api-docs-assets/scalar.js`、`POST /api/filesystem/ensure-bwrap`、`POST /api/filesystem/ensure-docker`、`PUT /api/knowledge-bases/feature`（`{"enabled": true, "backend": "onnx"}`：依赖缺失时期望 `KNOWLEDGE_PREREQUISITES_FAILED`，依赖存在时期望 2xx），并直接调用 `octop.launch._ensure_linux_bubblewrap()`；若 `rapidocr` 可导入，再构造一次 `ocr._rapidocr_engine()`。最后断言连接记录与子进程记录均为空。
  - 改动：另写一条夹具自检用例：在夹具生效时主动 `socket.create_connection(("198.51.100.1", 443))` 与 `subprocess.run(["pip", "--version"])`，断言二者都被记录并抛错，防止夹具失效后用例空转。
  - 验证：`uv run pytest tests/integration/test_airgap_runtime.py -q`
  - _需求：15.1, 4.3_

- [ ] 10. harness-* 行内 Git 内部分支（3 人日，主要在行内 harness 仓库中完成）
  - [ ] 10.1 导入与构建发布（1.5 人日）
    - 改动（行内 Git）：为 `orcakit-harness-agent` 1.0.11、`harness-gateway` 0.9.8、`harness-memory` 0.9.10、`harness-browser` 0.7.9 各建仓库，首个提交为 sdist 原样解包（说明中写 sdist 文件名与 SHA256，SHA256 取自基线 `uv.lock` 中对应 `sdist` 条目），建 `intranet/<版本>` 分支；配置行内流水线：把 `version` 改为 `<版本>+intranet.<N>`、构建 wheel、检查无二进制文件、发布到行内 PyPI、打 `v<版本>+intranet.<N>` 标签。本步四个包都以 `+intranet.1` 发布（`harness-memory`、`harness-browser` 不含补丁）。
    - 改动（本仓库）：在 `docs/intranet/offline-build.md` 写"harness 内部分支"一节：仓库地址占位、分支与标签规则、补丁清单、上游升级流程（设计文档方案第 6 条）。
    - 验证（行内环境，在各 harness 仓库执行）：`git tag -l 'v*+intranet.*'`；`! unzip -l dist/*.whl | rg -q '\.(so|pyd|dylib)$'`；`ls dist/*-py3-none-any.whl`
    - _需求：7.1, 7.2_
  - [ ] 10.2 `harness-gateway` 去掉 IM SDK 硬依赖（0.5 人日）
    - 改动（行内 Git，`harness-gateway`）：`pyproject.toml` 把 `dingtalk-stream`、`lark-oapi`、`python-telegram-bot`、`wecom-aibot-sdk` 移到 extra `dingtalk`、`feishu`、`telegram`、`wecom`，删除 `discord-py`；发布 `0.9.8+intranet.2`。
    - 验证（行内环境）：`! unzip -p dist/harness_gateway-*.whl '*.dist-info/METADATA' | rg '^Requires-Dist: (dingtalk-stream|discord-py|lark-oapi|python-telegram-bot|wecom-aibot-sdk)[^;]*$'`
    - 验证（行内环境）：`uv venv /tmp/gw-check && uv pip install --python /tmp/gw-check/bin/python dist/harness_gateway-*.whl && /tmp/gw-check/bin/python -c "import harness_gateway, harness_gateway.manager, harness_gateway.channels.mqtt" && ! uv pip show --python /tmp/gw-check/bin/python lark-oapi`
    - _需求：7.4_
  - [ ] 10.3 `orcakit-harness-agent` 两个补丁（1 人日）
    - 改动（行内 Git，`orcakit-harness-agent`）：先在其测试中加用例：`ensure_docker_image` 对假客户端在 `images.get` 抛 `ImageNotFound` 时抛 `RuntimeError` 且 `images.pull`、`api.pull` 均未被调用；`inspect.getsource(HarnessAgent._build_tools)` 不含 `browser_use` 与 `build_desktop_screenshot_tool(`。再实现：`backends/docker_sandbox.py::ensure_docker_image` 删除拉取分支，抛出带"请在 Docker 主机预置镜像"说明的错误；`agent.py::_build_tools` 不再注册两个内置工具并删除相应导入。发布 `1.0.11+intranet.2`。
    - 验证（行内环境，在该仓库执行）：`uv run pytest -q`
    - _需求：7.5, 4.1_

- [ ] 11. 依赖收敛与锁文件行内重生成（1.5 人日）
  - [ ] 11.1 先写契约用例，再改 `pyproject.toml`（0.5 人日）
    - 改动：在 `tests/unit/test_offline_build_contract.py` 追加：`[project].dependencies` 中 `orcakit-harness-agent` 的 extra 恰为 `docker,observability`、有 `psutil>=5.9`、四个 harness 包以 `==…+intranet.` 固定；无 `desktop`、`browser` extra；`[tool.uv].environments` 限定 3.12；`uv.lock` 不含需求 6.3 所列 24 个包；锁中四个 harness 包版本带 `+intranet.` 且 wheel 以 `-py3-none-any.whl` 结尾；`uv.lock` 不含 `files.pythonhosted.org` 与 `pypi.org/simple`；`dashboard/package-lock.json` 不含 `registry.npmjs.org`。
    - 改动：`pyproject.toml`：≈L24 改为 `"orcakit-harness-agent[docker,observability]==1.0.11+intranet.2"`，并新增 `"psutil>=5.9"`；`harness-memory`、`harness-gateway`、`harness-browser` 改为对应 `==…+intranet.N`；删除 `desktop` extra（≈L70）及其注释；按任务 1 的判定删除已无导入的残余直接依赖；在 `[dependency-groups]` 之前新增 `[tool.uv]` 段与 `environments`。
    - 验证：`uv run pytest tests/unit/test_offline_build_contract.py -q`（锁相关用例此时应失败，其余应通过）
    - _需求：6.1, 6.3, 6.4, 7.3_
  - [ ] 11.2 行内重生成两份锁（0.5 人日，行内环境，锁文件单独一个提交）
    - 改动：`make relock PYPI_INDEX=<行内 PyPI> NPM_REGISTRY=<行内 npm>`；提交信息注明使用的 uv 版本（与任务 13 的 `UV_IMAGE` 一致）。
    - 验证：`uv run pytest tests/unit/test_offline_build_contract.py -q`
    - 验证：`test "$(grep -c files.pythonhosted.org uv.lock)" -eq 0 && test "$(grep -c 'pypi.org/simple' uv.lock)" -eq 0 && test "$(grep -c registry.npmjs.org dashboard/package-lock.json)" -eq 0 && ! rg -n '://[^/@ ]+:[^/@ ]+@' uv.lock dashboard/package-lock.json`
    - 验证：`test "$(uv export --frozen --no-dev --no-hashes --no-emit-project | grep -c '==')" -le 155 && test "$(uv export --frozen --no-dev --no-hashes --no-emit-project --extra local-embedding --extra knowledge-ocr | grep -c '==')" -le 175`
    - _需求：8.1, 8.2, 8.4, 6.2_
  - [ ] 11.3 行内实测离线同步（0.5 人日，行内环境）
    - 改动：在只能解析行内制品库域名的构建机上执行下列命令，结果与 `uv sync -v` 日志中出现的主机名写入 `docs/intranet/offline-build.md` 的"锁文件"一节；同时记录路径前缀型 npm 私服与 `replace-registry-host=always` 的实测结论（`w0-02`、`w0-04` 的交接项）。
    - 验证（行内环境）：`uv sync --frozen --no-dev -v 2>&1 | rg -o 'https?://[^/ ]+' | sort -u`（期望只有行内域名）；`make install-frontend NPM_REGISTRY=<行内 npm> && make check-frontend`
    - _需求：8.3_

- [ ] 12. 删除 `w1-02` 过渡中和层并补 Docker 不拉取用例（0.5 人日）
  - 改动：先新增 `tests/unit/backend/test_docker_probe_no_pull.py`：monkeypatch `docker.from_env` 返回假客户端（`ping` 成功、`images.get` 抛 `docker.errors.ImageNotFound`、`images.pull` 与 `api.pull` 记录调用），对 `kind="docker"` 的行调用 `octop.infra.backend.probe.probe_storage_backend`，断言 `ok is False` 且两个 pull 均未被调用；另加契约用例断言已安装 harness 的 `HarnessAgent._build_tools` 源码不含 `browser_use` 与 `build_desktop_screenshot_tool(`。
  - 改动：删除 `src/octop/infra/agents/harness_removed_tools.py` 与 `tests/unit/agents/test_harness_removed_tools.py`，删除 `src/octop/infra/server.py::_boot_runtime` 中对 `neutralize_removed_harness_tools()` 的调用与导入。
  - 验证：`uv run pytest tests/unit/backend/test_docker_probe_no_pull.py tests/unit/agents tests/integration/test_agents_shared.py -q && ! rg -n "harness_removed_tools|neutralize_removed_harness_tools" src tests`
  - _需求：7.6, 4.1_

- [ ] 13. 镜像：行内基础镜像、非 root、双架构（2.5 人日）
  - [ ] 13.1 Dockerfile（1.25 人日）
    - 改动：先在 `tests/unit/test_offline_build_contract.py` 追加 Dockerfile 用例：首个 `FROM` 之前声明无默认值的 `ARG NODE_IMAGE`、`ARG PYTHON_IMAGE`、`ARG UV_IMAGE`；每个 `FROM` 只引用这三个参数，前端阶段带 `--platform=$BUILDPLATFORM`；不含 `ghcr.io`、`docker.io`、`PIP_INDEX_URL`、`PIP_TRUSTED_HOST`、`UV_INDEX_URL`、`APT_MIRROR`、`COPY .env.example`；含 `COPY --from=uv`、`APT_DEBIAN_URL`、`APT_SECURITY_URL`、`--mount=type=secret,id=netrc`、`--mount=type=secret,id=npmrc`、两处 `uv sync --frozen --no-dev --extra local-embedding --extra knowledge-ocr`、`npm ci` 带 `--registry`、两条"锁含公网地址即失败"的检查、`useradd` 的 uid 10001；`ENV` 含 `HF_HUB_OFFLINE=1`、`HF_HUB_DISABLE_TELEMETRY=1`、`XDG_CACHE_HOME=/tmp/octop-cache`；最后一条 `USER` 为 `10001:10001`。
    - 改动：`docker/Dockerfile` 按设计文档方案第 8 条重写（产物扫描一步留给任务 14）；`scripts/intranet/public_hosts.py` 删除 `docker/Dockerfile` 的 `PENDING_FIXES`。
    - 验证：`uv run pytest tests/unit/test_offline_build_contract.py tests/unit/test_no_public_endpoints.py -q`
    - 验证（行内环境）：`PLATFORMS=linux/amd64 NODE_IMAGE=… PYTHON_IMAGE=… UV_IMAGE=… NPM_REGISTRY=… APT_DEBIAN_URL=… APT_SECURITY_URL=… bash docker/docker_build.sh octop:intranet-dev && docker run --rm --entrypoint id octop:intranet-dev -u && docker run --rm --entrypoint sh octop:intranet-dev -c 'test ! -e /app/.env.example && test ! -w /app'`
    - _需求：9.1, 9.3, 9.6, 10.1, 10.4, 4.2, 6.5_
  - [ ] 13.2 构建脚本与 Make 目标（0.75 人日）
    - 改动：先新增 `tests/unit/test_docker_build_script.py`（`posix_only`）：在 `PATH` 前置假 `docker` 记录参数；缺任一必填变量时脚本非零退出、列出缺失项且未调用 `docker`；全部提供时参数含 `buildx build`、`--platform linux/amd64,linux/arm64` 与 6 个 `--build-arg`；未设 `PUSH=1` 且为多平台时非零退出并提示；`NETRC_FILE` 存在时出现 `--secret id=netrc,src=…`。
    - 改动：`docker/docker_build.sh` 按设计文档方案第 8 条重写，删除腾讯镜像注释与透传；`Makefile.intranet` 新增 `image` 目标（`bash docker/docker_build.sh $(IMAGE_TAG)`），`help-intranet` 增加一行；`scripts/intranet/public_hosts.py` 删除 `docker/docker_build.sh` 的 `PENDING_FIXES`。
    - 验证：`bash -n docker/docker_build.sh && uv run pytest tests/unit/test_docker_build_script.py tests/unit/test_no_public_endpoints.py -q`
    - 验证（行内环境）：`PUSH=1 bash docker/docker_build.sh <行内 Harbor 标签> && docker buildx imagetools inspect <行内 Harbor 标签> | rg -c 'linux/(amd64|arm64)'`（期望 2）
    - _需求：9.2, 9.4, 9.6_
  - [ ] 13.3 compose（0.5 人日）
    - 改动：先在 `tests/unit/test_offline_build_contract.py` 追加 compose 用例：`docker/docker-compose.yml` 的 `image` 为 `${OCTOP_IMAGE:-octop:latest}`，声明 `user: "10001:10001"`、`read_only: true`、`tmpfs`、`cap_drop` 含 `ALL`、`security_opt` 含 `no-new-privileges:true`，`environment` 不含 `OPENAI_API_KEY`、`DASHSCOPE_API_KEY`；`docker/docker-compose.postgres.yml` 的 `image` 为 `${OCTOP_PG_IMAGE:?…}` 且不含 `pgvector/pgvector`。
    - 改动：两份 compose 按设计文档方案第 8 条修改；新增键放在 `environment:` 之前。
    - 验证：`uv run pytest tests/unit/test_offline_build_contract.py tests/unit/test_docker_compose_database_env.py -q`
    - _需求：9.5, 10.4_

- [ ] 14. 构建产物出网门禁（0.75 人日）
  - 改动：先在 `tests/unit/test_no_public_endpoints.py` 追加产物用例：在 `tmp_path` 构造假产物目录，含 `https://cdn.jsdelivr.net/npm/monaco-editor@0.55.1/min/vs` 时通过，含 `https://cdn.jsdelivr.net/npm/@scalar/api-reference`、`https://challenges.cloudflare.com/x.js`、`https://fonts.googleapis.com/css` 任一时失败，含 `https://raw.githubusercontent.com/org/repo/main/x.zip`（展示域名）时通过、含 `https://huggingface.co/x` 时失败；`ARTIFACT_DISPLAY_HOSTS` 等于 `dashboard/` 侧白名单域名集合。
  - 改动：`scripts/intranet/public_hosts.py` 实现 `scan_artifact` 与子命令 `artifact <dir>`；`Makefile.intranet` 新增 `build-frontend-intranet`（依次执行 `install-frontend`、`cd $(DASHBOARD_DIR) && npm run build`、`$(PYTHON) scripts/intranet/public_hosts.py artifact $(DASHBOARD_DEST)`），并让 `check-public-hosts` 在 `$(DASHBOARD_DEST)/index.html` 存在时同时扫描产物；`docker/Dockerfile` runtime 阶段在复制前端产物后执行产物扫描（设计文档方案第 8 条），并在契约用例中断言该步骤存在。
  - 验证：`uv run pytest tests/unit/test_no_public_endpoints.py tests/unit/test_offline_build_contract.py -q`
  - 验证（行内环境）：`make build-frontend-intranet NPM_REGISTRY=<行内 npm>`
  - _需求：1.4, 1.5, 1.6_

- [ ] 15. 运行期资产预置清单与 ONNX 打包脚本（0.75 人日）
  - 改动：先新增 `tests/unit/test_pack_onnx_models.py`：以 `importlib` 加载 `scripts/intranet/pack_onnx_models.py`，用 `monkeypatch.setitem(sys.modules, "huggingface_hub", <假模块>)` 注入假的 `snapshot_download`（脚本在函数内导入该包，因此用例不依赖 `local-embedding` extra 是否安装），由它在临时缓存目录生成 `models--<org>--<name>/refs/main` 与 `snapshots/<rev>/onnx/model.onnx`；断言脚本产出的压缩包解到 `tmp_path/embedding_models/` 后，在 `OCTOP_HOME=tmp_path` 下 `list_downloaded_models()` 列出该模型，且 `SHA256SUMS` 与文件一致。
  - 改动：新增 `scripts/intranet/pack_onnx_models.py`（默认模型为 `ONNX_PRESET_MODEL_IDS`，按 `onnx_catalog` 的 `hf_source` 取仓库，参数 `--out`、`--model`）；`docs/intranet/offline-build.md` 写入设计文档方案第 12 条的预置清单表（含每项的校验命令与缺失表现）与 Harbor 导入清单（应用构建所需的 node、python、uv 三个基础镜像，以及 `w0-02` 需要的 `node:20`、`postgres:16` 和 compose 用的 pgvector 镜像）。
  - 验证：`uv run pytest tests/unit/test_pack_onnx_models.py -q && rg -n "预置清单" docs/intranet/offline-build.md`
  - _需求：14.1, 14.2, 14.3_

- [ ] 16. 容器级断网冒烟与人工验收（1.5 人日，行内环境）
  - 改动：新增 `scripts/intranet/airgap_smoke.sh <镜像>`：`docker network create --internal`；SQLite 组与 PostgreSQL 组（`OCTOP_PG_IMAGE`）各以 `--read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges` 启动，等待 `docker exec … curl -fsS http://127.0.0.1:8088/api/health`，写入标记文件，`docker restart` 3 次并每次复查健康、标记文件、`docker inspect -f '{{.State.Restarting}}'` 为 `false`、`docker logs` 不含 `already exists and is not empty`；检查 `id -u` 为 10001；另起一个挂载"属主不是 10001、权限 755 的宿主目录"的容器，断言以 78 退出；结束时清理网络与容器；任一检查失败即非零退出。`Makefile.intranet` 新增 `airgap-smoke` 目标。
  - 改动：分别在 amd64 与 arm64 主机（或 QEMU）上对任务 13 推送的双架构镜像执行冒烟；在只允许访问自身的浏览器环境中按需求 15.3 与 12.3 做人工检查；结果写入 `docs/intranet/offline-build.md` 的"断网验收记录"。
  - 验证：`bash -n scripts/intranet/airgap_smoke.sh`
  - 验证（行内环境）：`bash scripts/intranet/airgap_smoke.sh <行内 Harbor 标签>`（amd64 与 arm64 各一次，退出码均为 0）
  - _需求：15.2, 15.3, 10.2, 11.5, 12.3, 9.4_

- [ ] 17. 收尾（0.75 人日）
  - 改动：确认 `scripts/intranet/public_hosts.py` 的 `PENDING_FIXES` 为空（在 `tests/unit/test_no_public_endpoints.py` 中加断言）；补全 `docs/intranet/offline-build.md`（基线、构建前置、harness 内部分支、`make relock`、镜像构建与运行参数、预置清单、门禁白名单维护规则、断网验收记录）。
  - 改动：`CHANGELOG-intranet.md` 追加本 spec 条目（需求 16.1 所列各项，另注明 `runtime_packages.py` 中保留的安装辅助函数已不可达）；`docs/api-intranet.md` 追加需求 16.2 所列接口与路径的变化。
  - 验证：`make all`
  - 验证：`cd dashboard && npx tsc -b && npm run lint && npm run test`
  - 验证：`uv run pytest tests/unit/i18n tests/unit/test_no_public_endpoints.py tests/unit/test_offline_build_contract.py tests/integration/test_airgap_runtime.py -q`
  - 验证：`rg -n "w2-01" CHANGELOG-intranet.md docs/api-intranet.md`
  - _需求：16.1, 16.2, 16.3, 16.4, 1.3_
