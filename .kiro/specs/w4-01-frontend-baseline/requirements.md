# 需求文档：前端内网适配

> spec：`w4-01-frontend-baseline` ｜ 波次：Wave 4 ｜ 基线：`757fd12` ｜ 预估：13.5 人日
> 前置：`w0-02-ci-gates`、`w0-04-fork-isolation-points`、`w1-03-online-fetch-trim`、`w1-04-content-trim`、`w1-05-saas-decoupling`、`w2-01-offline-build`、`w3-01-web-security-baseline` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 引言

**结论：** 本 spec 让 `dashboard/` 构建出的控制台在行内网络里"挂得上、看得对、不外带"：可部署在反向代理子路径下；PWA 整体下线；模型输出与工具结果里的外部图片、媒体地址不再被浏览器自动请求；界面语言固定为中文；品牌字样、Logo 与吉祥物在构建期替换为行方品牌。

**为什么做：**

- 行内应用通常共用一个网关域名，按子路径分流（如 `https://portal.bank/octop/`）。基线前端的资源、跳转与 API 前缀全部写成根绝对路径，挂在子路径下首屏即 404，未登录跳转会跳出应用。
- PWA 的 Service Worker 把 HTML 外壳与静态分片长期留在浏览器 Cache Storage（`vite.config.ts` 的 `VitePWA` 运行时缓存，含 24 小时 HTML 外壳、30 天静态分片、5 分钟 `api-readonly` 聊天接口缓存），等保场景不接受。
- Markdown 渲染会把任意 `https://` 图片地址原样放进 `<img src>`，工具结果里的媒体地址也一样，这是模型或工具把数据编码进 URL 外带的通道。
- 行方要求中文界面；控制台当前会按浏览器语言与用户存量偏好切到英文。
- 交付物需要行方品牌，而上游 locale JSON 是全仓 churn 最高的文件，源码内全量替换每次同步上游都会冲突。

**范围内：**

1. 子路径部署：Vite `base`、Router `basename`、前端全部根绝对资源路径与绕过 Router 的硬跳转、SSO 与连接器 OAuth 回跳、API 与 WebSocket 前缀。采用"反向代理剥前缀"拓扑。
2. PWA 下线：Service Worker、`manifest.json`、`offline.html`、`VitePWA` 插件及其依赖尾巴、`PwaUpdatePrompt` 与 `PwaInstallPrompt` 组件及挂载点；后端对已退役的 `sw.js` 返回 404，让旧客户端的 Service Worker 自然注销。
3. 同源过滤：Markdown 图片与四个工具媒体消费点只渲染同源、`data:image/*`、`blob:` 地址；远程 `icon_url` 同样过滤（`w1-03` 交接）。
4. 语言固定中文：初始语言、`applyUserLocale` 五个调用点、三个语言切换入口、首屏启动文案、`<html lang>`，以及把存量用户的 `locale` 偏好收敛为 `zh`。
5. 构建期品牌替换：品牌名文案走 intranet overlay，Logo 与吉祥物由构建插件覆盖同名产物，并用测试把"合并后 bundle 不含上游品牌字样"变成门禁。

**范围外：**

| 事项 | 归属 |
|---|---|
| Monaco 编辑器本地化、`monaco-editor` 显式声明、Scalar 本地化、离线 npm 镜像 | `w2-01-offline-build` |
| CSP 与安全响应头、`index.html` 两段内联脚本抽离到 `dashboard/public/boot/` | `w3-01-web-security-baseline` |
| 云验证码适配器删除 / 本地图形验证码终态 | `w1-05-saas-decoupling` / `w3-01-web-security-baseline` |
| vitest 接入 CI 与 `make check-frontend` | `w0-02-ci-gates` |
| `/pwa-debug` 页、头像菜单 GitHub 与文档站外链、`build@0.1.4` | `w1-04-content-trim`（已删除） |
| SkillHub、skills.sh 等运行期外呼面 | `w1-03-online-fetch-trim`（已删除） |
| 前端管控（水印、复制下载限制等） | `p2-07-frontend-controls` |
| 反向代理不剥前缀的拓扑、`/api/docs` 标题中的上游品牌、供应商文档纯文本外链 | 不做，见 design.md"待行方确认" |

## 需求

### 需求 1：子路径下的静态资源与路由

**用户故事：** 作为行内运维，我希望把控制台挂在网关的任意子路径下，以便与其它行内应用共用一个域名。

#### 验收标准

1. 当以 `VITE_BASE_PATH=/octop/` 构建时，构建产物 `index.html` 引用的脚本、样式、favicon、Logo 应当全部以 `/octop/` 开头。
2. 当以默认参数（不设 `VITE_BASE_PATH`）构建时，产物 `index.html` 中的资源路径应当与基线一致地以 `/` 开头。
3. 当用户在子路径部署下直接访问或刷新 `/octop/chat/<id>` 时，前端路由应当匹配到聊天页而不是 404 页。
4. 控制台源码应当始终不含根绝对的公共资源路径：`rg -n '"/(logo|favico|apple-touch|pwa-|octop-mascot|assets/mbti|experts/avatars)' dashboard/src --glob '!*.test.*'` 无输出。
5. 当后端下发的内置专家 `avatar_url` 为 `/experts/avatars/<id>.svg` 时，前端应当把它渲染为带子路径前缀的地址。

### 需求 2：子路径下的 API、硬跳转与登录回跳

**用户故事：** 作为行内用户，我希望在子路径部署下登录、掉线重登、SSO 回跳都留在应用内，以便不会被踢到网关首页或陷入重定向循环。

#### 验收标准

1. 当子路径部署下 `getApiUrl("/models")` 被调用且 API 源站为空时，应当返回 `/octop/api/models`；`getWsUrl` 同理带前缀。
2. 当收到 401 时，`handleUnauthorized` 应当跳转到 `/octop/login`；当收到 503 setup-required 时，`handleSetupRequired` 应当跳转到 `/octop/setup`。
3. 如果当前页面已经是 `/octop/login`、`/octop/setup` 或 `/octop/invite`，那么两个处理函数应当不再跳转（守卫对去前缀后的路径判断）。
4. 当用户点击错误兜底页"返回聊天"、专家抽屉"去模型配置"、侧栏"聊天"时，应当停留在 `/octop/` 前缀内。
5. 当用户发起 OIDC 登录、SSO 绑定或连接器 OAuth 时，前端传给后端的 `redirect_after` 应当带子路径前缀；OIDC 回跳完成后应当落到 `/octop/chat`，且 `safeRedirect` 仍只接受站内路径。

### 需求 3：PWA 下线

**用户故事：** 作为安全合规人员，我希望浏览器不再安装 Service Worker、不再缓存页面与接口响应，以便下线或撤权后终端上不留应用数据。

#### 验收标准

1. 当执行 `make build-frontend` 后，`src/octop/dashboard/` 下应当不存在 `sw.js`、`workbox-*.js`、`manifest.json`、`offline.html`。
2. 当浏览器请求 `/sw.js` 或 `/manifest.json` 时，后端应当返回 404 而不是 SPA 外壳 HTML。
3. 控制台源码应当始终不含 PWA 注册与提示代码：`rg -n 'sw-register|pwa-prompt|PwaUpdatePrompt|PwaInstallPrompt|VitePWA|vite-plugin-pwa' dashboard/src dashboard/vite.config.ts dashboard/package.json` 无输出。
4. 在 PWA 下线后的第一个发布周期内，启动脚本中既有的 Service Worker 自卸载逻辑应当保留，访问首页后 `navigator.serviceWorker.getRegistrations()` 为空。

### 需求 4：Markdown 图片同源过滤

**用户故事：** 作为安全合规人员，我希望模型输出里的外部图片不被浏览器自动请求，以便模型无法经图片 URL 把会话数据带出行内。

#### 验收标准

1. 当 Markdown 中出现 `![x](https://example.com/a.png)` 时，`resolveImageSrc` 应当返回空串，页面渲染 `[x]` 占位，不对 `example.com` 发请求。
2. 如果图片地址是同源相对路径、同源绝对 URL、`data:image/*` 或 `blob:`，那么 `resolveImageSrc` 应当原样放行（同源 API 路径带子路径前缀）。
3. 如果图片地址是 `data:text/html`、`javascript:`、跨域 `http(s)`，或不在工作区内的 `file://` 路径，那么 `resolveImageSrc` 应当返回空串。
4. 当图片地址是工作区内 `file://` 路径时，应当转换为带子路径前缀的 `api/workspace/media?path=…` 地址。

### 需求 5：工具媒体与远程图标同源过滤

**用户故事：** 作为安全合规人员，我希望工具返回的图片、音视频与文件卡片，以及技能与专家的远程图标，只从本站加载，以便堵住第二条外带通路。

#### 验收标准

1. 当工具结果中的媒体 `url` 为跨域地址时，`ToolMediaStrip`、`ChatMediaPlayer`、`MessageFileCard`、`collectTurnToolMedia` 应当不渲染该项。
2. 当媒体 `url` 为带子路径前缀的 `api/agents/…` 或 `api/workspace/media` 地址时，`needsAuthBlobFetch` 应当返回 `true` 并以鉴权 blob 方式加载。
3. 如果 `icon_url` 不是同源地址，那么技能与专家卡片应当显示默认图标而不是远程图片。
4. `isSameOriginMediaUrl` 应当始终对七类输入（同源相对、同源绝对、跨域 http、`data:image`、`data:text/html`、`blob:`、`file://`）给出确定结果，并由 vitest 覆盖。

### 需求 6：界面语言固定中文

**用户故事：** 作为行内用户，我希望控制台始终是中文，以便不因浏览器语言或历史偏好出现英文界面。

#### 验收标准

1. 当清空 localStorage 且浏览器语言为 `en-US` 时，首屏启动文案、React 挂载后的界面与 `document.documentElement.lang` 应当分别为中文、中文与 `zh-CN`。
2. 当后端用户的 `locale` 为 `en` 并登录时，界面应当保持中文，且该用户的 `locale` 偏好被收敛为 `zh`（`GET /api/preferences` 返回 `zh`）。
3. 控制台应当始终不提供语言切换入口：头像菜单、安装向导、邀请页均无语言控件，`LanguageSwitcher.tsx` 与 `pages/Settings/Language/` 不存在。
4. 在语言固定期间，前端发出的请求应当始终带 `Accept-Language: zh`。

### 需求 7：品牌文案替换

**用户故事：** 作为行方产品负责人，我希望界面上的产品名是行方品牌，以便交付物符合行内视觉规范，同时不增加跟随上游的冲突面。

#### 验收标准

1. 上游 locale JSON 应当始终不因品牌替换而修改：`git diff --quiet <基线> -- dashboard/src/locales/zh.json dashboard/src/locales/en.json src/octop/i18n/zh.json src/octop/i18n/en.json` 成立。
2. 当合并 intranet overlay 后，后端与前端 zh、en bundle 的字符串值应当不含 `Octop`，白名单 `OctopBot` 除外。
3. 当品牌名改动时，后端 `skills` 子树与前端 `skills` 子树应当仍逐值相等，`uv run pytest tests/unit/i18n -q` 通过。
4. 协议标识符应当始终保持不变：`rg -n 'X-Octop-Access-Token|X-Octop-Agent-Id|octop:ui-locale|octop:unauthorized|octop-assistant' dashboard/src` 仍有命中。

### 需求 8：品牌视觉资产与页面标题

**用户故事：** 作为行方产品负责人，我希望 Logo、favicon、吉祥物与浏览器标题来自行方素材，以便替换素材时不改源码。

#### 验收标准

1. 当 `dashboard/brand/public/` 下存在与 `dashboard/public/` 同名的文件时，构建产物中对应文件应当与品牌目录中的文件字节一致。
2. 当构建完成时，产物 `index.html` 的 `<title>` 与 `apple-mobile-web-app-title` 类文案应当为 `dashboard/brand/brand.json` 中的品牌名，且不含 `Octop`。
3. 登录页、安装向导、侧栏 Logo 的 `alt` 应当始终取自品牌常量，不硬编码 `Octop`。
4. 如果 `dashboard/brand/` 不存在，那么构建应当按上游素材与名称照常完成（上游 CI 不受影响）。

### 需求 9：交付门禁与文档

**用户故事：** 作为 fork 维护者，我希望本 spec 的行为有自动化回归保护并有部署说明，以便同步上游时不被悄悄改回去。

#### 验收标准

1. 当执行 `make all` 与 `make check-frontend` 时，二者应当全绿，其中包含本 spec 新增的 vitest 用例与 pytest 用例。
2. 当本 spec 合入后，`CHANGELOG-intranet.md` 应当记录子路径、PWA 下线、同源过滤、语言固定、品牌替换五项变更，`docs/intranet-frontend.md` 应当给出剥前缀反代配置样例与 `dashboard_origin` 填写要求。
