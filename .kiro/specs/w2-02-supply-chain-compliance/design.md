# 设计文档：许可证与供应链合规

> spec：`w2-02-supply-chain-compliance` ｜ 波次：Wave 2 ｜ 基线：`757fd12` ｜ 预估：15 人日
> 前置：`w0-02-ci-gates`、`w0-04-fork-isolation-points`、`w1-02-capability-trim`、`w1-03-online-fetch-trim`、`w1-04-content-trim`、`w1-05-saas-decoupling` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 概述

**结论：** 契约是 `Makefile.intranet` 里的九个目标，判定逻辑集中在一个只用标准库的脚本 `scripts/intranet/supply_chain.py`，人工结论集中在一份策略文件 `supply-chain/license-policy.toml`。GitHub CI 与行内流水线都只调用这些目标。

- **删除，不改写。** 四个 Anthropic 专有技能整目录删除；自研替代归 `p2-10`。人设文件改为"文档技能由管理员以 ZIP 技能包导入"。i18n 零改动。
- **AGPL 不报备，直接移除。** `pymupdf` 唯一的使用点是 OCR 的 PDF 转图，改用已是核心依赖的 `pypdf` 抽取页内图片。扫描版 PDF 本来就是"每页一张图"，这条路径覆盖主要场景。
- **判定读已安装包，不读锁文件。** 实测锁文件缺许可证字段（npm 81 个生产条目），且元数据会自相矛盾（`fastembed`），也会漏掉 wheel 内捆绑的 LGPL 共享库（`opencv-python`、`shapely`）。闸门因此在独立环境 `build/compliance-venv` 里按"运行期闭包 + 全部非 dev extra"安装后逐包读取元数据与许可证文件。
- **策略文件自带防腐。** 每条人工结论都必须对应 `uv.lock` 或 `package-lock.json` 中仍存在的包，陈旧条目直接判红。其他 spec 负责删除的包（`pynput` 等）用带 owner 的 `transitional` 条目承接；owner spec 删掉包后，条目必须同批删除。
- **SCA / SAST / 签名选离线工具。** grype（关闭自更新与漏洞库自动更新，漏洞库由行方导入）、bandit（加入 dev 依赖、带基线）、openssl（`SHA256SUMS` 加分离签名）。三者都已在本环境实测过关键行为。
- **CI 只加步骤，不改语义。** 按 `w0-02` 的原则不动上游的 `all`、`check-all` 与 pre-commit；在 `ci.yml` 的三个 job 各加步骤，并用 fork 自有的契约测试守住。

## 现状

以下事实均在基线 `757fd12` 上核实；标注"实测"的数字来自本环境（Linux x86_64、uv 0.8.17）。

### 1. 仓库内的专有内容

- `src/octop/infra/agents/experts/library/office-automation/` 共 192 个文件。其中 `skills/docx` 61 个（`scripts/` 59 个）、`skills/pdf` 12 个（8 个）、`skills/pptx` 59 个（55 个）、`skills/xlsx` 54 个（52 个），四者合计 186 个；其余为 `IDENTITY.md`、`SOUL.md`、`USER.md`、`manifest.json`、`skills/file_reader/SKILL.md`、`skills/news/SKILL.md`（`news` 由 `w1-04` 删除）。
- 四份 `skills/*/LICENSE.txt` 的 md5 均为 `f8515c3694eb11622110ca76c7c15d1b`。首行为 `© 2025 Anthropic, PBC. All rights reserved.`；≈L16-21 禁止在 Anthropic 服务之外留存副本、复制、做衍生作品与分发。四份 `SKILL.md` 的 ≈L4 为 `license: Proprietary. LICENSE.txt has complete terms`，≈L6 为 `builtin_skill_version: "1.1"`。
- 分发路径：`pyproject.toml` 的 hatch `include`（≈L110）包含 `src/octop/infra/agents/experts/library/**/*`，所以这些文件进入 wheel。`src/octop/infra/agents/experts/catalog.py::discover_seed_paths`（≈L148）收录专家目录下除 `manifest.json` 外的全部文件；`seed_expert_directory`（≈L213）把它们上传进 Agent 工作区；调用点是 `src/octop/infra/agents/manager.py::_seed_expert_template`（≈L2440，≈L2486 调用）与 `src/octop/infra/agents/experts/published_creation.py`（≈L347）。
- 人设文件：`SOUL.md` ≈L7-16 为 "Bundled skills" 表，≈L23 要求 "PDF and Office files → use the matching skill"；`IDENTITY.md` ≈L18 写"全套文档技能开箱即用"，≈L29 与 ≈L31-38 列出 docx / xlsx / pptx / pdf；`USER.md` 与 `IDENTITY.md` 内容逐字相同；`manifest.json` 的 `description`（≈L7-10）写"内置 Word、Excel、PPT、PDF 全套文档技能"。
- 测试：`tests/unit/agents/test_expert_catalog.py::test_bundled_office_automation_discovers_skills`（≈L235）断言 `len(expert.files) > 50`（≈L243）、`"skills/docx/SKILL.md" in names`（≈L245）、`"DOCX" in docx_skill`（≈L251）。全仓 `tests/` 中再无其他用例引用 bundled 的四个技能；`test_skill_package_store.py` 与两个集成测试里的 `skills/pdf*` 是 `tmp_path` 合成数据。
- i18n：`tests/unit/i18n/test_skills.py` 只校验 `skill_display_name("pdf", "zh")`（≈L12）、`labels["docx"]`（≈L33）与前后端 `skills` 键逐条相等（≈L41-42），与技能目录是否存在无关。
- 腾讯专有头：`src/octop/infra/gateway/bot_creators/{feishu,yuanbao}_bot_creator.py` ≈L5 的 `Unauthorized copying, modification, distribution` 由 `w1-05` 随整个目录删除。
- 用精确标记在六个仓库目录（`src dashboard/src dashboard/public docker scripts plugins`）上检索，命中恰为上述 4 份 `LICENSE.txt`、4 份 `SKILL.md` 与 2 个 bot creator 文件。宽泛检索 `proprietary` 还会命中 6 个专家与子智能体提示词里的普通用词，不能用作标记。

### 2. 第三方包内的专有内容（本仓库改不了）

- `.venv` 中 `orcakit-harness-agent` 1.0.11 的 `harness_agent/builtin/skills/{en,zh}/powerpoint/` 含同一份 Anthropic `LICENSE.txt`（md5 相同）；两份 `SKILL.md` ≈L4 为 `license: Proprietary`；两目录共 100 个文件。该包 `METADATA` 声明 `License: MIT`。
- 同目录 `skill-creator/SKILL.md` ≈L38-40 自述 "a library-grade version of the original Anthropic `skill-creator` recipe"，包内无许可证文件。该包每种语言各 24 个技能，其中 7 个（中英共 14 份 `SKILL.md`，含 `skill-creator`）未写 `license` 字段。
- `harness_agent/init.py` ≈L125 在初始化工作区时调用 `sync_builtin_skills`，把包内技能写进 `{workspace}/_builtin_skills/`；`harness_agent/builtin/_sync.py::sync_builtin_skills_to_backend`（≈L33）按版本号覆盖写入，没有删除逻辑。
- 实测：在 compliance 环境的 site-packages 中，`Anthropic, PBC` 还出现在 `anthropic` 与 `mcp` 两个 MIT 包的版权行；换成 `Anthropic, PBC. All rights reserved` 与行首 `license: Proprietary` 后只命中 `powerpoint` 的 4 个文件。

### 3. Python 依赖许可证

- `uv.lock` 共 242 个 `[[package]]`。`pyproject.toml`：≈L10 `license = { text = "MIT" }`；≈L24 `orcakit-harness-agent[all]`；≈L38 `psycopg[binary]`；≈L42-44、≈L46-47 为 `pypdf`、`python-docx`、`python-pptx`、`openpyxl`、`xlrd`（≈L45 是 `pypinyin`）；≈L53-64 为 `[project.optional-dependencies].dev`；≈L70 `desktop = ["mss>=9.0", "pynput>=1.7"]`；≈L72 `local-embedding`；≈L73-77 `knowledge-ocr`（≈L76 `pymupdf>=1.24`）；≈L82-93 为 `[dependency-groups].dev`。
- 注意：`--all-extras` 会连带装入 `[project.optional-dependencies].dev`（实测装入了 `pytest`、`ruff`、`xlwt` 等），必须加 `--no-extra dev`。
- 实测 compliance 环境：`uv sync --frozen --no-dev --all-extras --no-extra dev --no-install-project` 装出 213 个分发包。与 `uv.lock` 的 242 个相差的 29 个里，1 个是项目自身 `octop`（`--no-install-project`），其余 28 个是 dev 专用（`pytest*`、`ruff`、`mypy`、`build`、`xlwt`、`coverage`、`pathspec` 等）或其他平台的条件依赖（`pywin32`、`pyobjc-*`、`win32-setctime`、`colorama`、`tzdata`、`audioop-lts`）。`discord.py` 的元数据名与锁文件名 `discord-py` 不同，匹配时必须按 PEP 503 规范化。
- 实测元数据（`License-Expression` / `License` / classifier）中需要处理的包：

| 包 | 版本 | 元数据 | 结论方向 |
|---|---|---|---|
| `pymupdf` | 1.28.2 | `License: Dual Licensed - GNU AFFERO GPL 3.0 or Artifex Commercial License` | 必须删（本 spec） |
| `edge-tts` | 7.2.8 | classifier LGPLv3 | 必须删（`w1-05` 已删） |
| `pynput` | 1.8.2 | `License: LGPLv3` + classifier | 必须删（`w2-01`） |
| `python-xlib` | 0.33 | `License: LGPLv2+` + classifier | 必须删（`w2-01`，仅经 `pynput` 引入） |
| `python-telegram-bot` | 22.8 | `LGPL-3.0-only` | 必须删（`w2-01` 重打包 `harness-gateway`） |
| `psycopg` / `psycopg-binary` / `psycopg-pool` | 3.3.4 / 3.3.4 / 3.3.1 | `LGPL-3.0-only` | 报备保留（D3 的 PG 驱动） |
| `certifi` / `bidict` | 2026.6.17 / 0.23.1 | `MPL-2.0` / `MPL 2.0` | 报备保留 |
| `orjson` | 3.11.9 | `MPL-2.0 AND (Apache-2.0 OR MIT)` | 报备保留（AND 无法择一规避） |
| `tqdm` | 4.68.3 | `License: MPL-2.0 AND MIT` | 报备保留 |
| `paho-mqtt` | 2.1.0 | `License: EPL-2.0 OR BSD-3-Clause` | 可保留，NOTICE 书面择 BSD-3-Clause |
| `fastembed` | 0.8.0 | `License: Apache License` 与 classifier `Other/Proprietary License` 矛盾 | 人工裁定：随包 `LICENSE` 为 Apache-2.0 全文 |
| `agent-client-protocol` | 0.11.0 | 三处元数据皆空；`dist-info/licenses/LICENSE` 为 Apache-2.0 全文 | 人工裁定（`w2-01` 收窄 `[all]` 后可能消失） |
| `deepagents-backends` | 0.2.0 | 元数据皆空；随包 `LICENSE` 为 MIT | 人工裁定 |
| `py-rust-stemmers` | 0.1.8 | 元数据皆空；随包 `LICENSE` 为 MIT | 人工裁定 |

- 实测捆绑库：按行匹配许可证文件中的 `GNU (LESSER |LIBRARY |AFFERO )?GENERAL PUBLIC LICENSE` 标题行，命中 9 个包。其中元数据为宽松许可的 3 个需要人工裁定：`opencv-python` 5.0.0.93（经 `rapidocr` 引入；`opencv_python.libs/` 含 `libQt5*`、`libavcodec` 等，`LICENSE-3RD-PARTY.txt` ≈L243 写明 FFmpeg、≈L710 写明 Qt 5 随包再分发）；`shapely` 2.1.2（经 `rapidocr` 引入；`shapely.libs/` 含 `libgeos`，`LICENSE_GEOS` 为 LGPL-2.1）；`numpy` 2.5.1（`numpy.libs/` 含 `libgfortran`，GPL-3.0 附 GCC 运行时库例外）。用宽泛的"正文出现 GPL 字样"规则会额外误报 `typing_extensions`、`aiohappyeyeballs`、`pillow` 等 7 个包，所以只匹配标题行。
- 实测按文件名（`LICENSE` / `LICENCE` / `COPYING` / `NOTICE` 或 `licenses/` 目录）检索，有 12 个包没有随包许可证文件（`antlr4-python3-runtime`、`esdk-obs-python`、`flatbuffers`、`langchain-community`、`langchain-text-splitters`、`langsmith`、`loguru`、`rapidocr`、`scalar_fastapi`、`sqlite-vec`、`tokenizers`、`wecom-aibot-sdk`），它们的元数据有明确许可证，不影响分类，但 `THIRD-PARTY-NOTICES.txt` 需要标注。
- 实测 `.venv`（开发环境）中 `fsspec` 为 2026.9.0，而 `uv.lock` 锁定 2026.7.0，说明开发环境不能作为判定依据。

### 4. npm 依赖许可证

- `dashboard/package-lock.json` 为 lockfileVersion 3，除根条目外 1125 个条目：`dev: true` 623 个、`devOptional: true` 2 个、其余 500 个为生产依赖。500 个中 81 个缺 `license` 字段（如 `@babel/runtime`、`dayjs`、`d3-shape`）。
- 生产依赖的许可证分布：MIT 353、ISC 34、Apache-2.0 15、BSD-3-Clause 9、BSD-2-Clause 1、`(MPL-2.0 OR Apache-2.0)` 2（`dompurify` 3.4.7 与 `monaco-editor/node_modules/dompurify` 3.2.7）、CC0-1.0 1（`highlightjs-vue`）、Unlicense 1（`robust-predicates`）、`(MIT AND Zlib)` 1、`MIT AND ISC` 1，以及 `jsmin` 1.0.1 的 "Doug Crockford's license that allows this module to be used for Good but not for Evil"（JSON 许可证，经 `build@0.1.4` 引入，`w1-04` 删除该依赖）。
- `xlsx` 0.18.5（Apache-2.0）是生产依赖，`dashboard/src/components/DocumentPreviewCore.tsx` ≈L452 动态导入。它是 SCA 首次分诊的预期对象（见"风险与回滚"）。
- 仓库中没有 `dashboard/node_modules`；`w0-02` 的 `make install-frontend` 负责安装。

### 5. 门禁与打包现状

- `Makefile`：`DIST_DIR`（≈L20）；`build-wheel` 在 ≈L111 执行 `rm -rf $(DIST_DIR)/*`；`all: format-all lint typecheck test`（≈L202）；`lint` 只查 `src tests`（≈L207-209）；`check-all`（≈L291）；`install` 在有 uv 时执行 `uv sync`（≈L303-310）。全文件没有 `licen`、`sbom` 字样。
- `.github/workflows/ci.yml`：`quality`（≈L14-42）与 `test-windows`（≈L44-66）都是 `make install / lint / typecheck / test`；`live-tests`（≈L68-129）。`w0-02` 在两者之后插入 `frontend`（只 `setup-node`，没有 `setup-uv`）与 `postgresql` 两个 job，并新增 `tests/unit/test_ci_gates_contract.py`。
- `.github/workflows/codeql.yml`：`languages: python`，`config-file: ./.github/codeql/codeql-config.yml`；后者只有 `paths-ignore` 两项（`fliggy.py`、`wecom_creds.py`）。
- `.gitignore`：`build/`（≈L2）、`dist/`（≈L5）已忽略，适合放 compliance 环境与产物。
- hatchling：uv 缓存中的 hatchling 1.32.4 在 `metadata/core.py` ≈L774 把默认 `license-files` 定为 `["LICEN[CS]E*", "COPYING*", "NOTICE*", "AUTHORS*"]`。根目录新增 `NOTICE` 会被自动放进 wheel 的 `dist-info/licenses/`，不需要改 `pyproject.toml`。
- `LICENSE` ≈L1-3 为 `MIT License` / `Copyright (c) 2026 Octop`；`README.md` ≈L538-540 与 `README_CN.md` ≈L532-534 为许可证小节。
- 测试加载 `scripts/` 下脚本的先例：`tests/unit/test_release_download_links.py` 用 `importlib.util.spec_from_file_location` 加载（该文件与被测脚本由 `w1-04` 删除，写法可沿用）。

### 6. OCR 与 `pymupdf`

- `src/octop/infra/knowledge/ocr.py`：`_LOCAL_PACKAGES`（≈L27）含 `pymupdf>=1.24`；`_PDF_SPEC`（≈L29）只装 `pymupdf`；`local_ocr_deps_available`（≈L73）与 `pdf_ocr_deps_available`（≈L82）用 `import pymupdf` 探测；`ensure_ocr_deps`（≈L90）两个分支的 `import_modules` 含 `pymupdf`（≈L97、≈L107）；`_image_inputs`（≈L232）对 PDF 用 `pymupdf` 以 2 倍矩阵逐页渲染成 PNG（≈L242-253）。本地 `_extract_local`（≈L266）与远程 `_RemoteOcr.__call__`（≈L286）都经 `_image_inputs` 取图。
- `src/octop/api/routers/knowledge_bases.py` ≈L407 在保存 OCR 设置时调用 `ensure_ocr_deps_async`。
- 全仓除 `ocr.py` 与 `pyproject.toml` ≈L76 外没有 `pymupdf` 引用；`tests/unit/knowledge/test_ocr.py::test_image_and_blank_pdf_use_ocr`（≈L78）注入假 OCR，从不进入 `_image_inputs` 的 PDF 分支。
- 实测：用 `PIL.Image.save(..., save_all=True)` 生成两页 PDF，`pypdf` 6.15.0 的 `page.images[i].image` 可逐张取出并存为 PNG；`PdfWriter.add_blank_page` 生成的空白页 `images` 为空。

### 7. 仓库内置的第三方内容

| 内容 | 位置与证据 | 许可证线索 |
|---|---|---|
| 子智能体库 | `src/octop/infra/agents/subagents/library/README.md` ≈L3 写明 "sourced from agency-agents"；`subagents/catalog.py` 模块 docstring 同 | 仓库内无上游许可证文本，待法务取证 |
| `superpowers-methodology` 专家 | `manifest.json` ≈L8 "源自 superpowers-zh 的 20 个工程技能" | 待法务取证 |
| `multi-agent-orchestrator`、`ai-coding-coach` 专家 | `manifest.json` ≈L8 分别写"源自 agency-orchestrator 的 DAG 协作理念"、"源自 ai-coding-guide 的 66 个 Claude Code 技巧" | 待法务判断是理念借鉴还是内容复制 |
| 字体 | `dashboard/public/fonts/FSPixelSansUnicode-Regular.ttf`；name 表：版权 `NZWStudios2024`，license 描述 `Open Font License`，来源 fontstruct.com；`dashboard/src` 与 `index.html` 中无引用，但 Vite 会把 `public/` 原样复制进构建产物 | OFL-1.1，需随附许可证文本 |

### 8. 工具实测

- **bandit 1.9.4**（Apache-2.0）：对 `src/octop`（排除 `src/octop/dashboard`）全量扫描约 9 秒，521 条结果，其中 `office-automation` 贡献 105 条；HIGH 3 条：`meituan-living-assistant/.../auth.py` 的 B324（该专家由 `w1-04` 删除）与 `src/octop/infra/backup/system_archive.py::_extract_archive` ≈L374、≈L379 的两条 B202——两处都已传 `filter=tarfile.data_filter`，是误报。用同一过滤条件生成基线后再扫，退出码为 0；在副本里新增一个 `hashlib.md5` 调用，退出码为 1。
- **grype 0.87.0**（Apache-2.0）：默认配置会访问 `toolbox-data.anchore.io`（检查自身版本与更新漏洞库）。写一份 `check-for-app-update: false`、`db.auto-update: false` 的配置后不再出网；漏洞库缺失时以退出码 1 结束（失败即关闭）。支持 `sbom:` 输入、`--fail-on`、`-c`、`-o json`、`--file`、`db import`。本环境无法下载漏洞库，未能跑出真实结果。
- **openssl 3.0.13**：`openssl dgst -sha256 -sign/-verify` 对 EC P-256 密钥可用，文件被改后验证失败。

## 方案

**1. 四个技能整目录删除，人设改为"技能包导入"。**
不改写 `SKILL.md`、不保留 `scripts/` 的任何部分，也不从被删目录捡回 XSD。`office-automation` 保留 `file_reader` 技能与人设。文档能力由管理员经 `w1-03` 保留的本地 ZIP 导入（Agent 技能页或技能包）提供，`p2-10` 交付自研技能后再替换。四个 slug 的 i18n 标签（`docx`→Word 等）保留为孤儿键：管理员导入同名技能包时仍能正确显示。

**2. `pymupdf` 移除，PDF 转图改为抽取页内图片。**
扫描件每页通常是一张图；`pypdf` 取出原图再转 PNG，比渲染更省内存。纯矢量页不含图片，但这类页的文字本来就能由 `parse_document` 直接抽取，不需要 OCR。无法解码的图片（如缺解码器的 JBIG2）跳过并记 warning，不让整份文档失败。远程后端因此不再需要任何可选包，`ensure_ocr_deps(backend="remote")` 直接返回 `"ready"`；`_PDF_SPEC` 与 `pdf_ocr_deps_available` 删除。

**3. 判定读已安装包；环境独立、可复现。**
`make compliance-env` 用 `UV_PROJECT_ENVIRONMENT=build/compliance-venv` 执行 `uv sync --frozen --no-dev $(LICENSE_EXTRAS) --no-install-project`，`LICENSE_EXTRAS` 默认 `--all-extras --no-extra dev`（超集，保守）。判定脚本在该环境内运行，用 `importlib.metadata` 读元数据、用 `Distribution.files` 读许可证文件。路径全部写成相对路径：Windows runner 上 make 运行在 Git Bash 里，`$(REPO_ROOT)` 会展开成 `/d/a/...` 这类 uv.exe 不认识的路径。

**4. 分类规则。**

- 信号优先级：`License-Expression`（PEP 639，权威）存在时只用它；否则汇总 `License` 字段（可解析为 SPDX 表达式或命中别名表时才算，超过 100 字符或多行视为正文、忽略）与 classifier（映射表）。没有信号判 `review`（缺失）；多个信号类别不同判 `review`（矛盾）。
- SPDX 求值：支持括号、`AND`、`OR`、`WITH`。`OR` 取最宽松分支，`AND` 取最严格分支，`WITH` 按基础许可证取类别；未知的 SPDX id 判 `review`，逼迫新许可证类型经人工归类。类别从宽到严为 `allow < report < review < deny`。
- 捆绑库：最终类别为 `allow` 时，扫描随包许可证文件，出现 GNU GPL / LGPL / AGPL 标题行则升为 `review`，需要 `reviewed` 条目。
- 策略覆盖：`overrides` 修正元数据（给出 SPDX 表达式与证据）；`reviewed` 给出捆绑库裁定（`allow` 或 `report`）；`reported` 登记需报备组件；`transitional` 让尚待别的 spec 删除的包暂时通过并打印 owner。
- 失败条件：`deny`；未登记的 `report`；未覆盖的 `review`；`report` 类包、`reviewed` 为 `report` 的包，以及 `OR` 舍弃了 `report`/`deny` 分支的包没有在 `NOTICE` 中出现；任何包级条目指向锁文件中不存在的包；`reported` 登记的许可证与判定结果不一致。

**5. 专有内容指纹扫描与第三方包过渡。**
标记只用三条精确字符串（见需求 5.4），扫描仓库六个目录与 compliance 环境 site-packages 中的文本文件（`.py`、`.md`、`.txt`、无后缀或以 `LICENSE`/`COPYING`/`NOTICE` 开头的文件，单文件 2 MB 以内）。`harness_agent` 的 `powerpoint` 若在合入时仍存在，登记 `proprietary.transitional`，owner 为 `w2-01-offline-build`；`w2-01` 的内部分支删掉它之后，该条目因匹配不到文件而判红，必须同批删除。标记只写在策略文件里（`supply-chain/` 不在扫描范围内）；`scripts/` 在扫描范围内，所以脚本源码与注释不得出现这三条标记原文，单测里的样例文本放在 `tests/` 下。

**6. SBOM 自己生成，与闸门同源。**
不引入 `cyclonedx-py` 与 `@cyclonedx/cyclonedx-npm`：它们要进 `uv.lock` 与 `package-lock.json` 两个最热文件，而且与闸门读的是两套数据。脚本直接从同一批判定结果输出 CycloneDX 1.5 JSON：组件的 `purl` 为 `pkg:pypi/<规范名>@<版本>` 与 `pkg:npm/<%40scope/>名@版本`，`licenses` 优先用 `expression`，类别写进 `properties`。`serialNumber` 用组件列表的 uuid5，不写时间戳（设置了 `SOURCE_DATE_EPOCH` 时才写），保证逐字节可复现。grype 按 purl 匹配漏洞，正好消费这两份文件。

**7. SAST 用 bandit + 基线；阻断只看新增 HIGH。**
CodeQL 只扫 Python，bandit 与之对位。基线只收录人工确认的误报（上文两条 B202），其余 LOW/MEDIUM 进全量报告供分诊，不阻断。bandit 进两处 dev 清单，版本由 `uv.lock` 锁定，避免规则漂移。

**8. SCA 用 grype；工具与漏洞库由行方提供。**
grype 是单个二进制，不进任何锁文件。`supply-chain/grype.yaml` 关闭一切出网，设置 `db.max-allowed-built-age: 720h`（30 天），漏洞库过旧即失败，逼迫行方按月导入。忽略规则必须带"理由 / 审批 / 到期"注释，由脚本在扫描前校验。行方若有自己的 SCA 平台，可直接消费 `make sbom` 的产物，或用 `GRYPE=` 指向兼容实现。

**9. 签名用 `SHA256SUMS` + openssl 分离签名。**
与算法、平台无关，目标主机只需 `sha256sum` 与 `openssl` 即可验证。私钥由流水线密文文件提供，不进仓库。国密（SM2/SM3）由 `p2-02` 在同一目标上替换摘要与密钥类型。

**10. CI 只加步骤；Windows 只跑 Python 闸门。**
Python 闭包有平台条件依赖，因此 `quality` 与 `test-windows` 都跑 `license-check-python`。npm 生产依赖与平台无关，放进已有 `node_modules` 的 `frontend` job 跑 `license-check-npm`，不给 Windows job 加 Node。`frontend` job 没有 uv，`$(PYTHON)` 退回 `python3`（`ubuntu-latest` 自带 3.12），脚本只依赖标准库且自检 Python ≥ 3.11。

**11. 参考流水线用 GitLab CI 语法，只调用 make 目标。**
行方平台未定（见"待行方确认"），GitLab CI 可直接执行，也最容易逐行映射到 Jenkins 等平台。文件名不叫 `.gitlab-ci.yml`，避免在 GitLab 上被自动启用。

## 组件与接口

### 文件清单

| 文件 | 类型 | 内容 |
|---|---|---|
| `src/octop/infra/agents/experts/library/office-automation/skills/{docx,pdf,pptx,xlsx}/` | 删除 | 整目录 |
| `src/octop/infra/agents/experts/library/office-automation/{SOUL.md,IDENTITY.md,USER.md,manifest.json}` | 修改 | 见下文"人设改写" |
| `tests/unit/agents/test_expert_catalog.py` | 修改 | 用 `test_bundled_office_automation_has_no_proprietary_skills` 替换 `test_bundled_office_automation_discovers_skills` |
| `src/octop/infra/knowledge/ocr.py` | 修改 | 见下文 |
| `tests/unit/knowledge/test_ocr.py` | 修改 | 新增 5 个用例 |
| `pyproject.toml` | 修改 | 删 `knowledge-ocr` 中的 `pymupdf>=1.24`；两处 dev 清单各加 `bandit>=1.9` |
| `uv.lock`、`dashboard/package-lock.json` | 重生成 | `make relock`，单独一个提交 |
| `scripts/intranet/supply_chain.py` | 新增 | 判定、扫描、SBOM、声明汇编、校验和，只用标准库 |
| `supply-chain/license-policy.toml` | 新增 | 策略文件 |
| `supply-chain/bandit-baseline.json` | 新增 | bandit 基线（`make sast-baseline` 生成） |
| `supply-chain/grype.yaml` | 新增 | grype 离线配置与忽略规则 |
| `supply-chain/pipeline.reference.yml` | 新增 | 行内流水线参考定义 |
| `Makefile.intranet` | 修改（`w0-02` 创建） | 追加供应链目标与 `help-intranet` 行 |
| `.github/workflows/ci.yml` | 修改 | 三个 job 各加步骤 |
| `.github/workflows/codeql.yml`、`.github/codeql/` | 删除 | SAST 接入 CI 后删除 |
| `tests/unit/test_supply_chain.py` | 新增 | 脚本单测 |
| `tests/unit/test_supply_chain_contract.py` | 新增 | CI、参考流水线、Makefile、策略与 NOTICE 的契约测试 |
| `NOTICE` | 新增 | 见下文 |
| `docs/intranet/third-party-licenses.md` | 新增 | 分类规则、报备清单、人工裁定、来源登记、处置表 |
| `docs/intranet/supply-chain.md` | 新增 | 目标与变量、离线前置条件、漏洞库导入、基线理由、SCA 分诊表、密钥托管 |
| `README.md`、`README_CN.md` | 修改 | MIT 声明后各加一句指针 |
| `docs/intranet/upstream-sync.md` | 修改（`w0-04` 创建） | 第 7、8 节各加一行 |
| `AGENTS.md` | 修改 | §9 加一行 |
| `CHANGELOG-intranet.md` | 修改 | 本 spec 条目 |

### 人设改写（`office-automation`）

- `SOUL.md`："Bundled skills" 表只保留 `file_reader` 一行；新增一段："Word、Excel、PPT、PDF 文档技能由管理员以技能包（本地 ZIP）导入。先检查工作区里是否已有对应技能；没有时告诉用户联系管理员导入，不要自行编写解析 Office 文件的脚本。" 删除 ≈L23 那条以"matching skill has scripts"为前提的边界句。
- `IDENTITY.md` 与 `USER.md`（保持逐字相同）：自我介绍改为"Word、Excel、PPT、PDF 处理需要管理员导入对应技能包"；"务实"一条去掉"优先调用对应技能（docx / xlsx / pptx / pdf）"；"Bundled Skills" 列表只留 `file_reader`。
- `manifest.json`：`description.zh` / `description.en` 删去"内置 Word、Excel、PPT、PDF 全套文档技能" / "bundled Word, Excel, PPT, and PDF skills"，改为"导入文档技能包后可处理 Word、Excel、PPT、PDF"；`quick_prompts`、`welcome_message`、`task_examples` 不改。
- 不得引入 `MBTI`、`browser_use` 字样（`w1-04` 的守卫测试会检查）。

### `ocr.py` 改动

```python
import io
import logging
logger = logging.getLogger(__name__)

_LOCAL_PACKAGES = ("rapidocr>=3.4,<4", "onnxruntime>=1.17")
# _PDF_SPEC 删除

def local_ocr_deps_available() -> bool: ...          # 只探测 rapidocr
# pdf_ocr_deps_available 删除；get_ocr_capability 中 remote 的 deps_available 恒为 True

def ensure_ocr_deps(*, backend: str) -> str:
    if backend == "onnx":
        ...                                           # import_modules=("rapidocr", "onnxruntime")
    return "ready"                                    # pypdf 与 pillow 是核心依赖

def _image_inputs(path: Path) -> Iterator[tuple[bytes, str]]:
    # 非 PDF 分支不变；PDF 分支：
    from pypdf import PdfReader
    for page_no, page in enumerate(PdfReader(path).pages, start=1):
        for image in page.images:
            try:
                buf = io.BytesIO()
                image.image.save(buf, format="PNG")
            except Exception as exc:  # 缺解码器（如 JBIG2）时跳过该图
                logger.warning("knowledge OCR: skip image %s on page %d of %s: %s",
                               image.name, page_no, path.name, exc)
                continue
            yield buf.getvalue(), "image/png"
```

`knowledge_bases.py` 不改；它调用的 `ensure_ocr_deps_async` 签名不变。

### `scripts/intranet/supply_chain.py`（新增）

只用标准库（`tomllib`、`json`、`importlib.metadata`、`sysconfig`、`hashlib`、`uuid`、`fnmatch`、`argparse`、`re`），启动时检查 `sys.version_info >= (3, 11)`，否则退出码 2。

```python
Category = Literal["allow", "report", "review", "deny"]

@dataclass(frozen=True)
class Finding:
    ecosystem: Literal["python", "npm"]
    name: str                 # 规范名
    version: str
    license: str              # 生效的 SPDX 表达式；缺失时为 ""
    category: Category
    basis: tuple[str, ...]    # "License-Expression" / "License" / "classifier" / "override" / "reviewed" / "bundled-gpl-title" / "lockfile" / "package.json"
    election: bool            # OR 舍弃了 report/deny 分支
    notes: tuple[str, ...]
    license_files: tuple[str, ...]

def normalize_name(name: str) -> str: ...                                   # PEP 503
def load_policy(path: Path) -> Policy: ...
def evaluate_expression(expr: str, policy: Policy) -> tuple[Category, bool]: ...
def classify_python(policy: Policy, *, path: list[str] | None = None) -> list[Finding]: ...
def classify_npm(policy: Policy, lock: dict[str, Any], node_modules: Path) -> list[Finding]: ...
def check(findings: list[Finding], policy: Policy, *, lock_names: set[str],
          notice_text: str, ecosystem: str) -> tuple[list[str], list[str]]: ...  # (violations, warnings)
def scan_proprietary(roots: list[Path], policy: Policy, *, include_site_packages: bool) -> tuple[list[str], list[str], list[str]]: ...  # (hits, warnings, stale)
def to_cyclonedx(findings: list[Finding], *, root_name: str, root_version: str, ecosystem: str) -> dict[str, Any]: ...
def write_notices(findings: list[Finding], out: Path, *, node_modules: Path | None) -> None: ...
def write_checksums(directory: Path, out: Path) -> None: ...
def verify_checksums(directory: Path, sums: Path) -> list[str]: ...
def check_grype_ignores(config_text: str) -> list[str]: ...
def main(argv: list[str] | None = None) -> int: ...
```

子命令与退出码：

| 子命令 | 作用 | 0 | 1 | 2 |
|---|---|---|---|---|
| `licenses python --policy P --lock uv.lock --notice NOTICE --out F` | 在当前解释器环境判定 | 通过 | 有违规 | 策略或锁文件无法解析 |
| `licenses npm --policy P --lock L --node-modules D --notice NOTICE --out F` | 判定 npm 生产依赖 | 通过 | 有违规 | `node_modules` 不存在或锁文件无法解析 |
| `proprietary --policy P [--include-site-packages] ROOT...` | 指纹扫描仓库目录，并按需扫描当前解释器的 site-packages | 无命中 | 有命中或陈旧过渡条目 | 参数错误 |
| `sbom {python,npm} ... --out F` | 输出 CycloneDX | 成功 | — | 输入缺失 |
| `notices --lock L --node-modules D --out F` | 汇编许可证文本 | 成功 | — | 输入缺失 |
| `checksums --dir D --out F` / `--verify F` | 生成或校验 `SHA256SUMS` | 成功 / 全部一致 | 有不一致 | 目录不存在 |
| `sca-ignore-check --config C` | 校验忽略规则注释 | 通过 | 缺注释 | 文件不存在 |

报告 JSON 形如 `{"ecosystem": "python", "platform": "<sysconfig.get_platform()>", "summary": {"allow": n, ...}, "packages": [Finding...], "violations": [...], "warnings": [...]}`，按包名排序。

### `supply-chain/license-policy.toml`（新增）

```toml
# 许可证策略。每条人工结论必须对应 uv.lock / package-lock.json 中仍存在的包，否则判红。
[categories]
allow  = ["MIT", "MIT-0", "BSD-2-Clause", "BSD-3-Clause", "0BSD", "ISC", "Apache-2.0", "PSF-2.0",
          "Python-2.0", "Unlicense", "CC0-1.0", "Zlib", "BSL-1.0", "HPND", "MIT-CMU",
          "LicenseRef-BSD", "LicenseRef-PublicDomain"]
report = ["LGPL-2.0-only", "LGPL-2.0-or-later", "LGPL-2.1-only", "LGPL-2.1-or-later",
          "LGPL-3.0-only", "LGPL-3.0-or-later", "MPL-2.0", "EPL-2.0"]
deny   = ["AGPL-3.0-only", "AGPL-3.0-or-later", "GPL-2.0-only", "GPL-2.0-or-later",
          "GPL-3.0-only", "GPL-3.0-or-later", "SSPL-1.0", "JSON", "LicenseRef-Proprietary"]

[aliases]          # 非 SPDX 的 License 字段 / npm license 字符串 → SPDX 表达式（初始内容由任务 5.2 分诊补齐）
"MIT License" = "MIT"
"MPL 2.0" = "MPL-2.0"
"LGPLv3" = "LGPL-3.0-only"
"LGPLv2+" = "LGPL-2.0-or-later"
"Dual Licensed - GNU AFFERO GPL 3.0 or Artifex Commercial License" = "AGPL-3.0-only OR LicenseRef-Proprietary"
"Doug Crockford's license that allows this module to be used for Good but not for Evil" = "JSON"

[classifiers]      # trove classifier → SPDX；裸 "License :: OSI Approved" 忽略
"License :: OSI Approved :: MIT License" = "MIT"
"License :: OSI Approved :: BSD License" = "LicenseRef-BSD"
"License :: OSI Approved :: Apache Software License" = "Apache-2.0"
"License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)" = "MPL-2.0"
"License :: OSI Approved :: GNU Lesser General Public License v3 (LGPLv3)" = "LGPL-3.0-only"
"License :: Other/Proprietary License" = "LicenseRef-Proprietary"

[reported.psycopg]
license = "LGPL-3.0-only"
usage   = "PostgreSQL 驱动；Python import 动态加载；未修改"
source  = "离线交付包附 PyPI sdist（w2-01）；上游 https://github.com/psycopg/psycopg"
# psycopg-binary、psycopg-pool、certifi、bidict、orjson、tqdm 同格式

[reviewed.opencv-python]
verdict = "report"
reason  = "wheel 内捆绑 FFmpeg、Qt5 等 LGPL 共享库（opencv_python.libs/），未修改；经 rapidocr 引入（knowledge-ocr extra）"
reviewed_version = "5.0.0.93"
# shapely（GEOS，LGPL-2.1，report）、numpy（libgfortran，GCC 运行时库例外，allow）同格式

[overrides.fastembed]
license  = "Apache-2.0"
evidence = "dist-info/licenses/LICENSE 为 Apache License 2.0 全文；classifier 'Other/Proprietary License' 与之矛盾，以随包 LICENSE 为准"
# agent-client-protocol（Apache-2.0）、deepagents-backends（MIT）、py-rust-stemmers（MIT）同格式

[transitional.pynput]
owner  = "w2-01-offline-build"
reason = "经 orcakit-harness-agent[all] 与 desktop extra 引入；w2-01 收窄后删除本条"
# python-xlib、python-telegram-bot 同格式；仅在任务 1 发现锁文件仍含它们时写入

[proprietary]
markers = ["Anthropic, PBC. All rights reserved", "Unauthorized copying, modification, distribution"]
line_start_markers = ["license: Proprietary"]

[[proprietary.transitional]]
path  = "harness_agent/builtin/skills/*/powerpoint/*"
owner = "w2-01-offline-build"
reason = "第三方包内的 Anthropic 专有技能；w2-01 内部分支删除后本条判为陈旧（D13）"

[npm.reported]     # 初始为空；dompurify 为 (MPL-2.0 OR Apache-2.0)，择 Apache-2.0，只需在 NOTICE 出现
```

### `Makefile.intranet`（追加）

```make
# ─── Supply chain (w2-02-supply-chain-compliance) ────────────────────────────
# Paths are relative on purpose: on Windows runners make runs in Git Bash and
# $(REPO_ROOT) expands to /d/a/... which uv.exe does not understand.
COMPLIANCE_VENV := build/compliance-venv
COMPLIANCE_DIR  := dist/compliance
SUPPLY_CHAIN    := scripts/intranet/supply_chain.py
POLICY          := supply-chain/license-policy.toml
LICENSE_EXTRAS  ?= --all-extras --no-extra dev
GRYPE           ?= grype
SCA_FAIL_ON     ?= high
SIGN_DIR        ?= dist
SIGNING_KEY     ?=
SIGNING_PUBKEY  ?=
COMPLIANCE_PY    = UV_PROJECT_ENVIRONMENT=$(COMPLIANCE_VENV) uv run --frozen --no-sync python
BANDIT_ARGS      = -r src/octop -x src/octop/dashboard -q

.PHONY: compliance-env
compliance-env:
	@command -v uv >/dev/null 2>&1 || { echo "[compliance] uv is required"; exit 2; }
	UV_PROJECT_ENVIRONMENT=$(COMPLIANCE_VENV) uv sync --frozen --no-dev $(LICENSE_EXTRAS) --no-install-project \
		|| { echo "[compliance] cannot build $(COMPLIANCE_VENV)"; exit 2; }

.PHONY: license-check-python
license-check-python: compliance-env
	$(COMPLIANCE_PY) $(SUPPLY_CHAIN) licenses python --policy $(POLICY) --lock uv.lock --notice NOTICE --out $(COMPLIANCE_DIR)/licenses-python.json
	$(COMPLIANCE_PY) $(SUPPLY_CHAIN) proprietary --policy $(POLICY) --include-site-packages src dashboard/src dashboard/public docker scripts plugins

.PHONY: license-check-npm
license-check-npm:
	$(PYTHON) $(SUPPLY_CHAIN) licenses npm --policy $(POLICY) --lock dashboard/package-lock.json --node-modules dashboard/node_modules --notice NOTICE --out $(COMPLIANCE_DIR)/licenses-npm.json

.PHONY: license-check
license-check: license-check-python license-check-npm

.PHONY: sbom
sbom: license-check
	$(COMPLIANCE_PY) $(SUPPLY_CHAIN) sbom python --policy $(POLICY) --out $(COMPLIANCE_DIR)/sbom-python.cdx.json
	$(PYTHON) $(SUPPLY_CHAIN) sbom npm --policy $(POLICY) --lock dashboard/package-lock.json --node-modules dashboard/node_modules --out $(COMPLIANCE_DIR)/sbom-npm.cdx.json
	$(COMPLIANCE_PY) $(SUPPLY_CHAIN) notices --lock dashboard/package-lock.json --node-modules dashboard/node_modules --out $(COMPLIANCE_DIR)/THIRD-PARTY-NOTICES.txt

.PHONY: sca
sca:
	@command -v $(GRYPE) >/dev/null 2>&1 || { echo "[sca] grype not found (set GRYPE=<path>)"; exit 2; }
	@for f in sbom-python sbom-npm; do test -f $(COMPLIANCE_DIR)/$$f.cdx.json || { echo "[sca] missing $(COMPLIANCE_DIR)/$$f.cdx.json; run make sbom"; exit 2; }; done
	$(PYTHON) $(SUPPLY_CHAIN) sca-ignore-check --config supply-chain/grype.yaml
	@rc=0; for eco in python npm; do \
		$(GRYPE) sbom:$(COMPLIANCE_DIR)/sbom-$$eco.cdx.json -c supply-chain/grype.yaml --fail-on $(SCA_FAIL_ON) -o table || rc=1; \
		$(GRYPE) sbom:$(COMPLIANCE_DIR)/sbom-$$eco.cdx.json -c supply-chain/grype.yaml -o json --file $(COMPLIANCE_DIR)/sca-$$eco.json || rc=1; \
	done; exit $$rc

.PHONY: sast
sast:
	@mkdir -p $(COMPLIANCE_DIR)
	$(RUN) bandit $(BANDIT_ARGS) --severity-level high --confidence-level medium -b supply-chain/bandit-baseline.json
	$(RUN) bandit $(BANDIT_ARGS) --exit-zero -f json -o $(COMPLIANCE_DIR)/sast-bandit.json

.PHONY: sast-baseline
sast-baseline:
	$(RUN) bandit $(BANDIT_ARGS) --severity-level high --confidence-level medium --exit-zero -f json -o supply-chain/bandit-baseline.json

.PHONY: sign
sign:
	@test -n "$(SIGNING_KEY)" || { echo "[sign] SIGNING_KEY=<PEM private key file> is required"; exit 2; }
	@command -v openssl >/dev/null 2>&1 || { echo "[sign] openssl is required"; exit 2; }
	$(PYTHON) $(SUPPLY_CHAIN) checksums --dir $(SIGN_DIR) --out $(SIGN_DIR)/SHA256SUMS
	@openssl dgst -sha256 -sign "$(SIGNING_KEY)" -out $(SIGN_DIR)/SHA256SUMS.sig $(SIGN_DIR)/SHA256SUMS
	@echo "[sign] wrote $(SIGN_DIR)/SHA256SUMS and $(SIGN_DIR)/SHA256SUMS.sig"

.PHONY: verify-signature
verify-signature:
	@test -n "$(SIGNING_PUBKEY)" || { echo "[verify-signature] SIGNING_PUBKEY=<PEM public key file> is required"; exit 2; }
	openssl dgst -sha256 -verify "$(SIGNING_PUBKEY)" -signature $(SIGN_DIR)/SHA256SUMS.sig $(SIGN_DIR)/SHA256SUMS
	$(PYTHON) $(SUPPLY_CHAIN) checksums --dir $(SIGN_DIR) --verify $(SIGN_DIR)/SHA256SUMS

.PHONY: supply-chain
supply-chain: license-check sast sbom sca
```

`help-intranet` 追加九行（`license-check`、`license-check-python`、`license-check-npm`、`sbom`、`sca`、`sast`、`sign`、`verify-signature`、`supply-chain`），并注明 `GRYPE_DB_CACHE_DIR`、`SIGNING_KEY`、`SIGNING_PUBKEY` 三个变量。`checksums` 生成时排除 `SHA256SUMS` 与 `SHA256SUMS.sig` 自身；`make build-wheel` 会清空 `dist/*`，所以顺序必须是先 `build` 后 `sbom` 再 `sign`。

### `supply-chain/grype.yaml`（新增）

```yaml
# grype 离线配置：不检查自身更新、不自动更新漏洞库；漏洞库由行方用 `grype db import <archive>` 导入，
# 目录由环境变量 GRYPE_DB_CACHE_DIR 指定。超过 30 天的库视为过期并失败。
check-for-app-update: false
db:
  auto-update: false
  validate-age: true
  max-allowed-built-age: 720h
ignore:
  # 每条规则前必须有一行注释：理由：… 审批：… 到期：YYYY-MM-DD
```

### `.github/workflows/ci.yml`（追加步骤）

- `quality` job 在 `Test` 之后追加 `- name: SAST (bandit)` / `run: make sast` 与 `- name: License check (Python)` / `run: make license-check-python`。
- `test-windows` job 在 `Test` 之后追加 `- name: License check (Python)` / `run: make license-check-python`。
- `frontend` job（`w0-02` 新增）在 `Frontend checks` 之后追加 `- name: License check (npm)` / `run: make license-check-npm`。
- `live-tests` 不改。

### `supply-chain/pipeline.reference.yml`（新增，GitLab CI 语法）

阶段为 `verify → build → compliance → sign`。

- `verify` 阶段三个并行作业：`quality`（`make install`、`make lint`、`make typecheck`、`make test`）、`frontend`（`make install-frontend`、`make check-frontend`）、`postgresql`（`make install`、`make test-postgresql`，DSN 取自受保护的掩码变量 `PG_TEST_DSN`）。
- `build` 阶段：`make install`、`make build`，产物 `dist/`。
- `compliance` 阶段：`make install`、`make install-frontend`、`make license-check`、`make sast`、`make sbom`、`make sca`；产物 `dist/compliance/`；`GRYPE_DB_CACHE_DIR` 指向 runner 上挂载的漏洞库目录。
- `sign` 阶段：只在受保护标签上运行；`make sign SIGNING_KEY=$SIGNING_KEY_FILE`（文件型密文变量）；产物 `dist/`。
- 全局变量只写 `UV_DEFAULT_INDEX: $PYPI_MIRROR`、`NPM_REGISTRY: $NPM_MIRROR` 这类引用，不写任何明文凭据。

### 契约测试 `tests/unit/test_supply_chain_contract.py`（新增）

`yaml.safe_load` 读取 `ci.yml` 与参考流水线（`w0-02` 已说明 `yaml` 由依赖树提供；若 `w2-01` 收窄后不可用，与 `w0-02` 的契约测试一起改为纯文本解析）。用例：

- `test_ci_quality_and_windows_run_python_license_check`、`test_ci_quality_runs_sast`、`test_ci_frontend_runs_npm_license_check`；
- `test_codeql_removed`（`.github/workflows/codeql.yml` 与 `.github/codeql` 均不存在）；
- `test_makefile_intranet_defines_supply_chain_targets`（行首正则 `^<target>:`，九个目标加 `compliance-env`、`sast-baseline`）与 `test_help_intranet_lists_targets`；
- `test_reference_pipeline_calls_contract_targets` 与 `test_reference_pipeline_orders_build_before_supply_chain`；
- `test_reference_pipeline_has_no_inline_secret`（不含 `postgresql://` 带口令的 DSN、不含 `PRIVATE KEY`）；
- `test_grype_config_is_offline`；
- `test_no_private_key_committed`（遍历 `supply-chain/`、`scripts/intranet/`、`docs/intranet/` 与 `NOTICE`）；
- `test_notice_lists_policy_packages`（`reported` 与 `reviewed` 中 verdict 为 `report` 的每个包名都出现在 `NOTICE`）；
- `test_supply_chain_script_is_ruff_clean`（`sys.executable -m ruff check scripts/intranet` 与 `ruff format --check scripts/intranet`，因为根 `Makefile` 的 `lint` 只查 `src tests`）。

所有文件读取用 `encoding="utf-8"` 与 `pathlib`，与平台无关。

### `NOTICE`（新增）

1. Octop 自身代码采用 MIT，见 `LICENSE`。
2. 第三方组件按各自许可证分发；完整清单见交付包中的 `sbom-python.cdx.json`、`sbom-npm.cdx.json`，许可证文本见 `THIRD-PARTY-NOTICES.txt`；分类规则与处置见 `docs/intranet/third-party-licenses.md`。
3. 需报备组件：`psycopg`、`psycopg-binary`、`psycopg-pool`（LGPL-3.0-only，动态加载、未修改、源码随离线包提供）；`opencv-python`、`shapely`（捆绑 LGPL 共享库，逐项列出）；`certifi`、`bidict`、`orjson`、`tqdm`（MPL-2.0，未修改）。
4. 双许可择一：`paho-mqtt` 择 BSD-3-Clause；`dompurify` 择 Apache-2.0；`orjson` 的 `(Apache-2.0 OR MIT)` 部分择 MIT（MPL-2.0 部分不可规避，已列入报备）。
5. 随仓库分发的第三方内容：FS Pixel Sans Unicode 字体（OFL-1.1，附全文）；子智能体库（来源 agency-agents，许可证全文待法务取回后附上）。

## 数据模型

无。本 spec 不新增表或列，不写 `forkNNN_` 迁移，不触碰 `_schema_version` 与 `_fork_schema_version`。

## 配置

`config.py` 不新增键，不涉及三触点。新增的只有 Make 变量与工具自身的环境变量，都不进入 `OctopConfig`：

| 名称 | 所在层 | 默认值 | 作用 |
|---|---|---|---|
| `LICENSE_EXTRAS` | `Makefile.intranet` | `--all-extras --no-extra dev` | compliance 环境装哪些 extra；与行内实际交付的 extra 集合对齐时可收窄 |
| `GRYPE` | `Makefile.intranet` | `grype` | grype 可执行文件路径 |
| `SCA_FAIL_ON` | `Makefile.intranet` | `high` | 阻断阈值 |
| `SIGN_DIR` | `Makefile.intranet` | `dist` | 签名范围 |
| `SIGNING_KEY` / `SIGNING_PUBKEY` | `Makefile.intranet` | 空 | 私钥 / 公钥文件路径，由流水线文件型密文提供 |
| `GRYPE_DB_CACHE_DIR` | grype 环境变量 | grype 默认 | 行方导入的漏洞库目录 |
| `SOURCE_DATE_EPOCH` | 环境变量 | 空 | 设置时写入 SBOM 时间戳 |

## 错误处理

不新增 `ErrorCode`，也不改 `_DEFAULT_STATUS`。

- OCR：PDF 中无图片时返回空文本，与基线"空白 PDF"行为一致；单张图片解码失败只记 warning。远程 OCR 不再有"依赖未安装"这条失败路径；本地 OCR 缺 `rapidocr` 时仍沿用基线的 `RuntimeError`，经 `knowledge_bases.py` 的 `_map_knowledge_error` 映射，行为不变。
- 门禁：失败语义完全由退出码表达，见上文子命令表。约定 0 为通过、1 为策略违规、2 为环境问题（缺 uv、缺 `node_modules`、缺 grype、缺密钥），与 `w0-04` 的 `make relock` 一致。所有违规一次性全部列出，不在第一条就退出。

## 安全考虑

- **不出网。** 判定与扫描只读本地文件；grype 配置关闭自更新与漏洞库更新（已实测默认配置会访问 `toolbox-data.anchore.io`）；bandit 与 openssl 本身不联网。建 compliance 环境只访问 uv 已配置的索引，行内即私服。
- **失败即关闭。** 漏洞库缺失或过期、SBOM 缺失、工具缺失都以非零退出结束；策略文件的陈旧条目判红，避免豁免永久残留。
- **密钥。** 私钥只以流水线文件型密文传入；`make sign` 的 openssl 行用 `@` 静默；契约测试禁止仓库出现 `PRIVATE KEY`。公钥可随交付文档一起发给运维。
- **标记本身不外泄敏感信息。** 三条标记都是公开许可证中的原文。
- **分发面收缩。** 删除四个技能后，新建的办公 Agent 不再收到任何 Anthropic 材料；wheel 中不再含这些文件。第三方包中的 `powerpoint` 由 `w2-01` 处理，在此之前由过渡条目显式标出，不会被静默放过。
- **OCR 输入面。** `pypdf` 解析不可信 PDF 的风险与基线的 `pymupdf` 同类；图片解码交给已是核心依赖的 pillow。本 spec 不扩大文件类型。
- **不改运行期权限与路由。** 本 spec 不新增端点、权限键或中间件。

## 测试策略

**单测（随 `make test` 在 Linux 与 Windows 执行）：**

```bash
uv run pytest tests/unit/test_supply_chain.py tests/unit/test_supply_chain_contract.py -q
uv run pytest tests/unit/knowledge -q
uv run pytest tests/unit/agents/test_expert_catalog.py tests/unit/i18n -q
```

`tests/unit/test_supply_chain.py` 用 `importlib.util.spec_from_file_location` 加载脚本，并先注册进 `sys.modules`（dataclass 需要）。Python 侧用 `tmp_path` 伪造 `*.dist-info/METADATA` 与 `licenses/` 文件，传 `path=[str(tmp_path)]` 给 `classify_python`；npm 侧伪造锁文件与 `node_modules`。覆盖：

1. `License-Expression: MIT` → `allow`；`AGPL-3.0-only` → `deny` 且 `main()` 返回 1（等价于"临时加入 AGPL 依赖后变红"）；
2. `pymupdf` 的双许可字符串经别名 → `deny`；
3. `LGPL-3.0-only` 未登记 → 失败；登记且在 NOTICE 中 → 通过；登记但 NOTICE 缺名 → 失败；
4. `EPL-2.0 OR BSD-3-Clause` → `allow` 且 `election=True`，NOTICE 缺名 → 失败；`MPL-2.0 AND MIT` → `report`；
5. 元数据全空 → `review`；有 `overrides` → 按覆盖许可证判定；
6. `License: Apache License` + classifier `Other/Proprietary License` → `review`（矛盾）；
7. 元数据 MIT 但 `licenses/COPYING` 含 `GNU LESSER GENERAL PUBLIC LICENSE` 标题行 → `review`；正文里只提到 "GNU General Public License" 的一句话 → 仍为 `allow`；
8. 策略条目名不在锁文件 → 失败；`discord.py` 与 `discord-py` 视为同名；
9. `transitional` 条目 → 通过并有 owner 警告；
10. npm：`dev` 与 `devOptional` 条目被忽略；锁文件缺 `license` 时取 `node_modules` 中的 `package.json`；`node_modules` 缺失 → 退出码 2；JSON 许可证 → `deny`；旧式 `licenses: [{type: ...}]` 可解析；
11. 专有扫描：命中 → 1；被过渡条目覆盖 → 0 且有警告；过渡条目无匹配 → 1；`Copyright 2023 Anthropic, PBC` 不命中；
12. SBOM：`bomFormat`、`specVersion == "1.5"`、purl 规范化（`Foo_Bar` → `pkg:pypi/foo-bar@1.0`，`@scope/x` → `pkg:npm/%40scope/x@1.0`）、组件集合与报告一致、两次输出逐字节相同；
13. 校验和：格式为 `<64 位十六进制><两个空格><相对路径>`，路径用 `/`；排除 `SHA256SUMS` 与 `.sig`；篡改后 `verify_checksums` 返回非空；
14. `check_grype_ignores`：规则前缺"理由 / 审批 / 到期"注释 → 返回错误。

**OCR 单测（`tests/unit/knowledge/test_ocr.py` 新增）：** 两页图片 PDF 产出两个 PNG；空白页 PDF 产出空序列；伪造一张 `.image` 抛异常的图片时跳过并记录 warning（`caplog`）；把 `ocr.install_packages` 替换为抛 `AssertionError` 后 `ensure_ocr_deps(backend="remote") == "ready"`；`ocr.py` 源码不含 `pymupdf`。

**集成与端到端（本地命令）：**

```bash
make license-check-python
make install-frontend && make license-check-npm
make build && make sbom
make sast
GRYPE_DB_CACHE_DIR=<行方导入的漏洞库目录> make sca          # 需要 grype 与离线漏洞库
make sign SIGNING_KEY=build/test-sign.pem && make verify-signature SIGNING_PUBKEY=build/test-sign.pub
```

**前端：** 本 spec 不改 `dashboard/` 源码，不需要 `tsc` 与 vitest；`license-check-npm` 需要 `make install-frontend` 装好的 `node_modules`。

**PostgreSQL：** 不涉及。本 spec 不改数据库代码，也不新增 PG 用例。

**回归：** `make all`（`format-all` 需要 `dashboard/node_modules`，先执行 `make install-frontend`）。

## 与其他 spec 的交接

**依赖：**

- `w0-02-ci-gates`：`Makefile.intranet` 与根 `Makefile` 的 `include` 行、`install-frontend`、`check-frontend`、`test-postgresql`、`ci.yml` 的 `frontend` job、`tests/unit/test_ci_gates_contract.py`。本 spec 只在 `ci.yml` 追加步骤、不改 job 结构，因此 `w0-02` 的契约测试不用改；`w0-02` 交接说"迁出 `ci.yml` 时改写其契约测试"，本 spec 不迁出 `ci.yml`，只提供参考流水线，这一条留给真正迁移的那一次。
- `w0-04-fork-isolation-points`：`make relock`、`CHANGELOG-intranet.md`、`docs/intranet/upstream-sync.md`。
- `w1-02-capability-trim`：已删 `src/octop/infra/desktop/`（含 `pynput` 导入与 6 个测试文件）与 `playwright`，本 spec 不为它们写任何改动。
- `w1-03-online-fetch-trim`：保留了本地 ZIP 技能导入，它是"文档技能改由技能包导入"的前提。
- `w1-04-content-trim`：已删 `news` 技能、`meituan-living-assistant`（bandit 的一条 HIGH）、`build@0.1.4`（带出 `jsmin`）、`desktop/`、`fnos/` 与安装脚本；按约定保留了 `ci.yml` 与 `codeql.yml`。它的需求 9.1 写"`.github/workflows/` 下应当始终恰为三个文件"，本 spec 删除 `codeql.yml` 后该表述失效；如果 `w1-04` 把它写成了守卫测试断言，本 spec 删除 `codeql.yml` 的同一提交里把断言改为"恰为 `anti-spam-issues.yml`、`ci.yml`"。
- `w1-05-saas-decoupling`：已删 `edge-tts` 与 bot creator。**发现的遗漏：** 基线 `dashboard/src/hooks/useVoiceOutput.ts` ≈L179 渲染 `voice.browserNoChineseVoice`（en/zh 文案都写着 "Edge TTS"），≈L182 与 ≈L200 调用 `speakWithServer(plain, gen, "edge")`；`w1-05` 的设计只列了 `Settings/Voice/index.tsx`。edge 预设删除后这两处调用会请求不存在的预设。这属于 `w1-05` 的范围，本 spec 不修，只在任务 1 核对并在 PR 里提示。

**并行协调：`w2-01-offline-build`（同波次并行）：**

- `w2-01` 负责删掉 `pynput`、`python-xlib`、`evdev`、`pyobjc` 一族（`desktop` extra 与 `[all]` 收窄）与 `python-telegram-bot`（`harness-gateway` 重打包）。若本 spec 先合入，这些包以 `transitional` 条目通过；`w2-01` 合入时必须同批删除对应条目，否则陈旧条目判红。若 `w2-01` 先合入，本 spec 不写这些条目。
- `w2-01` 的 harness 内部分支需要：删除 `harness_agent/builtin/skills/{en,zh}/powerpoint/`；为 `skill-creator` 补齐上游许可证与署名，或一并删除；核实另外 6 个未写 `license` 字段的技能来源。删除 `powerpoint` 后同批删除 `proprietary.transitional` 条目。注意 `sync_builtin_skills_to_backend` 只覆盖不删除，存量工作区的 `_builtin_skills/powerpoint/` 不会自动消失。
- 两个 spec 都改 `pyproject.toml`、`uv.lock` 与 `ocr.py`。本 spec 在 `ocr.py` 只动 `pymupdf` 相关的行、`ensure_ocr_deps` 的 remote 分支与 `_image_inputs` 的 PDF 分支；`w2-01` 关闭运行期安装时只动 `install_packages` 调用本身。后合入者 rebase 后执行 `make relock` 与 `make license-check`。
- 交付给 `w2-01`：离线交付包须包含 `dist/compliance/`（两份 SBOM、`THIRD-PARTY-NOTICES.txt`、许可证报告）与 `NOTICE`，并附 `reported` 各组件的 sdist 以履行源码提供义务；行内工具镜像须提供 grype 二进制、`openssl` 与漏洞库导入目录；`LICENSE_EXTRAS` 应与离线包实际包含的 extra 对齐。若行方要求 wheel 单独分发时也自带前端第三方声明，由 `w2-01` 在 `build-frontend` 之后把 `THIRD-PARTY-NOTICES.txt` 复制进 `src/octop/dashboard/`。模型权重（`fastembed`、`rapidocr` 的模型文件）不在 Python 元数据里，由提供离线模型包的一方登记许可证。

**交付给谁：**

- `w2-03-database-adaptation`：`psycopg-binary` 在 wheel 内捆绑 `libpq`、`libssl`/`libcrypto`、`libkrb5`、`libldap`、`libsasl2`、`libcrypt` 等共享库（`psycopg_binary.libs/`）。如果改用 `psycopg` + 系统 `libpq`，或引入信创数据库驱动，需要更新 `reported` 条目并重跑 `make license-check`。
- `w4-01-frontend-baseline`：SCA 首次分诊中的前端组件（预期包括 `xlsx`）由它处置。
- `p2-02-kms-sm-crypto`：在 `make sign` / `make verify-signature` 上替换为 SM3 摘要与 SM2 密钥，保持目标名不变。
- `p2-10-office-skills-rewrite`：在已清空的 `office-automation/skills/` 下交付自研技能，XSD 如需校验从 ECMA-376 官方发布包取源；交付时恢复人设中的"内置技能"描述，并同步本 spec 改过的 `test_expert_catalog.py` 用例。
- 所有后续改依赖的 spec：在末尾 `make relock` 之后执行 `make license-check`；新依赖触发 `review` / `report` / `deny` 时在同一 PR 补策略条目或换依赖。

**看起来相关、但归别的 spec：**

- `anti-spam-issues.yml`、`.github/ISSUE_TEMPLATE/`、`.github/pull_request_template.md`（`w1-04` 建议由本 spec 处理）：它们不是供应链门禁，本 spec 不动；仓库迁入行内 Git 平台时整体移除 `.github/`（见"待行方确认"）。
- `ci.yml` 的 `live-tests` job 引用了大量已删连接器与渠道的密文变量（`w1-04` 建议由本 spec 处理）：fork 仓库没有这些密文，job 会自动跳过；本 spec 不改它，参考流水线也不包含 live 阶段。
- 前端 SAST：CodeQL 原本就只扫 Python，本 spec 与之对位；是否需要前端规则见"待行方确认"。
- 语音、IM 渠道、桌面、安装脚本、Dockerfile 注释中的 `pynput` 与 edge 痕迹：分别已由 `w1-05`、`w1-02`、`w1-04` 删除。

## 风险与回滚

| 风险 | 影响 | 缓解 |
|---|---|---|
| compliance 环境较大（基线实测 1.1 GB、约 3.1 万个文件，含将被 `w1-02` 删除的 `playwright`） | Windows job 变慢 | uv 缓存；`w1-02`、`w2-01` 收窄后变小；只扫描文本文件（基线约 600 个许可证类文件） |
| 上游同步或依赖升级带来新的 `review` / `deny` | 同步 PR 变红 | 这正是闸门的作用；在同步 PR 里补条目或按 owner spec 处置；手册第 8 节加入 `make license-check` |
| `reviewed` 条目按包名生效，升级后捆绑库可能变化 | 漏审 | 报告在版本与 `reviewed_version` 不一致时打印警告；升级 PR 的审阅清单包含该警告 |
| SCA 首次运行出现大量高危（预期包括 npm `xlsx` 0.18.5；SheetJS 修复版本不在 npm 官方源发布） | `make sca` 长期红 | 首次分诊记录进 `docs/intranet/supply-chain.md`：可升级的交给 owner spec，不可立即升级的写带到期日的忽略规则 |
| 行方 grype 版本与 0.87.0 的参数不一致，或 `sbom:` 读 CycloneDX 有差异 | `make sca` 无法执行 | 任务 9.2 在行方工具镜像上实测；不兼容时退路是 grype 的 `purl:` 输入（脚本可输出 purl 列表） |
| 漏洞库更新节奏跟不上 30 天期限 | `make sca` 因库过期失败 | 这是有意为之；期限可在 `grype.yaml` 调整，但须记录在 `docs/intranet/supply-chain.md` |
| `pypdf` 抽图覆盖不到的 PDF（JBIG2 无解码器、矢量扫描件） | 个别扫描件 OCR 结果变少 | 跳过并记 warning；必要时由 `p2-05` 评估引入 `pypdfium2` 渲染（Apache-2.0/BSD-3-Clause，需重新走许可证闸门） |
| 仓库 git 历史中仍有被删的 Anthropic 文件 | 若交付完整历史，仍构成持有与分发 | 默认交付无历史的源码快照与制品；历史重写与 D7 的长期 fork 冲突（重写后无法再合并上游），须法务拍板 |
| `w2-01` 与本 spec 并行修改 `pyproject.toml`、`uv.lock`、`ocr.py` | rebase 冲突 | 锁文件冲突取对方后 `make relock`；`ocr.py` 按上文分工；过渡条目由陈旧检查自动提示 |
| 存量工作区与已发布专家快照里仍有四个技能与 `powerpoint` 的副本 | 已部署实例继续持有 | 默认行内为全新部署，无存量；否则追加清理工具（见"待行方确认"） |

**回滚：** 每个顶层任务一个提交，可按提交逆序 `git revert`。删除的技能目录、`codeql.yml` 与 `.github/codeql/` 随 revert 恢复；锁文件回滚后重新执行 `make relock`。本 spec 不写迁移、不改运行期配置，回滚不涉及数据。只想临时停用某个门禁时，不要删步骤，而是在策略文件里加带 owner 与理由的 `transitional` 条目，或调高 `SCA_FAIL_ON`，并在 `CHANGELOG-intranet.md` 登记。

## 待行方确认

**steering 第 4 节的 D 编号：**

- **D13（harness-* 源码可得）：** `powerpoint` 删除与 `skill-creator` 署名依赖 `w2-01` 的内部分支。若源码不可得，本仓库无法从 wheel 中移除这两处，只能保留过渡条目并与供应方协商发布不含这两处的版本；在此之前，交付物中仍含 Anthropic 专有材料。
- **D9（`desktop/`、`fnos/` 不交付）：** 按此假设，`pynput`、`python-xlib` 必须删除。若答复为交付，它们改为 LGPL 报备组件，`fnos/docker/LICENSE`、`fnos/native/LICENSE` 需要随包附 `NOTICE`，由 `w1-04` 保留的打包渠道补改。
- **D3（控制面数据库为 PG 系）：** `psycopg` 一族作为 LGPL 组件报备保留。若改用达梦、OceanBase 或 TiDB，新驱动需重新走闸门。
- **D4（x86_64 与 arm64）：** Python 闭包存在平台条件依赖，`make sbom` 与 `make license-check-python` 应分别在两种架构的构建机上执行，SBOM 以 `platform` 属性区分。
- **D7（长期 fork）：** 每次上游同步都要过 `make license-check`；这也决定了不能用重写 git 历史的方式清理被删文件。
- **D8（国密进二期）：** 一期签名使用 ECDSA P-256 或 RSA；SM2/SM3 由 `p2-02` 替换。
- **D2（OpenAI 兼容网关）：** 远程 OCR 走行内视觉模型时同样经 `pypdf` 抽图，不需要任何可选包。

**不属于 D 编号、但影响本 spec 边界的事项：**

1. **git 历史的交付形态。** 默认交付无历史的源码快照与制品，仓库历史中的已删文件不视为分发。需法务书面确认。
2. **存量数据。** 默认行内为全新部署，没有已创建的办公 Agent 工作区和已发布专家快照。若有试点实例，需要追加一个经 `BackendWorkspace` 清理 `skills/{docx,pdf,pptx,xlsx}/` 与 `_builtin_skills/powerpoint/` 的一次性工具，约 1.5-2 人日。
3. **行内流水线平台与工具。** 参考定义按 GitLab CI 起草；行方若使用 Jenkins 或自有平台，只需逐作业映射 make 目标。行方若已有 SCA / SAST 平台，可消费 `make sbom` 产物或替换 `GRYPE`，Makefile 契约不变。
4. **许可证分类表。** `allow` / `report` / `deny` 三张表与 MPL、EPL 的"报备"定位需要法务确认；LGPL 的源码提供方式（离线包附 sdist）需要确认。
5. **待取证的第三方内容。** 子智能体库（agency-agents）、`superpowers-methodology`（superpowers-zh）、`multi-agent-orchestrator`（agency-orchestrator）、`ai-coding-coach`（ai-coding-guide）的上游许可证与署名要求，以及是否保留。
6. **未被引用的字体。** `FSPixelSansUnicode-Regular.ttf` 默认保留并在 `NOTICE` 附 OFL-1.1 全文；也可以删除，但删除会与上游形成 modify/delete 冲突点。
7. **前端 SAST 与签名密钥托管。** 是否要求对 `dashboard/` 做安全规则扫描；签名密钥由谁生成、存放在哪、如何轮换。
