# 设计文档：凭据加密与主密钥
> spec：`w3-05-credential-encryption` ｜ 波次：Wave 3 ｜ 基线：`757fd12` ｜ 预估：20 人日
> 前置：w0-01-fork-migration-namespace, w0-02-ci-gates, w0-04-fork-isolation-points, w1-01-security-hotfix, w1-05-saas-decoupling, w3-02-audit-baseline, w3-04-session-and-password ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 概述

**结论：** 加密原语放在 `infra/utils/crypto/`（repos 层允许 import utils），主密钥解析、回填、轮换这类需要读配置的逻辑放在新的领域包 `infra/keys/`。一期只有一个主密钥，按域用 HKDF 派生子密钥（**统一主密钥 + 分域子密钥**，不存独立 DEK）。`SecretRepo` 作为加密器的载体：持有 `secret_repo` 的一切调用方（SSO、验证码、连接器、Langfuse、JWT）不改签名就能拿到 provider。明文列用文本信封原地替换，不加列；唯一的表结构变更是一张 `crypto_state` 水位表，走 fork 迁移。

关键决策：

| 决策 | 选择 | 理由 |
|---|---|---|
| per-domain DEK 还是统一 DEK | 统一主密钥，HKDF 按域派生子密钥（`secrets`、`connector`、`sso`、`field`、`backup`） | 保留 `test_sso_crypto.py` 的跨域隔离语义；轮换只换一个根；不引入 KEK/DEK 两层（二期 KMS 时由 `p2-02` 在 provider 内部实现 wrap DEK） |
| 明文列加密方式 | 原 TEXT 列写文本信封 `oce1:<base64url>` | 不改 DDL，不产生新旧两列的双份真相；非 `oce1:` 前缀即存量明文，天然幂等 |
| 解密落点 | repo 方法在 `from_row` 之后用 `dataclasses.replace` 重建行 | `from_row` 是 frozen dataclass 的 classmethod，拿不到 codec |
| JWT 签名密钥 | 保留 `secrets.jwt` 行，由 `SecretRepo` 的 codec 以 `secrets` 域封装 | "由主密钥保护"即可满足；六处 `secret_repo.get("jwt")` 零改动；密钥派生与 SM3-HMAC 归 `p2-02` |
| 回填位置 | `infra/keys/backfill.py`，在 `build_shared_services` 之后显式调用 | `run_migrations(db)` 单参且早于服务构建，拿不到 provider |
| env 文件 | 不加密，只改覆盖语义 | docker 沙箱把 env 文件路径交给容器运行时解析 |

## 现状

- `src/octop/infra/connectors/crypto.py`：`_FERNET_KEY = "connector_fernet"`（≈L12），`_get_fernet`（≈L15）用 `repo.get_or_create` 把 Fernet 密钥写进 `secrets` 表；`encrypt_credentials(repo, payload)`（≈L20）、`decrypt_credentials(repo, blob)`（≈L25）。调用方 `infra/connectors/service.py`（≈L105、≈L117）。
- `src/octop/infra/auth/sso/crypto.py`：`_FERNET_KEY = "sso_fernet"`（≈L9），`encrypt_secret(secret_repo, plain) -> bytes`（≈L17）、`decrypt_secret`（≈L22）。调用方 `infra/auth/sso/service.py`（≈L153、≈L420）；feishu / wecom / dingtalk 适配器已由 `w1-05` 删除。
- `src/octop/infra/auth/captcha/store.py`：`from cryptography.fernet import InvalidToken`（≈L10），`_decode_secret`（≈L48）用 `except (InvalidToken, ValueError)` 吞掉失败（≈L53），写侧 `encrypt_secret(...).decode("ascii")`（≈L329、≈L334）依赖 ASCII 返回值。
- `src/octop/infra/agents/langfuse.py`：`_SECRET_KEY = "langfuse_secret_key"`（≈L23），`save` 中 `secret_key.encode("utf-8")`（≈L123）明文写入，读侧 `decode("utf-8")`（≈L144、≈L165）。
- `src/octop/infra/db/repos/secrets.py`：`SecretRepo.__init__(db)`（≈L12）；`rotate`（≈L36）只有 `UPDATE`（≈L39），行不存在时静默不生效。`cli/commands/admin.py::rotate_jwt_secret`（≈L106）在 ≈L121 调 `SecretRepo(db).rotate("jwt", ...)`。
- JWT：`infra/server.py::_ensure_jwt_secret`（≈L583）`get_or_create("jwt", os.urandom(32))`，调用点 ≈L328、≈L355；读取点 `api/deps.py`（≈L131、≈L164）、`api/routers/auth.py`（≈L109）、`auth_oidc.py`（≈L69）、`invites.py`（≈L148）、`setup.py`（≈L363）。
- 明文列：`ProviderRow`（`repos/providers.py` ≈L24，`api_key` ≈L29、`extra_json` ≈L30，`from_row` ≈L38）；`VoiceProviderRow`（`repos/voice_providers.py` ≈L21，`from_row` ≈L35，`extra_json` ≈L28）；`BackendRow`（`repos/backends.py` ≈L19，`access_key` ≈L24、`secret_key` ≈L25、`config_json` ≈L28）；`ChannelRow`（`repos/channels.py` ≈L12，`config_json` ≈L19）。`infra/backend/adapter.py` 从 `config_json` 取 `connection_string`（≈L127）与 `api_key`（≈L155）。
- 服务装配：`infra/db/services.py::RepoBundle.from_pool`（≈L66）在 ≈L73/74/80/84/89 构造 Provider / Channel / Secret / Backend / VoiceProvider 五个 repo；`build_shared_services(*, db, paths, config)`（≈L203）无加密参数。`infra/agents/manager.py::replace_persistence`（≈L390）用 `repos.secret_repo` 重建 `LangfuseSettingsStore` 与 `ConnectorService`。
- 响应体：`api/routers/storage_backends.py::_row_to_dict`（≈L64）在 ≈L81 原样返回 `config_json`；`api/routers/channels.py::_row_to_detail`（≈L93）在 ≈L98 原样返回 `config`，`patch_channel`（≈L179）。哨兵约定 `api/routers/envs.py::_SECRET_SENTINEL = "********"`（≈L28）。
- 数据库口令：`infra/db/rebind.py::persist_database_config`（≈L30）写 `password`（≈L50、≈L60），并在 url 含 `?` 时写 `section["url"]`（≈L53），url 内嵌口令。`config.py::_apply_database_env`（≈L374）读 `OCTOP_DATABASE_PASSWORD`（≈L390），`_parse_database_url`（≈L295）。
- env 文件：`infra/utils/env_file.py::apply_env_file`（≈L87）无条件 `os.environ[key] = value`（≈L91）；`apply_env_file_replace`（≈L95）。调用点：`server.py` ≈L292、`cli/support/db.py` ≈L24、`cli/commands/init.py` ≈L80、`cli/commands/admin.py` ≈L117；`cli/commands/backup.py` 不调用。`infra/backend/docker_spec.py::inject_docker_global_environment`（≈L81）把 env 文件路径写入 `environment_file`（≈L90）。
- 备份：`infra/backup/system_archive.py` 以 `"w:gz"`（≈L283）写 `octop-backup-*.tar.gz`（≈L89），恢复时 `SecretRepo(pool).get_or_create("jwt", ...)`（≈L573）；`infra/backup/snapshot.py::capture_jwt_secret_from_pool`（≈L317）用裸 SQL；`infra/backup/store.py::_BACKUP_SUFFIXES`（≈L18）只认 `.tar.gz`、`.tgz`；dashboard `BackupRestore/index.tsx` 的 `accept`（≈L491）同。
- `from cryptography` 现有 7 个文件，`w1-05` 删除 `wecom_creds.py`、`fliggy.py` 后剩 5 个。
- `infra/utils/paths.py::PathLayout`（≈L11）没有 `secrets` 目录；README 所说的 `~/.octop/secrets/` 不存在（steering §6）。
- `infra/errors.py`：`ErrorCode`（≈L13），`_DEFAULT_STATUS`（≈L115），`OctopError.__post_init__`（≈L225）对它无保护下标。

## 方案

1. **原语层（`infra/utils/crypto/`，新增）。** `CryptoProvider` Protocol、信封编解码、local provider、旧 Fernet 只读解码、进程级 `install_crypto` / `current_crypto`、敏感键判定与字段助手。不 import `octop.config`。
2. **领域层（`infra/keys/`，新增）。** `master_key.py` 按三级顺序解析主密钥并生成 key_id；`bootstrap.py::init_crypto(config, paths, *, env_file_keys)` 构建 provider、执行自检并 `install_crypto`；`backfill.py` 做幂等回填与重封；`rotate.py` 做离线轮换。
3. **入口接线。** `OctopServer.start()` 在 `apply_env_file` 与 `load_config` 之后、`build_shared_services` 之前调 `init_crypto`；`build_shared_services` 之后调 `backfill_all(services)`。`bind_control_plane` 与 rebind 走同一 provider。CLI 的 `open_cli_services`、`init`、`admin rotate-jwt-secret`、`backup` 各自在建库前调 `init_crypto`。
4. **SecretRepo 载体。** `SecretRepo(db, codec=None)`；`codec` 非空时写入走 `wrap(domain="secrets", aad=b"secrets:"+k)`，读取时有魔数则解封、无魔数原样返回（待回填）。`RepoBundle.from_pool(db, crypto=None)` 把 provider 交给五个 repo。`build_shared_services(..., crypto=None)` 取 `crypto or current_crypto()`，后者未安装即抛 `SECRET_KEY_UNAVAILABLE`。测试由 `tests/conftest.py` 的 autouse fixture 安装固定测试密钥的 provider。
5. **收敛。** `connectors/crypto.py` 与 `auth/sso/crypto.py` 保留函数名与第一参数类型 `SecretRepo`，内部改用 `repo.require_codec()`；连接器用二进制载体（`credential_blob` 是 BLOB），SSO 用文本载体。识别不到信封魔数时回落 `LegacyFernetReader`，用 `secrets` 表中残留的 `connector_fernet` / `sso_fernet` 解旧值。`captcha/store.py`（若经 `w1-05`、`w3-01` 后仍存在）改捕获 `SECRET_DECRYPT_FAILED`，不再 import `InvalidToken`。Langfuse 无需改代码：它经 `SecretRepo` 读写，codec 自动生效。
6. **明文列。** 四个 repo 的写方法把敏感值换成 `wrap_text(domain="field", aad="<table>:<column>:<name或id>")`；JSON 列只加密敏感子键（判定规则与 `w1-01` 的 `infra/voice/credentials.py` 相同，规则下沉到 `infra/utils/crypto/fields.py::is_sensitive_key`，`w1-01` 模块改为委托调用）。storage / channel 的 GET 把敏感子键替换为 `SECRET_SENTINEL`，PATCH 遇哨兵还原库内值。
7. **回填。** `backfill_all(services)` 按表分批（每批 200 行、独立事务），水位写 `crypto_state`；已是 `oce1:` 或魔数开头的值跳过。全部完成后删除 `connector_fernet`、`sso_fernet` 行。
8. **轮换。** `octop keys rotate-master --new-key-file` 只在离线 CLI 可用：用旧、新两把密钥构建双钥 provider，逐表 unwrap→wrap，水位续跑，完成后更新 `crypto_state.active_key_id` 并提示运维替换外部密钥；通过 `w3-02` 的 `AuditRepo.write`（`AuditContext` 的 `actor_kind="cli"`）记 `secret.master_rotate`。
9. **备份。** `domain="backup"` 子密钥分块 AES-GCM 流式封装（块序号入 AAD），头部 `OCTOPBK1` + key_id；恢复前先比对 key_id，不符即 `BACKUP_KEY_MISMATCH`；无魔数的旧包按 tar 读。
10. **口令与 env。** `persist_database_config` 不写口令（含 url 内嵌口令）；`apply_env_file` 默认不覆盖。

## 组件与接口

其余修改点（收敛、口令、env、备份、路由、CLI、前端）的文件与符号见 tasks.md，下表只列新增模块与签名有变的接口。

| 文件 | 类型 | 内容 |
|---|---|---|
| `src/octop/infra/utils/crypto/provider.py` | 新增 | `class CryptoProvider(Protocol)`：`key_id: str`、`suite_id: int`、`wrap(plaintext: bytes, *, domain: str, aad: bytes = b"") -> bytes`、`unwrap(blob: bytes, *, domain: str, aad: bytes = b"") -> bytes`、`wrap_text(plaintext: str, *, domain: str, aad: str = "") -> str`、`unwrap_text(text: str, *, domain: str, aad: str = "") -> str`、`is_envelope(value: bytes | str) -> bool`、`self_test() -> None` |
| `src/octop/infra/utils/crypto/envelope.py` | 新增 | `MAGIC = b"OCE1"`、`TEXT_PREFIX = "oce1:"`；`encode(suite_id, key_id, nonce, ct) -> bytes`、`decode(blob) -> Envelope` |
| `src/octop/infra/utils/crypto/local.py` | 新增 | `LocalProvider(master_keys: Mapping[str, bytes], active_key_id: str)`：AES-256-GCM，子密钥 `HKDF-SHA256(master, info=b"octop/"+domain)`；多钥只用于轮换期解封 |
| `src/octop/infra/utils/crypto/registry.py` | 新增 | `register_provider(name, factory)`、`build_provider(name, **kw)`；内置 `local`，`kms` / `sdf` 为抛 `SECRET_KEY_UNAVAILABLE` 的占位；`install_crypto(p)`、`current_crypto() -> CryptoProvider`、`reset_crypto()`（测试用） |
| `src/octop/infra/utils/crypto/fields.py` | 新增 | `SECRET_SENTINEL = "********"`、`is_sensitive_key(name) -> bool`、`seal_json_secrets(raw, provider, aad) -> str`、`open_json_secrets(raw, provider, aad) -> str`、`redact_json_secrets(raw) -> dict`、`restore_sentinels(new, old) -> dict` |
| `src/octop/infra/keys/__init__.py`、`master_key.py` | 新增 | `resolve_master_key(config: CryptoConfig, paths: PathLayout, *, env_file_keys: frozenset[str]) -> tuple[bytes, str]`（密钥, key_id） |
| `src/octop/infra/keys/bootstrap.py` | 新增 | `init_crypto(config: OctopConfig, paths: PathLayout, *, env_file_keys: frozenset[str] = frozenset()) -> CryptoProvider` |
| `src/octop/infra/keys/backfill.py` | 新增 | `backfill_all(services: SharedServices) -> BackfillReport`、`pending_count(services) -> int` |
| `src/octop/infra/keys/rotate.py` | 新增 | `rotate_master(services, new_key: bytes) -> str`（返回新 key_id） |
| `src/octop/infra/backup/archive_crypto.py` | 新增 | `seal_archive(src: Path, dest: Path, provider)`、`open_sealed_archive(path, provider) -> IO[bytes]`、`peek_sealed_header(path) -> SealedHeader | None` |
| `src/octop/cli/commands/keys.py` | 新增 | `keys status` / `keys rewrap` / `keys rotate-master --new-key-file` |
| `src/octop/infra/utils/paths.py` | 修改 | `PathLayout.secrets_dir`、`master_key_file`、`ensure_secrets_dir()`（POSIX 下 0o700） |
| `src/octop/infra/db/repos/secrets.py` | 修改 | `SecretRepo(db, codec=None)`、`codec` 属性、`require_codec()`、`rotate` 改 upsert、`list_keys()`、`delete(k)`、`get_raw(k)` |
| `src/octop/infra/db/repos/{providers,voice_providers,backends,channels}.py` | 修改 | 构造函数加 `codec=None`；写方法封装、读方法解封 |
| `src/octop/infra/db/services.py` | 修改 | `RepoBundle.from_pool(db, crypto=None)`；`SharedServices.crypto`；`build_shared_services(*, db, paths, config, crypto=None)` |
| `src/octop/infra/server.py` | 修改 | `start()` 接线 `init_crypto` 与 `backfill_all`；`apply_env_file(..., override=False)` |
| `src/octop/infra/agents/manager.py` | 修改 | `replace_persistence` 仅新增一行 `assert repos.secret_repo.codec is not None`（热点文件只留单行） |

## 数据模型

`forkNNN_crypto_state.sql` 与 `forkNNN_crypto_state.pg.sql`（号不预占）：

```sql
CREATE TABLE IF NOT EXISTS crypto_state (
  k TEXT PRIMARY KEY,          -- 'active_key_id' | 'suite' | 'backfill:<table>' | 'rotate:<table>'
  v TEXT NOT NULL,
  updated_at INTEGER NOT NULL
);
```

- 不给 `secrets` 或四张业务表加列：信封自带 `suite_id` 与 `key_id`，加列会产生双份真相。
- 回填在 Python 中完成（需要主密钥），不登记 `_FORK_PY_STEPS`。
- 不改 `_schema_version`，不改 `assert v == 15` 类断言。

## 配置

| 键 | env | 默认 | 说明 |
|---|---|---|---|
| `crypto.provider` | `OCTOP_CRYPTO_PROVIDER` | `local` | 一期仅 `local`；`kms` / `sdf` 占位 |
| `crypto.suite` | `OCTOP_CRYPTO_SUITE` | `aes256gcm` | 一期仅此值；`p2-02` 加 SM4 |
| `crypto.master_key_file` | `OCTOP_MASTER_KEY_FILE` | `""` | 外部密钥文件路径 |
| `crypto.require_external_key` | `OCTOP_CRYPTO_REQUIRE_EXTERNAL_KEY` | `false` | 真时禁止自动生成与 env 文件来源 |

三触点（`src/octop/config.py`）：① 新增 `@dataclass class CryptoConfig`（紧随 `TlsConfig` ≈L77 之后），`OctopConfig`（≈L125）加字段 `crypto: CryptoConfig`；② env 覆盖块加上述四个 `OCTOP_*`；③ `return OctopConfig(...)`（≈L592）加 `crypto=_parse_crypto_section(raw.get("crypto"))`，与 `tls=_parse_tls_section(...)`（≈L613）同形。`OCTOP_MASTER_KEY` **只从进程环境读取**，不进 `OctopConfig`、不写 `config.json`。第三触点由 `w1-02` 的 `tests/unit/test_config_touchpoints.py` 自动校验；本 spec 在 `tests/unit/test_config.py` 补 env 覆盖用例。

## 错误处理

| ErrorCode | `_DEFAULT_STATUS` | 场景 |
|---|---|---|
| `SECRET_KEY_UNAVAILABLE` | 503 | 主密钥缺失、强制外部密钥但未注入、provider / suite 未实现、`current_crypto()` 未安装 |
| `SECRET_DECRYPT_FAILED` | 500 | 信封校验失败、域或 AAD 不符、key_id 不在钥环中 |
| `BACKUP_KEY_MISMATCH` | 400 | 备份包 key_id 与当前主密钥不符 |

三码同批追加到 `ErrorCode` 末尾与 `_DEFAULT_STATUS` 末尾；后端 en/zh 文案与 dashboard `apiErrors` 写入 `w0-04` 的 intranet overlay。口令去除的弃用警告只写日志，不新增码。`OctopError` 的 message 与日志中不出现密钥、口令、明文凭据。

## 安全考虑

- AAD 绑定"表:列:行标识"，防止密文在字段间搬运。
- `require_external_key=true` 是行内生产的推荐值：拒绝自动生成，也拒绝只出现在 `~/.octop/env` 中的 `OCTOP_MASTER_KEY`（env 文件与数据同目录）。
- 主密钥丢失等于数据不可恢复：`keys status` 与备份页显示 key_id，托管流程由 `w4-02` 写入手册。
- local provider 不满足"密钥不出密码设备"的密评要求，只承诺接口就绪；密评由 `p2-02` 完成。

## 测试策略

- 单测（新增）：`tests/unit/crypto/test_envelope.py`、`test_master_key.py`（chmod 断言用 `posix_only`）、`test_registry.py`、`test_single_crypto_entrypoint.py`、`tests/unit/db/test_secret_repo_codec.py`、`tests/unit/keys/test_backfill.py`、`test_rotate.py`、`tests/unit/backup/test_archive_crypto.py`。命令：`uv run pytest tests/unit/crypto tests/unit/keys tests/unit/db/test_secret_repo_codec.py tests/unit/backup -q`。
- 单测（改写）：`tests/unit/auth/test_sso_crypto.py`（≈L21-22 隔离断言改为跨域不可解）、`tests/unit/auth/test_captcha_store.py`、`tests/unit/test_langfuse_settings.py`、`tests/unit/connectors/test_custom_mcp.py`、`tests/unit/db/test_repo_secret_audit.py::test_secret_rotate`、`tests/unit/test_env_file.py`、`tests/unit/backup/test_snapshot.py`、`test_system_archive.py`、`test_store.py`。新增 `tests/support/crypto.py::make_test_provider()`，`tests/conftest.py` 加 autouse fixture 安装并在结束时 `reset_crypto()`。
- 集成：`tests/integration/test_secret_at_rest.py`（探针原始字节扫描、哨兵回写）、`tests/integration/test_setup_database.py`（无口令、`password_persisted`）。命令：`uv run pytest tests/integration/test_secret_at_rest.py tests/integration/test_setup_database.py -q`。
- PG：`OCTOP_TEST_DATABASE_URL=postgresql://octop:octop@localhost:5432/octop_test uv run pytest tests/integration/test_secret_at_rest.py -q`（依赖 `w0-02` 的 postgres service）。
- 前端：`cd dashboard && npx tsc -b && npm run lint`。
- i18n：`uv run pytest tests/unit/i18n -q`。

## 与其他 spec 的交接

- **依赖：** `w0-01` 的 fork 迁移 runner；`w0-02` 的 PG 门禁；`w0-04` 的 i18n overlay、`CHANGELOG-intranet.md`、`docs/api-intranet.md`；`w1-01` 的 providers / voice 响应脱敏与 `infra/voice/credentials.py`；`w1-02` 的配置三触点单测；`w1-05` 已删除 `wecom_creds.py`、`fliggy.py`、`media_generation.py`、`codex_oauth.py` 与三家 SSO 行的密文；`w3-02` 的 `AuditRepo.write` 与 `AuditContext`；`w3-04` 的会话表（`auth_sessions` 无秘密列，不加密）。
- **交付给 `p2-02`：** `CryptoProvider` 接口、注册表中 `kms` / `sdf` 占位键位、信封中的 `suite_id`、`crypto.provider` / `crypto.suite` 配置键；二期只新增 provider 模块与套件，不改调用方。JWT 签名算法与密钥派生归 `p2-02`。
- **交付给 `p2-06`：** providers `extra_json` 已加密落库，`p2-06` 在 `w1-01` 的脱敏契约下加回传字段。
- **交付给 `w4-02`：** 主密钥托管、备份包恢复、`keys rotate-master` 的运维手册。
- **不归本 spec：** 见 requirements.md 引言的范围外清单。

## 风险与回滚

- **回填半途失败：** 每批独立事务 + 水位续跑；未回填行仍可读（非信封原样返回），不会宕机。
- **主密钥丢失：** 首次生成时在日志打印 key_id 与文件路径（不打印密钥），`keys status` 可随时核对；手册要求与备份分开托管。
- **测试中直接构造 `SecretRepo(db)` 的 6 处：** codec 可选，不传即保持明文，只有加密相关用例需要注入。
- **回滚：** 代码可 `git revert`，但回填后的信封数据旧代码读不了，因此不提供"解密回明文"的命令。数据回滚的唯一方案是恢复升级前的 `.tar.gz` 备份；`w4-02` 手册要求升级前先做一次备份。

## 待行方确认

- D8：一期只保留 `suite_id`，国密套件在 `p2-02`；若一期强制国密，需提前约 8 人日。
- D3：控制面为 PG 系；PG 用例在 `w0-02` 的 postgres service 上执行。
- D9：`desktop/`、`fnos/` 不交付；若交付，各自的打包导入校验需补 `cryptography.hazmat.primitives.ciphers.aead`。
