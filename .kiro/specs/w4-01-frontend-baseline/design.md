# 设计文档：前端内网适配

> spec：`w4-01-frontend-baseline` ｜ 波次：Wave 4 ｜ 基线：`757fd12` ｜ 预估：13.5 人日
> 前置：`w0-02-ci-gates`、`w0-04-fork-isolation-points`、`w1-03-online-fetch-trim`、`w1-04-content-trim`、`w1-05-saas-decoupling`、`w2-01-offline-build`、`w3-01-web-security-baseline` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 概述

五件事，全部以"新增收口模块 + 既有文件只改一行调用"的方式落地，压低跟随上游的冲突面：

1. 新增 `dashboard/src/utils/basePath.ts`，提供 `BASE_PATH`、`withBase`、`stripBase`、`isSameOriginMediaUrl`。所有子路径与同源判断都经过它。
2. PWA 整体删除，后端让 `sw.js` / `manifest.json` 返回 404。
3. Markdown 与工具媒体两条通路接入 `isSameOriginMediaUrl`。
4. 语言固定在 `localePrefs.ts` 与 `locale.ts` 两个咽喉点实现，调用点不动。
5. 品牌：文案走 `w0-04` 的 intranet overlay；视觉资产与标题由新增的 Vite 插件在构建期覆盖；`dashboard/brand/` 缺席时插件为空操作。

后端只有一处改动（退役 PWA 文件 404），不新增配置键、ErrorCode、迁移。

## 现状

以下事实均在仓库中核实（行号基于基线，仅作提示）。

**子路径**

- `dashboard/vite.config.ts` 的 `defineConfig` 返回对象没有 `base` 键；`BASE_URL` 是 `define` 注入的 **API 源站地址**（≈L58 `const apiBaseUrl = env.BASE_URL ?? ""`，≈L168 `BASE_URL: JSON.stringify(apiBaseUrl)`），不是 Vite 的 `import.meta.env.BASE_URL`。
- `dashboard/src/api/config.ts`：≈L1 `declare const BASE_URL: string`；`getApiUrl`（≈L8）与 `getWsUrl`（≈L22）的前缀写死为 `"/api"`。
- `dashboard/src/App.tsx` ≈L165 `<BrowserRouter useTransitions={false}>` 无 `basename`。
- 绕过 Router 的硬跳转：`api/request.ts` 的 `handleSetupRequired`（≈L77，≈L92 `window.location.replace("/setup")`，≈L82 守卫读 `window.location.pathname`）与 `handleUnauthorized`（≈L249，≈L266 `replace("/login")`，≈L251 守卫）；`components/ErrorBoundary/index.tsx` 的 `handleHome`（≈L59 `"/chat"`）；`pages/Experts/components/CreateFromExpertDrawer.tsx` ≈L466 `<a href="/admin/models">`；`layouts/Sidebar.tsx` ≈L429、≈L444 用原始 `window.location.pathname` 判断当前页。
- 回跳源头：`pages/Login/index.tsx` ≈L173 `authApi.startOauth(kind, "/chat")`、≈L155 兜底 `"/chat"`；`components/AvatarDropdown.tsx` ≈L214 `startOauthBind(kind, …)`；`pages/Login/OidcComplete.tsx` 的 `DEFAULT_REDIRECT`（≈L13）与 `safeRedirect`（≈L16）；`api/modules/connectors.ts` 的 `oauthStart` / `oauthStartCatalog`（≈L251、≈L261）接受可选 `redirectAfter`，现有调用方都不传，后端 `api/routers/connectors.py` ≈L1350 兜底为 `"/connectors"`。
- 后端 SSO 回跳 `infra/auth/sso/service.py` ≈L339 `f"{frontend}/login/oidc/complete#…"`，`frontend` 来自 `_frontend_base`（≈L378），优先取 SSO 行的 `dashboard_origin`，否则取 `public_base`。`infra/auth/sso/redirect_after.py` 的 `sanitize_redirect_after` 接受任意 `/` 开头的站内路径，因此前端传入 `/octop/chat` 可原样回传。
- 根绝对资源：`layouts/Header.tsx` ≈L24 `mobileLogoSrc`；`layouts/Sidebar.tsx` ≈L398 `wordmarkSrc`、≈L460 `pwa-192.png`；`assets/mascot.ts` ≈L5 `OCTOP_EMPTY_MASCOT_SRC`；`pages/Chat/components/WelcomeScreen.tsx` ≈L8-9 `MASCOT_PEEK` / `MASCOT_TYPE`；`dashboard/index.html` ≈L5 `/favico.svg`、≈L6 `/apple-touch-icon.png`、≈L31 `/manifest.json`、≈L214 `/logo.svg`。
- 后端 `infra/agents/experts/catalog.py` ≈L38 `_BUILTIN_AVATAR_URL_TEMPLATE = "/experts/avatars/{expert_id}.svg"`，≈L414 按该前缀判断；前端 `pages/Experts/components/iconForName.tsx` ≈L150 `url.includes("/experts/avatars/")`。
- 反代剥前缀时后端看到的仍是 `assets/…`，`api/app.py` 的 `is_dashboard_asset_path`（≈L55）、`dashboard_cache_control`（≈L36）、`spa_fallback`（≈L293）无需改。

**PWA**

- `vite.config.ts` ≈L4 导入、≈L174 调用 `VitePWA`；运行时缓存含 `html-shell`（≈L220，24 小时）、`static-chunks`（≈L235，30 天）、`api-readonly`（≈L254-259，`/api/(chats|agent/files|agent/memory)`，5 分钟）。≈L1 与 ≈L11 的 `webcrypto` 垫片只为 `vite-plugin-pwa` 的依赖链存在。
- `dashboard/package.json`：`vite-plugin-pwa`（≈L83），`overrides` 中 `serialize-javascript`（≈L55）、`@rollup/plugin-terser`（≈L56）。
- 文件：`src/sw-register.ts`、`src/sw-register.test.ts`、`src/pwa.ts`、`src/pwa-prompt.ts`、`src/components/PwaUpdatePrompt/`、`src/components/PwaInstallPrompt/`（含 `index.test.tsx`）、`public/manifest.json`、`public/offline.html`。
- 挂载点：`main.tsx` ≈L4 `import "./pwa-prompt"`、≈L78 `registerSW`；`layouts/MainLayout/index.tsx` ≈L10、≈L11、≈L290；`layouts/Header.tsx` ≈L3、≈L105；`pages/Chat/index.tsx` ≈L91、≈L1203。`/pwa-debug` 路由（`routes/index.tsx` ≈L33、≈L284）已由 `w1-04` 删除。
- `index.html` ≈L169-170 有 Service Worker 自卸载逻辑（`w3-01` 合入后位于 `dashboard/public/boot/` 下的启动脚本）。
- `api/app.py` ≈L33 `_NO_CACHE_DASHBOARD_NAMES = {"sw.js", "manifest.json", "index.html"}`；`tests/unit/api/test_dashboard_cache.py` ≈L11-12 断言这两个名字为 `no-cache`。文件删除后，未知路径会落到 `spa_fallback` 返回 `index.html`，旧 Service Worker 的更新检查拿到 200 HTML 而不是 404。

**同源过滤**

- `components/Markdown/index.tsx` 的 `resolveImageSrc`（≈L127）对 `http(s)`、`data:`、`/api/`（≈L133）原样返回；工作区转换返回根绝对 `/api/workspace/media?path=…`（≈L152）；`MarkdownImage`（≈L159）在 `src` 为空时渲染 `[alt]` 占位；`components={…}` 在 ≈L299。
- `utils/toolMediaBlocks.ts`：`isFileMediaUrl`（≈L18）、`needsAuthBlobFetch`（≈L28，≈L32 等值 `"/api/workspace/media"`）、`agentMediaPreviewUrl`（≈L40，≈L49 根绝对 `/api/agents/`），另有 ≈L216、≈L316、≈L355、≈L374 的 `/api/` 前缀判断。
- 消费方（均 import `toolMediaBlocks`）：`pages/Chat/components/{ToolMediaStrip,ChatMediaPlayer,MessageFileCard}.tsx`、`utils/collectTurnToolMedia.ts`、`pages/Chat/hooks/useChat.ts`（≈L155-156、≈L175 的 `/api/` 前缀判断）、`hooks/useAuthImageSrc.ts`、`plugins/toolRenderers/builtin/DefaultToolRenderer.tsx`。`ToolMediaStrip.tsx` ≈L56、≈L63 以 `/api/` 前缀剥离后再 `getApiUrl`。

**语言**

- `utils/localePrefs.ts`：`detectBrowserLocale`（≈L6）、`resolveInitialLocale`（≈L51，`stored ?? detectBrowserLocale()`）、`syncDocumentLang`（≈L55）。
- `utils/locale.ts`：`applyUserLocale`（≈L22）、`applyGuestLocale`（≈L36）。调用点：`components/AuthGuard.tsx` ≈L65、`pages/Login/index.tsx` ≈L205、`pages/Login/OidcComplete.tsx` ≈L80、`pages/Invite/index.tsx` ≈L122、`pages/Setup/steps/FinishStep.tsx` ≈L61。
- 切换入口：`AvatarDropdown.tsx` ≈L563 的 `Segmented`（`onChange` → ≈L169 `handleLocaleChange` → ≈L171 `setLocale`）；`pages/Setup/index.tsx` ≈L186-187；`pages/Invite/index.tsx` ≈L84-85。孤儿文件：`components/LanguageSwitcher.tsx`、`pages/Settings/Language/index.tsx`。
- `i18n.ts` 的 `initI18n`（≈L83）：`fallbackLng` 为另一语言（≈L95），`supportedLngs: ["zh", "en"]`（≈L96）。`api/request.ts` ≈L186、≈L227 按 `i18n.language` 发 `Accept-Language`。
- `index.html` ≈L2 `lang="en"`，≈L220 `Loading…`，≈L229 按 `navigator.language` 选启动文案。
- 后端 `api/routers/preferences.py` 已有 `locale` 偏好读写，`infra/utils/locale.py` 的解析顺序为"存量偏好优先"。前端 `api/modules/preferences.ts` 有 `setLocale`。

**品牌**

- `Octop` 出现次数：`dashboard/src/locales/zh.json` 63 行、`en.json` 54 行；`src/octop/i18n/zh.json` 8 行、`en.json` 9 行；`index.html` 2 行（≈L29、≈L32 `<title>`）。
- `tests/unit/i18n/test_skills.py` ≈L16、≈L20 断言 `"Octop 配置助手"`，≈L34 断言 `"Octop Assistant"`。
- 硬编码 `alt="Octop"`：`Login/index.tsx` ≈L249、`Setup/index.tsx` ≈L232、`Sidebar.tsx` ≈L461。
- `dashboard/public/` 品牌资产：`logo.svg`、`logo_name.png`、`logo_name_dark.png`、`favico.svg`、`apple-touch-icon.png`、`pwa-192.png`（侧栏仍在用）、`pwa-512.png`、`octop-mascot-empty.png`、`octop-mascot-peek.webp`、`octop-mascot-type.webp`、`octop-mascot-tasks.png`。
- `w0-04` 提供 `dashboard/src/i18nIntranet.ts::applyIntranetOverlay(locale)` 与 `dashboard/src/locales/intranet/{en,zh}.json`、后端 `src/octop/i18n/intranet/{en,zh}.json`，三方相等门禁读合并后的 bundle。

## 方案

**1. 部署拓扑固定为"反向代理剥前缀"。** 网关把 `/octop/*` 转发为后端的 `/*`。于是后端路由、静态资源判断、`spa_fallback` 全部不变；子路径只存在于浏览器侧。前端构建参数 `VITE_BASE_PATH` 决定 Vite `base` 与 Router `basename`，不引入后端配置键。后端生成的前端地址分两类处理：SSO 回跳由管理员把 `dashboard_origin` 填成含子路径的地址（如 `https://portal.bank/octop`），`redirect_after` 由前端显式传入带前缀的值；内置专家头像的根绝对 URL 由前端 `withBase` 补前缀，后端 `catalog.py` 不动。

**2. `define` 的 `BASE_URL` 不改名。** 改名会同时改 `vite.config.ts` 与 `api/config.ts` 两个上游文件的多处；只在 `config.ts` 加一行注释说明它是 API 源站，并由 `basePath.ts` 统一读取 `import.meta.env.BASE_URL`。API 前缀变为 `` `${BASE_URL}${BASE_PATH}api${path}` ``，`BASE_PATH` 恒以 `/` 结尾。

**3. 同源判定只有一个实现。** `isSameOriginMediaUrl(url)`：`blob:` 放行；`data:` 仅 `data:image/*` 放行；其余用 `new URL(url, location.href)` 解析，协议为 `http(s)` 且 `origin === location.origin` 才放行；解析失败一律拒绝。Markdown 与工具媒体、远程图标都调用它。外部超链接不自动发请求，本 spec 不处理。

**4. PWA 退役分三步：** 删前端代码与构建插件；启动脚本中的自卸载逻辑保留一个发布周期；后端对 `sw.js`、`manifest.json` 返回 404。浏览器在 Service Worker 更新检查拿到 404 时会注销该 Worker，这是自卸载脚本之外的第二道保险。

**5. 语言在咽喉点固定。** `resolveInitialLocale` 恒返回 `"zh"`；`applyUserLocale` / `applyGuestLocale` 保留签名、忽略入参恒应用 `"zh"`，五个调用点不改。`AuthGuard` 在拿到 `user.locale !== "zh"` 时调用一次 `preferencesApi.setLocale("zh")`，把后端存量偏好收敛为中文，从而 IM 回复与 API 错误信封也是中文，无需改后端解析顺序。`fallbackLng` 保留 `"en"`，避免 zh 缺键时露裸 key（残留风险见下）。

**6. 品牌文案走 overlay，不改上游 JSON。** 前后端 overlay 各自写入含 `Octop` 的键的品牌版本（值为行方品牌名），`OctopBot` 不覆盖。新增一条 pytest 门禁读合并后的 bundle，任何字符串值含 `Octop`（白名单除外）即失败——上游新增带品牌的键时同步会变红，提醒补 overlay。TSX 里 `t(key, "…Octop…")` 形式的 inline 兜底文案只在键缺失时显示，不逐个改；三处 `alt` 与首屏标题改为品牌常量。

**7. 视觉资产走构建插件。** 新增 `dashboard/scripts/brandPlugin.ts`：读取 `dashboard/brand/brand.json`；`config` 钩子注入 `__BRAND_NAME__`；`transformIndexHtml` 替换 `%BRAND_NAME%`；`closeBundle` 把 `dashboard/brand/public/` 下与产物同名的文件覆盖进 `outDir`。`dashboard/brand/` 不存在时插件回落到上游名称"Octop"且不复制，保证上游构建与 CI 不受影响。文件名不改（不去 `octop-` 前缀），避免改动引用点。

## 组件与接口

| 文件 | 动作 | 说明 |
|---|---|---|
| `dashboard/src/utils/basePath.ts` | 新增 | 见下方签名 |
| `dashboard/src/utils/basePath.test.ts` | 新增 | `withBase`/`stripBase`/`isSameOriginMediaUrl` 用例 |
| `dashboard/src/brand.ts` | 新增 | `export const BRAND_NAME: string = __BRAND_NAME__` |
| `dashboard/scripts/brandPlugin.ts` | 新增 | Vite 插件 `brandPlugin(): Plugin` |
| `dashboard/brand/brand.json`、`dashboard/brand/public/` | 新增 | 行方品牌名与素材；素材到位前放占位 |
| `dashboard/vite.config.ts` | 修改 | 加 `base: env.VITE_BASE_PATH \|\| "/"`、`brandPlugin()`；删 `VitePWA` 与 `webcrypto` 垫片 |
| `dashboard/package.json` | 修改 | 删 `vite-plugin-pwa` 与两条 `overrides`；`make relock` 重生成锁文件 |
| `dashboard/index.html` | 修改 | 资源路径改 `%BASE_URL%`；删 PWA meta 与 manifest link；`lang="zh-CN"`；标题用 `%BRAND_NAME%` |
| `dashboard/public/boot/`（`w3-01` 新增的启动脚本） | 修改 | 启动文案固定中文 |
| `dashboard/src/api/config.ts` | 修改 | 前缀改 `` `${BASE_PATH}api` ``，加注释 |
| `dashboard/src/App.tsx` | 修改 | `basename={ROUTER_BASENAME}` |
| `dashboard/src/api/request.ts`、`components/ErrorBoundary/index.tsx`、`layouts/Sidebar.tsx`、`pages/Experts/components/CreateFromExpertDrawer.tsx` | 修改 | 硬跳转与守卫经 `withBase`/`stripBase`；抽屉链接改 `<Link>` |
| `pages/Login/index.tsx`、`pages/Login/OidcComplete.tsx`、`components/AvatarDropdown.tsx`、`api/modules/connectors.ts` 的调用方 | 修改 | `redirect_after` 带前缀；OIDC 完成后 `navigate(stripBase(target))` |
| `layouts/Header.tsx`、`assets/mascot.ts`、`WelcomeScreen.tsx`、`iconForName.tsx` 及专家头像渲染点 | 修改 | 资源路径 `withBase` |
| PWA 文件与挂载点（见现状） | 删除 / 修改 | |
| `components/Markdown/index.tsx` | 修改 | `resolveImageSrc` 接入同源判定，工作区路径改 `getApiUrl` |
| `components/Markdown/resolveImageSrc.test.ts` | 新增 | 七类输入 |
| `utils/toolMediaBlocks.ts` 及 7 个消费方 | 修改 | `/api/` 判断 `BASE_PATH` 化；渲染前过滤 |
| `utils/localePrefs.ts`、`utils/locale.ts`、`components/AuthGuard.tsx` | 修改 | 固定 zh；存量偏好收敛 |
| `AvatarDropdown.tsx`、`pages/Setup/index.tsx`、`pages/Invite/index.tsx` | 修改 | 删语言入口 |
| `components/LanguageSwitcher.tsx`、`pages/Settings/Language/` | 删除 | 孤儿文件 |
| `dashboard/src/locales/intranet/{en,zh}.json`、`src/octop/i18n/intranet/{en,zh}.json` | 修改 | 品牌键覆盖 |
| `src/octop/api/app.py` | 修改 | `spa_fallback` 前加一行 `if is_retired_pwa_path(full_path): raise HTTPException(404)` |
| `src/octop/api/intranet_dashboard.py` | 新增 | `_RETIRED_PWA_FILES`、`is_retired_pwa_path(full_path: str) -> bool` |
| `tests/unit/api/test_pwa_retired.py`、`tests/unit/i18n/test_intranet_brand.py` | 新增 | 见测试策略 |
| `tests/unit/i18n/test_skills.py` | 修改 | ≈L16、≈L20、≈L34 的品牌断言改为读合并 bundle 的期望值 |
| `docs/intranet-frontend.md` | 新增 | 部署说明 |

关键签名：

```ts
// dashboard/src/utils/basePath.ts
export const BASE_PATH: string;            // 规范化后的 import.meta.env.BASE_URL，恒以 "/" 开头和结尾
export const ROUTER_BASENAME: string;      // BASE_PATH 去掉末尾 "/"，根部署时为 "/"
export function withBase(p?: string): string;          // withBase("login") === "/octop/login"；已带前缀或绝对 URL 原样返回
export function stripBase(pathname: string): string;   // stripBase("/octop/login") === "/login"
export function isSameOriginMediaUrl(url: string): boolean;
export function apiPathPrefix(): string;   // `${BASE_PATH}api/`，供 toolMediaBlocks / useChat 判断
```

## 数据模型

无。`users` 的 `locale` 偏好由前端经既有 `PUT /api/preferences` 收敛，不写迁移。

## 配置

无 `config.py` 新键。新增的只有前端构建期参数：`VITE_BASE_PATH`（默认 `/`）与可选的 `dashboard/brand/` 目录。行内构建命令在 `docs/intranet-frontend.md` 中给出。

## 错误处理

不新增 `ErrorCode`。退役 PWA 文件返回 FastAPI 默认 404。同源过滤失败不报错，前端渲染占位或默认图标。

## 安全考虑

- 同源过滤是数据外带防线，与 `w3-01` 的 CSP `img-src 'self' data: blob:` 形成双层；即便 CSP 仍处于 Report-Only，本 spec 也能在前端阻止请求。
- `data:text/html`、`javascript:`、`file:` 一律拒绝；`blob:` 只能由本页创建，放行安全。
- `safeRedirect` 与后端 `sanitize_redirect_after` 的站内路径语义保持不变，只是路径多了前缀。
- PWA 下线后浏览器不再持久缓存 HTML 与接口响应；`index.html` 仍为 `no-cache`。
- 残留：TSX inline 兜底文案中的上游品牌只在键缺失时出现；`fallbackLng: "en"` 使 zh 缺键时显示英文。二者均不涉及数据外带。

## 测试策略

- 前端单测（vitest，门禁由 `w0-02` 的 `make check-frontend` 执行）：
  - `cd dashboard && npm test -- src/utils/basePath.test.ts src/components/Markdown/resolveImageSrc.test.ts src/utils/toolMediaBlocks.test.ts src/utils/localePrefs.test.ts src/api/request.setup.test.ts src/api/request.unauthorized.test.ts`
  - `basePath.test.ts` 用 `vi.stubEnv("BASE_URL", "/octop/")` 后动态 import，覆盖根部署与子路径两种情形。
- 后端单测：`uv run pytest tests/unit/api/test_pwa_retired.py tests/unit/api/test_dashboard_cache.py tests/unit/i18n -q`。
- 构建检查：`cd dashboard && VITE_BASE_PATH=/octop/ npx vite build --outDir ../.tmp-subpath-build --emptyOutDir && ! rg -n '(src|href)="/(assets|favico|logo|apple-touch)' ../.tmp-subpath-build/index.html && rm -rf ../.tmp-subpath-build`。
- 集成与 PG：无数据库改动，不需要。
- 手工联调：按 `docs/intranet-frontend.md` 的 nginx 样例挂 `/octop/`，走一遍登录、401 重登、OIDC 回跳、聊天发图、清缓存英文浏览器首屏。

## 与其他 spec 的交接

- `MBTISelector.tsx`、`MBTITest.tsx` 已由 `w1-04-content-trim` 随 MBTI 一并删除，本 spec 不再涉及。

| 方向 | spec | 内容 |
|---|---|---|
| 依赖 | `w0-02-ci-gates` | `make check-frontend` 跑 vitest；本 spec 的前端用例依赖它才有门禁 |
| 依赖 | `w0-04-fork-isolation-points` | 前后端 intranet overlay 与三方相等测试读合并 bundle；`CHANGELOG-intranet.md`；`make relock` |
| 依赖 | `w1-03-online-fetch-trim` | 已把 `PwaUpdatePrompt` 的 `updateApi` 调用换为 `serviceApi`；本 spec 删除该组件时一并去掉这两处调用；远程 `icon_url` 过滤由本 spec 承接 |
| 依赖 | `w1-04-content-trim` | 已删 `/pwa-debug`、头像菜单外链与 `build@0.1.4`，本 spec 不再规划 |
| 依赖 | `w1-05-saas-decoupling` | SSO 只剩通用 OIDC，本 spec 只处理 OIDC 与 SSO 绑定回跳 |
| 依赖 | `w2-01-offline-build` | Monaco 与 Scalar 本地化、离线 npm 镜像；本 spec 删依赖后用其私服 `make relock` |
| 依赖 | `w3-01-web-security-baseline` | CSP 与安全响应头、内联脚本抽离到 `dashboard/public/boot/`；本 spec 修改抽离后的启动文案，并让 `index.html` 引用这些脚本时用 `%BASE_URL%` |
| 交付 | `p2-07-frontend-controls` | `basePath.ts` 的同源判定可复用于下载与外链管控 |
| 交付 | `w4-02-ops-minimum` | `docs/intranet-frontend.md` 的反代样例供运维清单引用 |

## 风险与回滚

- **上游冲突（中）**：改动的既有文件多为一行调用；`App.tsx`、`request.ts`、`Sidebar.tsx` churn 较高，同步时按 `withBase`/`stripBase` 关键字复核。
- **遗漏根绝对路径（中）**：以需求 1.4 的 `rg` 作为回归检查写进收尾任务；上游新增路径时会被发现。
- **旧 Service Worker 残留（低）**：自卸载脚本加 404 双保险；保留一个发布周期后再删自卸载逻辑。
- **zh 缺键露英文（低）**：保留 `fallbackLng: "en"`；发现后在 zh overlay 补键。
- **回滚**：每个顶层任务独立提交，可按提交回退；`VITE_BASE_PATH` 不设即回到根部署；删除 `dashboard/brand/` 即回到上游品牌。PWA 删除不建议回滚。

## 待行方确认

- 本 spec 无对应的 D 编号，按 steering 第 4 节默认假设（D4 容器单副本部署）起草。
- 非 D 项：① 反代拓扑是否"剥前缀"（不剥前缀需后端挂载前缀，约 +1.5 人日）；② 品牌中英文名与 Logo、favicon、吉祥物源文件，是否保留吉祥物；③ `/api/docs` 标题与介绍中的上游品牌是否需要替换；④ 供应商文档等纯文本外链是否保留为不可点击文本。
