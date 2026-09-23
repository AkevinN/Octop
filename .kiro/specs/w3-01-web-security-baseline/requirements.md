# 需求文档：Web 安全基线
> spec：`w3-01-web-security-baseline` ｜ 波次：Wave 3 ｜ 基线：`757fd12` ｜ 预估：27 人日
> 前置：w0-02-ci-gates, w0-03-test-auth-baseline, w0-04-fork-isolation-points, w1-02-capability-trim, w1-05-saas-decoupling, w2-01-offline-build, w2-02-supply-chain-compliance ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 引言

**结论：** 本 spec 给 Octop 的两个 HTTP 入口（`build_app` 主应用与 `infra/setup/tls/http_companion.py` 伴生应用）建立一套可在行内落地的 Web 安全基线：定死中间件栈顺序、收口唯一的可信客户端 IP、增加 per-server 全局限流、发送安全响应头与 CSP、让全部用户字节落盘入口经过限长 + 魔数 + 杀毒，并把验证码终态改成服务端出题、服务端判定的本地图形验证码。

**背景：** 全仓无安全响应头；`auth.py::_client_ip` 与 `invites.py::_client_id` 无条件信任 `X-Forwarded-For`，可绕过邀请码限流；JWT 豁免路径无限流，已有邀请限流器是模块级单例；8 处上传无限长读入内存且只看扩展名与声明类型，无杀毒；滑块验证码只在前端判定，服务端对它直接放行。

**范围内：** 中间件栈顺序契约（owner）；`api/common/client_ip.py`（owner）；per-server 限流器与限流中间件（owner）；安全响应头与 CSP（先 Report-Only）；伴生应用的安全头与 Host 头开放重定向修复；launch.py 三处 `uvicorn.Config` 的代理信任显式化；12 个上传入口（10 个 multipart + 2 个 base64 JSON）的限长、魔数、杀毒；inbound 白名单可执行类型收口；本地图形验证码（后端、CLI 文案、前端组件与设置页）。

**范围外：**
- 测试鉴权基线与验证码测试豁免机制归 `w0-03`，本 spec 只在其豁免夹具里追加限流开关，并把新用例登记进 `REAL_AUTH_GUARD_MODULES`。
- 云验证码 provider 删除归 `w1-05`（本 spec 假设只剩滑块）。
- Scalar 本地化归 `w2-01`（`api/intranet_docs.py::install_api_docs`）；内置字体的许可登记归 `w2-02` 的许可证清单流程。
- 审计日志落来源 IP、request_id 中间件归 `w3-02`，它消费本 spec 的 `client_ip()` 并占用中间件栈的预留槽位。
- 会话、令牌移出 URL、口令策略归 `w3-04`；剩余 2 条 WebSocket（`chat/ws.py`、`chat/notify_ws.py`）的连接限速作为书面残留风险，不在本 spec 实现。
- 技能市场远程拉取通道已由 `w1-03` 删除，不在本 spec 覆盖。
- 前端其余内网适配归 `w4-01`。

## 需求

### 需求 1：中间件栈顺序契约

**用户故事：** 作为后续加固 spec 的开发者，我希望中间件栈有一个唯一、可测的装配入口与顺序，以便新增中间件时不会因 Starlette `insert(0)` 语义放错层。

#### 验收标准
1. 当 `build_app` 完成装配时，主应用的请求链自外向内应当是：[w3-02 预留槽] → security_headers → setup_lockdown → rate_limit → jwt_auth → CORS（仅配置时）→ 路由，并由 `uv run pytest tests/unit/api/test_middleware_stack.py -q` 断言。
2. 如果同一个 app 上重复调用任一 `install(app, server)`（含 `setup_lockdown`），那么中间件数量应当不变。
3. 本 spec 新增的中间件模块应当始终带 `_INSTALL_ATTR` 幂等守卫，并把自身名字登记到顺序记录中。

### 需求 2：可信客户端 IP 与代理头

**用户故事：** 作为安全管理员，我希望应用只信任经可信代理白名单过滤后的来源地址、协议与主机名，以便伪造转发头不能绕过限流或篡改回调地址。

#### 验收标准
1. 当 app 外包 `ProxyHeadersMiddleware(trusted_hosts=["127.0.0.1"])` 且请求带 `X-Forwarded-For: 1.2.3.4` 时，`client_ip(request)` 应当返回 `1.2.3.4`。
2. 如果 peer 为 `None` 或非 IP 字面量（如 `testclient`），那么 `client_ip`、`trusted_peer` 应当不抛异常，且 `trusted_peer` 返回 `False`。
3. 如果 peer 不在 `trusted_proxies` 或 `X-Forwarded-Host` 不在 `trusted_hosts`，那么 `resolve_public_base` 应当回退到 `request.url` 的主机。
4. `rg -n -i 'x-forwarded' src/octop --glob '*.py'` 应当始终只命中 `src/octop/api/common/client_ip.py` 一个文件。
5. 当 `octop run` 构造 `uvicorn.Config` 时，三处调用都应当显式传入 `proxy_headers` 与 `forwarded_allow_ips`，取值来自 `OctopConfig.trusted_proxies`。

### 需求 3：per-server 全局限流

**用户故事：** 作为运维，我希望未认证洪泛在解析 JWT 与查库之前被切断，以便登录爆破与匿名接口滥用不会拖垮实例。

#### 验收标准
1. 当同一来源对 `POST /api/auth/login` 连续请求超过登录桶预算时，系统应当返回 429、错误码 `RATE_LIMITED`，并带 `Retry-After` 头。
2. 当两个不同的 `OctopServer` 实例各自处理请求时，它们的限流桶应当互不影响。
3. 如果 `rate_limit.enabled` 为 `False`，那么中间件应当直通且不计数。
4. 在测试进程中（未进入 `REAL_AUTH_GUARD_MODULES` 的模块），限流应当默认关闭，`make test` 应当全绿。
5. 邀请码 validate/redeem 的限流 key 应当始终来自 `client_ip()`，伪造 `X-Forwarded-For` 不能换桶。

### 需求 4：安全响应头与 CSP

**用户故事：** 作为等保测评方，我希望所有 HTTP 响应都带安全头且 CSP 不依赖任何外部主机，以便满足 Web 安全基线检查。

#### 验收标准
1. 当请求 `GET /api/health`、SPA 回退 `GET /`、ACME 挑战路径、无令牌访问 `/api/agents` 的 401、触发未处理异常的 500 时，每个响应都应当含 CSP（或 CSP-Report-Only）、`X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY`、`Referrer-Policy`、`Permissions-Policy`。
2. 如果 `tls.enabled` 为 `True` 或 `security_headers.hsts` 为 `True`，那么响应应当含 `Strict-Transport-Security`；两者都为 `False` 时应当不含。
3. 在 `security_headers.csp_mode` 为 `report-only`（默认）期间，系统应当发送 `Content-Security-Policy-Report-Only`，并由 `POST /api/security/csp-report` 以 204 接收报告并记 WARNING 日志。
4. CSP 取值应当始终只含 `'self'`、`data:`/`blob:` 等本地来源，不含任何 `https://` 外部主机；`dashboard/index.html` 应当不再含内联 `<script>` 块。

### 需求 5：伴生 HTTP 应用

**用户故事：** 作为安全管理员，我希望 80 端口的伴生应用同样带安全头且不能被 Host 头利用做开放重定向。

#### 验收标准
1. 当请求伴生应用的 ACME 挑战路径或任意路径得到 301 时，响应应当带与主应用相同的安全头。
2. 如果请求头 `Host: evil.com` 不在 `tls.domains ∪ trusted_hosts` 中，那么 301 的 `Location` 应当指向配置的第一个规范域名，而不是 `evil.com`。

### 需求 6：上传限长与魔数一致性

**用户故事：** 作为安全管理员，我希望所有上传入口都流式限长并校验文件真实类型，以便改扩展名的可执行文件与超大文件在落盘前被拒。

#### 验收标准
1. `rg -n 'await (file|audio|pkg_file|compare_pkg|upload)\.read\(\)' src/octop/api/routers` 应当始终无输出。
2. 当把 PE 头（`MZ`）以 `filename=report.pdf`、`content-type=application/pdf` 提交给 12 个入口中的任一个时，系统应当返回 400 `UPLOAD_CONTENT_MISMATCH`（参数化用例逐一列出 12 个入口）。
3. 如果无扩展名、无 content-type 的上传内容是可解码的 UTF-8 文本，那么聊天附件上传应当成功。
4. 当工作区归档或插件 ZIP 的条目数或解压后总大小超过上限时，系统应当拒绝且不写盘。

### 需求 7：杀毒钩子

**用户故事：** 作为行方安全部门，我希望上传内容在落盘前经过本地杀毒引擎，引擎不可用时默认拒收。

#### 验收标准
1. 当注入的扫描器返回 INFECTED 时，上传应当返回 403 `UPLOAD_VIRUS_DETECTED`。
2. 如果扫描器抛出连接错误且 `upload_scan.fail_closed` 为 `True`（默认），那么上传应当返回 503 `UPLOAD_SCAN_UNAVAILABLE`；插件上传在 `fail_closed=False` 时也应当返回 503。
3. 如果 `upload_scan.address` 不是回环地址、unix socket 或私网地址，那么 `OctopServer.start()` 应当抛错拒绝启动。

### 需求 8：可执行类型收口

**用户故事：** 作为安全管理员，我希望聊天附件白名单不含可执行类型。

#### 验收标准
1. 当上传 `a.exe` 或声明 `application/x-msdownload` 的附件时，系统应当拒绝。
2. `ALLOWED_INBOUND_MEDIA_TYPES` 应当始终不含 `application/x-msdownload`、`application/x-apple-diskimage`、`application/vnd.android.package-archive`。

### 需求 9：服务端本地图形验证码

**用户故事：** 作为安全管理员，我希望登录验证码由服务端出题并判定，以便脚本不能绕过验证码爆破口令。

#### 验收标准
1. 当未取题直接登录时，系统应当返回 `CAPTCHA_REQUIRED`；答案错误、同一 challenge 第二次使用、超过 TTL 时应当返回 `CAPTCHA_FAILED`；同一来源取题超过频率上限时应当返回 429 `RATE_LIMITED`。
2. 当初装未完成时，`GET /api/auth/captcha/challenge` 应当返回 503（setup_lockdown 不放行）。
3. 如果验证码设置 blob 损坏、密钥不可解密或 `active` 指向未注册 slug，那么系统应当降级到 `local-image` 且登录仍可完成，而不是放行或锁死。
4. 当管理员 `PUT /api/settings/captcha` 把 `active` 设为 `local-image`（不带 site_key/secret）时，系统应当保存成功。
5. 挑战答案应当始终只保存在服务端，`GET /api/auth/captcha/challenge` 的响应只含 `challenge_id`、`image_base64`、`expires_in`；历史值 `slider` 应当被解析为 `local-image`。
6. `uv run pytest tests/unit/auth tests/unit/cli/test_captcha_cmd.py tests/integration/test_captcha_api.py tests/integration/test_local_captcha.py -q` 应当全绿。

### 需求 10：前端验证码与文案

**用户故事：** 作为终端用户，我希望在登录页看到可刷新的图形验证码并在出错时看到本地化提示。

#### 验收标准
1. 当登录页加载且 provider 为 `local-image` 时，页面应当渲染验证码图片、输入框与刷新按钮，`getToken()` 返回非空的 `challenge_id:answer`。
2. 如果登录返回 `CAPTCHA_FAILED`，那么登录页应当自动重新取题。
3. `dashboard/src/pages/Login/SlideCaptcha.tsx` 与其测试应当被删除，`rg -n 'SlideCaptcha' dashboard/src` 无输出。
4. 新增的每个 `ErrorCode` 应当始终同时出现在枚举、`_DEFAULT_STATUS`、后端 overlay `errors.*` 与前端 overlay `apiErrors.*` 的 en/zh 中，`uv run pytest tests/unit/i18n -q` 全绿。
