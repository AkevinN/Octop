# 实施计划：Office 技能自研替换

> spec：`p2-10-office-skills-rewrite` ｜ 波次：二期 ｜ 基线：`757fd12` ｜ 预估：12-16 人日
> 前置：`w2-02-supply-chain-compliance` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

每个顶层任务完成后可独立提交；提交前运行任务内的验证命令。

- [ ] 1. 确认前置 spec 已合入并记录基线
  - 改动：无代码改动，仅核实。确认 `w2-02-supply-chain-compliance` 已合入 `develop`：
    四个技能目录下 `LICENSE.txt` 与旧 `scripts/` 已删除，`pyproject.toml` 已无
    `pymupdf`/`edge-tts`，`make license-check` 已存在。记录当时的 commit 作为本 spec 的
    实际起点（区别于本文档撰写时的 `757fd12`）。
  - 验证：`rg -n "pymupdf|edge-tts" pyproject.toml`（应无输出）；
    `ls src/octop/infra/agents/experts/library/office-automation/skills/docx/`（应无
    `LICENSE.txt`、无 `scripts/`）。
  - _需求：全部_

- [ ] 2. docx 技能自研实现
  - [ ] 2.1 先写会失败的测试：为新脚本的核心函数（创建/读取/编辑/查找替换）补单元测试，
    断言当前因脚本不存在而失败
    - 验证：`uv run pytest tests/unit/agents/office_skills/test_docx.py -q`（预期失败，
      路径为落地时新增，示例名）
    - _需求：1.1_
  - [ ] 2.2 实现 `skills/docx/scripts/`（基于 `python-docx`），使 2.1 测试转绿
    - 改动：新增 `src/octop/infra/agents/experts/library/office-automation/skills/docx/scripts/`
    - 验证：`uv run pytest tests/unit/agents/office_skills/test_docx.py -q`
    - _需求：1.1_
  - [ ] 2.3 新建 `docx/SKILL.md`，升 `builtin_skill_version` 到 `"2.0"`，保留
    `name`/`description`/`metadata.octop.label/summary`
    - 验证：`git diff --stat` 人工核对 `name`/`description` 未变；
      `grep -n "builtin_skill_version" src/octop/infra/agents/experts/library/office-automation/skills/docx/SKILL.md`
    - _需求：1.2, 1.3_

- [ ] 3. xlsx 技能自研实现
  - [ ] 3.1 先写会失败的测试，覆盖读写（`openpyxl`）与旧版 `.xls` 读取（`xlrd`）
    - 验证：`uv run pytest tests/unit/agents/office_skills/test_xlsx.py -q`（预期失败）
    - _需求：2.1_
  - [ ] 3.2 实现 `skills/xlsx/scripts/`，使 3.1 测试转绿；新建 `SKILL.md`、升版本号
    - 验证：`uv run pytest tests/unit/agents/office_skills/test_xlsx.py -q`
    - _需求：2.1, 2.4_

- [ ] 4. pptx 技能自研实现
  - [ ] 4.1 先写会失败的测试，覆盖新建/编辑演示文稿（`python-pptx`）
    - 验证：`uv run pytest tests/unit/agents/office_skills/test_pptx.py -q`（预期失败）
    - _需求：2.2_
  - [ ] 4.2 实现 `skills/pptx/scripts/`，使 4.1 测试转绿；新建 `SKILL.md`、`editing.md`、
    `pptxgenjs.md`、升版本号
    - 验证：`uv run pytest tests/unit/agents/office_skills/test_pptx.py -q`
    - _需求：2.2, 2.4_

- [ ] 5. pdf 技能自研实现
  - [ ] 5.1 先写会失败的测试，覆盖表单填写/拆分/信息提取（`pypdf`，不得引入 `pymupdf`）
    - 验证：`uv run pytest tests/unit/agents/office_skills/test_pdf.py -q`（预期失败）
    - _需求：2.3_
  - [ ] 5.2 实现 `skills/pdf/scripts/`，使 5.1 测试转绿；新建 `SKILL.md`、`forms.md`、
    `reference.md`、升版本号；如需 XSD 校验则从 ECMA-376 官方包重新获取并注明出处
    - 验证：`uv run pytest tests/unit/agents/office_skills/test_pdf.py -q`；
      `rg -n "pymupdf" src/octop/infra/agents/experts/library/office-automation/`（应无输出）
    - _需求：2.3, 2.4, 4.2_

- [ ] 6. 同步专家目录测试断言
  - 改动：`tests/unit/agents/test_expert_catalog.py` 的
    `test_bundled_office_automation_discovers_skills`，按新实现的实际文件数与内容调整
    `len(expert.files) > 50` 等断言
  - 验证：`uv run pytest tests/unit/agents/test_expert_catalog.py -q`
  - _需求：3.1, 3.2, 3.3_

- [ ] 7. 许可证与依赖回归检查
  - 改动：无代码改动，核实本 spec 未新增任何 Python 依赖
  - 验证：`git diff --stat pyproject.toml uv.lock`（应为空）；
    `rg -n "pymupdf|AGPL" src/octop/infra/agents/experts/library/office-automation/`（应无输出）
  - _需求：4.1, 4.2_

- [ ] 8. 存量工作区版本感知验证
  - 改动：无新代码（复用既有 `builtin_skill_version` 机制）；如二期落地时该机制仍不存在，
    在此任务内改为记录待确认项并停止，不新建 reseed 框架
  - 验证：人工核对四份 `SKILL.md` 的 `builtin_skill_version` 均为 `"2.0"`：
    `grep -rn "builtin_skill_version" src/octop/infra/agents/experts/library/office-automation/skills/{docx,xlsx,pptx,pdf}/SKILL.md`
  - _需求：5.1, 5.2_

- [ ] 9. 收尾：全量验证与文档更新
  - 改动：更新 `CHANGELOG-intranet.md`（记录四个技能自研替换、`builtin_skill_version`
    升版）；如新增了面向用户的 API 无则不改 `docs/api-intranet.md`
  - 验证：`make all` 全绿；`uv run pytest tests/unit/agents -q`；
    （无 `dashboard/` 改动，跳过 `npx tsc -b`）
  - _需求：全部_
