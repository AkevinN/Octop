# 实施计划：凭据加密与主密钥
> spec：`w3-05-credential-encryption` ｜ 波次：Wave 3 ｜ 基线：`757fd12` ｜ 预估：20 人日
> 前置：w0-01-fork-migration-namespace, w0-02-ci-gates, w0-04-fork-isolation-points, w1-01-security-hotfix, w1-05-saas-decoupling, w3-02-audit-baseline, w3-04-session-and-password ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

每个顶层任务完成后可独立提交；提交前运行任务内的验证命令。

- [ ] 1. 确认前置 spec 已合入并记录基线（0.5 人日）
  - 改动：确认 `src/octop/infra/db/fork_migrate.py::run_fork_migrations`、`src/octop/i18n/intranet/{en,zh}.json`、`src/octop/infra/voice/credentials.py`、`AuditContext` 存在；确认 `wecom_creds.py`、`fliggy.py`、`media_generation.py` 已删除；记录 `captcha/store.py` 是否仍存在，以及 `from cryptography` 的命中文件清单，写进 PR 描述。
  - 验证：`rg -l "from cryptography" src/octop && test -f src/octop/infra/db/fork_migrate.py && test -f src/octop/i18n/intranet/en.json && uv run pytest tests/unit -x -q`
  - _需求：1.5_

- [ ] 2. 错误码与 overlay 文案（0.5 人日）
  - 改动：`src/octop/infra/errors.py` 的 `ErrorCode` 末尾追加 `SECRET_KEY_UNAVAILABLE`、`SECRET_DECRYPT_FAILED`、`BACKUP_KEY_MISMATCH`，`_DEFAULT_STATUS` 末尾依次登记 503、500、400；后端 `src/octop/i18n/intranet/{en,zh}.json` 的 `errors.*`、dashboard `dashboard/src/locales/intranet/{en,zh}.json` 的 `apiErrors.*` 各加三键，并加 `setup.databasePasswordNotPersisted`、`backup.sealedKeyId` 两条提示。
  - 验证：`uv run pytest tests/unit/i18n -q`
  - _需求：1.3, 1.4, 7.2_

- [ ] 3. 加密原语包 `infra/utils/crypto/`（2 人日）
  - [ ] 3.1 先写失败用例
    - 改动：新增 `tests/unit/crypto/test_envelope.py`（二进制与文本往返、篡改、错域、错 AAD）、`tests/unit/crypto/test_registry.py`（`kms`、`sdf`、非 `aes256gcm` 套件报 `SECRET_KEY_UNAVAILABLE`；`current_crypto()` 未安装时报错）。
    - 验证：`uv run pytest tests/unit/crypto -q`（预期失败）
    - _需求：1.1, 1.2, 1.3, 1.4_
  - [ ] 3.2 实现
    - 改动：新增 `provider.py`（`CryptoProvider`）、`envelope.py`、`local.py`（`LocalProvider`，HKDF 分域子密钥）、`legacy.py`（`LegacyFernetReader`）、`registry.py`（`register_provider`、`build_provider`、`install_crypto`、`current_crypto`、`reset_crypto`）、`fields.py`（`SECRET_SENTINEL`、`is_sensitive_key`、`seal_json_secrets`、`open_json_secrets`、`redact_json_secrets`、`restore_sentinels`）。模块不得 import `octop.config`。
    - 验证：`uv run pytest tests/unit/crypto -q && make typecheck`
    - _需求：1.1, 1.2, 1.3, 1.4_

- [ ] 4. 配置键与主密钥解析（1.5 人日）
  - 改动：`src/octop/config.py` 三触点——新增 `CryptoConfig`（`TlsConfig` 之后）并在 `OctopConfig` 加 `crypto` 字段；env 覆盖块加 `OCTOP_CRYPTO_PROVIDER`、`OCTOP_CRYPTO_SUITE`、`OCTOP_MASTER_KEY_FILE`、`OCTOP_CRYPTO_REQUIRE_EXTERNAL_KEY`；`return OctopConfig(...)` 加 `crypto=_parse_crypto_section(...)`；第三触点由 `w1-02` 的 `tests/unit/test_config_touchpoints.py` 自动覆盖，另在 `tests/unit/test_config.py` 加四个 env 覆盖用例。`src/octop/infra/utils/paths.py::PathLayout` 加 `secrets_dir`、`master_key_file`、`ensure_secrets_dir`。新增 `src/octop/infra/keys/master_key.py::resolve_master_key` 与 `bootstrap.py::init_crypto`。先写 `tests/unit/crypto/test_master_key.py`：env 优先且不建文件、外部文件、自动生成（`posix_only` 断言 0o600 / 0o700）、强制外部密钥缺失或仅在 env 文件中时报错。
  - 验证：`uv run pytest tests/unit/crypto/test_master_key.py tests/unit/test_config_touchpoints.py tests/unit/test_config.py -q && make typecheck`
  - _需求：2.1, 2.2, 2.3, 2.4, 1.4_

- [ ] 5. env 文件不覆盖进程环境（0.5 人日）
  - 改动：先在 `tests/unit/test_env_file.py` 加 `test_apply_env_file_does_not_override_process_env` 与 `override=True` 用例；`src/octop/infra/utils/env_file.py::apply_env_file` 加 `override: bool = False`（默认 `os.environ.setdefault`），返回本次新设置的键集供 `init_crypto` 判断来源；`apply_env_file_replace` 不变。调用点 `infra/server.py::start`、`cli/support/db.py::open_cli_services`、`cli/commands/init.py`、`cli/commands/admin.py::rotate_jwt_secret` 显式传 `override=False`。
  - 验证：`uv run pytest tests/unit/test_env_file.py tests/integration/test_envs_api.py -q`
  - _需求：9.1, 9.2, 9.3_

- [ ] 6. SecretRepo 信封化与服务装配（1.5 人日）
  - 改动：先写 `tests/unit/db/test_secret_repo_codec.py`（带 codec 写入为信封、读回原值；不带 codec 与基线一致；`rotate` 对不存在的键 upsert），并在 `tests/unit/db/test_repo_secret_audit.py::test_secret_rotate` 补 upsert 断言。`src/octop/infra/db/repos/secrets.py::SecretRepo` 加 `codec`、`require_codec`、`get_raw`、`list_keys`、`delete`，`rotate` 改 upsert。`src/octop/infra/db/services.py`：`RepoBundle.from_pool(db, crypto=None)`、`SharedServices.crypto`、`build_shared_services(..., crypto=None)` 取 `crypto or current_crypto()`。新增 `tests/support/crypto.py::make_test_provider`，`tests/conftest.py` 加 autouse fixture 安装 / 复位。
  - 验证：`uv run pytest tests/unit/db tests/unit/test_langfuse_settings.py -q`
  - _需求：3.1, 3.2, 3.4_

- [ ] 7. 启动与 CLI 入口接线（1 人日）
  - 改动：`src/octop/infra/server.py::start` 在 `load_config` 之后、`build_shared_services` 之前调 `init_crypto`，之后调 `backfill_all`；`bind_control_plane` 复用同一 provider；`src/octop/infra/agents/manager.py::replace_persistence` 只加一行 codec 断言。`cli/support/db.py::open_cli_services`、`cli/commands/init.py`、`cli/commands/admin.py::rotate_jwt_secret`（`SecretRepo(db, codec=...)`）、`cli/commands/backup.py` 在建库前调 `init_crypto`。新增用例：rebind 后 `LangfuseSettingsStore`、`ConnectorService` 的 `secret_repo.codec` 为当前 provider；`admin rotate-jwt-secret` 后 `jwt` 行为信封；强制外部密钥缺失时 `start()` 抛错。
  - 验证：`uv run pytest tests/unit/agents tests/unit/cli tests/integration/test_setup_database.py -q`
  - _需求：2.4, 3.2, 3.3, 3.4, 3.5_

- [ ] 8. 既有实现收敛（1.5 人日）
  - 改动：`src/octop/infra/connectors/crypto.py` 与 `src/octop/infra/auth/sso/crypto.py` 改用 `repo.require_codec()`（连接器二进制载体、SSO 文本载体），无魔数时经 `LegacyFernetReader` 读旧值；删除 `Fernet` 导入。`src/octop/infra/auth/captcha/store.py`（若存在）删除 `InvalidToken` 导入，`_decode_secret` 改捕获 `OctopError`。改写 `tests/unit/auth/test_sso_crypto.py`（跨域不可解、旧 Fernet 可读）、`tests/unit/auth/test_captcha_store.py`、`tests/unit/connectors/test_custom_mcp.py`、`tests/unit/test_langfuse_settings.py`（`langfuse_secret_key` 行为信封）。新增 `tests/unit/crypto/test_single_crypto_entrypoint.py`。
  - 验证：`uv run pytest tests/unit/auth tests/unit/connectors tests/unit/crypto tests/unit/test_langfuse_settings.py -q`
  - _需求：1.5, 4.1, 4.2, 4.3, 4.4, 3.5_

- [ ] 9. 明文列加密（2.5 人日）
  - [ ] 9.1 先写集成用例
    - 改动：新增 `tests/integration/test_secret_at_rest.py`：经 API 写入五个探针后扫描 SQLite 原始字节；storage / channel 的 GET 返回哨兵，哨兵回写后密文不变、新值后密文变化；PG 下复用同一用例。
    - 验证：`uv run pytest tests/integration/test_secret_at_rest.py -q`（预期失败）
    - _需求：5.1, 5.4, 5.5_
  - [ ] 9.2 repo 层封装
    - 改动：`src/octop/infra/db/repos/providers.py`（`api_key`、`extra_json` 敏感键）、`voice_providers.py`（`api_key`、`extra_json` 敏感键）、`backends.py`（`access_key`、`secret_key`、`config_json` 敏感键）、`channels.py`（`config_json` 敏感键）加 `codec`；写方法封装，读方法在 `from_row` 后用 `dataclasses.replace` 解封，非 `oce1:` 值原样返回。`src/octop/infra/voice/credentials.py` 的判定委托 `fields.is_sensitive_key`。
    - 验证：`uv run pytest tests/unit/db tests/unit/gateway tests/integration/test_providers_api.py -q`
    - _需求：5.2, 5.3_
  - [ ] 9.3 响应脱敏与哨兵还原
    - 改动：`src/octop/api/routers/storage_backends.py::_row_to_dict` 的 `config_json` 与 `api/routers/channels.py::_row_to_detail` 的 `config` 用 `redact_json_secrets`；创建 / 更新路径与 `patch_channel` 用 `restore_sentinels`。
    - 验证：`uv run pytest tests/integration/test_secret_at_rest.py -q`
    - _需求：5.1, 5.4, 5.5_

- [ ] 10. 存量回填与水位表（2 人日）
  - 改动：新增 `src/octop/infra/db/migrations/forkNNN_crypto_state.sql` 与 `.pg.sql`；新增 `src/octop/infra/keys/backfill.py::backfill_all`、`pending_count`。新增 `tests/unit/keys/test_backfill.py`：用 1.0.1 形态的库（明文 `jwt`、Fernet 的 `connector_fernet` / `sso_fernet`、明文 `providers.api_key`）回填后全部为信封、两个 Fernet 行被删除、二次执行零改写；在第二批注入异常后重跑能续上且无双重加密；回填后 `secrets` 每行以魔数开头。
  - 验证：`uv run pytest tests/unit/keys/test_backfill.py tests/unit/db -q`
  - _需求：2.5, 4.1, 5.3, 6.1, 6.2_

- [ ] 11. 离线轮换 CLI（1.5 人日）
  - 改动：新增 `src/octop/infra/keys/rotate.py::rotate_master` 与 `src/octop/cli/commands/keys.py`（`status`、`rewrap`、`rotate-master --new-key-file`），在 `src/octop/cli/registry.py` 的 `COMMANDS` 注册 `keys`；轮换经 `AuditRepo.write` 记 `secret.master_rotate`。新增 `tests/unit/keys/test_rotate.py` 与 `tests/unit/cli/test_keys_cmd.py`：旧钥不可解、新钥可解、审计 payload 无密钥材料、`status` 输出字段齐全。
  - 验证：`uv run pytest tests/unit/keys tests/unit/cli/test_keys_cmd.py -q`
  - _需求：6.3, 6.4_

- [ ] 12. 备份包加密（2 人日）
  - 改动：新增 `src/octop/infra/backup/archive_crypto.py`；`src/octop/infra/backup/system_archive.py`（`create_system_backup` 输出经 `seal_archive`、文件名改 `.octbk`、`_extract_archive` 先 `peek_sealed_header` 校验 key_id、恢复时 `SecretRepo(pool, codec=...)`）；`store.py` 的 `_BACKUP_SUFFIXES`、`normalize_backup_filename` 文案、`peek_backup_contents`；`auto.py` 的自动备份文件名映射；`api/routers/backup.py` 与 `cli/commands/backup.py` 的临时名与帮助文案；`dashboard/src/pages/Settings/BackupRestore/index.tsx` 的 `accept` 加 `.octbk`。新增 `tests/unit/backup/test_archive_crypto.py`，更新 `test_system_archive.py`、`test_store.py`、`test_snapshot.py`，保留一个旧 `.tar.gz` 只读用例。
  - 验证：`uv run pytest tests/unit/backup tests/integration -k backup -q`
  - _需求：7.1, 7.2, 7.3, 7.4_

- [ ] 13. 数据库口令不落盘（1 人日）
  - 改动：`src/octop/infra/db/rebind.py::persist_database_config` 不写 `password`，写 `url` 前去掉口令；`src/octop/config.py::parse_database_config` 读到旧 `password` 时记弃用警告（不含口令）；`src/octop/api/routers/setup.py::apply_database` 响应加 `password_persisted`；`dashboard/src/pages/Setup/steps/DatabaseStep.tsx` 在口令项下展示 overlay 提示。`tests/integration/test_setup_database.py` 新增：带 `?sslmode=require` 的 DSN 与离散字段两种提交后 `config.json` 无口令；PG 下仅经 `OCTOP_DATABASE_PASSWORD` 注入仍可重启绑定。
  - 验证：`uv run pytest tests/integration/test_setup_database.py tests/unit/test_config.py -q`
  - _需求：8.1, 8.2, 8.3_

- [ ] 14. 收尾（1 人日）
  - 改动：`make all` 全绿；前端检查；PG 本地复现；`CHANGELOG-intranet.md` 记录主密钥外置、升级即回填、备份改 `.octbk`、口令不落盘、env 覆盖语义反转；`docs/api-intranet.md` 记录 `POST /api/setup/database` 的 `password_persisted`、storage / channel 的哨兵语义、备份接口后缀；清理本 spec 引入的孤儿符号。
  - 验证：`make all && cd dashboard && npx tsc -b && npm run lint && cd .. && OCTOP_TEST_DATABASE_URL=postgresql://octop:octop@localhost:5432/octop_test uv run pytest tests/integration/test_secret_at_rest.py tests/integration/test_setup_database.py -q`
  - _需求：5.5, 8.3, 9.3_
