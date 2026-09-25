# 需求文档：Office 技能自研替换

> spec：`p2-10-office-skills-rewrite` ｜ 波次：二期 ｜ 基线：`757fd12` ｜ 预估：12-16 人日
> 前置：`w2-02-supply-chain-compliance` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 引言

`w2-02` 出于许可证合规，删除了 `office-automation` 专家下 `docx`/`xlsx`/`pptx`/`pdf` 四个技能的
`LICENSE.txt`（Anthropic 专有声明）与全部 `scripts/` 脚本树，仅保留四份 `SKILL.md` 骨架（已被
`w2-02` 剥离 `license:` 字段）。此后四个技能事实上不可用：`SKILL.md` 无脚本可跑，`expert.files`
数量跌破既有测试断言的下限。

本 spec 只做一件事：用许可证干净的第三方库（`pypdf`、`python-docx`、`python-pptx`、`openpyxl`、
`xlrd` —— 均已是 `pyproject.toml` 现有依赖，见 ≈L42-47）重新实现这四个技能的脚本，挂回
`office-automation` 专家目录，使技能重新可用，并让存量 Agent 工作区通过 `builtin_skill_version`
升版感知到新实现。

**范围内：**
- 四个技能目录下 `scripts/` 的自研实现（创建/读取/编辑/格式转换等主干能力）。
- 四份 `SKILL.md`（以及 `pptx/editing.md`、`pptx/pptxgenjs.md`、`pdf/forms.md`、`pdf/reference.md`）
  正文重写为面向新脚本的使用说明；`name`、`description`、`metadata.octop.label/summary`
  保持不变；`builtin_skill_version` 从 `"1.1"` 升到 `"2.0"`。
- 若脚本仍需 OOXML XSD 校验，XSD 从 ECMA-376 官方发布包重新获取，不得从已删除的旧目录恢复。
- 同步调整 `tests/unit/agents/test_expert_catalog.py::test_bundled_office_automation_discovers_skills`
  的文件数与内容断言。

**范围外（归其他 spec）：**
- 删除 `LICENSE.txt`、旧 `scripts/` 脚本树、`pyproject.toml` 里 `edge-tts`/`pymupdf`/`pynput` 依赖、
  `uv.lock` 重生成、SBOM/许可证扫描 CI 闸门、`NOTICE`/`docs/third-party-licenses.md`：全部属于
  `w2-02-supply-chain-compliance`，本 spec 不重复处理，只消费其已完成的删除结果。
- `infra/knowledge/ocr.py` 中 pymupdf 依赖点的改造：属于 `w2-02`。
- 腾讯专有声明文件（`feishu_bot_creator.py` / `yuanbao_bot_creator.py`）处置：属于 `w1-01`
  或 `w2-02`（源材料未明确切分，落地时以 `w2-02` 的实际归属为准）。
- 前端 `voice.browserNoChineseVoice` 文案改写：属于 `w1-05`。
- 存量 Agent 工作区技能 reseed 机制本体（如果需要新的批量刷新流程）：不在本 spec 新建，只调用
  既有 `builtin_skill_version` 感知机制（若二期落地时仍不存在批量 reseed，需求 6 转为待确认项）。

## 需求

### 需求 1：docx 技能自研实现
**用户故事：** 作为使用 office-automation 专家的用户，我希望在断网环境下仍能创建、读取、编辑
Word 文档，以便获得合规、可用的 docx 能力。

#### 验收标准
1. 当技能被加载执行创建/读取/编辑 `.docx` 的典型操作时，新脚本应当基于 `python-docx`
   （MIT）完成，不依赖已被 `w2-02` 删除的旧脚本或其任何残留文件。
2. `docx/SKILL.md` 的 `name`、`description`、`metadata.octop.label/summary` 应当与改造前
   逐字一致；`license:` 字段应当保持缺失（不得恢复）；`builtin_skill_version` 应当为 `"2.0"`。
3. 如果脚本需要 OOXML XSD 校验，那么 XSD 应当标注取自 ECMA-376 官方发布包的出处说明。

### 需求 2：xlsx / pptx / pdf 技能自研实现
**用户故事：** 作为使用 office-automation 专家的用户，我希望电子表格、演示文稿、PDF 三类技能
与 docx 同批恢复可用，以便专家的四类办公能力保持一致体验。

#### 验收标准
1. 当技能执行电子表格读写时，新脚本应当基于 `openpyxl`（MIT，写）与 `xlrd`（BSD，读旧版
   `.xls`）实现。
2. 当技能执行演示文稿创建或编辑时，新脚本应当基于 `python-pptx`（MIT）实现。
3. 当技能执行 PDF 表单填写、拆分、信息提取等操作时，新脚本应当基于 `pypdf`（BSD-3-Clause）
   实现，不引入 `pymupdf` 或任何 AGPL/GPL 许可证的库。
4. 每个技能新建的 `SKILL.md` 正文应当遵循需求 1 验收标准 2、3 的同等约束。

### 需求 3：专家目录文件数与测试断言同步
**用户故事：** 作为维护 CI 门禁的工程师，我希望 `test_expert_catalog.py` 的断言反映新实现后的
真实文件数与内容，以便该测试继续起到防回归作用而不是变成误导性的绿灯。

#### 验收标准
1. 当 `ExpertCatalog.refresh()` 扫描 `office-automation` 目录时，`expert.files` 的数量应当
   大于测试里声明的下限（当前为 `> 50`，四个技能自研实现落地后按实测值调整，不得低于 50）。
2. `"skills/docx/SKILL.md"` 应当仍出现在 `catalog.read_file_contents("office-automation")`
   返回的文件名集合中。
3. `docx/SKILL.md` 的新正文中应当仍包含大写 `"DOCX"` 字样，使既有断言 `assert "DOCX" in
   docx_skill` 不必删除即可通过（如内容改写导致该词消失，须同步修改该断言并说明理由）。

### 需求 4：许可证闸门通过
**用户故事：** 作为负责合规的工程师，我希望新引入的任何依赖都已在 `w2-02` 的许可证白名单内，
以便本 spec 的改动不会让 `make license-check`（`w2-02` 交付）变红。

#### 验收标准
1. 如果本 spec 的脚本实现需要新增 Python 依赖（当前假设为零新增，五个替代库均已在
   `pyproject.toml` ≈L42-47），那么该依赖必须先通过 `w2-02` 建立的许可证扫描且不属于
   AGPL/GPL/LGPL。
2. 当 `docx`/`xlsx`/`pptx`/`pdf` 四个技能目录被扫描时，其中不应当再出现任何 `pymupdf`
   引用或依赖提示。

### 需求 5：存量工作区版本感知
**用户故事：** 作为运维人员，我希望已创建的 Agent 工作区能感知到 office 技能已升级，以避免
终端用户停留在旧的、不可用的技能骨架上。

#### 验收标准
1. `builtin_skill_version` 应当始终随四份 `SKILL.md` 一起从 `"1.1"` 升到 `"2.0"`。
2. 在<存量工作区下一次技能同步/reseed 触发>期间，系统应当以新版本号覆盖旧技能内容（具体
   触发机制沿用二期落地时已有的 reseed 实现；若该机制彼时仍不存在，转入"待行方确认"）。
