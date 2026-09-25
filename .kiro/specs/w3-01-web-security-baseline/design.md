# 设计文档：Web 安全基线
> spec：`w3-01-web-security-baseline` ｜ 波次：Wave 3 ｜ 基线：`757fd12` ｜ 预估：27 人日
> 前置：w0-02-ci-gates, w0-03-test-auth-baseline, w0-04-fork-isolation-points, w1-02-capability-trim, w1-05-saas-decoupling, w2-01-offline-build, w2-02-supply-chain-compliance ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 概述

策略逻辑放进新包 `infra/security/`（限流器、魔数、杀毒）与 `infra/auth/captcha/local_image.py`（验证码），`api/` 只做装配：一个中间件装配入口 `api/middleware/stack.py` 定死顺序，一个 `api/common/client_ip.py` 收口全部来源地址判断。应用层不再自己解析 `X-Forwarded-For/Proto`，而是依赖 uvicorn `ProxyHeadersMiddleware` 按 `forwarded_allow_ips` 过滤后的 `request.client` 与 `request.url.scheme`；只有 uvicorn 不处理的 `X-Forwarded-Host` 在应用层按 `trusted_peer + trusted_hosts` 双重约束。

## 现状

- 中间件：`src/octop/api/app.py::build_app` 先 `app.add_middleware(CORSMiddleware, …)`（仅 `cfg.cors_origins` 非空，≈L122-131），再 `install_jwt_auth`（≈L132）、`install_setup_lockdown`（≈L133）。Starlette 为 `insert(0)`，故 setup_lockdown 当前最外层。`api/middleware/jwt_auth.py` 有 `_INSTALL_ATTR`（≈L28，`install` ≈L32-35 守卫）；`api/middleware/setup_lockdown.py::install`（≈L21）无守卫，`_OPEN_PREFIXES`（≈L15）只放行 `/api/setup/`、`/api/health/`。
- 伴生应用：`infra/setup/tls/http_companion.py::build_http_companion_app(*, https_port)`（≈L21），`redirect_https` 在 ≈L25 直接取 `Host` 头拼 `https://{host}` 做 301，无安全头。`launch.py` 有三处 `uvicorn.Config(`（≈L106、≈L117 伴生应用、≈L135），均未显式传 `proxy_headers`/`forwarded_allow_ips`。
- 转发头：`api/routers/auth.py::_client_ip`（≈L83）与 `api/routers/invites.py::_client_id`（≈L32）读原始 `x-forwarded-for`；`invites.py` 在 ≈L120、≈L135 调 `check_invite_rate_limit(_client_id(request))`；`auth.py::login` 在 ≈L105 调 `ensure_captcha(effective, body.captcha_token, _client_ip(request))`。`api/common/public_base.py::resolve_public_base`（≈L15，读头 ≈L22-23）与 `api/common/sso_cookie.py::request_is_https`（≈L13，读头 ≈L14）无条件信任转发头。`api/routers/setup.py` ≈L329 已正确使用 `request.client.host`。
- 限流：`infra/users/invites.py::_PUBLIC_LIMITER = InviteRateLimiter()`（≈L50）是模块级单例；`infra/server.py` ≈L252 `self.wizard_tokens = WizardTokenStore(ttl_seconds=300)` 是 per-server 持有的先例。
- 错误码：`infra/errors.py` 共 99 个 `ErrorCode`，已有 `SETUP_RATE_LIMITED`（≈L31）、`INVITE_RATE_LIMITED`（≈L106）、`CAPTCHA_REQUIRED`（≈L110）、`CAPTCHA_FAILED`（≈L111）；`_DEFAULT_STATUS` 起于 ≈L115，
- 上传：`api/common/upload_limit.py::read_upload_capped`（≈L32）是唯一流式限长实现，仅 `uploads.py`（≈L72）与 `knowledge_bases.py`（≈L735）使用。8 处无限长读取：`workspace.py` ≈L317/≈L553、`voice.py` ≈L121、`memory_portable.py` ≈L220/≈L278、`agents.py` ≈L436、`plugins.py` ≈L172、`backup.py` ≈L423。base64 通道：`skills.py` ≈L742 与 `skill_packages.py` ≈L101 的 `base64.b64decode`。`uploads.py::_resolve_media_type`（≈L26）在客户端声明非 octet-stream 时直接采信（≈L28），终端回退 `application/octet-stream`（≈L39）。`infra/backup/workspace_archive.py::_safe_zip_name`（≈L22）已在 `_iter_zip_entries`（≈L77，≈L83 调用）防路径穿越，但无条目数与解压总量上限；`infra/agents/plugins/manager.py` ≈L464 直接 `zipfile.ZipFile`。
- inbound 白名单：`infra/gateway/media/inbound_store.py` 的 `INBOUND_EXTENSION_MEDIA_TYPES`（≈L28）含 `.exe`（≈L94）、`.dmg`（≈L95）、`.apk`（≈L96）；`.ps1/.bat/.cmd` 映射 `text/plain`（≈L114-116）；`_INBOUND_MEDIA_TYPE_ALIASES`（≈L174）含三条 PE 别名（≈L209-211）；`ALLOWED_INBOUND_MEDIA_TYPES`（≈L216）是由 `_OCTET_STREAM`（≈L214）与两张表的 values 推导出的 frozenset。
- 验证码：`infra/auth/captcha/verify.py::ensure_captcha`（≈L39）在 ≈L43 对 `not provider.requires_token` 直接返回；`store.py` 以 `not provider.requires_token` 判"是否本地"（≈L43、≈L154、≈L178），`"slider"` 字面量散在 `public_config`（≈L41）、`_slider`（≈L109）、`save_settings`（≈L290，≈L347 对 `requires_token` 的 active 强制要求 site_key+secret）；`config.py::snapshot_env` 默认 `"slider"`（≈L34），`validate_boot` 在 ≈L69、≈L72 各有一处硬编码判定。`providers.py` 有 `CaptchaProvider` Protocol（≈L59）、`_SliderProvider`（≈L105）、`_register_builtins`（≈L345）。`api/deps.py::_JWT_EXEMPT_EXACT`（≈L73）含 `/api/auth/captcha`（≈L76）但为精确匹配。
- 其它：`dashboard/index.html` 有内联 `<style>`（≈L37）与两段内联 `<script>`（≈L140、≈L223）；`pyproject.toml` 的 `[tool.hatch.build].include`（≈L102）是白名单且无 `*.ttf`；`pillow>=10.0` 是核心依赖（≈L41）。`w1-02` 删除 terminal/mobile/browser/desktop 后只剩 `chat/ws.py`、`chat/notify_ws.py` 两条 WebSocket。

## 方案

1. **中间件栈**：新增 `api/middleware/stack.py::install_middleware_stack(app, server)`，按"内→外"顺序调用 CORS、jwt_auth、rate_limit、setup_lockdown、security_headers 的 `install`；最外层预留给 `w3-02` 的 request_id。`build_app` 里原三处调用替换为这一行。`setup_lockdown.install` 补 `_INSTALL_ATTR`。
2. **可信 IP**：`client_ip()` 直接返回 `request.client.host`（None 时 `"unknown"`）；`request_scheme()` 返回 `request.url.scheme`；`forwarded_host()` 仅在 `trusted_peer()` 且主机在 `trusted_hosts` 时返回转发主机。`trusted_peer()` 用 `ipaddress` 匹配 CIDR，非 IP 字面量按字面比较、不抛异常。launch.py 三处 Config 传 `proxy_headers=bool(cfg.trusted_proxies)`、`forwarded_allow_ips=cfg.trusted_proxies or None`。
3. **限流**：`infra/security/rate_limit.py::SlidingWindowLimiter`（deque + `threading.Lock` + 可注入时钟），`OctopServer.__init__` 持有 `self.rate_limiter`。中间件按路径分桶：`login`、`captcha`、`invite`、`internal_mcp`、`anon`（其余 JWT 豁免路径）、`auth`（其余，key 取 IP；w3-04 引入会话后可改 user id）。WebSocket scope 不进 http 中间件。
4. **安全头**：`setdefault` 写入 `X-Content-Type-Options`、`X-Frame-Options: DENY`、`Referrer-Policy: same-origin`、`Permissions-Policy`、`Cross-Origin-Opener-Policy: same-origin`、CSP（`default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; worker-src 'self' blob:; frame-ancestors 'none'; report-uri /api/security/csp-report`）。`style-src 'unsafe-inline'` 是 antd v5 的已知例外，写进安全说明。首轮 `csp_mode=report-only`，下一迭代由行方决定转 `enforce`。`dashboard/index.html` 两段内联脚本抽到 `dashboard/public/boot/` 下的独立文件。
5. **伴生应用**：`build_http_companion_app` 增加关键字参数 `allowed_hosts`、`headers_cfg`；复用 `security_headers.apply_headers()` 纯函数；Host 不在白名单时重定向到首个规范域名（无配置时回 400）。
6. **上传**：`read_upload_capped` 扩展 `filename`、`declared_type`、`scanner`、`expect` 参数，一次完成限长 → 魔数一致性 → 杀毒；base64 通道调用同名的 `check_upload_bytes()`。归档类入口先流式限长再解压，解压前校验条目数与总大小。
7. **杀毒**：`infra/security/av.py` 定义 `Scanner` Protocol 与 `ClamdScanner`（INSTREAM），`IcapScanner` 待行方接口确定后补齐（见待确认）。`upload_scan.backend="off"` 时 `server.upload_scanner` 为 `None`，只做魔数；设置后 fail-closed。
8. **可执行类型**：删除扩展名表的 `.exe/.dmg/.apk` 与别名表三条 PE 别名；声明 octet-stream 时强制走 `detect_media_type`，推断不出才拒。
9. **本地图形验证码**：Protocol 增加 `kind: Literal["remote", "local"]`；删 `_SliderProvider`，新增 `_LocalImageProvider(slug="local-image", kind="local", requires_token=True, aliases=("slider",))`；store/config 中所有"是否本地"判定改用 `kind`，`"slider"` 字面量收成 `_LOCAL_SLUG`；三条降级分支降到 `local-image`；`save_settings` 对 `kind=="local"` 跳过 site_key/secret 校验。`captcha_token` 承载 `"<challenge_id>:<answer>"`，`LoginBody` 与 `ensure_captcha` 的位置参数不变（与 `w0-03` 的 `CAPTCHA_SEAMS` 契约兼容），新增关键字参数 `challenges`。`ChallengeStore` 挂在 `server.captcha_challenges`，一次性消费、TTL 120s、大小写不敏感比较、`hmac.compare_digest`。

## 组件与接口

| 文件 | 动作 | 说明 |
|---|---|---|
| `src/octop/api/middleware/stack.py` | 新增 | `install_middleware_stack(app: FastAPI, server: Any) -> None`；`MIDDLEWARE_ORDER: tuple[str, ...]` |
| `src/octop/api/middleware/security_headers.py` | 新增 | `install(app, server)`；`apply_headers(headers: MutableHeaders, cfg: SecurityHeadersConfig, *, tls: bool) -> None` |
| `src/octop/api/middleware/rate_limit.py` | 新增 | `install(app, server)`；`bucket_for(path: str) -> str` |
| `src/octop/api/middleware/setup_lockdown.py` | 修改 | `install` 加 `_INSTALL_ATTR` |
| `src/octop/api/common/client_ip.py` | 新增 | `client_ip(request) -> str`、`request_scheme(request) -> str`、`trusted_peer(request) -> bool`、`forwarded_host(request) -> str \| None` |
| `api/common/{public_base,sso_cookie}.py`、`api/routers/{auth,invites,setup}.py` | 修改 | 读头动作移入 helper；删 `_client_ip`、`_client_id`；`auth.py` 新增 `GET /api/auth/captcha/challenge`（`CaptchaChallengeResponse`） |
| `src/octop/api/routers/csp_report.py` | 新增 | `POST /api/security/csp-report`（204，JWT 豁免，走 `anon` 桶）；不与既有的 `api/routers/security.py`（安全策略管理 API）合并 |
| `src/octop/api/deps.py` | 修改 | `_JWT_EXEMPT_EXACT` 加 `/api/auth/captcha/challenge`、`/api/security/csp-report` |
| `src/octop/api/app.py` | 修改 | 调 `install_middleware_stack`；把 `trusted_proxies/trusted_hosts` 放进 `app.state`；挂载 `csp_report` 路由 |
| `src/octop/launch.py` | 修改 | 三处 `uvicorn.Config` 传代理参数；伴生应用传 `allowed_hosts`、`headers_cfg` |
| `src/octop/infra/setup/tls/http_companion.py` | 修改 | Host 白名单 + 安全头 |
| `src/octop/infra/security/{__init__,rate_limit,file_sniff,av}.py` | 新增 | `SlidingWindowLimiter.hit(bucket, key) -> float \| None`（返回 retry_after）；`detect_media_type(data: bytes) -> str \| None`、`assert_declared_matches_content(filename, declared_type, data) -> str`；`Scanner.scan(data, filename) -> Verdict`、`build_scanner(cfg) -> Scanner \| None` |
| `src/octop/infra/server.py` | 修改 | `__init__` 持有 `rate_limiter`、`captcha_challenges`；`start()` 构造 `upload_scanner` 并校验地址 |
| `src/octop/api/common/upload_limit.py` | 修改 | `read_upload_capped(..., filename=None, declared_type=None, scanner=None, expect=None)`；新增 `check_upload_bytes(...)` |
| 12 个入口所在的 10 个路由文件 | 修改 | 统一走上面两个入口；`plugins` 期望 ZIP，`backup` 期望 gzip，`agents` 上限 `MAX_AVATAR_BYTES` |
| `infra/backup/workspace_archive.py`、`infra/agents/plugins/manager.py`、`infra/gateway/media/inbound_store.py`、`infra/auth/captcha/{providers,store,config,verify}.py` | 修改 | 见方案 6、8、9 |
| `src/octop/infra/auth/captcha/local_image.py` | 新增 | `ChallengeStore.issue(client_ip) -> Challenge`、`ChallengeStore.consume(challenge_id, answer) -> bool`、`render_png(text: str) -> bytes` |
| `src/octop/infra/auth/captcha/assets/captcha.ttf` | 新增 | OFL/Apache 字体，许可登记交 w2-02 |
| `src/octop/cli/commands/captcha.py` | 修改 | reset 文案改为 local-image |
| `pyproject.toml` | 修改 | `include` 加 `"src/octop/**/*.ttf"` |
| `dashboard/src/pages/Login/ImageCaptcha.tsx`（新增）、`Login/{CaptchaField.tsx,captchaAdapters.ts,index.tsx}`、`Settings/AdvancedSettings/CaptchaSettings.tsx`、`api/modules/auth.ts`、`dashboard/index.html`、`public/boot/*.js`（新增） | 修改 | slider → local-image；删除 `SlideCaptcha.tsx` 及其测试；抽离内联脚本 |

## 数据模型

无。验证码设置沿用 `settings` 表的 `captcha.settings` 键，历史值 `slider` 由别名解析为 `local-image`，无需迁移。

## 配置

新增 5 个键，每个都动 `src/octop/config.py` 三触点（`OctopConfig` 字段、env 覆盖块、`return OctopConfig(...)`），由 `w1-02` 的第三触点单测兜底：

| 键 | 类型 / 默认 | env 覆盖 |
|---|---|---|
| `trusted_proxies` | `list[str]`，`[]` | `OCTOP_TRUSTED_PROXIES`（逗号分隔） |
| `trusted_hosts` | `list[str]`，`[]` | `OCTOP_TRUSTED_HOSTS` |
| `security_headers` | `SecurityHeadersConfig(csp_mode="report-only", hsts=False)` | `OCTOP_CSP_MODE`、`OCTOP_HSTS` |
| `rate_limit` | `RateLimitConfig(enabled=True, login_per_min=10, captcha_per_min=30, invite_per_min=20, internal_mcp_per_min=600, anon_per_min=120, auth_per_min=600)` | `OCTOP_RATE_LIMIT_ENABLED` |
| `upload_scan` | `UploadScanConfig(backend="off", address="", timeout_s=10.0, fail_closed=True)` | `OCTOP_UPLOAD_SCAN_BACKEND`、`OCTOP_UPLOAD_SCAN_ADDRESS` |

`docs/configuration.md` 不写 fork 内容，配置说明写进 `docs/api-intranet.md` 的配置附录。

## 错误处理

新增 4 个码，追加到 `ErrorCode` 与 `_DEFAULT_STATUS` 末尾：`RATE_LIMITED: 429`、`UPLOAD_CONTENT_MISMATCH: 400`、`UPLOAD_VIRUS_DETECTED: 403`、`UPLOAD_SCAN_UNAVAILABLE: 503`。验证码过期复用 `CAPTCHA_FAILED`（前端对两者都重新取题），未取题复用 `CAPTCHA_REQUIRED`。三个 429 码的适用面：`SETUP_RATE_LIMITED` 仅初装口令校验，`INVITE_RATE_LIMITED` 仅邀请码，`RATE_LIMITED` 为全局中间件与取题。文案写进 `src/octop/i18n/intranet/{en,zh}.json` 的 `errors.*` 与 `dashboard/src/locales/intranet/{en,zh}.json` 的 `apiErrors.*`；前端新增 `login.imageCaptcha.*` 也写进前端 overlay。不删 `login.slideHint` 等旧键。限流中间件直返 `JSONResponse(OctopError(RATE_LIMITED).to_envelope(locale=…), 429, headers={"Retry-After": …})`。

## 安全考虑

- 信任边界唯一：`forwarded_allow_ips` 与 `trusted_proxies` 同源，应用层不重复实现 XFF 解析，避免两层分叉。行内 NAT 下按 IP 限流会误伤，默认值偏宽，认证面待 w3-04 改 user id。
- 验证码降级到 `local-image` 而不是放行，也不是拒绝全部登录；`octop captcha reset` 仍是离线逃生口。挑战表设容量上限防内存膨胀。
- 残留风险：2 条 WebSocket 不受 http 中间件覆盖；CSP 实效需浏览器人工验收。
- 魔数校验不可配置关闭；杀毒 fail-closed 默认开；插件入口无视 `fail_closed=False`。

## 测试策略

- 单测：`uv run pytest tests/unit/api/test_middleware_stack.py tests/unit/api/test_security_headers.py tests/unit/api/test_client_ip.py tests/unit/api/test_rate_limit.py tests/unit/infra/test_file_sniff.py tests/unit/infra/test_av.py tests/unit/infra/setup/test_http_companion.py tests/unit/test_launch_proxy_headers.py tests/unit/auth -q`
- 集成：`uv run pytest tests/integration/test_rate_limit_api.py tests/integration/test_upload_content_check.py tests/integration/test_local_captcha.py tests/integration/test_captcha_api.py tests/integration/test_auth_oidc.py -q`
- PG：不改表结构，设置读写回归用 `OCTOP_TEST_DATABASE_URL=… uv run pytest tests/integration/test_local_captcha.py -q`。
- 测试默认值：在 `w0-03` 的根 `tests/conftest.py` 豁免夹具中追加 `OCTOP_RATE_LIMIT_ENABLED=0`，登记在 `REAL_AUTH_GUARD_MODULES` 中的模块不设；本 spec 的 `test_rate_limit_api.py`、`test_local_captcha.py` 登记进去。由于用环境变量，7 处直接调 `build_app` 的测试同样覆盖。`upload_scan` 默认 `off`，杀毒用例用 monkeypatch 注入 stub。
- 前端：`cd dashboard && npx tsc -b && npm run lint && npm run test -- src/pages/Login`（vitest 在 CI 的执行由 `w0-02` 保证）。
- 打包：`uv build --wheel && unzip -l dist/octop-*.whl | rg -c 'captcha/assets/.*\.ttf'`（期望 ≥1）。

## 与其他 spec 的交接

- 依赖 `w0-03`：`CAPTCHA_SEAMS`、`REAL_AUTH_GUARD_MODULES`、根 conftest 豁免夹具；本 spec 保持 `octop.api.routers.auth.ensure_captcha` 名字与位置参数不变。
- 依赖 `w0-04`：i18n overlay、`CHANGELOG-intranet.md`、`docs/api-intranet.md`。依赖 `w1-02`：配置第三触点单测、WebSocket 路由已删。依赖 `w1-05`：云验证码已删，只剩滑块。依赖 `w1-03`：技能市场远程拉取已删。
- 交给 `w2-01`（已合入）：Scalar 本地化由其 `api/intranet_docs.py` 完成，本 spec 的 CSP 只需覆盖 `/api-docs-assets/scalar.js` 同源加载，不再改 `get_scalar_api_reference`。
- 交给 `w2-02`：内置字体 `captcha.ttf` 的许可登记与 SBOM 条目。
- 交给 `w3-02`：`client_ip()` 作为审计来源 IP 的唯一来源；中间件栈最外层预留给 request_id，只需在 `stack.py` 追加一行；audit_log 加列由 w3-02 的 fork 迁移完成。
- 交给 `w3-04`：限流 `auth` 桶的 key 可在会话表落地后改为 user id；`/api/auth/captcha/challenge` 属登录模式的一部分，w3-04 不再另建验证码。
- 交给 `w4-02`：部署模板中 `trusted_proxies`、`upload_scan`、`csp_mode` 的生产取值与巡检。
- 看似相关但不归本 spec：Scalar 本地化（w2-01）、audit_log 加 IP 列（w3-02）、AGENTS.md 修订（w0-04）、`docs/api.md`（不写 fork 内容）。本 spec 不删除 `auth.py`、`invites.py`、`deps.py` 文件，只删其中的函数。

## 风险与回滚

- 魔数校验可能误拒既有测试夹具里的伪造文件（如把 `b"hello"` 声明为 png）：任务 9 先跑全量找出并修正夹具。
- CSP 抽离内联脚本可能导致首屏主题闪烁：首轮 Report-Only，回滚只需把 `csp_mode` 设为 `off`。
- 限流误伤：`OCTOP_RATE_LIMIT_ENABLED=0` 即可关闭。杀毒不可用：`backend=off` 回退为只做魔数。

## 待行方确认

- D11：验证码终态为服务端校验的本地图形验证码（本 spec 按此实现）；字符型是否满足行方基线、是否需算术题或对接行方验证码中台，若需对接则改走 `kind="remote"` 的新 provider。
- D4：部署形态与反向代理拓扑决定 `trusted_proxies` 取值、TLS 由谁终结、是否由 Octop 发 HSTS，以及伴生应用是否在线。
- 非 D 项：杀毒接口形态（clamd / ICAP / 行方 HTTP）与超时预算；限流预算与 NAT 出口规模；CSP 转 enforce 的时间点与 `style-src 'unsafe-inline'` 例外的书面认可；剩余 2 条 WebSocket 是否接受为残留风险；内置字体的法务审批。
