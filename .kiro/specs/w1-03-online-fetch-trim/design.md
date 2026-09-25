# 设计文档：外网获取类功能裁剪

> spec：`w1-03-online-fetch-trim` ｜ 波次：Wave 1 ｜ 基线：`757fd12` ｜ 预估：18 人日
> 前置：`w0-01-fork-migration-namespace`、`w0-02-ci-gates`、`w0-03-test-auth-baseline`、`w0-04-fork-isolation-points`、`w1-02-capability-trim` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 概述

**结论：** 七类运行期外网获取功能全部物理删除，不走能力开关，也不登记 `_FORK_DISABLED_MOUNTS`。原因是这些端点的实现本身就是出网代码，只摘路由会把几千行出网代码和公网域名留在仓库里，`w2-01` 的全量出网门禁因此无法收紧。删除后补回两项离线能力：

1. **服务重启**：`POST /api/update/restart` 的逻辑原样迁入 fork 自有的 `api/routers/service_control.py`，路径改为 `/api/service/restart`；再加一个不联网的 `GET /api/service/status`，替代原 `/api/update/status` 里"当前版本 + 服务模式"这部分。权限键 `update` 更名为 `service_control`，由一对 fork 迁移把存量用户的 `update` 换成 `service_control`。
2. **HTTPS**：删掉 ACME 签发、挑战路由、自动续期、预检与 `acme`、`josepy` 依赖，新增 `POST /api/admin/tls/certificate` 上传行内证书。校验逻辑放在 fork 自有的 `infra/setup/tls/upload.py`。上传模式默认 `http_port=0`，即不启动 80 端口伴随应用。

改动面的分布：

| 类别 | 删除的文件 | 大幅修改的上游文件 | fork 自有新文件 |
|---|---|---|---|
| 自更新 | `infra/setup/self_update.py`、`api/routers/update.py`、`api/routers/update_store.py`、`cli/commands/update.py`，前端 9 个文件 | `app.py`、`permissions.py`、`Sidebar.tsx`、`Header.tsx` | `api/routers/service_control.py`、`infra/db/fork_permission_keys.py`、`migrations/forkNNN_service_control_permission{,.pg}.sql`、`dashboard/src/api/modules/service.ts`、`dashboard/src/hooks/useServiceStatus.ts` |
| 技能 / 专家市场 | `infra/skills/{skills_hub,skillhub_market,skill_package_from_skillhub}.py`、`infra/agents/experts/{skillhub_market,market_creation}.py`，前端 9 个文件 | `api/routers/{skills,skill_packages,experts}.py`、`SkillPackages/index.tsx`、`Experts/index.tsx` | 无 |
| 插件 | 前端 `PluginMarketPanel.tsx` | `api/routers/plugins.py`、`plugins/manager.py`、`cli/commands/plugin.py` | 无 |
| 模型 | `api/routers/ollama_download_store.py`、`infra/agents/providers/onnx_download.py`，前端 `onnxDownloadWatcher.ts` | `ollama_models.py`、`onnx_models.py`、`knowledge_bases.py`、`onnx_service.py`、`ProviderConfigModal.tsx`、`KnowledgeBases/index.tsx` | 无 |
| TLS | `infra/setup/tls/{acme_issue,challenge,preflight,renewal,modes}.py` | `tls/manager.py`、`tls/store.py`、`api/routers/tls.py`、`HttpsSettings/index.tsx` | `infra/setup/tls/upload.py` |

本 spec 不新增配置键；新增 1 个 `ErrorCode`、1 个权限键（替换 `update`）、1 对 fork 迁移与 1 个迁移 Python 步骤；不改任何上游 i18n JSON。

## 现状

以下事实均在基线 `757fd12` 上用 `rg` / `sed -n` / `wc -l` 核实。行号只作提示。

### 自更新与版本检查

- `src/octop/infra/setup/self_update.py`（732 行）：`_PYPI_URL = f"https://pypi.org/pypi/{_PACKAGE_NAME}/json"`（≈L24），`_GREEN_PACKAGES_ENV = "OCTOP_GREEN_PACKAGES"`（≈L25），`_MIRRORS` 含腾讯、阿里、清华、中科大四个公网镜像（≈L27）。`green_packages_dir()`（≈L51）读 `OCTOP_GREEN_PACKAGES`，`get_local_version()`（≈L102）读 `importlib.metadata.version("octop")`，失败时返回 `"0.0.0"`。
- `src/octop/api/routers/update.py`（412 行）：`router = APIRouter(prefix="/update", tags=["update"])`（≈L46），`_STABLE_ONLY_KEY = "update.stable_only"`（≈L48）。
  - `GET /status`（≈L186）只挂 `current_user`。缓存未命中时，经 `_build_status`（≈L132）调 `fetch_pypi_info()` 访问 PyPI。所以**任何已登录用户**都能触发外联。
  - `POST /check`（≈L203）、`PATCH /settings`（≈L230）、`POST /upgrade`（≈L315，工作函数 `_upgrade_worker` ≈L252）、`GET /progress`（≈L343）都用 `require_permission("update")`。
  - `_is_desktop_process`（≈L363）读 `green_packages_dir()` 与 `OCTOP_DESKTOP`；`_restart_desktop_process`（≈L370）用 `os.execv`；`_restart_service_task`（≈L376）调 `infra/setup/service.py::restart_service`（≈L777）。`POST /restart`（≈L383-412）用 `require_permission("update")`（≈L386），逻辑是：desktop 进程就在后台 `execv`；否则调 `detect_service_mode()`（`service.py` ≈L87，读 `OCTOP_SERVICE_MODE`），为 `None` 时抛 `FORBIDDEN`；再用 `build_runtime` 与 `is_service_installed` 校验，失败抛 `INTERNAL_ERROR`；最后在后台调用 `restart_service`。
  - `_present_status`（≈L92）返回的 `service_mode` 来自 `detect_service_mode()`，`desktop` 来自 `_is_desktop_process()`。
- `src/octop/api/routers/update_store.py`（85 行）只服务于上述缓存与升级任务。
- `src/octop/cli/commands/update.py`（78 行）调用 `fetch_pypi_info`；在 `src/octop/cli/registry.py` 的 `COMMANDS` 中注册（≈L31）。
- `src/octop/api/app.py`：≈L186 在路由导入列表里导入 `update`，≈L261 为 `_RouterMount(update.router, "/api", ["update"])`。
- `src/octop/api/openapi_meta.py` ≈L144 为 `{"name": "update", ...}`。
- `src/octop/api/deps.py` 的 `_JWT_EXEMPT_PREFIXES` / `_JWT_EXEMPT_EXACT`（≈L66-88）不含任何 `/api/update` 路径，删除后不需要清理豁免项。
- dashboard：
  - `api/modules/update.ts` 导出 `updateApi`（`getUpdateStatus`、`checkForUpdates`、`patchSettings`、`triggerUpgrade`、`getUpgradeProgress`、`restartService`），在 `api/index.ts` ≈L17 导入、≈L40 展开。
  - **`components/PwaUpdatePrompt/index.tsx` 确实引用了 `updateApi`**：≈L4 导入，≈L29-32 挂载时调 `getUpdateStatus()` 取 `service_mode`，≈L42 调 `restartService()`。它挂在主布局里，因此它本身就是"每次打开控制台就查 PyPI"的一个触发点。编排方给的"S03 复核说它并未引用 `updateApi`"与源码不符，源分析的复核结论（引用了）才是对的。
  - `hooks/useServiceRestart.ts` ≈L4 导入、≈L167 调 `updateApi.restartService()`；它经 `context/ServiceRestartContext.tsx`（全局确认与等待遮罩）提供 `requestRestart`。基线上调用 `requestRestart` 的只有 `pages/Settings/HttpsSettings/index.tsx`（≈L59、≈L240）与将被删除的 `UpdateConfig.tsx`（≈L158）；`pages/Settings/BackupRestore/index.tsx` 只读取 `isRestarting`（≈L171）。
  - `pages/Settings/HttpsSettings/index.tsx` ≈L12 导入 `updateApi`，≈L80-84 调 `getUpdateStatus()` 取 `service_mode`，决定是否显示"重启服务"按钮。
  - `hooks/useUpdateStatus.ts`（及 `.test.ts`）、`utils/updateStatusCache.ts`（及 `.test.ts`）、`components/AppVersionBadge/`、`pages/Settings/AdvancedSettings/UpdateConfig.tsx` 与 `UpdateConfig.module.less` 只服务升级链路。
  - `layouts/Header.tsx`：≈L4、L5 导入两个角标，≈L92、L93 渲染。`layouts/Sidebar.tsx`：≈L6、L7 导入角标，≈L13 导入 `useUpdateStatus`；`hasUpdate` 共 10 处（≈L121、131、193、264、316、358、384、531、556、566），其中 ≈L193 是"应用设置"红点；≈L474-475 渲染两个角标。
  - `components/CurrentVersionBadge/index.tsx`：≈L19 取 `useUpdateStatus().status.current_version`；≈L24 以 `userCan(user, "update")` 决定是否可点击，点击后跳转 `/admin/advanced?tab=updates`。
  - `components/AvatarDropdown.tsx` ≈L391-402 有 `userCan(user, "update")` 控制的"检查更新"菜单项（`account.checkUpdates`），`RefreshCw` 在 ≈L25 导入。**源分析"该文件没有检查更新入口"的结论不成立。** 同文件 ≈L53 的 `GITHUB_URL` 与 ≈L361 的文档链接属于外链，归 `w4-01`。
  - `pages/Settings/AdvancedSettings/index.tsx`：≈L6 `RefreshCw`、≈L15 `import UpdateConfig`、≈L29 `"updates"`、≈L38 标签定义、≈L46 `parseTab`、≈L81-82 渲染分支。
  - `routes/index.tsx` ≈L240-241 与 ≈L273-274 是 `/admin/updates`、`/updates` 两条重定向。
  - `utils/permissions.ts`：≈L28 `advancedPage` 含 `"update"`，≈L64 `updates: "update"`，≈L154 `pathname.startsWith("/admin/updates")`。
- 权限：`src/octop/infra/users/permissions.py` 的 `"update"`（≈L198-206，label "应用更新" / "Updates"，page `advanced`）；`ALL_PERMISSION_KEYS = set(PERMISSIONS)`（≈L218）；`validate_permission_keys`（≈L237）对未知键抛 `ValueError`。权限选择器的数据来自 `GET /api/users/permissions`（`api/routers/users.py` ≈L126，遍历 `PERMISSIONS`），前端 `UsersListPanel.tsx` ≈L1069 动态读取，没有硬编码键名。
- `users.permissions` 在 SQLite 下是 `TEXT`（JSON 数组），在 PG 下是 `JSONB`（`migrations/006_user_permissions{,.pg}.sql`）；`UserRepo.set_permissions`（`infra/db/repos/users.py` ≈L304）在两种方言上都用 `UPDATE users SET permissions = ? WHERE id = ?`，参数为 `json.dumps` 的结果；`_parse_permissions`（≈L13）兼容 list 与 JSON 字符串。
- `tests/unit/api/test_acl_gate_coverage.py`：`GATED_FILES` 中 `"routers/update.py"` 位于 ≈L25（源分析写的 L23 是 `routers/tls.py`）；测试会 `read_text` 列表中的每个文件，并用 AST 校验 `require_permission` 的字面量属于 `ALL_PERMISSION_KEYS`。
- `tests/support/auth.py` 的新基线（`w0-03`）按运行期 `sorted(ALL_PERMISSION_KEYS)` 给管理员授权，改键不需要改夹具。

### SkillHub 技能市场

- `src/octop/api/routers/skills.py`（1417 行）：
  - `_SKILLHUB_INSTALL_URL`（≈L75-76）指向腾讯云 COS 上的 `install/install.sh`。
  - `_resolve_skillhub_bin`（≈L227）、`_close_subprocess`（≈L243）、`_install_skillhub_cli`（≈L264，用 `asyncio.create_subprocess_exec` 先起 `curl` 再把输出喂给 `bash`）、`_ensure_skillhub_cli`（≈L327）、`_run_skillhub_cmd`（≈L335）、`_upgrade_skillhub_cli`（≈L360）、`_map_skillhub_install_error`（≈L377）、`_skillhub_cli_failure_detail`（≈L403）、`_skillhub_stderr_suggests_upgrade`（≈L414）。
  - `_valid_skillhub_icon_url`（≈L173-176）只被 `tests/unit/test_skillhub_install_metadata.py` 使用。
  - `LocalizedSkillCopy`（≈L1078）、`HubInstallBody`（≈L1083）、`_download_skillhub_package_via_cli`（≈L1092）、`_parse_skillhub_search_output`（≈L1152）。
  - 三个端点：`GET /agents/{agent_id}/skills/hub/search`（≈L1213）、`/hub/rankings`（≈L1271）、`POST /hub/install`（≈L1307，先用 HTTP 下载，失败再走 CLI）。
- `src/octop/api/routers/skill_packages.py`（772 行）：
  - 导入 `infra/agents/experts/skillhub_market`（≈L14）、`skill_package_from_skillhub`（≈L22）与 `infra/skills/skillhub_market`（≈L28）；`_SAFE_SKILLHUB_REASONS`（≈L35）、`FromSkillHubBody`（≈L61）、`_map_skillhub_error`（≈L212）。
  - 端点：`GET /hub/search`（≈L270）、`GET /hub/rankings`（≈L291）、`POST /from-skillhub`（≈L337）、`POST /{package_id}/skills/hub/install`（≈L659）。
  - `_icon_url`（≈L205）调用 `infra/skills/install.py::valid_skillhub_icon_url`，校验**本地技能包**创建与修改（≈L328、≈L398）时的 `icon_url` 字段。它不是 SkillHub 专用逻辑，必须保留。
- `src/octop/infra/skills/skillhub_market.py`（440 行，`DEFAULT_SKILLHUB_HOST = "https://api.skillhub.cn"` ≈L27，读 `SKILLHUB_HOST`）与 `skill_package_from_skillhub.py`（83 行）只服务市场。
- `src/octop/infra/skills/install.py`（221 行）：≈L10 `from octop.infra.skills import skills_hub`；`with_skillhub_presentation_metadata`（≈L44）、`prepare_skillhub_package`（≈L88）、`resolve_url_import`（≈L124，调 `skills_hub.resolve_bundle_from_url`）、`install_skill_from_url`（≈L157）、`install_skill_from_skillhub`（≈L175）是市场与 URL 导入专用；`commit_skill_install`（≈L142）被 ZIP 与本地流程复用；`_valid_skillhub_icon_url` / `valid_skillhub_icon_url`（≈L39、≈L206）被 `skill_packages.py::_icon_url` 复用。
- `src/octop/infra/skills/__init__.py` 的 docstring（≈L1）与再导出（≈L5-13）、`__all__`（≈L25-41）含 `install_skill_from_skillhub`、`install_skill_from_url`、`prepare_skillhub_package`、`resolve_url_import`。
- 内置技能 `src/octop/infra/agents/builtin_skills/skill-manager/`：`SKILL.md` ≈L3（description）、≈L32、≈L40-41、≈L54 提到 SkillHub；`scripts/manage_skills.py` 的 `_skillhub_source`（≈L98）、`_materialize` 中的 SkillHub 分支（≈L319-329）、`_effective_name`（≈L558）、`_skillhub_search`（≈L596）、`skillhub-search` 子命令（≈L644、≈L672）。对应测试 `tests/unit/agents/test_octop_builtin_skills.py::test_manager_installs_namespaced_skillhub_page_url`（≈L200）。
- 专家目录 `src/octop/infra/agents/experts/catalog.py` 的 `ExpertCatalog` 通过 `extra_roots` 读本地市场缓存（`server.py` ≈L297-300 传入 `paths.expert_market_dir`，即 `~/.octop/expert_market/`，`paths.py` ≈L63）；`_manifest_scene`（≈L447）兼容 manifest 中的 `skillhub` 字段。这些都是本地文件读取，不联网。

### URL 导入

- `src/octop/infra/skills/skills_hub.py`（1493 行）：`SUPPORTED_URL_PREFIXES`（≈L42-47）为 `skills.sh`、`clawhub.ai`、`skillsmp.com`、`github.com`；`OCTOP_SKILLS_HUB_BASE_URL` 的默认值是 `https://clawhub.ai`（≈L143）；另有 `OCTOP_SKILLS_IMPORT_URL_PREFIXES`（≈L53）、`OCTOP_SKILLS_HUB_*` 超时与路径类环境变量（≈L105-169），以及 `api.github.com`（≈L197）。
- 调用方：`skills.py` 的 `POST /agents/{agent_id}/skills/import`（≈L894-981，≈L911 导入 `is_supported_skill_url`）；`skill_packages.py` 的 `POST /{package_id}/skills/import`（≈L579，≈L600 同样导入）；`install.py::resolve_url_import`。`ImportSkillBody`（`skills.py` ≈L710）与 `_AgentWorkspaceInstallTarget`（≈L861）只被 URL 导入与 hub 安装使用。
- dashboard：`pages/Agent/Skills/components/SkillImportModal.tsx` 的 `DEFAULT_SKILL_URL_PREFIXES`（≈L8-13）、`onImportUrl`（≈L26）、`urlPrefixes`（≈L34）、`mode: "url" | "zip"`（≈L55）；`pages/Agent/Skills/useSkills.ts` 的 `importFromUrl`（≈L266，请求 `/agents/${agentId}/skills/import`）；`InstalledSkillsTab.tsx` ≈L27、≈L59、≈L271 透传；`pages/SkillPackages/index.tsx` 的 `SKILL_URL_PREFIXES`（≈L93-96）与 `onImportUrl={confirmImport}`（≈L1026，内部 ≈L480 调 `skillPackagesApi.importSkill`）；`api/modules/skillPackages.ts` 的 `importSkill`（≈L115）。

### 专家市场

- `src/octop/api/routers/experts.py`（760 行）：docstring ≈L1-9；导入 `market_creation`（≈L36-41）与 `experts/skillhub_market`（≈L59）；`_SAFE_MARKET_REASONS`（≈L90）；`ExpertHubItemResponse`、`ExpertHubListResponse`、`MarketCreateSourceResponse`、`MarketCreateResponse`（≈L170-213）；`_map_skillhub_error`（≈L281）；端点 `GET /experts/hub`（≈L556）、`GET /experts/hub/{slug}`（≈L577）、`POST /experts/hub/{slug}/install`（≈L594-672）。
- `src/octop/infra/agents/experts/skillhub_market.py`（1323 行，`MARKET_EXPERT_PREFIX = "skillhub-skillset-"` ≈L42，`DEFAULT_SKILLHUB_HOST` ≈L43）与 `market_creation.py`（365 行，`create_agent_from_skillhub_skillset` ≈L233）只服务市场。`manifest_generator.py` 的函数只被 `market_creation.py` 与 `tests/unit/agents/test_expert_manifest_generator.py` 使用，本身不联网。
- dashboard：`api/modules/expertMarket.ts` 被 `ExpertMarketTab.tsx`、`CreateFromExpertDrawer.tsx`（≈L10-12，`kind: "market"` 分支 ≈L73、≈L208、≈L237、≈L366、≈L383、≈L429）与 `SkillsetFromHubDrawer.tsx`（及 `.test.tsx`、`.module.less`）引用；`pages/Experts/index.tsx` ≈L53 导入 `ExpertMarketTab`，≈L58 `TabKey` 含 `"market"`，≈L513-521 `marketContent`，≈L550-554 注册标签页。
- 技能侧：`pages/Agent/Skills/components/SkillsTabs.tsx` ≈L21 导入 `SkillHubTab`，≈L27 类型，≈L32 标签，≈L81-82 渲染；`SkillHubTab.tsx`、`SkillHubDetailDrawer.tsx`、`skillHubCache.ts`、`skillInstallTarget.ts`（三个 hub 路径函数 ≈L7、≈L14、≈L26）只服务市场；`api/types/skill.ts` 的 `HubSkillSpec`（≈L29）与 `SkillHubSkill`（≈L37）只被它们引用；`pages/SkillPackages/index.tsx` ≈L70 导入 `SkillHubTab`、≈L82 导入 `SkillsetFromHubDrawer`、≈L628 与 ≈L673-676 为"从 SkillHub 创建"入口、≈L909 为市场按钮、≈L1031 渲染抽屉、≈L1067-1074 渲染市场弹窗；`api/modules/skillPackages.ts` 的 `fromSkillHub`（≈L64）、`hubSearch`、`hubRankings`、`hubInstall`（≈L124-148）；`skillPackages.test.ts` ≈L70、≈L94 覆盖 `fromSkillHub`。

### 插件

- `src/octop/api/routers/plugins.py`：`PluginInstallBody`（≈L43-44）；`POST /install`（≈L132-158，调 `mgr.install_url`）；`POST /upload`（≈L160-200，把上传内容写入临时 ZIP 后调 `mgr.install_archive`）。`tempfile`、`File`、`Form`、`UploadFile` 只被 `/upload` 使用。
- `src/octop/infra/agents/plugins/manager.py`：`_GITHUB_BLOB_RE`（≈L36）与 `normalize_plugin_download_url`（≈L44-58，返回 `raw.githubusercontent.com` 地址）；`_assert_http_url`（≈L105）；`install_path`（≈L419，调 `load_plugin_dir(dest, install_deps=True)`）；`install_archive`（≈L453）；`install_url`（≈L492，`urllib.request.urlretrieve`）。
- `src/octop/cli/commands/plugin.py` 的 `install`（≈L45-66）：参数是目录就走 `install_path`，是 `http(s)://` 就走 `install_url`，否则报错；不支持本地 ZIP。
- 测试：`tests/unit/test_plugin_manager.py` 覆盖 `normalize_plugin_download_url` 与 `install_url`（≈L88-142）；`tests/integration/test_plugin_upload.py` 有 4 个上传用例和 1 个 `test_list_plugins_is_available_to_authenticated_users`；`tests/integration/test_plugin_tool_disable.py` ≈L26 用 `/api/plugins/upload` 装测试插件（夹具目录 `tests/fixtures/plugins/echo-tool`）。
- dashboard：`pages/Admin/Plugins/index.tsx` ≈L5、L9、L11、L14、L58-60；`PluginMarketPanel.tsx` 是纯占位页；`InstalledPluginsPanel.tsx` ≈L73-77 状态、≈L104 `handleInstall`、≈L129-137 上传、≈L362 上传按钮、≈L596-609 URL 安装弹窗；`api/modules/plugins.ts` 的 `install`（≈L77）与 `upload`（≈L86）。

### Ollama 与 ONNX

- `src/octop/api/routers/ollama_models.py`（`prefix="/ollama-models"` ≈L30）：≈L18 导入 `ollama_download_store`；`POST /download`（≈L117）、`_run_pull_in_background`（≈L149，调 `OllamaModelManager.pull_model`）、`GET /download-status`（≈L179）、`DELETE /download/{task_id}`（≈L192）。列表、删除模型与服务开关（≈L210、≈L255、≈L275）保留。
- `src/octop/infra/utils/ollama_manager.py`：≈L102 的错误文案含 `https://ollama.com/download`；`pull_model`（≈L203-214，≈L207 `ollama.pull(name)`）。
- `src/octop/cli/commands/models.py` 的 `ollama-pull`（≈L212-229）；`tests/unit/cli/test_models_cmd.py` ≈L14 断言帮助里有 `ollama-pull`。
- `src/octop/api/routers/onnx_models.py`（`prefix="/onnx-models"` ≈L28）：`OnnxServiceConfigBody.download_if_missing` 默认为 `True`（≈L42-45）；`put_config`（≈L121-160）在模型缺失且 `download_if_missing` 为真时调 `DOWNLOAD_MANAGER.start_download`，也就是**第三个下载入口**；`OnnxDownloadRequest`（≈L48）；`POST /download`（≈L183）、`GET /download-status`（≈L197）。
- `src/octop/api/routers/knowledge_bases.py`（`prefix="/knowledge-bases"` ≈L62）：≈L29 导入 `DOWNLOAD_MANAGER`；`POST /onnx-download`（≈L468）、`GET /onnx-download-status`（≈L481）；`POST /onnx-activate` 在 ≈L502 用 `DOWNLOAD_MANAGER.state` 组装返回的状态；`_enable_onnx_service`（≈L274）在模型缺失时抛错，不会下载。
- `src/octop/infra/agents/providers/onnx_download.py`（457 行）：`HF_ENDPOINT_OFFICIAL`（≈L25）、`HF_ENDPOINT_MIRROR`（≈L26）、`COS_ENDPOINT_DEFAULT`（≈L28，腾讯云 COS 公有桶）、`OCTOP_ONNX_COS_BASE`（≈L32）、`cos_base_url`（≈L81）、`download_model_raced`（≈L205）；只被 `onnx_service.py` 与 `tests/unit/agents/test_onnx_download.py` 使用。它的 `hf_cache_snapshot_dir`（≈L341）会写 `refs/main`，即 Hugging Face 缓存布局。
- `src/octop/infra/agents/providers/onnx_service.py`：≈L29 导入 `download_model_raced`；`embedding_models_dir()`（≈L188，`~/.octop/embedding_models`）；`model_cache_dir`（≈L194，`models--<org>--<name>`）；`_ui_progress_from_bytes`（≈L336，只被 `_download_sync` 使用）；`_build_text_embedding`（≈L389-392）构造 `TextEmbedding(model_name=model, cache_dir=...)` 时**没有**传 `local_files_only`，模型缺失时 fastembed 会自行联网下载，这是一个隐式下载入口；`status_payload`（≈L444）把 `download.to_dict()` 放进返回体；`OnnxDownloadManager`（≈L461，`start_download` ≈L487、`_download_sync` ≈L537）；`DOWNLOAD_MANAGER`（≈L601）。
- fastembed：`uv.lock` 锁定 0.8.0；本地虚拟环境为 0.8.1，`fastembed/common/model_management.py` 从 `kwargs` 读取 `local_files_only`（≈L454），为真时只用本地文件。
- 测试：`tests/unit/agents/test_onnx_service.py` 的 `test_ui_progress_from_bytes_is_byte_fraction`（≈L31）与 `test_download_sync_reports_tqdm_bytes`（≈L40）；`tests/unit/api/test_knowledge_bases.py::test_onnx_download_starts_catalog_model`（≈L504）；`tests/integration/test_onnx_models_api.py` 已有"未下载时启用返回 409 且含 `not downloaded`"用例（≈L20-35）。
- dashboard：`pages/Settings/Models/components/modals/ProviderConfigModal.tsx`（1227 行）中，Ollama 拉取为 `pollOllamaDownloads`（≈L199）、`startOllamaPolling`（≈L249）、`handleOllamaDownload`（≈L284）及取消（≈L340）；ONNX 下载为 `runOnnxDownloadWithProgress`（≈L419，≈L429 调 `onnxModelApi.download`）、`handleLocalModelDownload`（≈L494），并导入 `api/modules/onnxDownloadWatcher.ts`（≈L32-33）。`pages/KnowledgeBases/index.tsx` 有 `watchOnnxDownloadStatus`（≈L839）、挂载时查询下载状态（≈L1239）、`startOnnxDownload`（≈L1251）与"下载模型"按钮（≈L3252-3259）。`api/modules/ollamaModel.ts`（≈L11-24）、`onnxModel.ts`（≈L58-75）、`knowledgeBases.ts`（≈L146-155）、`knowledgeBases.test.ts`（≈L22、≈L32、≈L40）含下载方法。
- 另：`pages/Agent/Memory/VectorSearchConfig.tsx` 与 `pages/Settings/Embedding/index.tsx` 调用的 `/api/embedding/*` 在后端不存在，两个页面也没有被任何路由引用，属于无关死代码，不在本 spec 处理。

### TLS

- `src/octop/infra/setup/tls/`：`acme_issue.py`（135 行，≈L11-17 导入 `acme` 与 `josepy`）、`challenge.py`（28 行，`challenge_store` 单例）、`preflight.py`（215 行，`_fetch_public_ip` ≈L60-68 访问 `https://api.ipify.org?format=text`）、`renewal.py`（88 行，`_AUTO_RENEW_JOB_ID = "octop_tls_auto_renew"` ≈L20，`install_auto_renewal_job` ≈L74）、`modes.py`（54 行，全部是"能否签发 / 续期"的判定）、`manager.py`（257 行，签发状态机）、`store.py`（95 行）、`listeners.py`、`http_companion.py`、`__init__.py`（≈L3 导出 `challenge_store`）。
- 续期任务在 `src/octop/infra/server.py` ≈L445-447 注册（源分析说的 `cron/manager.py:67` 只是一行注释）。
- `src/octop/api/app.py` ≈L135-142 注册 `GET /.well-known/acme-challenge/{token}`；`PlainTextResponse`（≈L13 导入）只在这里使用，`HTTPException` 在 ≈L68、≈L295 还有他用。
- `src/octop/infra/setup/tls/http_companion.py` ≈L10 导入 `challenge_store`，≈L13-18 `_acme_challenge`，≈L36-40 注册挑战路由；其余路由把所有请求 301 到 HTTPS。
- `src/octop/api/routers/tls.py`（112 行，挂在 `/api/admin/tls` ≈app.py L240）：`GET /status`（≈L55）、`POST /preflight`（≈L66）、`POST /issue`（≈L80），均为 `require_permission("tls")`。**基线没有任何证书上传接口**。
- `src/octop/infra/setup/tls/store.py`：`REL_CERT_FILE = "ssl/fullchain.pem"`、`REL_KEY_FILE = "ssl/privkey.pem"`（≈L15-16）；`resolve_tls_paths`（≈L19）；`_atomic_write_bytes`（≈L34，支持 `mode`）；`_merge_config_file`（≈L43，对 `tls` 段做浅合并）；`install_letsencrypt_cert`（≈L57-91，写死 `bind_host="0.0.0.0"`、`port=443`、`http_port=80`、`mode="letsencrypt"`、`acme_staging`）；`account_key_path`（≈L94）。
- `src/octop/infra/setup/tls/listeners.py::build_listen_plan`（≈L33）：只有在 TLS 启用、证书可用且 `0 < tls.http_port != bind_port` 时才双端口监听；否则单端口，并在该端口上启用 TLS。`src/octop/launch.py` ≈L115-133 按计划启动伴随应用，≈L128 的日志文案是 "(ACME + redirect)"。
- `src/octop/config.py`：`TlsConfig`（≈L77，docstring 提到 Let's Encrypt）；`acme_staging` 在 ≈L87 与 `_parse_tls_section` ≈L180；`OctopConfig` 以 `tls=_parse_tls_section(raw.get("tls"))`（≈L613）构造，`_parse_tls_section` 只读取已知键。
- `src/octop/cli/commands/run.py` 已支持 `--ssl --certfile --keyfile` 与自签证书（`_maybe_generate_self_signed` ≈L25），这是一条现成的离线 HTTPS 路径。
- `src/octop/api/openapi_meta.py` ≈L116-118 的 `tls` 标签描述为 "Let's Encrypt HTTPS certificate issuance and status."。
- 依赖：`pyproject.toml` ≈L33 `acme>=5.6.0`、≈L34 `josepy>=2.2.0`；按 `uv.lock` 统计，`acme` 与 `josepy` 只被 `octop` 直接依赖，`pyopenssl` 与 `pyrfc3339` 只被 `acme` 依赖。
- 可复用的证书处理：`cryptography` 锁定 49.0.0，提供 `x509.load_pem_x509_certificates` 与 `Certificate.not_valid_after_utc`。
- 审计：`server.services.audit_repo.write(actor=, action=, target=, payload=)`（`infra/db/repos/audit.py` ≈L39），`api/routers/connectors.py` ≈L545 有现成用法。
- ErrorCode：`TLS_NOT_ELIGIBLE`、`TLS_ISSUE_IN_PROGRESS`、`TLS_DOMAIN_MISMATCH`（`errors.py` ≈L68-70）只被签发流程使用。`OctopError.__post_init__` 对 `_DEFAULT_STATUS[self.code]` 做无保护下标（≈L227 附近）。
- dashboard：`api/modules/tls.ts`（`getStatus`、`preflight`、`issue`）只被 `pages/Settings/HttpsSettings/index.tsx`（360 行）使用；页面的 `tls.*` 文案（en/zh 各 42 键）围绕签发流程撰写，例如 `tls.title` 为 "HTTPS (Let's Encrypt)"。

### 其他

- `tests/unit/api/test_openapi_meta.py` 展示了"以 `enable_api_docs=True` 构建应用、读取 `/api/openapi.json`"的测试写法。
- `tests/conftest.py` 的 `_SLOW_TEST_MODULES`（≈L15-28）列出了 `tests/unit/agents/test_skills_hub_raw.py` 与 `tests/unit/agents/test_skillhub_market.py`，删文件时同批删除这两项。
- 后端 i18n：`errors.SKILLHUB_SSL_FAILED`、`tls.preflight.*`、`tls.preflight_failed_summary` 会变成孤儿；dashboard 的 `advancedSettings.update.*`、`header.versionUpdateAvailable`、`account.checkUpdates`、`skills.*SkillHub*`、`plugins.market*`、`experts.expertMarket` 等也会变成孤儿。按全局约束 1.2 一律保留。

## 方案

**1. 物理删除，不做开关。** 全局约束 1.5 与 2 节允许裁剪 spec"物理删除时同批删 mount 行"。本 spec 删除的都是整段出网实现，挂开关只会让代码留在仓库里，因此不使用 `_FORK_DISABLED_MOUNTS`，也不向 `w1-02` 的能力框架登记键位。

**2. 删除的边界是"从外网获取"，不碰本地数据。**
- 已安装的 SkillHub 技能、已缓存的市场专家（`~/.octop/expert_market/`）、已下载的 ONNX 模型、Let's Encrypt 签发的现有证书都属于本地数据，继续可用。
- 因此 `ExpertCatalog` 的 `extra_roots`、`catalog.py` 对 `skillhub` 字段的兼容、`paths.expert_market_dir`、`valid_skillhub_icon_url`、`manifest_generator.py` 都不动。源分析建议删 `paths.py:64` 的目录，本 spec 不采纳，否则既有 Agent 的专家模板会失联。`manifest_generator.py` 因市场下线成为无调用方的模块，在"与其他 spec 的交接"中登记，不在本 spec 删除，以免扩大 diff。

**3. 服务重启：迁到 fork 自有文件，不在上游 `update.py` 里留一个端点。**
`update.py` 整文件删除后，上游再改它时，同步会出现 modify/delete 冲突，一律保留删除即可；如果只在 `update.py` 里留一个 `/restart`，每次同步都要手工合并上游的升级逻辑。新文件 `service_control.py` 的 `restart_service_endpoint` 与基线逐行等价，只有两处差异：一是权限键字面量改为 `"service_control"`；二是原来调用 `self_update.green_packages_dir()` 的地方，改为直接读 `OCTOP_GREEN_PACKAGES`，行为不变。desktop 分支保留，由 `w1-04` 按 D9 决定是否删除。

**4. 版本号来源：新增 `GET /api/service/status`，不复用 `/api/health`。**
`/api/health` 免鉴权，把版本号放进去等于向未登录者暴露版本，不利于等保测评。新接口只要求登录，与基线 `/update/status` 的可见范围一致，只返回 `current_version`、`service_mode`、`desktop` 三个本地可得的值。

**5. 权限键 `update` 更名为 `service_control`，而不是保留旧键名。**
全局约束 1.6 把本 spec 列为删键 spec。保留 `update` 虽然零迁移，但权限选择器会继续显示"应用更新"这个已不存在的功能。更名后：
- `PERMISSIONS` 新增 `service_control`（label "服务重启" / "Service restart"，category `admin`，page `advanced`，与原 `update` 同组），删除 `update`。
- 迁移步骤把存量用户的 `update` **替换**为 `service_control`，而不是直接剔除，这样原持有者的重启权限不丢。
- 前端 `advancedPage` 数组去掉 `"update"`，但不加入 `service_control`，因为应用设置页里没有对应的标签页；删除 `UpdateConfig` 之后，唯一的重启按钮在 HTTPS 标签页里，由后端 403 兜底。这与基线"持 `tls` 但不持 `update` 时点重启得 403"的行为一致。

**6. ONNX：删入口，保留状态字段的形状。**
`status_payload` 的 `download` 字段是既有 API 契约，前端类型 `OnnxServiceStatus`（`dashboard/src/api/modules/onnxModel.ts` ≈L34）也声明了它。本 spec 删掉 `OnnxDownloadManager.start_download` 与 `_download_sync`，保留 `state` 属性与 `DOWNLOAD_MANAGER` 单例，于是 `download` 恒为 `{"status": "idle", ...}`。这样响应形状与前端类型都不用改，只删触发下载的按钮与轮询。`put_config` 删掉 `download_if_missing` 字段与自动下载分支，模型缺失一律返回 409（沿用基线文案，`test_onnx_models_api.py` 断言文案含 `not downloaded`）；旧前端若仍发送该字段，Pydantic 默认忽略多余字段。fastembed 推理加 `local_files_only=True`，堵住隐式下载。

**7. TLS：上传模式只写证书与 `tls` 段，不改监听地址与端口。**
- 基线的 Let's Encrypt 流程会把 `bind_host` 写成 `0.0.0.0`、`port` 写成 443、`http_port` 写成 80。行内部署的端口由容器平台或负载均衡决定（D4），而且 `w2-01` 让容器以非 root 运行，绑定 80 / 443 需要额外能力。所以上传模式只写 `tls` 段，并把 `http_port` 设为 0。按 `build_listen_plan` 的判定，重启后进程在原端口上只开 HTTPS，80 端口伴随应用不会启动。
- 需要 HTTP→HTTPS 跳转的部署可以手工在 `config.json` 里设置 `tls.http_port`，这时伴随应用由 `w3-01` 覆盖安全头。
- 校验在服务端完成：解析证书链（第一张为叶子）、解析私钥（拒绝加密私钥）、比对公钥、检查有效期，SAN 中的 DNS 与 IP 作为 `domains`，缺 SAN 时回落到 CN。
- 请求体用 JSON 传 PEM 文本，不走 multipart。这样不会成为 `w3-01` 需要做魔数与杀毒的"文件上传入口"，也便于 `/api/docs` 展示类型。
- 前端用 `FileReader` 读取用户选择的 `.pem` / `.crt` / `.key` 文件，或让用户直接粘贴。
- 证书与私钥按原样字节写入（仅校验，不重新编码）；私钥文件在 POSIX 上为 0600，沿用 `_atomic_write_bytes(mode=0o600)`。
- 签发状态机整体删除。`TlsManager` 只保留两件事：计算 `idle` / `restart_required` / `active` 三态，以及执行一次上传。

**8. i18n：零改上游 JSON。**
新增的文案写进两对 overlay；需要改措辞的上游键（HTTPS 页标题与说明、`PLUGIN_INVALID_ARCHIVE` 里的 GitHub 建议）用 overlay 覆盖。变成孤儿的键全部保留。`ErrorCode.SKILLHUB_SSL_FAILED`、`EXPERT_MARKET_FAILED`、`TLS_NOT_ELIGIBLE`、`TLS_ISSUE_IN_PROGRESS`、`TLS_DOMAIN_MISMATCH`、`SKILL_IMPORT_UNSUPPORTED_URL` 也保留：删枚举必须同批删四处文案，违反全局约束 1.2。源分析"删 `SKILLHUB_SSL_FAILED` 与 `tls.preflight.public_ip.fail`"的方案按 steering 改掉。

**9. 两个守卫测试按任务增量填充。**
任务 2 先建"空清单"的守卫测试。之后每个删除任务先把自己的 token 与路由加进清单，此时测试变红，再做删除让它变绿。这样每个顶层任务都能独立提交，pre-commit 的 `make all` 始终为绿。

## 组件与接口

### 后端：删除的文件

`src/octop/infra/setup/self_update.py`、`src/octop/api/routers/update.py`、`src/octop/api/routers/update_store.py`、`src/octop/cli/commands/update.py`、`src/octop/infra/skills/skills_hub.py`、`src/octop/infra/skills/skillhub_market.py`、`src/octop/infra/skills/skill_package_from_skillhub.py`、`src/octop/infra/agents/experts/skillhub_market.py`、`src/octop/infra/agents/experts/market_creation.py`、`src/octop/api/routers/ollama_download_store.py`、`src/octop/infra/agents/providers/onnx_download.py`、`src/octop/infra/setup/tls/acme_issue.py`、`src/octop/infra/setup/tls/challenge.py`、`src/octop/infra/setup/tls/preflight.py`、`src/octop/infra/setup/tls/renewal.py`、`src/octop/infra/setup/tls/modes.py`。

### 后端：修改的文件

| 文件 | 改动 |
|---|---|
| `src/octop/api/app.py` | 删 ≈L135-142 的 ACME 路由与 `PlainTextResponse` 导入；路由导入列表删 `update`、加 `service_control`；≈L261 的 mount 行改为 `_RouterMount(service_control.router, "/api", ["service"])` |
| `src/octop/api/openapi_meta.py` | ≈L144 的 `update` 标签改为 `{"name": "service", "description": "Local service status (version, service mode) and restart."}`；≈L117 的 `tls` 描述改为 "HTTPS certificate upload and status." |
| `src/octop/cli/registry.py` | 删 ≈L31 的 `"update"` |
| `src/octop/infra/users/permissions.py` | 删 `"update"`（≈L198-206），在同位置加 `"service_control": _p("service_control", "admin", "服务重启", "Service restart", page="advanced", page_zh="应用设置", page_en="App settings")` |
| `src/octop/api/routers/skills.py` | 删 `_SKILLHUB_INSTALL_URL`、`_valid_skillhub_icon_url`、≈L227-417 的 SkillHub CLI 辅助函数、`ImportSkillBody`、`_AgentWorkspaceInstallTarget`、`import_skill_from_url`、`LocalizedSkillCopy`、`HubInstallBody`、`_download_skillhub_package_via_cli`、`_parse_skillhub_search_output` 与三个 hub 端点；随之孤立的 `shutil`、`tempfile`、`os` 等导入以 ruff F401 为准一并删除 |
| `src/octop/api/routers/skill_packages.py` | 删 ≈L14、L22、L28 三处导入，`_SAFE_SKILLHUB_REASONS`、`FromSkillHubBody`、`_map_skillhub_error`，以及 `hub/search`、`hub/rankings`、`from-skillhub`、`{package_id}/skills/import`、`{package_id}/skills/hub/install` 五个端点；保留 `_icon_url` 与 `valid_skillhub_icon_url` 导入 |
| `src/octop/api/routers/experts.py` | 删 docstring 中三条 hub 路由说明、`market_creation` 与 `skillhub_market` 导入、`_SAFE_MARKET_REASONS`、四个市场响应模型、`_map_skillhub_error` 与三个 `/experts/hub*` 端点 |
| `src/octop/infra/skills/install.py` | 删 `skills_hub` 导入、`with_skillhub_presentation_metadata`、`prepare_skillhub_package`、`resolve_url_import`、`install_skill_from_url`、`install_skill_from_skillhub` 及其 `__all__` 项；保留 `SkillAlreadyExistsError`、`SkillInstallTarget`、`commit_skill_install`、`_valid_skillhub_icon_url`、`valid_skillhub_icon_url`；随之孤立的 `yaml`、`parse_frontmatter` 导入一并删除 |
| `src/octop/infra/skills/__init__.py` | docstring 改为 "Skills domain: package validation, global packages, local install."；去掉四个已删符号的再导出与 `__all__` 项 |
| `src/octop/infra/agents/builtin_skills/skill-manager/SKILL.md`、`scripts/manage_skills.py` | 删 SkillHub 描述、`_skillhub_source`、`_materialize` 的 SkillHub 分支、`_effective_name` 对 SkillHub 的推导（改为直接返回 `name`）、`_skillhub_search` 与 `skillhub-search` 子命令 |
| `src/octop/api/routers/plugins.py` | 删 `PluginInstallBody`、`install_plugin`、`upload_plugin` 与随之孤立的导入 |
| `src/octop/infra/agents/plugins/manager.py` | 删 `_GITHUB_BLOB_RE`、`normalize_plugin_download_url`、`_assert_http_url`、`install_url` 与 `urllib` 导入；保留 `install_path` 与 `install_archive` |
| `src/octop/cli/commands/plugin.py` | `install` 改为：目录 → `install_path`；`.zip` 文件 → `install_archive`；其他（含 URL）→ `click.ClickException("not a local plugin directory or .zip file: …")`；docstring 改为 "Install from a local directory or .zip file." |
| `src/octop/api/routers/ollama_models.py` | 删 `ollama_download_store` 导入与三个 download 端点、`_run_pull_in_background`、`_task_to_response` 等只服务下载的辅助函数与模型 |
| `src/octop/infra/utils/ollama_manager.py` | 删 `pull_model`；≈L102 文案改为 "Ollama binary not found on this system; ask the operator to pre-install Ollama and its models."（`infra/utils` 不能读 i18n，保持英文） |
| `src/octop/cli/commands/models.py` | 删 `ollama-pull` 命令 |
| `src/octop/api/routers/onnx_models.py` | 删 `download_if_missing`、`OnnxDownloadRequest`、`post_download`、`get_download_status`；`put_config` 在启用且模型未预置时一律 409 |
| `src/octop/api/routers/knowledge_bases.py` | 删 `start_onnx_download`、`onnx_download_status`；`DOWNLOAD_MANAGER` 导入保留（`status_payload` 仍需要） |
| `src/octop/infra/agents/providers/onnx_service.py` | 删 `download_model_raced` 导入、`OnnxDownloadManager.start_download` / `_download_sync` / `_set` / `_task` 以及只被它们使用的 `_ui_progress_from_bytes`；`_build_text_embedding` 加 `local_files_only=True` |
| `src/octop/infra/setup/tls/manager.py` | 重写为上传模式（见下） |
| `src/octop/infra/setup/tls/store.py` | 删 `install_letsencrypt_cert`、`account_key_path`；新增 `install_uploaded_cert` |
| `src/octop/infra/setup/tls/http_companion.py` | 删 `challenge_store` 导入、`_acme_challenge` 与挑战路由；docstring 改为 "redirect to HTTPS" |
| `src/octop/infra/setup/tls/__init__.py` | docstring 改为 "TLS certificate management."；去掉 `challenge_store` |
| `src/octop/api/routers/tls.py` | 删 `preflight`、`issue` 及其模型；`status` 改用新的响应模型；新增 `upload_certificate` |
| `src/octop/infra/server.py` | 删 ≈L445-447 的续期任务注册 |
| `src/octop/launch.py` | ≈L128 日志文案去掉 "ACME + " |
| `src/octop/config.py` | `TlsConfig` 删 `acme_staging` 字段（≈L87），`_parse_tls_section` 删对应行（≈L180），docstring 改为 "TLS settings persisted in config.json." |
| `src/octop/infra/errors.py` | `ErrorCode` 末尾追加 `TLS_CERT_INVALID`，`_DEFAULT_STATUS` 末尾追加 `ErrorCode.TLS_CERT_INVALID: 400` |
| `src/octop/infra/db/fork_migrate.py` | `_FORK_PY_STEPS` 登记 `NNN: step_service_control_permission` |
| `pyproject.toml` / `uv.lock` | 删 `acme`、`josepy`；`make relock` 重生成 |
| `tests/conftest.py` | `_SLOW_TEST_MODULES` 删两个已删测试文件 |
| `tests/unit/api/test_acl_gate_coverage.py` | `GATED_FILES` 中 `routers/update.py` 换成 `routers/service_control.py` |

### 新增：`src/octop/api/routers/service_control.py`（fork 自有）

```python
"""Local service status and restart (intranet fork; replaces the upstream update router)."""

router = APIRouter(prefix="/service", tags=["service"])

_GREEN_PACKAGES_ENV = "OCTOP_GREEN_PACKAGES"  # desktop portable marker (was self_update)

class ServiceStatusResponse(BaseModel):
    current_version: str = Field(..., description="Installed octop package version")
    service_mode: str | None = Field(None, description="systemd / launchd when run as a system service")
    desktop: bool = Field(False, description="True when spawned by the desktop shell")

class ServiceRestartResponse(BaseModel):
    status: Literal["restarting"]
    service_mode: str

def _local_version() -> str: ...          # importlib.metadata.version("octop")；PackageNotFoundError 时回落 octop.__version__
def _is_desktop_process() -> bool: ...    # OCTOP_GREEN_PACKAGES 非空，或 OCTOP_DESKTOP ∈ {1,true,yes,on}
def _restart_desktop_process() -> None: ...
def _restart_service_task(runtime: ServiceRuntime) -> None: ...

@router.get("/status", summary="Local service status and version", response_model=ServiceStatusResponse)
async def service_status(_: Any = Depends(current_user)) -> ServiceStatusResponse: ...

@router.post(
    "/restart",
    summary="Restart the Octop system service",
    description="Requires the service_control permission. Only works under OCTOP_SERVICE_MODE or the desktop shell.",
    response_model=ServiceRestartResponse,
)
async def restart_service_endpoint(
    background_tasks: BackgroundTasks,
    _: Any = Depends(require_permission("service_control")),
) -> ServiceRestartResponse: ...
```

`restart_service_endpoint` 的函数体从 `update.py` ≈L383-412 原样搬过来。

### 新增：迁移步骤 `src/octop/infra/db/fork_permission_keys.py`（fork 自有）

```python
def rewrite_permission_keys(conn: Any, dialect: str, *, rename: Mapping[str, str], drop: frozenset[str] = frozenset()) -> int:
    """Rewrite users.permissions in place; returns the number of rows changed.

    Skips silently when the users table is absent. Parsing mirrors repos/users.py::_parse_permissions;
    writes use the same "UPDATE users SET permissions = ? WHERE id = ?" + json.dumps as UserRepo.set_permissions.
    Order is preserved, duplicates collapse to the first occurrence. Idempotent.
    """

def step_service_control_permission(conn: Any, dialect: str) -> None:
    """forkNNN: update -> service_control; delete the settings row 'update.stable_only' (if settings exists)."""
```

- 表存在性在同一连接上判断（`ForkPyStep` 只拿到 `conn` 与 `dialect`），SQL 与 `migrate._table_exists`（≈L96）逐方言一致：PG 查 `information_schema.tables`，SQLite 查 `sqlite_master`。
- 如果任务 1 发现 `w1-02` 已经提供了等价的通用函数，就直接复用它，本 spec 只新增 `step_service_control_permission` 并登记。

### 新增：`src/octop/infra/setup/tls/upload.py`（fork 自有）

```python
CertRejectReason = Literal[
    "no_certificate", "certificate_invalid", "key_invalid", "key_encrypted",
    "key_mismatch", "expired", "not_yet_valid",
]

class CertificateRejected(ValueError):
    def __init__(self, reason: CertRejectReason) -> None: ...
    reason: CertRejectReason

@dataclass(frozen=True)
class UploadedCertInfo:
    domains: list[str]          # SAN DNS + IP（去重、保序）；无 SAN 时回落 CN；都没有则空列表
    not_before: str             # ISO-8601 UTC，秒精度
    not_after: str
    fingerprint_sha256: str     # 叶子证书 DER 的 SHA-256 十六进制

def inspect_certificate_pair(cert_pem: bytes, key_pem: bytes, *, now: datetime | None = None) -> UploadedCertInfo:
    """Parse the chain (leaf first) and an unencrypted private key; verify they match and the leaf is valid now.

    Raises CertificateRejected. Never logs or echoes key material.
    """
```

实现要点：

- 先检查文本中是否有 `-----BEGIN CERTIFICATE-----`，没有则为 `no_certificate`；再用 `x509.load_pem_x509_certificates` 解析，抛 `ValueError` 则为 `certificate_invalid`。之所以先检查标记，是因为 cryptography 49.0.0 对空输入与乱码都抛同一个 `ValueError`（已实测）。
- 私钥用 `serialization.load_pem_private_key(key_pem, password=None)`：`TypeError`（需要口令）为 `key_encrypted`，`ValueError` / `UnsupportedAlgorithm` 为 `key_invalid`。
- 取叶子证书公钥（`leaf.public_key()`）时抛 `UnsupportedAlgorithm` / `ValueError`，也归为 `certificate_invalid`。
- 用 `public_bytes(DER, SubjectPublicKeyInfo)` 比对私钥公钥与叶子公钥，不等为 `key_mismatch`。
- 有效期用 `not_valid_before_utc` / `not_valid_after_utc`。

`src/octop/infra/setup/tls/store.py` 新增：

```python
def install_uploaded_cert(paths: PathLayout, *, cert_pem: bytes, key_pem: bytes, info: UploadedCertInfo) -> None:
    """Write ssl/fullchain.pem + ssl/privkey.pem (0600) and merge the tls section of config.json.

    tls := {enabled: True, mode: "uploaded", domains, cert_file: REL_CERT_FILE, key_file: REL_KEY_FILE,
            issued_at: info.not_before, expires_at: info.not_after, http_port: 0}; bind_host/port untouched.
    """
```

`src/octop/infra/setup/tls/manager.py` 重写后的接口：

```python
class TlsState(StrEnum):
    IDLE = "idle"; RESTART_REQUIRED = "restart_required"; ACTIVE = "active"

class TlsManager:
    def status_payload(self, config: OctopConfig, paths: PathLayout) -> dict[str, Any]: ...
    async def install_upload(self, *, cert_pem: bytes, key_pem: bytes, paths: PathLayout) -> UploadedCertInfo:
        """inspect_certificate_pair + install_uploaded_cert in asyncio.to_thread; then mark restart_required."""

def get_tls_manager() -> TlsManager: ...
```

状态判定：本进程内上传过则为 `restart_required`；否则运行期配置中 `tls.enabled` 为真且 `resolve_tls_paths` 能解析出证书与私钥时为 `active`；其余为 `idle`。不再要求端口为 443。`dual_listeners` 与 `build_listen_plan` 的判定一致：`tls.enabled`、证书可用、`0 < tls.http_port != config.port`。

`src/octop/api/routers/tls.py`：

```python
class TlsInfo(BaseModel):
    enabled: bool; mode: str; domains: list[str]; issued_at: str; expires_at: str
    http_port: int; https_port: int | None; dual_listeners: bool; cert_present: bool

class TlsStatusResponse(BaseModel):
    tls: TlsInfo
    state: Literal["idle", "restart_required", "active"]

class TlsCertificateUpload(BaseModel):
    cert_pem: str = Field(..., min_length=1, max_length=65536, description="PEM certificate chain, leaf first")
    key_pem: str = Field(..., min_length=1, max_length=16384, description="Unencrypted PEM private key (PKCS#1/PKCS#8/SEC1)")

@router.get("/status", summary="HTTPS certificate status", response_model=TlsStatusResponse)
@router.post(
    "/certificate",
    summary="Upload an HTTPS certificate and private key",
    description="Validates the pair, writes ~/.octop/ssl, updates config.json (tls.mode=uploaded, http_port=0). Takes effect after a restart.",
    response_model=TlsStatusResponse,
)
async def upload_certificate(body: TlsCertificateUpload, request: Request, user: User = Depends(require_permission("tls")), server: Any = Depends(get_server)) -> TlsStatusResponse: ...
```

上传成功后写审计：`audit_repo.write(actor=user.username, action="tls.certificate.upload", target=",".join(info.domains), payload=info.fingerprint_sha256)`。`CertificateRejected` 映射为 `OctopError.localized(ErrorCode.TLS_CERT_INVALID, locale, details={"reason": exc.reason})`。

### 前端

| 文件 | 类型 | 改动 |
|---|---|---|
| `dashboard/src/api/modules/service.ts` | 新增 | `serviceApi = { getServiceStatus(): request<ServiceStatus>("/service/status"), restartService(): request<RestartResponse>("/service/restart", { method: "POST" }) }`；方法名避开 `api/index.ts` 聚合对象里已有的 `getStatus` |
| `dashboard/src/api/modules/service.test.ts` | 新增 | 两个方法的路径与 method |
| `dashboard/src/hooks/useServiceStatus.ts` | 新增 | 模块级缓存一个 promise，页头与侧栏两处角标只发一次请求；失败返回 `null` |
| `dashboard/src/api/modules/update.ts`、`hooks/useUpdateStatus.ts`(+test)、`utils/updateStatusCache.ts`(+test)、`components/AppVersionBadge/`、`pages/Settings/AdvancedSettings/UpdateConfig.tsx`(+`.module.less`) | 删除 | |
| `api/index.ts` | 修改 | `updateApi` 换成 `serviceApi` |
| `hooks/useServiceRestart.ts`、`pages/Settings/HttpsSettings/index.tsx`、`components/PwaUpdatePrompt/index.tsx` | 修改 | `updateApi.getUpdateStatus()` 换成 `serviceApi.getServiceStatus()`，`updateApi.restartService()` 换成 `serviceApi.restartService()`；`PwaUpdatePrompt` 只改这 3 行（它由 `w4-01` 删除） |
| `layouts/Header.tsx`、`layouts/Sidebar.tsx` | 修改 | 删 `AppVersionBadge` 的导入与渲染；删 `useUpdateStatus` 与 `hasUpdate` 整条 prop 链与红点 |
| `components/CurrentVersionBadge/index.tsx` | 修改 | 改用 `useServiceStatus()`；删可点击分支与 `userCan(user, "update")` |
| `components/AvatarDropdown.tsx` | 修改 | 删"检查更新"菜单项与 `RefreshCw` 导入（外链不动） |
| `pages/Settings/AdvancedSettings/index.tsx`、`routes/index.tsx`、`utils/permissions.ts` | 修改 | 删 `updates` 标签与两条重定向；`advancedPage` 去掉 `"update"`，删 `updates: "update"` 与 `/admin/updates` 分支 |
| `pages/Agent/Skills/components/{SkillHubTab,SkillHubDetailDrawer}.tsx`、`skillHubCache.ts`、`skillInstallTarget.ts`；`pages/Experts/components/ExpertMarketTab.tsx`；`api/modules/expertMarket.ts`；`pages/SkillPackages/SkillsetFromHubDrawer.{tsx,test.tsx,module.less}`；`pages/Admin/Plugins/PluginMarketPanel.tsx`；`api/modules/onnxDownloadWatcher.ts` | 删除 | 删前用 `rg` 确认无剩余引用 |
| `SkillsTabs.tsx`、`SkillImportModal.tsx`(+test)、`InstalledSkillsTab.tsx`、`useSkills.ts`、`pages/SkillPackages/index.tsx`、`api/modules/skillPackages.ts`(+test)、`api/types/skill.ts` | 修改 | 删 SkillHub 标签页与 URL 模式；`SkillImportModal` 删 `onImportUrl` / `urlPrefixes` / `Segmented`，直接渲染 ZIP 面板；删 `importSkill`、`fromSkillHub`、`hub*` 方法与 `HubSkillSpec`、`SkillHubSkill` 类型 |
| `pages/Experts/index.tsx`、`pages/Experts/components/CreateFromExpertDrawer.tsx` | 修改 | 删 market 标签页与 `kind: "market"` 来源 |
| `pages/Admin/Plugins/index.tsx`、`InstalledPluginsPanel.tsx`、`api/modules/plugins.ts` | 修改 | 只剩"已安装"；删 URL 安装弹窗、上传按钮与两个 API 方法；页首加 overlay 提示 `intranet.plugins.offlineInstallHint` |
| `pages/Settings/Models/components/modals/ProviderConfigModal.tsx`、`api/modules/ollamaModel.ts`、`api/modules/onnxModel.ts`、`pages/KnowledgeBases/index.tsx`、`api/modules/knowledgeBases.ts`(+test) | 修改 | 删 Ollama 拉取与 ONNX 下载的状态、轮询、按钮与 API 方法；模型未预置时显示 `intranet.models.onnxNotProvisioned` / `intranet.models.ollamaPreinstallHint` |
| `api/modules/tls.ts` | 修改 | 删 `preflight`、`issue`、`PreflightResult`；`TlsStatus` 对齐新响应；加 `uploadCertificate(body)` |
| `api/modules/tls.test.ts` | 新增 | `getStatus` 与 `uploadCertificate` 的路径、method、请求体 |
| `pages/Settings/HttpsSettings/index.tsx` | 重写 | 状态卡（模式、域名、到期时间）；两个文件选择框加两个可粘贴的文本框；提交；`restart_required` 时显示重启按钮与"改用 https://"提示；错误用 `utils/apiError.ts::parseApiError(err)?.details?.reason` 取 `intranet.tls.reason.<reason>`；取不到才回退 `apiErrorMessage`（它会把 `details.reason` 原样拼在文案后，≈L78-81，直接用会露出机器码） |
| `dashboard/src/locales/intranet/{en,zh}.json`、`src/octop/i18n/intranet/{en,zh}.json` | 修改 | 见下 |

### overlay 文案（en / zh 同键）

- 后端 `src/octop/i18n/intranet/{en,zh}.json`：
  - 新增 `errors.TLS_CERT_INVALID`（"The certificate or private key is invalid." / "证书或私钥无效。"）；
  - 覆盖 `errors.PLUGIN_INVALID_ARCHIVE`（去掉 GitHub 下载建议："The file is not a valid plugin ZIP archive." / "文件不是有效的插件 ZIP 包。"）。
- 前端 `dashboard/src/locales/intranet/{en,zh}.json`：
  - 新增 `apiErrors.TLS_CERT_INVALID`；覆盖 `apiErrors.PLUGIN_INVALID_ARCHIVE`；
  - 覆盖 `tls.title`（"HTTPS certificate" / "HTTPS 证书"）、`tls.subtitle`、`tls.restartRequired`、`tls.activeCert`（占位符改为 `{{port}}` 与 `{{expires}}`）；
  - 新增 `intranet.tls.{uploadTitle, uploadDesc, certLabel, keyLabel, certPlaceholder, keyPlaceholder, chooseFile, upload, uploadSuccess, uploadFailed, modeUploaded, modeLetsencrypt, domains, httpsHint}`、`intranet.tls.reason.{no_certificate, certificate_invalid, key_invalid, key_encrypted, key_mismatch, expired, not_yet_valid}`；
  - 新增 `intranet.models.{onnxNotProvisioned, ollamaPreinstallHint}`、`intranet.plugins.offlineInstallHint`。

## 数据模型

一对 fork 迁移加一个 Python 步骤，号不预占：

- `src/octop/infra/db/migrations/forkNNN_service_control_permission.sql` 与 `forkNNN_service_control_permission.pg.sql`：两份文件都只含说明性注释，没有 SQL 语句（`_split_pg_sql` 会剥掉整行注释，runner 执行 0 条语句）。之所以要这一对文件，是 `w0-01` 的静态检查要求 `_FORK_PY_STEPS` 的每个键都有 SQL 对。
- `_FORK_PY_STEPS[NNN] = step_service_control_permission`，执行两件事：
  1. `users` 表存在时：对每一行 `permissions` 按 `_parse_permissions` 的规则解析；含 `update` 的，把 `update` 替换为 `service_control`，去重并保序后写回。
  2. `settings` 表存在时：`DELETE FROM settings WHERE key = ?`，参数为 `update.stable_only`。
- 回填对象只有存量用户的权限列表与一行设置。不新增表，不改列，不改 `_schema_version`，不改任何 `assert v == 15` 断言。
- 幂等性：第二次执行时已没有 `update`，不改任何行；runner 的水位也会阻止重复执行。

## 配置

**无新增配置键**，不涉及 `config.py` 的三触点。

删除：`TlsConfig.acme_staging`，只动两处：dataclass 字段（≈L87）与 `_parse_tls_section` 中的读取（≈L180）。`OctopConfig(...)` 的构造（≈L613）只传入 `tls=_parse_tls_section(...)`，不需要改。存量 `config.json` 里的 `acme_staging` 键会被解析函数忽略。

随模块删除而失效的环境变量（记入 `CHANGELOG-intranet.md`）：`OCTOP_SKILLS_HUB_BASE_URL`、`OCTOP_SKILLS_HUB_SEARCH_PATH`、`OCTOP_SKILLS_HUB_VERSION_PATH`、`OCTOP_SKILLS_HUB_DETAIL_PATH`、`OCTOP_SKILLS_HUB_FILE_PATH`、`OCTOP_SKILLS_HUB_HTTP_TIMEOUT`、`OCTOP_SKILLS_HUB_HTTP_RETRIES`、`OCTOP_SKILLS_HUB_HTTP_BACKOFF_BASE`、`OCTOP_SKILLS_HUB_HTTP_BACKOFF_CAP`、`OCTOP_SKILLS_IMPORT_URL_PREFIXES`、`SKILLHUB_HOST`、`OCTOP_ONNX_COS_BASE`、`OCTOP_FPK_SITE_PACKAGES`。`OCTOP_GREEN_PACKAGES` 与 `OCTOP_DESKTOP` 仍由 `service_control.py` 读取。

## 错误处理

| 码 | HTTP | 来源 | 说明 |
|---|---|---|---|
| `TLS_CERT_INVALID`（新增） | 400 | `POST /api/admin/tls/certificate` | 追加到 `ErrorCode` 末尾与 `_DEFAULT_STATUS` 末尾；`details.reason` ∈ {`no_certificate`、`certificate_invalid`、`key_invalid`、`key_encrypted`、`key_mismatch`、`expired`、`not_yet_valid`}；文案进两对 overlay；三方相等门禁读合并后的 bundle（`w0-04`） |
| `FORBIDDEN`（复用） | 403 | `/api/service/restart`、`/api/admin/tls/*` | 权限不足，或非服务 / desktop 模式下重启 |
| `INTERNAL_ERROR`（复用） | 500 | `/api/service/restart` | 服务单元未安装，与基线一致 |
| `PLUGIN_INVALID_ARCHIVE`、`PLUGIN_ALREADY_EXISTS`、`PLUGIN_INSTALL_FAILED`（复用） | 400 / 409 / 502 | CLI `octop plugin install` | CLI 沿用既有写法转成 `ClickException(exc.message)`，HTTP 状态不外露 |
| 409（`HTTPException`，沿用基线） | 409 | `PUT /api/onnx-models/config` | 模型未预置；沿用基线的 `detail` 文案 |

保留但不再使用的码：`SKILLHUB_SSL_FAILED`、`EXPERT_MARKET_FAILED`、`TLS_NOT_ELIGIBLE`、`TLS_ISSUE_IN_PROGRESS`、`TLS_DOMAIN_MISMATCH`、`SKILL_IMPORT_UNSUPPORTED_URL`（理由见"方案"第 8 点）。

被删除的路由对外表现为：未带令牌时由 JWT 中间件返回 401；带有效令牌时，路径完全不存在则返回 404，路径与保留路由的模板重合但方法不同则返回 405（例如 `POST /api/agents/{id}/skills/import` 会落到 `PUT/DELETE /agents/{agent_id}/skills/{name}` 的模板上）。因此守卫测试以路由表为准，不以状态码为准。

## 安全考虑

- **攻击面收缩**：删掉以服务身份执行公网脚本的 `curl | bash`、按用户输入访问任意 URL 的技能 / 插件下载，以及控制台上传可执行插件的通道。插件只能随镜像预置，或由有主机权限的运维用 CLI 安装。
- **重启权限**：`service_control` 只控制"重启本进程"；`GET /api/service/status` 只返回版本号与服务模式，可见范围与基线 `/update/status` 相同（登录即可），不再暴露 `is_editable`、`source`、`release_notes` 等信息。
- **私钥处理**：
  - 私钥只出现在请求体与 `~/.octop/ssl/privkey.pem`（POSIX 0600）中；
  - 不写日志、不进审计、不进响应，校验异常信息只含 `reason` 机器码；
  - 私钥落盘加密归 `w3-05` / `p2-02`；备份包是否包含 `ssl/` 目录维持基线行为，由 `w3-05` 评估。
- **请求体大小**：Pydantic `max_length` 限制证书 64 KiB、私钥 16 KiB。
- **证书质量**：只校验可解析、匹配、在有效期内，不校验链是否可信。行内 CA 不在系统信任库里，这里做可信链校验会误拒；可信性由客户端浏览器与行内 PKI 保证。`cryptography` 不支持国密 SM2 密钥，SM2 证书与私钥会以 `key_invalid` 或 `certificate_invalid`（取叶子公钥时抛 `UnsupportedAlgorithm`）被拒绝；一期按 D8 默认假设使用 RSA / ECDSA 证书。
- **80 端口伴随应用**：上传模式默认 `http_port=0`，伴随应用不启动，因此不需要 `w3-01` 为它补安全头；Let's Encrypt 存量实例与手工设置 `http_port` 的部署仍会启动它，由 `w3-01` 覆盖。
- **审计**：证书上传写 `tls.certificate.upload`。重启沿用基线行为，本 spec 不新增审计点，完整审计基线归 `w3-02`。
- **JWT 豁免**：`deps.py` 的豁免清单不含任何被删或新增的路径；新路由全部受 JWT 中间件保护。

## 测试策略

| 类别 | 用例 | 本地命令 |
|---|---|---|
| 守卫：token | `tests/unit/test_online_fetch_tokens_removed.py`：用 `pathlib` 遍历，以 UTF-8 读取，逐 token 断言不出现；清单为 `pypi.org`、`mirrors.cloud.tencent.com`、`pypi.tuna.tsinghua.edu.cn`、`mirrors.ustc.edu.cn`、`skillhub.cn`、`skillhub-1388575217`、`_install_skillhub_cli`、`clawhub.ai`、`https://skills.sh`、`skillsmp.com`、`api.github.com`、`raw.githubusercontent.com`、`ollama.pull(`、`ollama.com/download`、`huggingface.co`、`hf-mirror.com`、`octop-1258344699`、`api.ipify.org`、`letsencrypt.org`、`from acme`、`josepy`、`install_auto_renewal_job`、`octop_tls_auto_renew`（任务 2 建空清单，后续任务逐批加入） | `uv run pytest tests/unit/test_online_fetch_tokens_removed.py -q` |
| 守卫：路由 | `tests/unit/api/test_online_fetch_removed_routes.py`：`write_octop_config(enable_api_docs=True)`，启动 `OctopServer` 并 `build_app`；收集 `app.routes` 的 `(path, method)` 与 `/api/openapi.json` 的 `paths`，断言删除清单不相交、新增清单存在；`build_http_companion_app(https_port=443).routes` 不含 `/.well-known/acme-challenge/{token}` | `uv run pytest tests/unit/api/test_online_fetch_removed_routes.py -q` |
| 单测：服务控制 | `tests/unit/api/test_service_control_router.py`：由 `test_update_router.py` 的三个重启用例迁移（systemd 后台重启、服务未安装、desktop `execv`）；`_local_version` 的两个分支；`tests/unit/cli/test_update_cmd_removed.py`：`octop --help` 不含 `update`，`octop update` 退出码非零 | `uv run pytest tests/unit/api/test_service_control_router.py tests/unit/cli/test_update_cmd_removed.py tests/unit/api/test_acl_gate_coverage.py tests/unit/users -q` |
| 集成：服务控制 | `tests/integration/test_service_control_api.py`：`GET /api/service/status` 的字段与版本号；未登录 401；持 `service_control` 的非管理员在未设 `OCTOP_SERVICE_MODE` 时得 403 `FORBIDDEN`；只持 `tls` 的非管理员得 403 | `uv run pytest tests/integration/test_service_control_api.py -q` |
| 迁移 | `tests/unit/db/test_fork_permission_keys.py`：替换、去重、保序、幂等、缺表跳过、非法 JSON 视为空；`tests/integration/test_service_control_permission_migration.py`：直接写入含 `update` 的老用户与 `update.stable_only` 行，用 `set_fork_version(pool, v - 1)` 回拨水位（`v` 从 `_FORK_PY_STEPS` 反查，不写死）后调用 `run_fork_migrations(pool)`，再以管理员 `PATCH /api/users/{id}` 改显示名得 200，读回为 `service_control` | `uv run pytest tests/unit/db/test_fork_permission_keys.py tests/integration/test_service_control_permission_migration.py -q` |
| PG | 同一迁移用例加 `requires_postgresql` 的 PG 版本（参照 `tests/integration/test_postgresql_control_plane.py`），验证 JSONB 列写回 | `OCTOP_TEST_DATABASE_URL=<专用库 DSN> uv run pytest tests/integration/test_service_control_permission_migration.py -q`，或 `OCTOP_TEST_DATABASE_URL=<DSN> make test-postgresql` |
| 单测：技能 / 专家 | 删除的测试：`test_skills_hub_raw.py`、`test_skillhub_market.py`、`test_skillhub_http_market.py`、`test_skill_package_from_skillhub.py`、`test_skillhub_install_metadata.py`、`test_skills_hub_errors.py`、`tests/integration/test_skills_hub.py`；修改的测试：`test_skill_install.py` 删 `test_prepare_skillhub_package_adds_presentation_metadata`，`test_skills_api.py` 删 `test_import_skill_from_url`、`test_import_rejects_unsupported_url`、`test_import_rejects_adapter_upload_outside_skill_root`，`test_skill_packages_api.py` 删 `test_import_skill_url_into_package`、`test_create_package_from_skillhub_returns_skills_and_rejects_duplicate_name`，`test_experts_api.py` 删 `test_hub_install_mounts_skill_packages`、`test_hub_install_rejects_unknown_package_before_creation`，`test_octop_builtin_skills.py` 删 `test_manager_installs_namespaced_skillhub_page_url`；新增用例：带 `metadata.octop.source: skillhub` 的技能可列出、启停、删除，`skill-manager` 对 `skillhub:foo` 报错且不调用 `skillhub`；专家库对缓存目录中的专家可 `get` | `uv run pytest tests/unit/skills tests/unit/agents tests/integration/test_skills_api.py tests/integration/test_skill_packages_api.py tests/integration/test_experts_api.py -q` |
| 单测：插件 | `test_plugin_manager.py` 删 URL 相关用例；新增 `tests/unit/cli/test_plugin_cmd.py`（目录安装、ZIP 安装、URL 被拒且 `urllib.request.urlretrieve` 未被调用）；`test_plugin_upload.py` 只留 `test_list_plugins_is_available_to_authenticated_users`；`test_plugin_tool_disable.py` 改用 `srv.plugin_manager.install_path(_FIXTURE)` 装插件 | `uv run pytest tests/unit/test_plugin_manager.py tests/unit/cli/test_plugin_cmd.py tests/integration/test_plugin_upload.py tests/integration/test_plugin_tool_disable.py -q` |
| 单测：模型 | `test_models_cmd.py` 改为断言无 `ollama-pull`；`test_onnx_service.py` 删两个下载用例，新增"`_build_text_embedding` 传 `local_files_only=True`"（用 `monkeypatch.setitem(sys.modules, "fastembed", …)` 注入假模块）；删 `test_onnx_download.py` 与 `test_knowledge_bases.py::test_onnx_download_starts_catalog_model`；`test_onnx_models_api.py` 新增"缺省请求体与 `download_if_missing: true` 都返回 409"与"`status.download.status == "idle"`" | `uv run pytest tests/unit/cli/test_models_cmd.py tests/unit/agents/test_onnx_service.py tests/unit/api/test_knowledge_bases.py tests/integration/test_onnx_models_api.py -q` |
| 单测：TLS | 删 `test_challenge.py`、`test_preflight.py`、`test_renewal.py`、`test_modes.py`；`test_tls_store.py` 改测 `install_uploaded_cert`（文件内容、`config.json` 的 `tls` 段、`bind_host` / `port` 不变、私钥 0600 仅在 `posix_only` 下断言）；新增 `tests/unit/infra/setup/tls/test_upload.py`：用 `cryptography` 在 `tmp_path` 现场生成 RSA 与 EC 自签证书，覆盖 7 个 `reason` 与 SAN / CN 提取；新增 `test_tls_manager.py`：三态判定与 `dual_listeners` 口径；`test_listeners.py` 不变并新增"`http_port=0` 时单端口"；`load_config` 对含 `acme_staging` 的 `config.json` 成功 | `uv run pytest tests/unit/infra/setup/tls -q` |
| 集成：TLS | `tests/integration/test_tls_certificate_api.py`：有效上传返回 `restart_required` 且文件与 `config.json` 正确、审计行存在且不含私钥；7 类非法输入均为 400 `TLS_CERT_INVALID`，且 `ssl/` 目录与 `config.json` 均未改动；只持 `channels` 的用户得 403 | `uv run pytest tests/integration/test_tls_certificate_api.py -q` |
| i18n | 新码的三方相等、overlay 对等、形状 | `uv run pytest tests/unit/i18n -q` |
| 前端 | 删除 `useUpdateStatus.test.ts`、`updateStatusCache.test.ts`、`SkillsetFromHubDrawer.test.tsx`；修改 `SkillImportModal.test.tsx`（去掉切换到 ZIP 的步骤）、`skillPackages.test.ts`（删 `fromSkillHub` 断言）、`knowledgeBases.test.ts`（删下载方法断言）；新增 `service.test.ts`、`tls.test.ts`、`hooks/useServiceStatus.test.ts`（两次调用只发一次请求） | `cd dashboard && npx tsc -b && npm run lint && npm run test`，或 `make check-frontend`（`w0-02`） |
| 锁文件 | `acme`、`josepy`、`pyopenssl`、`pyrfc3339` 不在 `uv.lock` 中 | `! rg -n '^name = "(acme|josepy|pyopenssl|pyrfc3339)"$' uv.lock && uv lock --check` |
| 手工 | 在已有 ONNX 模型缓存的机器上，断网执行 `embed_texts`（见 tasks 任务 13）；上传行内证书后重启，并用 `curl --cacert <行内 CA> https://<host>:<port>/api/health` 验证 | 见 tasks.md |

所有新增 Python 测试遵守 AGENTS.md §7：只用 `pathlib` 与 `tmp_path`，设置 `OCTOP_HOME` 时用 `monkeypatch.setenv`，文件模式断言标 `posix_only`，不硬编码 POSIX 路径。

## 与其他 spec 的交接

**依赖：**

- `w0-01-fork-migration-namespace`：`forkNNN_` 命名、`run_fork_migrations`、`set_fork_version`、`_FORK_PY_STEPS` 与静态成对检查。
- `w0-02-ci-gates`：`make check-frontend` 与 CI 的 frontend job 负责执行本 spec 的 vitest 用例；`make test-postgresql` 与 postgres service 负责执行 PG 迁移用例。
- `w0-03-test-auth-baseline`：`env` 夹具与 `sorted(ALL_PERMISSION_KEYS)` 授权；本 spec 改键后夹具无需改动。
- `w0-04-fork-isolation-points`：两对 overlay 与读取合并 bundle 的三方相等门禁、`make relock`、`CHANGELOG-intranet.md`、`docs/api-intranet.md`。
- `w1-02-capability-trim`：先于本 spec 合入，已删掉 ACP、终端、远程浏览器、远程桌面、远程手机的路由与权限键，并改过 `app.py` 挂载表、`permissions.py`、`GATED_FILES`、`pyproject.toml`。本 spec 在其结果上改同一批文件。若它已提供通用的权限键改写函数，本 spec 直接复用。

**交付给：**

| 消费方 | 交付物 |
|---|---|
| `w2-01-offline-build` | ① 模型必须离线预置：ONNX 放在 `~/.octop/embedding_models/models--<org>--<name>/`，采用 Hugging Face 缓存布局（含 `refs/main` 与 `snapshots/`），`is_model_downloaded` 认可即可；Ollama 模型在 Ollama 主机上预置。② 基线的预置导出逻辑可从 `git show 757fd12:src/octop/infra/agents/providers/onnx_download.py` 中的 `export_model_tree_for_cos`、`hf_cache_snapshot_dir` 取用，写成构建期脚本。③ 本 spec 已删 `acme`、`josepy`，`w2-01` 收窄依赖时以此为起点。④ 本 spec 的 token 守卫可被其全量 `test_no_public_endpoints.py` 吸收。⑤ 以下仍属运行期下载，由 `w2-01` 关闭：`ensure_local_embedding_deps(allow_install=True)`（`onnx_models.py`、`knowledge_bases.py`、`onnx_service.py` 共多处调用）、插件 `load_plugin_dir(..., install_deps=True)`、OCR 依赖、连接器 CLI |
| `w3-01-web-security-baseline` | 上传模式下 80 端口伴随应用默认不启动；存量 Let's Encrypt 实例与手工设置 `tls.http_port` 的部署仍会启动它，需要覆盖。上传入口清单比基线少 `POST /api/plugins/upload` 一个；证书上传是 JSON 请求体，不属于文件上传入口 |
| `w3-02-audit-baseline` | 新审计动作 `tls.certificate.upload`，按冻结字段集纳入；`service.restart` 是否审计由其决定 |
| `w3-03-authorization-foundation` | 新权限键 `service_control`，三员分立时归系统管理员；前端 4 处绕过清单里不含本 spec 新增的判断 |
| `w3-05-credential-encryption` / `p2-02-kms-sm-crypto` | `~/.octop/ssl/privkey.pem` 的落盘保护；SM2 证书支持 |
| `w4-01-frontend-baseline` | 删除 `PwaUpdatePrompt` 时一并去掉它对 `serviceApi` 的两处调用；外链与远程 `icon_url` 过滤；孤儿 CSS 类（`skillHub*`、`stagingRow` 等）可一并清理 |
| `w4-02-ops-minimum` | 运维手册写明：升级 = 换镜像 tag + 重启；插件用 `octop plugin install <目录或 .zip>`；证书也可用 `octop run --ssl --certfile --keyfile` 或手工编辑 `config.json` |
| `w1-04-content-trim` | `service_control.py` 保留了 desktop 重启分支（读 `OCTOP_GREEN_PACKAGES` / `OCTOP_DESKTOP`），按 D9 删除 desktop 时一并删掉；`README*`、`docs/cli.md`、`docs/user-guide.md` 中关于 `octop update` 与一键脚本的段落，由其随安装脚本一起处理，或留给 `w4-02` 重写 |

**看似相关、但归别的 spec：**

| 事项 | 归属 |
|---|---|
| `w0-04` 示例中把联网搜索（`search:router`）登记进 `_FORK_DISABLED_MOUNTS` | `w1-05`（公网 SaaS 断开）；本 spec 不登记任何下线项 |
| `browser/env.py` 的在线安装 Chromium、`infra/mobile/docker_install.py` | `w1-02` |
| `launch.py` 的 bubblewrap 自动安装、`docker_env.py`、`backend/probe.py::ensure_docker_image`、`runtime_packages.py`、Dockerfile、lock 行内化 | `w2-01` |
| 云验证码、`tencent_sign.py`、元宝云元数据、在线语音 | `w1-05` |
| `manifest_generator.py` 因市场下线失去生产调用方（只剩单测） | 登记为死代码，`w1-04` 或后续清理时处理 |
| `pages/Agent/Memory/VectorSearchConfig.tsx`、`pages/Settings/Embedding/index.tsx` 调用不存在的 `/api/embedding/*` | 无关死代码，登记 |
| `skill-manager` 对普通 URL、Git 仓库的下载能力 | 这是 Agent 在工作区里执行脚本的一般能力，受 `w3-06` 的执行审批与 `p2-01` 的网络隔离约束，本 spec 只删 SkillHub 分支 |

## 风险与回滚

| 风险 | 影响 | 缓解 |
|---|---|---|
| `skills.py`（1417 行）、`experts.py`、`skill_packages.py`、`SkillPackages/index.tsx`、`ProviderConfigModal.tsx`、`KnowledgeBases/index.tsx` 是上游高频文件 | 同步时冲突多 | 删除都是整段连续块，冲突时一律保留删除；两个守卫测试会拦住同步时回流的路由与 token，同步者据此重删 |
| 上游继续修改 `update.py` / `self_update.py` | modify/delete 冲突 | 一律保留删除；如果上游在 `update.py` 里改了重启逻辑，人工比对后移植到 `service_control.py` |
| fastembed 的 `local_files_only=True` 与存量缓存不兼容 | 已下载的模型加载失败 | 基线下载器会写 `refs/main`（`onnx_download.py` ≈L344-346），布局与 HF 一致；任务 13 用断网手工验证；失败时回退这一行，靠 `is_model_downloaded` 前置检查兜底 |
| 删掉插件上传后，行方要求控制台可装插件 | 功能缺失 | 在"待行方确认"中列出；`install_archive` 保留，恢复一个上传端点的成本不到 0.5 人日 |
| 上传模式设 `http_port=0`，用户习惯 80→443 跳转 | 访问 http:// 失败 | HTTPS 页提示"改用 https://"；需要跳转时手工设置 `tls.http_port`，或由前置负载均衡跳转 |
| 上传后重启，浏览器仍在 http:// 页面 | 重启遮罩一直等到超时 | 提示文案说明重启后要改用 https:// 访问；`useServiceRestart` 的超时态本身可恢复 |
| 存量 Let's Encrypt 实例失去自动续期 | 90 天后证书过期 | `CHANGELOG-intranet.md` 写明；HTTPS 页对 `mode="letsencrypt"` 显示"请上传行内证书替换" |
| 权限改名后，前端 `advancedPage` 不含 `service_control` | 只持 `service_control` 的用户看不到应用设置页 | 这是有意的：该键只控制 API；持 `tls` 或 `backup` 的用户能在对应页面点重启 |

**回滚：**

- 代码可以按任务粒度 `git revert`，每个顶层任务一个提交。
- 迁移不可逆，但影响可控：`service_control` 在回滚后的代码中是未知键，编辑这些用户会触发 `validate_permission_keys` 的 `ValueError`。回滚任务 3 时，要同时写一个反向 Python 步骤（`service_control` → `update`），并用新的 fork 号 fix forward，不能改已合入的迁移文件。
- `settings` 里被删的 `update.stable_only` 只是升级通道偏好，回滚后缺省为 `true`，与基线默认一致。
- 删掉的 TLS 签发、市场、下载代码回滚后即可恢复；`config.json` 中 `mode="uploaded"` 的 `tls` 段，基线代码也能按 `cert_file` / `key_file` 正常加载。

## 待行方确认

- **D4（部署形态）**：默认按"容器平台单副本、端口由平台决定"设计，上传模式不改端口、不开 80。如果行方要求 Octop 自身监听 443 并提供 80→443 跳转，就改为在上传请求中增加可选的 `http_port`（约 0.25 人日），伴随应用由 `w3-01` 覆盖。
- **D8（国密与密评）**：一期只接受 RSA / ECDSA 证书，SM2 证书与私钥会被拒绝（`key_invalid` 或 `certificate_invalid`）。如果一期就要求国密 HTTPS，建议由前置国密网关终止 TLS，Octop 内部走 HTTP，或提前做 `p2-02`。
- **D9（`desktop/`、`fnos/`）**：默认不交付。`service_control.py` 暂时保留 desktop 重启分支以保持行为等价，由 `w1-04` 删除。
- **D2（行内大模型平台是否含 Embedding）**：如果没有 Embedding，知识库依赖本地 ONNX 模型，那么模型预置（`w2-01`）就是必需项而非可选项。
- **非 D 编号：技能与插件的行内分发方式。** 本 spec 默认技能只能通过本地 ZIP 上传分发，插件只能随镜像预置或由运维用 CLI 安装，不建行内技能仓库或插件市场。如果行方要求控制台上传插件，就恢复 `/api/plugins/upload`（约 0.5 人日）；如果要求行内技能仓库，需另立 spec（约 3-5 人日）。
- **非 D 编号：TLS 终止位置。** 如果行内统一由负载均衡或网关终止 TLS，本 spec 的上传功能只作为直连部署的备选，不影响其他交付。
