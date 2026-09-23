# 实施计划：前端内网适配

> spec：`w4-01-frontend-baseline` ｜ 波次：Wave 4 ｜ 基线：`757fd12` ｜ 预估：13.5 人日
> 前置：`w0-02-ci-gates`、`w0-04-fork-isolation-points`、`w1-03-online-fetch-trim`、`w1-04-content-trim`、`w1-05-saas-decoupling`、`w2-01-offline-build`、`w3-01-web-security-baseline` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

每个顶层任务完成后可独立提交；提交前运行任务内的验证命令。

- [ ] 1. 确认前置 spec 已合入并记录基线
  - 改动：无代码改动。确认 `dashboard/src/i18nIntranet.ts`、`dashboard/src/locales/intranet/`、`src/octop/i18n/intranet/`、`dashboard/public/boot/` 存在，`dashboard/src/pages/PwaDebug/` 已不存在，`make check-frontend` 可用；把当前提交记为 `W401_BASE`。
  - 验证：`test -f dashboard/src/i18nIntranet.ts && test -d dashboard/public/boot && test ! -e dashboard/src/pages/PwaDebug && make check-frontend && git rev-parse HEAD`
  - _需求：9.1_

- [ ] 2. 新增子路径与同源判定收口模块（测试先行）
  - [ ] 2.1 先写 `dashboard/src/utils/basePath.test.ts`：根部署与 `/octop/` 两种 `BASE_URL` 下的 `withBase`、`stripBase`、`ROUTER_BASENAME`、`apiPathPrefix`；`isSameOriginMediaUrl` 七类输入（同源相对、同源绝对、跨域 http、`data:image/png`、`data:text/html`、`blob:`、`file://`）。此时运行应失败。
    - 验证：`cd dashboard && npm test -- src/utils/basePath.test.ts`（预期失败）
    - _需求：5.4_
  - [ ] 2.2 新增 `dashboard/src/utils/basePath.ts`，按 design.md 签名实现。
    - 验证：`cd dashboard && npm test -- src/utils/basePath.test.ts`
    - _需求：2.1, 5.4_

- [ ] 3. Vite base、Router basename、API 前缀
  - 改动：`dashboard/vite.config.ts` 返回对象加 `base: env.VITE_BASE_PATH || "/"`；`dashboard/src/App.tsx` 的 `<BrowserRouter>` 加 `basename={ROUTER_BASENAME}`；`dashboard/src/api/config.ts` 的 `getApiUrl` / `getWsUrl` 前缀改为 `` `${BASE_PATH}api` ``，并在 `declare const BASE_URL` 上加注释说明它是 API 源站；`dashboard/index.html` 的 `/favico.svg`、`/apple-touch-icon.png`、`/logo.svg` 及 `w3-01` 引入的 `boot/*.js` 改为 `%BASE_URL%` 前缀。在 `basePath.test.ts` 补 `getApiUrl("/models")` 子路径用例。
  - 验证：`cd dashboard && npm test -- src/utils/basePath.test.ts && VITE_BASE_PATH=/octop/ npx vite build --outDir ../.tmp-subpath-build --emptyOutDir && ! rg -n '(src|href)="/(assets|favico|logo|apple-touch|boot)' ../.tmp-subpath-build/index.html && rm -rf ../.tmp-subpath-build`
  - _需求：1.1, 1.2, 1.3, 2.1_

- [ ] 4. 硬跳转与路径守卫
  - 改动：先改 `dashboard/src/api/request.setup.test.ts` 与 `request.unauthorized.test.ts`，新增子路径用例（期望 `/octop/setup`、`/octop/login`，且位于 `/octop/login` 时不跳转）。再改 `api/request.ts` 的 `handleSetupRequired` / `handleUnauthorized`：守卫用 `stripBase(window.location.pathname)`，跳转用 `withBase("setup")` / `withBase("login")`；`components/ErrorBoundary/index.tsx` 的 `handleHome` 改 `withBase("chat")`；`layouts/Sidebar.tsx` 的 `handleNavigate`、`handleExpandChatRail` 守卫改 `stripBase`；`pages/Experts/components/CreateFromExpertDrawer.tsx` ≈L466 的 `<a href>` 改 `<Link to="/admin/models">`。
  - 验证：`cd dashboard && npm test -- src/api/request.setup.test.ts src/api/request.unauthorized.test.ts && npx tsc -b`
  - _需求：2.2, 2.3, 2.4_

- [ ] 5. 登录、SSO 绑定与连接器 OAuth 回跳
  - 改动：`pages/Login/index.tsx` 的 `startOauth(kind, …)` 与 `window.location.replace` 兜底改 `withBase("chat")`；`components/AvatarDropdown.tsx` 的 `startOauthBind` 回跳改 `withBase("chat")`；`pages/Login/OidcComplete.tsx` 的 `DEFAULT_REDIRECT` 改 `withBase("chat")`，`safeRedirect` 先 `stripBase` 再做站内校验，路由跳转用去前缀路径；`connectorsApi.oauthStart` / `oauthStartCatalog` 的调用方（`rg -n 'oauthStart' dashboard/src --glob '!api/modules/*'` 定位）传 `withBase("connectors")`。新增 `pages/Login/OidcComplete.test.ts` 覆盖 `safeRedirect("/octop/chat")`、`safeRedirect("//evil")`。
  - 验证：`cd dashboard && npm test -- src/pages/Login/OidcComplete.test.ts && npx tsc -b`
  - _需求：2.5_

- [ ] 6. 静态资源路径 base 化
  - 改动：`layouts/Header.tsx` 的 `mobileLogoSrc`、`layouts/Sidebar.tsx` 的 `wordmarkSrc` 与 `pwa-192.png`、`assets/mascot.ts` 的 `OCTOP_EMPTY_MASCOT_SRC`、`pages/Chat/components/WelcomeScreen.tsx` 的 `MASCOT_PEEK` / `MASCOT_TYPE`、`Login/index.tsx` 与 `Setup/index.tsx` 的 Logo 改 `withBase(...)`；专家头像：`iconForName.tsx` 的前缀判断保持 `includes`，头像渲染点（`rg -n 'avatar_url|avatarUrl' dashboard/src/pages/Experts dashboard/src/components --glob '!*.test.*'` 定位）对 `/` 开头的非 API 地址套 `withBase`。
  - 验证：`! rg -n '"/(logo|favico|apple-touch|pwa-|octop-mascot|assets/mbti|experts/avatars)' dashboard/src --glob '!*.test.*' && cd dashboard && npx tsc -b`
  - _需求：1.4, 1.5_

- [ ] 7. 删除前端 PWA 代码与挂载点
  - 改动：删除 `dashboard/src/sw-register.ts`、`sw-register.test.ts`、`pwa.ts`、`pwa-prompt.ts`、`components/PwaUpdatePrompt/`（连同 `w1-03` 留下的 `serviceApi` 调用）、`components/PwaInstallPrompt/`；删除 `main.tsx` 的 `import "./pwa-prompt"` 与 `registerSW` 动态导入、`layouts/MainLayout/index.tsx`、`layouts/Header.tsx`、`pages/Chat/index.tsx` 中的 PWA 组件导入与挂载。不删 `pwa.*` i18n 键。
  - 验证：`! rg -n 'sw-register|pwa-prompt|PwaUpdatePrompt|PwaInstallPrompt' dashboard/src && cd dashboard && npx tsc -b && npm run lint`
  - _需求：3.3_

- [ ] 8. 删除 PWA 构建插件与公共文件
  - 改动：`dashboard/vite.config.ts` 删除 `VitePWA` 导入与调用、`webcrypto` 导入与垫片；`dashboard/package.json` 删除 `vite-plugin-pwa` 与 `overrides` 中的 `serialize-javascript`、`@rollup/plugin-terser`；删除 `dashboard/public/manifest.json`、`dashboard/public/offline.html`；`index.html` 删除 PWA meta 与 manifest link；启动脚本中的 Service Worker 自卸载逻辑保留。最后一个 commit 用 `make relock` 重生成 `dashboard/package-lock.json`。
  - 验证：`make build-frontend && test ! -e src/octop/dashboard/sw.js && test ! -e src/octop/dashboard/manifest.json && test ! -e src/octop/dashboard/offline.html && ! ls src/octop/dashboard/workbox-*.js 2>/dev/null && ! rg -n 'VitePWA|vite-plugin-pwa' dashboard/vite.config.ts dashboard/package.json`
  - _需求：3.1, 3.3, 3.4_

- [ ] 9. 后端让退役的 PWA 文件返回 404
  - 改动：先写 `tests/unit/api/test_pwa_retired.py`：`GET /sw.js`、`GET /manifest.json` 返回 404，`GET /chat` 仍返回 SPA 外壳（预期先失败）。新增 `src/octop/api/intranet_dashboard.py` 的 `is_retired_pwa_path`；`src/octop/api/app.py` 的 `spa_fallback` 开头加一行调用。`_NO_CACHE_DASHBOARD_NAMES` 与 `tests/unit/api/test_dashboard_cache.py` 不动。
  - 验证：`uv run pytest tests/unit/api/test_pwa_retired.py tests/unit/api/test_dashboard_cache.py -q`
  - _需求：3.2, 3.4_

- [ ] 10. Markdown 图片同源过滤
  - 改动：先写 `dashboard/src/components/Markdown/resolveImageSrc.test.ts`（七类输入 + 工作区 `file://` 转换带前缀），并从 `components/Markdown/index.tsx` 导出 `resolveImageSrc`。再改 `resolveImageSrc`：放行分支改为 `isSameOriginMediaUrl`，`/api/` 前缀判断改 `apiPathPrefix()`，工作区转换改 `getApiUrl("/workspace/media?path=…")`，其余返回空串走 `MarkdownImage` 的 `[alt]` 占位。
  - 验证：`cd dashboard && npm test -- src/components/Markdown/resolveImageSrc.test.ts`
  - _需求：4.1, 4.2, 4.3, 4.4_

- [ ] 11. 工具媒体与远程图标同源过滤
  - 改动：先在 `dashboard/src/utils/toolMediaBlocks.test.ts` 补跨域 url 被过滤、子路径下 `needsAuthBlobFetch` 返回 `true` 的用例。再改 `utils/toolMediaBlocks.ts`：`needsAuthBlobFetch` 先做同源校验，路径比对与 `agentMediaPreviewUrl` 等处的 `/api/` 改 `apiPathPrefix()` / `getApiUrl`；`ToolMediaStrip.tsx`、`ChatMediaPlayer.tsx`、`MessageFileCard.tsx`、`collectTurnToolMedia.ts` 渲染前以 `isSameOriginMediaUrl` 过滤；`useChat.ts`、`useAuthImageSrc.ts`、`DefaultToolRenderer.tsx` 的 `/api/` 前缀判断 `BASE_PATH` 化；远程 `icon_url` 渲染点（`rg -n 'icon_url|iconUrl' dashboard/src/pages dashboard/src/components --glob '!*.test.*'` 定位）非同源时回落默认图标。
  - 验证：`cd dashboard && npm test -- src/utils/toolMediaBlocks.test.ts && npx tsc -b`
  - _需求：5.1, 5.2, 5.3_

- [ ] 12. 语言固定中文：初始化与咽喉点
  - 改动：先改 `dashboard/src/utils/localePrefs.test.ts`：`resolveInitialLocale()` 在浏览器语言 `en-US`、存储值 `en` 时都返回 `zh`，删去 `detectBrowserLocale` 用例；新增 `utils/locale.test.ts` 断言 `applyUserLocale("en")` 后 `i18n.language === "zh"`。再改 `localePrefs.ts`（`resolveInitialLocale` 恒 `"zh"`，删 `detectBrowserLocale`）、`locale.ts`（`applyUserLocale` / `applyGuestLocale` 恒应用 `"zh"`）、`i18n.ts` 的 `initI18n`（`supportedLngs: ["zh"]`，`fallbackLng` 保留 `"en"`）；`dashboard/index.html` 改 `lang="zh-CN"`；`dashboard/public/boot/` 启动脚本的文案固定中文，删除 `navigator.language` 分支。
  - 验证：`cd dashboard && npm test -- src/utils/localePrefs.test.ts src/utils/locale.test.ts && ! rg -n 'navigator.language' index.html public/boot`
  - _需求：6.1, 6.4_

- [ ] 13. 语言入口移除与存量偏好收敛
  - 改动：删除 `AvatarDropdown.tsx` 的语言 `Segmented` 与 `handleLocaleChange`；删除 `pages/Setup/index.tsx` 与 `pages/Invite/index.tsx` 的语言切换控件；删除 `components/LanguageSwitcher.tsx` 与 `pages/Settings/Language/`；`components/AuthGuard.tsx` 在 `user.locale !== "zh"` 时调用一次 `preferencesApi.setLocale("zh")`（失败静默）。新增 `components/AuthGuard.locale.test.tsx` 断言该调用只发生一次。不删 `account.langZh` 等 i18n 键。
  - 验证：`cd dashboard && npm test -- src/components/AuthGuard.locale.test.tsx && ! rg -n 'handleLocaleChange|LanguageSwitcher' src && npx tsc -b && npm run lint`
  - _需求：6.2, 6.3_

- [ ] 14. 品牌文案：overlay 与门禁
  - [ ] 14.1 先写 `tests/unit/i18n/test_intranet_brand.py`：读后端合并 bundle 与前端 `locales/{zh,en}.json` 叠加 `locales/intranet/{zh,en}.json` 后的结果（复用 `w0-04` 的 `deep_merge`），断言字符串值不含 `Octop`（`OctopBot` 除外），且 overlay 中的品牌名与 `dashboard/brand/brand.json` 一致；断言上游四个 JSON 相对 `W401_BASE` 无改动。此时运行应失败。
    - 验证：`uv run pytest tests/unit/i18n/test_intranet_brand.py -q`（预期失败）
    - _需求：7.1, 7.2_
  - [ ] 14.2 在 `src/octop/i18n/intranet/{en,zh}.json` 与 `dashboard/src/locales/intranet/{en,zh}.json` 写入含品牌字样键的覆盖值（`skills.octop-assistant`、`skills.octop_assistant` 前后端同值）；`tests/unit/i18n/test_skills.py` ≈L16、≈L20、≈L34 的期望值改为品牌版本。
    - 验证：`uv run pytest tests/unit/i18n -q && rg -n 'X-Octop-Access-Token|X-Octop-Agent-Id|octop:ui-locale|octop:unauthorized|octop-assistant' dashboard/src`
    - _需求：7.1, 7.2, 7.3, 7.4_

- [ ] 15. 品牌视觉资产与标题：构建插件
  - 改动：新增 `dashboard/scripts/brandPlugin.ts`、`dashboard/brand/brand.json`、`dashboard/brand/public/`（素材到位前放占位图）、`dashboard/src/brand.ts`；`vite.config.ts` 注册 `brandPlugin()`；`index.html` 的 `<title>` 与 `apple-mobile-web-app-title` 改 `%BRAND_NAME%`；`Login/index.tsx`、`Setup/index.tsx`、`Sidebar.tsx` 的 `alt` 改 `BRAND_NAME`。新增 `dashboard/scripts/brandPlugin.test.ts` 覆盖"品牌目录缺席时回落上游名称且不复制"。
  - 验证：`cd dashboard && npm test -- scripts/brandPlugin.test.ts && cd .. && make build-frontend && cmp dashboard/brand/public/logo.svg src/octop/dashboard/logo.svg && ! rg -n 'Octop' src/octop/dashboard/index.html && ! rg -n 'alt="Octop"' dashboard/src`
  - _需求：8.1, 8.2, 8.3, 8.4_

- [ ] 16. 收尾
  - 改动：新增 `docs/intranet-frontend.md`（`VITE_BASE_PATH` 与品牌目录用法、nginx 剥前缀样例、OIDC `dashboard_origin` 必须含子路径、PWA 已下线与自卸载保留周期、同源过滤范围）；`CHANGELOG-intranet.md` 记录五项变更；本 spec 无 API 变更，不改 `docs/api-intranet.md`。复跑子路径回归检查，清理本 spec 引入的孤儿符号。
  - 验证：`make all && cd dashboard && npx tsc -b && npm run lint && npm run test && cd .. && make check-frontend && ! rg -n '"/(logo|favico|apple-touch|pwa-|octop-mascot|assets/mbti|experts/avatars)' dashboard/src --glob '!*.test.*'`
  - _需求：1.4, 9.1, 9.2_
