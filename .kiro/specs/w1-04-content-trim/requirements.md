# 需求文档：C 端内容与非交付工程裁剪

> spec：`w1-04-content-trim` ｜ 波次：Wave 1 ｜ 基线：`757fd12` ｜ 预估：8.5 人日
> 前置：`w0-02-ci-gates`、`w0-03-test-auth-baseline`、`w0-04-fork-isolation-points`、`w1-02-capability-trim`、`w1-03-online-fetch-trim` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 引言

**结论：** 本 spec 物理删除 Octop 中面向个人与家庭用户的内容，以及面向公网发行的打包与工程文件，不做任何加固。删除范围分三块。第一块是两条完整功能链：MBTI 人格与主动关怀，覆盖后端路由、领域模块、仓储装配、运行时调度、CLI 选项、前端页面与组件。第二块是三个内容库：内置专家 18 个删 7 个，子智能体删除营销、游戏开发、付费媒体、空间计算、销售五个分类（zh 272 → 187 个、en 217 → 154 个），内置插件 11 个删 8 个，只保留 `pomodoro`、`qrcode`、`server-status`。第三块是非交付工程：按 D9 删除 `desktop/` 与 `fnos/` 及其连带脚本、测试和 `service_control.py` 的桌面重启分支；删除四个公网一键安装脚本；删除发布、镜像推送、同步类 GitHub 工作流与 `.cursor/`；删除 `/pwa-debug` 调试页、头像菜单的两个项目外链、企业微信客户群二维码与零引用的 `build@0.1.4` 依赖。数据库列与表保留在已发布的 001 迁移里，不写 fork 迁移；不删除任何 i18n 键；不新增配置键与 `ErrorCode`。

### 背景

以下事实均在基线 `757fd12` 上核实，证据见设计文档"现状"一节。

| 对象 | 基线状态 | 在行内网的问题 |
|---|---|---|
| MBTI 人格 | `api/routers/mbti.py`（766 行）提供 7 个 `/api/mbti/*` 端点，含心理测评题与答卷提交；`mbti_profiles.py`（596 行）是 16 型人格数据；`POST/PATCH /api/agents` 与 `octop agent create --persona-mbti` 都能写 `agents.persona_mbti` | 心理测评属于 C 端玩法；`mbti.py` 还是全仓唯一读取 `X-Octop-Agent-Id` 请求头的后端模块 |
| 主动关怀 | `infra/proactive/`（913 行）在启动时为**每个**已启用 Agent 排一个随机间隔的推送任务（`list_enabled` 对没有配置行的 Agent 也视为开启），按 sad / angry / anxious / frustrated 权重 1.5 挑选情绪日记喂给 LLM 生成关怀文案并推送 | 默认对全部 Agent 开启、未经用户授权向其推送；处理情绪类个人信息 |
| 内置专家 | 18 个专家目录；其中育儿、证券、美团生活、热点新闻、公众号发文、医学文献、卡帕西知识库 7 个依赖公网或属于生活消费场景 | 断网不可用，且与银行业务无关；其中 3 个在提示词里要求调用已被 `w1-02` 删除的 `browser_use` |
| 子智能体 | zh 19 个分类、en 16 个分类；营销、游戏开发、付费媒体、空间计算、销售五类共 zh 85 个、en 63 个定义 | 非行内场景 |
| 内置插件 | 11 个，其中 5 个（`bilibili-anime`、`hot-topics`、`market-quotes`、`parcel-tracker`、`weather`）在 `main.py` 里直连公网，3 个（`fortune`、`mini-games`、`tetris`）是娱乐内容 | 断网不可用或不适合行内 |
| `desktop/`、`fnos/` | Wails 桌面壳与绿色便携包 73 个文件、飞牛 NAS 安装包 49 个文件，另有 3 个专属测试、3 个打包脚本和 2 个构建工作流 | D9 默认不交付 |
| 一键安装脚本 | `scripts/install.sh` 等 4 个脚本从 GitHub、公网 PyPI 镜像与 `astral.sh` 拉取安装物，并含已被 `w1-02` 删除的 `--extras browser` 逻辑 | 行内按容器平台交付（D4），这些脚本在断网环境不可用 |
| GitHub 工程 | 9 个工作流，其中 6 个用于发布、镜像推送与分支同步；`.cursor/skills/publish` 描述 PyPI / Docker Hub 发布流程 | 行内无对应物 |
| 前端杂项 | `/pwa-debug` 调试页（703 行）对所有登录用户开放；头像菜单指向 GitHub 仓库与 GitHub Pages 文档站；`dashboard/package.json` 依赖全仓零引用的 `build@0.1.4`，它把 `uglify-js@1.3.5` 等 10 个包带进锁文件 | 暴露调试信息；断网外链；供应链扫描的确定性告警 |

### 为什么做

1. 全局约束 1.5"先删后改"：这些功能删掉后，`w3-02` 不必为 MBTI 与主动关怀写审计，`p2-04` 不必为关怀文案写内容安全与脱敏，`w2-02` 的许可证与 SCA 清单少一批无用条目。
2. `w2-01`、`w2-02`、`w3-04`、`w3-05` 都曾计划改 `fnos/` 或 `desktop/` 下的打包文件。按 D9 先删目录，这些改动全部归零，也避免多个 spec 在同一批打包文件上轮流冲突。
3. 内容库是上游持续新增的目录。只删不守，上游同步时被删的专家、分类、插件会以"新增文件"的形式静默回流，因此本 spec 同时交付一个白名单守卫测试。

### 范围内

1. **MBTI 人格**：删除 `mbti.py`、`mbti_profiles.py`、`persona.py` 与路由挂载、OpenAPI tag；`AgentCreateSpec`、`AgentManager.apply_persona_mbti`、`POST/PATCH /api/agents` 的请求与响应字段、CLI `--persona-mbti` 选项；前端个性化页 MBTI 标签页、专家页与管理页的人格标签和人格列、"人格"菜单项、MBTI 目录抽屉、API 模块与类型、16 张插画、`/mbti` 路由；以及保留下来的 4 个专家模板文件中的"MBTI 人格"段落。数据库列与 `AgentRow.persona_mbti` 列映射保留。
2. **主动关怀**：删除 `infra/proactive/`、`proactive_care.py` 路由、两个仓储及其在 `RepoBundle`、`SharedServices`、`AppRuntime`、`AgentManager` 中的装配；测试夹具中的调度器挂起逻辑；前端记忆页"主动关心"标签页、配置面板、API 方法与类型（含指向不存在的 `/agent/proactive-config` 的既有死代码）。
3. **内置专家**：删除 7 个专家目录、7 张头像及 `_FALLBACK_BUNDLED_AVATAR_IDS` 中的对应 id；保留专家中不再引用已删能力：`multi-agent-orchestrator` 的分类清单与示例 slug、`office-automation` 的 `news` 技能。
4. **子智能体**：zh、en 两侧同步删除 5 个分类目录，并同步修改两份 `divisions.json`。
5. **内置插件**：删除 8 个插件、仓库根的 `plugins/bilibili-anime/` 指针目录、专测 `hot-topics` 的单测，以及 weather 插件遗留的孤儿页面 `dashboard/src/pages/Chat/Weather/`。
6. **D9 与安装脚本**：删除 `desktop/`、`fnos/`、`scripts/build-fpk.sh`、`scripts/fnos/`、`scripts/release_download_links.py`、`scripts/install{.sh,-octop.sh,.ps1,.bat}`，以及 `tests/unit/test_green_launch.py`、`tests/unit/desktop/test_stamp_version.py`、`tests/unit/test_release_download_links.py`；删除 `w1-03` 迁入 `api/routers/service_control.py` 的桌面重启分支与 `desktop` 响应字段；清理 `.gitignore`、`scripts/README.md`、`infra/setup/service.py` 中指向已删文件的内容。
7. **GitHub 工程**：删除 `octop-desktop.yml`、`fnos-build-fpk.yml`、`release.yml`、`auto-tag-on-release.yml`、`docker-publish.yml`、`sync-main-to-develop.yml` 与 `.cursor/`；保留 `ci.yml`、`codeql.yml`。
8. **前端杂项**：删除 `/pwa-debug` 页与路由、`AvatarDropdown.tsx` 中的 GitHub 与文档站两个菜单项、`build@0.1.4` 依赖，并用 `make relock` 重生成 `dashboard/package-lock.json`。
9. **文档**：删除 `docs/personas.md` 与 `docs/assets/qrcode.png`；删除 README 与用户指南中的企业微信客户群段落；在仓库其余文件中清除指向本 spec 已删路径（以及 `w1-02` 已删的 `docs/acp.md`）的链接与引用；修正 `AGENTS.md`、`CONTRIBUTING.md` 中因本次删除而失效的描述。
10. **守卫与记录**：新增内容库白名单守卫测试、内容裁剪 API 集成测试与前端路由测试；在 `w1-02` 的 `tests/integration/test_removed_routes.py` 中追加本 spec 删除的路由；更新 `CHANGELOG-intranet.md` 与 `docs/api-intranet.md`。

### 范围外（归属）

| 事项 | 归属与说明 |
|---|---|
| 删除任何 i18n 键（含 MBTI 约 39 个、主动关怀约 28 个、`adminAgents.columns.persona`、`subagents.divisions` 下 5 个分类、后端 `proactive_care.*` 2 个） | 全局约束 1.2 禁止。源分析的 70 余处删键全部作废，孤儿键保留。`experts.fileLabel.proactive` 与 `experts.fileLabel.heartbeat` 本来就仍在使用 |
| 清除存量数据：`agents.persona_mbti` 列值、`agents.config_json` 中的 `persona` 键、两张关怀表的行、`~/.octop/plugins/` 下已播种的旧插件副本 | 默认不做（行内为全新部署）；若行方要求，见设计文档"待行方确认" |
| `pyproject.toml` 的 `desktop` extra（`mss`、`pynput`，唯一消费者是被删的 `fnos/docker/Dockerfile`）与锁文件中的 Python 依赖 | `w2-01-offline-build`（依赖收敛） |
| `ci.yml`、`codeql.yml`、`.github/codeql/`、`anti-spam-issues.yml`、`.github/ISSUE_TEMPLATE/`、`.github/pull_request_template.md` | `w2-02-supply-chain-compliance` 提供行内流水线与 SAST 替代后一并处理；本 spec 的范围只含发布、镜像推送、同步三类工作流 |
| 行内安装与部署文档（替代被删的一键安装脚本），以及 README、`docs/cli.md`、`docs/user-guide.*` 中 `octop update` 与一键安装段落的重写 | `w2-01` 提供离线安装物，`w4-02-ops-minimum` 编写运维手册；本 spec 只清除指向已删仓库路径的引用 |
| 上游叙述文档中对已删功能的文字描述（README 特性列表中的 MBTI、`w1-02` 五类能力的介绍段落等） | 不改写（全局约束第 5 节的同步成本考虑）；以 `CHANGELOG-intranet.md` 的"移除"条目为准 |
| dashboard 的桌面壳适配（`utils/desktopChrome.ts`、`hooks/useDesktopChrome.ts`、`components/DesktopWindowControls/` 等） | 只在 `window._wails` 存在时生效，浏览器中恒为惰性。清理涉及 `App.tsx` 等 10 余个上游文件，零功能收益，交 `w4-01-frontend-baseline` 酌情处理 |
| PWA 整体下线（`PwaUpdatePrompt`、Service Worker）、其余外链（供应商文档、通道平台链接、远程 `icon_url`） | `w4-01-frontend-baseline`；通道与云服务相关链接归 `w1-05-saas-decoupling` |
| 腾讯云相关专家（`cvm-ai-doctor`、`cvm-cluster-doctor`、`tencentcloud-api`）及被删专家使用过的连接器（`tencent-news`、`meituan-travel`） | `w1-05-saas-decoupling` 决定去留；本 spec 只剥离其中的"MBTI 人格"段落 |
| `office-automation` 的 docx / xlsx / pptx / pdf 技能许可证与自研替换 | `w2-02`、`p2-10-office-skills-rewrite`；本 spec 只删其 `news` 技能 |
| 记忆模块的情绪日记（Episode）采集 | 保留；个人信息最小化评估归 `p2-04-content-security-pii` |
| `self_update.py`、`update.py`、`UpdateConfig.tsx`、`update.ts` 的 fpk / green / desktop 分支 | 已由 `w1-03` 随自更新整体删除，本 spec 不再规划 |
| `pages/Control/Terminal/components/AiPanel.tsx`、`pages/Agent/ACP/index.tsx` 中的 MBTI 痕迹 | 已由 `w1-02` 随文件删除，本 spec 不再规划 |
| `dashboard/src/pages/Settings/octop/Providers.tsx` 死代码（`w1-01` 交接）、`infra/agents/experts/manifest_generator.py` 死代码（`w1-03` 交接） | 与 C 端内容无关，按 AGENTS.md §1"只登记不删"，本 spec 不处理 |

## 需求

### 需求 1：MBTI 人格后端与 CLI 下线

**用户故事：** 作为行方安全评审人员，我希望系统中不再存在心理测评与人格设定的任何接口和写入入口，以便行内版本不收集与业务无关的心理画像数据。

#### 验收标准

1. 当 `build_app` 构建应用时，路由表应当不含任何以 `/api/mbti` 开头的路径（含基线的 `POST /api/mbti/apply` 与 `POST /api/mbti/test/submit`）；已登录用户请求 `GET /api/mbti/types`、`GET /api/mbti/current` 时应当得到 404；在 `enable_api_docs=True` 时，`/api/openapi.json` 的 `tags` 应当不含 `mbti`，`paths` 应当不含以 `/api/mbti` 开头的键。
2. 当客户端以含 `"persona_mbti": "INTJ"` 的请求体调用 `POST /api/agents` 时，接口应当返回 201，响应体不含 `persona_mbti` 键，新建 Agent 行的 `persona_mbti` 列为 NULL，且其 `config_json` 不含 `persona` 键。
3. 如果客户端以含 `persona_mbti` 的请求体调用 `PATCH /api/agents/{agent_id}`，那么接口应当返回 200 并忽略该字段，Agent 行的 `persona_mbti` 列保持调用前的值。
4. 当运维执行 `uv run octop agent create --help` 时，输出应当不含 `--persona-mbti`；如果运维传入 `--persona-mbti INTJ`，那么命令应当以非零退出码结束。
5. 仓库应当始终不存在 `src/octop/infra/agents/mbti_profiles.py`、`src/octop/infra/agents/persona.py`、`src/octop/api/routers/mbti.py`；`AgentCreateSpec` 应当不含 `persona_mbti` 字段，`AgentManager` 应当不含 `apply_persona_mbti`；`src/octop` 下的 Python 文件中应当不再出现字符串 `X-Octop-Agent-Id`。
6. `agents.persona_mbti` 列应当始终保留在 `001_initial.sql` 与 `001_initial.pg.sql` 中，本 spec 不改任何已发布迁移；`AgentRow.persona_mbti` 作为列映射保留；`rg -n -i 'mbti' src/octop --glob '*.py'` 应当只命中 `src/octop/infra/db/repos/agents.py`。

### 需求 2：MBTI 前端入口下线

**用户故事：** 作为行内员工，我希望控制台里不再出现人格测评、人格标签与人格设置入口，以便界面只保留与工作相关的功能。

#### 验收标准

1. 控制台应当始终不再渲染 MBTI 人格标签与人格列：专家页的 Agent 卡片与 Agent 表格、Agent 资料抽屉、管理后台的 Agents 表格与 Agent 卡片均不含该元素；专家页"更多"菜单不含"人格"项，也不再能打开 MBTI 目录抽屉。
2. 当用户访问 `/personalization/mbti` 时，个性化页应当显示一个非 MBTI 的标签页（本地记住的标签页，缺省为 `skills`），标签栏中不存在 MBTI 标签；当用户访问 `/mbti` 时，控制台应当显示 404 页。
3. `dashboard/src/routes/index.tsx` 的 `routeConfigs` 与 `pathToKey`、`dashboard/src/routes/prefetch.ts` 的预加载表应当始终不含 `/mbti` 与 `/personalization/mbti`，由 `dashboard/src/routes/contentTrim.test.ts` 断言。
4. 仓库应当始终不存在 `MBTITest.tsx`、`MBTITest.module.less`、`MBTISelector.tsx`、`MBTISelector.module.less`、`MbtiCatalogDrawer.tsx`、`MbtiPersonaTag.tsx`、`api/modules/mbti.ts`、`api/types/mbti.ts` 与 `dashboard/public/assets/mbti/`；`OctopAgent` 类型不含 `persona_mbti`；`request.ts` 的 `isAgentScopedPath` 不再匹配 `/mbti/`；`cd dashboard && npx tsc -b` 应当通过。

### 需求 3：主动关怀后端下线

**用户故事：** 作为行方合规人员，我希望系统不再在未经授权的情况下读取员工的情绪日记并主动推送关怀消息，以便满足个人信息处理的最小必要原则。

#### 验收标准

1. 当 `build_app` 构建应用时，路由表应当不含 `GET` 与 `PUT /api/agents/{agent_id}/proactive-care`；已登录用户请求 `GET /api/agents/{agent_id}/proactive-care` 时应当得到 404；`/api/openapi.json` 的 `paths` 中应当不含任何包含 `/proactive-care` 的键。
2. 当 `OctopServer.start()` 完成时，即使存在已启用的 Agent，进程中也应当不存在主动关怀调度任务；`AppRuntime` 应当不再有 `proactive_scheduler` 字段，`AgentManager` 应当不再有 `set_proactive_scheduler`；创建与删除 Agent 时应当不再调度或取消任何关怀任务。
3. 仓库应当始终不存在 `src/octop/infra/proactive/`、`src/octop/infra/db/repos/care_push.py`、`src/octop/infra/db/repos/proactive_care_config.py`；`RepoBundle` 与 `SharedServices` 应当不再有 `care_push_repo`、`proactive_care_config_repo`；`tests/conftest.py` 中不再有 `_suspend_proactive_care_loops`，且 `uv run pytest -m "not live"` 应当正常结束而不因遗留的 sleep 任务挂起。
4. 在新建的 SQLite 与 PostgreSQL 库上，001 迁移应当始终照常建出 `proactive_care_config`、`care_push_records` 两张表及两个索引；`tests/unit/db/test_db_pool.py` 不改动即通过；`_schema_version` 仍为 15；本 spec 不新增任何 fork 迁移。
5. 定时任务的推送链路应当保持不变：本 spec 对 `src/octop/infra/gateway/` 的 diff 为空，`uv run pytest tests/unit/gateway/test_gateway_push.py tests/unit/cron -q` 通过。
6. `src/octop/api/openapi_meta.py` 的 `API_DESCRIPTION` 应当不再提及 proactive care，只描述定时任务提醒。

### 需求 4：主动关怀前端下线

**用户故事：** 作为行内员工，我希望记忆页不再提供"主动关心"的开关与时段设置，以便界面与后端能力一致。

#### 验收标准

1. 当用户打开 Agent 的记忆面板时，标签栏应当不含"主动关心"；其余标签页（含情绪日记）行为不变，`dashboard/src/pages/Agent/Memory/*.test.tsx` 全部通过。
2. 仓库应当始终不存在 `dashboard/src/pages/Agent/Memory/ProactiveConfig.tsx` 与 `ProactiveConfig.module.less`；`dashboard/src/api/modules/agent.ts` 应当不含 `getProactiveConfig`、`updateProactiveConfig`、`getProactiveCareConfig`、`updateProactiveCareConfig`；`dashboard/src/api/types/agent.ts` 应当不含 `ProactiveConfig` 与 `ProactiveCareConfig`。
3. 在专家文件预览中，`PROACTIVE.md` 与 `HEARTBEAT.md` 应当始终显示本地化文件标签：`iconForName.tsx` 的两项映射、`experts.fileLabel.proactive` 与 `experts.fileLabel.heartbeat` 两个键、`infra/agents/experts/publish.py` 的 `_EXPORT_ROOT_MD` 均保持不变。

### 需求 5：内置专家 18 → 11

**用户故事：** 作为行内员工，我希望专家库只提供与办公、研发、运维相关的模板，以便不会创建出依赖公网或面向家庭生活的 Agent。

#### 验收标准

1. `src/octop/infra/agents/experts/library/` 下的专家目录应当始终恰为 11 个：`ai-coding-coach`、`ai-safety-guardian`、`cvm-ai-doctor`、`cvm-cluster-doctor`、`default`、`general-assistant`、`multi-agent-orchestrator`、`office-automation`、`ops-engineer`、`superpowers-methodology`、`tencentcloud-api`。
2. `dashboard/public/experts/avatars/` 下的 SVG 应当始终恰为 28 个，且 `catalog.py` 的 `_FALLBACK_BUNDLED_AVATAR_IDS` 与磁盘上的头像 id 集合相等，`uv run pytest tests/unit/agents/test_expert_catalog.py -q` 通过。
3. 当已登录用户请求 `GET /api/experts` 时，返回的专家 id 应当不含 `clinical-learning-subscription`、`karpathy-knowledge-base`、`meituan-living-assistant`、`news-trend`、`parenting-companion`、`stock-assistant`、`wechat-ops`；请求 `GET /api/experts/news-trend` 时应当返回 404 且 `error.code == "NOT_FOUND"`。
4. 如果客户端以已删除的专家 id 作为 `template_name` 调用 `POST /api/agents`，那么系统应当与基线处理未知模板的方式一致：返回 201、不复制任何模板文件、记录一条 WARNING；已由这些模板创建的存量 Agent 应当仍能启动。
5. 保留专家的内容应当始终不再引用已删能力：`rg -n 'MBTI|browser_use' src/octop/infra/agents/experts/library` 没有输出；`multi-agent-orchestrator` 的 `AGENTS.md` 与 `SOUL.md` 不再列出已删的 5 个分类，也不再以 `marketing-content-creator` 作示例；`office-automation` 不再包含 `skills/news/`，其 `SOUL.md`、`IDENTITY.md`、`manifest.json` 不再提及 news 技能。
6. 测试中硬编码的已删专家 id 应当全部替换为保留专家或随用例删除；`uv run pytest tests/live --collect-only -q` 应当无收集错误。

### 需求 6：子智能体分类裁剪

**用户故事：** 作为行内员工，我希望子智能体目录不再出现营销、游戏开发、付费媒体、空间计算、销售类角色，以便委派时只看到与行内工作相关的角色。

#### 验收标准

1. `subagents/library/zh` 下的 `.md` 定义应当始终为 187 个，`subagents/library/en` 下为 154 个；两份 `divisions.json` 的 `divisions` 键集合应当分别为 14 项与 11 项，且各自与磁盘上的分类目录集合相等，均不含 `marketing`、`game-development`、`paid-media`、`spatial-computing`、`sales`。
2. 当已登录用户请求 `GET /api/subagent-catalog/divisions` 时，接口应当返回 14 条记录，每条的 `count` 都大于 0，且不含上述 5 个分类 id。
3. 如果用户请求 `POST /api/agents/{agent_id}/subagents/install` 安装已删分类下的 slug（如 `marketing-content-creator`），那么接口应当返回 404 且 `error.code == "NOT_FOUND"`；此前已安装到 Agent 工作区 `agents/` 目录的副本应当不受影响。
4. `tests/integration/test_subagents_api.py::test_catalog_divisions` 与 `tests/unit/agents/test_subagent_catalog.py::test_bundled_library_non_empty` 中的 `== 19` 应当改为 `== 14` 并通过。

### 需求 7：内置插件 11 → 3

**用户故事：** 作为行方安全管理员，我希望随包分发的插件都不访问公网、不含娱乐内容，以便即使有人启用插件也不会产生外联。

#### 验收标准

1. `src/octop/infra/agents/plugins/bundled/` 下（不计 `__pycache__`）的插件目录应当始终恰为 `pomodoro`、`qrcode`、`server-status` 三个，`uv run pytest tests/unit/test_bundled_plugins_layout.py -q` 通过。
2. 当运维执行 `octop init` 时，`~/.octop/plugins/` 下应当只播种这 3 个插件，且 `config.json` 中它们的 `enabled` 均为 `false`，由 `tests/unit/cli/test_init_cmd.py` 验证。
3. 保留的 3 个插件的 `main.py` 应当始终不含 `http`：`rg -n 'http' src/octop/infra/agents/plugins/bundled --glob 'main.py'` 没有输出。
4. 仓库应当始终不存在 `plugins/bilibili-anime/`、`dashboard/src/pages/Chat/Weather/`、`tests/unit/test_hot_topics_plugin.py`。

### 需求 8：`desktop/`、`fnos/` 与公网安装脚本下线

**用户故事：** 作为行方交付负责人，我希望仓库只保留行内实际交付的服务端形态，以便后续的依赖收敛、合规扫描与加固不必再覆盖桌面客户端、NAS 安装包和公网安装脚本。

#### 验收标准

1. 仓库应当始终不存在 `desktop/`、`fnos/`、`scripts/build-fpk.sh`、`scripts/fnos/`、`scripts/release_download_links.py`、`scripts/install.sh`、`scripts/install-octop.sh`、`scripts/install.ps1`、`scripts/install.bat`、`tests/unit/test_green_launch.py`、`tests/unit/desktop/test_stamp_version.py`、`tests/unit/test_release_download_links.py`；`uv run pytest --collect-only -q -m "not live"` 应当无收集错误。
2. 当已登录用户请求 `GET /api/service/status` 时，响应应当只含 `current_version` 与 `service_mode`，不含 `desktop`；如果进程设置了 `OCTOP_DESKTOP=1` 或 `OCTOP_GREEN_PACKAGES` 但不处于系统服务模式，那么 `POST /api/service/restart` 应当返回 403 且 `error.code == "FORBIDDEN"`，并且不调用 `os.execv`；`rg -n 'OCTOP_DESKTOP|OCTOP_GREEN_PACKAGES|_restart_desktop_process|_is_desktop_process' src/octop dashboard/src` 没有输出。
3. `.gitignore` 应当不再含 `!desktop/src/build/` 两行；`infra/setup/service.py` 中找不到 `octop` 可执行文件时的报错应当不再提示运行 `scripts/install.sh`；`scripts/README.md` 应当只描述仍存在的 `wheel_build.sh`、`wheel_build.ps1`；`scripts/wheel_build.sh`、`scripts/wheel_build.ps1`、`scripts/smoke_memory_api.py` 保持存在。
4. 本 spec 应当始终保留 dashboard 的桌面壳适配代码：`dashboard/src/utils/desktopChrome.ts` 仍存在，`cd dashboard && npx vitest run src/utils/desktopChrome.test.ts` 通过（浏览器中 `isDesktopShell` 返回 `false`）。
5. 本 spec 应当始终不修改 `pyproject.toml` 与 `uv.lock`：`desktop` extra 留给 `w2-01` 处理。

### 需求 9：发布、镜像推送、同步类工作流与 `.cursor/` 下线

**用户故事：** 作为行方研发管理员，我希望仓库里不再有向 PyPI、Docker Hub、GitHub Release 发布或自动同步分支的工作流，以便行内流水线接入前不会有人误以为这些流程仍然有效。

#### 验收标准

1. `.github/workflows/` 下应当始终恰为 `anti-spam-issues.yml`、`ci.yml`、`codeql.yml` 三个文件；`octop-desktop.yml`、`fnos-build-fpk.yml`、`release.yml`、`auto-tag-on-release.yml`、`docker-publish.yml`、`sync-main-to-develop.yml` 不存在。
2. 本 spec 应当始终不修改 `.github/workflows/ci.yml`、`.github/workflows/codeql.yml`、`.github/codeql/`、`.github/ISSUE_TEMPLATE/` 与 `.github/pull_request_template.md`，它们在本 spec 各提交前后的 `git diff` 为空。
3. 仓库应当始终不存在 `.cursor/`；`AGENTS.md` 与 `CONTRIBUTING.md` 中应当不再出现 `.cursor/skills/publish` 与 `sync-main-to-develop.yml`。

### 需求 10：前端调试页、项目外链与零引用依赖

**用户故事：** 作为行方安全管理员，我希望控制台不再暴露调试页、不再出现指向公网项目站点的链接、不再携带无用且含已知高危版本的依赖，以便通过前端安全检查与供应链扫描。

#### 验收标准

1. 当已登录用户访问 `/pwa-debug` 时，控制台应当显示 404 页；`dashboard/src/pages/PwaDebug/` 应当不存在，`rg -n 'pwa-debug|PwaDebug' dashboard/src` 没有输出。
2. 当用户打开头像菜单时，菜单应当不再含"帮助与反馈"文档站链接与"项目地址"GitHub 链接，外观、设置、修改密码等其余项不变；`rg -n 'github\.com/TencentCloud/Octop|tencentcloud\.github\.io' dashboard/src --glob '!**/locales/**'` 没有输出。
3. `dashboard/package.json` 的 `dependencies` 应当始终不含 `build`，`scripts.build` 保持 `tsc -b && vite build`；`dashboard/package-lock.json` 的 `packages` 中应当不含 `build`、`cssmin`、`jsmin`、`jxLoader`、`moo-server`、`promised-io`、`timespan`、`uglify-js`、`walker`、`winston`、`wrench` 这 11 个条目；`cd dashboard && npm ci` 应当成功。

### 需求 11：文档与 fork 记录

**用户故事：** 作为在本仓库工作的维护者或 AI 代理，我希望仓库中的链接与导航说明在删除后仍然指向真实存在的文件，并能在 fork 自有文档里查到本次删除了什么，以便不被失效信息误导。

#### 验收标准

1. 仓库应当始终不存在 `docs/personas.md` 与 `docs/assets/qrcode.png`；`README.md`、`README_CN.md` 应当不再含企业微信客户群一节及其目录锚点，`docs/user-guide.md` 应当不再含加入客户群的问答与图 7.1 行。
2. 当执行设计文档"测试策略"中的悬空引用检查命令时，除 `CHANGELOG.md`、`docs/api.md` 与 fork 自有记录外，仓库中应当没有任何文件引用本 spec 删除的路径或 `docs/acp.md`。
3. `AGENTS.md` 应当始终不再把"MBTI personas"列为 `infra/agents/` 的职责，也不再声称存在读取 `X-Octop-Agent-Id` 的遗留端点。
4. 本 spec 应当始终不修改 `src/octop/i18n/en.json`、`src/octop/i18n/zh.json`、`dashboard/src/locales/en.json`、`dashboard/src/locales/zh.json`、`CHANGELOG.md`、`docs/api.md`、`src/octop/infra/db/migrations/001_initial.sql`、`001_initial.pg.sql` 与 `tests/unit/db/test_db_pool.py`。
5. 当本 spec 合入时，`CHANGELOG-intranet.md` 的"移除"分类应当列出本 spec 删除的功能、内容与工程文件；`docs/api-intranet.md` 应当在"已物理删除的上游路由"中列出 7 个 `/api/mbti/*` 端点与 2 个 `/proactive-care` 端点，在"fork 新增或变更的端点"中说明 `POST/PATCH /api/agents` 与 `GET /api/service/status` 的字段变化，在"鉴权与权限差异"中说明后端不再读取 `X-Octop-Agent-Id`。

### 需求 12：守卫与交付

**用户故事：** 作为 fork 维护者，我希望有测试守住本 spec 删掉的内容与路径，以便上游同步把它们带回来时 CI 立刻变红。

#### 验收标准

1. `tests/unit/test_content_trim_guard.py` 应当始终通过；如果上游同步把已删的专家目录、子智能体分类、Python 模块或仓库路径带回来，那么该测试应当失败，并在失败信息中列出回流项。
2. 当本 spec 合入时，`make all` 应当全绿，`cd dashboard && npx tsc -b && npm run lint && npm run test` 应当通过。
3. 在本 spec 开始实施前，前置 spec 的交付物应当已存在：`tests/integration/test_removed_routes.py`（`w1-02`）、`src/octop/api/routers/service_control.py`（`w1-03`）、`CHANGELOG-intranet.md` 与 `docs/api-intranet.md`（`w0-04`），且 `src/octop/infra/setup/self_update.py`、`dashboard/src/pages/Agent/ACP/` 已不存在。
