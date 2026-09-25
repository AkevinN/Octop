# 实施计划：统一认证适配器

> spec：`p2-11-identity-adapters` ｜ 波次：二期 ｜ 基线：`757fd12` ｜ 预估：7 人日
> 前置：`w3-04-session-and-password` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

每个顶层任务完成后可独立提交；提交前运行任务内的验证命令。三个协议互斥，只实施行方最终确认的那一支（任务 2/3/4 三选一）。

- [ ] 1. 确认前置 spec 已合入并记录基线；确认行方选定的协议
  - 改动：无代码改动；确认 `w3-04-session-and-password` 已合入（会话表、短时令牌、登录模式开关可用），确认行方对 steering D1 的最终答复（CAS / SAML / LDAP）
  - 验证：`git log --oneline -1`（记录本 spec 开工时的基线提交）；`rg -n "auth_sessions" src/octop/infra/db/migrations` 确认会话表已存在
  - _需求：5.1, 5.2_

- [ ] 2. CAS 3.0 适配器（若行方选定 CAS）
  - [ ] 2.1 新增 `CasAdapter` 并注册五处 kind 入口
    - 改动：新增 `src/octop/infra/auth/sso/providers/cas.py` 实现 `IdentityProvider`；改 `providers/base.py` 的 `SSO_KINDS`、`providers/__init__.py::build_adapters`、`auth_oauth.py` 的 `SsoKind`、`dashboard/src/api/modules/sso.ts` 与 `SsoPanel.tsx` 的 kind 分支
    - 验证：`uv run pytest tests/unit/auth -k cas -q`；`cd dashboard && npx tsc -b`
    - _需求：1.1_
  - [ ] 2.2 `/login?service=` 跳转与 `/p3/serviceValidate` 票据校验
    - 改动：`CasAdapter.authorize_url` 生成 CAS 跳转地址；`CasAdapter.complete_login` 调用 `serviceValidate` 校验票据并映射用户
    - 验证：`uv run pytest tests/unit/auth/test_cas_adapter.py -q`（先写会失败的用例覆盖成功票据与过期/无效票据两种路径）
    - _需求：1.2, 1.3, 1.4_
  - [ ] 2.3 登录成功后复用 `w3-04` 会话签发，i18n 与错误码补齐
    - 改动：`CasAdapter.complete_login` 返回结果接入既有会话签发流程；新增 `CAS_TICKET_INVALID` 到 `ErrorCode` 枚举与 `_DEFAULT_STATUS` 末尾，补齐后端 en/zh 与 dashboard apiErrors 四份文案
    - 验证：`uv run pytest tests/unit/i18n -q`；`uv run pytest tests/integration -k "cas or sso" -q`
    - _需求：1.5_

- [ ] 3. SAML 2.0 适配器（若行方选定 SAML）
  - [ ] 3.1 确认 `xmlsec1` 离线可得性，新增 `SamlAdapter` 骨架并注册五处 kind 入口
    - 改动：确认内网私服或离线介质能提供 `xmlsec1` 系统库与配套 wheel（信创 CPU 架构需额外确认）；新增 `src/octop/infra/auth/sso/providers/saml.py`；同 2.1 的五处注册点
    - 验证：目标部署环境上 `python -c "import xmlsec"` 成功；`cd dashboard && npx tsc -b`
    - _需求：2.3_
  - [ ] 3.2 元数据交换与 IdP 证书管理
    - 改动：`SamlAdapter.is_configured` / provider 管理界面支持录入 IdP 元数据 URL 与证书；若字段不足，新增 fork 迁移 `forkNNN_saml_provider_fields`（合入前定号，成对 `.sql`/`.pg.sql`）
    - 验证：`uv run pytest tests/unit/db -k saml -q`；`uv run pytest tests/unit/auth -k saml_metadata -q`
    - _需求：2.1_
  - [ ] 3.3 AuthnRequest 发起与 SAML Response 签名/断言校验
    - 改动：`SamlAdapter.authorize_url` 发起重定向 binding AuthnRequest；`SamlAdapter.complete_login` 校验 POST binding 回传的签名与（如启用）加密断言，校验 `NotBefore`/`NotOnOrAfter`/`InResponseTo` 防重放
    - 验证：`uv run pytest tests/unit/auth/test_saml_adapter.py -q`（先写会失败的用例覆盖有效签名、篡改签名、过期断言三种路径）
    - _需求：2.2, 2.4_
  - [ ] 3.4 登录成功后复用 `w3-04` 会话签发，i18n 与错误码补齐
    - 改动：接入既有会话签发流程；新增 `SAML_ASSERTION_INVALID` 到 `ErrorCode` 与 `_DEFAULT_STATUS` 末尾，补齐四份文案
    - 验证：`uv run pytest tests/unit/i18n -q`；`uv run pytest tests/integration -k "saml or sso" -q`

- [ ] 4. LDAP/AD 适配器（若行方选定 LDAP/AD）
  - [ ] 4.1 新增 LDAP 客户端封装与 `auth_backend` 配置三触点
    - 改动：新增 `src/octop/infra/auth/ldap/` 目录（客户端封装、连接池、TLS 配置）；`config.py` 新增 `auth_backend` 等键，改齐 `OctopConfig` dataclass 字段 + env 覆盖块 + `return OctopConfig(...)` 三处
    - 验证：`uv run pytest tests/unit/test_config.py -k ldap -q`
    - _需求：3.1_
  - [ ] 4.2 `UserManager.authenticate` 开 LDAP bind 分支
    - 改动：`infra/users/manager.py::UserManager.authenticate` 在本地 `verify_password` 前后新增 LDAP bind 逻辑；bind 失败返回统一鉴权失败错误，不透传具体原因；新增 `LDAP_BIND_FAILED` 到 `ErrorCode` 与 `_DEFAULT_STATUS` 末尾并补齐四份文案
    - 验证：`uv run pytest tests/unit/auth/test_ldap_backend.py -q`（先写会失败的用例覆盖 bind 成功、bind 失败、服务器不可达三种路径）；`uv run pytest tests/unit/i18n -q`
    - _需求：3.1, 3.2, 3.4_
  - [ ] 4.3 自动开户与属性→角色映射
    - 改动：LDAP bind 成功且本地用户不存在时，按 `auto_provision` 配置自动开户或拒绝；用户属性映射到 `w3-03` 已有角色体系
    - 验证：`uv run pytest tests/integration -k ldap -q`
    - _需求：3.3_

- [ ] 5. SM2 验签协作（若 IdP 要求国密签名，跨任务 2/3）
  - 改动：CAS/SAML 适配器的签名校验点调用 `p2-02` 暴露的验签接口（实施时先用 `rg` 在 `.kiro/specs/p2-02-kms-sm-crypto/design.md` 核对接口名与依赖是否已合入）
  - 验证：`uv run pytest tests/unit/auth -k sm2 -q`（若 `p2-02` 未合入，本任务标记阻塞，不得静默跳过签名校验）
  - _需求：4.1, 4.2_

- [ ] 6. 收尾：全绿门禁、文档同步
  - 改动：无新增业务代码；`CHANGELOG-intranet.md` 追加本 spec 条目；若新增 API 路由或响应字段，更新 `docs/api-intranet.md`
  - 验证：`make all`；如有前端改动，`cd dashboard && npx tsc -b && npm run lint`（若新增 vitest 用例，追加 `npm run test`）；`uv run pytest tests/unit/i18n -q` 确认 i18n 键集对等
  - _需求：1.1-1.5, 2.1-2.4, 3.1-3.4, 4.1, 4.2, 5.1, 5.2_
