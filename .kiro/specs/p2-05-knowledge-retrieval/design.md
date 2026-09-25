# 设计文档：知识库检索重写与三级权限

> spec：`p2-05-knowledge-retrieval` ｜ 波次：二期 ｜ 基线：`757fd12` ｜ 预估：35 人日
> 前置：`w3-03-authorization-foundation`、`w2-03-database-adaptation` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 概述

把"每库一个 SQLite 侧车、全表读出后 Python 算余弦"重写为"BM25 全文 + 向量召回 → RRF 融合 → 可选行内 rerank → 父窗口扩展"的混合检索栈；切分改为结构感知；权限从两档扩展为 `visibility(private|grant|org)` + 授权表三级，三条检索入口口径统一到 repo 层单一 SQL。本 spec 是二期任务，实施时代码已经过一期全部改造，下述"现状"仅作定位起点，实施前必须用 `rg` 重新核实。

## 现状（基线 757fd12，已在仓库核实）

- `src/octop/infra/knowledge/index.py:110`：`SELECT chunk_id, doc_id, ordinal, text, embedding, meta_json FROM chunks`，无 WHERE 无 LIMIT，全表读出后 Python 算余弦排序。
- `src/octop/infra/knowledge/retrieve.py`（132 行）：`retrieve_context`（≈L22）/`_retrieve_context_sync`（≈L58）/`_format_context`（≈L108）；每个可见库各自 `search()`，无融合、无重排、无上下文扩展。
- `src/octop/infra/db/repos/knowledge.py:174-178`：`list_visible(user_id)` SQL 为 `owner_user_id = ? OR shared = 1`，是当前权限唯一入口。
- `src/octop/infra/knowledge/service.py:3`：docstring 写死两档权限；`get_readable_base`（≈L323）/`get_writable_base`（≈L331）同样只有 owner/shared 判定。
- `src/octop/infra/db/migrate.py`：`_ensure_knowledge_bases_schema`（≈L669）调用 `_drop_knowledge_base_members`（≈L662），在迁移循环前（≈L1443）与无条件安全网尾部（≈L1702）都会跑——新表严禁复用该名字，否则每次启动被删。
- `src/octop/infra/errors.py`：`ErrorCode` 的 `KNOWLEDGE_*` 段在 ≈L90-99（9 个既有码），`_DEFAULT_STATUS` 逐一对应（≈L115 起）。
- `src/octop/infra/db/migrations/`：现有 001-015 共 15 对（已 `ls` 核实 30 个文件）；按 §1.1，fork 新增表**不得**占上游数字号（源分析的 `016_...sql` 方案冲突，已改为 fork 迁移，见"数据模型"）。

实施时以一期落地后代码重新定位（不写行号）：`processor.py`/`cron/delivery.py` 知识库可见库判定、`routers/knowledge_bases.py` 路由布局、`onnx_download.py`/`onnx_service.py` 离线开关消费点（归 `w2-01`，本 spec 只确认已生效）、`tools.py` 中 `search_knowledge` 对 `retrieve_context` 的调用签名、`permissions.py` 既有键 `knowledge_bases`/`knowledge_settings`。

## 方案

1. **索引 schema v2**：`chunks` 增 `token_text`（应用侧分词）、`meta_json` 落值；新增 `schema_meta(key,value)`、`chunks_fts` FTS5 虚表+触发器。拆出 `search_vector(query_vec,k,*,candidate_limit)`/`search_lexical(tokens,k)`，旧 `search()` 保留薄壳。向量侧先按 `doc_id`/`dim` 粗筛再反序列化。
2. **中文分词**：新增 `lexical.py`（jieba `tokenize`、`build_match_query`、`normalize_bm25`、`fts5_available()` 探测，失败则字面通道整体降级）。
3. **RRF 融合**：新增纯函数模块 `fusion.py`（`reciprocal_rank_fusion` + 确定性 tie-break）。
4. **可选重排**：新增 `rerank.py`，对齐 `embed.py` provider/凭据范式；超时或异常降级为原序返回。
5. **结构感知切分**：重写 `chunk.py` 内部为 `split_structured`，`chunk_text()` 签名不变。
6. **三级 ACL**：`knowledge_bases` 增 `visibility`（与 `shared` 双写过渡）；新增 `knowledge_base_grants`；`list_visible` 改为 `owner_user_id = ? OR visibility = 'org' OR EXISTS(grant)`，三入口均经过它。
7. **v1→v2 自动迁移**：`needs_rebuild()`/`rebuild_meta()`；启动路径新增 `resume_stale_index_schema()`（`contextlib.suppress` 包裹）。
8. **审计**：检索结束经 `getattr(services, "audit_repo", None)` 写 `knowledge.retrieve`。

## 组件与接口

| 文件 | 改动 |
|---|---|
| `knowledge/index.py` | schema v2、`search_vector`/`search_lexical`、`needs_rebuild`/`rebuild_meta`、惰性单连接 |
| `knowledge/lexical.py`（新增） | `tokenize`/`build_match_query`/`normalize_bm25`/`fts5_available` |
| `knowledge/fusion.py`（新增） | `reciprocal_rank_fusion`/`dedup_by_chunk_id`/`stable_tie_break` |
| `knowledge/rerank.py`（新增） | `rerank_settings`/`rerank_capability`/`rerank_hits` |
| `knowledge/chunk.py` | `split_structured`，`chunk_text` 兼容壳不变 |
| `knowledge/retrieve.py` | ACL 过滤→并发检索→RRF→可选 rerank→父窗口扩展；`retrieve_context` 新增 `lexical`/`rerank: bool \| None = None` |
| `knowledge/tools.py` | 透传新开关到 `search_knowledge` |
| `knowledge/params.py` | 新增 `lexical_enabled`/`vector_candidate_limit`/`rrf_k`/`rerank_top_n`/`parent_window`/`chunk_strategy` |
| `knowledge/service.py` | 读写判定加 grant；新增 `grant_access`/`revoke_access`/`list_grants` |
| `db/repos/knowledge.py` | 行加 `visibility`；`list_visible` 改写；新增 grants CRUD |
| `knowledge/gate.py` | `get_capability` 加 `rerank` 子对象与 lexical 就绪标志 |
| `api/routers/knowledge_bases.py` | `_capability_payload` 扩展、新增 `PUT /advanced-settings`、`PUT /feature` 加 rerank 字段（不进重建判定）、新增 grants 三路由（须在 `GET /{kb_id}` 前声明）；`openapi_meta.py` 改 knowledge tag 描述 |
| `processor.py`/`cron/delivery.py` | 知识库可见库判定统一经 `list_visible`（admin 绕过应已被 `w3-03` 删除，本 spec 只确认口径一致） |
| `infra/server.py` | 启动追加 `resume_stale_index_schema(self.services)` |
| `knowledgeBases.ts`/`KnowledgeBases/index.tsx`/`GrantsPanel.tsx`（新增） | `visibility` 三选 UI、授权成员面板、高级检索参数面板 |

## 数据模型

fork 迁移（编号不预占，合入前按 §1.1 取下一个可用号）：`forkNNN_knowledge_acl_and_index`

- `.sql`（SQLite）与 `.pg.sql`（PostgreSQL）成对，由 `w0-01` 的独立 fork 迁移 runner 与 `_fork_schema_version` 水位表执行，**不**进入 `migrate.py` 上游迁移链（源分析基于占用上游 `016` 号设计了 5 处 `migrate.py` 改动，与 §1.1 冲突，已全改为 fork 迁移，不动 `migrate.py`）。
- `knowledge_bases` 新增 `visibility TEXT NOT NULL DEFAULT 'private'`，回填 `UPDATE ... SET visibility='org' WHERE shared=1`；`shared` 保留一个版本兼容窗口，与 `visibility=='org'` 双向同步。
- 新表 `knowledge_base_grants`：`id`（整型主键）、`grant_id`（公开串 ULID）、`kb_id TEXT REFERENCES knowledge_bases(knowledge_base_id)`、`principal_type`、`principal_id`、`role`（`reader`|`editor`）、`granted_by`、`created_at`，`UNIQUE(kb_id, principal_type, principal_id)`，符合 AGENTS.md §7 约定。表名不得为 `knowledge_base_members`（`007` 迁移删除并被上游启动路径反复清空）。
- fork 迁移不改 `_schema_version`，**不改** `test_db_pool.py`/`test_published_experts_repo.py` 的 `assert v == 15` 断言（源分析要求改成 16，与 §1.1 冲突，已改掉）。
- 索引 schema v2（SQLite 侧车，非控制面表）：`schema_meta`、`chunks.token_text`、`meta_json` 落值、`chunks_fts`。旧库经 `needs_rebuild()` 检测后台重建。

## 配置

无新增 `config.py` 键。检索可调参数经既有 `knowledge/params.py`（`get_advanced_settings`/`set_advanced_settings`）落在 `settings` 表，非 env 三触点配置。若实施时确认全局断网开关（`OCTOP_OFFLINE`）尚未由 `w2-01` 落地，在待确认项提出阻塞，不自行补三触点。

## 错误处理

新增 `ErrorCode`（追加到 `KNOWLEDGE_*` 段末尾，`_DEFAULT_STATUS` 同批追加——漏登记会导致 `OctopError.__post_init__` 无保护字典下标 `KeyError`）：

| 码 | 状态 | 场景 |
|---|---|---|
| `KNOWLEDGE_GRANT_NOT_FOUND` | 404 | 操作不存在的授权记录 |
| `KNOWLEDGE_GRANT_INVALID_ROLE` | 400 | 授权角色不在 `reader`/`editor` 枚举内 |
| `KNOWLEDGE_RERANK_UNAVAILABLE` | 409 | 显式要求 rerank 但不可达（仅诊断接口用；正常检索路径静默降级不抛此码） |

新码文案与 dashboard `apiErrors` 条目一律写进 fork i18n overlay（`src/octop/i18n/intranet/{en,zh}.json`、`dashboard/src/locales/intranet/{en,zh}.json`，路径由 `w0-04` 建立），**不写入**上游 `{en,zh}.json`（源分析要求改上游 JSON，与 §1.2 规则二冲突，已改掉）。`knowledge.retrieval.*` 新增串同样走 overlay。

## 安全考虑

- `list_visible` 是三条入口共同的权限闸门，`EXISTS` 子查询必须过滤 `principal_type`，否则全员可见；回归测试须保留并扩充"不可读库不得泄漏"断言。
- 检索审计 payload 不含 chunk 正文与完整查询词。
- admin 是否天然可见全部知识库由 `w3-03` 决定；本 spec 假定其已统一权限判定（无独立 `list_all()` 绕过），三级 ACL 在此之上叠加，不重新引入绕过。
- `knowledge_base_grants.principal_id` 需与 `w3-03` 用户/角色模型对齐；若已扩展部门/角色组，`principal_type` 需同步扩展（默认仅 `user`）。

## 测试策略

- 单测：`uv run pytest tests/unit/knowledge -q`；`uv run pytest tests/unit/db/test_repo_knowledge.py -q`。
- 集成：`uv run pytest tests/integration/test_knowledge_bases_api.py -q`（grants 201/403/404）；`uv run pytest tests/integration/test_postgresql_control_plane.py -q`（需 `OCTOP_TEST_DATABASE_URL`，前置 `w0-02`）。
- 前端：`cd dashboard && npx tsc -b`；若已接入 vitest 追加对应用例。
- 断网：容器内 `uv sync --offline` 后 `uv run pytest -m 'not live' -q` 全绿；检索路径 monkeypatch httpx 断言零出网。
- i18n：`uv run pytest tests/unit/i18n -q`（若 `w0-04` 已让对等测试读 overlay 合并 bundle，新 key 自动纳入）。
- 全量：`make all`。

## 与其他 spec 的交接

- 依赖 `w3-03`：`list_visible` admin 绕过删除、权限判定收口先行，本 spec 在其上加 `visibility`/`grants`。
- 依赖 `w2-03`：控制面数据库方言定稿，fork 迁移双写遵循其约定。
- 依赖 `w0-01`：fork 迁移 runner 与 `_fork_schema_version`；本 spec 的迁移对由其执行，不接入上游 `migrate.py`。
- 依赖 `w0-04`：i18n overlay 路径/深合并、`CHANGELOG-intranet.md`/`docs/api-intranet.md` 骨架，本 spec 只追加内容。
- 依赖 `w2-01`：全局断网开关与离线消费改造；本 spec 假定已生效，不重复实现。
- 依赖 `w1-02`：能力开关框架；rerank 能力探测复用，不另起机制。
- 交付给下游：`p2-02`（若知识库凭据需国密改造，复用本 spec 的 provider 接入范式）；知识库三级 ACL 成为唯一权限入口，未来新入口须复用 `list_visible`。
- 归别的 spec：`list_visible` admin 绕过删除（`w3-03`）；断网开关本身（`w2-01`）；PG/信创库方言选型（`w2-03`）；向量数据强制入信创库（独立立项）；国密算法（`p2-02`）；overlay 深合并机制（`w0-04`）。

## 风险与回滚

- v1 检测不到位时 `retrieve.py` 现状把异常吞掉只记 warning、返回空串，表现为"静默失灵"；`needs_rebuild()` 须有显式日志与 capability 降级标志。
- `list_visible` 改写漏过滤 `principal_type` 会越权；须保留并扩充"不可读库不得泄漏"回归用例。
- FTS5 若目标环境未编译，字面通道整体降级为纯向量；实施前须用最小探测脚本确认目标环境（非本机开发环境）编译选项，探测失败则下调验收目标，不阻塞交付。
- 分词词典变更会使已建索引 `token_text` 失效，等同又一次全量重建；金融术语分词质量依赖行内词典。
- 回滚：fork 迁移与索引重建均是加列/可重建操作；禁用新检索路径（保留旧 `search()` 壳）即退回原行为，无需回滚数据。

## 待行方确认

- D2：若无 Embedding 服务，检索降级为纯全文，工作量重估。
- D3：若要求向量数据强制入信创库，PG/信创向量后端从可选变必做。
- D8：若一期即强制算法替换，rerank/embedding 凭据传输需提前接入国密改造。
- 新问题：授权是否需按角色/部门而非仅按用户——`users` 表无组织维度（D14 不在本轮范围），若需要须先由用户体系改造支撑，`principal_type` 相应扩展，属范围外变更。
