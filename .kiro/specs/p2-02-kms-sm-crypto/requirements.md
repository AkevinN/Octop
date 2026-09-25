# 需求文档：密钥托管与国密

> spec：`p2-02-kms-sm-crypto` ｜ 波次：二期 ｜ 基线：`757fd12` ｜ 预估：约 39 人日
> 前置：`w3-05-credential-encryption`、`w3-04-session-and-password` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 引言

`w3-05` 已交付 `CryptoProvider` 接口（`src/octop/infra/utils/crypto/provider.py`）、信封格式（`suite_id` + `key_id` 自描述）、`local` 软件 provider，以及注册表中为 `kms`/`sdf` 预留但抛 `SECRET_KEY_UNAVAILABLE` 的占位键位；`crypto.provider`/`crypto.suite` 两个配置键也已就绪，一期只接受 `local`/`aes256gcm`。`w3-04` 已交付会话与短时令牌机制，`sign_token`/`decode_token` 固定用 `HS256`，`id_token.py` 的算法白名单固定 `RS256,ES256`；口令哈希固定 Argon2id。

本 spec 在这些接口之上补齐面向银行密评场景的能力：让 `crypto.provider` 支持 `kms`（行内密管平台 REST）与 `sdf`（GM/T 0018 加密机/密码卡）两种外部密钥托管后端；让 `crypto.suite` 支持国密 SM4/SM3 套件并保证切换前的 AES-GCM 旧密文仍可读；把 JWT 签名、OIDC ID Token 验签、口令哈希扩展到可选国密算法；提供启动期从密码平台取数据库口令/KMS 凭据注入环境变量的钩子；并对"Python 国密库是否满足密评'经检测的密码模块'"给出书面结论。

**范围内**：`infra/utils/crypto/` 下新增 `kms.py`（KMS REST provider）与 `sdf.py`（SDF ctypes provider）、新增 SM4/SM3/SM2 算法适配模块及其在 `local`/`kms`/`sdf` provider 中的套件切换逻辑、`crypto.suite=sm-gm` 相关配置扩展、启动期口令注入钩子（覆盖全部独立进程入口）、`api/deps.py` 的 JWT 签名算法可插拔化（在 `w3-04` 已交付的 `sign_token`/`decode_token` 签名上加算法参数）、`infra/auth/sso/id_token.py` 的 SM2 ID Token 验签分支、`infra/users/password.py` 的口令哈希双轨与惰性重哈希、密钥管理管理页与 `/api/admin/kms` 只读状态/自检/轮换接口、Python 国密库合规口径评估结论。

**范围外**：`CryptoProvider` 接口本身、信封编解码、`local` provider、四张业务表明文列加密、`SecretRepo` 改造——已由 `w3-05` 交付，本 spec 不重复实现，只新增 provider 与套件。会话表、令牌吊销、口令策略（长度/历史/复杂度）、登录模式——归 `w3-04`，本 spec 只在其已定的 `sign_token`/`decode_token`/`password.py` 接缝上加算法分支。验证码 fail-open 改造、图形验证码终态——归 `w3-01`。入站国密 TLS（TLCP）终结——明确划给前置国密网关，不在本 spec 代码范围内。密钥的强托管（HSM 强制、密钥永不出设备的完整合规证据链）与审计防篡改——归 `p2-03`；身份源（CAS/SAML/LDAP）适配——归 `p2-11`。

## 需求

### 需求 1：KMS REST 密钥托管后端

**用户故事：** 作为行内安全运维人员，我希望主密钥由行内密管平台通过 REST 接口托管、Octop 进程只做 wrap/unwrap，以便主密钥不落地本机磁盘。

#### 验收标准

1. 当 `crypto.provider=kms` 且配置了 `kms_endpoint`/`kms_key_id` 时，`init_crypto()` 应当构造 `KmsProvider` 并通过 mTLS 客户端证书 + 内网 CA 调用密管平台完成一次 `wrap`/`unwrap` 自检。
2. 如果 KMS 在启动阶段不可达或自检失败，那么进程应当以 `KMS_UNAVAILABLE` 明确失败退出并写入 `audit_log`（`action=kms.unwrap_failed`），不得降级为本地明文密钥。
3. 当运行期 KMS 调用超时或触发熔断阈值时，`KmsProvider` 应当在有效 TTL 内使用内存 DEK 缓存兜底，超出 TTL 后重新 unwrap。
4. `GET /api/admin/kms/status` 应当返回当前 provider、`suite_id`、`key_id`、自检结果与 KMS 连通性，且仅 `kms` 权限可访问。

### 需求 2：SDF 密码机/密码卡后端

**用户故事：** 作为行内密评合规负责人，我希望在具备加密机硬件的环境下，Octop 的密码运算可委派给经检测的密码模块，以便满足"使用经检测的密码模块"的密评口径。

#### 验收标准

1. 当 `crypto.provider=sdf` 且配置了 `sdf_library` 路径时，`init_crypto()` 应当通过 `ctypes` 加载该 GM/T 0018 动态库并建立会话句柄池。
2. 如果动态库加载失败或找不到指定路径，那么进程应当以 `CRYPTO_SUITE_UNSUPPORTED` 明确失败退出，不得静默回落到 `local` provider。
3. 在进程正常退出时，`SdfProvider` 应当释放全部已建立的会话句柄，不留资源泄漏。
4. 本 spec 应当在 `docs/adr/` 中给出"纯软件 SM4/SM3（经 `cryptography`）能否满足密评'经检测的密码模块'口径"的书面评估结论及适用边界，供行方决策 `local` 国密套件与 `sdf` 硬件后端的取舍。

### 需求 3：SM4/SM3 国密套件与旧密文兼容

**用户故事：** 作为运维人员，我希望能把加密套件从 AES-GCM 切到国密 SM4/SM3，且切换前写入的密文在切换后仍能正常解密，以便平滑过渡而不需要停机重加密全部存量数据。

#### 验收标准

1. 当 `crypto.suite=sm-gm` 时，`current_crypto().wrap()`/`wrap_text()` 应当使用 SM4-GCM（或 SM4-CBC + SM3-HMAC）加密新数据，且信封 `suite_id` 标识为国密套件。
2. 无论当前 `crypto.suite` 取值为何，`unwrap()`/`unwrap_text()` 都应当根据密文信封自带的 `suite_id` 选择对应算法解密，正确读出切换前用 AES-GCM 套件写入的旧密文。
3. `tests/unit/crypto/test_gm_vectors.py` 应当用 GB/T 32907（SM4）与 GM/T 0004（SM3）标准测试向量逐字节校验 provider 输出。
4. `run_self_test()` 在国密套件下应当额外执行 SM4/SM3 已知答案测试，结果供 `/api/admin/kms/status` 展示。

### 需求 4：JWT 签名与 OIDC ID Token 的国密算法窗口

**用户故事：** 作为安全合规负责人，我希望会话令牌签名与 OIDC ID Token 验签能够支持国密算法，同时不因一次切换让全部在线用户被强制登出。

#### 验收标准

1. 当 `crypto.jwt_alg` 配置为国密算法时，`sign_token()` 应当使用该算法签发新令牌；`decode_token()` 应当同时接受新算法与 `HS256` 两种签名，覆盖切换前签发、TTL 内尚未过期的旧令牌。
2. 如果 OIDC IdP 的 JWKS 条目 `kty`/`crv` 标识为 SM2，那么 `id_token.py` 的验签应当直接调用 provider 完成 SM2 验签，不经过 `jwt.PyJWK`；非 SM2 条目应当仍走既有 `RS256`/`ES256` 路径。
3. 在未配置国密算法样例（无行方提供的 SM2 JWKS/ID Token 样例）的情况下，SM2 验签分支应当保持关闭且不影响既有 `RS256`/`ES256` 登录路径。

### 需求 5：口令哈希双轨与启动期凭据注入钩子

**用户故事：** 作为运维人员，我希望口令哈希能够按需切到国密方案且存量用户无感升级，同时进程启动时能从行内密码平台自动取回数据库口令与 KMS 凭据，以便不在配置文件或环境文件里保存明文凭据。

#### 验收标准

1. 当 `password.py` 配置为国密哈希方案时，`hash_password()` 应当产出带算法前缀的国密哈希；`verify_password()` 应当按存量哈希前缀分派到对应算法完成校验。
2. 当用户使用旧算法（Argon2id）哈希成功登录时，系统应当返回"需要重哈希"标记，由调用方在登录成功后就地升级为当前配置的算法。
3. 当设置了 `OCTOP_SECRET_BOOTSTRAP_CMD`（或等效的密码平台调用配置）时，`load_boot_secrets()` 应当在 `server.py`、`cli/support/db.py`、`cli/commands/init.py`、`cli/commands/admin.py`、`cli/commands/backup.py` 五个独立进程入口的 `apply_env_file`/`load_config` 之前被调用一次，把取回的 `KEY=VALUE` 按白名单前缀注入 `os.environ`。
4. 该钩子应当始终保持幂等（重复调用零副作用）；在未配置任何密码平台来源时，应当立即返回且不产生任何副作用。

### 需求 6：密钥管理面板与错误码

**用户故事：** 作为行内安全管理员，我希望在管理后台看到当前密码套件、provider、密钥状态与自检结果，并能手动触发自检与主密钥轮换。

#### 验收标准

1. 当具备 `kms` 权限的管理员访问"安全防护 → 密钥管理"页时，页面应当展示当前 `crypto.provider`、`crypto.suite`、`key_id`、最近一次自检结果与 KMS/SDF 连通性。
2. 当管理员点击"轮换主密钥"并二次确认后，系统应当调用 `POST /api/admin/kms/rotate-master-key`，并把操作写入 `audit_log`。
3. 如果 `KmsProvider`/`SdfProvider` 初始化或调用失败，那么系统应当使用本 spec 新增的 `ErrorCode`（如 `KMS_UNAVAILABLE`、`KMS_KEY_NOT_FOUND`）并同批登记 `_DEFAULT_STATUS`、后端 `errors.*` 中英文案与 dashboard `apiErrors`，不得复用无关错误码掩盖故障原因。
4. 系统应当始终保证：缺失 `_DEFAULT_STATUS` 登记的新错误码不会被提交（由既有的 i18n 键集测试兜底）。
