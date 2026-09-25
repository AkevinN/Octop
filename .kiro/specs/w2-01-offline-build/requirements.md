# 需求文档：离线构建与依赖收敛

> spec：`w2-01-offline-build` ｜ 波次：Wave 2 ｜ 基线：`757fd12` ｜ 预估：20 人日
> 前置：`w0-01-fork-migration-namespace`、`w0-02-ci-gates`、`w0-03-test-auth-baseline`、`w0-04-fork-isolation-points`、`w1-02-capability-trim`、`w1-03-online-fetch-trim`、`w1-04-content-trim`、`w1-05-saas-decoupling` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 引言

**结论：** 本 spec 让 Octop 能在只通向行内 Harbor、行内 PyPI 私服、行内 npm 私服与行内 Git 的构建机上一次构建出 `linux/amd64` 与 `linux/arm64` 双架构镜像；镜像以 uid 10001 运行，可在只读根文件系统下启动；进程在启动、登录、打开控制台、保存 Agent 后端、做 OCR 与本地向量检索时都不向任何非回环地址发起连接，也不在运行期安装任何软件包或拉取任何模型、镜像。依赖侧去掉 `orcakit-harness-agent[all]`，改为显式 extra 加一个直接依赖；四个 `harness-*` 包改由行内 Git 内部分支构建，`harness-gateway` 去掉五个公网 IM SDK 的硬依赖；两份锁文件在行内私服用 `make relock` 重生成。入口脚本改为对 SQLite 与 PostgreSQL 都幂等。Monaco 编辑器与 Scalar 文档页改为本地资源。最后用一道源码与构建产物双层的出网静态门禁，加一个进程内断网用例和一个容器级断网冒烟脚本守住结果。本 spec 不新增 `ErrorCode`，不新增 `config.py` 配置键，不写 fork 迁移，不删除任何 i18n 键。

### 背景

以下数字与事实均在基线 `757fd12` 上实测（证据见设计文档"现状"）：

| 项 | 基线实测 | 后果 |
|---|---|---|
| `uv.lock` | 242 个包；`grep -c files.pythonhosted.org` = **2715**；`grep -c 'registry = "https://pypi.org/simple"'` = 241 | `uv sync --frozen` 按锁中记录的 URL 下载，忽略 `UV_INDEX_URL`，行内必然失败 |
| `dashboard/package-lock.json` | `grep -c registry.npmjs.org` = 1125 | 同上 |
| 运行时依赖闭包 | `uv export --frozen --no-dev --no-hashes --no-emit-project \| grep -c '=='` = 203；加 `--extra local-embedding --extra knowledge-ocr` = 223；去掉 `[all]` 可少 49 个，其中含腾讯云、阿里云、华为云、Google、AWS 五家公网 SDK | 离线镜像同步量大、SCA 噪声大 |
| `harness-gateway` 0.9.8 | 硬依赖 `dingtalk-stream`、`discord-py`、`lark-oapi`、`python-telegram-bot`、`wecom-aibot-sdk`；这些 SDK 在包内全部是函数内惰性导入，`discord-py` 在包内无任何导入 | 公网 IM SDK 随镜像交付 |
| `docker/Dockerfile` | 基础镜像 `node:20-slim`、`python:3.12-slim` 与 `ghcr.io/astral-sh/uv:0.7` 写死；无 `USER` 指令；构建参数指向腾讯公网镜像 | 行内拉不到镜像；以 root 运行 |
| 入口脚本 | 以 `~/.octop/octop.db` 是否存在判断首次启动；兜底重试的 `octop init` 不在 `if` 内 | PostgreSQL 模式第二次启动即崩溃重启循环 |
| 运行期安装 | `runtime_packages.install_packages` 用 `uv pip` / `pip` 装 OCR、本地向量、OpenSandbox 依赖；启动时插件加载以 `install_deps=True` 调 `pip install`；启动与 `POST /api/filesystem/ensure-bwrap`（任意登录用户可调）以 root 执行 `apt-get install bubblewrap`；`POST /api/filesystem/ensure-docker` 自动装 Docker | 运行期联网，且普通用户可触发 root 装包 |
| 前端 | `@monaco-editor/loader` 默认从 `cdn.jsdelivr.net` 加载 Monaco；`/api/docs` 默认从 `cdn.jsdelivr.net` 取 Scalar 脚本、从 `fastapi.tiangolo.com` 取图标、从 `fonts.scalar.com` 取字体并开启遥测 | 打开代码编辑器与文档页即外联 |

### 为什么做

1. 行内网完全断外网，构建与运行都只能依赖行内制品库；这是 Wave 2 之后所有 spec 能在行内环境验收的前提。
2. 等保要求安装包中不含未使用的外联组件、服务不以 root 运行、运行期不从外部获取可执行内容。
3. 上游热修 ae43484（基线合入的 #792）刚改过 npm 锁文件的 registry，说明锁文件是上游高频变更点；必须把"取上游、在行内重生成"变成固定流程，并用门禁防止公网地址回流。

### 范围内

1. **出网静态门禁**：`scripts/intranet/public_hosts.py`（域名黑名单、白名单、源码扫描、产物扫描）与 `tests/unit/test_no_public_endpoints.py`；镜像构建期执行产物扫描。
2. **运行期不安装**：`install_packages` 对未安装的包一律拒绝；插件加载的三处 `install_deps=True` 改为 `False`；`ensure_bubblewrap` 与 `ensure_docker` 降级为纯探测；两个 `/api/filesystem/ensure-*` 接口保留、只返回探测结果。
3. **运行期不拉取**：harness 内部分支让 `ensure_docker_image` 不再 `docker pull`；镜像设置 `HF_HUB_OFFLINE=1`；ONNX 模型只读本地（`w1-03` 已改），本 spec 负责预置方式。
4. **存储后端 SDK 可用性闸门**：`cos`、`oss`、`obs`、`postgres`、`opensandbox` 五类后端在 SDK 不可导入时，创建与修改接口返回既有错误码 `STORAGE_BACKEND_DEPS_FAILED`。
5. **依赖收敛**：`orcakit-harness-agent[all]` 改为 `[docker,observability]` 并直接依赖 `psutil`；删 `desktop` extra；删除已无导入的残余直接依赖；锁解析收窄到 Python 3.12；镜像安装 `local-embedding` 与 `knowledge-ocr` 两个 extra。
6. **harness-* 内部分支**：四个包从 sdist 导入行内 Git，构建 `+intranet.N` 本地版本号的纯 Python wheel 并发布到行内 PyPI；`harness-gateway` 把五个 IM SDK 移出硬依赖；`orcakit-harness-agent` 打两个补丁（镜像不自动拉取、移除内置 `browser_use` 与 `desktop_screenshot`）；随后删除 `w1-02` 的过渡中和层。
7. **锁文件行内重生成**：在行内私服执行 `make relock`，两份锁文件只记录行内地址；锁文件单独一个提交。
8. **镜像**：`docker/Dockerfile` 三个基础镜像改为构建参数、apt 与 npm 源改为行内、构建凭据走 BuildKit secret、以 uid 10001 运行、只读根文件系统可用、前端阶段固定在构建平台；`docker/docker_build.sh` 改为 `docker buildx` 双架构；两份 compose 的镜像引用行内化并加非 root 与只读设置。
9. **入口脚本幂等**：`octop init` 新增 `--if-needed`；`docker/docker-entrypoint.sh` 重写。
10. **Monaco 与 Scalar 本地化**：Monaco 改为本地打包并以本地 worker 运行；Scalar 独立脚本随包交付并由 Octop 自身提供。
11. **预置清单**：OCR、ONNX 向量模型、Ollama 模型、Docker 沙箱镜像、tiktoken 编码文件各自的预置方式，以及 ONNX 模型打包脚本。
12. **断网验收**：进程内断网用例 `tests/integration/test_airgap_runtime.py`；容器级冒烟脚本 `scripts/intranet/airgap_smoke.sh`。
13. **记录**：`docs/intranet/offline-build.md`（新增）、`CHANGELOG-intranet.md`、`docs/api-intranet.md`、intranet overlay 文案。

### 范围外（归属）

| 事项 | 归属 |
|---|---|
| 自更新、SkillHub、`skills_hub.py`、专家市场、插件 URL 安装、Ollama 拉取、ONNX 在线下载、Let's Encrypt 与 `api.ipify.org` 的删除 | `w1-03-online-fetch-trim`（已合入；本 spec 只在门禁里防回流） |
| 云验证码、在线语音与 `edge-tts`、`opencode_session.py`、元宝云元数据探测、公网 IM 通道与连接器（含连接器 CLI 的 `npm install -g`）、`lark-oapi` 直接依赖 | `w1-05-saas-decoupling`（已合入；若残留则按设计文档"与其他 spec 的交接"处理） |
| 远程浏览器、远程手机（含 `docker-compose.mobile.yml` 与 Docker 安装脚本）、playwright 直接依赖 | `w1-02-capability-trim`（已合入） |
| `desktop/`、`fnos/`、一键安装脚本、发布与镜像推送类 GitHub 工作流（含 `docker-publish.yml`） | `w1-04-content-trim`（已合入，D9） |
| 许可证、SBOM、SCA、SAST、制品签名，以及把本 spec 的 Make 目标接入行内流水线；`pymupdf`（AGPL）的去留 | `w2-02-supply-chain-compliance` |
| 关闭运行期 DDL、PG 方言、连接池；`octop init --if-needed` 在"运行账号无 DDL 权限"下的行为 | `w2-03-database-adaptation` |
| CSP 与安全响应头（含 Scalar 页的内联脚本、Monaco worker 的 `worker-src`） | `w3-01-web-security-baseline` |
| 子代理遵守 `tools_disabled`（在本 spec 建立的 harness 内部分支上打补丁）、镜像是否预装 bubblewrap、容器内 user namespace 权限 | `w3-06-agent-execution-hardening`（D6） |
| 控制台外链清理（供应商文档链接、存储后端表单中的公有云占位提示）、PWA 下线 | `w4-01-frontend-baseline` |
| 健康检查拆分为存活与就绪、HA | `p2-08-ha-lease-probes`；运维手册 `w4-02-ops-minimum` |
| 删除任何 i18n 键（含变成孤儿的 `mobile.docker_*`、`skills.skillhubNotInstalled` 等） | 全局约束 1.2 禁止，任何 spec 都不做 |

## 需求

### 需求 1：出网静态门禁

**用户故事：** 作为行方安全评审人员，我希望仓库源码与前端构建产物中不出现公网下载、CDN、模型仓库、验证码与遥测类域名，并且上游同步时回流的公网地址会被测试拦下，以便交付物可以通过合规扫描。

#### 验收标准

1. 当执行 `uv run pytest tests/unit/test_no_public_endpoints.py -q` 时，门禁应当扫描 `src/octop`（排除 `src/octop/infra/agents/experts/library/`、`src/octop/infra/agents/subagents/library/` 与构建产物目录 `src/octop/dashboard/`；随包交付的 `src/octop/api/vendor/` 照常扫描）、`dashboard/src`、`dashboard/public`、`dashboard/index.html` 与 `docker/`（排除 `*.md`），对设计文档附录 A 黑名单中每个域名的命中，只要不在白名单登记中，就以"相对路径: 域名"的形式报错并失败；黑名单应当包含 `opencode.ai`。
2. 如果某个 locale JSON（`src/octop/i18n/*.json`、`dashboard/src/locales/*.json` 及其 intranet overlay）中出现黑名单域名，那么只有当该值的键路径登记在 `LOCALE_ALLOWLIST` 中时才放行，否则失败。
3. 如果白名单（`LOCALE_ALLOWLIST`、`CODE_ALLOWLIST`、`PENDING_FIXES`）中的任一条登记已找不到对应命中，那么门禁应当失败并提示删除该条，防止陈旧放行。
4. 当执行 `python scripts/intranet/public_hosts.py artifact <前端产物目录>` 时，产物中"资源加载类"域名（附录 A 第一组）的命中数应当为 0，唯一例外是 `@monaco-editor/loader` 默认常量 `https://cdn.jsdelivr.net/npm/monaco-editor@<版本>/min/vs` 的精确形式；其余黑名单域名只允许是 `ARTIFACT_DISPLAY_HOSTS` 中的展示域名；否则进程退出码非 0。
5. 当在 `docker/Dockerfile` 的 runtime 阶段复制前端产物后，构建应当执行第 4 条的产物扫描，扫描失败则镜像构建失败。
6. 门禁应当始终满足：`ARTIFACT_DISPLAY_HOSTS` 等于 `dashboard/` 侧白名单登记涉及的域名集合，且每条白名单登记都带有归属 spec 与理由（由单测断言）。

### 需求 2：运行期不安装任何软件包

**用户故事：** 作为行方运维人员，我希望服务在运行期绝不调用 `pip`、`uv pip` 或插件依赖安装，缺失的组件给出明确错误，以便镜像内容在交付后保持不变、可审计。

#### 验收标准

1. 当任何调用方经 `octop.infra.utils.runtime_packages.install_packages` 请求一个当前不可导入的包时，函数应当抛出 `RuntimeInstallDisabledError`（`RuntimeError` 的子类），并且不创建任何子进程（单测以替换 `subprocess.run` 为"被调用即失败"的桩验证）。
2. 如果 `is_satisfied()` 返回真，那么 `install_packages` 应当返回 `"ready"`，与基线一致。
3. 当 `OctopServer.start()`、`POST /api/plugins/reload`、`PluginManager.install_path` 加载插件时，Octop 应当以 `install_deps=False` 调用 harness 的插件加载；`rg -n "install_deps=True" src` 应当没有输出。
4. 如果管理员在知识库设置中启用本地 ONNX 向量或本地 OCR、而对应依赖不可导入，那么接口应当返回既有错误（知识库设置返回 `KNOWLEDGE_PREREQUISITES_FAILED`），且不创建子进程。
5. 在设置了 `OCTOP_ALLOW_RUNTIME_PIP=1` 的状态下，`ensure_local_embedding_deps()` 应当仍然不安装任何包（行为同第 1 条）。

### 需求 3：bubblewrap 与 Docker 引擎只探测、不安装

**用户故事：** 作为行方安全评审人员，我希望服务启动与任何 HTTP 接口都不会以 root 身份调用包管理器，以便普通登录用户无法触发主机级安装。

#### 验收标准

1. 当 `ensure_bubblewrap()` 被调用（`octop run` 启动时的后台任务或 `POST /api/filesystem/ensure-bwrap`）时，它应当只依据平台与 `shutil.which("bwrap")` 返回 `skipped`、`ready` 或 `degraded`（`reason` 为 `not_installed`），且不创建任何子进程。
2. 当已登录用户调用 `POST /api/filesystem/ensure-docker` 时，接口应当返回与 `GET /api/filesystem/docker-status` 相同的探测结果，其中 `can_auto_install` 为 `false`，`install_script`、`agent_prompt`、`docs_url` 均为空字符串，且不调用任何包管理器。
3. `rg -n "apt-get|dnf|yum|pacman|zypper|get\.docker\.com|docs\.docker\.com" src/octop/infra/utils/bwrap.py src/octop/infra/utils/docker_env.py` 应当始终没有输出。
4. 如果主机上没有 bubblewrap，那么专家后端保存流程应当照常保存配置，并显示 intranet overlay 中的提示文案（说明运行期不会自动安装、需由管理员预置）。

### 需求 4：运行期不拉取模型与容器镜像

**用户故事：** 作为行方运维人员，我希望 OCR、本地向量、Docker 沙箱在运行期只使用预置在镜像或数据卷中的资产，以便服务行为不依赖任何外部仓库的可用性。

#### 验收标准

1. 当 Docker 类存储后端探测或 Docker 沙箱创建时目标镜像在 Docker 主机上不存在，系统应当返回失败结果（探测返回 `ok: false`，沙箱创建抛出带"请在主机预置镜像"说明的错误），并且不调用 Docker SDK 的 `images.pull` 或 `api.pull`。
2. 在镜像运行期间，环境变量 `HF_HUB_OFFLINE` 应当为 `1`、`HF_HUB_DISABLE_TELEMETRY` 应当为 `1`、`XDG_CACHE_HOME` 应当指向 `/tmp` 下的目录（由 Dockerfile 契约测试断言）。
3. 当本地 OCR 首次构造 `RapidOCR()` 时，引擎应当只使用 `rapidocr` wheel 内自带的三个 ONNX 模型，不发起网络连接（由需求 15 的进程内断网用例在依赖可用时覆盖）。

### 需求 5：存储后端 SDK 可用性闸门

**用户故事：** 作为管理员，我希望选择了行内版未交付的存储后端类型时立即得到明确提示，而不是保存成功后在 Agent 启动时才失败，以便配置错误能在录入时发现。

#### 验收标准

1. 当管理员创建或修改存储后端、`kind` 为 `cos`、`oss`、`obs`、`postgres` 或 `opensandbox`、而对应 SDK 模块（依次为 `qcloud_cos`、`oss2`、`obs`、`deepagents_backends`、`opensandbox`）不可导入时，接口应当返回 503 与 `error.code == "STORAGE_BACKEND_DEPS_FAILED"`，且 `storage_backends` 表中不新增或不修改行。
2. 如果对应 SDK 可导入，那么创建与修改的行为应当与基线一致。
3. 在请求带 `Accept-Language: zh-CN` 时，`STORAGE_BACKEND_DEPS_FAILED` 的 `message` 应当来自 intranet overlay，说明"该存储后端所需组件未随行内版本交付"，且 `uv run pytest tests/unit/i18n -q` 通过。

### 需求 6：Python 依赖收敛

**用户故事：** 作为行方供应链管理人员，我希望运行时依赖只包含实际用到的包，不含任何公有云 SDK、公网 IM SDK 与桌面自动化库，以便离线同步量与 SCA 告警面最小。

#### 验收标准

1. 当检查 `pyproject.toml` 的 `[project].dependencies` 时，`orcakit-harness-agent` 的 extra 应当恰为 `docker,observability`，应当存在直接依赖 `psutil>=5.9`，且不存在 `desktop`、`browser` 两个 optional extra；`[tool.uv].environments` 应当把解析限定在 Python 3.12。
2. 当执行 `uv export --frozen --no-dev --no-hashes --no-emit-project | grep -c '=='` 时，输出应当不大于 155（基线 203）；加 `--extra local-embedding --extra knowledge-ocr` 时应当不大于 175（基线 223）。
3. `uv.lock` 中应当始终不存在以下包：`agent-client-protocol`、`cos-python-sdk-v5`、`oss2`、`aliyun-python-sdk-core`、`aliyun-python-sdk-kms`、`esdk-obs-python`、`langchain-aws`、`aioboto3`、`aiobotocore`、`google-api-python-client`、`langchain-tavily`、`langchain-community`、`deepagents-backends`、`mss`、`pynput`、`dingtalk-stream`、`discord-py`、`python-telegram-bot`、`wecom-aibot-sdk`、`lark-oapi`、`acme`、`josepy`、`playwright`、`edge-tts`（由 `tests/unit/test_offline_build_contract.py` 断言）。
4. 如果某个直接依赖在 `src/` 中已无任何导入（以 `rg` 检索其导入名为准），那么它应当从 `pyproject.toml` 中删除；`boto3`、`segno`、`psutil` 这类仍被导入的包应当保留。
5. 当 `docker/Dockerfile` 执行 `uv sync` 时，应当带 `--extra local-embedding --extra knowledge-ocr`，使 `fastembed` 与 `rapidocr`、`onnxruntime` 随镜像交付。

### 需求 7：harness-* 包由行内 Git 内部分支构建

**用户故事：** 作为行方供应链管理人员，我希望 `orcakit-harness-agent`、`harness-gateway`、`harness-memory`、`harness-browser` 四个包的每一行源码都在行内 Git 可审计、由行内流水线构建，以便对上游第三方包的修改与来源可追溯（D13）。

#### 验收标准

1. 当检查行内 Git 时，四个包应当各有一个从对应 sdist 导入的基线提交（提交说明含 sdist 文件名与 SHA256），以及 `intranet/<上游版本>` 分支与 `v<上游版本>+intranet.<N>` 标签。
2. 当行内流水线构建这四个包时，产物应当是 `py3-none-any` wheel，版本号带 `+intranet.<N>` 本地标签，且 `unzip -l <wheel> | grep -E '\.(so|pyd|dylib)$'` 没有输出。
3. 当检查 `pyproject.toml` 时，四个包应当以 `==<上游版本>+intranet.<N>` 精确固定；`uv.lock` 中这四个包的版本应当带 `+intranet.` 且 wheel 文件名以 `-py3-none-any.whl` 结尾。
4. 当检查内部分支构建出的 `harness-gateway` wheel 的 `METADATA` 时，`Requires-Dist` 中不带 `extra ==` 条件的条目应当不含 `dingtalk-stream`、`discord-py`、`lark-oapi`、`python-telegram-bot`、`wecom-aibot-sdk`；在未安装这五个 SDK 的环境中 `python -c "import harness_gateway, harness_gateway.manager, harness_gateway.channels.mqtt"` 应当成功。
5. 当检查内部分支构建出的 `orcakit-harness-agent` 时，`HarnessAgent._build_tools` 应当不再注册 `browser_use` 与 `desktop_screenshot`，`harness_agent.backends.docker_sandbox.ensure_docker_image` 应当不再调用 pull（满足需求 4.1）。
6. 当上述内部分支版本合入后，`src/octop/infra/agents/harness_removed_tools.py` 及其在 `server.py` 中的调用应当被删除，`uv run pytest tests/unit/agents -q` 通过。

### 需求 8：锁文件在行内私服重生成

**用户故事：** 作为行方构建人员，我希望提交在 fork 中的两份锁文件只记录行内私服地址，以便 `uv sync --frozen` 与 `npm ci` 在断外网的构建机上直接成功。

#### 验收标准

1. 当检查已提交的 `uv.lock` 时，`grep -c files.pythonhosted.org uv.lock` 与 `grep -c 'pypi.org/simple' uv.lock` 应当均为 0（基线 2715 与 241）。
2. 当检查已提交的 `dashboard/package-lock.json` 时，`grep -c registry.npmjs.org dashboard/package-lock.json` 应当为 0（基线 1125）。
3. 当在只能解析行内制品库域名的构建机上执行 `uv sync --frozen --no-dev` 与 `make install-frontend NPM_REGISTRY=<行内 npm>` 时，两者都应当成功，且 `uv sync -v` 日志中出现的下载主机只有行内域名。
4. 当重生成锁文件时，操作应当使用 `make relock PYPI_INDEX=<行内 PyPI> NPM_REGISTRY=<行内 npm>`，锁文件变更应当单独成为一个提交，且 `! rg -n '://[^/@ ]+:[^/@ ]+@' uv.lock dashboard/package-lock.json` 成立（锁中无内嵌凭据）。

### 需求 9：镜像构建来源全行内且产出双架构

**用户故事：** 作为行方构建人员，我希望用一条命令从行内 Harbor 基础镜像构建并推送 amd64 与 arm64 双架构镜像，构建过程不访问任何公网地址，以便镜像能部署到 x86_64 与 ARM 信创服务器（D4）。

#### 验收标准

1. 当检查 `docker/Dockerfile` 时，所有 `FROM` 行应当只引用全局构建参数 `NODE_IMAGE`、`PYTHON_IMAGE`、`UV_IMAGE`（均无默认值），不得出现字面的 `ghcr.io`、`docker.io` 或不带仓库前缀的 `node:`、`python:` 镜像名；uv 可执行文件经命名阶段复制。
2. 如果构建时未提供 `NODE_IMAGE`、`PYTHON_IMAGE`、`UV_IMAGE`、`NPM_REGISTRY`、`APT_DEBIAN_URL`、`APT_SECURITY_URL` 中的任一项，那么 `bash docker/docker_build.sh <标签>` 应当在调用 `docker` 之前以非零退出码结束，并列出缺失项。
3. 当 `uv.lock` 含 `files.pythonhosted.org` 或 `pypi.org/simple`、或 `package-lock.json` 含 `registry.npmjs.org` 时，镜像构建应当在安装依赖之前失败，并提示在行内私服执行 `make relock`。
4. 当执行 `PUSH=1 bash docker/docker_build.sh <行内 Harbor 标签>` 后，`docker buildx imagetools inspect <标签>` 应当同时列出 `linux/amd64` 与 `linux/arm64`；前端构建阶段应当固定在 `$BUILDPLATFORM` 上执行。
5. 当检查 `docker/docker-compose.yml` 与 `docker/docker-compose.postgres.yml` 时，`image:` 应当由环境变量提供（`${OCTOP_IMAGE:-octop:latest}`、`${OCTOP_PG_IMAGE:?…}`），不含 `pgvector/pgvector` 等隐式指向 Docker Hub 的镜像名；`docker-compose.yml` 应当不再透传 `OPENAI_API_KEY` 与 `DASHSCOPE_API_KEY`，且 `tests/unit/test_docker_compose_database_env.py` 保持通过。
6. 构建凭据应当始终只经 BuildKit secret（`--secret id=netrc`、`--secret id=npmrc`）传入，`docker history --no-trunc <镜像>` 与镜像文件系统中不出现凭据。

### 需求 10：以非 root 身份运行并支持只读根文件系统

**用户故事：** 作为行方安全评审人员，我希望容器进程不以 root 运行、根文件系统可设为只读、不需要任何 Linux capability，以便满足等保对最小权限的要求。

#### 验收标准

1. 当执行 `docker run --rm <镜像> id -u` 时，输出应当为 `10001`；Dockerfile 最后一个阶段应当以 `USER 10001:10001` 结束。
2. 当以 `docker run --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges -v <卷>:/data/.octop <镜像>` 启动时，容器应当完成首次初始化，`/api/health` 返回 200。
3. 如果挂载到 `/data/.octop` 的目录对 uid 10001 不可写，那么入口脚本应当在 5 秒内以退出码 78 结束，并在日志中说明需要 `chown 10001:10001` 或设置 `user:`。
4. 镜像应当始终不包含 `.env.example`，`/app` 下文件对 uid 10001 只读，`docker/docker-compose.yml` 应当声明 `user`、`read_only`、`tmpfs`、`cap_drop: [ALL]` 与 `security_opt: [no-new-privileges:true]`。

### 需求 11：入口脚本在 SQLite 与 PostgreSQL 下都幂等

**用户故事：** 作为行方运维人员，我希望容器反复重启不会重复初始化、不会清空数据、不会进入崩溃重启循环，以便冷备切换与日常重启安全（D3、D5）。

#### 验收标准

1. 当执行 `octop init --if-needed --yes --admin-username <u>`（密码经 `OCTOP_ADMIN_PASSWORD` 提供）且控制面库中已有至少一个用户时，命令应当以退出码 3 结束，不修改 `~/.octop` 下任何文件，不创建用户；SQLite 与 PostgreSQL 均成立。
2. 当控制面库可达但没有用户时，`octop init --if-needed` 应当执行迁移、播种内置插件、创建管理员并以退出码 0 结束，即使 `~/.octop` 已非空。
3. 如果 `--if-needed` 模式下管理员密码未通过口令策略，那么命令应当以退出码 4 结束且不创建用户；`--if-needed` 与 `--force` 同时出现时应当以 Click 用法错误结束。
4. 当入口脚本收到退出码 4 时，应当改用随机强密码重试一次；收到 0 时写入 `credential.txt`（权限 600）；收到 3 时跳过初始化；收到其他非零值时以该退出码结束，且不再无条件调用第二次 `octop init`。
5. 当容器分别以 SQLite 与 PostgreSQL 连续 `docker restart` 3 次时，每次都应当进入运行状态且 `/api/health` 返回 200，日志中不出现 `already exists and is not empty`，首次启动后写入 `/data/.octop` 的标记文件在重启后仍在。
6. 入口脚本应当始终经环境变量而非命令行参数把管理员密码传给 `octop init`。

### 需求 12：Monaco 编辑器本地打包

**用户故事：** 作为行内用户，我希望在断网环境中打开工作区代码编辑器与专家文件编辑抽屉时编辑器正常渲染并有语法高亮，以便日常编辑不依赖公网 CDN。

#### 验收标准

1. 当 `CodeEditor` 或 `FileEditModal` 首次渲染编辑器时，前端应当经 `dashboard/src/utils/monacoLocal.ts` 的 `loadMonacoEditor()` 在加载 `@monaco-editor/react` 后调用 `loader.config({ monaco })`，传入的是本地 `monaco-editor` 模块；由 vitest 用例 `dashboard/src/utils/monacoLocal.test.ts` 断言，且断言配置中不含 `cdn.jsdelivr.net`。
2. `dashboard/package.json` 应当始终把 `monaco-editor` 声明为精确版本的直接依赖（与锁中 `@monaco-editor/loader` 默认常量的版本一致）。
3. 在只允许访问自身的浏览器环境中打开上述两个编辑器时，Network 面板应当只出现与页面同源的请求（含 worker 脚本）。
4. 当执行 `cd dashboard && npx tsc -b && npm run lint && npm run test` 时，全部通过；`monaco-editor` 不进入首屏入口 chunk（编辑器仍为按需加载）。

### 需求 13：Scalar API 文档页本地化

**用户故事：** 作为运维与测评人员，我希望开启 API 文档后 `/api/docs` 页面所需的脚本、图标、字体都由 Octop 自身提供且不开启遥测，以便在断网环境中查看接口文档。

#### 验收标准

1. 当 `enable_api_docs=True` 并请求 `GET /api/docs` 时，返回的 HTML 中应当不含 `cdn.jsdelivr.net`、`fastapi.tiangolo.com`，应当引用 `/api-docs-assets/scalar.js`，并在配置中带 `"withDefaultFonts": false`、`"telemetry": false` 与禁用 Agent 的设置；由 `tests/integration/test_scalar.py` 断言。
2. 当请求 `GET /api-docs-assets/scalar.js` 时，未带令牌也应当返回 200、`content-type` 为 JavaScript，内容的 SHA256 等于 `src/octop/api/vendor/scalar/SOURCE.json` 中登记的值。
3. 如果 `enable_api_docs=False`，那么 `/api/docs` 与 `/api-docs-assets/scalar.js` 都不应当注册（404）。
4. 构建出的 wheel 应当始终包含 `octop/api/vendor/scalar/standalone.js` 与其 `LICENSE`。

### 需求 14：运行期资产预置清单

**用户故事：** 作为行方运维人员，我希望有一份明确的清单告诉我哪些模型与镜像必须在构建期或部署期预置、放在哪里、如何校验，以便功能在断网环境中完整可用。

#### 验收标准

1. 当查阅 `docs/intranet/offline-build.md` 时，应当有一张预置清单表，逐项列出 OCR 模型、ONNX 向量模型（`ONNX_PRESET_MODEL_IDS` 的三个模型）、Ollama 模型、Docker 沙箱镜像、tiktoken 编码文件的预置位置、来源、校验命令与缺失时的表现。
2. 当在可联网的摆渡区执行 `uv run --extra local-embedding python scripts/intranet/pack_onnx_models.py --out <目录>` 时，脚本应当为每个预置模型生成 Hugging Face 缓存布局（`models--<org>--<name>/`，含 `refs/main` 与 `snapshots/`）的压缩包与 `SHA256SUMS`。
3. 当把压缩包解到数据卷的 `embedding_models/` 后，`OCTOP_HOME=<目录> uv run python -c "from octop.infra.agents.providers.onnx_service import list_downloaded_models; print(list_downloaded_models())"` 应当列出对应模型。

### 需求 15：断网运行验收

**用户故事：** 作为行方测评人员，我希望有可重复执行的用例证明服务在启动、登录、浏览主要页面、保存 Agent 后端时不对外连接、不启动安装进程，以便把"断网可用"作为回归门禁。

#### 验收标准

1. 当执行 `uv run pytest tests/integration/test_airgap_runtime.py -q` 时，用例应当在拦截全部非回环 `socket` 连接与非本地域名解析、拦截 `pip`/`uv pip`/`npm`/`apt-get`/`curl`/`wget` 子进程的前提下，完成服务启动、管理员登录、依次请求设计文档列出的控制台接口、调用两个 `/api/filesystem/ensure-*` 接口与 `launch._ensure_linux_bubblewrap()`，并断言被拦截的连接与子进程列表均为空。
2. 当在行内执行 `bash scripts/intranet/airgap_smoke.sh <镜像>` 时，脚本应当在 `--internal`（无出口）Docker 网络中按需求 10.2 的参数分别以 SQLite 与 PostgreSQL 完成需求 11.5 的重启验证，并检查 `id -u` 为 10001，全部通过时退出码为 0。
3. 在控制台首屏、工作区代码编辑器、专家、技能、应用设置、登录页、`/api/docs` 页面加载期间，浏览器应当不向第三方域名发起请求（人工验收，结果记录进 `docs/intranet/offline-build.md`）。

### 需求 16：记录

**用户故事：** 作为后续 spec 的实施者与上游同步负责人，我希望本 spec 的行为变化、构建步骤与维护规则有文档可查，以便同步上游时知道哪些文件要在行内重新生成。

#### 验收标准

1. 当本 spec 合入后，`CHANGELOG-intranet.md` 应当有本 spec 条目，列出：运行期安装全部关闭、`OCTOP_ALLOW_RUNTIME_PIP` 不再生效、`ensure-*` 接口改为只探测、`octop init --if-needed`、镜像以 uid 10001 运行、依赖收敛结果与锁文件记录行内地址。
2. 当本 spec 合入后，`docs/api-intranet.md` 应当记录 `POST /api/filesystem/ensure-bwrap`、`POST /api/filesystem/ensure-docker`、存储后端创建与修改、`/api/docs` 与 `/api-docs-assets/scalar.js` 的变化。
3. `docs/intranet/offline-build.md` 应当始终包含：基线实测数字、构建前置清单、harness 内部分支流程、`make relock` 流程、镜像构建与运行参数、预置清单、门禁白名单维护规则。
4. 本 spec 新增或覆盖的界面文案应当只写进 intranet overlay（`src/octop/i18n/intranet/{en,zh}.json`、`dashboard/src/locales/intranet/{en,zh}.json`），上游四份 locale JSON 不增不删键。
