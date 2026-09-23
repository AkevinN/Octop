# 设计文档：C 端内容与非交付工程裁剪

> spec：`w1-04-content-trim` ｜ 波次：Wave 1 ｜ 基线：`757fd12` ｜ 预估：8.5 人日
> 前置：`w0-02-ci-gates`、`w0-03-test-auth-baseline`、`w0-04-fork-isolation-points`、`w1-02-capability-trim`、`w1-03-online-fetch-trim` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 概述

本 spec 是一次纯删除：按"功能链"逐条物理删除代码、内容与工程文件，每条链一个可独立提交的任务，不引入新能力。关键设计决定有五条：

1. **数据层不动。** `agents.persona_mbti` 列、`proactive_care_config` 与 `care_push_records` 两张表都留在已发布的 001 迁移里，不写 fork 迁移，也不改 `_schema_version` 与 `test_db_pool.py`。仓储层保留 `AgentRow.persona_mbti` 的列映射（它是表结构的镜像），删除两个只服务主动关怀的仓储类。
2. **i18n 零改动。** 四份 i18n JSON 一个键都不删，本 spec 也不需要新增文案，因此不碰 overlay。
3. **内容库用白名单守住。** 新增 `tests/unit/test_content_trim_guard.py`，把专家、子智能体分类、已删模块与已删仓库路径写成显式集合。上游同步带回任何一项，CI 都会变红，由同步者决定删除还是纳入白名单。
4. **非交付工程按 D9、D4 一次删净。** 删除 `desktop/`、`fnos/` 及其全部连带文件，删除 4 个公网一键安装脚本，删除 `w1-03` 为保持行为等价而暂留在 `service_control.py` 里的桌面重启分支。
5. **上游叙述文档只做"不留悬空引用"的最小修改。** 删除只讲已删功能的文档（`docs/personas.md`）与对外引流物料（企业微信客户群二维码），在其余文件里删掉指向已删路径的链接行；其它对已删功能的文字描述不改写，以 `CHANGELOG-intranet.md` 为准。`CHANGELOG.md` 与 `docs/api.md` 按全局约束第 5 节不改。

## 现状

以下事实均在基线 `757fd12` 上用 `rg` / `sed` / `ls` 核实。行号只作定位提示。

### MBTI 人格链路

| 位置 | 事实 |
|---|---|
| `src/octop/api/routers/mbti.py`（766 行） | `router = APIRouter(prefix="/mbti", tags=["mbti"])`（≈L28）；7 个端点：`GET /current`（≈L151）、`GET /types`（≈L174）、`GET /types/{code}`（≈L187）、`GET /preview/{code}`（≈L204）、`GET /test/questions`（≈L589）、`POST /test/submit`（≈L676）、`POST /apply`（≈L742）。`Header(..., alias="X-Octop-Agent-Id")` 出现在 ≈L153、≈L679、≈L745，`rg -n 'X-Octop-Agent-Id' src/octop` 只命中本文件，即它是全仓唯一读取该请求头的后端模块。源分析提到的 `PUT /agents/{aid}/mbti` 在基线上不存在 |
| `src/octop/infra/agents/mbti_profiles.py`（596 行） | 16 型人格数据，只被 `mbti.py` 与 `persona.py` 导入 |
| `src/octop/infra/agents/persona.py`（83 行） | `PersonaLoader`（≈L38）的全部调用点是 `mbti.py` ≈L210-212 与 `manager.py::AgentManager.apply_persona_mbti` ≈L1679-1682；`resolve_persona_code`（≈L72）零调用方。Agent 创建走 `spec.system_prompt`，`SOUL.md` 来自专家模板，与本文件无关 |
| `src/octop/api/app.py::build_app` | 路由导入元组中的 `mbti`（≈L167）与挂载行 `_RouterMount(mbti.router, "/api", ["mbti"])`（≈L247） |
| `src/octop/api/openapi_meta.py` | `OPENAPI_TAGS` 中的 `{"name": "mbti", ...}`（≈L129）；不存在 `proactive-care` tag |
| `src/octop/infra/agents/manager.py` | `AgentCreateSpec`（≈L278）的 `persona_mbti` 字段（≈L285）；`create`（≈L505）中 `config["persona"] = spec.persona_mbti.upper()`（≈L534-535）与 `agent_repo.create(..., persona_mbti=spec.persona_mbti, ...)`（≈L578）；`apply_persona_mbti`（≈L1672-1700）写 `cfg["persona"]` 并经 `persist_harness_config(**extra)`（≈L860）写列 |
| `src/octop/infra/db/repos/agents.py` | `AgentRow.persona_mbti`（≈L29）、`AgentRow.from_row` 逐键映射（≈L48，≈L62 为该列）、`create` 形参与列清单（≈L96、≈L115、≈L125）、`update_config` 形参与映射（≈L207、≈L226）。`from_row` 显式按键取值，`SELECT *` 多一列会被忽略 |
| `src/octop/api/routers/agents.py` | `AgentCreateBody.persona_mbti`（≈L46）、`AgentPatchBody.persona_mbti`（≈L65）、`_row_dict`（≈L124）响应中的 `"persona_mbti"`（≈L151）、`create_agent`（≈L252）的 `AgentCreateSpec(persona_mbti=...)`（≈L283）；`patch_agent` 用 `body.model_dump(exclude_unset=True)`（≈L367）把字段透传给 `registry.update`。两个请求模型都未设置 `extra`，Pydantic 默认忽略未知字段 |
| `src/octop/cli/commands/agent.py::create` | `@click.option("--persona-mbti", ...)`（≈L22）、形参（≈L28）、`AgentCreateSpec(persona_mbti=...)`（≈L51） |
| 迁移 | `001_initial.sql` ≈L36 与 `001_initial.pg.sql` ≈L30 定义 `persona_mbti TEXT` |
| 权限键 | `infra/users/permissions.py` 中没有 MBTI 或关怀相关的键，`tests/unit/api/test_acl_gate_coverage.py` 的 `GATED_FILES` 也不含 `mbti.py`、`proactive_care.py`，全局约束 1.6 不适用 |
| 测试 | `tests/unit/agents/test_persona.py`（52 行，导入两个被删模块）；`tests/integration/test_personas_admin_api.py` 的 3 个 MBTI 用例（≈L36-66，其后 ≈L68 起是 6 个管理员用例）；`tests/integration/test_agents_shared.py` ≈L117-122 的 `POST /api/mbti/apply` 断言 403；`tests/integration/test_e2e_golden_path.py` ≈L83 在创建请求体里带 `persona_mbti`；另有 6 个测试文件以关键字实参 `persona_mbti=None` 构造 `AgentRow` |
| 专家模板 | `default/IDENTITY.md`（≈L29-37）、`cvm-ai-doctor/USER.md`（≈L40-48）、`cvm-cluster-doctor/IDENTITY.md` 与 `USER.md`（≈L38-46）各有一节"## MBTI 人格"；没有任何代码解析该节。子智能体库中出现的 MBTI 是心理学、招聘等领域知识，不属于本功能 |
| 前端 | 页面与组件：`pages/Agent/Personalization/components/MBTITest.tsx`、`MBTISelector.tsx` 及两份样式、`pages/Experts/components/MbtiCatalogDrawer.tsx`、`components/MbtiPersonaTag.tsx`；API：`api/modules/mbti.ts`、`api/types/mbti.ts`，`api/index.ts`（≈L30 导入、≈L83 展开）、`api/types/index.ts`（≈L11）；`api/request.ts::isAgentScopedPath`（≈L174，≈L178-179 为 `/mbti/` 分支）；`context/AgentContext.tsx` ≈L38 与 `AgentContext.test.ts` ≈L15 的 `persona_mbti`；个性化页 `index.tsx` 的 `mbti` 标签（≈L6 `Brain`、≈L22、≈L33、≈L42、≈L52、≈L168-183）；路由 `routes/index.tsx` 的 `pathToKey`（≈L62、≈L83）与 `/mbti` 重定向（≈L203-205）、`routes/prefetch.ts`（≈L27、≈L30）；人格标签与人格列：`AgentExpertsTable.tsx`（≈L38-39、≈L109-110、≈L159-161、≈L410-420、≈L512、≈L618-630）、`AgentCard.tsx`（≈L24、≈L30、≈L102、≈L347-350、≈L480、≈L555-563）、`AgentMoreActions.tsx`（必填 prop `onMbti` ≈L21、解构 ≈L33、菜单项 ≈L64-69，`Brain` ≈L5）、`components/AgentProfileDrawer.tsx`（≈L19，≈L312-315 为"人格"标签加人格标签组件）、`pages/Settings/octop/AdminAgentCard.tsx`（≈L19、≈L149）、`pages/Settings/octop/Agents.tsx`（≈L232-237 人格列）；插画 `dashboard/public/assets/mbti/` 16 个 SVG。`w1-02` 已删除 `pages/Control/Terminal/components/AiPanel.tsx` 与 `pages/Agent/ACP/index.tsx`，本 spec 不再涉及 |
| 前端路由兜底 | `/personalization/*` 统一交给 `PersonalizationPage`（≈L160），标签由 `hooks/usePathTabs.ts` 解析：路径段不是合法标签时退回本地记住的标签或 `defaultTab`（≈L52-64）；`routeConfigs` 末尾 `*` 路由渲染 `NotFoundPage` |

### 主动关怀链路

| 位置 | 事实 |
|---|---|
| `src/octop/infra/proactive/` | `__init__.py`（18 行）、`picker.py`（217 行，≈L32-35 对 sad / angry / anxious / frustrated 权重 1.5）、`scheduler.py`（396 行，随机间隔调度）、`service.py`（282 行，≈L194-201 读 Agent 的 `SOUL.md`，≈L215-223 用 `proactive_care.system_prompt*` 两个 i18n 键组装提示词） |
| `src/octop/infra/db/repos/proactive_care_config.py::ProactiveCareConfigRepo.list_enabled`（≈L94-127） | `LEFT JOIN ... WHERE a.enabled = 1 AND (c.agent_id IS NULL OR c.enabled = 1)`：没有配置行的 Agent 也视为开启，即默认对全部 Agent 生效 |
| `src/octop/infra/db/repos/care_push.py`（71 行） | 推送去重记录，只被 `infra/proactive/` 使用 |
| `src/octop/infra/db/services.py` | `RepoBundle`（≈L37）的两个字段（≈L61-62）与构造（≈L90-91）；`SharedServices`（≈L97）的两个 property（≈L191-196）；导入（≈L12、≈L18） |
| `src/octop/infra/server.py` | 导入（≈L27-28）；`AppRuntime.proactive_scheduler`（≈L216，无默认值的必填字段）；`AppRuntime.replace_services` 中的 `replace_persistence`（≈L231-235）；`_boot_runtime`（≈L362）中构造 `ProactiveCareService`（≈L456-461）与 `ProactiveCareScheduler`（≈L462-469）、`registry.set_proactive_scheduler`（≈L470）、`start_all()`（≈L477）、`AppRuntime(proactive_scheduler=...)`（≈L484）；`stop`（≈L522）中的 `shutdown()`（≈L528） |
| `src/octop/infra/agents/manager.py` | `TYPE_CHECKING` 导入（≈L83）、`_proactive_scheduler`（≈L348）、`set_proactive_scheduler`（≈L419-421）、`create` 中的 `ensure_scheduled`（≈L629-630）、`delete`（≈L724）中的 `cancel`（≈L740-741） |
| `src/octop/api/routers/proactive_care.py`（145 行） | `GET` 与 `PUT /agents/{agent_id}/proactive-care`（≈L97-145），挂载于 `app.py` ≈L176（导入）与 ≈L253（`_RouterMount(proactive_care.router, "/api", ["proactive-care"])`） |
| `src/octop/api/openapi_meta.py` ≈L50 | `API_DESCRIPTION`："Text-type dashboard pushes (cron reminders, proactive care) also emit ..." |
| 迁移 | `001_initial.sql` ≈L246（`proactive_care_config`，`agent_id` 外键 `ON DELETE CASCADE`）、≈L256（`care_push_records`）、≈L264-265（两个索引）；PG 对应 ≈L240、≈L250、≈L258-259 |
| 测试 | `tests/unit/proactive/`（3 个文件）；`tests/conftest.py` ≈L46-69 的 `_PROACTIVE_SCHEDULER_TESTS` 与 autouse 夹具 `_suspend_proactive_care_loops`（导入被删模块）；`tests/support/app.py::octop_client`（≈L38）中 ≈L57-62 调用 `proactive_scheduler.shutdown()` 与 `suspend()`；`tests/unit/db/test_runtime_replace_services.py` ≈L15-16、≈L47-64 构造调度器并传给 `AppRuntime`；`tests/unit/db/test_db_pool.py` ≈L60-61 的表名清单只验证表存在，本 spec 不动 |
| 共享推送链路 | `infra/gateway/gateway.py` ≈L389、≈L418、≈L529 的主动推送函数由定时任务共用；`tests/unit/gateway/test_gateway_push.py` ≈L149 用例名含 proactive，实测的是 QQ 群路由。本 spec 不碰 `infra/gateway/` |
| `PROACTIVE.md` | `iconForName.tsx` ≈L232-236 把它映射到 `experts.fileLabel.proactive`，`infra/agents/experts/publish.py` ≈L52 把它列入 `_EXPORT_ROOT_MD` 导出白名单。它是专家工作区的约定文件名，关怀服务从不读取它（只读 `SOUL.md`）。`HEARTBEAT.md` 由 `cvm-ai-doctor`、`cvm-cluster-doctor`、`news-trend`、`parenting-companion`、`stock-assistant` 五个专家携带，删除后仍有两个在用 |
| 前端 | `pages/Agent/Memory/ProactiveConfig.tsx` 与样式；`MemoryPanel.tsx` 的导入（≈L32）、`MemoryTab` 联合类型（≈L46）、标签项（≈L104-107，图标 `Bell` 仅此处使用）、`case "proactive"`（≈L263-269）；`api/modules/agent.ts` 的类型导入（≈L6-7）与 4 个方法（≈L81-97），其中 `getProactiveConfig` / `updateProactiveConfig` 指向后端不存在的 `/agent/proactive-config`；`api/types/agent.ts` 的 `ProactiveConfig`（≈L66）与 `ProactiveCareConfig`（≈L82） |

### 内容库

| 位置 | 事实 |
|---|---|
| 专家库 `src/octop/infra/agents/experts/library/` | 18 个目录加 `README.md`。拟删 7 个共 100 个受控文件。`catalog.py::_FALLBACK_BUNDLED_AVATAR_IDS`（≈L41-79）含 18 个专家 id 与 17 个 `scene-*`，与 `dashboard/public/experts/avatars/` 的 35 个 SVG 一致；`_BUNDLED_AVATAR_IDS = discover_bundled_avatar_ids()`（≈L101）。`GET /api/experts/{expert_id}` 对未知 id 抛 `NOT_FOUND`（`api/routers/experts.py` ≈L680-682）；`AgentManager._seed_expert_template`（≈L2440）遇到未知模板只记 WARNING 并跳过复制 |
| 保留专家引用已删能力 | `multi-agent-orchestrator/AGENTS.md` ≈L13 列出全部 19 个分类，≈L14 与 `SOUL.md` ≈L10 以 `marketing-content-creator` 作示例；`office-automation/skills/news/SKILL.md` 要求调用 `browser_use` 抓取外部新闻站，`SOUL.md` ≈L16、`IDENTITY.md` ≈L38、`manifest.json` 的中英文 `description` 提到该技能。`w1-02` 交接的"4 个专家 9 个文件引用 `browser_use`"中，另外 3 个专家本 spec 整体删除 |
| 专家相关测试 | `tests/unit/agents/test_clinical_learning_subscription_template.py`、`test_karpathy_knowledge_base_template.py`（整文件针对被删专家）；`test_library_task_examples.py::test_domain_experts_offer_six_task_examples` 的 `richer` 元组（≈L32-39）；`test_expert_catalog.py` ≈L64-66 与 ≈L83 的 `stock-assistant`；`tests/integration/test_experts_api.py::test_get_expert_file_contents_limited_to_preview_paths`（≈L260-270，断言 `skills/stock-info/SKILL.md`）；`tests/live/test_agent_expert_template_live.py` ≈L122-124 三条断言、`test_wechat_ops_copies_skill_scripts`（≈L167）、`test_stock_assistant_skill_references_copied`（≈L200）、≈L241 的 `template_name="news-trend"`。保留专家中带 `skills/` 的有 `ai-coding-coach`（`skills/cheatsheet/SKILL.md`）等 |
| 子智能体库 `subagents/library/{zh,en}/` | zh 272 个定义、19 个分类；en 217 个、16 个分类（比 zh 少 `hr`、`legal`、`supply-chain`）。五个待删分类：zh 43 + 20 + 7 + 6 + 9 = 85，en 36 + 5 + 7 + 6 + 9 = 63。`SubagentCatalog._scan_locale`（≈L315）以 `divisions.json` 决定扫描哪些目录，`_merge_divisions`（≈L119）对两种语言求并集，`list_divisions`（≈L460）按合并后的全量分类输出，因此两侧目录与两份 `divisions.json` 必须同改。`api/routers/subagents.py` 的路径是 `/subagent-catalog/divisions`（≈L103），安装接口对未知 slug 抛 `NOT_FOUND`（≈L195-197）。`test_subagents_api.py` ≈L106 与 `test_subagent_catalog.py` ≈L195 硬编码 `== 19` |
| 内置插件 `plugins/bundled/` | 11 个插件加 `__pycache__`。`grep -c http main.py`：`bilibili-anime` 8、`hot-topics` 13、`market-quotes` 7、`parcel-tracker` 7、`weather` 5，其余 6 个为 0。`tests/unit/test_bundled_plugins_layout.py` 的 `_EXPECTED`（≈L11-25）与 `test_offline_bundled_plugins_load` 的元组（≈L65）硬编码插件 id；`tests/unit/cli/test_init_cmd.py` ≈L43-46 断言 `octop init` 播种了 `weather`；`test_plugin_seed.py`、`test_plugins.py`、`tests/unit/backup/test_system_archive.py` 使用临时目录里的合成插件，不需要改。`infra/agents/plugins/seed.py::seed_bundled_plugins` 只复制、不清理已删插件的旧副本。仓库根 `plugins/bilibili-anime/README.md` 只是一句"已随安装包分发"的指针；`dashboard/src/pages/Chat/Weather/index.tsx`（240 行）无任何导入方 |

### 非交付工程

| 位置 | 事实 |
|---|---|
| `desktop/`、`fnos/` | 分别 73 与 49 个受控文件。仓库其余位置的引用：`README.md` / `README_CN.md` ≈L211-220 的"桌面客户端"段落与下载表；`.gitignore` ≈L3-4；`tests/unit/test_green_launch.py`（加载 `desktop/portable/templates/launch.py`）；`tests/unit/desktop/test_stamp_version.py`（加载 `desktop/src/build/stamp_version.py`，`w1-02` 删除同目录其余 6 个文件后它是唯一剩余文件）；`scripts/build-fpk.sh` ≈L73-92 与其唯一依赖 `scripts/fnos/common.sh`；`scripts/release_download_links.py` 及其单测 `tests/unit/test_release_download_links.py`，被 `release.yml` ≈L126 调用；`octop-desktop.yml`、`fnos-build-fpk.yml`、`release.yml` ≈L168 的 `trigger-fnos`。`Makefile`、`docker/`、`.dockerignore` 均不引用这两个目录；`src/octop/infra/server.py` ≈L285 与 `infra/connectors/gateway/cli_install.py` 中的"fnOS/容器内非 root"只是注释，描述的场景同样适用于容器 |
| 桌面重启分支 | 基线 `api/routers/update.py::_is_desktop_process`（≈L363）读 `self_update.green_packages_dir()` 与 `OCTOP_DESKTOP`，`_restart_desktop_process`（≈L370）调用 `os.execv`；这两个环境变量只由 `desktop/package-dev.sh` ≈L52 与 `desktop/src/process.go` ≈L27 设置。`w1-03` 删除 `update.py` 时把这段原样迁入 fork 自有的 `api/routers/service_control.py`（`_GREEN_PACKAGES_ENV`、`_is_desktop_process`、`_restart_desktop_process`、`ServiceStatusResponse.desktop`），并在其设计文档中明确交由本 spec 删除 |
| dashboard 桌面壳适配 | `utils/desktopChrome.ts::isDesktopShell`（≈L51）只在 `window._wails.invoke` 存在时返回 `true`，该对象只有被删的 Wails 壳会注入；使用方有 `App.tsx`、`layouts/Sidebar.tsx`、`layouts/PageShell.tsx`、`components/DesktopWindowControls/`、`pages/Chat/components/ChatTitleBar.tsx` 等 10 余个文件 |
| 一键安装脚本 | `scripts/install.sh`（1154 行）、`install-octop.sh`（1109 行）、`install.ps1`（381 行）、`install.bat`（257 行）；`install.sh` 从 `astral.sh` 装 uv（≈L193）、含公网 PyPI 镜像与 `--extras browser` 逻辑。引用方：`scripts/README.md` ≈L5-66、≈L88-93；`README.md` ≈L321-322 与 `README_CN.md` ≈L314-315 的"本地脚本"两行；`docs/agent-backend-file-io.md` ≈L239；`src/octop/infra/setup/service.py` ≈L189-192 的 `FileNotFoundError` 文案。`Makefile`、`docker/` 不引用它们。`scripts/wheel_build.{sh,ps1}` 与 `scripts/smoke_memory_api.py` 与安装脚本无关 |
| GitHub 工作流 | 9 个：`anti-spam-issues.yml`（issue 反垃圾）、`auto-tag-on-release.yml`（≈L78-80 触发 `release.yml`、`docker-publish.yml`、`octop-desktop.yml`）、`ci.yml`、`codeql.yml`、`docker-publish.yml`（推 Docker Hub / GHCR）、`fnos-build-fpk.yml`、`octop-desktop.yml`、`release.yml`（PyPI 与 GitHub Release，≈L151 触发 `sync-main-to-develop.yml`）、`sync-main-to-develop.yml`。`ci.yml` 只在注释与 `if` 条件里提到 sync 分支名，不引用被删文件 |
| `.cursor/` | 只有 `skills/publish/SKILL.md`（320 行），描述 GitHub + PyPI + Docker Hub 发布；`AGENTS.md` ≈L375、≈L407 与 `CONTRIBUTING.md` ≈L77 引用它；`AGENTS.md` ≈L402 与 `CONTRIBUTING.md` ≈L57、≈L122 引用 `sync-main-to-develop.yml` |
| 前端杂项 | `pages/PwaDebug/index.tsx`（703 行），`routes/index.tsx` ≈L33 懒加载、≈L284 注册 `/pwa-debug`，没有权限映射；`components/AvatarDropdown.tsx` 的 `GITHUB_URL`（≈L53）、文档站菜单项（≈L359-368，图标 `CircleHelp`）、GitHub 菜单项（≈L370-379，图标 `Github`），两个图标只在这两处使用；`dashboard/package.json` ≈L32 `"build": "^0.1.4"`（≈L8 的 `scripts.build` 是另一回事），全仓零导入，锁文件中 `build` 及其独占的 10 个传递依赖共 11 条，其中 `uglify-js` 为 1.3.5，`winston` 为 3.19.0（当前主线版本，删它的理由是零引用而不是版本风险） |
| 企业微信客户群二维码 | `docs/assets/qrcode.png`；引用方 `README.md` ≈L312（目录）与 ≈L528-536（整节）、`README_CN.md` ≈L305 与 ≈L522-530、`docs/user-guide.md` ≈L448-453（问答）与 ≈L477（图 7.1 行）。dashboard 中没有该二维码 |
| 文档 | `docs/personas.md`（123 行）全文讲 MBTI；引用方 `docs/architecture.md` ≈L163 与 `docs/api.md` ≈L281。`w1-02` 删除 `docs/acp.md` 后留下的链接：`README.md` 与 `README_CN.md` ≈L147、`docs/user-guide.md` ≈L364、`docs/user-guide.html` ≈L474、`docs/cli.md` ≈L420、`docs/architecture.md` ≈L164、`docs/api.md` ≈L339。`docs/user-guide.html` 与 `docs/octop-introduction.html` 是手工维护的签入文件，没有生成脚本 |
| `AGENTS.md` | ≈L110 `infra/agents/` 的职责列表含"MBTI personas"；≈L205 写"A few legacy endpoints (e.g. MBTI) still take `X-Octop-Agent-Id`"；≈L248-249 把 `care_push_records`、`proactive_care_config` 列为不套用资源表规范的表（两表仍存在，此描述保持正确） |

## 方案

### 1. 删除按功能链组织

每条功能链（MBTI 后端、MBTI 前端、关怀后端、关怀前端、专家、子智能体、插件、D9 与安装脚本、工作流、前端杂项、文档）是一个顶层任务，删除实现与修正连带测试在同一个提交里完成，保证每个提交 `make all` 可绿。上游同步时，被删文件若遇 modify/delete 冲突，一律保持删除；守卫测试会报出回流项。

### 2. 数据层的取舍

- **不写 fork 迁移。** 全局约束 1.1 禁止改已发布迁移。表与列留在 001 里，对全新部署只是空表与空列；存量数据清除作为可选项列入"待行方确认"。
- **保留 `AgentRow.persona_mbti` 映射，删除两个关怀仓储。** 仓储层按 AGENTS.md §5"一表一仓储、只写 SQL"镜像表结构。`agents` 表仍有该列，保留映射可以让 `repos/agents.py` 与 6 个以 `persona_mbti=None` 构造 `AgentRow` 的测试文件零改动，减少上游同步冲突；API、CLI、`AgentCreateSpec` 全部去掉该字段后，没有任何外部入口还能写入它（`create` 默认写 NULL，`update_config` 默认 `UNSET`）。两个关怀仓储的唯一消费者被删除，保留它们只是死代码，因此随 `RepoBundle` 字段一并删除。
- **`config_json` 中的 `persona` 键**：删除 `mbti.py` 后已无读取方，不迁移。

### 3. 路由删除与验证

`mbti` 与 `proactive_care` 两个路由整文件删除，同批删 `app.py` 的导入项与挂载行（全局约束第 2 节"物理删除时同批删 mount 行"），不登记 `_FORK_DISABLED_MOUNTS`。回归验证复用 `w1-02` 新增的 `tests/integration/test_removed_routes.py`：在 `REMOVED_PREFIXES` 追加 `"/api/mbti"`，在 `REMOVED_AGENT_SEGMENTS` 追加 `"/proactive-care"`，在 OpenAPI tag 断言中追加 `mbti`。

`POST /api/agents` 与 `PATCH /api/agents/{agent_id}` 删掉 `persona_mbti` 字段后，老客户端继续发送该字段会被 Pydantic 静默忽略，不报 422。这样 `test_e2e_golden_path.py` ≈L83 无需修改，也天然承担了"老客户端兼容"的回归。

### 4. 主动关怀的删除边界

只删 `infra/proactive/`、关怀路由、两个仓储与四处装配（`RepoBundle` / `SharedServices`、`AppRuntime`、`_boot_runtime` / `stop`、`AgentManager`），`infra/gateway/` 一行不动。`AppRuntime.proactive_scheduler` 是无默认值字段，删除后 `server.py` 与 `test_runtime_replace_services.py` 的构造同步去掉该实参。`tests/conftest.py` 的 autouse 夹具与 `tests/support/app.py` 的挂起代码是为了防止关怀调度的长 sleep 拖住测试，调度器删除后一并删除。

### 5. 内容库白名单守卫

新增 `tests/unit/test_content_trim_guard.py`，只检查"结构性"事实，不扫描上游叙述文档，避免每次同步都要改 README：

- 专家库目录集合等于 `EXPECTED_EXPERTS`（11 个）；
- zh / en 两侧的分类目录集合与各自 `divisions.json` 的键集合都等于 `EXPECTED_DIVISIONS[locale]`；
- `REMOVED_MODULES` 中的模块 `importlib.util.find_spec` 为 `None`；
- `REMOVED_REPO_PATHS` 中的路径在仓库根下不存在；
- 专家库中不出现 `MBTI`、`browser_use` 与已删分类 id；
- `AgentCreateBody`、`AgentPatchBody` 的 `model_fields` 与 `AgentCreateSpec` 的 dataclass 字段不含 `persona_mbti`；`octop agent create --help` 不含 `--persona-mbti`；
- `src/octop` 下的 `.py` 文件不含 `X-Octop-Agent-Id`。

插件集合已由 `tests/unit/test_bundled_plugins_layout.py::_EXPECTED` 精确断言，不重复。上游新增专家、分类或插件时，同步者按行方准入结论二选一：删除，或把新项加入白名单并在 `CHANGELOG-intranet.md` 登记。

### 6. D9 与安装脚本

- 按 D9 删除 `desktop/`、`fnos/` 及其全部连带文件（见"组件与接口"）。`w1-02` 保留的 `tests/unit/desktop/test_stamp_version.py` 在本 spec 删除，目录随之消失。
- 按 D4（容器平台交付），删除 4 个公网一键安装脚本。它们在断网环境不可用，且含已被 `w1-02` 删除的 `[browser]` 逻辑；`w1-02` 与 `w1-03` 都把它们交接给本 spec。修改 4 个合计 2900 行的脚本比删除成本高得多。行内安装物由 `w2-01` 提供、运维手册由 `w4-02` 编写。
- 删除 `service_control.py` 的桌面分支后，`POST /api/service/restart` 只在系统服务模式下可用，其它情况一律 403，与基线"非服务、非桌面进程返回 403"一致；`GET /api/service/status` 去掉 `desktop` 字段。`w1-03` 的前端 `serviceApi` 类型若带 `desktop?`，一并删除；它是可选属性，`tsc` 不会报错，所以要用 `rg` 逐个核对消费点。
- dashboard 的桌面壳适配保留：浏览器中恒为惰性，清理成本高、零收益，交 `w4-01` 酌情处理。

### 7. 工作流

只删发布、镜像推送、同步三类共 6 个工作流；`ci.yml`、`codeql.yml` 按全局约束第 3 节保留到 `w2-02` 提供替代；`anti-spam-issues.yml`、ISSUE / PR 模板不在这三类之内，本 spec 不动，交 `w2-02` 在切换行内流水线时一并处理。`.cursor/` 整体删除。

### 8. 文档处置规则

规则只有一条：**本 spec（以及 `w1-02`）删除的路径，不在仓库其余文件中留下链接或引用。** 落实方式：

- 整篇只讲已删功能或对外引流的文件直接删除：`docs/personas.md`、`docs/assets/qrcode.png`。
- 引用已删路径的行或段落就地删除：README 两份的桌面下载段、企业微信群一节及目录锚点、"本地脚本"两行、`docs/acp.md` 链接行；`docs/user-guide.md` 的客户群问答、图 7.1 行与 `docs/acp.md` 链接句；`docs/user-guide.html`、`docs/cli.md`、`docs/architecture.md` 的链接行；`docs/agent-backend-file-io.md` 提到 `scripts/install.sh` 的半句；`scripts/README.md` 的安装章节；`.gitignore` 两行；`infra/setup/service.py` 的报错文案。
- `AGENTS.md` 是 AI 代理的导航文件，除上述引用外，还要修正 ≈L110 与 ≈L205 两处因本次删除而失真的描述。
- 例外：`CHANGELOG.md` 是历史记录，`docs/api.md` 由全局约束第 5 节规定不改，二者保留原样；API 差异写进 `docs/api-intranet.md`。
- 上游叙述文档里对已删功能的文字描述（不含链接）不改写。

### 9. 锁文件

删除 `build` 依赖后，按全局约束第 5 节执行 `make relock PYPI_INDEX=<行内 PyPI 私服> NPM_REGISTRY=<行内 npm 私服>` 重生成 `dashboard/package-lock.json`，参数与 `w1-02` 上次重生成锁文件时一致；锁文件改动单独成一个提交，不手改。`w0-04` 保证 `make relock` 幂等，本 spec 不动 Python 依赖，因此 `uv.lock` 应当无变化。

## 组件与接口

### 删除

| 类别 | 路径 |
|---|---|
| MBTI 后端 | `src/octop/api/routers/mbti.py`、`src/octop/infra/agents/mbti_profiles.py`、`src/octop/infra/agents/persona.py`、`tests/unit/agents/test_persona.py`、`docs/personas.md` |
| MBTI 前端 | `dashboard/src/pages/Agent/Personalization/components/{MBTITest.tsx,MBTITest.module.less,MBTISelector.tsx,MBTISelector.module.less}`、`dashboard/src/pages/Experts/components/MbtiCatalogDrawer.tsx`、`dashboard/src/components/MbtiPersonaTag.tsx`、`dashboard/src/api/modules/mbti.ts`、`dashboard/src/api/types/mbti.ts`、`dashboard/public/assets/mbti/` |
| 主动关怀后端 | `src/octop/infra/proactive/`、`src/octop/api/routers/proactive_care.py`、`src/octop/infra/db/repos/proactive_care_config.py`、`src/octop/infra/db/repos/care_push.py`、`tests/unit/proactive/` |
| 主动关怀前端 | `dashboard/src/pages/Agent/Memory/ProactiveConfig.tsx`、`ProactiveConfig.module.less` |
| 专家 | `src/octop/infra/agents/experts/library/{clinical-learning-subscription,karpathy-knowledge-base,meituan-living-assistant,news-trend,parenting-companion,stock-assistant,wechat-ops}/`、`dashboard/public/experts/avatars/` 下同名 7 个 SVG、`src/octop/infra/agents/experts/library/office-automation/skills/news/`、`tests/unit/agents/test_clinical_learning_subscription_template.py`、`tests/unit/agents/test_karpathy_knowledge_base_template.py` |
| 子智能体 | `src/octop/infra/agents/subagents/library/{zh,en}/{marketing,game-development,paid-media,spatial-computing,sales}/` |
| 插件 | `src/octop/infra/agents/plugins/bundled/{bilibili-anime,fortune,hot-topics,market-quotes,mini-games,parcel-tracker,tetris,weather}/`、`plugins/bilibili-anime/`、`tests/unit/test_hot_topics_plugin.py`、`dashboard/src/pages/Chat/Weather/` |
| D9 与安装脚本 | `desktop/`、`fnos/`、`scripts/build-fpk.sh`、`scripts/fnos/`、`scripts/release_download_links.py`、`scripts/install.sh`、`scripts/install-octop.sh`、`scripts/install.ps1`、`scripts/install.bat`、`tests/unit/test_green_launch.py`、`tests/unit/desktop/test_stamp_version.py`、`tests/unit/test_release_download_links.py` |
| 工作流与 IDE | `.github/workflows/{octop-desktop,fnos-build-fpk,release,auto-tag-on-release,docker-publish,sync-main-to-develop}.yml`、`.cursor/` |
| 前端杂项 | `dashboard/src/pages/PwaDebug/` |
| 文档素材 | `docs/assets/qrcode.png` |

### 修改（后端）

| 文件 | 符号 | 改动 |
|---|---|---|
| `src/octop/api/app.py` | `build_app` | 删导入元组中的 `mbti`、`proactive_care` 与两条 `_RouterMount` |
| `src/octop/api/openapi_meta.py` | `API_DESCRIPTION`、`OPENAPI_TAGS` | 括注改为只写 cron reminders；删 `mbti` tag |
| `src/octop/infra/__init__.py` | 模块 docstring（≈L4） | `agents` 一行删去 "MBTI personas"，否则需求 1.6 的 `rg` 检查会命中 |
| `src/octop/api/routers/agents.py` | `AgentCreateBody`、`AgentPatchBody`、`_row_dict`、`create_agent` | 删 `persona_mbti` 字段、响应键与传参 |
| `src/octop/cli/commands/agent.py` | `create` | 删 `--persona-mbti` 选项、形参与传参 |
| `src/octop/infra/agents/manager.py` | 模块 `TYPE_CHECKING` 块、`AgentCreateSpec`、`AgentManager.__init__`、`set_proactive_scheduler`、`create`、`delete`、`apply_persona_mbti` | 删关怀调度器的导入、字段、setter 与两处调用；删 `persona_mbti` 字段与 `create` 中两处使用；删 `apply_persona_mbti` 整个方法 |
| `src/octop/infra/db/services.py` | `RepoBundle`、`SharedServices` | 删两个仓储的导入、字段、构造与 property |
| `src/octop/infra/server.py` | `AppRuntime`、`AppRuntime.replace_services`、`OctopServer._boot_runtime`、`OctopServer.stop` | 删调度器与关怀服务的导入、字段、构造、注册、启动、重绑与关闭 |
| `src/octop/api/routers/service_control.py`（`w1-03` 新增） | `_GREEN_PACKAGES_ENV`、`_is_desktop_process`、`_restart_desktop_process`、`ServiceStatusResponse.desktop`、`service_status`、`restart_service_endpoint` | 删桌面判定、`os.execv` 重启与 `desktop` 字段；`restart_service_endpoint` 的 `description` 去掉"or the desktop shell" |
| `src/octop/infra/setup/service.py` | 查找 `octop` 可执行文件处的 `FileNotFoundError`（≈L189-192） | 文案改为 "…; ensure `octop` is installed" |
| `src/octop/infra/agents/experts/catalog.py` | `_FALLBACK_BUNDLED_AVATAR_IDS` | 删 7 个专家 id（35 → 28），`scene-*` 不动 |
| 专家内容 | `default/IDENTITY.md`、`cvm-ai-doctor/USER.md`、`cvm-cluster-doctor/IDENTITY.md`、`cvm-cluster-doctor/USER.md` | 删"## MBTI 人格"标题及其列表（`default/IDENTITY.md` 其后的"说明："段保留） |
| 专家内容 | `multi-agent-orchestrator/AGENTS.md`、`SOUL.md` | 分类清单去掉 5 个已删分类；示例 slug `marketing-content-creator` 换成 `testing-api-tester`（已核实存在） |
| 专家内容 | `office-automation/SOUL.md`、`IDENTITY.md`、`manifest.json` | 删 `news` 技能的表格行、列表项与描述中的"获取办公资讯 / office news briefings" |
| 子智能体 | `subagents/library/zh/divisions.json`、`en/divisions.json` | `divisions` 删 5 项（zh 19 → 14，en 16 → 11）；`_note` 不动 |

### 修改（前端）

| 文件 | 符号 | 改动 |
|---|---|---|
| `dashboard/src/api/index.ts`、`api/types/index.ts` | `api` 聚合、类型出口 | 删 `mbtiApi` 与 `./mbti` |
| `dashboard/src/api/request.ts` | `isAgentScopedPath` | 删 `/mbti/` 分支及其注释，`/agents/<id>/` 分支不动 |
| `dashboard/src/context/AgentContext.tsx`、`AgentContext.test.ts` | `OctopAgent` | 删 `persona_mbti` |
| `dashboard/src/pages/Agent/Personalization/index.tsx` | `PersonalizationTab`、`PERSONALIZATION_TABS`、`TAB_ICONS`、`PersonalizationPage` | 删 `mbti` 标签与面板、`MBTISelector` 与 `Brain` 导入 |
| `dashboard/src/pages/Experts/components/AgentExpertsTable.tsx` | 组件体 | 删两个导入、两个 state、`openMbtiCatalog`、人格列、`onMbti` 传参与抽屉 |
| `dashboard/src/pages/Experts/components/AgentCard.tsx` | 组件体 | 删两个导入、state、人格标签、`onMbti` 传参与抽屉 |
| `dashboard/src/pages/Experts/components/AgentMoreActions.tsx` | `AgentMoreActionsProps`、`AgentMoreActions` | 删 `onMbti` 与"人格"菜单项、`Brain` 导入；与两个调用方同一提交 |
| `dashboard/src/components/AgentProfileDrawer.tsx` | 组件体 | 删导入与"人格"一行（标签文字加 `MbtiPersonaTag`） |
| `dashboard/src/pages/Settings/octop/AdminAgentCard.tsx`、`Agents.tsx` | 组件体、列定义 | 删人格标签与人格列 |
| `dashboard/src/routes/index.tsx` | `pathToKey`、`routeConfigs`、`PwaDebugPage` | 删 `/personalization/mbti`、`/mbti` 映射与重定向，删 `PwaDebugPage` 懒加载与 `/pwa-debug` 路由 |
| `dashboard/src/routes/prefetch.ts` | 预加载表 | 删 `/personalization/mbti`、`/mbti` |
| `dashboard/src/pages/Agent/Memory/MemoryPanel.tsx` | `MemoryTab`、标签项、`switch` | 删 `proactive` 标签、`ProactiveConfig` 与 `Bell` 导入 |
| `dashboard/src/api/modules/agent.ts`、`api/types/agent.ts` | `agentApi`、类型 | 删 4 个关怀方法与 2 个接口 |
| `dashboard/src/components/AvatarDropdown.tsx` | `GITHUB_URL`、菜单 | 删常量、两个外链菜单项与 `CircleHelp`、`Github` 导入 |
| `dashboard/src/api/modules/service.ts`（`w1-03` 新增） | 服务状态类型 | 若含 `desktop?: boolean` 则删除，并删除全部消费点 |
| `dashboard/package.json`、`package-lock.json` | `dependencies.build` | 删除依赖，`make relock` 重生成锁文件 |

### 修改（测试、文档与工程）

| 文件 | 改动 |
|---|---|
| `tests/conftest.py` | 删 ≈L46-69 的注释、`_PROACTIVE_SCHEDULER_TESTS` 与 `_suspend_proactive_care_loops`；`_module_path`（≈L31）仍被 ≈L37 使用，保留 |
| `tests/support/app.py::octop_client` | 删 ≈L57-62 的注释与两行调度器调用 |
| `tests/unit/db/test_runtime_replace_services.py` | 删两个导入、关怀服务与调度器的构造、`AppRuntime(proactive_scheduler=...)` 实参 |
| `tests/integration/test_personas_admin_api.py` | 删 3 个 MBTI 用例并改写模块 docstring，6 个管理员用例保留 |
| `tests/integration/test_agents_shared.py` | 删 ≈L117-122 的 `/api/mbti/apply` 请求块 |
| `tests/unit/agents/test_expert_catalog.py` | ≈L64-66、≈L83 的 `stock-assistant` 换成 `ops-engineer` |
| `tests/unit/agents/test_library_task_examples.py` | `richer` 元组只留 `ops-engineer` |
| `tests/integration/test_experts_api.py` | `test_get_expert_file_contents_limited_to_preview_paths` 改用 `ai-coding-coach` 与 `skills/cheatsheet/SKILL.md` |
| `tests/live/test_agent_expert_template_live.py` | 删 ≈L122-124 三条断言与两个专测已删专家的用例；≈L241 改为 `general-assistant` |
| `tests/integration/test_subagents_api.py`、`tests/unit/agents/test_subagent_catalog.py` | `== 19` 改为 `== 14` |
| `tests/unit/test_bundled_plugins_layout.py` | `_EXPECTED` 改为三项；离线加载元组改为 `("pomodoro", "qrcode", "server-status")` |
| `tests/unit/cli/test_init_cmd.py` | ≈L43-46 的 `weather` 换成 `pomodoro` |
| `tests/unit/api/test_service_control_router.py`（`w1-03` 新增） | 删 desktop 分支用例；新增"设置 `OCTOP_DESKTOP=1` 且非服务模式时 403"与"状态响应不含 `desktop`" |
| `tests/integration/test_removed_routes.py`（`w1-02` 新增） | 追加 `"/api/mbti"`、`"/proactive-care"` 与 `mbti` tag 断言 |
| `.gitignore` | 删 `!desktop/src/build/` 两行 |
| `scripts/README.md` | 只保留"构建 PyPI wheel"一节 |
| `README.md`、`README_CN.md` | 删 ≈L147 的 `docs/acp.md` 链接行、≈L211-220 桌面下载段、目录中的客户群锚点、"本地脚本"两行、客户群一节 |
| `docs/user-guide.md` | 删 ≈L364 的 `docs/acp.md` 链接句、≈L448-453 客户群问答、≈L477 图 7.1 行 |
| `docs/user-guide.html`、`docs/cli.md`、`docs/architecture.md`、`docs/agent-backend-file-io.md` | 删 `docs/acp.md` / `personas.md` 链接与提到 `scripts/install.sh` 的半句 |
| `AGENTS.md` | ≈L110 删"MBTI personas"；≈L205 改写为"所有 Agent 路由都在 URL 中带 `agent_id`，后端不再读取 `X-Octop-Agent-Id`"；≈L375、≈L407 删 `.cursor/skills/publish`；≈L402 把"Actions syncs … (`sync-main-to-develop.yml`; …)"改为"合并后手工把 `main` 合回 `develop`"。不触及 §7 Database 段 |
| `CONTRIBUTING.md` | ≈L57、≈L122 删 `sync-main-to-develop.yml` 的描述；≈L77 删 `.cursor/skills/publish` 一行 |
| `CHANGELOG-intranet.md`、`docs/api-intranet.md` | 见任务 14 |

### 新增

| 文件 | 内容 |
|---|---|
| `tests/unit/test_content_trim_guard.py` | 白名单守卫，见下 |
| `tests/integration/test_content_trim_api.py` | 用 `tests/integration/conftest.py::env` 夹具：`persona_mbti` 在创建与修改时被忽略；以已删模板创建 Agent 返回 201；`GET /api/experts/news-trend` 返回 404；`GET /api/subagent-catalog/divisions` 返回 14 条且 `count > 0`；安装 `marketing-content-creator` 返回 404；`srv.app_runtime` 没有 `proactive_scheduler` 属性 |
| `dashboard/src/routes/contentTrim.test.ts` | `routeConfigs` 不含 `/mbti`、`/pwa-debug`；`pathToKey` 不含 `/mbti`、`/personalization/mbti` |

`tests/unit/test_content_trim_guard.py` 的骨架：

```python
"""Intranet content-trim guard: removed C-end content must not flow back from upstream."""

EXPECTED_EXPERTS: frozenset[str]            # 11 ids
EXPECTED_DIVISIONS: dict[str, frozenset[str]]  # {"zh": 14 ids, "en": 11 ids}
REMOVED_DIVISIONS: frozenset[str]           # marketing, game-development, paid-media, spatial-computing, sales
REMOVED_MODULES: tuple[str, ...]            # octop.infra.proactive, octop.infra.agents.mbti_profiles,
                                            # octop.infra.agents.persona, octop.api.routers.mbti,
                                            # octop.api.routers.proactive_care,
                                            # octop.infra.db.repos.care_push,
                                            # octop.infra.db.repos.proactive_care_config
REMOVED_REPO_PATHS: tuple[str, ...]         # 相对仓库根的 POSIX 字符串，用 Path(*s.split("/")) 拼接

def test_expert_library_matches_allowlist() -> None: ...
def test_subagent_divisions_match_allowlist() -> None: ...
def test_removed_modules_are_not_importable() -> None: ...
def test_removed_repo_paths_absent(repo_root: Path) -> None: ...
def test_expert_library_has_no_removed_capability_refs() -> None: ...
def test_agent_models_and_cli_have_no_persona_mbti() -> None: ...
def test_backend_does_not_read_agent_id_header() -> None: ...
```

所有断言失败时都输出"多出的项 / 缺少的项"两个排序列表，便于同步者定位；只用 `pathlib` 与 `encoding="utf-8"`，遵守 AGENTS.md §7 的跨平台约定。

`service_control.py` 删除桌面分支后的接口：

```python
class ServiceStatusResponse(BaseModel):
    current_version: str = Field(..., description="Installed octop package version")
    service_mode: str | None = Field(None, description="systemd / launchd when run as a system service")

@router.post(
    "/restart",
    summary="Restart the Octop system service",
    description="Requires the service_control permission. Only works under OCTOP_SERVICE_MODE.",
    response_model=ServiceRestartResponse,
)
async def restart_service_endpoint(...) -> ServiceRestartResponse: ...
```

## 数据模型

无。本 spec 不新增、不修改任何表、列、索引或迁移，不写 fork 迁移，`_schema_version` 保持 15，`_fork_schema_version` 不受影响。

- `agents.persona_mbti`：列保留，全新部署下恒为 NULL；`AgentRow.persona_mbti` 映射保留。
- `proactive_care_config`、`care_push_records`：表与索引保留，全新部署下恒为空；`proactive_care_config` 对 `agents` 的外键带 `ON DELETE CASCADE`，删除 Agent 不受影响。
- 如果行方要求清除存量残留，可选追加一对 `forkNNN_purge_c_end_residue`（`.sql` 与 `.pg.sql`）：`UPDATE agents SET persona_mbti = NULL`、`DELETE FROM proactive_care_config`、`DELETE FROM care_push_records`，外加一个 Python 步骤从 `agents.config_json` 删除 `persona` 键。它走 `w0-01` 的 fork runner，不改 `test_db_pool.py` 的 `v == 15`。默认不做。

## 配置

无新增、删除或修改的 `config.py` 配置键。

随代码删除而失效的环境变量（不在 `config.py` 中，记入 `CHANGELOG-intranet.md`）：`OCTOP_DESKTOP`、`OCTOP_GREEN_PACKAGES`。`config.json` 中 `plugins.<已删插件 id>` 与 `bundled_plugins_seeded` 里的旧 id 在存量实例上保留为无害的残值。

## 错误处理

不新增 `ErrorCode`，也不删除任何 `ErrorCode`（`test_errors.py` 的三方相等门禁不受影响）。

| 场景 | 行为 | 错误码 |
|---|---|---|
| 请求已删路由（`/api/mbti/*`、`/api/agents/{id}/proactive-care`） | FastAPI 无匹配路由；`GET` 返回 404。挂载了 SPA 兜底路由时，`/api/` 前缀的 `GET` 仍返回 404，其它方法可能是 405 | 无（框架默认） |
| 请求已删专家 `GET /api/experts/{id}` | 沿用既有逻辑 | `NOT_FOUND`（404） |
| 安装已删分类下的子智能体 | 沿用既有逻辑 | `NOT_FOUND`（404） |
| 以已删专家为模板创建 Agent | 沿用既有逻辑：创建成功、跳过复制、记 WARNING | 无 |
| 非系统服务模式下调用 `POST /api/service/restart`（含设置了 `OCTOP_DESKTOP` 的进程） | 与基线非服务、非桌面进程一致 | `FORBIDDEN`（403） |
| 请求体带 `persona_mbti` | Pydantic 忽略未知字段 | 无 |

## 安全考虑

- **个人信息最小化**：删除 MBTI 测评（答卷提交与人格推断）与主动关怀（默认对全部 Agent 开启、读取带负面情绪加权的情绪日记并交给 LLM 生成文案、未经用户授权主动推送）。情绪日记的采集侧仍在，由 `p2-04` 评估。
- **攻击面收缩**：减少 9 个 HTTP 端点；后端不再有任何读取 `X-Octop-Agent-Id` 请求头的代码，dashboard 仍会为 `/agents/<id>/` 路径发送该头，但无人读取，无害；`/pwa-debug` 不再向登录用户暴露 Service Worker 与缓存内部状态；`service_control.py` 不再存在"设置一个环境变量即可让 `service_control` 持有者触发 `os.execv` 重启"的旁路。
- **外联收缩**：删除 5 个直连公网的内置插件、3 个依赖公网或 `browser_use` 的专家、1 个抓取外部新闻站的技能、4 个从 GitHub / 公网 PyPI / `astral.sh` 拉取安装物的脚本、头像菜单的两个公网链接。
- **供应链**：删除零引用的 `build@0.1.4`，同时去掉 `uglify-js@1.3.5` 等 10 个传递依赖；删除携带 PyPI、Docker Hub 等发布凭据引用的 GitHub 工作流。
- **不在本 spec 内**：删除代码不等于删除数据，存量实例上的人格值、关怀记录、已播种的旧插件副本不会被自动清除（见"待行方确认"）；`ci.yml` 中 `live-tests` 作业引用的外部凭据由 `w2-02` 处理。

## 测试策略

所有新测试先写、先确认失败，再删实现。

| 类别 | 内容 | 本地命令 |
|---|---|---|
| 单测：守卫 | `tests/unit/test_content_trim_guard.py` 全部用例 | `uv run pytest tests/unit/test_content_trim_guard.py -q` |
| 单测：受影响模块 | 专家目录、子智能体目录、插件布局、`octop init`、运行时重绑、管理器、服务控制 | `uv run pytest tests/unit/agents/test_expert_catalog.py tests/unit/agents/test_library_task_examples.py tests/unit/agents/test_subagent_catalog.py tests/unit/agents/test_agent_manager.py tests/unit/test_bundled_plugins_layout.py tests/unit/cli/test_init_cmd.py tests/unit/db/test_runtime_replace_services.py tests/unit/db/test_db_pool.py tests/unit/api/test_service_control_router.py -q` |
| 单测：不应受影响 | 定时推送、cron、i18n 四条门禁、插件播种与归档 | `uv run pytest tests/unit/gateway/test_gateway_push.py tests/unit/cron tests/unit/i18n tests/unit/test_plugin_seed.py tests/unit/test_plugins.py tests/unit/backup/test_system_archive.py -q` |
| 集成 | 已删路由、内容裁剪 API、Agent 共享、管理员接口、专家与子智能体 API、黄金路径 | `uv run pytest tests/integration/test_removed_routes.py tests/integration/test_content_trim_api.py tests/integration/test_agents_shared.py tests/integration/test_personas_admin_api.py tests/integration/test_experts_api.py tests/integration/test_subagents_api.py tests/integration/test_e2e_golden_path.py -q` |
| live | 只验证可收集 | `uv run pytest tests/live --collect-only -q` |
| 全量 | ship bar | `make all` |
| 前端 | 类型、lint、vitest（`w0-02` 已让 CI 执行） | `cd dashboard && npx tsc -b && npm run lint && npx vitest run src/routes src/context src/pages/Agent/Memory src/utils/desktopChrome.test.ts && npm run test` |
| 前端依赖 | 锁文件条目与安装 | `cd dashboard && npm ci && npm ls build`（`npm ls` 应输出空树并以非零码退出） |
| PG | 本 spec 不改表结构与仓储 SQL，只需确认无回归 | `OCTOP_TEST_DATABASE_URL=postgresql://… make test-postgresql`（专用库，见 `w0-02`） |
| 悬空引用 | 需求 11.2 | 见下方命令 |
| 手工冒烟 | 全新库起服 → 登录 → 用 `general-assistant` 模板建 Agent → 对话一轮 → 依次打开专家页、个性化页各标签、记忆页各标签、插件管理页、管理后台 Agents 表 → 访问 `/mbti`、`/pwa-debug` 看到 404 页；确认无空分类、无裸 i18n 键、无控制台报错 | `uv run octop run` |

悬空引用检查（需求 11.2，退出码 1 即通过）：

```bash
! rg -n --hidden -g '!.git/**' -g '!.kiro/**' -g '!**/node_modules/**' \
  -g '!CHANGELOG.md' -g '!CHANGELOG-intranet.md' -g '!docs/api.md' -g '!docs/api-intranet.md' \
  -g '!docs/intranet/**' -g '!tests/unit/test_content_trim_guard.py' \
  -g '!src/octop/infra/agents/subagents/library/**' \
  -e 'desktop/(README\.md|src/|portable/)' -e 'fnos/(README|docker|native)' \
  -e 'scripts[/\\](build-fpk\.sh|fnos/|release_download_links\.py|install(-octop)?\.(sh|ps1|bat))' \
  -e '\.cursor/skills' -e 'personas\.md' -e 'assets/qrcode\.png' \
  -e 'docs/acp\.md|\(\./acp\.md\)|\(acp\.md\)' \
  -e '(octop-desktop|fnos-build-fpk|docker-publish|auto-tag-on-release|sync-main-to-develop|release)\.yml' .
```

排除子智能体库是因为 `specialized/zk-steward.md` 引用的是外部仓库的 `.cursor/skills` 布局，与本仓库无关。

## 与其他 spec 的交接

**依赖：**

| spec | 使用的交付物 |
|---|---|
| `w0-02-ci-gates` | CI 的前端作业与 vitest 执行；`make check-frontend`、`make install-frontend`、`make test-postgresql`。按其约定，删除前端组件时同批删除对应 vitest 文件（本 spec 删除的组件均无专属 vitest 文件） |
| `w0-03-test-auth-baseline` | `tests/integration/conftest.py::env` 与 `tests/support/auth.py` 新基线 |
| `w0-04-fork-isolation-points` | `make relock`、`CHANGELOG-intranet.md`、`docs/api-intranet.md`、上游同步手册中"modify/delete 冲突保持删除"的规则 |
| `w1-02-capability-trim` | `tests/integration/test_removed_routes.py` 的 `REMOVED_PREFIXES` / `REMOVED_AGENT_SEGMENTS`；已删除 `AiPanel.tsx`、`pages/Agent/ACP/`、`infra/desktop/` 与 `tests/unit/desktop/` 下另外 6 个文件、`docs/acp.md` |
| `w1-03-online-fetch-trim` | 已删除 `self_update.py`、`update.py`、`update_store.py`、`UpdateConfig.tsx`、`update.ts`；新增 `service_control.py`、`service.ts`、`test_service_control_router.py`，本 spec 在其上删桌面分支 |

**已承接的交接项：**

- `w1-02`：4 个专家引用 `browser_use` —— 3 个随专家删除，`office-automation` 删 `news` 技能；`scripts/install.*` 与 `scripts/README.md` 的 playwright / `[browser]` 逻辑 —— 随脚本删除；`docs/acp.md` 留下的 7 处链接 —— 除 `docs/api.md` 外全部删除；`fnos/docker/Dockerfile` 的 `.[desktop]` —— 随 `fnos/` 删除。
- `w1-03`：`service_control.py` 的桌面分支 —— 删除；一键安装脚本 —— 删除；README、`docs/cli.md`、`docs/user-guide.md` 中 `octop update` 与一键安装的叙述段落 —— 本 spec 只删指向已删仓库路径的行，段落重写交 `w4-02`；`manifest_generator.py` 死代码 —— 与内容裁剪无关，不处理。
- `w1-01`：`pages/Settings/octop/Providers.tsx` 与 `ProviderInfo.current_api_key` 死代码 —— 决定保留，理由同上。

**交付给：**

| spec | 交付内容 |
|---|---|
| `w1-05-saas-decoupling` | 若删除 `cvm-ai-doctor`、`cvm-cluster-doctor`、`tencentcloud-api`，需同步修改 `test_content_trim_guard.py::EXPECTED_EXPERTS`、`catalog.py::_FALLBACK_BUNDLED_AVATAR_IDS` 与对应头像；被删专家用过的 `tencent-news`、`meituan-travel` 连接器已无内置专家依赖 |
| `w2-01-offline-build` | `pyproject.toml` 的 `desktop` extra 已无消费者，可在依赖收敛时删除；一键安装脚本已删，行内安装物（镜像 / 离线包）由其提供；本 spec 删除 `build` 依赖后已 relock 一次 |
| `w2-02-supply-chain-compliance` | `.github/` 下剩余 `ci.yml`、`codeql.yml`、`anti-spam-issues.yml`、`codeql/`、`ISSUE_TEMPLATE/`、`pull_request_template.md`，切换行内流水线时一并处理；SBOM 中不再有 `uglify-js@1.3.5` 等 11 个 npm 包与被删插件 |
| `w3-02-audit-baseline` | 无需为 MBTI、主动关怀写审计埋点 |
| `w3-04-session-and-password` | 后端已无读取 `X-Octop-Agent-Id` 的代码，令牌与请求头整改不必考虑它 |
| `w4-01-frontend-baseline` | 桌面壳适配代码（`desktopChrome.ts` 等）惰性保留，可选清理；PWA 整体下线与其余外链不在本 spec。`AvatarDropdown.tsx` 的 GitHub 与文档站两个链接已由本 spec 删除（`w1-03` 的范围外表曾把它划给 `w4-01`，以本 spec 的分配为准），`w4-01` 不再重复 |
| `w4-02-ops-minimum` | 运维手册需替代被删的一键安装脚本与 README 安装段落 |
| `p2-04-content-security-pii` | 主动关怀已删，情绪日记采集侧仍在，需评估个人信息最小化 |
| `p2-10-office-skills-rewrite` | `office-automation` 已无 `news` 技能 |

**看似相关、但不归本 spec：** i18n 孤儿键清理（全局约束 1.2 禁止）；`scene-*` 头像与专家市场（`w1-03`）；通道平台链接、云验证码、在线语音（`w1-05`）；`pages/Agent/Memory/VectorSearchConfig.tsx` 等调用不存在接口的死代码与 `agent.ts` 中指向 `/agent/heartbeat-config` 的旧路径（登记，不处理）。

## 风险与回滚

| 风险 | 等级 | 缓解 |
|---|---|---|
| 上游同步时，`api/app.py`、`manager.py`、`routes/index.tsx`、README 与内容库发生 modify/delete 或相邻行冲突 | 中 | 删除都是整段连续块；冲突时一律保持删除；守卫测试与 `test_removed_routes.py` 会拦下回流项 |
| 上游新增专家、子智能体分类或插件静默回流 | 中 | 守卫测试与 `test_bundled_plugins_layout.py` 的精确集合断言让 CI 变红，由同步者按准入结论处理 |
| 只删一侧语言的子智能体目录或只删目录不改 `divisions.json`，出现空分类或英文界面残留 | 中 | zh / en 与两份 JSON 在同一任务内修改；守卫测试同时比对目录与 JSON；集成测试断言 `count > 0` |
| `AgentMoreActions` 的必填 prop 与两个调用方不同步 | 低 | 三个文件同一提交修改，`tsc -b` 兜底 |
| `service.ts` 的 `desktop?` 是可选属性，删除后 `tsc` 不报遗漏的消费点 | 低 | 用 `rg -n 'desktop' dashboard/src/api/modules/service.ts dashboard/src/hooks dashboard/src/pages/Settings` 逐个核对 |
| 删除关怀调度器后仍有代码路径创建长 sleep 任务，导致测试挂起 | 低 | 守卫断言模块不可导入；`AppRuntime` 字段删除后遗留调用会在 mypy 阶段失败 |
| 锁文件在离线 npm 私服上重生成失败或 registry 不一致 | 中 | 用 `make relock NPM_REGISTRY=…`，锁文件单独提交；`npm ci` 必须通过 |
| 存量实例上残留旧插件副本、人格值与关怀记录 | 低 | 行内为全新部署；若有试点实例，按"待行方确认"决定是否追加清除步骤 |
| 删除后测试覆盖率下降（删除测试代码逾 2000 行） | 低 | 被删测试都针对被删代码；若行内设覆盖率门禁，按新基线调整阈值 |

**回滚：** 每个顶层任务一个提交，可按提交逆序 `git revert`。本 spec 不写迁移、不改表结构，回滚不涉及数据修复；锁文件回滚后需再执行一次 `make relock`。

## 待行方确认

- **D9（`desktop/`、`fnos/`）**：按默认假设"不交付"删除。若答复为交付，则本 spec 保留这两个目录、`tests/unit/test_green_launch.py`、`tests/unit/desktop/test_stamp_version.py`、`scripts/build-fpk.sh`、`scripts/fnos/` 与 `octop-desktop.yml`、`fnos-build-fpk.yml`，`service_control.py` 保留桌面分支，并由 `w2-01`、`w2-02`、`w3-04`、`w3-05` 各自补打包渠道改动；工作量约减 1 人日。
- **D4（部署形态）**：一键安装脚本的删除以"容器平台交付"为前提。若行方要求虚拟机或物理机直装，改为保留 `scripts/install.sh` 并由 `w2-01` 改写为离线安装器（去掉公网源与 `[browser]` 逻辑），本 spec 只删 `install.ps1`、`install.bat` 与 `install-octop.sh`。
- 以下两项不在 steering 第 4 节，建议补入：
  - **存量数据清除**：默认不清除 `agents.persona_mbti`、`config_json.persona`、两张关怀表的行与 `~/.octop/plugins/` 下的旧插件副本。若等保测评要求"删除即无痕"，追加 `forkNNN_purge_c_end_residue` 与一个插件目录清理步骤，约 0.5 人日。
  - **`.github/` 中非发布类文件的去留**：`anti-spam-issues.yml`、`ISSUE_TEMPLATE/`、`pull_request_template.md` 在行内平台上不生效，本 spec 按范围保留，建议 `w2-02` 与 `ci.yml` 一并迁移或删除。
