# 设计文档：密钥托管与国密

> spec：`p2-02-kms-sm-crypto` ｜ 波次：二期 ｜ 基线：`757fd12` ｜ 预估：约 39 人日
> 前置：`w3-05-credential-encryption`、`w3-04-session-and-password` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 概述

本 spec 是 `w3-05` `CryptoProvider` 体系的二期扩展：只新增 provider 模块（`kms`、`sdf`）与算法套件（SM4/SM3/SM2），不改动 `w3-05` 已交付的调用方（`SecretRepo`、四张业务表 codec、`sso/crypto.py` 等）。同时在 `w3-04` 已固定的会话令牌与口令模块上加算法可插拔分支。由于二期在一期全部落地后才启动，届时代码已发生较大变化，本文档只锚定当前基线（`757fd12`，`w3-05`/`w3-04` 均**尚未合入**）已验证的既有实现，作为"一期改动前的原始形态"参照；实施时改以一期落地后的代码重新定位，不依赖本文档的具体行号。

## 现状（基线 `757fd12`，一期改动前）

以下已在仓库核实存在，用于锚定"一期将如何改动它们、二期在此基础上再加什么"，实施时改以一期落地后的代码重新定位：

- `src/octop/infra/users/password.py`：`_HASHER = PasswordHasher()`（≈L10）、`hash_password()`（≈L35）、`verify_password()`（≈L41-43，返回 `bool`）。当前仅 Argon2id，无前缀分派——本 spec 需要的分派逻辑建立在 `w3-04` 之后。
- `src/octop/api/deps.py`：`sign_token()`（≈L28）在 ≈L44 硬编码 `algorithm="HS256"`；`decode_token()`（≈L47）在 ≈L49 硬编码 `algorithms=["HS256"]`。`w3-04`/`w3-05` 设计文档均已交接"JWT 签名算法与密钥派生归 `p2-02`"。
- `src/octop/infra/auth/sso/id_token.py`：`_ALLOWED_ALGORITHMS = ("RS256", "ES256")`（L11）、`_signing_key()`（L14，L32 处 `jwt.PyJWK.from_dict`）、`verify_id_token()`（L36，L50 处 `algorithms=`）。`w3-04` 会把算法集合改为 `set_allowed_algorithms()` 注入式，本 spec 在该注入点加 SM2 分支。
- `src/octop/infra/errors.py`：`class ErrorCode(StrEnum)`（L13），当前末项 `CONFIG_FILE_CORRUPT`（≈L112）；`_DEFAULT_STATUS`（L115 起）。新码追加在彼时末尾。
- `src/octop/infra/users/permissions.py`：`"captcha"` 条目在 ≈L207-215，`ALL_PERMISSION_KEYS`（L218）。`"kms"` 键追加在彼时末尾。
- `w3-05` 交付给本 spec 的接缝（已在其 design.md 中确认，非本 spec 实现）：`infra/utils/crypto/provider.py::CryptoProvider`（`key_id`/`suite_id`/`wrap`/`unwrap`/`wrap_text`/`unwrap_text`/`is_envelope`/`self_test`）、`registry.py::register_provider`/`build_provider`（`kms`/`sdf` 为占位）、`install_crypto`/`current_crypto`、`infra/keys/bootstrap.py::init_crypto`、`config.py` 的 `CryptoConfig`（`provider`/`suite`/`require_external_key`）。

## 方案

1. **Provider 扩展层**：在 `w3-05` 的 `registry.py` 占位位置新增 `kms.py`（`KmsProvider`，httpx mTLS 客户端、DEK 内存缓存、熔断）与 `sdf.py`（`SdfProvider`，ctypes 加载 GM/T 0018 动态库、会话句柄池），通过 `register_provider("kms", ...)`/`register_provider("sdf", ...)` 接入既有注册表，替换 `w3-05` 里抛 `SECRET_KEY_UNAVAILABLE` 的占位工厂。
2. **算法套件层**：新增 `gm.py`，基于 `cryptography.hazmat.primitives`（锁定版本 `algorithms.SM4`、`hashes.SM3`）实现 SM4-GCM/SM4-CBC+SM3-HMAC，并在 `local`/`kms`/`sdf` 三种 provider 内按 `suite_id` 分派；解密路径始终按密文信封自带的 `suite_id` 选择算法，与运行期 `crypto.suite` 配置无关，从而保证旧密文可读。SM2 用于 ID Token 验签，走独立签验封装（不复用 wrap/unwrap 接口）。
3. **JWT/OIDC/口令的算法分支**：在 `w3-04` 落地后的 `sign_token`/`decode_token`/`id_token.py`/`password.py` 接缝上加国密分支，均带默认值保持向后兼容，不改变既有 `RS256`/`ES256`/Argon2id 路径的默认行为。
4. **启动期凭据注入钩子**：新增 `infra/keys/bootstrap.py::load_boot_secrets()`（幂等、默认关闭），在 5 个独立进程入口的 `apply_env_file`/`load_config` 之前调用一次。
5. **管理面**：新增 `/api/admin/kms` 只读状态 + 自检 + 轮换接口与对应前端页面，复用 `w3-05` 已建立的信封/自检基础设施。
6. **密评口径评估**：产出 ADR，结论覆盖"纯软件国密实现 vs 经检测密码模块"的适用边界，供行方在 `local`(sm-gm) 与 `sdf` 之间选型。

## 组件与接口

| 路径 | 状态 | 要点 |
|---|---|---|
| `src/octop/infra/utils/crypto/kms.py` | 新增 | `KmsProvider`：实现 `CryptoProvider`；mTLS `httpx.Client`（内网 CA+超时+重试+熔断）；TTL DEK 缓存；主密钥不落盘 |
| `src/octop/infra/utils/crypto/sdf.py` | 新增 | `SdfProvider`：`ctypes.CDLL` 加载 GM/T 0018 库；会话句柄池；encrypt/decrypt/sign/verify/random；退出释放 |
| `src/octop/infra/utils/crypto/gm.py` | 新增 | SM4/SM3 适配（`cryptography` 的 `algorithms.SM4`、`hashes.SM3`）；SM4-GCM 用 `Cipher(SM4, modes.GCM)` 自封装；SM2 签验独立封装，import 失败抛 `CRYPTO_SUITE_UNSUPPORTED` |
| `src/octop/infra/utils/crypto/health.py` | 新增 | `run_self_test()`：国密算法已知答案测试 + KMS/SDF 连通性探测，供状态接口复用 |
| `src/octop/infra/keys/bootstrap.py`（`w3-05` 已建） | 修改（追加） | 新增 `load_boot_secrets()`：跑 `OCTOP_SECRET_BOOTSTRAP_CMD` 或调密码平台接口，白名单前缀注入 `os.environ`，模块级 `_done` 幂等，未配置零副作用 |
| `src/octop/infra/server.py` | 修改 | `start()` 中 `ensure_root()` 后、`apply_env_file()` 前插入 `load_boot_secrets()` |
| `src/octop/cli/support/db.py`、`cli/commands/{init,admin,backup}.py` | 修改 | 各自 `apply_env_file`/`load_config` 前插入 `load_boot_secrets()`；`backup.py` 无 `apply_env_file`，在 `load_config` 前插 |
| `src/octop/api/deps.py` | 修改 | `sign_token(..., alg="HS256")`；国密套件下注册 SM3-HMAC；`decode_token()` 接受 `[配置算法, "HS256"]` 双值覆盖旧令牌 |
| `src/octop/infra/auth/sso/id_token.py` | 修改 | `set_allowed_algorithms()`（`w3-04` 已建）扩展国密算法名；SM2 按 JWKS `kty`/`crv` 判定，直接调 provider 验签，不经 `jwt.PyJWK` |
| `src/octop/infra/users/password.py` | 修改 | `PasswordHasherProtocol` + 前缀分派；SM3 基 KDF；新增 `verify_password_ex()` 返回 `(bool, needs_rehash)`，旧 `verify_password()` 签名不变 |
| `src/octop/infra/users/manager.py` | 修改 | `authenticate()` 改调 `verify_password_ex`，`needs_rehash` 时调 `UserRepo.set_password_hash` 升级 |
| `src/octop/api/routers/kms.py` | 新增 | `GET /status`、`POST /self-test`、`POST /rotate-master-key`、`POST /rewrap`；均 `require_permission("kms")`，写 `audit_log` |
| `src/octop/api/app.py` | 修改 | 路由 import 块与 `_mount_routers` 追加 `_RouterMount(kms_router, "/api/admin/kms", ["kms"])`，参照既有 `tls_router`/`security_router` 挂法 |
| `src/octop/api/openapi_meta.py` | 修改 | `OPENAPI_TAGS` 追加 `{"name": "kms", ...}` |
| `src/octop/infra/users/permissions.py` | 修改 | `PERMISSIONS` 追加 `"kms"` 键（`page="security"`）；`tests/unit/api/test_acl_gate_coverage.py::GATED_FILES` 同批加入 `"routers/kms.py"` |
| `dashboard/src/api/modules/kms.ts`、`dashboard/src/pages/Settings/Kms/*` | 新增 | `kmsApi`（getStatus/selfTest/rotateMasterKey/rewrap）；密钥管理面板 |
| `dashboard/src/pages/Settings/Security/index.tsx`、`dashboard/src/utils/permissions.ts` | 修改 | 新增 `kms` tab 与 `SECURITY_TAB_PERMISSIONS.kms` |
| `docs/adr/00X-gm-crypto-module-compliance.md` | 新增 | 密评口径评估结论 |

## 数据模型

无。信封已带 `suite_id`/`key_id`（`w3-05` 交付），本 spec 不新增数据库列，也不新增 fork 迁移。

## 配置

`CryptoConfig`（`w3-05` 在 `src/octop/config.py` 建立，紧随 `TlsConfig` 之后）扩展以下字段，三触点均须改：① `OctopConfig`/`CryptoConfig` dataclass 追加字段；② env 覆盖块追加对应 `OCTOP_*`；③ `load_config()` 里 `return OctopConfig(...)` 的逐字段构造追加解析。

| 字段 | env | 默认 | 说明 |
|---|---|---|---|
| `crypto.kms_endpoint` | `OCTOP_KMS_ENDPOINT` | 空 | KMS REST 基址；`provider=kms` 时必填 |
| `crypto.kms_key_id` | `OCTOP_KMS_KEY_ID` | 空 | KMS 侧主密钥标识 |
| `crypto.sdf_library` | `OCTOP_CRYPTO_SDF_LIBRARY` | 空 | SDF 动态库路径；`provider=sdf` 时必填 |
| `crypto.jwt_alg` | `OCTOP_CRYPTO_JWT_ALG` | `HS256` | 会话 JWT 签名算法；国密取值需自定义注册 |
| `crypto.password_hash` | `OCTOP_PASSWORD_HASH` | `argon2id` | 口令哈希算法前缀，新增国密取值 |
| `crypto.secret_bootstrap_cmd` | `OCTOP_SECRET_BOOTSTRAP_CMD` | 空 | 启动期取口令命令；未设置则钩子零副作用 |

`crypto.provider` 取值扩展为 `local`/`kms`/`sdf`（枚举本身、默认值 `local` 由 `w3-05` 定义，本 spec 只扩展可选值集合与对应实现）；`crypto.suite` 取值扩展为 `aes256gcm`/`sm-gm`（同理）。

## 错误处理

新增 `ErrorCode`（追加到彼时枚举末尾，同批登记 `_DEFAULT_STATUS`，不按字母序插入）：

| ErrorCode | 建议状态码 | 场景 |
|---|---|---|
| `KMS_UNAVAILABLE` | 503 | 启动自检或运行期调用 KMS/SDF 失败 |
| `KMS_KEY_NOT_FOUND` | 404 | 请求的 `key_id` 在 KMS 侧不存在 |
| `CRYPTO_DECRYPT_FAILED` | 400 | 密文信封解密失败（区分"无 blob"与"有 blob 解不开"，后者不得吞成 `None`） |
| `CRYPTO_SUITE_UNSUPPORTED` | 501 | 配置的套件/provider 在当前环境不可用（如国密库缺失、SDF 库加载失败） |

同批更新：后端 `src/octop/i18n/{en,zh}.json` 的 `errors.*`（或 `w0-04` 建立的 intranet overlay）、dashboard `apiErrors.*`。

## 安全考虑

- 主密钥启动自检失败一律 fail-closed（`KMS_UNAVAILABLE` 明确退出并写 `audit_log`），不得降级为本地明文主密钥，呼应 D8 的密评前提。
- SDF 会话句柄池需在异常路径（包括未捕获异常导致的进程退出）也尽量释放；但 ctypes 层面的资源清理不可能 100% 覆盖，需在 ADR 中说明该限制。
- 国密算法实现锁定 `cryptography` 版本号（当前基线 49.0.0），版本升级需重跑 `test_gm_vectors.py`。
- `load_boot_secrets()` 只注入白名单前缀的环境变量，避免密码平台返回的任意键覆盖无关配置。
- 入站国密 TLS 明确不在本 spec 范围（由前置国密网关终结），代码与文档需固化该边界，不得在 `launch.py` 里尝试自定义 `SSLContext` 做 TLCP。

## 测试策略

- 单测：`uv run pytest tests/unit/crypto/test_gm_vectors.py tests/unit/crypto/test_bootstrap_hook.py tests/unit/api/test_token_alg_switch.py tests/unit/auth/test_id_token_sm2.py tests/unit/test_password.py -q`
- 集成：`uv run pytest tests/integration/test_kms_api.py -q`（含 fail-closed 启动场景）
- PG：以上用例在设置 `OCTOP_TEST_DATABASE_URL` 后重跑一遍，确认 KMS/SDF provider 与 PG 控制面组合无回归（`w0-02` 已合入为前提）。
- 前端：`cd dashboard && npx tsc -b`；`npm run lint`；密钥管理面板补充 `controlAdminPath.test.ts` 的 `kms` tab 权限断言。
- 密评材料：ADR 落地后，附一份可复现的 SM4/SM3 标准向量核对记录，供密评现场演示。

## 与其他 spec 的交接

- **依赖 `w3-05`**：`CryptoProvider` 接口、信封 `suite_id`/`key_id`、注册表 `kms`/`sdf` 占位键位、`crypto.provider`/`crypto.suite` 配置键，本 spec 只新增实现。
- **依赖 `w3-04`**：`sign_token`/`decode_token` 签名、`id_token.py` 的 `set_allowed_algorithms()` 注入点、`password.py` 口令策略字段，本 spec 在其上加算法分支。
- **交付给 `p2-03`**：`audit_log` 里 `kms.unwrap_failed`/轮换等密码操作事件，`p2-03` 加哈希链防篡改，不改写入点。
- **交付给 `p2-06`**：providers 响应体脱敏契约不变（`w3-05` 落库，本 spec 只切套件），`p2-06` 可直接加字段。
- **不属于本 spec**：入站国密 TLS（前置网关）；验证码 fail-open 与终态（`w3-01`）；`auth_sessions`/令牌吊销/口令策略（`w3-04`）；四表明文列加密/`SecretRepo`（`w3-05`）；强制硬件托管与完整密评证据链（本 spec 只给评估结论，正式配合归行方与 `p2-03`）。

## 风险与回滚

- SDF 硬件联调依赖行方动态库与测试环境，未到位则 `sdf.py` 只交付接口 + fake 桩单测，硬件联调顺延，是最大进度风险。
- SM2 样例缺失时需求 4 的 SM2 分支保持关闭，不阻塞其余交付。
- JWT/口令双算法窗口回滚只需改回默认配置并重启，无需数据迁移。
- 若密评要求硬件密码模块，`local` 的 `sm-gm` 需在正式环境禁用、强制走 `sdf`，由 `crypto.provider` 白名单落实，ADR 给出判定依据。

## 待行方确认

- D8：是否必须硬件 SDF 联调，还是纯软件 `sm-gm` 即可，决定约 5-9 人日是否发生。
- 密码模块合规口径：软件 SM4/SM3 是否可被密评接受，还是必须落在认证密码模块内——ADR 只给技术结论，最终口径需行方与测评机构确认。
- SM2 联调样例：行方 IdP 的 SM2 JWKS 与自签 ID Token 样例能否提供。
- 主密钥托管形态：KMS REST 接口文档、鉴权方式、可联调测试环境是否就绪。
