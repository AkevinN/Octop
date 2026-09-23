# 设计文档：统一认证适配器

> spec：`p2-11-identity-adapters` ｜ 波次：二期 ｜ 基线：`757fd12` ｜ 预估：7 人日
> 前置：`w3-04-session-and-password` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 概述

`w3-04` 交付后，Octop 的登录/会话/口令层已完成收口，默认统一认证走 OIDC。若行方最终答复（steering D1）不是 OIDC，本 spec 在此之上补一个协议适配器。CAS、SAML 走既有 `IdentityProvider` 协议扩展一个 kind；LDAP/AD 因协议形状不匹配，在 `UserManager.authenticate` 内开分支。三者互斥，行方只选一种，本文档为每种给出独立方案与估算。

## 现状（已核实，基线 `757fd12`）

- `src/octop/infra/auth/sso/providers/base.py:9` — `SSO_KINDS = ("oidc", "feishu", "dingtalk", "wecom")`；同文件 `IdentityProvider` 为 `Protocol`，定义 `is_configured` / `authorize_url` / `complete_login` / `test_connection` 四个方法，均假定"浏览器重定向 + 授权码"形状。
- `src/octop/infra/auth/sso/service.py` — `self._adapters: dict[str, IdentityProvider] = build_adapters(self)`（≈L54）；`_adapter(kind)` 在多处被调用（≈L96/148/208/228/279），未知 kind 场景下上游会拒绝（`adapter is None` 分支 ≈L211 `raise ValueError("SSO is misconfigured")`）。
- `src/octop/api/routers/auth_oauth.py:28` — `SsoKind = Literal["oidc", "feishu", "dingtalk", "wecom"]`，是 kind 的第二处硬编码，新增协议必须同步改。
- `src/octop/infra/users/manager.py:438` — `UserManager.authenticate(self, username, password)`，≈L463 调用 `verify_password(password, row.password_hash)` 做本地口令校验。LDAP 分支需要在此函数内、`verify_password` 调用前后插入外部目录 bind 逻辑。
- `dashboard/src/api/modules/sso.ts` — `kind` 字段目前类型是裸 `string`（≈L30），不是前端枚举硬约束点；真正需要同步的是后端两处 `Literal`/元组，以及 `SsoPanel.tsx` 里做展示判断的 kind 分支与对应 i18n 标签。
- `src/octop/infra/utils/ssrf_guard.py:71` — `validate_https_url` 显式拒绝 `host == "localhost"`（L75）及私网 IP 字面量；**不适用于**校验行内自建 IdP 的 issuer/元数据地址（大概率是私网 IP），CAS/SAML 的元数据与服务地址校验不得复用该函数，需用只做 scheme 校验 + 主机白名单的本地 helper（`w3-04` 处理 OIDC issuer 时应已建立同类 helper，本 spec 复用其模式）。
- `src/octop/infra/errors.py:115` — `_DEFAULT_STATUS: dict[ErrorCode, int]` 是无保护字典下标（`self.status = _DEFAULT_STATUS[self.code]` ≈L227），新增 `ErrorCode` 必须同批登记，否则构造即 `KeyError`。

## 方案

行方选定协议后，只实施对应分支：

- **CAS 3.0**：新增 `CasAdapter` 实现 `IdentityProvider` 协议。`/login?service=` 跳转对应 `authorize_url`；`/p3/serviceValidate` 票据校验对应 `complete_login(code=ticket)`。登录成功后的用户身份直接交给现有 `service.py` 流程，复用 `w3-04` 的令牌签发与会话表，不新建平行机制。
- **SAML 2.0**：新增 `SamlAdapter`，同样实现 `IdentityProvider` 协议，`authorize_url` 对应发起 AuthnRequest（重定向 binding），`complete_login` 对应接收并校验 POST binding 回传的 SAML Response（依赖 `xmlsec` 做签名/加密断言校验）。离线环境下 `xmlsec1` 系统库与配套 wheel 是否可得，需在启动前确认（见"风险与回滚"）。
- **LDAP/AD**：不实现 `IdentityProvider` 协议，改为在 `UserManager.authenticate` 内加 `if config.auth_backend == "ldap":` 分支，走目录 bind；本地用户表仍作为角色与会话主体存在，LDAP 只负责口令校验与（可选）自动开户。
- **SM2 验签**：CAS/SAML 适配器的签名校验点若需支持国密算法，调用 `p2-02` 暴露的验签接口（具体函数签名以 `p2-02` 落地后的代码为准，实施时用 `rg` 在 `p2-02-kms-sm-crypto` 目录下的 design.md 核对接口名），不在本 spec 内重复实现。

## 组件与接口

三个协议互斥，各自新增文件独立，互不依赖：

| 协议 | 新增文件（实施时以一期落地后的代码重新定位） | 说明 |
|---|---|---|
| CAS | `src/octop/infra/auth/sso/providers/cas.py`（新增） | 实现 `IdentityProvider`；注册点：`base.py` 的 `SSO_KINDS`、`providers/__init__.py::build_adapters`、`auth_oauth.py` 的 `SsoKind`、`dashboard/src/api/modules/sso.ts` 与 `SsoPanel.tsx` 的 kind 分支、对应 i18n 标签，共 5-6 处 |
| SAML | `src/octop/infra/auth/sso/providers/saml.py`（新增） | 同上注册点；另需元数据交换与证书管理界面（复用 `w3-04` 交付的 provider 管理 UI 模式） |
| LDAP | `src/octop/infra/auth/ldap/`（新增目录） | `UserManager.authenticate` 加分支；新增 LDAP 客户端封装、连接池、TLS 配置、属性→角色映射；`config.py` 新增 `auth_backend` 配置键 |

关键函数签名以一期（`w3-04`）落地后的 `IdentityProvider` 协议与 `UserManager.authenticate` 实际签名为准，实施前重新 `rg` 核实。

## 数据模型

无本 spec 独有的新表。CAS/SAML provider 复用 `w3-04`/`w3-01` 交付的 `sso_providers` 表结构（`kind` 列接受新值）；若字段不足以存 SAML 元数据/证书，按 steering §1.1 新增 fork 迁移 `forkNNN_saml_provider_fields`（号不预占，合入前定号），字段：IdP 证书、SP 私钥引用（走 `w3-05` 的 `CryptoProvider` 信封加密，不明文落库）、元数据 URL。LDAP 无需新表，`auth_backend` 是配置键不是数据库字段。

## 配置

| 配置键 | 用途 | 三触点 |
|---|---|---|
| `auth_backend`（仅 LDAP 分支需要） | 是否启用 LDAP 目录 bind（`local` / `ldap`） | `config.py`：`OctopConfig` dataclass 字段 + env 覆盖块 + `return OctopConfig(...)` 逐字段构造，三处缺一则"配了不生效" |
| `ldap_server_url` / `ldap_bind_dn` / `ldap_tls_*` | LDAP 连接参数 | 同上三触点 |

CAS/SAML 无需新增 `config.py` 键，走已有的 `sso_providers` 表配置（同 OIDC provider 的管理方式）。

## 错误处理

新增 `ErrorCode`（按 steering §1.2 规则三，追加到枚举与 `_DEFAULT_STATUS` 末尾，同批补齐后端 en/zh 与 dashboard apiErrors）：

- `CAS_TICKET_INVALID`（CAS 票据校验失败，若选 CAS）
- `SAML_ASSERTION_INVALID`（SAML 断言/签名校验失败，若选 SAML）
- `LDAP_BIND_FAILED`（LDAP bind 失败，若选 LDAP）

优先复用已有的通用鉴权失败码；仅在语义不可复用时才新增。三码均为"仅实施对应协议时才新增"，未选中协议不登记。

## 安全考虑

- CAS/SAML 的 IdP 地址、元数据地址校验一律不用 `ssrf_guard.validate_https_url`（会拒私网 IP），复用 `w3-04` 为 OIDC issuer 建立的本地 scheme 校验 + 主机白名单 helper。
- LDAP 连接强制 TLS，不接受明文 LDAP（389 端口无 TLS）。
- LDAP bind 失败不得把服务器返回的具体错误（如"用户不存在" vs "口令错误"）透传给前端，防止账号枚举。
- SAML 断言重放：需校验 `NotBefore`/`NotOnOrAfter` 与 `InResponseTo`，防止重放攻击。
- 三种适配器登录成功后一律走 `w3-04` 的会话签发与吊销路径，不新建平行令牌存储，避免出现第二套吊销盲区。

## 测试策略

- 单测：`uv run pytest tests/unit/auth -q`（新增 `test_cas_adapter.py` / `test_saml_adapter.py` / `test_ldap_backend.py`，取决于实施的协议）。
- 集成：`uv run pytest tests/integration -k "sso or auth" -q`（需 `w0-02` 的 CI 门禁已合入才具备强制力）。
- PG：`OCTOP_TEST_DATABASE_URL=... uv run pytest tests/integration -k "sso" -q`（若新增 fork 迁移，需 SQLite 与 PG 两个方言都跑一遍）。
- i18n：`uv run pytest tests/unit/i18n -q`（新增 ErrorCode 的四份文案 + `_DEFAULT_STATUS` 校验）。
- 前端：`cd dashboard && npx tsc -b`；如新增 `SsoPanel` 相关用例，`npm run test`（需 `w0-02` 的 vitest CI job 已合入）。

## 与其他 spec 的交接

- **依赖 `w3-04`**：登录模式三态开关、会话表（`auth_sessions`）、短时令牌签发/吊销、口令策略。本 spec 的三种适配器登录成功后统一调用 `w3-04` 暴露的会话签发接口，不重新实现。
- **依赖 `p2-02`（若 IdP 要求 SM2 签名）**：SM2 验签能力由 `p2-02` 的 `CryptoProvider` 国密后端提供；本 spec 只在验签点接入，不重复实现算法原语。若 `p2-02` 未合入而 IdP 强制要求国密验签，本 spec 在该部署中阻塞（见需求 4.2）。
- **交付给谁**：无下游 spec 直接依赖本 spec 的产出；本 spec 是 D1 默认假设（OIDC）不成立时的独立补丁单元。
- **看似相关但归别的 spec**：
  - OIDC 加固（算法白名单、issuer 校验、准入组映射）——归 `w3-04`，`w3-04` 的 S07 源材料里已包含，本 spec 不重复。
  - 三员分立、权限键治理、存量 `permissions` 清洗——归 `w3-03`。
  - 会话管理 API（会话列表/单个吊销/全部吊销的路由与前端页面）——归 `w3-04`，本 spec 的三种适配器只是新的登录入口，不新增会话管理界面。
  - 国密算法原语、KMS/SDF 托管——归 `p2-02`。

## 风险与回滚

- SAML 是三者中风险最高的一支：依赖 `xmlsec1` 系统库与对应 Python wheel，在信创 CPU 架构（如龙芯）上的离线编译可能单独消耗 5 人日以上（steering D4：龙芯需全量自编译 wheel）。若离线环境无法提供 `xmlsec1`，SAML 方案不可行，需退回 CAS 或 LDAP。
- kind 注册点分散在后端两处（`base.py` 元组、`auth_oauth.py` 的 `Literal`）与前端两处（`sso.ts`、`SsoPanel.tsx`）及对应 i18n，共 5-6 处，遗漏任一处会导致该协议在部分路径下"看起来支持但实际 404 或类型报错"。
- 回滚：三种适配器均为纯新增文件 + 若干处新增分支，不改动 `w3-04` 已交付的会话/令牌核心路径；回滚只需下线新 kind 的 provider 配置（或还原 `config.auth_backend`），不影响 OIDC 与已有会话。

## 待行方确认

- 引用 steering 第 4 节 D1：统一认证协议若不是 OIDC，三选一（CAS 3.0 / SAML 2.0 / LDAP/AD）需在本 spec 开工前明确，本文档三个需求/方案互斥，行方只需其中一种。
- 若最终选 SAML 且部署目标含信创 CPU（D4），需提前确认 `xmlsec1` 系统库与 wheel 的离线可得性，否则本 spec 的 SAML 分支不可执行。
- 若 IdP 要求 SM2 签名（D8 国密要求），需确认 `p2-02` 的排期是否早于本 spec 启动，否则本 spec 在该部署中阻塞。
