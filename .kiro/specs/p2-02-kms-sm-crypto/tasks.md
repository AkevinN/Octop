# 实施计划：密钥托管与国密

> spec：`p2-02-kms-sm-crypto` ｜ 波次：二期 ｜ 基线：`757fd12` ｜ 预估：约 39 人日
> 前置：`w3-05-credential-encryption`、`w3-04-session-and-password` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

每个顶层任务完成后可独立提交；提交前运行任务内的验证命令。

- [ ] 1. 确认前置 spec 已合入并记录基线
  - 改动：确认 `w3-05-credential-encryption`（`CryptoProvider`/信封/`local` provider/`crypto.provider`/`crypto.suite`）与 `w3-04-session-and-password`（`sign_token`/`decode_token` 去默认 TTL 形态、`id_token.py::set_allowed_algorithms()`、口令策略字段）均已合入 `develop`；用 `rg` 在彼时代码里重新核实本文档"现状"节列出的符号位置（行号已漂移，以符号名重新定位）
  - 验证：`uv run pytest tests/unit/crypto tests/unit/keys -q` 全绿（确认 `w3-05` 基础设施可用）
  - _需求：全部_

- [ ] 2. 国密算法适配层：SM4/SM3/SM2
  - 改动：新增 `src/octop/infra/utils/crypto/gm.py`（SM4-GCM/CBC+SM3-HMAC、SM2 签验封装）；先写 `tests/unit/crypto/test_gm_vectors.py`（GB/T 32907、GM/T 0004 标准向量，此时应失败）再补实现
  - 验证：`uv run pytest tests/unit/crypto/test_gm_vectors.py -q`
  - _需求：3.1, 3.2, 3.3, 3.4_

- [ ] 3. `local`/`kms`/`sdf` provider 接入国密套件与解密自适配
  - 改动：`local.py`（`w3-05` 已建）与新增的 `kms.py`/`sdf.py` provider 按 `suite_id` 分派 `gm.py`；`unwrap`/`unwrap_text` 始终按密文信封 `suite_id` 选算法，与运行期 `crypto.suite` 无关
  - 验证：`uv run pytest tests/unit/crypto -q`（含旧 AES-GCM 密文在 `crypto.suite=sm-gm` 下仍可解密的用例）
  - _需求：3.1, 3.2_

- [ ] 4. KMS REST provider
  - 改动：新增 `src/octop/infra/utils/crypto/kms.py::KmsProvider`（mTLS `httpx.Client`、DEK 内存缓存、熔断、fail-closed 自检）；`registry.py` 里替换 `kms` 占位工厂；`config.py` 三触点追加 `kms_endpoint`/`kms_key_id`
  - 验证：`uv run pytest tests/unit/crypto/test_kms_provider.py tests/integration/test_kms_api.py::test_boot_fails_closed_when_kms_down -q`
  - _需求：1.1, 1.2, 1.3_

- [ ] 5. SDF 密码机/密码卡 provider
  - 改动：新增 `src/octop/infra/utils/crypto/sdf.py::SdfProvider`（ctypes 加载、会话句柄池、退出释放）；`registry.py` 替换 `sdf` 占位工厂；`config.py` 三触点追加 `sdf_library`；用 fake `.so` 桩覆盖单测，真实硬件联调按待行方确认项另行安排
  - 验证：`uv run pytest tests/unit/crypto/test_sdf_provider.py -q`
  - _需求：2.1, 2.2, 2.3_

- [ ] 6. JWT 签名算法窗口
  - 改动：`api/deps.py::sign_token`/`decode_token` 加 `alg` 参数（默认 `HS256` 不变）；国密套件下注册自定义 SM3-HMAC 算法；`config.py` 三触点追加 `jwt_alg`
  - 验证：`uv run pytest tests/unit/api/test_token_alg_switch.py tests/unit/api/test_jwt_auth_middleware.py -q`
  - _需求：4.1_

- [ ] 7. OIDC SM2 ID Token 验签
  - 改动：`infra/auth/sso/id_token.py` 在 `set_allowed_algorithms()` 注入点扩展国密算法名；`_signing_key`/`verify_id_token` 按 `kty`/`crv` 分派 SM2 分支（不经 `jwt.PyJWK`），无样例时保持关闭
  - 验证：`uv run pytest tests/unit/auth/test_id_token_sm2.py tests/unit/auth/test_sso_id_token.py -q`
  - _需求：4.2, 4.3_

- [ ] 8. 口令哈希双轨与惰性重哈希
  - 改动：`infra/users/password.py` 加 `PasswordHasherProtocol`、SM3 基 KDF 实现、`verify_password_ex()`（保留旧 `verify_password` 签名）；`config.py` 三触点追加 `password_hash`；`infra/users/manager.py::authenticate()` 改调 `verify_password_ex`，`needs_rehash` 时调 `UserRepo.set_password_hash`
  - 验证：`uv run pytest tests/unit/test_password.py tests/unit/users/test_manager.py -q`
  - _需求：5.1, 5.2_

- [ ] 9. 启动期凭据注入钩子
  - 改动：`infra/keys/bootstrap.py` 新增 `load_boot_secrets()`（幂等、默认关闭、白名单前缀注入）；在 `infra/server.py::start()`、`cli/support/db.py::open_cli_services`、`cli/commands/init.py`、`cli/commands/admin.py`、`cli/commands/backup.py`（该文件当前不调用 `apply_env_file`）五处调用点之前接入；`config.py` 三触点追加 `secret_bootstrap_cmd`
  - 验证：`uv run pytest tests/unit/crypto/test_bootstrap_hook.py -q`
  - _需求：5.3, 5.4_

- [ ] 10. 密钥管理面：错误码、权限、`/api/admin/kms` 路由
  - 改动：`infra/errors.py` 追加 `KMS_UNAVAILABLE`/`KMS_KEY_NOT_FOUND`/`CRYPTO_DECRYPT_FAILED`/`CRYPTO_SUITE_UNSUPPORTED` 及同批 `_DEFAULT_STATUS`；`i18n/{en,zh}.json`（或 `w0-04` overlay）`errors.*` 与 dashboard `apiErrors.*` 同步；`infra/users/permissions.py` 追加 `"kms"` 权限键并加入 `test_acl_gate_coverage.py::GATED_FILES`；新增 `api/routers/kms.py`（status/self-test/rotate-master-key/rewrap）并在 `app.py`/`openapi_meta.py` 挂载
  - 验证：`uv run pytest tests/unit/i18n -q tests/unit/api/test_acl_gate_coverage.py tests/integration/test_kms_api.py -q`
  - _需求：1.4, 6.2, 6.3, 6.4_

- [ ] 11. 前端密钥管理页
  - 改动：新增 `dashboard/src/api/modules/kms.ts`、`dashboard/src/pages/Settings/Kms/index.tsx`；`Settings/Security/index.tsx` 加 `kms` tab；`utils/permissions.ts` 加 `SECURITY_TAB_PERMISSIONS.kms`；`dashboard/src/locales/{en,zh}.json`（或 intranet overlay）补 `security.tabKms`、`kms.*` 文案与 `apiErrors` 4 个新码
  - 验证：`cd dashboard && npx tsc -b && npm run lint`
  - _需求：6.1_

- [ ] 12. 密评口径 ADR、文档与收尾
  - 改动：新增 `docs/adr/00X-gm-crypto-module-compliance.md`（Python 国密库合规口径评估结论）；更新 `docs/configuration.md`/`docs/api.md` 的 KMS 相关章节；`make all` 全绿；`cd dashboard && npx tsc -b && npm run lint`；更新 `CHANGELOG-intranet.md` 与 `docs/api-intranet.md`（新增 `/api/admin/kms/*`）
  - 验证：`make all`；`cd dashboard && npx tsc -b && npm run lint`
  - _需求：2.4_
