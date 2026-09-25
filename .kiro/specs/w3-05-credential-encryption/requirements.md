# 需求文档：凭据加密与主密钥
> spec：`w3-05-credential-encryption` ｜ 波次：Wave 3 ｜ 基线：`757fd12` ｜ 预估：20 人日
> 前置：w0-01-fork-migration-namespace, w0-02-ci-gates, w0-04-fork-isolation-points, w1-01-security-hotfix, w1-05-saas-decoupling, w3-02-audit-baseline, w3-04-session-and-password ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 引言

**结论：** 本 spec 交付一个可替换的 `CryptoProvider`（一期只有 local 实现）和自描述信封，把 Octop 现存的"密钥与密文同库"结构全部拆掉。主密钥从数据库移到"环境变量 → 外部文件 → `~/.octop/secrets/master.key`"三级解析；`secrets` 表、四张表的明文凭据列、备份包都改为经信封加密；数据库口令不再写入 `config.json`；`~/.octop/env` 不再覆盖进程环境变量。

**背景：** 基线有四套各自持钥的做法：连接器 Fernet（密钥行 `connector_fernet` 就在 `secrets` 表）、SSO Fernet（`sso_fernet` 同表）、企微文件 AES-GCM（已由 `w1-05` 删除）、Langfuse 明文字节。JWT 密钥 `jwt` 是明文行；四张表的凭据列是明文 TEXT；备份是连同这些钥匙一起打包的明文 tar.gz。等保与密评要求密钥与密文分离。

**范围内：**
1. `CryptoProvider` 接口：`wrap`/`unwrap`（二进制载体）、`wrap_text`/`unwrap_text`（base64 文本载体）、`key_id`、`suite_id`；提供者注册表；信封格式；local provider（AES-256-GCM + HKDF-SHA256 分域子密钥）；旧 Fernet 只读兼容。
2. 主密钥三级解析与"强制外部注入"开关；为 `p2-02` 的 KMS / SDF 预留注册表键位。
3. `SecretRepo` 增加可选 codec；`build_shared_services` 在生产路径断言 codec 非空；`replace_persistence` 等重建路径自动携带 codec；`rotate` 改为 upsert。
4. 收敛既有实现：connector Fernet、SSO Fernet（含验证码对文本载体的依赖）、Langfuse 明文；JWT 签名密钥改由主密钥保护。
5. 明文列加密：`providers.api_key` 与 `extra_json` 中的敏感键、`voice_providers.api_key` 与 `extra_json` 中的敏感键、`storage_backends.access_key/secret_key` 与 `config_json` 中的敏感键、`channels.config_json` 中的敏感键。存量行在启动时幂等回填。
6. 离线轮换 CLI `octop keys status|rewrap|rotate-master`；轮换写审计。
7. 备份包加密（`.octbk`）与 key_id 预检；1.0.1 的明文包保持只读兼容。
8. 数据库口令不写 `config.json`，包括 `url` 带 `?sslmode` 时的内嵌口令分支。
9. `apply_env_file` 默认不覆盖已存在的进程环境变量。

**范围外：**
- KMS、SDF 加密机、SM4/SM3/SM2 套件、JWT 的 SM3-HMAC、口令哈希国密化：`p2-02-kms-sm-crypto`（D8）。
- providers / voice 管理接口响应体脱敏（`has_api_key` 布尔位）与前端 Models / Voice 页适配：`w1-01-security-hotfix`（已合入）。本 spec 只负责落库。
- `/api/envs` 的全量脱敏、env 文件落盘加密：不做。docker 沙箱把 env 文件路径原样交给容器运行时解析，Python 侧无法插入解密钩子；env 文件保持 dotenv 明文。
- 向导口令文件、stdout banner 中的明文口令：`w3-04-session-and-password`。
- TLS 私钥加密、国密证书：`p2-02`。审计防篡改：`p2-03`。
- 密钥托管与备份包跨机恢复的运维手册：`w4-02-ops-minimum`。
- 因 `w1-05` 删除而不再存在的对象（`wecom_creds.py`、`fliggy.py`、`media_generation.py`、`codex_oauth.py`）：不为它们写代码。

## 需求

### 需求 1：统一加密提供者与信封

**用户故事：** 作为安全架构师，我希望全站加解密只经过一个可替换的提供者接口，密文自带算法与密钥标识，以便二期切换 KMS 或国密时只新增模块而不改调用方。

#### 验收标准
1. 当调用 `wrap(plaintext, domain=..., aad=...)` 时，local provider 应当返回以信封魔数开头、含 `suite_id` 与 `key_id` 的字节串；`unwrap` 应当还原明文。`uv run pytest tests/unit/crypto/test_envelope.py -q` 通过。
2. 当调用 `wrap_text` 时，返回值应当是纯 ASCII（可直接 `.decode("ascii")` 与写入 JSON 字符串），并以文本前缀 `oce1:` 开头；`unwrap_text` 应当还原明文。
3. 如果密文被篡改、`aad` 不同或 `domain` 不同，那么 `unwrap` 应当抛 `OctopError(ErrorCode.SECRET_DECRYPT_FAILED)`，不得返回部分明文。
4. 如果 `crypto.provider` 为 `kms` 或 `sdf`，或 `crypto.suite` 不是 `aes256gcm`，那么启动应当以 `SECRET_KEY_UNAVAILABLE` 失败，消息说明该提供者或套件一期未实现。
5. `src/octop/infra` 与 `src/octop/cli` 下的 `from cryptography` 应当始终只出现在 `infra/utils/crypto/`、`infra/setup/tls/acme_issue.py`、`cli/commands/run.py` 三处；由 `tests/unit/crypto/test_single_crypto_entrypoint.py` 检查。

### 需求 2：主密钥移出数据库

**用户故事：** 作为行内运维，我希望主密钥由容器平台或外部文件注入，而不是和数据放在同一个库里，以便"拿到库"不等于"拿到明文"。

#### 验收标准
1. 当设置 `OCTOP_MASTER_KEY`（base64 编码的 32 字节）时，系统应当使用它，并且不创建 `~/.octop/secrets/master.key`。
2. 当未设置 `OCTOP_MASTER_KEY` 而 `crypto.master_key_file` 指向可读文件时，系统应当使用该文件中的密钥。
3. 当两者都未设置且 `crypto.require_external_key` 为假时，系统应当生成 `~/.octop/secrets/master.key`；在 POSIX 下文件权限为 `0o600`、目录权限为 `0o700`（用例带 `posix_only` 守卫）。
4. 如果 `crypto.require_external_key` 为真，而外部密钥缺失或仅出现在 `~/.octop/env` 中，那么 `OctopServer.start()` 应当抛 `SECRET_KEY_UNAVAILABLE` 并且不监听端口。
5. 迁移与回填完成后，`secrets` 表应当始终不含 `connector_fernet`、`sso_fernet` 行，且每一行的 `v` 都以信封魔数开头。

### 需求 3：SecretRepo 信封化与生产接线

**用户故事：** 作为后端开发者，我希望 `SecretRepo` 在生产路径上一定带着加密器，以便任何新写入 `secrets` 表的值都不可能以明文落盘。

#### 验收标准
1. 当 `SecretRepo` 带 codec 时，`get_or_create` 与 `rotate` 写入的应当是信封，`get` 返回的应当是解密后的原值；不带 codec 时行为与基线一致。
2. 如果调用 `build_shared_services` 时既未传入 crypto，进程内也未安装 provider，那么它应当抛 `SECRET_KEY_UNAVAILABLE`，而不是静默退回明文。
3. 当控制面经 `bind_control_plane` 或 rebind 路径重建服务，以及执行 `manager.replace_persistence` 之后，`LangfuseSettingsStore`、`ConnectorService` 持有的 `secret_repo.codec` 应当是当前 provider。
4. 当对不存在的键调用 `rotate` 时，`SecretRepo` 应当插入该行（upsert），`octop admin rotate-jwt-secret` 之后 `jwt` 行存在且为信封。
5. JWT 签发与校验（`api/deps.py::_decode`、`maybe_sliding_renew_token` 与各签发点）应当始终读取经主密钥解封的 `jwt` 值；换一把主密钥后旧库中的 `jwt` 行无法解封。

### 需求 4：既有加密实现收敛

**用户故事：** 作为安全审计员，我希望连接器、SSO、验证码、Langfuse 都走同一个提供者，以便只有一处需要评审和轮换。

#### 验收标准
1. 当连接器保存凭据时，`connectors.credential_blob` 应当是 `domain="connector"` 的二进制信封；1.0.1 的 Fernet 密文应当仍可读取，并在回填后被重封。
2. 当 SSO 保存 `client_secret` 时，`encrypt_secret` 的返回值应当可 `.decode("ascii")`（文本载体），旧 Fernet 值应当仍可读。
3. SSO 域与连接器域的密文应当始终互不可解：用 `domain="connector"` 解 SSO 密文抛 `SECRET_DECRYPT_FAILED`（改写 `tests/unit/auth/test_sso_crypto.py` 的隔离断言）。
4. 当保存 Langfuse secret 后，`secrets` 表中 `langfuse_secret_key` 行应当是信封，`test_connection` 与 harness 配置取到的仍是原值。

### 需求 5：明文列加密

**用户故事：** 作为数据库管理员，我希望库里的供应商密钥、存储凭据、通道凭据都是密文，以便 DBA、备份介质、SQL 注入都拿不到可用凭据。

#### 验收标准
1. 当经 API 创建 provider（`api_key` 与 `extra_json` 请求头含探针）、voice provider、storage backend（`secret_key` 与 `config_json.password` 含探针）、channel（`config` 敏感键含探针）后，直接读取 SQLite 文件原始字节应当找不到任何探针串。`uv run pytest tests/integration/test_secret_at_rest.py -q` 通过。
2. 当 repo 读出上述行时，`ProviderRow.api_key` 等字段应当是解密后的原值，模型调用、存储探测、通道启动行为与基线一致。
3. 如果读到的列值不以 `oce1:` 开头（存量明文），那么 repo 应当原样返回，回填完成后该行应当被改写为信封。
4. 当 `GET /api/admin/storage-backends` 与 `GET /api/agents/{id}/channels/{cid}` 返回 `config_json` / `config` 时，敏感子键的值应当是 `********`；用 `********` 回写时库内密文保持不变，传新值时密文变化。
5. 在 PostgreSQL 控制面期间，需求 5.1 至 5.3 应当同样成立（`OCTOP_TEST_DATABASE_URL` 下执行同一用例）。

### 需求 6：存量回填与离线轮换

**用户故事：** 作为升级实施人员，我希望升级后存量明文与旧密文自动重封，并能离线轮换主密钥，以便升级不丢配置、轮换可审计。

#### 验收标准
1. 当以 1.0.1 生成的库启动时，回填应当把 `secrets` 明文行、Fernet 密文、四张表的明文列全部改为信封，删除 `connector_fernet` 与 `sso_fernet` 行；再次启动不再改写任何行。
2. 如果回填中途失败，那么已完成的批次应当保持提交，重新启动后从 `crypto_state` 中的水位继续，且不会出现双重加密。
3. 当执行 `octop keys rotate-master --new-key-file <path>` 后，旧主密钥不能再解封任何字段，新主密钥可以；`audit_log` 出现 `action='secret.master_rotate'`，payload 不含任何密钥材料。
4. 当执行 `octop keys status` 时，输出应当包含 provider、suite、active key_id 与待回填行数；不输出任何密钥材料。

### 需求 7：备份包加密

**用户故事：** 作为备份管理员，我希望备份包本身是密文且标明所用密钥，以便介质丢失不泄露数据，恢复时能在写库前发现密钥不匹配。

#### 验收标准
1. 当创建系统备份时，输出文件应当以 `.octbk` 结尾，以魔数 `OCTOPBK1` 加 key_id 开头，`tarfile.open` 应当无法直接打开它。
2. 当用同一主密钥恢复时，恢复应当成功；如果换一把主密钥，那么恢复应当在改写任何目标之前以 `BACKUP_KEY_MISMATCH`（HTTP 400）失败。
3. 当恢复或 peek 1.0.1 产出的明文 `.tar.gz` 时，系统应当仍可读取（只读兼容）。
4. 备份列表、上传、下载接口与 dashboard 备份页应当始终同时接受 `.octbk`、`.tar.gz`、`.tgz`。

### 需求 8：数据库口令不落盘

**用户故事：** 作为安全管理员，我希望数据库口令只由环境注入，以便 `config.json` 被读取时不泄露口令。

#### 验收标准
1. 当 `POST /api/setup/database` 携带口令时，`config.json` 的 `database` 段应当既没有 `password` 键，也没有含口令的 `url`（包括带 `?sslmode=` 的 DSN）；响应含 `password_persisted: false`。
2. 当 `config.json` 中残留旧的 `password` 键时，系统应当仍能读取（兼容升级）并输出一条弃用警告日志，日志中不含口令。
3. 在 `config.json` 无口令而 `OCTOP_DATABASE_PASSWORD` 已由进程环境注入期间，重启后控制面应当正常绑定 PostgreSQL（PG 集成用例）。

### 需求 9：env 文件不覆盖进程环境

**用户故事：** 作为容器平台运维，我希望 K8s / systemd 注入的环境变量优先于 `~/.octop/env`，以便平台下发的口令与密钥不被本地文件静默覆盖。

#### 验收标准
1. 当进程环境已有 `OCTOP_DATABASE_PASSWORD=from-k8s` 且 `~/.octop/env` 写有同名键时，`apply_env_file(path)` 之后值应当仍为 `from-k8s`；`apply_env_file(path, override=True)` 才覆盖。
2. 当管理员经 `/api/envs` 保存时，`apply_env_file_replace` 应当保持覆盖语义（显式写入），行为与基线一致。
3. `OctopServer.start()`、`open_cli_services`、`octop init`、`octop admin rotate-jwt-secret` 应当始终以不覆盖语义加载 env 文件。
