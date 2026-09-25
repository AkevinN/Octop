# 实施计划：知识库检索重写与三级权限

> spec：`p2-05-knowledge-retrieval` ｜ 波次：二期 ｜ 基线：`757fd12` ｜ 预估：35 人日
> 前置：`w3-03-authorization-foundation`、`w2-03-database-adaptation` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

每个顶层任务完成后可独立提交；提交前运行任务内的验证命令。

- [ ] 1. 确认前置 spec 已合入并记录基线
  - 改动：无代码改动。用 `rg` 核实 `w3-03`/`w2-03`/`w0-01`/`w0-04` 均已合入；记录 `git rev-parse HEAD` 作为实施基线，重新核实 design.md 中"实施时以一期落地后代码重新定位"各路径的真实行号。
  - 验证：`git log --oneline -5`；`rg "list_visible" src/octop/infra/db/repos/knowledge.py`
  - _需求：4.5_

- [ ] 2. 索引 schema v2 与去全表扫描
  - [ ] 2.1 重写 `KnowledgeIndex`：`schema_meta` 表、`chunks` 增列、`chunks_fts` 虚表、`search_vector`/`search_lexical`、旧 `search()` 兼容壳、`needs_rebuild`/`rebuild_meta`
    - 验证：`uv run pytest tests/unit/knowledge/test_index.py -q`
    - _需求：1.1, 1.4_
  - [ ] 2.2 新增 `lexical.py`（分词/BM25/FTS5 探测）与 `test_lexical.py`（含银行语料、FTS5 不可用降级用例）
    - 验证：`uv run pytest tests/unit/knowledge/test_lexical.py -q`
    - _需求：2.1, 2.2, 2.3_
  - [ ] 2.3 新增 `fusion.py`（RRF、确定性 tie-break）与 `test_fusion.py`
    - 验证：`uv run pytest tests/unit/knowledge/test_fusion.py -q`
    - _需求：1.2, 1.3_

- [ ] 3. 结构感知切分
  - 改动：重写 `chunk.py` 内部为 `split_structured`，`chunk_text()` 签名不变；扩写 `test_chunk.py`（标题/中文句末/表格行/幂等，保留旧用例）
  - 验证：`uv run pytest tests/unit/knowledge/test_chunk.py -q`
  - _需求：3.1, 3.2, 3.3, 3.4_

- [ ] 4. 可选重排
  - 改动：新增 `rerank.py`（对齐 `embed.py` 的 provider 接入范式，超时/异常降级为原序）、`gate.py` 增 `rerank` capability 字段；新增 `test_rerank.py`（未配置/超时/成功三路径）
  - 验证：`uv run pytest tests/unit/knowledge/test_rerank.py -q`
  - _需求：6.3, 6.4_

- [ ] 5. 检索编排重写
  - 改动：重写 `retrieve.py`（ACL 过滤→并发检索→RRF→可选 rerank→父窗口扩展，`retrieve_context` 新增 `lexical`/`rerank` 关键字参数且带默认值）；同步 `tools.py` 的 `search_knowledge` 调用；扩写 `test_retrieve.py`（保留既有"不可读库不得泄漏"断言）
  - 验证：`uv run pytest tests/unit/knowledge/test_retrieve.py tests/unit/knowledge/test_knowledge_tools.py -q`
  - _需求：1.1, 1.2, 4.5_

- [ ] 6. 三级 ACL：fork 迁移与 repo 层
  - [ ] 6.1 新增 fork 迁移对 `forkNNN_knowledge_acl_and_index.sql`/`.pg.sql`（`visibility` 列 + `knowledge_base_grants` 表，遵循 §7 资源表约定，表名不得为 `knowledge_base_members`），由 `w0-01` 的 fork runner 执行，不改 `migrate.py`
    - 验证：本地跑一次 fork 迁移 runner（命令随 `w0-01` 落地方式补全）；`sqlite3 <test_db> '.schema knowledge_base_grants'`
    - _需求：4.1, 4.4_
  - [ ] 6.2 `repos/knowledge.py`：行加 `visibility`、`list_visible` 改写为 `owner_user_id = ? OR visibility = 'org' OR EXISTS(grant)`、新增 grants CRUD；扩写 `test_repo_knowledge.py`（含 `principal_type` 过滤负向用例）
    - 验证：`uv run pytest tests/unit/db/test_repo_knowledge.py -q`
    - _需求：4.1, 4.2, 4.3, 4.4, 4.5_
  - [ ] 6.3 `service.py`：读写判定加 grant，新增 `grant_access`/`revoke_access`/`list_grants`；扩写 `test_service_acl.py`（reader/editor 读写矩阵、撤销即时生效、`visibility=org` 与旧 `shared` 等价）
    - 验证：`uv run pytest tests/unit/knowledge/test_service_acl.py -q`
    - _需求：4.1, 4.2, 4.3, 4.4_

- [ ] 7. 三条检索入口口径统一
  - 改动：核对 `gateway/process/processor.py`、`cron/delivery.py` 的知识库可见库判定均经过 `list_visible`（不重新引入 admin 绕过分支）；新增覆盖三入口一致性的用例（cron 路径不得把未授权库带入 `stamp_turn_knowledge_config`）
  - 验证：`uv run pytest tests/unit/knowledge tests/unit/gateway -k knowledge -q`
  - _需求：4.5_

- [ ] 8. v1→v2 自动重建
  - 改动：`jobs.py` 用 `split_structured` 结果写 `metadata`/`token_text`，新增 `resume_stale_index_schema`；`server.py` 启动路径追加调用（`contextlib.suppress` 包裹）；新增 `test_index_migration.py`，扩写 `test_jobs.py`
  - 验证：`uv run pytest tests/unit/knowledge/test_index_migration.py tests/unit/knowledge/test_jobs.py -q`
  - _需求：5.1, 5.2, 5.3_

- [ ] 9. 检索审计
  - 改动：`retrieve.py` 检索结束通过 `getattr(services, "audit_repo", None)` 写 `knowledge.retrieve`；新增 `test_retrieve_audit.py`（含 payload 不泄漏正文、缺 `audit_repo` 不抛错两条断言）
  - 验证：`uv run pytest tests/unit/knowledge/test_retrieve_audit.py -q`
  - _需求：6.1, 6.2_

- [ ] 10. HTTP 路由、错误码、i18n overlay、参数面
  - 改动：`params.py` 新增可调参数；`routers/knowledge_bases.py` 扩展 `_capability_payload`、新增 `PUT /advanced-settings`、`PUT /feature` 加 rerank 字段（不入重建判定）、新增 grants 三条路由（须在 `GET /{kb_id}` 之前声明）；`openapi_meta.py` 改 knowledge tag 描述；`errors.py` 追加 3 个 `KNOWLEDGE_*` 码及 `_DEFAULT_STATUS`；新增文案写入 i18n intranet overlay（不改上游 JSON）；扩写对应单测与集成测试
  - 验证：`uv run pytest tests/unit/api/test_knowledge_bases.py tests/integration/test_knowledge_bases_api.py tests/unit/i18n -q`
  - _需求：4.2, 4.3, 6.4_

- [ ] 11. 前端：visibility/grants/高级参数 UI
  - 改动：`knowledgeBases.ts` 补类型与 `listGrants`/`addGrant`/`removeGrant`/`updateAdvancedSettings`；`KnowledgeBases/index.tsx` 把 `shared` 开关换成 `visibility` 三选，新增高级检索参数折叠面板；新增 `GrantsPanel.tsx`
  - 验证：`cd dashboard && npx tsc -b`
  - _需求：4.1, 4.2, 4.3_

- [ ] 12. 收尾：全量门槛与文档
  - 改动：新增 `docs/knowledge-retrieval.md`（schema v2、检索流程、参数、权限三档、v1→v2 迁移、断网部署清单）；补 `docs/configuration.md`；`docs/api.md` 新建 Knowledge bases 一节；新增 `scripts/bench_knowledge.py`；更新 `CHANGELOG-intranet.md`/`docs/api-intranet.md`
  - 验证：`make all`；`cd dashboard && npx tsc -b && npm run lint`（有 vitest 则加 `npm run test`）；`uv run pytest -m 'not live' -q`
  - _需求：全部_
