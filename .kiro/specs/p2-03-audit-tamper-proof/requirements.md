# 需求文档：审计防篡改与外发

> spec：`p2-03-audit-tamper-proof` ｜ 波次：二期 ｜ 基线：`757fd12` ｜ 预估：26 人日
> 前置：`w3-02-audit-baseline`、`w3-03-authorization-foundation`、`w0-01-fork-migration-namespace` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 引言

`audit_log` 当前是一张可被任意 `UPDATE`/`DELETE` 的普通表（`src/octop/infra/db/migrations/001_initial.sql` ≈L231-238，仅 `id/ts/actor/action/target/payload` 六列），无完整性证明、无容量治理、无法外证。本 spec 在 `w3-02` 冻结的审计字段集之上，把它改造成可举证的防篡改证据链：哈希链、库层禁改删触发器、Kafka 外发通道、导出、≥180 天保留与归档、审计管理员只读视图。

**范围内**：
- 哈希链（`prev_hash`/`row_hash`，canonical 序列化，算法可插拔以便密评替换 SM3）与链校验。
- SQLite/PostgreSQL 双方言的库层禁改删触发器，及其边界说明（挡不住 `DROP TRIGGER`、挡不住 SQLite 整库覆盖恢复）。
- Kafka 外发（第二条外发通道；`syslog` 外发已由 `w3-02` 交付，本 spec 不重做）。
- 导出（XLSX/CSV 流式，含链校验摘要）。
- 保留期（在线默认 ≥180 天，可配置）与归档（签名归档段，清理动作入链）。
- 审计管理员只读视图：新增的校验/导出/归档/外发配置端点按 `audit_admin` 权限键门控。

**范围外**（写明归属）：
- `audit_log` 字段集扩列、`AuditContext`、request_id、syslog 外发、`ACTOR_ADMIN` 替换、线程保留期 —— 归 `w3-02`（本 spec 只消费其冻结结果）。
- `audit_admin` 权限键的创建、`effective_permissions` 对 admin 的排除逻辑、`PUT /api/users/{id}` 的自授权守卫、前端 `userCan`/`userCanAny` 的例外短路 —— 归 `w3-03`（三员分立机制），本 spec 只消费既有角色。
- 数据库迁移版本号策略、fork 迁移 runner、`_fork_schema_version` —— 归 `w0-01`，本 spec 的迁移一律走 fork 独立空间。
- 国密 SM3/SM2 落地、KMS 托管 —— 归 `p2-02`（本 spec 仅为哈希算法预留可插拔接口）。
- CI 前端与 PostgreSQL 门禁的建立 —— 归 `w0-02`，本 spec 假设其已合入。

## 需求

### 需求 1：哈希链完整性

**用户故事：** 作为合规审计人员，我希望每条审计记录都携带可验证的哈希链，以便任何一处篡改都能被检测并定位。

#### 验收标准
1. 当 `AuditRepo.write()` 写入一条记录时，系统应当在同一事务内计算 `row_hash = H(canonical(id, ts, actor, action, target, payload, prev_hash))` 并更新链头。
2. 如果某一行被篡改或删除，那么 `AuditRepo.verify_chain()` 应当返回 `ok=False` 且精确定位到 `first_broken_id`。
3. 在存量库升级期间，系统应当先完成分批链回填、再创建禁改删触发器，因为触发器一旦存在会拒绝回填所需的 `UPDATE`。
4. 系统应当始终以 `id` 作为同秒多行的排序依据（`ts` 为秒级精度，无法定序）。

### 需求 2：库层禁改删触发器

**用户故事：** 作为数据库管理员，我希望 `audit_log` 在 SQLite 与 PostgreSQL 下都拒绝直接的 `UPDATE`/维护窗口外 `DELETE`，以便把篡改门槛提高到应用层之上。

#### 验收标准
1. 当有连接对已迁移的库执行 `UPDATE audit_log` 时，系统应当抛出完整性错误（SQLite: `sqlite3.IntegrityError`；PostgreSQL: 等价异常）。
2. 如果维护窗口未开启，那么对 `audit_log` 的 `DELETE` 应当同样被拒绝。
3. 设计文档应当始终明确触发器的边界：不防 `DROP TRIGGER`、不防 SQLite `backup` API 整库覆盖式恢复；真正的防篡改保证来自哈希链 + 外发到独立系统。

### 需求 3：Kafka 外发

**用户故事：** 作为安全运营人员，我希望审计事件能异步外发到行内 Kafka 集群，以便在原库被篡改时仍有独立可比对的副本。

#### 验收标准
1. 当 Kafka 目标不可达时，`audit_repo.write()` 应当始终在 1 秒内返回且不向调用方抛出异常。
2. 系统应当将待发事件持久化在本地 spool 中，目标恢复后按 `audit_log.id` 升序补发。
3. 如果 spool 达到配置上限，那么系统应当丢弃最旧记录并写入一条自描述的审计事件（该事件本身入链）。
4. 外发的网络 IO 应当始终在独立后台线程执行，不得阻塞请求协程（`audit_repo.write` 被同步与异步调用方共用）。

### 需求 4：导出与保留归档

**用户故事：** 作为审计管理员，我希望能导出带链证明的审计记录，并让超过保留期的记录被自动归档清理，以便满足等保对留存与可核查性的要求。

#### 验收标准
1. 当调用导出接口时，系统应当以流式方式返回 XLSX/CSV，不得将整表读入内存，且导出内容包含 `row_hash`/`prev_hash` 列与链校验摘要。
2. 系统应当始终沿用 `w3-02-audit-baseline` 定义的 `audit.retention_days` 及其下限校验（大于 0 且小于 180 时 `load_config` 抛错）；本 spec 不重复定义该键，也不提供放行开关。
3. 当系统作业执行清理时，系统应当先把被清理区间写入带 `.sha256` 校验的签名归档段（记录首尾 `row_hash` 以便与在线链续接），再在同一维护窗口事务内完成删除，并写入一条清理事件。

### 需求 5：审计管理员只读视图

**用户故事：** 作为持有 `audit_admin` 角色的审计管理员，我希望能只读地查看链状态、导出与归档记录、外发配置状态，以便履行独立监督职责而无需拥有系统管理员权限。

#### 验收标准
1. 当持有 `audit_admin` 而非系统管理员角色的用户访问新增的校验/导出/归档只读端点时，系统应当返回 200。
2. 如果该用户尝试调用外发配置的写端点（如变更 Kafka 目标），那么系统应当返回 403。
3. 新增路由文件应当被纳入既有的权限门控覆盖清单，防止门控被静默绕过。

### 需求 6：跨平台与验收可执行性

**用户故事：** 作为维护者，我希望本 spec 的全部验收标准都能在 Linux 与 Windows 两条 CI 上用 `uv run pytest` 直接复现，以便验收结果可信。

#### 验收标准
1. 新增的外发与保留期测试应当始终不依赖 POSIX 专属能力（`/dev/log`、Unix socket、`chmod` 位断言），只使用回环地址与临时端口。
2. 归档目录相关测试应当始终通过 `monkeypatch.setenv("OCTOP_HOME", ...)` + `Path` 拼接定位，不假设 `~/.octop` 字符串形状。
3. `make all` 应当在合入前于本地全绿，PostgreSQL 相关用例在 `w0-02` 提供的门禁下可执行。
