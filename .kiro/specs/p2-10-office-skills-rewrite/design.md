# 设计文档：Office 技能自研替换

> spec：`p2-10-office-skills-rewrite` ｜ 波次：二期 ｜ 基线：`757fd12` ｜ 预估：12-16 人日
> 前置：`w2-02-supply-chain-compliance` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 概述

`w2-02` 已删除四个技能的 `LICENSE.txt` 与旧 `scripts/` 树，只留 `SKILL.md` 骨架。本 spec 用
仓库已有的许可证干净第三方库重新实现脚本、新写 `SKILL.md` 正文、升版
`builtin_skill_version`，把 `office-automation` 专家的四类办公能力找补回来。**本 spec 不做任何
依赖增删、许可证扫描、SBOM、CI 闸门改动**——那些是 `w2-02` 的交付物，本 spec 只消费其结果。

## 现状（基线 757fd12 实测；二期实施时以当时代码重新定位）

- `src/octop/infra/agents/experts/library/office-automation/skills/` 下有 `docx/`、`xlsx/`、
  `pptx/`、`pdf/`、`file_reader/`、`news/` 六个技能目录（已用 `ls` 核实存在）。
- 四份 `SKILL.md` 头部结构一致（已用 `sed -n '1,10p'` 核实 `docx/SKILL.md`）：
  第 2 行 `name: docx`、第 3 行 `description: "..."`（技能触发文案）、第 4 行
  `license: Proprietary. LICENSE.txt has complete terms`、第 5 行 `metadata:`、第 6 行
  `  builtin_skill_version: "1.1"`。`w2-02` 落地后第 4 行应已消失，其余行号据此上移一行——
  二期实施时需重新 `sed -n` 核实实际行号，不假设行号不变。
- `pyproject.toml` ≈L42-47（已用 `grep -n` 核实）：`pypdf>=5.0`、`python-docx>=1.2.0`、
  `python-pptx>=1.0`、`pypinyin>=0.53`（**不是**替代库，勿混入）、`openpyxl>=3.1`、
  `xlrd>=2.0.1`。五个替代库均已是现有依赖，本 spec 预期零新增依赖。
- `tests/unit/agents/test_expert_catalog.py::test_bundled_office_automation_discovers_skills`
  （函数体 ≈L235-251，已用 `sed -n` 核实）：`assert len(expert.files) > 50`、
  `assert "skills/docx/SKILL.md" in names`、`assert "DOCX" in docx_skill`。
- `src/octop/infra/agents/experts/catalog.py::discover_seed_paths`（≈L148，已用 `grep -n` 核实）
  遍历技能目录下全部文件（排除 `manifest.json`）计入 `expert.files`。
- `src/octop/infra/errors.py:91` 已有 `ErrorCode.KNOWLEDGE_PREREQUISITES_FAILED`（已核实），
  与本 spec 无直接关系，仅作为"复用既有码"的参考先例。
- 二期实施时，上述除 `pyproject.toml` 依赖清单外的路径与行号大概率已因 `w1-`~`w4-` 系列 spec
  变化，落地前必须用 `rg`/`sed -n` 重新定位，不得照抄本文档行号。

## 方案

1. 在四个技能目录下新建 `scripts/`（新增文件，`w2-02` 已清空该目录），用五个既有依赖分别
   实现各技能的主干能力：docx 创建/读取/编辑/查找替换、xlsx 读写/重算、pptx 新建/编辑/缩略图、
   pdf 表单填写/拆分/信息提取。不追求逐字节复刻旧实现的全部高级能力（如 Word 修订痕迹
   redlining）；若行方要求完整复刻，需求 1/2 之外另立工作量。
2. 若脚本内部需要 OOXML XSD 做结构校验，从 ECMA-376 官方发布包重新下载并在校验模块头部
   注明出处 URL 与版本，不得从 git 历史中恢复 `w2-02` 删除的旧 XSD（旧 XSD 属于被清除的
   `LICENSE.txt` 覆盖范围）。
3. 新写四份 `SKILL.md` 正文（原文件已由 w2-02 删除）（含 `pptx/editing.md`、`pptx/pptxgenjs.md`、`pdf/forms.md`、
   `pdf/reference.md`，如二期实施时 `w2-02` 也已清空则视为新增）为面向新脚本的使用说明；
   `name`、`description`、`metadata.octop.label/summary` 原样保留；`builtin_skill_version`
   由 `w2-02` 落地后的值升到 `"2.0"`。
4. 同步调整 `test_bundled_office_automation_discovers_skills` 的文件数下限与内容断言，使其
   反映新实现的真实文件数（不得为了凑数保留无意义的空文件）。

## 组件与接口

| 路径 | 改动 |
|---|---|
| `src/octop/infra/agents/experts/library/office-automation/skills/docx/scripts/` | 新增：基于 `python-docx` 的创建/读取/编辑/查找替换脚本 |
| `.../skills/xlsx/scripts/` | 新增：基于 `openpyxl`（写）+ `xlrd`（读旧版 `.xls`）的脚本 |
| `.../skills/pptx/scripts/` | 新增：基于 `python-pptx` 的脚本 |
| `.../skills/pdf/scripts/` | 新增：基于 `pypdf` 的脚本 |
| `.../skills/{docx,xlsx,pptx,pdf}/SKILL.md` | 新建（原目录已由 `w2-02` 整体删除）：按新实现编写正文，`builtin_skill_version` 取 `2.0`（高于被删旧版本，便于存量工作区同步识别） |
| `.../skills/pptx/editing.md`、`pptxgenjs.md`、`pdf/forms.md`、`pdf/reference.md` | 修改或新增：随新脚本能力重写 |
| `tests/unit/agents/test_expert_catalog.py` | 修改：`test_bundled_office_automation_discovers_skills` 的文件数与内容断言 |

不新增模块、不新增函数签名约定——四个技能目录各自是独立的 Markdown + 脚本包，由
`harness-agent` 侧的技能加载机制消费（`octop` 侧不解析脚本内容，只搬运文件），因此无需
在 Octop 代码里定义新的 Python 接口。

## 数据模型

无（不涉及数据库表结构变更）。

## 配置

无新增 `config.py` 配置键。

## 错误处理

不新增 `ErrorCode`。新脚本对用户输入错误（如损坏的 `.docx`）的处理，复用调用方（技能执行
框架）既有的错误上抛路径；不在本 spec 引入新的错误分类。

## 安全考虑

- 新脚本仅处理办公文档格式解析/生成，不引入网络请求；沿用现有技能执行沙箱边界
  （`w3-06` 的收紧范围覆盖工具执行面，本 spec 不重复定义）。
- XSD 校验（如启用）应防范 XML 实体扩展攻击，复用 `defusedxml` 或所选库自带的安全解析开关
  （落地时确认所选库版本的默认行为，不默认信任第三方库的"安全默认值"宣传）。

## 测试策略

- 单测：`uv run pytest tests/unit/agents/test_expert_catalog.py -q`
  验证 `office-automation` 专家文件发现与 `docx/SKILL.md` 内容断言。
- 单测：`uv run pytest tests/unit/agents -q` 覆盖专家目录相关的其余既有用例，确认无连带回归。
- 集成：若新脚本引入独立的单元测试文件（如 `tests/unit/agents/office_skills/test_docx.py`
  之类，具体路径二期实施时新定），用 `uv run pytest tests/unit/agents/office_skills -q`
  （示例路径，落地时按实际新增测试目录调整命令）驱动脚本本身的正确性验证。
- 前端：不涉及 `dashboard/` 改动，无需 `npx tsc -b`。
- PG：不涉及数据库，无需 PG 集成用例。
- 许可证闸门回归：`grep -nE 'pymupdf|AGPL' src/octop/infra/agents/experts/library/office-automation/` 应无命中（人工检查，`make license-check` 由 `w2-02` 提供后一并跑）。

## 与其他 spec 的交接

- **依赖 `w2-02-supply-chain-compliance`**：`w2-02` 先删除四个技能的 `LICENSE.txt` 与旧
  `scripts/` 树、清理 `pyproject.toml`/`uv.lock` 中的 `edge-tts`/`pymupdf`/`pynput`、建立
  `make license-check` 闸门。本 spec 的第一个任务即确认该前置已合入。
- **交付给**：无下游 spec 直接依赖本 spec 的产出；office-automation 专家的可用性面向最终
  用户，属于产品能力交付，不是其他 spec 的技术前置。
- **看似相关但归别的 spec**：
  - `infra/knowledge/ocr.py` 中 pymupdf 依赖点改造 → `w2-02`。
  - `pyproject.toml`/`uv.lock` 依赖增删、SBOM、`docs/third-party-licenses.md`、`NOTICE` → `w2-02`。
  - 腾讯专有声明文件（`feishu_bot_creator.py`/`yuanbao_bot_creator.py`）处置 → `w1-01`/`w2-02`
    （源材料未明确切分，以 `w2-02` 落地时的实际归属为准，本 spec 不涉及）。
  - `dashboard/src/locales/{en,zh}.json` 中 `voice.browserNoChineseVoice` 文案改写 → `w1-05`。
  - 存量 Agent 工作区批量 reseed 机制本体的新建 → 不属于本 spec；本 spec 只提供
    `builtin_skill_version` 升版这一触发信号，具体重刷逻辑复用二期落地时已有的机制。

## 风险与回滚

- **风险**：旧脚本的高级能力（如 Word 修订痕迹 redlining、复杂 OOXML 校验）在新实现里可能
  缺失或行为不同，用户可感知的功能退化。缓解：先交付主干能力（创建/读取/编辑/格式转换），
  在 `docs/api-intranet.md` 或技能说明中明确标注当前不支持的能力范围。
- **风险**：`test_bundled_office_automation_discovers_skills` 的文件数断言依赖新实现的实际
  文件数，若脚本拆分粒度导致文件数逼近或低于历史下限，测试需要同步调整而非强行凑数。
- **回滚**：四个技能目录整体回退到 `w2-02` 落地后的骨架状态（仅 `SKILL.md`，无
  `scripts/`），`builtin_skill_version` 保持 `w2-02` 后的值不升级；`office-automation`
  专家的其余两个技能（`file_reader`、`news`）不受影响。

## 待行方确认

- 无（本 spec 不涉及 `.kiro/steering/intranet-transformation.md` 第 4 节 D1-D14 任何一项；
  是否要求完整复刻 Word 修订痕迹能力属于产品范围裁定，不是该节列出的待拍板项，若行方有
  明确要求应在落地前作为任务范围调整，而非阻塞项）。
