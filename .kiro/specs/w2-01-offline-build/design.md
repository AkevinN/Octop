# 设计文档：离线构建与依赖收敛

> spec：`w2-01-offline-build` ｜ 波次：Wave 2 ｜ 基线：`757fd12` ｜ 预估：20 人日
> 前置：`w0-01-fork-migration-namespace`、`w0-02-ci-gates`、`w0-03-test-auth-baseline`、`w0-04-fork-isolation-points`、`w1-02-capability-trim`、`w1-03-online-fetch-trim`、`w1-04-content-trim`、`w1-05-saas-decoupling` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 概述

**结论：** 本 spec 用"构建期把一切备齐、运行期什么都不取"的原则收口离线交付。构建期：三个基础镜像、apt 源、npm 与 PyPI 私服全部由构建参数指向行内，锁文件只记录行内地址，`harness-*` 由行内 Git 构建，前端的 Monaco 与后端的 Scalar 都随包交付，镜像同时产出 amd64 与 arm64。运行期：所有"缺了就装"的路径（`pip`、插件依赖、`apt-get` 装 bubblewrap 与 Docker、`docker pull`）全部改为"只探测、缺了就报错"，模型与镜像按预置清单放进镜像或数据卷。守护：源码与产物两层的出网静态门禁、进程内断网用例、容器级断网冒烟脚本。

设计上坚持三条：

1. **不新增配置键。** 运行期安装是硬关闭而不是开关。开关要穿过 `infra/utils` 不得读配置的边界（全局约束第 2 节），需要 `server.py`、`launch.py`、`open_cli_services` 三处注入；而行内版不存在"需要打开它"的场景，开发机用 `uv sync --all-extras` 即可。
2. **不改接口形状。** `/api/filesystem/ensure-*` 保留、只探测，字段不变、值变空，前端零 TypeScript 改动；需要改变的用户可见文案一律走 intranet overlay。
3. **上游热点文件只做最小编辑。** `app.py` 的文档路由逻辑下沉到新模块 `api/intranet_docs.py`；`pyproject.toml` 只改依赖行、删 `desktop` extra、加一个 `[tool.uv]` 段与一行 hatch include；锁文件永不手改，只用 `make relock` 在行内重生成。

## 现状

以下事实都在基线 `757fd12` 上用 `rg`、`sed -n`、`uv export` 与对锁文件的 `tomllib` 解析亲自核实。行号仅作定位提示。

### 构建与镜像

- `docker/Dockerfile`：`FROM node:20-slim AS frontend-builder`（≈L36）、`ARG NPM_REGISTRY=`（≈L38）后用 `npm config set registry` 并带一次重试的 `npm ci`（≈L46-51）；`FROM python:3.12-slim AS runtime`（≈L64）；`ARG PIP_INDEX_URL/PIP_TRUSTED_HOST/APT_MIRROR`（≈L82-84），其中 `APT_MIRROR` 只接受主机名并拼成 `https://%s/debian`（≈L86-97）；`COPY --from=ghcr.io/astral-sh/uv:0.7 /uv /uvx /bin/`（≈L99）；两处 `uv sync --frozen`（≈L105-110、≈L122-127）之前 `export UV_INDEX_URL`，而 `--frozen` 按锁中 URL 下载，这段导出无效；`COPY .env.example ./`（≈L118，全仓无读取方，且该文件 ≈L69 含 `cos.ap-guangzhou.myqcloud.com` 示例）；`fonts-noto-cjk` 与清理 `build-essential`（≈L128-129）；`HEALTHCHECK … curl -f http://localhost:${OCTOP_PORT}/api/health`（≈L136-137）。全文件无 `USER` 指令。`w1-02` 已去掉 `--extra browser` 与 `PLAYWRIGHT_BROWSERS_PATH`。
- `docker/docker_build.sh`：注释与参数透传指向 `mirrors.cloud.tencent.com`（≈L13-18、≈L31-46），最终调用普通 `docker build`（≈L54-59），没有 `buildx` 与 `--platform`。`w1-04` 已删除 `.github/workflows/docker-publish.yml`（其中 `platforms: linux/amd64`），仓库内再无双架构构建入口。
- `docker/docker-compose.yml`：`image: octop:latest`（≈L27）、`restart: unless-stopped`（≈L29）、宿主机目录挂载 `${OCTOP_DATA:-~/.octop}:/data/.octop`（≈L33）、`environment` 列表（≈L34-55）含 `OPENAI_API_KEY`、`DASHSCOPE_API_KEY`（≈L50-51）。文件头 ≈L16-17 说明变量必须列在 `environment` 中才进容器，`tests/unit/test_docker_compose_database_env.py` 据此断言数据库变量全部透传。`docker/docker-compose.postgres.yml` 使用 `image: pgvector/pgvector:pg16`（≈L23），即隐式指向 Docker Hub。
- `dashboard/.npmrc` 固定 `registry=https://registry.npmjs.org` 与 `replace-registry-host=always`（上游热修 ae43484）。Dockerfile 在执行 `npm ci` 时只复制了 `package.json` 与 `package-lock.json`，项目级 `.npmrc` 此时不在场。
- 根 `Makefile` 的 `build-frontend`（≈L96-102）硬编码 `npm ci`；`w0-02` 与 `w0-04` 交付的 `Makefile.intranet` 提供 `install-frontend`（带 `NPM_REGISTRY`）、`check-frontend`、`test-postgresql` 与 `relock`。

### 锁文件与依赖

- `uv.lock`：242 个包；`resolution-markers` 覆盖 `>=3.15`、`3.14.*`、`3.13.*`、`<3.13` 四个区间（≈L4-9）；`grep -c files.pythonhosted.org` = 2715，`grep -c 'registry = "https://pypi.org/simple"'` = 241。四个 harness 包的条目在 ≈L1332（`harness-browser` 0.7.9）、≈L1347（`harness-gateway` 0.9.8）、≈L1372（`harness-memory` 0.9.10）、≈L2837（`orcakit-harness-agent` 1.0.11），均为 `py3-none-any` wheel 且带 sdist。
- `dashboard/package-lock.json`：`grep -c registry.npmjs.org` = 1125。
- 运行时闭包：`uv export --frozen --no-dev --no-hashes --no-emit-project | grep -c '=='` = 203，加 `--extra local-embedding --extra knowledge-ocr` = 223。用 `tomllib` 遍历锁依赖图复算：带 `[all]` 203、去掉 154，差 49 个包。
- `pyproject.toml`：`requires-python = ">=3.12"`（≈L11）；`"orcakit-harness-agent[all]>=1.0.11"`（≈L24）、`harness-memory`（≈L25）、`lark-oapi`（≈L26）、`harness-gateway`（≈L27）、`scalar-fastapi`（≈L29）、`edge-tts`（≈L30）、`boto3`（≈L35）、`harness-browser`（≈L36）；`desktop = ["mss>=9.0", "pynput>=1.7"]`（≈L70）、`local-embedding`（≈L72）、`knowledge-ocr`（≈L73-77，含 AGPL 的 `pymupdf`）；`[tool.hatch.build].include`（≈L101-115）不含 `.js`；无 `[tool.uv]` 段；pytest `markers`（≈L205-209）。`w1-02` 已删 `playwright` 与 `browser` extra，`w1-03` 已删 `acme`、`josepy`，`w1-04` 把 `desktop` extra 交接给本 spec。
- `orcakit-harness-agent` 1.0.11 的 `METADATA`（已安装的 dist-info）提供细粒度 extra：`acp`、`all`、`bedrock`、`cli`、`desktop`、`docker`（`docker>=7.0`）、`object-storage`（COS/OBS/OSS）、`observability`（`langfuse>=4.9.0`）、`opensandbox`、`remote-backends`（`deepagents-backends`）、`web-search-all`。`[all]` 是其中 15 项的并集。它还硬依赖 `harness-browser`、`harness-memory`、`pyyaml`。
- `[all]` 中被 Octop 实际用到的只有：`psutil`（内置插件 `infra/agents/plugins/bundled/server-status/main.py` ≈L13 模块级导入，其 `plugin.yaml` 声明 `requires: psutil>=5.9`）、`docker`（`infra/backend/probe.py` ≈L136 与 harness 的 `backends/docker_sandbox.py`）、`langfuse`（`infra/agents/langfuse.py` ≈L153 导入 `harness_agent.observability.langfuse`）。harness 的 `backends/__init__.py::_build_s3`（≈L451-472）在缺 `deepagents_backends` 时回落到自带的 boto3 实现；`_build_postgres`（≈L475-492）必须有 `deepagents_backends`；COS、OSS、OBS 三类后端必须有各自的 SDK（模块名 `qcloud_cos`、`oss2`、`obs`）。ACP 已被 `w1-02` 删除，联网搜索（`langchain_community`、`langchain_tavily`、`googleapiclient` 的唯一用户）已被 `w1-05` 删除。
- `harness-gateway` 0.9.8 的 `METADATA` 硬依赖 `dingtalk-stream`、`discord-py`、`lark-oapi`、`python-telegram-bot`、`wecom-aibot-sdk`。包内对前四者的导入全部在函数内（`channels/feishu.py` ≈L223、`channels/dingtalk.py` ≈L174、`channels/wecom.py` ≈L116、`channels/telegram/channel.py` ≈L94）；`manager.py` ≈L15-24 对各通道配置类的导入在 `TYPE_CHECKING` 块中；`discord` 在包内没有任何导入。`channels/__init__.py` 用 `_CHANNEL_MAP` 惰性加载通道类。
- 在基线锁上模拟"前序 spec 删除 `playwright`、`acme`、`josepy`、`lark-oapi`、`edge-tts` 与 `browser` extra，再加上本设计的依赖改法"后重新 `uv lock`（草稿目录，未改仓库）实测：运行时闭包 157、带两个镜像 extra 178；再扣除 `harness-gateway` 的五个 IM SDK 与其独占依赖 `pycryptodome` 后分别为 **151** 与 **172**。`[tool.uv].environments` 限定 Python 3.12 后锁中包数 242 → 241（去掉仅 3.13+ 需要的 `audioop-lts`），wheel 条目 2482 → 2434。
- wheel 覆盖：锁中 57 个包带平台相关二进制 wheel。按 cp312 + manylinux 复算，所有 Linux 上会安装的包都同时有 `x86_64` 与 `aarch64` wheel；不满足的只有 `pyobjc-*`、`pywin32`（仅 macOS/Windows）与 `audioop-lts`（仅 3.13+）。

### 运行期安装与下载

- `infra/utils/runtime_packages.py`：`build_install_commands`（≈L116-133）生成 `uv pip install` 与 `python -m pip install`，`_extra_fallback_commands`（≈L136-152）生成 `octop[<extra>]` 安装，`install_packages`（≈L204-241）按序执行且都不带 `--index-url`。调用方：`infra/knowledge/ocr.py::ensure_ocr_deps`（规格 ≈L27-29，调用 ≈L90-111）、`infra/agents/providers/onnx_service.py::ensure_local_embedding_deps`（规格 ≈L41-49，≈L87-109；`runtime_pip_allowed()` ≈L53-60 读环境变量 `OCTOP_ALLOW_RUNTIME_PIP`，但管理接口都显式传 `allow_install=True`）、`infra/backend/opensandbox_deps.py::ensure_opensandbox_deps`（≈L9、≈L16-37）。上层入口：`api/routers/knowledge_bases.py` ≈L400、≈L407、≈L495，`api/routers/onnx_models.py` ≈L136，`api/routers/storage_backends.py::_ensure_opensandbox_sdk`（≈L17-25，创建 ≈L106、修改 ≈L133 调用），`infra/agents/manager.py` ≈L2433（Agent 启动）。
- `api/routers/knowledge_bases.py::_map_knowledge_error`（≈L201-226）按异常文本分派：含 `disabled` 映射为 `KNOWLEDGE_FEATURE_DISABLED`，含 `component`、`install` 等映射为 `KNOWLEDGE_PREREQUISITES_FAILED`。因此新异常的消息里不能出现 `disabled`。
- 插件：harness 的 `plugins/loader.py::_install_requires`（第三方包 ≈L29-43）在 `install_deps=True` 且清单有 `requires` 时执行 `python -m pip install`（≈L55）。Octop 以 `install_deps=True` 调用的有三处：`infra/server.py` ≈L310（每次启动）、`api/routers/plugins.py` ≈L116（`/reload`）、`infra/agents/plugins/manager.py` ≈L445（`install_path`）；`PluginManager.load_installed` 默认值也是 `True`（≈L214）。保留的内置插件 `qrcode`、`server-status` 分别声明 `segno`、`psutil`。
- bubblewrap：`infra/utils/bwrap.py` 有五套包管理器（≈L22-30）、`_can_install_without_password`（≈L39-56，`geteuid()==0` 即真）、`_run_install`（≈L57-81）、`_install_argv`（≈L83-119）、`_install_bubblewrap`（≈L121-156），`ensure_bubblewrap`（≈L159-212）在缺 `bwrap` 时安装。`launch.py` 的 `_ensure_linux_bubblewrap` / `_schedule_linux_bubblewrap_ensure`（≈L16-39）在每次 `octop run` 后台调用它（≈L76，关停 ≈L150）。`api/routers/filesystem.py` 的 `POST /ensure-bwrap`（≈L144-157）只要求 `current_user`。
- Docker：`infra/utils/docker_env.py` 的 `_DOCS_BY_PLATFORM`（≈L31-35，`docs.docker.com`）、`_try_auto_install_linux`（≈L157-198）、`install_script`（≈L200，≈L242 输出 `curl -fsSL https://get.docker.com | sudo sh`）、`agent_prompt`（≈L267，≈L310 同样的指引，喂给 LLM）、`docker_status`（≈L332-398）、`ensure_docker = docker_status(attempt_install=True)`（≈L401-403）。`filesystem.py` 的 `POST /ensure-docker`（≈L174-186）同样只要求 `current_user`。前端 `pages/Admin/Storage/DockerEnvFooter.tsx` 仅在 `install_script`、`agent_prompt`、`docs_url` 非空时渲染对应区块。
- `infra/backend/probe.py::_probe_docker`（≈L120）在 ≈L163 调 harness 的 `ensure_docker_image`；该函数（第三方包 `backends/docker_sandbox.py` ≈L129-151）在镜像缺失时 `images.pull`，沙箱创建（≈L380）也调用它。
- 本地模型：`rapidocr` 3.9.2 wheel 自带 `PP-OCRv6_det_small.onnx`、`PP-OCRv6_rec_small.onnx`、`ch_ppocr_mobile_v2.0_cls_mobile.onnx`，`infra/knowledge/ocr.py::_rapidocr_engine`（≈L256-263）无参构造。ONNX 向量模型目录与识别逻辑在 `onnx_service.py` 的 `embedding_models_dir`、`model_cache_dir`（≈L188-196）与 `is_model_downloaded`（≈L257-274，按 `models--<org>--<name>` 目录下是否存在 `*.onnx` 判断）；预置模型为 `onnx_catalog.py::ONNX_PRESET_MODEL_IDS`（≈L7-11）三项，镜像源映射在 `_HF_SOURCE_FALLBACK`（≈L42-55）。`w1-03` 已删除在线下载并让 fastembed 只读本地。

### 前端与文档页

- `dashboard/package.json` 只声明 `@monaco-editor/react ^4.7.0`（≈L25）；锁中 `monaco-editor` 0.55.1 标为 `peer`；`@monaco-editor/loader` 1.7.0 的默认配置为 `paths.vs = 'https://cdn.jsdelivr.net/npm/monaco-editor@0.55.1/min/vs'`；仓库内没有任何 `loader.config(` 调用。两处使用点都是懒加载：`pages/Agent/Workspace/components/CodeEditor.tsx` ≈L19、`pages/Experts/components/FileEditModal.tsx` ≈L10。`monaco-editor` 0.55.1 的 ESM 目录内无 CDN 地址，五个 worker 位于 `esm/vs/editor/editor.worker.js` 与 `esm/vs/language/{json,css,html,typescript}/*.worker.js`。
- `api/app.py`：≈L13 导入 `HTMLResponse`（仅文档路由使用）、≈L14 导入 `get_scalar_api_reference`；`if enable_api_docs:` 分支（≈L278-285）只传 `openapi_url` 与 `title`。`scalar-fastapi` 1.8.2 的默认值为 `scalar_js_url="https://cdn.jsdelivr.net/npm/@scalar/api-reference"`、`scalar_favicon_url="https://fastapi.tiangolo.com/img/favicon.png"`、`with_default_fonts=True`（加载 `fonts.scalar.com`）、`telemetry=True`，另有 `agent` 配置。以 `with_default_fonts=False, telemetry=False, agent=AgentScalarConfig(disabled=True)` 渲染实测，输出的初始化配置为 `{"url": …, "agent": {"disabled": true}, "withDefaultFonts": false, "_integration": "fastapi", "telemetry": false}`，HTML 不含 `jsdelivr` 与 `tiangolo`。
- JWT 中间件只处理以 `/api/` 开头的路径（`api/middleware/jwt_auth.py` ≈L43），`setup_lockdown.py` 同样（≈L29）；`api/deps.py` 的 `_JWT_EXEMPT_EXACT`（≈L73-89）含 `/api/docs` 与 `/api/openapi.json`。
- `@scalar/api-reference` 1.71.0 的 `dist/browser/standalone.js` 为 4 312 689 字节、MIT 许可，内含 `fonts.scalar.com`、`proxy.scalar.com`、`api.scalar.com` 等地址，仅在字体、代理、遥测、Agent 开启时使用。

### 入口脚本与初始化

- `docker/docker-entrypoint.sh`：`set -euo pipefail`（≈L19）；`DB_FILE="${OCTOP_HOME}/octop.db"`（≈L23）；`if [ ! -f "$DB_FILE" ]`（≈L47）为唯一的首次启动判据；首次 `octop init` 在 `if !` 内（≈L55-59），兜底重试（≈L62-66）不在任何保护内；密码以命令行参数传入。
- `cli/commands/init.py`：`~/.octop` 非空且无 `--force` 时 `SystemExit(1)`（≈L63-69）；先播种插件、打开库、执行迁移（≈L78-84），之后才校验口令（≈L103-107）。因此：PostgreSQL 模式永远不会生成 `octop.db`，第二次启动必进初始化分支并因目录非空退出；SQLite 模式下如果首次口令被拒，库已建好，兜底重试同样因目录非空退出。两种情况都在 `set -e` 下直接结束脚本，配合 `restart: unless-stopped` 形成崩溃重启循环。
- `infra/db/repos/users.py::UserRepo.count`（≈L316）可用于判断是否已初始化；`infra/db/rebind.py::assert_control_plane_database_empty`（≈L82-99）是"迁移后数用户"的既有先例。

### 公网域名在仓库中的分布

用附录 A 的黑名单在门禁扫描范围内试扫基线，命中文件共 34 个。其中 27 个属于前序 spec 已删除或已改写的文件（`self_update.py`、`update.ts`、`UpdateConfig.tsx`、SkillHub 与 `skills_hub.py` 相关、`onnx_download.py`、`acme_issue.py`、`preflight.py`、`ollama_manager.py`、`infra/mobile/`、云验证码、`yuanbao_bot_creator.py`、`opencode_session.py`、`voice/adapters.py`）。前序合入后预计剩余：

| 位置 | 域名 | 处置 |
|---|---|---|
| `docker/Dockerfile` | `ghcr.io`、`mirrors.cloud.tencent.com` | 本 spec 任务 13 修复 |
| `docker/docker_build.sh` | `mirrors.cloud.tencent.com` | 本 spec 任务 13 修复 |
| `src/octop/infra/utils/docker_env.py` | `docker.io`、`docs.docker.com`、`get.docker.com` | 本 spec 任务 4 修复 |
| `dashboard/src/assets/providers/index.ts` ≈L79、≈L90、≈L98-108 | `ollama.com`、`modelscope.cn`、`opencode.ai`（供应商文档外链） | 白名单，归 `w4-01` |
| `dashboard/src/components/BackendBuilder.tsx` ≈L196、`pages/Admin/Storage/useStorageBackends.tsx` ≈L121 | `myqcloud.com`（COS 表单占位提示） | 白名单，归 `w4-01` |
| 后端 locale：`errors.PLUGIN_INVALID_ARCHIVE`、`mobile.docker_*` 三键 | `raw.githubusercontent.com`、`get.docker.com`、`download.docker.com`、`docs.docker.com` | 展示文本或孤儿键，按全局约束 1.2 保留，登记白名单 |
| dashboard locale：`apiErrors.PLUGIN_INVALID_ARCHIVE`、`plugins.installUrlHint`、`plugins.installUrlPlaceholder`、`skills.skillhubNotInstalled`、`advancedSettings.update.mirrorSource`（仅 en） | `raw.githubusercontent.com`、`myqcloud.com`、`pypi.org` | 同上 |

### 测试

- `tests/integration/test_scalar.py` 只有 2 个用例，`test_api_docs_endpoint` 断言 200 与 `/api/openapi.json` 出现在页面中。
- `tests/unit/infra/utils/test_bwrap.py`、`tests/unit/infra/utils/test_docker_env.py`、`tests/unit/utils/test_runtime_packages.py`、`tests/unit/backend/test_opensandbox_deps.py` 各有断言"会安装"的用例；`tests/unit/test_launch_bwrap.py` 只测后台调度；`tests/integration/test_filesystem_api.py` 断言 `/ensure-bwrap` 的响应形状。
- `tests/unit/agents/test_onnx_service.py` 以 monkeypatch 替换 `onnx_service.install_packages`，不受本 spec 影响。

## 方案

### 1. 出网静态门禁分两层，白名单三类且防陈旧

- **实现**集中在 `scripts/intranet/public_hosts.py`（仓库脚本，非运行时代码），由 pytest 以 `importlib.util.spec_from_file_location` 加载（与 `tests/unit/test_release_download_links.py` 的做法一致），也可作为命令行在 Dockerfile 与 `Makefile.intranet` 中执行。
- **源码层**：扫描范围与后缀见需求 1.1。构建产物目录 `src/octop/dashboard/` 不在源码层扫描（本地构建过前端时它含 locale 展示文本与 Monaco 默认常量，由产物层按产物规则检查）；随包交付的 Scalar 独立脚本照常扫描，1.71.0 版实测不含黑名单域名。匹配规则：黑名单项作为主机后缀匹配，左边界为文本开头、`.` 或不属于 `[A-Za-z0-9_-]` 的字符，右边界为不属于 `[A-Za-z0-9_-]` 的字符；对形似文件名的条目（`skills.sh`）只匹配 `//skills.sh` 与 `.skills.sh`，避免误伤 `install_skills.sh`。命中后按三类白名单放行：
  - `LOCALE_ALLOWLIST`：`(locale 文件, 键路径, 域名)`，用于展示文本与孤儿键（全局约束 1.2 禁删）；
  - `CODE_ALLOWLIST`：`(相对路径, 域名, 归属 spec, 理由)`，只用于外链与占位提示这类非请求型文本，归属后序 spec 清理；
  - `PENDING_FIXES`：`(相对路径, 域名, 本 spec 任务号)`，只在本 spec 实施期间存在，收尾任务要求为空。
- **防陈旧**：任一白名单条目找不到对应命中即失败，逼迫后序 spec 清理时同步删登记。
- **产物层**：`artifact <目录>` 子命令扫描 `.js`、`.css`、`.html`、`.json`、`.svg`、`.webmanifest`。资源加载类域名（附录 A 第一组）必须为零，唯一例外是 `@monaco-editor/loader` 默认常量的正则 `https://cdn\.jsdelivr\.net/npm/monaco-editor@[0-9.]+/min/vs`（它在本方案下是死值，见第 10 条）；其余黑名单域名只能是 `ARTIFACT_DISPLAY_HOSTS`（由 `dashboard/` 侧白名单派生，单测断言两者相等）。产物层不依赖 locale 文件，因此可在只有 Python 的镜像 runtime 阶段执行。
- **与 `w1-03` 的 token 守卫的关系**：不合并。`w1-03` 的 `tests/unit/test_online_fetch_tokens_removed.py` 还守着非域名 token（`_install_skillhub_cli`、`ollama.pull(` 等），归属清晰；两者对域名有重叠是可接受的冗余。

### 2. 运行期安装：唯一闸口硬关闭

- 在 `install_packages` 入口保留"已满足即返回 `ready`"，其余情况一律抛 `RuntimeInstallDisabledError(RuntimeError)`。所有调用方都已按 `RuntimeError` 处理，错误码映射不变。
- 异常消息写成 `"Required components are not bundled in this build: <包列表>. Runtime installation is not available; rebuild the image with the corresponding extra."`：不含 `disabled`，含 `component` 与 `install`，保证 `_map_knowledge_error` 仍映射为 `KNOWLEDGE_PREREQUISITES_FAILED` 而不是 `KNOWLEDGE_FEATURE_DISABLED`。
- `build_install_commands`、`_extra_fallback_commands` 等内部函数保留不删（上游文件，减少同步冲突），成为不可达代码；这一点写进 `CHANGELOG-intranet.md`。`OCTOP_ALLOW_RUNTIME_PIP` 因此不再生效。
- 插件依赖：三处调用点改为 `install_deps=False`，`load_installed` 的默认值也改为 `False`。插件依赖一律在构建期作为 Octop 的依赖交付（`segno` 已是直接依赖，`psutil` 本 spec 补为直接依赖）；本地安装的第三方插件如缺依赖，加载时报导入错误，由 `PLUGIN_INSTALL_FAILED` 或日志呈现。

### 3. bubblewrap 与 Docker 引擎：只探测，接口形状不变

- `ensure_bubblewrap()` 只保留"非 Linux → `skipped`；`which bwrap` → `ready`；否则 `degraded` + `reason="not_installed"`"三分支，删除五套包管理器与提权判断。`launch.py` 不改：它的后台任务从此只做一次探测并记日志，`tests/unit/test_launch_bwrap.py` 不变。
- `docker_env.py` 删除自动安装、`install_script`、`agent_prompt` 与 `_DOCS_BY_PLATFORM`；`docker_status()` 去掉 `attempt_install` 参数的安装分支，返回的 `install_script`、`agent_prompt`、`docs_url` 固定为空字符串、`can_auto_install` 固定为 `False`；`ensure_docker()` 等价于 `docker_status()`。
- 两个 `POST /api/filesystem/ensure-*` 接口保留、鉴权不变（`w3-03` 统一收口），因为它们已无副作用。前端依赖字段为空时不渲染的既有逻辑，无需改 TypeScript。
- 用户可见文案通过 dashboard overlay 覆盖 `experts.ensureBwrap.degraded`、`storage.dockerEnv.manualDesc`、`storage.dockerEnv.octopDesc`、`storage.dockerEnv.status.missing`，说明"运行期不会自动安装，请联系管理员在镜像或宿主机预置"。

### 4. 模型与镜像：运行期不拉取

- Docker 镜像：在 `orcakit-harness-agent` 内部分支上让 `ensure_docker_image` 在镜像缺失时直接抛 `RuntimeError("Docker image … is not present on the Docker host; pre-load it (docker load / docker pull from the intranet registry) before use")`，不再调用 pull。这一处补丁同时覆盖 Octop 探测（`probe.py` ≈L163）与 harness 沙箱创建（≈L380）两个入口，Octop 侧无需改代码；本仓库用单测以假 Docker 客户端验证探测结果为 `ok: false` 且 `images.pull` 未被调用。
- Hugging Face：镜像设 `HF_HUB_OFFLINE=1` 与 `HF_HUB_DISABLE_TELEMETRY=1`，与 `w1-03` 的 `local_files_only=True` 互为纵深。
- 缓存目录：镜像设 `XDG_CACHE_HOME=/tmp/octop-cache`，让 `huggingface_hub` 等库在只读根文件系统下把缓存写进 tmpfs。
- tiktoken：`langchain-openai` 在少数路径（如 `get_num_tokens_from_messages`）会用 tiktoken，首次使用某编码时从 `openaipublic.blob.core.windows.net` 下载。Octop 与 harness 的主路径使用 `count_tokens_approximately`，未发现必经调用；本 spec 把该域名列入黑名单、由进程内断网用例兜底，并在预置清单中给出"若触发则预置编码文件并设 `TIKTOKEN_CACHE_DIR`"的处置。

### 5. 依赖收敛：精细 extra 取代 `[all]`，SDK 缺失的后端在录入时拒绝

| `[all]` 中的项 | 决定 | 理由 |
|---|---|---|
| `psutil` | 改为 Octop 直接依赖 `psutil>=5.9` | 内置插件 `server-status` 模块级导入；经 `acp` extra 取会连带 ACP |
| `docker` | 保留，经 `[docker]` | Docker 类后端与探测使用；纯 Python；去留随 D6 与 `p2-01` |
| `langfuse` | 保留，经 `[observability]` | 可指向行内自建 Langfuse；默认关闭；去留见"待行方确认" |
| `deepagents-backends` | 不交付 | 仅 `postgres` 类工作区后端必需，并连带 `aioboto3` 一族；S3 类自动回落到 boto3 |
| COS / OSS / OBS 三家 SDK | 不交付 | 公有云；行内对象存储走 S3 兼容（`s3` / `custom` 类，依赖直接依赖 `boto3`） |
| `mss`、`pynput`、`agent-client-protocol`、`langchain-aws`、`langchain-community`、`langchain-tavily`、`google-api-python-client`、`pillow` | 不经 `[all]` 取 | 对应能力已被 `w1-02`、`w1-05` 删除；`pillow` 已是直接依赖 |

- 新增 `src/octop/infra/backend/sdk_availability.py`，维护"后端类型 → SDK 模块名"表：`cos→qcloud_cos`、`oss→oss2`、`obs→obs`、`postgres→deepagents_backends`、`opensandbox→opensandbox`。`storage_backends.py` 的 `_ensure_opensandbox_sdk` 改为通用的 `_ensure_backend_sdk`，SDK 不可导入时抛既有的 `STORAGE_BACKEND_DEPS_FAILED`（503）。这样不删任何后端类型，行方若日后把 SDK 加进镜像即可恢复。已存在的此类后端行在 Agent 启动时仍由 harness 报导入错误，与基线的"缺 SDK"行为一致。
- 删除 `desktop` extra；在 `src/` 中已无导入的残余直接依赖（预计 `lark-oapi`、`edge-tts` 已由 `w1-05` 删除；若仍在且 `rg` 无导入，本 spec 删除）。
- `[tool.uv].environments = ["python_full_version >= '3.12' and python_full_version < '3.13'"]`，放在 `[dependency-groups]` 之前，远离上游在文件尾追加的 mypy 段。它把锁解析与离线同步范围收窄到 3.12，与 `python:3.12-slim` 镜像、CI 的 3.12 一致。不在锁层面限制平台，因为开发机与 Windows CI 仍需安装（见"待行方确认"）。
- 镜像安装 `local-embedding` 与 `knowledge-ocr` 两个 extra；`pymupdf` 的去留由 `w2-02` 决定，本 spec 的 Dockerfile 只按 extra 名安装，extra 内容变化随 `make relock` 自动生效。

### 6. harness-* 内部分支：本地版本号 + 精确固定

- **导入**：四个包各建行内 Git 仓库；第一个提交是对应 sdist 的原样解包（提交说明记录 sdist 文件名与 SHA256）；分支 `intranet/<上游版本>`；补丁以普通提交叠加；标签 `v<上游版本>+intranet.<N>`。
- **版本**：构建时把 `version` 改为 `<上游版本>+intranet.<N>`（PEP 440 本地版本号），发布到行内 PyPI。Octop 的 `pyproject.toml` 以 `==<上游版本>+intranet.<N>` 精确固定，防止私服代理上游 PyPI 时解析到公网版本；`orcakit-harness-agent` 自身对 `harness-memory>=0.9.6`、`harness-browser>=0.7.9` 的约束仍被本地版本满足。
- **补丁清单**（首批）：
  1. `harness-gateway`：`dingtalk-stream`、`lark-oapi`、`python-telegram-bot`、`wecom-aibot-sdk` 从 `dependencies` 移到同名 optional extra（`dingtalk`、`feishu`、`telegram`、`wecom`），删除 `discord-py`；代码不改（导入本就惰性）。`p2-06` 若需要行内 IM 通道，按 extra 机制追加。
  2. `orcakit-harness-agent`：`ensure_docker_image` 不再 pull（见第 4 条）。
  3. `orcakit-harness-agent`：`HarnessAgent._build_tools` 不再注册 `browser_use` 与 `desktop_screenshot`，并删除对 `build_desktop_screenshot_tool` 的导入。合入后删除 `w1-02` 的过渡中和层 `infra/agents/harness_removed_tools.py` 及其在 `server.py::_boot_runtime` 中的调用，并把 `w1-02` 的契约用例替换为"`_build_tools` 源码不含 `browser_use` 与 `build_desktop_screenshot_tool(`"。
  4. `harness-memory`、`harness-browser`：不打补丁，只从源码重建以获得可审计的来源。`harness-browser` 仍是 `orcakit-harness-agent` 的硬依赖、`browser_media.py` 仍在使用，且其依赖全部与其他包共享，移出依赖树只省 1 个包，本 spec 不移出。
- **上游升级流程**（写进 `docs/intranet/offline-build.md`，并在 `w0-04` 的同步手册中引用）：上游提升某个 harness 版本时，先导入新 sdist 为新分支、按提交挑选补丁、构建发布 `+intranet.1`，再在 Octop 同步分支中改固定版本并 `make relock`。
- **子代理遵守 `tools_disabled`**：`w1-02` 把它列在给本 spec 的交接中，但它属于执行面安全策略（全局约束第 3 节把执行面划给 `w3-06`，`w1-02` 自己的范围外表也写明"执行面由 `w3-06` 负责"）。本 spec 交付的是分支、构建与发布流程，该补丁由 `w3-06` 在同一分支上提交。

### 7. 锁文件记录行内私服地址

- 这是 `w0-04` 留给本 spec 的决定：fork 中提交的两份锁文件记录**行内私服 URL**。理由：`uv sync --frozen` 只按锁中 URL 下载；npm 在行内也无法访问锁中的公网地址。上游同步时锁文件冲突一律取上游、再在行内 `make relock`，这已写进 `w0-04` 的同步手册。
- npm 路径前缀兼容：锁在行内 registry 上生成后，`resolved` 的主机与路径前缀都已是行内 registry 本身；`replace-registry-host=always` 只替换主机，而"配置的 registry"与"锁中 registry"相同，替换是恒等的，因此路径前缀型 Nexus 仓库也兼容。`dashboard/.npmrc` 不改（上游刚改过，改它会制造冲突）；所有 fork 入口都显式传 registry：Dockerfile 用 `npm ci --registry`，`make install-frontend` 用 `NPM_REGISTRY`，开发者在 shell 中设 `npm_config_registry`（环境变量优先于项目 `.npmrc`）。行内实测列为任务。
- 凭据：uv 走 netrc，npm 走用户级 `.npmrc` 的 `_authToken`；镜像构建以 BuildKit secret 挂载，锁文件中不出现凭据（`w0-04` 的检查命令）。
- uv 版本：`UV_IMAGE` 的 uv 版本应当与执行 `make relock` 的 uv 版本一致（基线本机为 0.8.17，镜像为 0.7），避免锁格式修订号不兼容。

### 8. 镜像：三个基础镜像参数化、前端固定构建平台、uid 10001、只读可用

- 全局 `ARG NODE_IMAGE`、`ARG PYTHON_IMAGE`、`ARG UV_IMAGE`，均无默认值（缺失即构建失败）。`FROM ${UV_IMAGE} AS uv`，runtime 阶段 `COPY --from=uv /uv /uvx /bin/`（`COPY --from=` 不支持变量，必须经命名阶段）。
- `FROM --platform=$BUILDPLATFORM ${NODE_IMAGE} AS frontend-builder`：前端产物与架构无关，只在构建机原生架构上跑一次，避免 QEMU 下的 Node 构建，也不需要 arm64 的 esbuild/rollup 原生包。
- 前端阶段：`ARG NPM_REGISTRY`（必填），先检查 `package-lock.json` 不含 `registry.npmjs.org`，再 `npm ci --no-audit --registry "$NPM_REGISTRY"`；凭据经 `--mount=type=secret,id=npmrc,target=/root/.npmrc,required=false`。
- runtime 阶段：`ARG APT_DEBIAN_URL`、`ARG APT_SECURITY_URL`（完整 URL，支持路径前缀型 apt 代理），无条件重写 `/etc/apt/sources.list.d/debian.sources`；先检查 `uv.lock` 不含 `files.pythonhosted.org` 与 `pypi.org/simple`；两处 `uv sync --frozen --no-dev --extra local-embedding --extra knowledge-ocr`，netrc 经 `--mount=type=secret,id=netrc,target=/root/.netrc,required=false`；删除 `PIP_INDEX_URL`、`PIP_TRUSTED_HOST`、`UV_INDEX_URL` 相关逻辑与 `COPY .env.example`。
- 产物扫描：复制前端产物后 `COPY scripts/intranet/public_hosts.py /tmp/` 并执行 `artifact`，随后删除脚本。
- 用户：`groupadd --system --gid 10001 octop && useradd --system --uid 10001 --gid 10001 --home-dir /data --no-create-home --shell /usr/sbin/nologin octop`；`/data/.octop` 归 10001 所有；`/app` 保持 root 所有、对 10001 只读；最后 `USER 10001:10001`。
- 环境：在现有 `ENV` 上追加 `HF_HUB_OFFLINE=1`、`HF_HUB_DISABLE_TELEMETRY=1`、`XDG_CACHE_HOME=/tmp/octop-cache`。`PYTHONDONTWRITEBYTECODE=1` 与构建期 `UV_COMPILE_BYTECODE=1` 已保证运行期不写字节码。
- `HEALTHCHECK` 保持 `curl /api/health`（探针拆分归 `p2-08`）。
- `docker/docker_build.sh`：校验 6 个必填变量；`docker buildx build --platform "${PLATFORMS:-linux/amd64,linux/arm64}"`；`PUSH=1` 时 `--push`，否则只允许单平台并 `--load`；`NETRC_FILE`、`NPMRC_FILE` 存在时转为 `--secret`。`Makefile.intranet` 新增 `image` 目标调用它。
- compose：`image: ${OCTOP_IMAGE:-octop:latest}`；新增 `user: "10001:10001"`、`read_only: true`、`tmpfs: [/tmp]`、`cap_drop: [ALL]`、`security_opt: [no-new-privileges:true]`（放在 `environment:` 之前，保持既有解析测试的块结构）；删除 `OPENAI_API_KEY`、`DASHSCOPE_API_KEY` 两行。`docker-compose.postgres.yml` 改为 `image: ${OCTOP_PG_IMAGE:?set OCTOP_PG_IMAGE to the intranet pgvector image}`。

### 9. 入口脚本：`octop init --if-needed` 的退出码契约

| 退出码 | 含义 | 入口脚本动作 |
|---|---|---|
| 0 | 本次完成初始化（迁移、播种插件、创建管理员） | 写 `credential.txt`（600） |
| 3 | 控制面库已有用户，未做任何修改 | 跳过初始化 |
| 4 | 口令未通过策略，未创建用户 | 改用随机强密码重试一次 |
| 2 | Click 用法错误（如与 `--force` 同用） | 以该码退出 |
| 1 | 其他错误（库不可达等） | 以该码退出，交给重启策略 |

- `--if-needed` 模式跳过"目录非空"检查，也不做任何清空；先迁移与数用户，再校验口令，最后才播种插件与建管理员，保证"已初始化"时对 `~/.octop` 零写入。不带该参数时行为与基线完全一致，既有用例不改。
- 入口脚本：先检测 `${OCTOP_HOME:-$HOME/.octop}` 可写（不可写以 78 退出并提示 `chown 10001:10001`）；密码经 `OCTOP_ADMIN_PASSWORD` 环境变量传入（`init.py` 的 Click 选项已声明 `envvar`），不出现在进程参数中；`set -e` 下用 `rc=0; cmd || rc=$?` 捕获退出码。
- `w2-03` 若关闭运行期 DDL，`--if-needed` 在"表不存在"时的行为由其调整（见交接）。

### 10. Monaco：懒加载入口里配置本地实例

- 新增 `dashboard/src/utils/monacoEnvironment.ts`：`import * as monaco from "monaco-editor"`，用 Vite 的 `?worker` 导入五个 worker，设置 `self.MonacoEnvironment.getWorker(_, label)` 按 `json`、`css/scss/less`、`html/handlebars/razor`、`typescript/javascript` 与默认返回对应 worker，并导出 `monaco`。
- 新增 `dashboard/src/utils/monacoLocal.ts`：`loadMonacoEditor()` 并行动态导入 `@monaco-editor/react` 与 `./monacoEnvironment`，调用 `loader.config({ monaco })` 后返回 `{ default: Editor }`。两处使用点把 `lazy(() => import("@monaco-editor/react"))` 改为 `lazy(loadMonacoEditor)`，其余不动。Monaco 因此仍按需加载，不进首屏 chunk；也不需要改 `main.tsx` 或 `vite.config.ts`。
- `loader.config({ monaco })` 之后 `loader.init()` 直接用传入的实例，不再注入 `<script src=…/loader.js>`；`@monaco-editor/loader` 模块里的默认 CDN 常量因此是死值，产物门禁对它做精确例外（第 1 条）。
- `dashboard/package.json` 显式加 `"monaco-editor": "0.55.1"`，与 loader 默认常量中的版本一致。

### 11. Scalar：随包交付独立脚本，由非 `/api` 路径提供

- 新增 `src/octop/api/vendor/scalar/`：`standalone.js`（`@scalar/api-reference` 的 `dist/browser/standalone.js`）、`LICENSE`（取自同一 tarball）、`SOURCE.json`（包名、版本、tarball 的 npm `integrity`、`standalone.js` 的 SHA256）。由新增脚本 `scripts/intranet/vendor_scalar.sh <版本>` 从 `NPM_REGISTRY` 执行 `npm pack` 生成，升级是一次显式提交。选择随仓库交付而不是加 npm 依赖，是因为该包连带数十个运行时依赖进入锁文件，而 Octop 只需要一个静态文件。
- 新增 `src/octop/api/intranet_docs.py::install_api_docs(app)`：注册 `GET /api-docs-assets/scalar.js`（`FileResponse`，`include_in_schema=False`）与 `GET /api/docs`（传 `scalar_js_url="/api-docs-assets/scalar.js"`、`scalar_favicon_url="data:,"`、`with_default_fonts=False`、`telemetry=False`、`agent=AgentScalarConfig(disabled=True)`）。`/api-docs-assets/` 不以 `/api/` 开头，JWT 与 setup 锁定中间件都不处理它，无需改 `deps.py`。`app.py` 的 `if enable_api_docs:` 分支改为一行调用，并从 ≈L13-14 删去 `HTMLResponse` 与 `get_scalar_api_reference` 的导入。两条路由在 SPA 兜底路由之前注册，不会被其吞掉。
- `pyproject.toml` 的 `[tool.hatch.build].include` 增加 `src/octop/api/vendor/**/*`。

### 12. 预置清单

| 资产 | 预置位置 | 来源 | 校验 | 缺失时表现 |
|---|---|---|---|---|
| OCR 模型（检测、识别、方向分类） | 镜像内 `rapidocr` wheel 自带 | 行内 PyPI 私服 | `python -c "import rapidocr, pathlib; print(sorted(p.name for p in (pathlib.Path(rapidocr.__file__).parent/'models').glob('*.onnx')))"` | 不会缺失（随 wheel） |
| ONNX 向量模型：`BAAI/bge-small-zh-v1.5`、`jinaai/jina-embeddings-v2-base-zh`、`intfloat/multilingual-e5-large` | 数据卷 `embedding_models/models--<org>--<name>/` | 摆渡区执行 `scripts/intranet/pack_onnx_models.py` 生成压缩包与 `SHA256SUMS`，行内解压 | `list_downloaded_models()` | 启用时返回"模型未就绪" |
| Ollama 模型 | Ollama 主机本地 | 行内摆渡后 `ollama create` / 拷贝模型目录 | `octop models ollama-list` | 列表中无该模型 |
| Docker 沙箱镜像 | Docker 主机本地 | 行内 Harbor `docker pull` 后由运维预置 | `docker image inspect <镜像>` | 探测返回 `ok: false`，沙箱创建报"请预置镜像" |
| tiktoken 编码文件（按需） | 数据卷，设 `TIKTOKEN_CACHE_DIR` | 摆渡区获取 `cl100k_base`、`o200k_base` | 断网用例不出现 `openaipublic.blob.core.windows.net` | 仅在触发 tiktoken 的路径上报网络错误 |

- `scripts/intranet/pack_onnx_models.py` 沿用基线 `onnx_download.py` 中 `hf_cache_snapshot_dir` 的布局约定（`w1-03` 的交接），但只在摆渡区运行、依赖 `huggingface_hub`，不进镜像。

### 13. 断网验收两层

- **进程内**（进入 `make all`）：`tests/integration/test_airgap_runtime.py` 用夹具替换 `socket.socket.connect`、`socket.socket.connect_ex`、`socket.create_connection`、`socket.getaddrinfo`，非回环目标记录并抛 `OSError`；替换 `subprocess.Popen.__init__` 与 `subprocess.run`，对 `pip`、`uv`、`npm`、`apt`、`apt-get`、`curl`、`wget` 与 `-m pip` 记录并拒绝。然后启动服务、登录管理员，依次请求 `/api/health`、`/api/auth/me`、`/api/agents`、`/api/settings/capabilities`、`/api/settings/timezone`、`/api/docs`、`/api-docs-assets/scalar.js`，调用两个 `ensure-*` 接口与 `launch._ensure_linux_bubblewrap()`，在知识库设置中尝试启用本地 ONNX（依赖缺失时期望映射错误，依赖存在时期望成功），最后断言两个记录列表为空。
- **容器级**（行内人工或流水线执行）：`scripts/intranet/airgap_smoke.sh <镜像>` 创建 `docker network create --internal` 网络，按只读、`--cap-drop ALL` 参数起 SQLite 与 PostgreSQL（`OCTOP_PG_IMAGE`）两组容器，各重启 3 次并检查健康、标记文件与日志，最后检查 `id -u`。

## 组件与接口

| 文件 | 类型 | 改动 |
|---|---|---|
| `scripts/intranet/public_hosts.py` | 新增 | 黑名单、三类白名单、`ARTIFACT_DISPLAY_HOSTS`、`scan_sources()`、`scan_artifact()`、命令行入口 |
| `tests/unit/test_no_public_endpoints.py` | 新增 | 源码门禁、白名单防陈旧、匹配规则自检、产物扫描自检、`ARTIFACT_DISPLAY_HOSTS` 一致性 |
| `src/octop/infra/utils/runtime_packages.py` | 修改 | 新增 `RuntimeInstallDisabledError`；`install_packages` 未满足即抛出 |
| `src/octop/infra/server.py` | 修改 | ≈L310 `install_deps=False`；删除 `w1-02` 中和层的调用（任务 12） |
| `src/octop/api/routers/plugins.py` | 修改 | ≈L116 `install_deps=False` |
| `src/octop/infra/agents/plugins/manager.py` | 修改 | ≈L214 默认值与 ≈L445 调用改为 `False` |
| `src/octop/infra/utils/bwrap.py` | 修改 | 只探测 |
| `src/octop/infra/utils/docker_env.py` | 修改 | 只探测；删安装、脚本、提示词与文档链接 |
| `src/octop/infra/backend/sdk_availability.py` | 新增 | 后端类型到 SDK 模块的映射与可用性判断 |
| `src/octop/api/routers/storage_backends.py` | 修改 | `_ensure_opensandbox_sdk` → `_ensure_backend_sdk` |
| `src/octop/cli/commands/init.py` | 修改 | 新增 `--if-needed` 及其流程 |
| `docker/docker-entrypoint.sh` | 修改 | 重写初始化段与可写检测 |
| `docker/Dockerfile` | 修改 | 见方案第 8 条 |
| `docker/docker_build.sh` | 修改 | `buildx` 双架构与必填校验 |
| `docker/docker-compose.yml`、`docker/docker-compose.postgres.yml` | 修改 | 镜像引用、非 root、只读、删公有云密钥透传 |
| `pyproject.toml` | 修改 | 依赖行、删 `desktop` extra、`[tool.uv]`、hatch include |
| `uv.lock`、`dashboard/package-lock.json` | 重生成 | 行内 `make relock`，单独提交 |
| `dashboard/package.json` | 修改 | `monaco-editor` 精确版本 |
| `dashboard/src/utils/monacoEnvironment.ts`、`monacoLocal.ts`、`monacoLocal.test.ts` | 新增 | 见方案第 10 条 |
| `dashboard/src/pages/Agent/Workspace/components/CodeEditor.tsx`、`dashboard/src/pages/Experts/components/FileEditModal.tsx` | 修改 | 懒加载入口改为 `loadMonacoEditor` |
| `src/octop/api/intranet_docs.py` | 新增 | `install_api_docs(app)` |
| `src/octop/api/app.py` | 修改 | 文档分支改为一行调用；删两处导入 |
| `src/octop/api/vendor/scalar/{standalone.js,LICENSE,SOURCE.json}` | 新增 | 随包交付的 Scalar |
| `scripts/intranet/vendor_scalar.sh` | 新增 | 生成上一行三个文件 |
| `scripts/intranet/pack_onnx_models.py` | 新增 | 摆渡区打包 ONNX 模型 |
| `scripts/intranet/airgap_smoke.sh` | 新增 | 容器级断网冒烟 |
| `Makefile.intranet` | 修改 | 新增 `check-public-hosts`、`build-frontend-intranet`、`image`、`vendor-scalar`、`airgap-smoke`，`help-intranet` 同步 |
| `src/octop/infra/agents/harness_removed_tools.py`、`tests/unit/agents/test_harness_removed_tools.py` | 删除 | 任务 12，条件是内部分支补丁 3 已合入 |
| `src/octop/i18n/intranet/{en,zh}.json`、`dashboard/src/locales/intranet/{en,zh}.json` | 修改 | 覆盖 `errors.STORAGE_BACKEND_DEPS_FAILED` / `apiErrors.STORAGE_BACKEND_DEPS_FAILED` 与方案第 3 条的 4 个键 |
| `docs/intranet/offline-build.md` | 新增 | 构建、运行、预置、门禁维护手册 |
| `CHANGELOG-intranet.md`、`docs/api-intranet.md` | 修改 | 追加本 spec 条目 |
| 测试文件 | 新增/修改 | 见"测试策略" |

关键签名：

```python
# src/octop/infra/utils/runtime_packages.py
class RuntimeInstallDisabledError(RuntimeError):
    """A caller asked to install a package at runtime; intranet builds never do."""

def install_packages(
    spec: PackageInstallSpec | Sequence[str],
    *,
    is_satisfied: Callable[[], bool] | None = None,
    import_modules: Sequence[str] = (),
    timeout: int = INSTALL_TIMEOUT_SEC,
) -> InstallOutcome: ...  # 已满足 → "ready"；否则 raise RuntimeInstallDisabledError

# src/octop/infra/backend/sdk_availability.py
KIND_SDK_MODULES: Final[Mapping[str, str]]  # {"cos": "qcloud_cos", "oss": "oss2", "obs": "obs", "postgres": "deepagents_backends", "opensandbox": "opensandbox"}
def backend_sdk_available(kind: str) -> bool: ...  # 未登记的类型恒为 True

# src/octop/api/routers/storage_backends.py
def _ensure_backend_sdk(kind: str) -> None: ...  # 不可用 → OctopError(ErrorCode.STORAGE_BACKEND_DEPS_FAILED, …)

# src/octop/infra/utils/bwrap.py
def ensure_bubblewrap() -> dict[str, Any]: ...  # {"status": "skipped"|"ready"|"degraded", "reason": …, "detail": …}

# src/octop/infra/utils/docker_env.py
def docker_status(*, attempt_install: bool = False) -> dict[str, Any]: ...  # attempt_install 保留签名、被忽略
def ensure_docker() -> dict[str, Any]: ...  # == docker_status()

# src/octop/cli/commands/init.py
EXIT_ALREADY_INITIALIZED: Final = 3
EXIT_PASSWORD_REJECTED: Final = 4
# @click.option("--if-needed", "if_needed", is_flag=True, default=False, help="Initialize only when the control-plane DB has no users; exit 3 if it already has users.")

# src/octop/api/intranet_docs.py
SCALAR_JS_PATH: Final = "/api-docs-assets/scalar.js"
def install_api_docs(app: FastAPI) -> None: ...

# scripts/intranet/public_hosts.py
def scan_sources(repo_root: Path) -> list[Violation]: ...
def scan_artifact(dist_dir: Path) -> list[Violation]: ...
def main(argv: Sequence[str] | None = None) -> int: ...  # "sources" | "artifact <dir>"
```

```ts
// dashboard/src/utils/monacoLocal.ts
export async function loadMonacoEditor(): Promise<{ default: typeof import("@monaco-editor/react").default }>;
```

## 数据模型

无。本 spec 不写 fork 迁移，不改任何表与 `_schema_version`。

## 配置

`src/octop/config.py` 无新增键，三触点不涉及。以下是构建与部署参数，均不进入 `OctopConfig`：

| 名称 | 所在 | 说明 |
|---|---|---|
| `NODE_IMAGE`、`PYTHON_IMAGE`、`UV_IMAGE` | Dockerfile 全局 `ARG`（必填） | 行内 Harbor 中的完整镜像引用，建议带 `@sha256:` 摘要 |
| `NPM_REGISTRY` | Dockerfile 前端阶段 `ARG`（必填）、`Makefile.intranet` | 行内 npm 私服 |
| `APT_DEBIAN_URL`、`APT_SECURITY_URL` | Dockerfile runtime 阶段 `ARG`（必填） | 行内 apt 代理的完整 URL |
| `PLATFORMS`、`PUSH`、`NETRC_FILE`、`NPMRC_FILE` | `docker/docker_build.sh` 环境变量 | 默认双架构；`PUSH=1` 推送；凭据文件转为 BuildKit secret |
| `OCTOP_IMAGE`、`OCTOP_PG_IMAGE` | compose 插值变量 | 应用镜像与 pgvector 镜像 |
| `HF_HUB_OFFLINE=1`、`HF_HUB_DISABLE_TELEMETRY=1`、`XDG_CACHE_HOME=/tmp/octop-cache` | 镜像 `ENV` | 固定值 |
| `OCTOP_ALLOW_RUNTIME_PIP` | 既有环境变量（`onnx_service.py` 直接读取） | 本 spec 后不再生效，记入 `CHANGELOG-intranet.md` |

## 错误处理

- 不新增 `ErrorCode`，也就不涉及 `_DEFAULT_STATUS`。
- 复用：`STORAGE_BACKEND_DEPS_FAILED`（503）用于存储后端 SDK 不可用；`KNOWLEDGE_PREREQUISITES_FAILED`（409）用于知识库启用本地向量或 OCR 而依赖缺失（经 `_map_knowledge_error` 的文本分派，消息措辞见方案第 2 条）；`onnx_models.py` 既有的 `HTTPException(503, detail=str(exc))` 不变。
- `STORAGE_BACKEND_DEPS_FAILED` 的上游文案是"请检查网络后重试"，在行内会误导，因此在后端与 dashboard 两侧 intranet overlay 中覆盖（en、zh 各一份，overlay 自身对等）；三方相等门禁由 `w0-04` 改为读取合并后的 bundle，不受影响。
- 入口脚本与 `octop init --if-needed` 的退出码见方案第 9 条；数据目录不可写时入口脚本以 78（`EX_CONFIG`）退出。
- 门禁脚本：有违规时退出码 1 并逐行输出 `相对路径: 域名`；参数错误退出码 2。

## 安全考虑

- **消除普通用户触发 root 装包**：基线上任何登录用户调用 `POST /api/filesystem/ensure-bwrap` 或 `/ensure-docker`，服务都可能以 root 执行 `apt-get install`。本 spec 后这两个接口无副作用，且镜像以 uid 10001 运行，即使代码回流也无权装包。
- **最小权限运行**：uid 10001、`/app` 只读、支持只读根文件系统、`cap_drop: [ALL]`、`no-new-privileges`。
- **供应链**：锁文件带哈希且只记录行内地址；harness 四包从可审计的源码构建；Scalar 独立脚本带 `SOURCE.json` 与 SHA256 校验用例；建议基础镜像以摘要固定。镜像不再包含 `.env.example`，compose 不再默认透传公有云模型密钥。
- **凭据**：构建凭据只经 BuildKit secret；入口脚本不再把管理员密码放进进程参数；`credential.txt` 仍为 600。
- **新公开路径**：`/api-docs-assets/scalar.js` 无需令牌，但只在 `enable_api_docs=True` 时注册，内容是公开的静态脚本。
- **待 `w3-01` 处理**：Scalar 页面的内联初始化脚本需要 CSP nonce 或 hash；Monaco worker 由同源脚本 URL 创建，需要 `worker-src 'self'`；`scalar_favicon_url="data:,"` 需要 `img-src data:`。
- **残余**：镜像仍含 `docker` Python SDK，Docker 类后端需要访问 Docker 守护进程，其授权与隔离归 `w3-06` / `p2-01`（D6）。

## 测试策略

| 类别 | 内容 | 本地命令 |
|---|---|---|
| 单测：门禁 | 源码扫描、三类白名单、防陈旧、匹配边界（`install_skills.sh` 不命中、`api.skills.sh` 命中）、产物扫描（含 Monaco 例外、资源加载类为零）、`ARTIFACT_DISPLAY_HOSTS` 一致性 | `uv run pytest tests/unit/test_no_public_endpoints.py -q` |
| 单测：运行期安装 | `install_packages` 未满足即抛且不建子进程；已满足返回 `ready`；消息被 `_map_knowledge_error` 映射为 `KNOWLEDGE_PREREQUISITES_FAILED`；`OCTOP_ALLOW_RUNTIME_PIP=1` 无效；`opensandbox` 依赖缺失即抛 | `uv run pytest tests/unit/utils/test_runtime_packages.py tests/unit/backend/test_opensandbox_deps.py tests/unit/api/test_knowledge_error_mapping_intranet.py -q` |
| 单测：插件 | 启动、`/reload`、`install_path` 均以 `install_deps=False` 调用 harness | `uv run pytest tests/unit/test_plugin_manager.py tests/unit/test_plugins_no_runtime_deps.py -q` |
| 单测：探测 | `ensure_bubblewrap` 三分支且不建子进程；`docker_status` / `ensure_docker` 字段为空与 `can_auto_install=False`；Docker 探测镜像缺失时不 pull | `uv run pytest tests/unit/infra/utils/test_bwrap.py tests/unit/infra/utils/test_docker_env.py tests/unit/test_launch_bwrap.py tests/unit/backend/test_docker_probe_no_pull.py -q` |
| 单测：初始化 | `--if-needed` 的 0 / 3 / 4 / 用法错误；已初始化时 `~/.octop` 文件快照不变 | `uv run pytest tests/unit/cli/test_init_cmd.py -q` |
| 单测：SDK 闸门与预置脚本 | 后端类型到 SDK 的映射与可用性；ONNX 打包产物解压后被 `list_downloaded_models()` 识别 | `uv run pytest tests/unit/backend/test_sdk_availability.py tests/unit/test_pack_onnx_models.py -q` |
| 单测：脚本契约 | Dockerfile、compose、`pyproject.toml`、两份锁、Scalar `SOURCE.json`；入口脚本与 `docker_build.sh` 以假 `octop` / 假 `docker` 驱动（`posix_only`） | `uv run pytest tests/unit/test_offline_build_contract.py tests/unit/test_docker_entrypoint.py tests/unit/test_docker_build_script.py tests/unit/test_docker_compose_database_env.py -q` |
| 集成 | Scalar 页与静态脚本；存储后端 SDK 闸门；`ensure-*` 接口形状；进程内断网 | `uv run pytest tests/integration/test_scalar.py tests/integration/test_storage_backend_sdk_gate.py tests/integration/test_filesystem_api.py tests/integration/test_airgap_runtime.py -q` |
| PG | `octop init --if-needed` 在 PostgreSQL 上的 0 / 3 | `OCTOP_TEST_DATABASE_URL=<专用库 DSN> uv run pytest tests/integration/test_init_if_needed_postgresql.py -q`，或 `make test-postgresql`（`w0-02`） |
| 前端 | `loadMonacoEditor` 以本地实例配置 loader；类型与 lint | `cd dashboard && npx vitest run src/utils/monacoLocal.test.ts`；`make check-frontend` |
| 产物 | 前端构建后产物扫描 | `make build-frontend-intranet NPM_REGISTRY=<行内 npm>` |
| i18n | overlay 对等与三方相等 | `uv run pytest tests/unit/i18n -q` |
| 行内环境 | 锁重生成、双架构镜像、容器冒烟 | `make relock PYPI_INDEX=… NPM_REGISTRY=…`；`PUSH=1 bash docker/docker_build.sh <标签>`；`docker buildx imagetools inspect <标签>`；`bash scripts/intranet/airgap_smoke.sh <标签>` |

新增的 PG 用例同时带 `@requires_postgresql` 与 `@pytest.mark.postgresql`（`w0-02` 约定）；`posix_only` 用例遵守 AGENTS.md §7。

## 与其他 spec 的交接

**依赖（均假设已合入）：**

| spec | 使用的交付物 |
|---|---|
| `w0-01` | `octop init` 路径上的 fork 迁移 runner（`--if-needed` 复用 `init` 的迁移调用） |
| `w0-02` | `Makefile.intranet`（`NPM_REGISTRY`、`install-frontend`、`check-frontend`、`test-postgresql`）；CI 的 frontend job 执行本 spec 的 vitest 用例 |
| `w0-03` | `tests/support/auth.py::bootstrap_admin` 新基线 |
| `w0-04` | 两对 intranet overlay 与读合并 bundle 的三方相等门禁、`make relock`、`CHANGELOG-intranet.md`、`docs/api-intranet.md`、`docs/intranet/`、上游同步手册 |
| `w1-02` | 已删 playwright、`browser` extra 与 Dockerfile 中的 `--extra browser`；过渡中和层 `harness_removed_tools.py`（本 spec 删除） |
| `w1-03` | 已删 ONNX 在线下载、Ollama 拉取、ACME 与 `acme`/`josepy`；fastembed 只读本地；token 守卫 |
| `w1-04` | 已删 `desktop/`、`fnos/`、一键安装脚本、`docker-publish.yml`；已删 `build@0.1.4` 并 relock 一次 |
| `w1-05` | 已删云验证码、在线语音与 `edge-tts`、`opencode_session.py`、元宝、公网 IM 通道与连接器（含 `connectors/gateway/cli_install.py` 的 `npm install -g`）、`lark-oapi` |

**回应前序 spec 留给本 spec 的事项：**

- `w0-04`：锁文件记录行内私服 URL；路径前缀型 npm 镜像兼容性见方案第 7 条，行内实测在任务 11；harness 四包由行内 PyPI 以 `+intranet.N` 提供。
- `w0-02`：`make install-frontend NPM_REGISTRY=…` 的行内实测并入任务 11；`node:20`、`postgres:16` 列入 Harbor 导入清单（`docs/intranet/offline-build.md`）；`vite build` 门禁以 `make build-frontend-intranet` 提供；`pyyaml` 仍由 `orcakit-harness-agent` 硬依赖引入，合同测试的 `yaml` 解析不受影响。
- `w1-02`：内置 `browser_use`、`desktop_screenshot` 由内部分支移除并删除中和层（任务 10.3、12）；`[all]` 已收窄；`harness-browser` 保留（理由见方案第 6 条）；子代理遵守 `tools_disabled` 转交 `w3-06`。
- `w1-03`：预置方式与目录见方案第 12 条；导出逻辑写成 `pack_onnx_models.py`；token 守卫不合并（理由见方案第 1 条）；`ensure_local_embedding_deps(allow_install=True)`、插件 `install_deps=True`、OCR 依赖安装全部由方案第 2 条关闭。
- `w1-04`：`desktop` extra 已删；替代一键安装脚本的行内安装物是本 spec 的镜像与 `docs/intranet/offline-build.md`。
- `w1-05`：若任务 1 发现 `connectors/gateway/cli_install.py` 仍存在，本 spec 在任务 3 中让 `install_connector_cli` 在未安装时直接返回"未随行内版本交付"的失败结果，不再执行 `npm`；若 `lark-oapi`、`edge-tts` 仍在 `pyproject.toml` 且 `src/` 中已无导入，在任务 11 删除。

**交付给：**

| spec | 交付内容 |
|---|---|
| `w2-02-supply-chain-compliance` | SBOM 与 SCA 的输入：行内重生成的两份锁、harness 内部 wheel、`src/octop/api/vendor/scalar/SOURCE.json`；把 `make check-public-hosts`、`make build-frontend-intranet`、`make image`、`make airgap-smoke` 接入行内流水线；`pymupdf` 若移除，需同步处理 `infra/knowledge/ocr.py::local_ocr_deps_available`（当前要求 `pymupdf` 与 `rapidocr` 同时可导入） |
| `w2-03-database-adaptation` | `octop init --if-needed` 的退出码契约；关闭运行期 DDL 后需让它在"表不存在"时以明确退出码结束；新增的库相关环境变量要补进 `docker-compose.yml` 的 `environment` 列表 |
| `w3-01-web-security-baseline` | CSP 需求：Scalar 页内联初始化脚本、`/api-docs-assets/scalar.js`、`data:` 图标、Monaco 同源 worker |
| `w3-06-agent-execution-hardening` | harness 内部分支与发布流程（在其上提交"子代理遵守 `tools_disabled`"补丁）；镜像是否预装 bubblewrap 与容器内 user namespace 权限；Docker 类后端是否保留（决定 `[docker]` extra 去留） |
| `p2-01-agent-sandbox` | Docker 沙箱镜像只能预置、不会自动拉取 |
| `p2-06-intranet-integration` | `harness-gateway` 的 IM SDK extra 机制；行内 IM 通道如需第三方 SDK，按 extra 加入并 relock |
| `p2-08-ha-lease-probes` | `HEALTHCHECK` 仍打 `/api/health`，拆分存活与就绪时一并修改 |
| `w4-01-frontend-baseline` | 清理 `CODE_ALLOWLIST` 中的 5 条（供应商文档外链、COS 表单占位提示），并删除对应白名单登记；`cos`、`oss`、`obs` 在表单中是否隐藏 |
| `w4-02-ops-minimum` | 运维手册引用 `docs/intranet/offline-build.md`；上游 `docker/README*.md`（≈L48-51 仍写腾讯镜像构建参数）与 `docs/agent-backend-file-io.md` ≈L239（仍写自动安装 bubblewrap）的过时描述在手册中说明以 fork 文档为准；旧版以 root 运行的数据卷升级时需 `chown -R 10001:10001` |

**看似相关、但归别的 spec：**

| 事项 | 归属 |
|---|---|
| harness 内置技能中的外发脚本（如 `excalidraw` 上传、`watchers` 访问 GitHub API） | `w3-06`（执行审批）与 `p2-01`（网络隔离） |
| 根 `Makefile` 的 `publish`、`install-online` 等公网发布与联网开发目标 | `w2-02`（对外发布链路） |
| `langfuse` 的默认说明文字 `https://cloud.langfuse.com`（`api/routers/observability.py`、`pages/Settings/Observability/index.tsx`） | `w1-05`（公网 SaaS）；本门禁未列入该域名 |
| PWA、外链清单化、品牌替换、子路径部署 | `w4-01` |
| CI 工作流改写为行内流水线 | `w2-02` |

## 风险与回滚

| 风险 | 影响 | 缓解 |
|---|---|---|
| Monaco 改为完整 ESM 加五个 worker 后构建内存上升 | Docker 前端阶段在 `NODE_MAX_OLD_SPACE_SIZE=2048` 下 OOM | 前端阶段已固定在构建平台原生运行；必要时调高该参数或只保留 `editor`、`json` 两个 worker（其余语言退化为无语言服务的高亮） |
| harness 内部分支的维护成本 | 每次上游提升 harness 版本都要导入新 sdist 并挑选补丁 | 补丁保持少而小（首批 3 个）；流程写入手册；同步节奏沿用全局约束第 5 节的 2-4 个 release 一次 |
| 行内私服代理了上游 PyPI | 未固定时可能解析到公网版本 | 四包以 `==…+intranet.N` 精确固定；契约测试断言锁中版本带 `+intranet.` |
| `make relock` 的 uv 与镜像内 uv 版本不一致 | `uv sync --frozen` 读锁失败 | `UV_IMAGE` 与 relock 使用同一 uv 版本，写入手册 |
| 锁契约测试在非行内检出中失败 | 在公网环境跑 `make all` 会红 | 这是预期：fork 仓库只存在于行内；手册注明 |
| 非 root 后旧数据卷属主为 root | 升级后启动即以 78 退出 | 入口脚本给出明确提示；手册给出 `chown -R 10001:10001` 步骤 |
| 只读根文件系统下还有未知写入点 | 容器启动或功能失败 | `XDG_CACHE_HOME` 指向 tmpfs；容器冒烟脚本以只读参数运行，发现即补 |
| 已有 `cos`/`oss`/`obs`/`postgres` 类后端行 | 相关 Agent 启动失败 | 行为与基线"缺 SDK"一致；手册要求改为 `s3`/`custom` 类后迁移数据 |
| tiktoken 在未覆盖的路径上被调用 | 该路径首次调用时报网络错误 | 黑名单与断网用例兜底；预置清单给出处置 |
| 前序 spec 残留的公网地址 | 门禁在任务 1-2 即红 | 任务 1 实测并按归属处置（本 spec 修、回报前序 owner 或登记） |

**回滚：** 每个顶层任务独立提交，可单独 `git revert`。锁文件提交回滚后在行内重新 `make relock`。harness 内部分支回滚为把 `pyproject.toml` 的固定版本退回上一个 `+intranet.N`。入口脚本与 `--if-needed` 回滚互不依赖（旧脚本不使用新参数）。

## 待行方确认

- **D4（部署形态）**：按默认假设只交付 `linux/amd64` 与 `linux/arm64`。若要求龙芯，`onnxruntime`、`psycopg-binary`、`sqlite-vec` 在 PyPI 上无 sdist，需全量自编译 wheel，不在本 spec 估算内。
- **D6（Agent 命令执行）**：默认保留 `[docker]` extra 与 Docker 类后端。若执行工具整体禁用，可去掉 `docker` 包与 `/api/filesystem/ensure-docker` 相关文案。
- **D9（`desktop/`、`fnos/`）**：按默认假设已由 `w1-04` 删除，本 spec 不改这两处的打包文件。若答复为交付，需另行为 `fnos/docker/Dockerfile` 做同样的行内化与非 root 改造（约 +2 人日）。
- **D13（harness 源码）**：默认可得。若不可得，`harness-gateway` 的五个 IM SDK 无法移出锁文件，需求 6.3 与 7 的相关条目改为"保留并在 SBOM 中说明"，`w1-02` 的中和层长期保留。
- **D2（行内大模型平台含 Embedding）**：若行方不需要本地 ONNX 向量，镜像可不装 `local-embedding`（约少 13 个包）并省去 ONNX 模型预置。
- **新增（steering 未列）**：
  1. 行内是否部署腾讯 TCE、阿里 Apsara Stack、华为 HCS 等私有云，并要求原生 COS/OSS/OBS 接口？默认否（S3 兼容足够）；若是，把对应 SDK 加回镜像即可，闸门自动放行。
  2. 是否保留 Langfuse（`[observability]`，11 个传递依赖）？默认保留并默认关闭。
  3. 开发机与流水线是否存在 Windows？默认存在，因此锁只收窄 Python 版本、不收窄平台；若不存在，可在 `[tool.uv].environments` 中加 `sys_platform == 'linux'`，锁中 wheel 条目约从 2434 降到 1569。
  4. ONNX 向量模型默认放数据卷而非镜像；若要求开箱即用，可把 `BAAI/bge-small-zh-v1.5`（约 0.09 GB）打进镜像。

## 附录 A：域名黑名单

1. **资源加载类**（产物中必须为零）：`jsdelivr.net`、`unpkg.com`、`cdnjs.cloudflare.com`、`fastapi.tiangolo.com`、`fonts.googleapis.com`、`gstatic.com`、`challenges.cloudflare.com`、`hcaptcha.com`、`recaptcha.net`、`google.com/recaptcha`、`turing.captcha.qcloud.com`。
2. **下载与分发类**：`pypi.org`、`pythonhosted.org`、`npmjs.org`、`npmjs.com`、`npmmirror.com`、`yarnpkg.com`、`huggingface.co`、`hf-mirror.com`、`modelscope.cn`、`ollama.com`、`ollama.ai`、`astral.sh`、`get.docker.com`、`download.docker.com`、`docs.docker.com`、`docker.io`、`ghcr.io`、`quay.io`、`rustup.rs`、`mirrors.cloud.tencent.com`、`mirrors.tencent.com`、`mirrors.aliyun.com`、`tuna.tsinghua.edu.cn`、`mirrors.ustc.edu.cn`、`mirrors.163.com`、`mirrors.cernet.edu.cn`、`myqcloud.com`、`openaipublic.blob.core.windows.net`。
3. **平台、市场与探测类**：`ipify.org`、`letsencrypt.org`、`tencentcloudapi.com`、`skillhub.cn`、`clawhub.ai`、`skills.sh`、`skillsmp.com`、`raw.githubusercontent.com`、`api.github.com`、`metadata.tencentyun.com`、`opencode.ai`。

## 附录 B：白名单初始登记

| 类别 | 条目 | 域名 | 归属 / 理由 |
|---|---|---|---|
| `LOCALE_ALLOWLIST` | 后端 en/zh `errors.PLUGIN_INVALID_ARCHIVE`；dashboard en/zh `apiErrors.PLUGIN_INVALID_ARCHIVE`、`plugins.installUrlHint`、`plugins.installUrlPlaceholder` | `raw.githubusercontent.com` | 展示文本或孤儿键，全局约束 1.2 |
| `LOCALE_ALLOWLIST` | 后端 en/zh `mobile.docker_missing_auto_install`、`mobile.docker_source_official`、`mobile.docker_hint_unsupported_distro` | `get.docker.com`、`download.docker.com`、`docs.docker.com` | 孤儿键（远程手机已由 `w1-02` 删除） |
| `LOCALE_ALLOWLIST` | dashboard en/zh `skills.skillhubNotInstalled`；dashboard en `advancedSettings.update.mirrorSource` | `myqcloud.com`、`pypi.org` | 孤儿键（`w1-03`） |
| `CODE_ALLOWLIST` | `dashboard/src/assets/providers/index.ts` | `ollama.com`、`modelscope.cn`、`opencode.ai` | `w4-01`：供应商文档外链 |
| `CODE_ALLOWLIST` | `dashboard/src/components/BackendBuilder.tsx`、`dashboard/src/pages/Admin/Storage/useStorageBackends.tsx` | `myqcloud.com` | `w4-01`：COS 表单占位提示 |
| `PENDING_FIXES` | `docker/Dockerfile`、`docker/docker_build.sh` | `ghcr.io`、`mirrors.cloud.tencent.com` | 本 spec 任务 13 |
| `PENDING_FIXES` | `src/octop/infra/utils/docker_env.py` | `docker.io`、`docs.docker.com`、`get.docker.com` | 本 spec 任务 4 |

`ARTIFACT_DISPLAY_HOSTS` = `raw.githubusercontent.com`、`myqcloud.com`、`pypi.org`、`ollama.com`、`modelscope.cn`、`opencode.ai`。任务 1 按前序实际合入结果修正本表。
