# 实施计划：公网 SaaS 断开

> spec：`w1-05-saas-decoupling` ｜ 波次：Wave 1 ｜ 基线：`757fd12` ｜ 预估：24 人日
> 前置：`w0-01-fork-migration-namespace`、`w0-02-ci-gates`、`w0-03-test-auth-baseline`、`w0-04-fork-isolation-points`、`w0-05-ssrf-intranet-allowlist`、`w1-01-security-hotfix`、`w1-02-capability-trim` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

每个顶层任务完成后可独立提交；提交前运行任务内的验证命令。

各任务标注的人日合计约 22；预估中另留约 2 人日用于控制台手工冒烟（MQTT 通道、OIDC 登录、WeKnora / Dify 接入、OpenAI 兼容语音）与评审返工。守卫测试按任务增量填充：每个删除任务先把自己的路由与域名加进清单（此时变红），再做删除使其变绿。

- [ ] 1. 确认前置 spec 已合入并记录基线（0.25 人日）
  - 改动：无代码改动。核对前置交付物存在：`src/octop/infra/db/fork_migrate.py`（`_FORK_PY_STEPS`、`set_fork_version`、`run_fork_migrations`）、`src/octop/infra/db/fork_steps.py`（`strip_permission_keys`）、`src/octop/infra/connectors/catalog_intranet.py`（`_FORK_REMOVED`）、`src/octop/api/intranet_mounts.py`、`src/octop/i18n/intranet/{en,zh}.json`、`dashboard/src/locales/intranet/{en,zh}.json`、`src/octop/infra/utils/intranet_allowlist.py`、`src/octop/infra/capabilities.py`（`REMOVED_CAPABILITY_TOOLS`、`forced_disabled_tools`）、`tests/support/auth_guards.py`、`CHANGELOG-intranet.md`、`docs/api-intranet.md`、`Makefile.intranet` 的 `relock` 目标。在本地打标签 `w1-05-base`，供需求 12.4 的 diff 使用。
  - 验证：`for f in src/octop/infra/db/fork_migrate.py src/octop/infra/db/fork_steps.py src/octop/infra/connectors/catalog_intranet.py src/octop/api/intranet_mounts.py src/octop/i18n/intranet/en.json dashboard/src/locales/intranet/en.json src/octop/infra/utils/intranet_allowlist.py src/octop/infra/capabilities.py tests/support/auth_guards.py CHANGELOG-intranet.md docs/api-intranet.md; do test -f "$f" || echo "MISSING $f"; done && make all && git tag w1-05-base`
  - _需求：4.6, 12.4_

- [ ] 2. 建立两条守卫测试（空清单）（0.5 人日）
  - 改动：新增 `tests/unit/test_saas_tokens_removed.py`：`REPO = Path(__file__).resolve().parents[2]`，遍历 `src/octop/**/*.py` 与 `dashboard/src/**/*.ts`、`dashboard/src/**/*.tsx`，排除 `src/octop/infra/connectors/catalog.py`（`w0-04` 规定 `_BASE` 不改）与 `dashboard/src/assets/providers/index.ts`（`w4-01`），以 UTF-8 读取，对清单 `REMOVED_TOKENS: tuple[str, ...] = ()` 中的每个字符串参数化断言不出现，失败信息列出命中文件。
  - 改动：新增 `tests/unit/api/test_saas_removed_routes.py`：`write_octop_config(enable_api_docs=True)` 启动 `OctopServer`、`ensure_control_plane_bound`、`build_app`；收集 `app.routes` 的 `(path, method)` 与 `/api/openapi.json` 的 `paths`；清单 `REMOVED_ROUTES: tuple[tuple[str, str], ...] = ()` 断言不相交；另断言 `/api/auth/oidc/callback`（GET）与 `/api/auth/oauth/exchange`（POST）存在。
  - 验证：`uv run pytest tests/unit/test_saas_tokens_removed.py tests/unit/api/test_saas_removed_routes.py -q`
  - _需求：12.1, 12.2_

- [ ] 3. 通道：Octop 自有 `ChannelKind` 与运行期闸门（1 人日）
  - [ ] 3.1 先写失败用例
    - 改动：新增 `tests/unit/gateway/test_channel_kind_allowlist.py`：`{k.value for k in ChannelKind} == {"mqtt"}`；`octop.infra.gateway.gateway.ChannelKind is octop.infra.gateway.channel_kinds.ChannelKind`；`(REPO / "src/octop/infra/gateway/gateway.py").read_text()` 不含 `harness_gateway.channels`；`Gateway.create_channel(ChannelCreateSpec(kind="feishu", …))` 与 `update_channel(…, kind="qq")` 抛 `OctopError`（`CHANNEL_KIND_UNSUPPORTED`）；给 `_channel_manager` 挂 `AsyncMock`，对 kind 为 `feishu` 的 `ChannelRow` 调 `_safe_register_channel` 后 `add_channel` 未被调用且运行态 `reason == "error"`；`probe_config(kind="feishu", …)` 返回 `ok is False` 且 `probe_channel` 未被调用。
    - 改动：新增 `tests/unit/cli/test_channel_cmd.py`（`monkeypatch.setenv("OCTOP_HOME", str(tmp_path))`，`click.testing.CliRunner` 调 `octop.cli.main.cli`，沿用 `test_chats_cmd.py` 的 monkeypatch 写法）：把 `octop.cli.commands.channel.require_agent` 与 `_resolve_user` 替换为返回固定值，`channel create --agent a1 --kind feishu` 的退出码非 0；另用 `octop.cli.support.db.open_cli_services(tmp_path)` 建用户与 agent 后直接调 `create_channel_offline(..., kind="feishu", home=tmp_path)` 抛 `OctopError` 且 `channel_repo` 中无行，`kind="mqtt"`、`config={"host": "broker.intranet"}` 时成功。
    - 验证：`uv run pytest tests/unit/gateway/test_channel_kind_allowlist.py tests/unit/cli/test_channel_cmd.py -q`（此时应失败）
    - _需求：1.1, 1.2, 1.3, 1.4_
  - [ ] 3.2 实现白名单与闸门
    - 改动：新增 `src/octop/infra/gateway/channel_kinds.py`：`ChannelKind(StrEnum)` 只含 `MQTT = "mqtt"`、`SUPPORTED_CHANNEL_KINDS`、`is_supported_channel_kind`、`ensure_supported_channel_kind`（抛 `OctopError(ErrorCode.CHANNEL_KIND_UNSUPPORTED, …)`）。
    - 改动：`src/octop/infra/gateway/gateway.py`：≈L14 导入改为 `from octop.infra.gateway.channel_kinds import ChannelKind, ensure_supported_channel_kind, is_supported_channel_kind`；`create_channel` 开头、`update_channel` 在 `kind is not None` 时、`_register_channel` 开头各调用一次 `ensure_supported_channel_kind`；`_probe_row` 开头对不支持的 kind 返回 `{"ok": False, "error": tr("errors.CHANNEL_KIND_UNSUPPORTED", locale)}`。
    - 改动：`src/octop/cli/support/offline_ops.py::create_channel_offline` 开头调用 `ensure_supported_channel_kind(kind)`。
    - 验证：`uv run pytest tests/unit/gateway/test_channel_kind_allowlist.py tests/unit/cli/test_channel_cmd.py -q`
    - _需求：1.1, 1.2, 1.3, 1.4_
  - [ ] 3.3 让既有用例改用 `mqtt`
    - 改动：`tests/integration/conftest.py::env_with_channel`（≈L193-205）、`tests/integration/test_channels_api.py`（≈L30、L99、L115）、`tests/integration/test_channel_probe_draft.py`（≈L26）、`tests/unit/gateway/test_gateway.py`、`tests/unit/gateway/test_gateway_probe.py`（≈L76）的 kind 改为 `mqtt`，config 改为 `{"host": "broker.intranet"}`；`tests/unit/backup/test_system_archive.py`（≈L865、≈L1057）的 `migrated-feishu` 夹具 kind 改为 `mqtt`（任务 21 的迁移会删除已删 kind 的行）。其余只把 IM 名当不透明 `channel_type` 字符串的用例不改，以实际失败为准。
    - 验证：`uv run pytest tests/unit/gateway tests/integration/test_channels_api.py tests/integration/test_channel_probe_draft.py tests/integration/test_channel_test_endpoint.py tests/unit/backup/test_system_archive.py tests/unit/gateway/test_dashboard_ws.py tests/unit/gateway/test_cli_channel.py -q`
    - _需求：1.1, 1.5_

- [ ] 4. 通道：删除扫码与一键建号（后端与 CLI）（1 人日）
  - 改动：守卫清单追加 14 个路由（`POST /api/agents/{agent_id}/channels/{dingtalk,wecom,qq,weixin}/qrcode/{generate,poll}`、`POST /api/agents/{agent_id}/channels/{feishu,yuanbao}/bot-creator/{start,poll,stop}`）与域名 `ilink.b.qq.com`、模块名 `lark_oapi`。
  - 改动：`src/octop/api/routers/channels.py` 删除 ≈L25-26 两行导入、≈L54-75 bot creator 请求体与 `_parse_bot_creator_body`、≈L263 `# ─── QR scan helpers ───` 起到文件末尾的全部代码，并删除随之孤立的标准库与 `parse_subprocess_json_lines` 导入（以 `ruff` 为准）；保留 ≈L22-24 与 ≈L27。
  - 改动：删除目录 `src/octop/infra/gateway/bot_creators/`、`src/octop/infra/gateway/channels/` 与文件 `src/octop/cli/support/feishu_creator.py`。
  - 改动：`src/octop/cli/commands/channel.py` 删除 `bind` 组及 `bind_qq` / `bind_wecom` / `bind_weixin`、`feishu_setup`；`config_channels` 的 kind 列表改为 `sorted(SUPPORTED_CHANNEL_KINDS)`，删除 QR / 飞书 / QQ 分支；`src/octop/cli/support/qr.py` 删除 `render_qrcode_terminal` 及其私有辅助函数，保留 `mask_secret`。
  - 改动：`src/octop/infra/utils/locale.py` 删除 `im_zh` 与 `telegram` 分支；`src/octop/infra/gateway/process/response_mode.py` 删除 `_config_flag`、`qq_channel_response_mode` 与其 `__all__` 项；`gateway.py` 删除 `qq_channel_response_mode` 导入与 `_register_channel` 的 qq 分支、`_format_probe_error` 的飞书分支；`src/octop/api/openapi_meta.py` channels tag 描述改为 MQTT。
  - 改动：删除 `tests/unit/gateway/test_channels_qr.py`、`tests/unit/gateway/test_feishu_bot_creator.py`、`tests/live/test_channel_probe.py`；`tests/unit/gateway/test_response_mode.py` 删除 `test_qq_channel_streams_by_default` 与导入；`tests/unit/test_user_locale.py` 按新逻辑调整渠道提示断言；`tests/unit/cli/test_channel_cmd.py` 增加 `--help` 不含 `bind`、`feishu-setup` 的断言。
  - 验证：`test ! -e src/octop/infra/gateway/bot_creators && test ! -e src/octop/infra/gateway/channels && test ! -e src/octop/cli/support/feishu_creator.py && uv run pytest tests/unit/test_saas_tokens_removed.py tests/unit/api/test_saas_removed_routes.py tests/unit/gateway tests/unit/cli tests/unit/test_user_locale.py tests/integration/test_channels_api.py -q`
  - _需求：1.4, 2.1, 2.2_

- [ ] 5. 通道：前端只保留 MQTT（2 人日）
  - [ ] 5.1 注册表、barrel 与 API 模块
    - 改动：`dashboard/src/pages/Agent/Channels/components/constants.test.ts` 改写为：`CHANNEL_KEYS` 等于 `["mqtt"]`、`CHANNEL_FIELDS.mqtt` 的必填字段为 `host`、`hasRequiredCredentials("mqtt", {host: "x"})` 为真、`getChannelColor("unknown")` 有回落值（先写，此时失败）。
    - 改动：`constants.ts`：图标导入只留 `mqtt`、`dashboard`、`console`、`octop`；`ChannelKey` 收窄为 `"mqtt" | "dashboard" | "agentchat" | "octopbot"`；`CHANNEL_KEYS = ["mqtt"]`；删除 `COLLAPSED_CHANNEL_KEYS`、`isCollapsedChannelKey`、`partitionChannelKeys`、`CHANNEL_URLS` 的公网条目、QQ 群上下文全套（≈L177-270）、`applyQqChannelSaveConfig`、`normalizeChannelFieldValue`；四张 Record、`CHANNEL_FIELDS`、`REQUIRED_CREDENTIALS` 只留白名单项。`components/index.ts` 删除 6 个已删符号的再导出。`dashboard/src/api/modules/channel.ts` 删除 ≈L95 起的 14 个扫码 / bot creator 方法。守卫清单追加 `q.qq.com`。
    - 验证：`cd dashboard && npm run test -- src/pages/Agent/Channels/components/constants.test.ts && cd .. && uv run pytest tests/unit/test_saas_tokens_removed.py -q`（`ChannelDrawer.tsx` 与 `ChannelsPanel.tsx` 仍引用已删符号，`tsc -b` 在 5.2 完成后才通过）
    - _需求：2.3_
  - [ ] 5.2 抽屉与面板
    - 改动：先改写 `ChannelsPanel.test.tsx` 的三个用例，改为点击 MQTT 卡片进入新建抽屉，保留"新建通道默认禁用"断言。
    - 改动：`ChannelDrawer.tsx` 删除 `qrcode.react` 导入、全部扫码与一键建号状态机、`render{Qq,Wecom,Weixin,Dingtalk,Feishu,Yuanbao}Panel` 及其分派（≈L1794-1799）、`QqGroupContextPolicyFields`（≈L255）与其渲染（≈L1788）、`getQqGroupContextConfig` 调用、飞书 / 元宝分支；`normalizeChannelFieldValue` 的两处调用改为直接取值，`applyQqChannelSaveConfig` 的两处调用删除；默认 kind 由 `"feishu"` 改为 `"mqtt"`。`ChannelsPanel.tsx` 删除 ≈L19-25 中已删符号的导入、≈L62 / ≈L82 调用、≈L142 的折叠分组、按 kind 的 QQ 配置处理与成功提示分支。守卫清单追加 `yuanbao.tencent.com`。
    - 验证：`cd dashboard && npx tsc -b && npm run lint && npm run test -- src/pages/Agent/Channels && cd .. && uv run pytest tests/unit/test_saas_tokens_removed.py -q`
    - _需求：2.3, 2.4_

- [ ] 6. SSO：后端只留通用 OIDC（1 人日）
  - 改动：先改写用例。`tests/integration/test_auth_oauth.py`：删除 `test_oauth_callback_accepts_dingtalk_auth_code`；第一个用例改为断言 `status` 的 kind 集合为 `{"oidc"}`、`/oauth/start`（`kind="oidc"`）设置 state cookie、`/oidc/callback` 回跳后 `/oidc/exchange` 返回用户、`GET /api/auth/oauth/callback` 无令牌时返回 401（已不在 JWT 豁免中）、带管理员令牌时返回 404；第二个用例改为 `bind/start`（`kind="feishu"`）返回 422、`GET /api/auth/oauth/providers/oidc` 返回 `redirect_uri` 以 `/api/auth/oidc/callback` 结尾、`PUT /api/auth/oauth/providers/feishu` 返回 422。`tests/unit/api/test_jwt_auth_middleware.py` ≈L35 改为 `assert not is_jwt_exempt_path("/api/auth/oauth/callback")`。新增单测断言 `SSO_KINDS == ("oidc",)` 与 `set(build_adapters(service)) == {"oidc"}`（放在 `tests/unit/auth/test_sso_service.py` 末尾）。
  - 改动：删除 `src/octop/infra/auth/sso/providers/{feishu,dingtalk,wecom}.py`；`providers/__init__.py::build_adapters` 只返回 `oidc`；`providers/base.py` 改为 `SSO_KINDS = ("oidc",)` 并删除 `DEFAULT_OAUTH_CALLBACK_PATH`；`sso/public_base.py` 删除 `_OAUTH_CALLBACK_PATH` 与 `oauth_callback_path()`；`sso/service.py::put_config_for_kind` 删除三家分支（≈L159-181），默认显示名直接用 `"Octop SSO"`。
  - 改动：`src/octop/api/routers/auth_oauth.py`：`SsoKind = Literal["oidc"]`，删除 `/oauth/callback`（≈L101-127）与随之孤立的导入；`src/octop/api/deps.py` 从 `_JWT_EXEMPT_EXACT` 删除 `"/api/auth/oauth/callback"`；`src/octop/api/openapi_meta.py` 公开端点说明删除该路径。
  - 改动：删除 `tests/unit/auth/test_{feishu,dingtalk,wecom}_adapter.py`；守卫清单追加路由 `GET /api/auth/oauth/callback` 与域名 `accounts.feishu.cn`、`oapi.dingtalk.com`、`login.dingtalk.com`、`api.dingtalk.com`。
  - 验证：`uv run pytest tests/integration/test_auth_oauth.py tests/integration/test_auth_oidc.py tests/unit/auth tests/unit/api/test_jwt_auth_middleware.py tests/unit/test_saas_tokens_removed.py tests/unit/api/test_saas_removed_routes.py -q`
  - _需求：3.1, 3.2, 3.3, 3.4, 3.5_

- [ ] 7. SSO：前端收窄并删除 9 个通道品牌图标（1 人日）
  - 改动：先改 `dashboard/src/pages/Admin/Users/SsoPanel.test.tsx`（去掉 `getFeishuConfig` / `putFeishuConfig` / `testFeishuConfig` 桩）与 `dashboard/src/api/modules/sso.test.ts`（删除飞书包装用例）。
  - 改动：删除 `dashboard/src/pages/Admin/Users/{oauthProviders.ts,OauthProviderCard.tsx,SsoAppProviderShell.tsx}`；`Admin/Users/index.tsx` 删除 ≈L11、≈L15-17、≈L23-26、三家标签、`isOauthKind` 判定、`OauthTabPanel` 与 ≈L121-125 分支，只留"本地"与"OIDC"；`Login/index.tsx` 删除 ≈L20-22 图标导入与 ≈L38-54 三家分支；`components/AvatarDropdown.tsx` 删除 ≈L48-50 图标导入、`APP_OAUTH_KINDS`、`oauthProviderIcon` 与只服务三家的账号绑定列表（状态、处理函数、弹窗消息监听、≈L585 起的渲染块，以 `tsc` / `eslint` 报出的孤儿为准）；`api/modules/sso.ts` 删除 ≈L84-95 三个飞书包装与 `FeishuConfig` 类型别名；`utils/permissions.ts` 的 `USERS_TAB_PERMISSIONS` 删除三家。
  - 改动：删除 `dashboard/src/assets/channels/{dingtalk,discord,feishu,qq,telegram,wecom,weixin,yuanbao}.svg` 与 `xiaoyi.png`，保留 `mqtt.png`、`dashboard.svg`、`console.svg`、`octop.svg`。
  - 验证：`test "$(ls dashboard/src/assets/channels | sort | tr '\n' ' ')" = "console.svg dashboard.svg mqtt.png octop.svg " && ! rg -n "assets/channels/(feishu|dingtalk|wecom)" dashboard/src && cd dashboard && npx tsc -b && npm run lint && npm run test -- src/pages/Admin src/api/modules/sso`
  - _需求：3.6, 2.3_

- [ ] 8. 连接器：登记 `_FORK_REMOVED` 并重连后端测试（2 人日）
  - [ ] 8.1 目录收窄
    - 改动：先在 `tests/integration/test_connectors_api.py::test_catalog`（≈L23）断言 `GET /api/connectors/catalog` 的 kind 集合为 `{"weknora", "dify"}`，新增用例：以 `kind="tencent-docs"` 调 `POST /api/connector-instances` 返回 400、`error.code == "CONNECTOR_KIND_UNSUPPORTED"` 且 `GET /api/connector-instances` 为空；在 `tests/unit/test_connectors.py` 增加 `len(catalog_intranet._FORK_REMOVED) == 21` 与 `{e.kind for e in catalog._BASE} - _FORK_REMOVED == {"weknora", "dify"}`。
    - 改动：`src/octop/infra/connectors/catalog_intranet.py` 的 `_FORK_REMOVED` 填入设计文档列出的 21 个 kind，行尾注释 `# w1-05`；`catalog.py` 不改。
    - 验证：`uv run pytest tests/integration/test_connectors_api.py::test_catalog tests/unit/test_connectors.py -q -k "catalog or fork_removed"`
    - _需求：4.1, 4.4_
  - [ ] 8.2 单元测试重连
    - 改动：`tests/unit/test_connectors.py`：删除只测已删 kind 的用例；`test_every_catalog_entry_has_category`、`test_catalog_entry_dict_has_no_tools`、`test_connector_repo_supports_multiple_kinds_and_unique_names`、`test_validate_mcp_servers_for_user` 等通用用例的夹具换成 `weknora` / `dify`；保留 `tests/unit/test_connectors.py::test_weknora_rejects_non_https_remote_url`（`w0-05` 的基线守护）原样。`tests/unit/connectors/test_mcp_oauth_ssrf.py` 用字面量 issuer（取 `_BASE` 中 notion 条目的 `oauth_issuer` 值）替代 `issuer_for_kind("notion")`，SSRF 断言不变；`test_oauth_discovery.py` ≈L49-53 用 monkeypatch 让 `octop.infra.connectors.oauth.registry.get_mcp_oauth_remote` 返回桩条目；`test_custom_mcp.py`、`test_default_open.py`、`tests/unit/agents/test_mcp_tool_cache.py`、`tests/unit/agents/test_agent_manager.py`（≈L1345-1386 的 `tencent-ima`）夹具按实际失败换成 `weknora`。
    - 验证：`uv run pytest tests/unit/test_connectors.py tests/unit/connectors tests/unit/agents -q`
    - _需求：4.1_
  - [ ] 8.3 集成测试与白名单正向用例
    - 改动：`tests/integration/test_connectors_api.py` 删除 `test_catalog_weknora_dify_last`（≈L414-425），其余把作夹具的 `tencent-docs` 与 `qq-mail` 换成 `weknora` / `dify`；`tests/integration/test_experts_api.py`（≈L337、≈L406）与 `test_published_experts.py`（≈L128、≈L181）同样替换。新增用例：服务启动后进入 `w0-05` 的上下文管理器 `tests/support/outbound.py::use_intranet_allowlist(cidrs=["10.0.0.0/8"], allow_http=True)`，以 `http://10.1.2.3:8080` 为 `base_url` 创建 WeKnora 实例、以 `http://10.1.2.3/mcp/server/abc/mcp` 为 `mcp_url` 创建 Dify 实例均返回 201（创建路径不做网络探测）；退出上下文后同样的请求返回 400。`tests/live/test_connector_probe.py` 的 `_CONNECTOR_CASES` 只留 `weknora`、`dify`。
    - 验证：`uv run pytest tests/integration/test_connectors_api.py tests/integration/test_experts_api.py tests/integration/test_published_experts.py -q && make test`
    - _需求：4.1, 4.4, 4.6_

- [ ] 9. 连接器：删除网关适配器、CLI 网关与飞书用户授权（0.5 人日）
  - 改动：守卫清单追加 6 个路由（`GET /api/connectors/{kind}/cli-status`、`POST /api/connectors/{kind}/install-cli`、`POST /api/connectors/feishu-cli/user-auth/start`、`POST /api/connectors/feishu-cli/user-auth/complete`、`POST /api/connector-instances/{instance_id}/feishu-user-auth/start`、`POST /api/connector-instances/{instance_id}/feishu-user-auth/complete`）与域名 `open.feishu.cn`、`work.weixin.qq.com`、`qyapi.weixin.qq.com`；在 `tests/unit/test_connectors.py` 增加 `set(registry._ADAPTERS) == {"weknora"}`。
  - 改动：删除 `src/octop/infra/connectors/gateway/adapters/` 下 `baidu_map.py`、`ctrip_wendao.py`、`feishu_cli.py`、`fliggy.py`、`meituan_travel.py`、`qq_mail.py`、`qq_music.py`、`tencent_ima.py`、`tencent_news.py`、`wechat_reading.py`、`wecom_cli.py`、`yuandian.py`，以及 `gateway/` 下 `cli_dirs.py`、`cli_fingerprint.py`、`cli_install.py`、`cli_runner.py`、`feishu_creds.py`、`feishu_user_auth.py`、`wecom_creds.py`；`gateway/registry.py` 的导入与 `_ADAPTERS` 只留 `weknora`。
  - 改动：`src/octop/infra/server.py::start` 删除 ≈L284-288 的注释、`ensure_cli_path` 导入与调用；`src/octop/infra/connectors/service.py` 删除 ≈L35-39 两处导入与 ≈L503-630 六个飞书 CLI 成员；`src/octop/api/routers/connectors.py` 删除 ≈L40-46 三处导入、6 个端点及其请求 / 响应模型、`get_instance` ≈L654-656 的在线预览、`delete_instance` ≈L893-902 的 CLI 目录清理、`_credentials_preview` 中 feishu-cli / wecom-cli 子分支。
  - 改动：删除 `tests/unit/connectors/` 下 `test_cli_install.py`、`test_cli_runner_and_dirs.py`、`test_feishu_user_auth.py`、`test_feishu_user_auth_preview.py`、`test_feishu_wecom_cli.py`、`test_wecom_cli_errors.py`、`test_tencent_ima.py`；`tests/integration/test_connectors_api.py` 删除两个 install-cli 用例（≈L427、≈L435）。
  - 验证：`! rg -n "cli_install|ensure_cli_path|feishu_user_auth" src/octop && uv run pytest tests/unit/test_connectors.py tests/unit/connectors tests/integration/test_connectors_api.py tests/unit/test_saas_tokens_removed.py tests/unit/api/test_saas_removed_routes.py -q`
  - _需求：4.2, 4.3, 4.5_

- [ ] 10. 连接器：裁剪共享模块中的公网分支与邮箱主机表（1 人日）
  - 改动：守卫清单追加 `docs.qq.com`、`mcp.meeting.tencent.com`、`weiyun.com`、`lexiang-app.com`、`open.mail.163.com`、`mcp.didichuxing.com`、`imap.qq.com`。
  - 改动：`src/octop/infra/connectors/builder.py` 删除 ≈L17 `mail_servers` 导入、≈L23 `DIDI_MCP_BASE_URL`、≈L30 `normalize_weiyun_mcp_token`、`_build_remote_spec` 的 didi / tencent-docs / tencent-weiyun / tencent-meeting / tencent-lexiang / youdao-note 分支、`validate_create_credentials` 中 `personal_token` 的 weiyun 归一化（改为直接用原始 token）、`api_key` 分派的 8 个 kind 子分支、`imap_app_password` 分支、`session_cookie` 的 tencent-ima 子分支、`inject_missing_gateway_tools` 的 `ima_names` 日志字段。通用的 `oauth2` / `auth_code` / `api_key` / `api_credentials` 分派与 `is_mcp_oauth_remote` 分支保留。
  - 改动：`src/octop/infra/connectors/probe.py` 删除 `normalize_weiyun_mcp_token` 导入、`prepare_probe_credentials` 的 weiyun / youdao 分支、`_probe_mcp_http_error` 与 `_probe_mcp_mcp_error` 的 youdao 分支、`_probe_mcp_sse`、`probe_youdao_note`、`_probe_youdao_note_http_error`、`_REMOTE_STATIC_TOOL_KINDS` 及其判断、`probe_connector` 的 youdao 分支。
  - 改动：`src/octop/api/routers/connectors.py` 删除 `normalize_weiyun_mcp_token` 导入、`_prepare_credentials` 的 weiyun 分支、`_credentials_preview` 的 tencent-news / tencent-ima / tencent-lexiang / tencent-weiyun 子分支。删除 `src/octop/infra/connectors/mail_servers.py` 与 `tests/unit/connectors/test_mail_servers.py`。
  - 验证：`test ! -e src/octop/infra/connectors/mail_servers.py && uv run pytest tests/unit/test_connectors.py tests/unit/connectors tests/integration/test_connectors_api.py tests/unit/test_saas_tokens_removed.py -q && make typecheck`
  - _需求：4.3, 4.4_

- [ ] 11. 连接器：前端只呈现 WeKnora、Dify 与自定义 MCP（1.5 人日）
  - 改动：先按实际需要改写 `dashboard/src/pages/Agent/Connectors/ConnectorCard.test.tsx` 与 `guidedConnectorUtils.test.ts`，夹具改用 `weknora` / `dify`。
  - 改动：`connectorDefs.tsx` 删除 `MAIL_PROVIDERS`、`MailProviderId`、`INLINE_CREDENTIAL_GUIDE_KINDS`、`HIDE_INLINE_FIELD_GUIDE_KINDS`、`mailProviderById`；`Connectors/index.tsx` 删除 ≈L50-53 的导入、CLI 安装（≈L392、≈L514、≈L544）、飞书用户授权流程（≈L578-703 与相关状态）、邮箱服务商选择器、feishu-cli / wecom-cli / tencent-* 专属表单与渲染分支，保留 `custom_fields`（WeKnora、Dify）与自定义 MCP 路径；`dashboard/src/api/modules/connectors.ts` 删除 `cliStatus`、`installCli`、四个飞书授权方法与 `ConnectorCliInstallResult`、`FeishuUserAuthStartResult`、`FeishuUserAuthCompleteResult`；`dashboard/src/assets/connectors/index.ts` 只保留 `weknora`、`dify` 的导入与映射；删除该目录下其余 35 个图片。
  - 验证：`test "$(ls dashboard/src/assets/connectors | sort | tr '\n' ' ')" = "dify.svg index.ts weknora.svg " && cd dashboard && npx tsc -b && npm run lint && npm run test -- src/pages/Agent/Connectors`
  - _需求：4.7_

- [ ] 12. 模型：预设改读自维护清单（0.5 人日）
  - 改动：先重写 `tests/unit/test_provider_preset_expansion.py`：id 集合等于 `provider_presets.json` 的 id 并上 `{"onnx"}`；不含 `openai-codex`；非空 `base_url` 的主机名属于 `{"localhost", "127.0.0.1", "::1"}`；`onnx` 紧跟在 `ollama` 之后；把 `harness_agent.providers._USER_DIR` monkeypatch 到含 `providers_template.json` 的 `tmp_path` 后结果不变。
  - 改动：新增 `src/octop/infra/agents/providers/provider_presets.json`，内容为 harness 模板中 `ollama` 一条（`http://localhost:11434/v1`）；`presets.py::load_provider_presets` 改为 `load_provider_templates(str(Path(__file__).with_name("provider_presets.json")))`，删除 ≈L222-244 的 `openai-codex` 注入块与包内模板读取，保留 `onnx` 注入与 `_reasoning_profile`。
  - 改动：`tests/integration/test_providers_api.py` 与 `tests/integration/test_setup_wizard.py` 中如有断言公有云预设 id 的用例，按新清单改写（以实际失败为准）。
  - 验证：`uv run pytest tests/unit/test_provider_preset_expansion.py tests/integration/test_providers_api.py tests/integration/test_setup_wizard.py -q`
  - _需求：5.1, 5.2_

- [ ] 13. 模型：删除 Codex OAuth 与 `opencode_session.py`（0.75 人日）
  - 改动：守卫清单追加 3 个路由（`POST /api/admin/providers/codex-oauth/start`、`GET /api/admin/providers/codex-oauth/pending/{state_id}`、`DELETE /api/admin/providers/codex-oauth`）与域名 `chatgpt.com`、`auth.openai.com`、`opencode.ai`；新增单测：`ProviderStore.build_harness_configs()` 对 `base_url="https://opencode.ai/zen/go"` 的供应商行产出的 `ProviderConfig.session_header is None`，`probe.fetch_openai_compatible_models` 对同一 `base_url` 发出的请求头不含 `x-opencode-session`（monkeypatch `httpx.AsyncClient` 捕获请求）。
  - 改动：删除目录 `src/octop/infra/providers/`；`src/octop/api/routers/providers.py` 删除 ≈L27-35 导入、`_is_codex_base_url`、`_maybe_refresh_codex_row`、`_run_codex_device_poll`、三个 codex 端点与 ≈L477 调用；`src/octop/infra/agents/providers/probe.py` 删除 ≈L38-39 `_is_codex_base_url` 与 ≈L56 分支。
  - 改动：删除 `src/octop/infra/agents/providers/opencode_session.py`；`store.py` 删除 ≈L12-15 导入与 `session_header=` 实参；`probe.py` 删除 ≈L15 导入，≈L49、≈L168、≈L274 三处改为直接使用原 headers（`dict(headers) if headers else {}`）。
  - 改动：删除 `tests/unit/providers/test_codex_oauth.py`、`tests/unit/providers/test_opencode_session.py`；`tests/integration/test_provider_test_draft.py` 删除 `test_admin_codex_oauth_start`（≈L43）。
  - 验证：`test ! -e src/octop/infra/providers && test ! -e src/octop/infra/agents/providers/opencode_session.py && uv run pytest tests/unit/providers tests/integration/test_provider_test_draft.py tests/integration/test_provider_fetch_models.py tests/unit/test_saas_tokens_removed.py tests/unit/api/test_saas_removed_routes.py -q`
  - _需求：5.3, 5.4_

- [ ] 14. 模型：前端删除 ChatGPT 设备码登录（0.5 人日）
  - 改动：删除 `dashboard/src/pages/Settings/Models/components/CodexOAuthConnect.tsx`；`components/modals/PresetProviderModal.tsx` 删除 ≈L19 导入、≈L50 `isCodexOAuth` 与其 6 处分支；`Settings/Models/providerApi.ts` 删除 `startCodexOAuth`（≈L68）与 `pollCodexOAuth`（≈L76）。`presetUtils.ts` 不改。
  - 验证：`! rg -n "CodexOAuth|codex-oauth" dashboard/src --glob '!**/locales/**' && cd dashboard && npx tsc -b && npm run lint && npm run test -- src/pages/Settings/Models`
  - _需求：5.5_

- [ ] 15. 语音：后端只留 browser 与 OpenAI 兼容（1 人日）
  - 改动：先写用例。改写 `tests/unit/test_voice_manager.py`：删除 `test_set_active_edge_tts_only`、`test_edge_cannot_be_stt`，新增 `is_builtin_preset` 对 `edge` / `tencent` / `mimo` 为假、`load_voice_presets()` 的 kind 集合 ⊆ `{"browser", "openai"}`；改写 `tests/unit/test_voice_probe.py` 与 `test_voice_stt_probe.py`：OpenAI 行 `base_url=None` 时 `test_stt` / `test_tts` 返回 `ok is False`，且 monkeypatch 的 `httpx.AsyncClient` 未被构造；新增集成用例（放在 `tests/integration/test_voice_probe_http.py`）：`POST /api/admin/voice/providers` 以 `kind="tencent"` 返回 400、`error.code == "VOICE_KIND_UNSUPPORTED"`，`test-configuration` 同样。
  - 改动：`src/octop/infra/voice/presets.py` 的 `_BUILTIN_PRESET_IDS = frozenset({"browser", "openai"})`，只返回两条；`adapters.py` 删除 ≈L19 `tencent_api_language` 与 ≈L26 `tencent_sign` 导入、`_parse_tencent_credentials`、`_voice_format`、腾讯 / edge / 小米三组实现与常量（保留 `_wav_header`，其默认采样率不再引用小米常量）、`test_stt` / `test_tts` / `_missing_credentials` 中的三家分支；`transcribe_openai` / `synthesize_openai` 在 `row.base_url` 为空时抛 `ValueError("base_url is required for OpenAI-compatible voice")`。`manager.py` 删除 edge / tencent / mimo 分支，`media_type` 恒为 `"audio/mpeg"`。`src/octop/i18n/domains/voice.py` 删除 `tencent_api_language`、腾讯凭据分支与 `voice.tencent.{code}` 查表。`src/octop/api/routers/voice.py` 增加 `_SUPPORTED_VOICE_KINDS = frozenset({"openai"})`，创建、修改（传入 kind 时）与 `test-configuration` 校验 kind。
  - 改动：删除 `tests/unit/test_voice_formats.py`、`tests/unit/api/test_voice_mimo.py`；`tests/unit/i18n/test_voice.py` 删除 `test_tencent_secret_id_is_localized`、`test_tencent_api_language_header`；守卫清单追加 `edge_tts`。
  - 验证：`! rg -n "edge_tts|tencentcloudapi|xiaomimimo|tencent_sign" src/octop/infra/voice && uv run pytest tests/unit/test_voice_manager.py tests/unit/test_voice_probe.py tests/unit/test_voice_stt_probe.py tests/integration/test_voice_probe_http.py tests/unit/i18n -q`
  - _需求：6.1, 6.2, 6.3, 6.4_

- [ ] 16. 语音：前端可填写 OpenAI 兼容接入点（0.75 人日）
  - 改动：先新增 `dashboard/src/pages/Settings/Voice/index.test.tsx`：打开 OpenAI 配置抽屉，"API 接入点"为可编辑输入框；填入 `http://10.1.2.3:8000/v1` 与密钥后保存，`voiceApi` 的创建 / 更新桩收到的 `base_url` 等于填写值；不填接入点时保存不调用接口并提示。
  - 改动：`dashboard/src/pages/Settings/Voice/index.tsx` 删除腾讯 / edge / 小米的状态（`mimoEndpoint`、`mimoVoiceId`、`secretId`、`secretKey` 等）、请求体分支（≈L113-131）与表单（≈L405-500 中对应块）；OpenAI 表单的 `disabled` `Select`（≈L434-446）改为可编辑 `Input`（沿用 `voice.mimoEndpoint` 标签），请求体带 `base_url`，校验时缺失则提示 `voice.baseUrlRequired`。`dashboard/src/locales/intranet/{en,zh}.json` 增加 `voice.baseUrlRequired`（en："Enter the API endpoint of your intranet voice gateway"；zh："请填写行内语音网关的 API 接入点"）并改写 `voice.openaiHint`（en："OpenAI-compatible API; point it at your intranet voice gateway."；zh："OpenAI 兼容接口，可指向行内语音网关。"）；守卫清单追加 `xiaomimimo.com`。
  - 验证：`cd dashboard && npx tsc -b && npm run lint && npm run test -- src/pages/Settings/Voice && cd .. && uv run pytest tests/unit/test_saas_tokens_removed.py -q`
  - _需求：6.5, 6.2_

- [ ] 17. 媒体生成与联网搜索：后端删除与强制关闭（1 人日）
  - 改动：守卫清单追加 4 个路由（`GET /api/admin/media-generation`、`PUT /api/admin/media-generation`、`POST /api/admin/media-generation/test`、`POST /api/search/{provider_id}/test`）与域名 `ark.cn-beijing.volces.com`。先写用例：`tests/unit/agents/test_tool_catalog.py` 断言目录名集合与 7 个工具名不相交且含 `memory_search`，删除 ≈L90 的 `web_search_tools` 用例；在 `w1-02` 的 `tests/unit/agents/test_forced_tool_denylist.py` 增加 `_build_harness_config` 产物 `web_search_tools is False`、`media_generation is None`、`tools_disabled` 含 7 个工具名；`tests/unit/test_capabilities.py` 的强制集断言改为名字集合（含本 spec 的 7 个）；`tests/unit/test_env_file.py` 删除 ≈L14、≈L82-84；新增 `tests/integration/test_envs_api.py` 用例：`PUT /api/envs` 写入 `TAVILY_API_KEY` 后 `reload_all` 未被调用（monkeypatch 计数），`invalidate_mcp_tool_cache` 被调用。
  - 改动：删除 `src/octop/infra/agents/media_generation.py`、`src/octop/api/routers/media_generation.py`、`src/octop/api/routers/search.py`、`src/octop/infra/utils/search_probe.py`；`src/octop/api/app.py` 删除 ≈L168、≈L178 两处导入与 ≈L227、≈L235-239 两条 `_RouterMount`；`src/octop/api/openapi_meta.py` 删除 `search` tag。
  - 改动：`src/octop/infra/agents/manager.py` 删除 ≈L25-27 导入、`__init__`（≈L364）与 `replace_persistence`（≈L398）中的 `MediaGenerationSettingsStore` 构造、≈L486-487 属性、≈L1636-1660 `save_media_generation`、≈L2944 的 `media_generation=` 传参，并在同一构造调用中加一行 `web_search_tools=False,`。`src/octop/infra/capabilities.py::REMOVED_CAPABILITY_TOOLS` 追加 `tavily_search`、`brave_search`、`google_search`、`kimi_search`、`searchfree_search`、`generate_image`、`generate_video`。`src/octop/infra/agents/tool_catalog.py` 删除 `_WEB_SEARCH_TOOLS`、`_MEDIA_TOOLS`、≈L72-78 七个目录项与 `builtin_tool_available` 中两段判定。
  - 改动：`src/octop/infra/utils/env_file.py` 删除 `SEARCH_ENV_KEYS` 与 `search_env_changed`；`src/octop/api/routers/envs.py` 删除导入，`_after_env_sync` 只保留 `invalidate_mcp_tool_cache()`，PUT 路由 `description` 删去"搜索键触发重载"的说明。`tests/unit/api/test_acl_gate_coverage.py` 的 `GATED_FILES` 删除 `"routers/search.py"`（权限键本身在任务 21 删除）。删除 `tests/integration/test_media_generation_api.py`、`tests/unit/agents/test_media_generation_settings.py`、`tests/integration/test_search_api.py`、`tests/unit/utils/test_search_probe.py`。
  - 验证：`uv run pytest tests/unit/agents tests/unit/test_capabilities.py tests/unit/test_env_file.py tests/integration/test_envs_api.py tests/unit/api/test_acl_gate_coverage.py tests/unit/test_saas_tokens_removed.py tests/unit/api/test_saas_removed_routes.py -q && make typecheck`
  - _需求：7.1, 7.2, 7.3, 7.4, 9.1_

- [ ] 18. 媒体生成与联网搜索：前端删除（0.75 人日）
  - 改动：先在 `dashboard/src/pages/Settings/Models/` 新增 `resolveModelCategory` 的 vitest 用例（如函数未导出则先导出）：`"search"`、`"generation"` 回落到 `"chat"`。删除 `dashboard/src/pages/Settings/SearchConfig/`（含 `index.test.tsx`）、`dashboard/src/pages/Settings/MediaGeneration/`、`dashboard/src/api/modules/mediaGeneration.ts`；`dashboard/src/api/modules/provider.ts` 删除 `testSearch` 与 `TestSearchResponse`；`Settings/Models/index.tsx` 删除 ≈L45 / ≈L47 导入，`ModelCategory` 收窄为 `"chat" | "voice"`，`resolveModelCategory`、`canSearch`（≈L80）、≈L105 tab 白名单、`generation` 与 `search` 两个标签和渲染分支同步收窄；`dashboard/src/utils/permissions.ts` ≈L24 `modelsPage` 删除 `"search"`。
  - 验证：`test ! -e dashboard/src/pages/Settings/SearchConfig && test ! -e dashboard/src/pages/Settings/MediaGeneration && cd dashboard && npx tsc -b && npm run lint && npm run test -- src/pages/Settings`
  - _需求：7.5, 9.4_

- [ ] 19. 云验证码：后端只留滑块并删除 `tencent_sign.py`（1 人日）
  - 改动：先改写用例。`tests/unit/auth/test_captcha_providers.py` 改为断言 `list_providers() == ["slider"]`、5 个云 slug 的 `get_provider` 为 `None`、`parse_slug("turnstile")` 抛 `ValueError`；`test_captcha_verify.py` 只保留"滑块不要求 token、不发请求"类用例；`test_captcha_store.py` 增加"`captcha.settings` 的 `active` 为 `turnstile` 时 `load_effective` 回落滑块"；`test_captcha_env.py` 增加"`OCTOP_CAPTCHA_PROVIDER=turnstile` 且无 blob 时 `validate_boot` 抛 `ValueError`"。`tests/integration/test_captcha_api.py` 删除 turnstile 与腾讯的 siteverify 用例，保留滑块登录、管理端读写与无权限用例，并增加"写入 `active=turnstile` 的旧 blob 后登录走滑块、monkeypatch 的 `httpx.AsyncClient.post` 未被调用"；如文件名或模块路径变化，同步维护 `tests/support/auth_guards.py::REAL_AUTH_GUARD_MODULES`。
  - 改动：`src/octop/infra/auth/captcha/providers.py` 删除 `tencent_sign` 导入、`_form_call`、`_FormPostProvider`、`_RecaptchaV3Provider`、`_TencentProvider`、`_TURNSTILE`、`_HCAPTCHA`、`_RECAPTCHA`、`_RECAPTCHA_V3`、`_TENCENT` 与末尾类型检查变量，`_register_builtins` 只注册 `_SLIDER`，模块 docstring 改为"滑块为过渡态，终态见 w3-01"；`verify.py` 删除 `_TEST_URLS` 与 `set_test_siteverify_url`，请求地址直接用 `call.url`；`captcha/__init__.py` 删除 ≈L27 与 ≈L48 的再导出。删除 `src/octop/infra/utils/tencent_sign.py`。守卫清单追加 `tencentcloudapi.com`。
  - 验证：`test ! -e src/octop/infra/utils/tencent_sign.py && ! rg -n "set_test_siteverify_url|tencent_sign" src/octop tests && uv run pytest tests/unit/auth tests/integration/test_captcha_api.py tests/unit/cli/test_captcha_cmd.py tests/unit/api/test_auth_guard_exemptions.py tests/unit/test_saas_tokens_removed.py -q`
  - _需求：8.1, 8.2, 8.3, 8.5, 6.2_

- [ ] 20. 云验证码：前端不再加载外部脚本（0.5 人日）
  - 改动：先改写 `dashboard/src/pages/Login/CaptchaField.test.tsx`：删除云 provider 用例，保留滑块用例，并断言 `Object.keys(CAPTCHA_WIDGETS)` 等于 `["slider"]`。`dashboard/src/pages/Login/captchaAdapters.ts` 的 `CAPTCHA_WIDGETS` 只保留 `slider`；`CaptchaField.tsx`、`CaptchaSettings.tsx` 不改。守卫清单追加 `challenges.cloudflare.com`、`hcaptcha.com`、`google.com/recaptcha`、`captcha.qcloud.com`。
  - 验证：`! rg -n "https://" dashboard/src/pages/Login/captchaAdapters.ts && cd dashboard && npx tsc -b && npm run lint && npm run test -- src/pages/Login && cd .. && uv run pytest tests/unit/test_saas_tokens_removed.py -q`
  - _需求：8.4_

- [ ] 21. 存量数据清洗与删除权限键 `search`（同一提交）（1 人日）
  - [ ] 21.1 先写失败用例
    - 改动：新增 `tests/unit/db/test_fork_saas_cleanup.py`：在 `tmp_path` 的 SQLite 库上执行 `run_migrations` 后写入残留数据（含 `search` 的用户权限、`feishu` 与 `mqtt` 通道、`tencent-docs` 与 `weknora` 连接器、`tencent` 与 `openai` 语音供应商且 `active_stt_provider='tencent'`、三家 SSO 行带 `client_secret_enc`、5 个 `media_generation_*` 键、`captcha.settings`、`codex_oauth.pending.x`、`media_generation_credentials` 密钥），调用 `step_saas_decoupling_cleanup(conn, "sqlite")` 后逐条断言需求 10.1-10.3；连续执行两次结果相同；只有 `users` 表的残缺库执行不报错；`REMOVED_CONNECTOR_KINDS == catalog_intranet._FORK_REMOVED`；`REMOVED_CHANNEL_KINDS` 等于基线 harness `ChannelKind` 取值减去 `{"mqtt"}`（用字面量集合比较）。
    - 改动：新增 `tests/integration/test_saas_cleanup_migration.py`：通过 `OctopServer` 的真实库写入同样的残留，`v` 从 `_FORK_PY_STEPS` 反查，`set_fork_version(pool, v - 1)` 后调用 `run_fork_migrations`，断言清洗结果与 `_schema_version` 不变；对含 `search` 的老用户执行 `PATCH /api/users/{id}`（改 `display_name` 与 `permissions`）返回 200。追加一个用 `tests.support.postgresql.requires_postgresql` 标记的 PG 版本。
    - 验证：`uv run pytest tests/unit/db/test_fork_saas_cleanup.py tests/integration/test_saas_cleanup_migration.py -q`（此时应失败）
    - _需求：9.2, 9.3, 10.1, 10.2, 10.3, 10.4, 10.5_
  - [ ] 21.2 实现迁移并删除权限键
    - 改动：新增 `src/octop/infra/db/fork_saas_cleanup.py`（常量快照与 `step_saas_decoupling_cleanup`，复用 `infra/db/fork_steps.py::strip_permission_keys`，表存在性判断与其同一做法，只用 `?` 占位，不提交事务）；新增 `src/octop/infra/db/migrations/forkNNN_saas_decoupling_cleanup.sql` 与 `forkNNN_saas_decoupling_cleanup.pg.sql`（只含说明注释；合入 fork 主干时取下一个可用号）；`src/octop/infra/db/fork_migrate.py::_FORK_PY_STEPS[NNN] = step_saas_decoupling_cleanup`。
    - 改动：`src/octop/infra/users/permissions.py` 删除 ≈L144-152 `"search"` 条目；`tests/unit/users/test_permissions.py` ≈L72 改为 `assert "search" not in PERMISSIONS`。
    - 验证：`uv run pytest tests/unit/db tests/unit/users tests/integration/test_saas_cleanup_migration.py tests/unit/api/test_acl_gate_coverage.py -q && OCTOP_TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:15432/octop_test uv run pytest tests/integration/test_saas_cleanup_migration.py -q`
    - _需求：9.1, 9.2, 9.3, 10.1, 10.2, 10.3, 10.4, 10.5_

- [ ] 22. 出站拒绝的错误语义与断网冒烟（1 人日）
  - 改动：先写用例。新增 `tests/unit/api/test_intranet_exception_handlers.py`：最小 `FastAPI` 应用挂 `install_intranet_exception_handlers`，路由抛 `UnsafeOutboundUrl("cannot resolve hostname 'gw.intranet'")`，响应 400、`error.code == "OUTBOUND_URL_REJECTED"`、响应体不含 `gw.intranet`；`caplog` 有 WARNING。新增 `tests/integration/test_offline_boot.py`：monkeypatch `socket.getaddrinfo`，对非 IP 字面量主机抛 `socket.gaierror`，对字面量委托原函数；在 `env_fake_harness` 上走 `bootstrap_admin` → `POST /api/auth/login` → `POST /api/agents` → `tests.support.http.ws_chat_turn` → `POST /api/agents/{agent_id}/cron` → `POST /api/connectors/test-credentials`（`kind="dify"`，`mcp_url` 用主机名），逐步断言 `status_code < 500`；第二个用例创建 OpenAI 兼容语音供应商（`base_url="https://voice-gw.intranet.example/v1"`）并设为当前 STT，`POST /api/voice/stt` 返回 400 与 `OUTBOUND_URL_REJECTED`。
  - 改动：`src/octop/infra/errors.py` 在 `ErrorCode` 末尾追加 `OUTBOUND_URL_REJECTED = "OUTBOUND_URL_REJECTED"`，在 `_DEFAULT_STATUS` 末尾追加 `ErrorCode.OUTBOUND_URL_REJECTED: 400`；`src/octop/i18n/intranet/{en,zh}.json` 的 `errors` 与 `dashboard/src/locales/intranet/{en,zh}.json` 的 `apiErrors` 增加该码（en："The configured outbound address is not allowed or cannot be resolved."；zh："配置的出站地址不被允许或无法解析。"）。
  - 改动：新增 `src/octop/api/intranet_exception_handlers.py::install_intranet_exception_handlers`；`src/octop/api/app.py::build_app` 在 `_install_exception_handlers(app)` 之后加 1 行调用，导入按 ruff isort 顺序放置。
  - 验证：`uv run pytest tests/unit/api/test_intranet_exception_handlers.py tests/integration/test_offline_boot.py tests/unit/i18n tests/unit/api/test_exception_handlers.py -q`
  - _需求：11.1, 11.2, 11.3_

- [ ] 23. 依赖收敛与锁文件（0.25 人日）
  - 改动：`pyproject.toml` 删除 ≈L26 `lark-oapi>=1.7.3` 与 ≈L30 `edge-tts>=6.1`，保留 `orcakit-harness-agent[all]`、`harness-gateway`、`segno`；`dashboard/package.json` 删除 `qrcode.react`；执行 `make relock`（单独一个提交）。在 `tests/unit/test_saas_tokens_removed.py` 追加一个用例：用 `tomllib` 读取 `pyproject.toml` 的 `project.dependencies`，断言不含 `lark-oapi`、`edge-tts`，且仍含 `harness-gateway`、`segno`、`orcakit-harness-agent[all]` 前缀项；读取 `dashboard/package.json` 断言不含 `qrcode.react`。
  - 验证：`make relock && uv sync && uv run pytest tests/unit/test_saas_tokens_removed.py -q && cd dashboard && npm ci && npx tsc -b`
  - _需求：12.3, 2.3, 6.2_

- [ ] 24. fork 记录与 AGENTS.md（0.5 人日）
  - 改动：`CHANGELOG-intranet.md` 的 `[Unreleased]` 下，"移除"写七类能力与 28 个端点，"变更"写通道 / SSO 请求体枚举收窄、OpenAI 兼容语音必须配置 `base_url`、`PUT /api/envs` 不再触发重载，"安全"写数据清洗与 `OUTBOUND_URL_REJECTED`；另加"升级须知"：迁移会删除已删能力的通道 / 连接器 / 语音行并停用三家 SSO，升级前做系统备份，升级后手工删除 `~/.octop/codex_oauth.json`、`~/.octop/connector-cli/` 与 `~/.octop/env` 中的搜索 API 键。
  - 改动：`docs/api-intranet.md`：第 2 节列 28 个已物理删除的路由；第 3 节列 `channels` 的 `kind`、`/auth/oauth/*` 的 `kind`、语音供应商的 `kind` 收窄与 `PUT /api/envs` 行为变化；第 4 节列 JWT 豁免移除 `/api/auth/oauth/callback`、权限键 `search` 删除；第 5 节登记 `OUTBOUND_URL_REJECTED`（400，文案在两份 overlay）；第 6 节登记 `_FORK_REMOVED` 的 21 个 kind。
  - 改动：`AGENTS.md` ≈L115 删去 `bot setup (bot_creators/)`，≈L163 删去 `channel QR bind (WeCom/WeChat), Feishu bot-creator subprocess`，≈L275 的渠道语言提示改为"then `DEFAULT_LOCALE`"。
  - 验证：`! rg -n "bot_creators|channel QR bind|IM platforms default" AGENTS.md && rg -n "OUTBOUND_URL_REJECTED" docs/api-intranet.md && rg -n "w1-05-saas-decoupling" CHANGELOG-intranet.md`
  - _需求：12.5_

- [ ] 25. 收尾（0.5 人日）
  - 改动：删除本 spec 引入的孤儿符号（以 `ruff`、`mypy`、`eslint` 为准）；确认两条守卫清单与设计文档一致（28 个路由、全部域名）；确认未修改上游 i18n JSON 与上游文档正文。
  - 验证：`make all && cd dashboard && npx tsc -b && npm run lint && npm run test && cd .. && git diff --stat w1-05-base -- CHANGELOG.md docs/api.md docs/cli.md docs/configuration.md README.md README_CN.md src/octop/i18n/en.json src/octop/i18n/zh.json dashboard/src/locales/en.json dashboard/src/locales/zh.json && OCTOP_TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:15432/octop_test uv run pytest tests/integration/test_saas_cleanup_migration.py -q`（`git diff --stat` 输出应为空）
  - _需求：12.4, 12.6_
