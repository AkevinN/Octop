# 需求文档：审计与日志基线
> spec：`w3-02-audit-baseline` ｜ 波次：Wave 3 ｜ 基线：`757fd12` ｜ 预估：34 人日
> 前置：`w0-01-fork-migration-namespace`、`w0-02-ci-gates`、`w0-03-test-auth-baseline`、`w0-04-fork-isolation-points`、`w1-02-capability-trim`、`w1-05-saas-decoupling`、`w3-01-web-security-baseline` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 引言

**背景。** 基线的审计只有 `audit_log(id, ts, actor, action, target, payload)` 六列：管理类操作写死常量 `_admin`（14 处），没有来源 IP、会话、请求 ID 与结果；供应商密钥、SSO 配置、环境变量、备份导出、文件上传下载、线程删除等涉密面零审计；`AuditRepo.delete_before` 没有任何调用方，审计永不过期也从不清理；线程删除是物理删除；应用日志只有文件 handler，访问日志会原样落下 `?access_token=<JWT>`。

**为什么做。** 等保三级要求审计记录可定责到人、含主体/客体/时间/结果/来源，并留存不少于 180 天。行内还要求日志能进集中平台，数据出口有留痕。

**范围内。**
- 冻结 `audit_log` 字段集，提供 `AuditContext`，保留旧 kwargs 调用方式（41 个写入点、14 个文件不必一次改完）。
- request_id：contextvar、`X-Request-Id` 响应头、错误信封字段、日志字段、审计列。本 spec 是唯一实现方。
- 真实操作人：替换 `ACTOR_ADMIN` 的 14 处使用点，JWT 增加 `sid`，来源 IP 取自 `w3-01` 的 `client_ip()`。
- 覆盖面补齐：供应商、语音供应商、SSO 配置、环境变量、备份、文件上传下载、知识库、轨迹导出、可携记忆、as_user 代访问、线程删除、权限拒绝。
- 线程软删除加保留期清除。清除时如果 agent 未运行、checkpoint 删不掉，就延期重试，不删库行。审计保留期从零建立。
- 应用日志：唯一的脱敏 Formatter（能覆盖 traceback），stdout JSON 结构化输出。
- syslog 单向外发，作为一期对哈希链的补偿控制；外发失败不阻塞主流程。
- 10 个附件下载出口的后端兜底开关与留痕。

**范围外。**
- 哈希链、Kafka、180 天归档、审计员视图、持久化外发队列：`p2-03-audit-tamper-proof`。
- 中间件栈顺序契约、`client_ip()`、`trusted_proxies`：`w3-01-web-security-baseline`（本 spec 只占用其预留的最外层槽位）。
- 权限判定收口、三员分立、审计员角色：`w3-03-authorization-foundation`。
- 会话表、吊销、强制下线：`w3-04-session-and-password`（复用本 spec 的 `sid`）。
- 按角色的下载/复制/水印策略与前端出口收敛：`p2-07-frontend-controls`。
- 日志与审计中的 PII（身份证、卡号）规则：`p2-04-content-security-pii`，它通过本 spec 的注册接口追加规则。
- 前端错误提示中展示 request_id：`w4-01-frontend-baseline`。
- 容器清单中打开 `OCTOP_LOG_STDOUT`：`w4-02-ops-minimum`。

## 需求

### 需求 1：审计字段集冻结与写入接口
**用户故事：** 作为安全审计员，我希望每条审计记录都带完整的主体、来源、会话、请求与结果字段，以便定责和关联。
#### 验收标准
1. 当新库初始化或老库升级时，fork 迁移应当让 `audit_log` 在 SQLite 与 PostgreSQL 上都新增 `actor_id, actor_kind, on_behalf_of, src_ip, user_agent, session_id, request_id, result, error_code` 九列，且 `ls src/octop/infra/db/migrations | grep -c '^016_'` 为 0。
2. 当调用方只传旧 kwargs（`actor/action/target/payload`）写审计时，`AuditRepo.write` 应当从当前 `AuditContext` 补齐 `src_ip/session_id/request_id/actor_id/user_agent`，`tests/unit/db/test_repo_secret_audit.py` 不改即通过。
3. 如果某个注入的 `AuditSink` 抛异常，那么 `AuditRepo.write` 应当照常落库并返回，异常只记 ERROR 日志。
4. 在无请求上下文（CLI 离线、系统任务）期间，`AuditContext` 应当返回各字段为 `None` 的默认值，`actor_kind` 为 `system` 或 `cli`。
5. `AuditRepo` 应当始终只有 `services.py` 一个构造点，并通过 `sinks=` 参数装配。

### 需求 2：request_id 贯穿
**用户故事：** 作为运维人员，我希望一次请求在响应、错误、日志、审计中带同一个 ID，以便串联排障。
#### 验收标准
1. 当任意 `/api/*` 请求完成时，响应应当带 `X-Request-Id` 头，包括 `jwt_auth` 短路返回的 401 和 `setup_lockdown` 返回的响应。
2. 当请求带合法的入站 `X-Request-Id`（`[A-Za-z0-9._-]{1,64}`）时，系统应当沿用它；如果不合法或缺失，那么系统应当生成新的 ULID。
3. 当请求以 `OctopError` 或 401 结束时，错误信封的 `error` 对象应当含与响应头相同的 `request_id`；无请求上下文时省略该键。
4. 当该请求写了审计或日志时，审计行的 `request_id` 与日志行的 `request_id` 都应当等于响应头的值。
5. 在并发请求期间，各请求的 request_id 应当互不串扰。
6. 中间件栈应当始终以本 spec 的 `RequestContextMiddleware` 为最外层，由 `uv run pytest tests/unit/api/test_middleware_stack.py -q` 断言。

### 需求 3：真实操作人、会话与结果
**用户故事：** 作为安全审计员，我希望管理操作记录真实操作人、登录会话与结果，以便追责。
#### 验收标准
1. `rg -n 'ACTOR_ADMIN' src/octop` 应当始终只命中 `infra/db/repos/audit.py` 的定义行。
2. 当管理员调用 `PATCH /api/users/{id}` 修改角色时，`user.set_role` 审计行的 `actor` 应当等于该管理员的 username，`actor_id` 等于其 user id；`user.create` 的 `actor` 应当是创建者而不是被创建者。
3. 当 JWT 经滑动续期换发时，新令牌的 `sid` claim 应当保持不变；重新登录后 `sid` 应当变化；同一令牌做 3 次管理操作，3 条审计行的 `session_id` 应当相同。
4. 当登录成功或失败时，`auth.login` / `auth.failed` 行的 `result` 应当分别为 `success` / `failure`，`src_ip` 应当等于 `client_ip()` 的返回值且非空。
5. 如果 `require_permission` 或 `require_admin` 拒绝请求，那么系统应当写一条 `action='authz.denied'`、`result='denied'`、`error_code='FORBIDDEN'` 的审计。

### 需求 4：涉密与数据面的审计覆盖
**用户故事：** 作为安全审计员，我希望密钥、配置、数据进出类操作都有记录，以便追查泄露。
#### 验收标准
1. 当执行下列操作时，系统应当各写一条对应 action 的审计：`provider.create/update/delete`、`voice.provider.create/update/delete`、`sso.config.update`、`env.read/env.update/env.delete`、`backup.auto.update/backup.auto.run/backup.create/backup.download/backup.file_delete/backup.export/backup.import`、`file.upload`、`workspace.file.write/workspace.file.delete`、`knowledge.document.upload/knowledge.document.delete/knowledge.base.delete/knowledge.reindex`、`memory.daily.read/memory.daily.delete`、`memory.portable.pack/memory.portable.adopt`、`thread.soft_delete`。
2. 审计 payload 应当始终不含 `api_key`、`client_secret`、环境变量值的明文，只记字段名或 `*_changed` 布尔值。
3. 当管理员以 `?as_user=<alice_id>` 访问 alice 的 agent 或用量时，系统应当写 `action='impersonate.access'`、`actor=admin`、`on_behalf_of=alice`；同一 actor + 对象 + 目标在节流窗口内只写一条；alice 访问自己的资源不写。
4. 如果用户经 OAuth 解绑自己的 SSO 身份，那么系统应当只保留 `user.sso_unbind` 一条审计，不新增重复行。

### 需求 5：线程软删除与不复活
**用户故事：** 作为合规负责人，我希望用户删除的对话在保留期内仍可取证，同时对用户不可见也不会复活。
#### 验收标准
1. 当 `DELETE /api/agents/{a}/threads/{t}` 返回 204 后，线程列表应当不含该线程，`threads.deleted_at/deleted_by` 应当非空，`thread_messages` 与 `trajectory_events` 行应当仍在，且应当有一条 `thread.soft_delete` 审计。
2. 当同一 `session_key` 在软删除后再次进入 `ThreadRegistry.get_or_create` 或 `get_or_create_by_key` 时，系统应当返回新的 `thread_id`。
3. 当 IM slash 删除命令或 `octop chats delete` 删除线程时，语义应当与 HTTP 一致，都是软删除并写审计。
4. 如果 fork 失败回滚，那么 `thread_fork` 应当硬删除刚插入的目标线程。
5. `thread_messages` 的 `migration_summary/migration_candidates/migration_active_thread_ids` 应当始终不返回已软删除的线程。

### 需求 6：保留期清除
**用户故事：** 作为运维人员，我希望到期数据由系统任务统一清除，并留下清除记录。
#### 验收标准
1. 当线程保留期为 0 天并触发清除任务时，如果 checkpoint 删除成功，那么系统应当删除该线程在 `threads/thread_messages/thread_history_projection/trajectory_events` 中的行，调用一次 history 归档的 `remove_thread`，并写 `actor='_system'`、`action='thread.purge'`。
2. 如果目标 agent 未运行、`delete_thread_checkpoint` 返回 False，那么系统应当保留 `threads` 行，`purge_attempts` 加 1，并写 `thread.purge_deferred`；超过上限时打 WARNING 日志。
3. 当 `audit.retention_days` 大于 0 并触发审计清除任务时，系统应当调用 `AuditRepo.delete_before` 删除过期行，并写一条 `audit.purge` 审计（含删除条数）。
4. 如果 `audit.retention_days` 大于 0 且小于 180，那么 `load_config` 应当抛 `ValueError`。

### 需求 7：日志结构化与脱敏
**用户故事：** 作为运维人员，我希望日志能结构化输出到 stdout，且不含令牌和密钥。
#### 验收标准
1. 当 `OCTOP_LOG_FORMAT=json` 时，文件与 stdout 日志每行都应当是合法 JSON，含 `ts/level/logger/msg/request_id/actor`；未设置时应当保持基线文本格式，并在 logger 名前追加 `[request_id]` 段（无上下文时为 `-`）。
2. 当 `OCTOP_LOG_STDOUT=1` 时，系统应当增加 stdout handler；未设置或为 0 时不增加。
3. 当日志消息、参数或 traceback 中出现 `access_token=<JWT>`、`Bearer <JWT>`、裸 JWT、`api_key=`/`client_secret=`/`password=` 时，输出应当已替换为 `***`，全文 `grep -c 'eyJ'` 为 0。
4. 脱敏应当始终在 Formatter 层完成，不依赖 `logging.Filter`；无请求上下文的第三方 handler 不得因缺字段抛异常。

### 需求 8：syslog 单向外发
**用户故事：** 作为安全管理员，我希望审计实时外发到行内日志平台，以便在哈希链上线前有外部留存。
#### 验收标准
1. 当 `audit.syslog_enabled=true` 时，每条审计写入后应当以 RFC5424 格式经 TCP、UDP 或 TLS 发往配置目标，由后台线程发送。
2. 如果目标不可达，那么连续 200 次 `AuditRepo.write` 应当全部返回且总耗时小于 1 秒，审计行数为 200，调用方不见异常。
3. 如果内存队列满，那么系统应当丢弃最旧条目、累计丢弃计数并打 WARNING 日志。
4. 外发测试应当始终只用 `127.0.0.1` 临时端口，不依赖 `/dev/log`，在 Windows CI 上同样通过。

### 需求 9：下载出口兜底与留痕
**用户故事：** 作为安全管理员，我希望能在服务端统一关闭附件下载，且每次下载都有记录。
#### 验收标准
1. 当能力 `file_download` 关闭时，10 个 attachment 出口都应当返回 403，`error.code == 'FORBIDDEN'`，`error.details.reason == 'download_disabled'`，并写 `result='denied'` 的 `file.download` 审计。
2. 在 `file_download` 开启期间，10 个出口都应当正常返回，并写 `result='success'` 的 `file.download` 审计（`backup.*`、`trajectory.export` 类出口使用各自的 action 名）。
3. inline 预览与 JSON 原文读取口（`workspace.py` 的 inline 预览、知识库 `disposition=inline`）应当始终不受该开关影响。

### 需求 10：审计查询接口与界面
**用户故事：** 作为安全审计员，我希望能按新字段筛选和查看审计。
#### 验收标准
1. 当调用 `GET /api/admin/audit-log` 时，响应应当包含九个新字段，支持 `result/actor_id/target/request_id/until` 过滤；`limit` 超过 1000 时返回 422；接口使用 Pydantic `response_model`。
2. 当执行 `octop admin audit --result denied` 时，CLI 应当只输出 `result='denied'` 的行，并含 `result/src_ip` 列。
3. 当打开设置页的审计面板时，界面应当显示来源 IP、结果、代访问对象列，并提供结果筛选；新增文案只写在 `dashboard/src/locales/intranet/{en,zh}.json`。
