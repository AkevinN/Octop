# 需求文档：外网获取类功能裁剪

> spec：`w1-03-online-fetch-trim` ｜ 波次：Wave 1 ｜ 基线：`757fd12` ｜ 预估：18 人日
> 前置：`w0-01-fork-migration-namespace`、`w0-02-ci-gates`、`w0-03-test-auth-baseline`、`w0-04-fork-isolation-points`、`w1-02-capability-trim` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 引言

**结论：** 本 spec 物理删除面向用户的七类"运行期从外网获取东西"的功能：自更新与版本检查、SkillHub 技能市场（含 `curl | bash` 安装器）、`skills_hub.py` 这套 URL 导入市场、专家市场、插件的 URL 安装 / 上传 / 市场页、Ollama 在线拉模型与 ONNX 在线下载、Let's Encrypt 签发与 `api.ipify.org` 公网 IP 探测。只有两项能力在删除后以离线方式补回：一是服务重启（从 `update` 路由迁到 fork 自有的 `service_control` 路由，权限键 `update` 同步更名为 `service_control` 并清洗存量），二是 HTTPS（由"在线签发"改为"上传行内 CA 签发的证书"）。本 spec 新增 1 个 `ErrorCode`（`TLS_CERT_INVALID`）、1 个权限键（`service_control`，替换 `update`）、1 对 fork 迁移，不新增配置键，不删除任何 i18n 键。

### 背景

以下事实在基线 `757fd12` 上核实（证据见设计文档"现状"）：

| 功能 | 基线行为 | 在行内网的后果 |
|---|---|---|
| 版本检查 | 任何已登录用户打开控制台，`PwaUpdatePrompt` 与 `useUpdateStatus` 就会调 `GET /api/update/status`，缓存失效时后端调 `fetch_pypi_info()` 访问 `pypi.org` | 每次登录都产生一条外联，合规扫描必记 |
| 自更新 | `POST /api/update/upgrade` 与 `octop update` 在运行期 `pip install` 新版本，候选源含腾讯、阿里、清华、中科大四个公网镜像 | 断网必失败；绕过行内制品发布流程 |
| SkillHub | 本机缺 `skillhub` CLI 时，`skills.py` 用 `curl -fsSL <腾讯云 COS 上的 install.sh> \| bash` 在服务器上现装 | 从公网拉脚本并以服务身份执行 |
| URL 导入 | `skills_hub.py`（1493 行）直连 `clawhub.ai`、`skills.sh`、`skillsmp.com`、GitHub | 断网失败；且是一条可被诱导的出网通道 |
| 专家市场 | `/api/experts/hub*` 从 `api.skillhub.cn` 拉专家模板 | 同上 |
| 插件 | `POST /api/plugins/install` 按 URL 下载 ZIP（GitHub 链接改写到 `raw.githubusercontent.com`）；`POST /api/plugins/upload` 允许控制台上传可执行插件 | 外联；控制台上传即服务器端代码执行 |
| 模型 | Ollama `pull`、ONNX 三源竞速下载（腾讯云 COS / Hugging Face / hf-mirror），另有 `PUT /api/onnx-models/config` 在模型缺失时默认自动下载 | 断网失败；模型来源不可审计 |
| TLS | Let's Encrypt HTTP-01 签发与每日自动续期；预检访问 `api.ipify.org` | 行内不可能用公网 CA；外联 |

### 为什么做

1. 全局约束 1.5"先删后改"：这些功能删掉后，`w3-01` 的上传入口清单少一个（插件上传），`w3-06` 不必再为 `curl | bash` 安装器与插件上传设计执行面控制。
2. 保留它们、只加开关，会在代码里留下几千行出网代码与公网域名，`w2-01` 的出网静态门禁无法收紧。
3. 行内的软件、技能、插件、模型、证书都应经行内制品流程进入，而不是由运行中的服务自己去拉。

### 范围内

1. **自更新与版本检查**：删 `infra/setup/self_update.py`、`api/routers/update.py`、`api/routers/update_store.py`、`cli/commands/update.py` 及其注册；前端删升级页、"有新版本"角标、侧栏红点、头像菜单"检查更新"、相关 hook 与缓存。
2. **服务重启迁移**：新增 fork 自有的 `api/routers/service_control.py`，提供 `GET /api/service/status`（版本号与服务模式，不联网）与 `POST /api/service/restart`（逻辑原样迁移）；权限键 `update` 更名为 `service_control`，写一对 fork 迁移清洗 `users.permissions` 存量值并删掉 `update.stable_only` 设置行。
3. **SkillHub 技能市场**：删 7 个 SkillHub 端点（Agent 侧 3 个 `/skills/hub/*`，技能包侧 `hub/search`、`hub/rankings`、`from-skillhub`、`{package_id}/skills/hub/install` 4 个）、`curl | bash` 安装器、`infra/skills/skillhub_market.py`、`infra/skills/skill_package_from_skillhub.py`；内置 `skill-manager` 技能去掉 SkillHub 来源。
4. **URL 导入**：删 `infra/skills/skills_hub.py` 与两个 `/skills/import` 端点；导入弹窗只留本地 ZIP。
5. **专家市场**：删 3 个 `/experts/hub*` 端点、`infra/agents/experts/skillhub_market.py`、`market_creation.py`；前端删市场标签页、市场 API 模块与"从专家市场建技能集"抽屉。本地已缓存的市场专家继续可解析。
6. **插件**：删 URL 安装、控制台上传与市场标签页；CLI `octop plugin install` 改为接受本地目录或本地 `.zip`。
7. **模型**：删 Ollama 拉取的 3 个端点、`pull_model` 与 `octop models ollama-pull`；删 ONNX 的 4 个下载端点、`onnx_download.py` 与 `PUT /api/onnx-models/config` 的自动下载分支；fastembed 推理强制 `local_files_only=True`。
8. **TLS**：删 ACME 签发、挑战路由、自动续期、预检（含 `api.ipify.org`）与 `acme`、`josepy` 依赖；新增 `POST /api/admin/tls/certificate` 上传行内证书；HTTPS 设置页改为上传表单。
9. **守卫**：两个 fork 自有测试，分别守住"本 spec 删掉的外网 token 不回流"和"本 spec 删掉的路由不回流"。
10. **记录**：`CHANGELOG-intranet.md`、`docs/api-intranet.md`。

### 范围外（归属）

| 事项 | 归属 |
|---|---|
| 启动时自动安装 bubblewrap / Docker（`launch.py::_schedule_linux_bubblewrap_ensure`、`infra/utils/bwrap.py`、`infra/utils/docker_env.py`、`/api/filesystem/ensure-*`）；`backend/probe.py` 拉 Docker 镜像 | `w2-01-offline-build` |
| 运行期 `pip` / `npm` 装包（`infra/utils/runtime_packages.py`、`ensure_local_embedding_deps(allow_install=True)`、OCR 依赖、插件 `install_deps`、连接器 CLI 的 `npm install -g`） | `w2-01-offline-build` |
| 模型离线预置的方式与目录布局、镜像与 lock、`[all]` 收窄、Monaco 与 Scalar 本地化、入口脚本幂等、全量出网静态门禁 `test_no_public_endpoints.py` | `w2-01-offline-build` |
| 在线安装 Chromium（`api/routers/browser/env.py` 的 `/browser/install`）、远程手机的 Docker 安装脚本 | `w1-02-capability-trim`（随远程浏览器 / 远程手机下线） |
| 云验证码 provider（Turnstile、hCaptcha、reCAPTCHA、腾讯）；联网搜索路由；元宝通道的云元数据探测 | `w1-05-saas-decoupling` |
| `desktop/`、`fnos/`、GitHub 工作流（D9），以及 `scripts/install*` 一键安装脚本等非交付工程 | `w1-04-content-trim`；行内离线安装方式由 `w2-01-offline-build` 承接 |
| 控制台外链（`AvatarDropdown.tsx` 的 GitHub 与文档链接、`assets/providers/index.ts` 的供应商文档链接、远程 `icon_url` 渲染）、PWA 下线（含删除 `PwaUpdatePrompt`） | `w4-01-frontend-baseline` |
| 中间件与安全响应头对 80 端口伴随应用的覆盖 | `w3-01-web-security-baseline`（本 spec 让上传模式下伴随应用默认不启动） |
| 私钥落盘加密、国密证书（SM2） | `w3-05-credential-encryption`、`p2-02-kms-sm-crypto`（D8） |
| 删除任何 i18n 键（含变成孤儿的 `errors.SKILLHUB_SSL_FAILED`、`tls.preflight.*`、`advancedSettings.update.*`） | 全局约束 1.2 禁止，任何 spec 都不做 |

## 需求

### 需求 1：自更新与版本检查链路下线

**用户故事：** 作为行方安全管理员，我希望控制台与服务端不再自行检查或安装新版本，以便登录与日常使用不产生任何指向 PyPI 的外联，版本升级只走行内镜像发布流程。

#### 验收标准

1. 当任一已登录用户加载控制台任意页面时，dashboard 应当不再请求任何 `/api/update/` 路径，`src/octop` 与 `dashboard/src` 中也不再出现 `pypi.org`、`mirrors.cloud.tencent.com`、`pypi.tuna.tsinghua.edu.cn`、`mirrors.ustc.edu.cn`。
2. `build_app` 生成的路由表与 `/api/openapi.json` 应当始终不含 `/api/update/status`、`/api/update/check`、`/api/update/settings`、`/api/update/upgrade`、`/api/update/progress`、`/api/update/restart`。
3. 当运维执行 `octop --help` 时，命令列表应当不含 `update`；执行 `octop update` 时，命令应当以非零退出码结束且不发起网络请求。
4. 控制台应当始终不再渲染"有新版本"角标、侧栏"应用设置"红点、头像菜单的"检查更新"项与应用设置的"检查更新"标签页；访问 `/admin/advanced?tab=updates` 时应当显示应用设置的默认标签页。
5. 当任一已登录用户查看页头或侧栏时，`CurrentVersionBadge` 应当显示 `v<当前版本>`，数据来自 `GET /api/service/status`，且不再提供点击跳转。

### 需求 2：服务状态与服务重启迁移到 service_control

**用户故事：** 作为系统管理员，我希望在上传 HTTPS 证书后仍能从控制台重启服务，以便删除自更新不连带删掉这个纯本地的运维操作。

#### 验收标准

1. 当持 `service_control` 权限的用户在系统服务模式（`OCTOP_SERVICE_MODE` 为 `systemd` 或 `launchd` 且服务已安装）下调用 `POST /api/service/restart` 时，接口应当返回 `{"status": "restarting", "service_mode": <mode>}` 并在后台重启；desktop 进程返回 `service_mode == "desktop"`。两者与基线 `POST /api/update/restart` 的行为一致。
2. 如果调用者既不是管理员也不持 `service_control`，那么 `POST /api/service/restart` 应当返回 403 且 `error.code == "FORBIDDEN"`。
3. 如果进程既不是系统服务也不是 desktop 进程，那么 `POST /api/service/restart` 应当返回 403 `FORBIDDEN`，与基线一致。
4. 当任一已登录用户调用 `GET /api/service/status` 时，接口应当返回 `current_version`、`service_mode`、`desktop` 三个字段且不发起任何网络请求；`current_version` 等于 `importlib.metadata.version("octop")`；未登录时返回 401。
5. dashboard 的全局重启流程（`useServiceRestart`，由 HTTPS 设置页的"重启服务"按钮触发）、HTTPS 设置页的服务模式探测与 PWA 更新提示应当始终经新的 `serviceApi` 调用 `/api/service/*`；`dashboard/src` 中不再出现字符串 `/update/`。

### 需求 3：权限键 update 更名为 service_control 并清洗存量

**用户故事：** 作为管理员，我希望权限清单里不再出现已不存在的"应用更新"，而原来持有它的用户继续能重启服务，以便权限语义与功能一致，且编辑老用户不报错。

#### 验收标准

1. `src/octop/infra/users/permissions.py` 的 `PERMISSIONS` 应当始终不含 `update`、含 `service_control`（category 为 `admin`，page 为 `advanced`）；`GET /api/users/permissions` 的返回随之变化。
2. 当 fork 迁移 `forkNNN_service_control_permission` 执行时，每个 `users.permissions` 含 `update` 的用户应当把 `update` 换成 `service_control`（去重，其余键及其顺序不变），不含 `update` 的用户应当保持不变；`settings` 表中键为 `update.stable_only` 的行应当被删除。
3. 如果目标库缺少 `users` 或 `settings` 表，那么迁移步骤应当跳过缺失的表，并照常推进 `_fork_schema_version` 水位。
4. 当管理员编辑一位迁移前持有 `update` 键的存量用户时，`PATCH /api/users/{id}` 应当返回 200，读回的 `permissions` 含 `service_control`、不含 `update`。
5. 迁移步骤应当始终幂等（重复执行结果不变），且在 SQLite 与 PostgreSQL 上结果一致。
6. `tests/unit/api/test_acl_gate_coverage.py` 的 `GATED_FILES` 应当始终包含 `routers/service_control.py`、不含 `routers/update.py`，且该测试通过。

### 需求 4：SkillHub 技能市场与 curl | bash 安装器下线

**用户故事：** 作为行方安全管理员，我希望服务器永远不会从公网下载并执行安装脚本，以便消除以服务身份执行外部代码的供应链风险。

#### 验收标准

1. 路由表应当始终不含 `/api/agents/{agent_id}/skills/hub/search`、`/api/agents/{agent_id}/skills/hub/rankings`、`/api/agents/{agent_id}/skills/hub/install`、`/api/skill-packages/hub/search`、`/api/skill-packages/hub/rankings`、`/api/skill-packages/from-skillhub`、`/api/skill-packages/{package_id}/skills/hub/install`。
2. `src/octop` 中应当始终不含 `skillhub.cn`、`skillhub-1388575217`、`_install_skillhub_cli`；`src/octop/infra/skills/skillhub_market.py` 与 `src/octop/infra/skills/skill_package_from_skillhub.py` 应当不存在。
3. 当 Agent 执行内置 `skill-manager` 技能时，其 `SKILL.md` 与 `scripts/manage_skills.py` 应当不再提供 SkillHub 来源与 `skillhub-search` 子命令；如果来源参数是 `skillhub:<slug>` 或 `https://skillhub.cn/...`，那么脚本应当按普通来源处理并报错，且不调用任何 `skillhub` 可执行文件。
4. 在已通过 SkillHub 安装过技能的实例上，这些技能应当仍可被列出、查看、启停与删除；frontmatter 中的 `metadata.octop.source: skillhub` 不影响本地操作。
5. 控制台的 Agent 技能页与技能包页应当始终不再出现 SkillHub 标签页、市场弹窗与"从 SkillHub 创建"入口。

### 需求 5：URL 导入下线

**用户故事：** 作为行方安全管理员，我希望技能只能通过本地 ZIP 进入系统，以便技能来源可审计、服务端不存在按用户输入去访问公网的通道。

#### 验收标准

1. 路由表应当始终不含 `POST /api/agents/{agent_id}/skills/import` 与 `POST /api/skill-packages/{package_id}/skills/import`。
2. `src/octop/infra/skills/skills_hub.py` 应当不存在；`src/octop` 与 `dashboard/src` 中应当始终不含 `clawhub.ai`、`https://skills.sh`、`skillsmp.com`、`api.github.com`。
3. 当用户打开"导入技能"弹窗时，弹窗应当只提供本地 ZIP 导入，ZIP 导入的行为与基线一致。
4. `import octop.infra.skills` 应当始终成功，且其 `__all__` 中的每个名字都能从该包取到。

### 需求 6：专家市场下线

**用户故事：** 作为行方安全管理员，我希望专家模板只来自随包内置的专家库与本行发布的模板，以便控制台不再访问 SkillHub。

#### 验收标准

1. 路由表应当始终不含 `GET /api/experts/hub`、`GET /api/experts/hub/{slug}`、`POST /api/experts/hub/{slug}/install`；`src/octop/infra/agents/experts/skillhub_market.py` 与 `src/octop/infra/agents/experts/market_creation.py` 应当不存在。
2. 专家页应当只保留"我的"与"专家库"两个标签页，创建抽屉不再有市场来源；技能包页不再有"从专家市场建技能集"抽屉；`dashboard/src/api/modules/expertMarket.ts` 应当不存在。
3. 在 `~/.octop/expert_market/` 下存在市场专家缓存的实例上，`GET /api/experts/{expert_id}` 对缓存中的专家 id 应当返回与基线相同的结果，由这些专家创建的既有 Agent 应当仍能启动。

### 需求 7：插件 URL 安装、上传与插件市场下线

**用户故事：** 作为行方安全管理员，我希望插件只能随镜像预置或由有主机权限的运维离线安装，以便控制台不再是下载或上传可执行代码的入口。

#### 验收标准

1. 路由表应当始终不含 `POST /api/plugins/install` 与 `POST /api/plugins/upload`；插件的列表、重载、启停、卸载、UI 资源与 Agent 插件接口保持不变。
2. `PluginManager` 应当不再有 `install_url`，`infra/agents/plugins/manager.py` 应当不再有 `normalize_plugin_download_url`；`src/octop` 中应当始终不含 `raw.githubusercontent.com`。
3. 当运维执行 `octop plugin install <本地目录>` 或 `octop plugin install <本地 .zip 文件>` 时，插件应当安装成功；如果参数以 `http://` 或 `https://` 开头，那么命令应当以非零退出码结束且不发起网络请求。
4. 插件管理页应当只有"已安装"标签页，且不再提供 URL 安装与上传按钮；访问 `?tab=market` 时应当显示"已安装"。

### 需求 8：Ollama 在线拉模型下线

**用户故事：** 作为运维，我希望 Ollama 模型由我在 Ollama 主机上预置，以便 Octop 不会驱动 Ollama 守护进程去公网注册表拉模型。

#### 验收标准

1. 路由表应当始终不含 `POST /api/ollama-models/download`、`GET /api/ollama-models/download-status`、`DELETE /api/ollama-models/download/{task_id}`；列举、删除与服务开关接口保持不变。
2. `OllamaModelManager` 应当不再有 `pull_model`；`octop models --help` 应当不含 `ollama-pull`；`src/octop` 中应当始终不含 `ollama.pull(` 与 `ollama.com/download`。
3. 在 Ollama 供应商配置弹窗打开期间，控制台应当不再提供拉取输入框、下载进度与取消按钮，并提示模型需由运维在 Ollama 主机上预置。

### 需求 9：ONNX 在线下载入口下线

**用户故事：** 作为运维，我希望本地向量模型只从预置目录加载，以便知识库与模型页的任何操作都不会触发向公网下载模型。

#### 验收标准

1. 路由表应当始终不含 `POST /api/onnx-models/download`、`GET /api/onnx-models/download-status`、`POST /api/knowledge-bases/onnx-download`、`GET /api/knowledge-bases/onnx-download-status`。
2. 如果启用本地 ONNX 服务时所选模型未预置，那么 `PUT /api/onnx-models/config` 应当返回 409、不启动任何下载，且不以 `enabled=true` 持久化配置；请求体里带 `download_if_missing: true` 时结果相同。
3. 本地嵌入推理构造 fastembed `TextEmbedding` 时应当始终传入 `local_files_only=True`。
4. `src/octop/infra/agents/providers/onnx_download.py` 应当不存在；`src/octop` 中应当始终不含 `huggingface.co`、`hf-mirror.com`、`octop-1258344699`。
5. `GET /api/onnx-models/status` 与 `POST /api/knowledge-bases/onnx-activate` 返回体中的 `download` 字段应当始终存在，且 `status == "idle"`。
6. 模型页与知识库设置页应当不再提供"下载模型"按钮；所选模型未预置时，应当显示"需由运维预置"的提示。

### 需求 10：Let's Encrypt 签发与公网 IP 探测下线

**用户故事：** 作为行方安全管理员，我希望服务端不再尝试向公网 CA 申请证书、不再探测公网 IP，以便 TLS 链路完全由行内 PKI 管理。

#### 验收标准

1. 路由表应当始终不含 `POST /api/admin/tls/preflight`、`POST /api/admin/tls/issue` 与 `GET /.well-known/acme-challenge/{token}`；`build_http_companion_app` 返回的应用路由中也不含 ACME 挑战路径。
2. 当 `OctopServer.start()` 完成时，cron 管理器应当不再注册 TLS 自动续期系统任务；`src/octop` 中不再出现 `install_auto_renewal_job` 与 `octop_tls_auto_renew`。
3. `pyproject.toml` 与 `uv.lock` 应当始终不含 `acme`、`josepy` 以及仅由 `acme` 引入的 `pyopenssl`、`pyrfc3339`；`src/octop` 中应当始终不含 `from acme`、`josepy`、`api.ipify.org`、`letsencrypt.org`。
4. `TlsConfig` 应当不再有 `acme_staging` 字段；如果存量 `config.json` 的 `tls` 段仍含 `acme_staging`，那么 `load_config` 应当照常成功。
5. 在基线已由 Let's Encrypt 签发并启用 TLS 的实例上，升级后 `resolve_tls_paths` 与 `build_listen_plan` 的结果应当与基线一致，HTTPS 继续以原证书提供服务。

### 需求 11：上传行内证书

**用户故事：** 作为系统管理员，我希望在控制台上传行内 CA 签发的证书与私钥，以便不接触服务器文件系统也能启用 HTTPS。

#### 验收标准

1. 当持 `tls` 权限的用户向 `POST /api/admin/tls/certificate` 提交可解析的 PEM 证书链与匹配的未加密私钥时，系统应当写入 `~/.octop/ssl/fullchain.pem` 与 `~/.octop/ssl/privkey.pem`，并把 `config.json` 的 `tls` 段设为 `enabled=true`、`mode="uploaded"`、`domains`（取自叶子证书的 SAN）、`cert_file`、`key_file`、`issued_at`、`expires_at`、`http_port=0`，不改 `bind_host` 与 `port`，返回 `state == "restart_required"`。
2. 如果证书无法解析、私钥无法解析或已加密、私钥与叶子证书公钥不匹配、证书已过期或尚未生效，那么接口应当返回 400、`error.code == "TLS_CERT_INVALID"`、`error.details.reason` 为对应机器码，且不写任何文件、不改 `config.json`。
3. 在上传成功而进程尚未重启期间，`GET /api/admin/tls/status` 应当返回 `state == "restart_required"`；进程以有效证书启动后返回 `"active"`；未启用 TLS 时返回 `"idle"`。
4. 当上传成功时，系统应当写入一条 `audit_log`：`action == "tls.certificate.upload"`，`target` 为逗号分隔的域名，`payload` 为叶子证书的 SHA-256 指纹；审计、日志与响应体应当始终不含私钥内容。
5. 如果调用者既不是管理员也不持 `tls` 权限，那么上传接口与状态接口应当返回 403。
6. HTTPS 设置页应当提供证书与私钥的上传表单，展示当前证书的域名、模式与到期时间；在 `restart_required` 状态下提供"重启服务"按钮与"重启后请改用 https:// 访问"的提示；上传失败时按 `details.reason` 显示 overlay 中的本地化文案。
7. `TLS_CERT_INVALID` 应当同时登记在 `ErrorCode` 末尾、`_DEFAULT_STATUS` 末尾（400）、后端 overlay 的 `errors` 与 dashboard overlay 的 `apiErrors`，且 `uv run pytest tests/unit/i18n -q` 通过。

### 需求 12：守卫与交付

**用户故事：** 作为 fork 维护者，我希望有测试守住本 spec 删掉的域名与路由，以便上游同步时它们一旦回流就在 CI 变红。

#### 验收标准

1. `tests/unit/test_online_fetch_tokens_removed.py` 应当始终通过：它扫描 `src/octop` 下的 `*.py`、`*.md`、`*.sh`（排除 `infra/agents/experts/library/` 与 `infra/agents/subagents/library/` 两个内容库）与 `dashboard/src` 下的 `*.ts`、`*.tsx`，断言设计文档列出的 token 一个都不出现。
2. `tests/unit/api/test_online_fetch_removed_routes.py` 应当始终通过：它以 `enable_api_docs=True` 构建应用，断言需求 1、4-10 列出的路由既不在 `app.routes` 中也不在 `/api/openapi.json` 中，而 `GET /api/service/status`、`POST /api/service/restart`、`POST /api/admin/tls/certificate` 存在。
3. 本 spec 应当始终不修改 `src/octop/i18n/en.json`、`src/octop/i18n/zh.json`、`dashboard/src/locales/en.json`、`dashboard/src/locales/zh.json`；新增与覆盖的文案只写进两对 intranet overlay。
4. 当本 spec 合入时，`make all` 应当全绿，`cd dashboard && npx tsc -b && npm run lint && npm run test` 应当通过，`CHANGELOG-intranet.md` 与 `docs/api-intranet.md` 应当记录本 spec 删除与新增的路由、权限键变化和新错误码。
