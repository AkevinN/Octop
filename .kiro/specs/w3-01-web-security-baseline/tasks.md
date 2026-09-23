# 实施计划：Web 安全基线
> spec：`w3-01-web-security-baseline` ｜ 波次：Wave 3 ｜ 基线：`757fd12` ｜ 预估：27 人日
> 前置：w0-02-ci-gates, w0-03-test-auth-baseline, w0-04-fork-isolation-points, w1-02-capability-trim, w1-05-saas-decoupling, w2-01-offline-build, w2-02-supply-chain-compliance ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

每个顶层任务完成后可独立提交；提交前运行任务内的验证命令。

- [ ] 1. 确认前置 spec 已合入并记录基线（0.5 人日）
  - 改动：核对 w0-03 豁免夹具、w0-04 overlay、w1-02 删路由、w1-05 只剩滑块、w2-01 `api/intranet_docs.py` 均已合入；记录 `make test` 基线用时。
  - 验证：`test -d src/octop/i18n/intranet && test -f src/octop/api/intranet_docs.py && test ! -e src/octop/api/routers/terminal.py && rg -n 'REAL_AUTH_GUARD_MODULES' tests/conftest.py && make test`
  - _需求：1.1, 10.4_

- [ ] 2. 新增错误码与 overlay 文案（0.5 人日）
  - 改动：`src/octop/infra/errors.py` 的 `ErrorCode` 与 `_DEFAULT_STATUS` 末尾追加 `RATE_LIMITED: 429`、`UPLOAD_CONTENT_MISMATCH: 400`、`UPLOAD_VIRUS_DETECTED: 403`、`UPLOAD_SCAN_UNAVAILABLE: 503`；`src/octop/i18n/intranet/{en,zh}.json` 加 `errors.*`；`dashboard/src/locales/intranet/{en,zh}.json` 加 `apiErrors.*` 与 `login.imageCaptcha.{label,placeholder,refresh}`。不删任何上游键。
  - 验证：`uv run pytest tests/unit/i18n -q && uv run python -c "from octop.infra.errors import OctopError, ErrorCode as E; [OctopError(getattr(E, c)) for c in ('RATE_LIMITED','UPLOAD_CONTENT_MISMATCH','UPLOAD_VIRUS_DETECTED','UPLOAD_SCAN_UNAVAILABLE')]"`
  - _需求：10.4_

- [ ] 3. 配置五键（1 人日）
  - 改动：先在 `tests/unit/test_config.py` 写失败用例：文件与 env 两条路径都能设置 `trusted_proxies`、`trusted_hosts`、`security_headers`、`rate_limit`、`upload_scan`，且 `load_config` 返回值带上这些值。
  - 改动：`src/octop/config.py` 三触点：触点一新增 `SecurityHeadersConfig`、`RateLimitConfig`、`UploadScanConfig`（frozen，照 `TlsConfig`）与 `OctopConfig` 五个字段；触点二新增 `_parse_security_headers_section`、`_parse_rate_limit_section`、`_parse_upload_scan_section` 与 `OCTOP_TRUSTED_PROXIES`、`OCTOP_TRUSTED_HOSTS`、`OCTOP_CSP_MODE`、`OCTOP_HSTS`、`OCTOP_RATE_LIMIT_ENABLED`、`OCTOP_UPLOAD_SCAN_BACKEND`、`OCTOP_UPLOAD_SCAN_ADDRESS` 覆盖；触点三在 `return OctopConfig(...)` 逐字段挂上。
  - 验证：`uv run pytest tests/unit/test_config.py tests/unit/test_capabilities_config.py -q`
  - _需求：2.5, 3.3, 4.2, 7.2_

- [ ] 4. 中间件栈顺序契约（1 人日）
  - 改动：先写 `tests/unit/api/test_middleware_stack.py`：断言 `app.state.octop_middleware_order == ("security_headers", "setup_lockdown", "rate_limit", "jwt_auth", "cors")`（CORS 仅在配置时出现）；对同一 app 重复调用 `install_middleware_stack` 与各 `install`，`len(app.user_middleware)` 不变。
  - 改动：新增 `src/octop/api/middleware/stack.py::install_middleware_stack`；`src/octop/api/app.py::build_app` 用它替换 CORS 块、`install_jwt_auth`、`install_setup_lockdown` 三处调用；`src/octop/api/middleware/setup_lockdown.py::install` 补 `_INSTALL_ATTR` 守卫；`rate_limit`、`security_headers` 此时以空实现占位。
  - 验证：`uv run pytest tests/unit/api/test_middleware_stack.py tests/unit/api/test_jwt_auth_middleware.py tests/unit/api/test_exception_handlers.py -q`
  - _需求：1.1, 1.2, 1.3_

- [ ] 5. 唯一的可信 IP helper（1.5 人日）
  - 改动：先写 `tests/unit/api/test_client_ip.py`（peer 为 `None`、`"testclient"`、可信/不可信 CIDR；外包 `uvicorn.middleware.proxy_headers.ProxyHeadersMiddleware(trusted_hosts=["127.0.0.1"])` 发 `X-Forwarded-For: 1.2.3.4` 断言返回 `1.2.3.4`）；改写 `tests/unit/auth/test_public_base.py` 为可信/不可信两组（scope 显式加 `"client"`）；`tests/integration/test_auth_oidc.py` 的转发头用例改为配置 `trusted_proxies=["127.0.0.1"]`、`trusted_hosts` 并只断言 host 维度。
  - 改动：新增 `src/octop/api/common/client_ip.py`；`src/octop/api/common/public_base.py::resolve_public_base` 与 `sso_cookie.py::request_is_https` 删除读头分支改调 helper；删除 `api/routers/auth.py::_client_ip` 与 `api/routers/invites.py::_client_id`，调用点改为 `client_ip(request)`；`api/routers/setup.py` ≈L329 改调 helper；`build_app` 把信任配置放进 `app.state`。
  - 验证：`uv run pytest tests/unit/api/test_client_ip.py tests/unit/auth/test_public_base.py tests/integration/test_auth_oidc.py tests/integration/test_invites_api.py -q && test "$(rg -l -i 'x-forwarded' src/octop --glob '*.py')" = "src/octop/api/common/client_ip.py"`
  - _需求：2.1, 2.2, 2.3, 2.4, 3.5_

- [ ] 6. launch.py 代理信任显式化（0.5 人日）
  - 改动：先写 `tests/unit/test_launch_proxy_headers.py`：monkeypatch `uvicorn.Config` 记录参数，覆盖单端口与双端口两条分支，断言三处都带 `proxy_headers` 与 `forwarded_allow_ips`。
  - 改动：`src/octop/launch.py` 三处 `uvicorn.Config(`（≈L106、≈L117、≈L135）传参，≈L117 处注释说明它服务伴生应用。
  - 验证：`uv run pytest tests/unit/test_launch_proxy_headers.py -q`
  - _需求：2.5_

- [ ] 7. per-server 限流器与限流中间件（2.5 人日）
  - [ ] 7.1 限流器（1 人日）
    - 改动：先写 `tests/unit/api/test_rate_limit.py`（可注入时钟、窗口滑动、`retry_after`、两个 `OctopServer` 的桶互不影响）；新增 `src/octop/infra/security/__init__.py`、`rate_limit.py::SlidingWindowLimiter`；`src/octop/infra/server.py` 的 `OctopServer.__init__` 持有 `self.rate_limiter`。
    - 验证：`uv run pytest tests/unit/api/test_rate_limit.py -q`
    - _需求：3.2_
  - [ ] 7.2 中间件与测试默认（1.5 人日）
    - 改动：先写 `tests/integration/test_rate_limit_api.py`（登录第 N+1 次 429 + `Retry-After` + `RATE_LIMITED`；认证态桶；`enabled=False` 直通），登记进 `tests/conftest.py` 的 `REAL_AUTH_GUARD_MODULES`；在 `w0-03` 的根 conftest 豁免夹具中对未登记模块设置 `OCTOP_RATE_LIMIT_ENABLED=0`。
    - 改动：实现 `src/octop/api/middleware/rate_limit.py::install` 与 `bucket_for`，key 取 `client_ip()`，按 `login`/`captcha`/`invite`/`internal_mcp`/`anon`/`auth` 分桶。
    - 验证：`uv run pytest tests/integration/test_rate_limit_api.py -q && make test`
    - _需求：3.1, 3.3, 3.4_

- [ ] 8. 安全响应头与 CSP 报告端点（1.5 人日）
  - 改动：先写 `tests/unit/api/test_security_headers.py`：对 `/api/health`、`/`、`/.well-known/acme-challenge/x`、无令牌 `/api/agents` 的 401、触发 `_unhandled` 的 500 断言全套头；`tls.enabled`/`hsts` 真值表断言 HSTS；`csp_mode` 三态断言头名；CSP 值不含 `https://`；`POST /api/security/csp-report` 未登录返回 204。
  - 改动：实现 `src/octop/api/middleware/security_headers.py`（`install` + `apply_headers`）；新增 `src/octop/api/routers/csp_report.py` 并在 `api/app.py` 挂载；`src/octop/api/deps.py::_JWT_EXEMPT_EXACT` 加 `/api/security/csp-report`。
  - 验证：`uv run pytest tests/unit/api/test_security_headers.py tests/unit/api/test_openapi_meta.py tests/integration/test_dashboard_serve.py -q`
  - _需求：4.1, 4.2, 4.3_

- [ ] 9. dashboard 内联脚本抽离（1 人日）
  - 改动：`dashboard/index.html` 两段内联 `<script>`（≈L140、≈L223）移到 `dashboard/public/boot/` 下的独立文件，以 `<script src>` 同步加载，保持执行顺序；内联 `<style>` 保留。浏览器以 Report-Only 打开登录、聊天、设置页，违规报告为零。
  - 验证：`cd dashboard && npm run build && ! rg -n '<script>' index.html && cd .. && make build-frontend`
  - _需求：4.4_

- [ ] 10. 伴生 HTTP 应用（0.5 人日）
  - 改动：先写 `tests/unit/infra/setup/test_http_companion.py`：ACME 路径与 301 带全套安全头；`Host: evil.com` 的 301 `Location` 指向规范域名；无白名单时 400。
  - 改动：`src/octop/infra/setup/tls/http_companion.py::build_http_companion_app` 新增 `allowed_hosts`、`headers_cfg` 关键字参数并复用 `apply_headers`；`src/octop/launch.py` 传入 `cfg.tls.domains + cfg.trusted_hosts`。
  - 验证：`uv run pytest tests/unit/infra/setup/test_http_companion.py tests/unit/test_launch_proxy_headers.py -q`
  - _需求：5.1, 5.2_

- [ ] 11. 魔数识别与统一上传入口（1.5 人日）
  - 改动：先写 `tests/unit/infra/test_file_sniff.py`（PDF、ZIP/OOXML、OLE2、PNG/JPEG/GIF/WEBP/BMP/TIFF、GZIP、7z、RAR、ELF、PE、Mach-O、Class、UTF-8 文本启发式；`MZ` + `report.pdf` 判不一致）。
  - 改动：新增 `src/octop/infra/security/file_sniff.py`；`src/octop/api/common/upload_limit.py::read_upload_capped` 增加 `filename`、`declared_type`、`scanner`、`expect` 参数，新增 `check_upload_bytes`；`src/octop/api/routers/uploads.py::_resolve_media_type` 改为以魔数为准、声明不符即拒，octet-stream 走推断。
  - 验证：`uv run pytest tests/unit/infra/test_file_sniff.py tests/integration/test_upload_api.py -q`
  - _需求：6.2, 6.3_

- [ ] 12. 12 个入口接入（2.5 人日）
  - 改动：先写 `tests/integration/test_upload_content_check.py`，参数化 12 个入口（`uploads`、`knowledge_bases`、`workspace` 上传与归档导入、`agents` 头像、`plugins`、`backup`、`voice`、`memory_portable` 两个、`skills` 与 `skill_packages` 的 base64），`MZ` 内容伪装 PDF 均得 400 `UPLOAD_CONTENT_MISMATCH`。
  - 改动：`src/octop/api/routers/{workspace,voice,memory_portable,agents,plugins,backup}.py` 的 8 处 `await ….read()` 改为 `read_upload_capped`（按设计文档的期望类型与上限）；`knowledge_bases.py` 传 `filename`/`declared_type`；`skills.py` 与 `skill_packages.py` 解码后调 `check_upload_bytes` 并给 `content` 字段加 `Field(max_length=…)`。再修正声明类型与内容不符的既有夹具。
  - 验证：`uv run pytest tests/integration/test_upload_content_check.py tests/integration/test_plugin_upload.py tests/integration/test_knowledge_bases_api.py -q && ! rg -n 'await (file|audio|pkg_file|compare_pkg|upload)\.read\(\)' src/octop/api/routers && make test`
  - _需求：6.1, 6.2_

- [ ] 13. 归档解压上限（0.5 人日）
  - 改动：先写 `tests/unit/infra/test_archive_limits.py`：条目数超限、解压总量超限的 ZIP 被拒且目标目录为空。
  - 改动：`src/octop/infra/backup/workspace_archive.py::_iter_zip_entries` 与 `src/octop/infra/agents/plugins/manager.py`（≈L464 的 `zipfile.ZipFile` 前）按 `ZipInfo.file_size` 累加校验；路径穿越沿用 `_safe_zip_name`。
  - 验证：`uv run pytest tests/unit/infra/test_archive_limits.py tests/integration/test_plugin_upload.py -q`
  - _需求：6.4_

- [ ] 14. 杀毒钩子（2 人日）
  - 改动：先写 `tests/unit/infra/test_av.py`（clamd 桩、公网地址被拒），在 `test_upload_content_check.py` 追加 INFECTED → 403、连接错误 → 503、插件在 `fail_closed=False` 下仍 503 的用例。
  - 改动：新增 `src/octop/infra/security/av.py`（`Scanner`、`Verdict`、`ClamdScanner`、`build_scanner`）；`src/octop/infra/server.py::start` 构造 `self.upload_scanner` 并校验地址；12 个入口经 `read_upload_capped`/`check_upload_bytes` 传入。
  - 验证：`uv run pytest tests/unit/infra/test_av.py tests/integration/test_upload_content_check.py -q`
  - _需求：7.1, 7.2, 7.3_

- [ ] 15. inbound 可执行类型收口（0.5 人日）
  - 改动：先在 `tests/integration/test_upload_content_check.py` 追加 `a.exe` 与声明 `application/x-msdownload` 被拒、无扩展名 UTF-8 文本上传成功的用例。
  - 改动：`src/octop/infra/gateway/media/inbound_store.py` 删除 `INBOUND_EXTENSION_MEDIA_TYPES` 的 `.exe/.dmg/.apk` 与 `_INBOUND_MEDIA_TYPE_ALIASES` 的三条 PE 别名。
  - 验证：`uv run pytest tests/integration/test_upload_content_check.py tests/unit/gateway -q && uv run python -c "from octop.infra.gateway.media.inbound_store import ALLOWED_INBOUND_MEDIA_TYPES as A; assert 'application/x-msdownload' not in A"`
  - _需求：8.1, 8.2, 6.3_

- [ ] 16. 验证码后端：kind 判别式与 local-image provider（2.5 人日）
  - 改动：先改写 `tests/unit/auth/test_captcha_{providers,env,store,verify}.py` 与 `tests/unit/cli/test_captcha_cmd.py`：`parse_slug("slider") == "local-image"`；默认 slug 为 `local-image`；四条降级路径 `public_config` 返回 `{"provider": "local-image"}`；`save_settings` 以 `active="local-image"` 且无密钥保存成功；`ensure_captcha` 对本地 provider 缺 token 抛 `CAPTCHA_REQUIRED`。
  - 改动：`src/octop/infra/auth/captcha/providers.py`：Protocol 加 `kind`，删 `_SliderProvider`，新增 `_LocalImageProvider` 并在 `_register_builtins` 注册；`store.py`：引入 `_LOCAL_SLUG`，`_slider` 改名 `_local`，≈L43/≈L154/≈L178 改按 `kind` 判定，`save_settings` 对本地 provider 跳过密钥校验；`config.py`：`snapshot_env` 默认值与 `validate_boot` 两处判定改按 `kind`；`verify.py::ensure_captcha` 增加 `challenges` 关键字参数，本地 provider 走 `ChallengeStore.consume`；`src/octop/cli/commands/captcha.py` reset 文案改为 local-image。
  - 验证：`uv run pytest tests/unit/auth tests/unit/cli/test_captcha_cmd.py -q`
  - _需求：9.3, 9.4, 9.5_

- [ ] 17. 取题端点、挑战存储与字体打包（1.5 人日）
  - 改动：先写 `tests/integration/test_local_captcha.py`（未取题 → `CAPTCHA_REQUIRED`；错答、重放、超 TTL → `CAPTCHA_FAILED`；取题超频 → 429；初装前取题 → 503；响应只含三个字段）并登记进 `REAL_AUTH_GUARD_MODULES`；改写 `tests/integration/test_captcha_api.py` 覆盖 local-image 的管理端读写。
  - 改动：新增 `src/octop/infra/auth/captcha/local_image.py`（`ChallengeStore`、`render_png`）与 `assets/captcha.ttf`；`OctopServer.__init__` 持有 `captcha_challenges`；`src/octop/api/routers/auth.py` 新增 `GET /api/auth/captcha/challenge`，`login` 把 `server.captcha_challenges` 传给 `ensure_captcha`；`src/octop/api/deps.py::_JWT_EXEMPT_EXACT` 加该路径；`tests/unit/api/test_jwt_auth_middleware.py` 补一条豁免正例；`pyproject.toml` 的 `include` 加 `"src/octop/**/*.ttf"`。
  - 验证：`uv run pytest tests/integration/test_local_captcha.py tests/integration/test_captcha_api.py tests/unit/api/test_jwt_auth_middleware.py -q && uv build --wheel && unzip -l dist/octop-*.whl | rg -c 'captcha/assets/.*\.ttf'`
  - _需求：9.1, 9.2, 9.5, 9.6_

- [ ] 18. 前端图形验证码（2.5 人日）
  - 改动：先改写 `dashboard/src/pages/Login/CaptchaField.test.tsx` 的两条滑块用例为图形验证码用例（渲染 img + 输入框；`getToken()` 返回 `id:answer`；`CAPTCHA_FAILED` 后重新取题）。
  - 改动：新增 `dashboard/src/pages/Login/ImageCaptcha.tsx`，`dashboard/src/api/modules/auth.ts` 增加取题函数；`captchaAdapters.ts` 的 `CaptchaMode` 与 `CAPTCHA_WIDGETS` 以 `local-image` 替换 `slider`；`CaptchaField.tsx` 三处 `"slider"` 分支改为图形验证码；`Login/index.tsx` 两处兜底字面量改为 `local-image`，`resetCaptcha` 触发重新取题；`Settings/AdvancedSettings/CaptchaSettings.tsx` 四处 `"slider"` 改为 `local-image` 且本地验证码不弹强校验确认、不渲染密钥输入框；删除 `SlideCaptcha.tsx` 与 `SlideCaptcha.test.tsx`。
  - 验证：`cd dashboard && npx tsc -b && npm run lint && npm run test -- src/pages/Login && ! rg -n 'SlideCaptcha' src`
  - _需求：10.1, 10.2, 10.3_

- [ ] 19. 收尾（1 人日）
  - 改动：`CHANGELOG-intranet.md` 记录中间件栈、可信代理、限流、安全头、上传校验、本地验证码与新配置键；`docs/api-intranet.md` 记录 `GET /api/auth/captcha/challenge`、`POST /api/security/csp-report`、4 个新错误码、上传入口新拒绝语义与五个配置键；清理本 spec 引入的孤儿符号；`make build-frontend`。
  - 验证：`make all && cd dashboard && npx tsc -b && npm run lint && npm run test && cd .. && uv run pytest tests/unit/i18n -q`
  - _需求：9.6, 10.4_
