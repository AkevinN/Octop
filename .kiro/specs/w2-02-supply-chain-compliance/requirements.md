# 需求文档：许可证与供应链合规

> spec：`w2-02-supply-chain-compliance` ｜ 波次：Wave 2 ｜ 基线：`757fd12` ｜ 预估：15 人日
> 前置：`w0-02-ci-gates`、`w0-04-fork-isolation-points`、`w1-02-capability-trim`、`w1-03-online-fetch-trim`、`w1-04-content-trim`、`w1-05-saas-decoupling` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 引言

**结论：** 本 spec 让行内交付物在许可证层面"说得清、拦得住"，并补齐 `w1-04` 保留下来的流水线缺口。它做四件事：

1. **清除专有内容。** 删除 `office-automation` 专家下 `docx`、`pdf`、`pptx`、`xlsx` 四个带 Anthropic 专有许可证的技能目录（含全部 `scripts/` 树），专家人设保留，文档能力暂由管理员以本地 ZIP 技能包导入。移除唯一的 AGPL 依赖 `pymupdf`，知识库 OCR 的 PDF 转图改用已是核心依赖的 `pypdf` 与 `pillow`。
2. **建立离线可跑的闸门。** 新增一个只用标准库的脚本和一份策略文件，对 Python 运行期闭包与 npm 生产依赖逐包分类为"可保留 / 需报备 / 必须删 / 待人工裁定"，同时对仓库与已安装包做专有内容指纹扫描。闸门接入 `ci.yml` 的 Linux 与 `test-windows` 两个 job。
3. **补齐 SBOM、SCA、SAST 与签名。** 以 `Makefile.intranet` 目标为契约：CycloneDX SBOM 与第三方许可证文本汇编、grype 离线漏洞扫描、bandit 替代 CodeQL、openssl 离线签名，并附一份行内流水线参考定义。SAST 接入 CI 后删除 `codeql.yml`。
4. **完成报备材料。** 新增根目录 `NOTICE` 与 `docs/intranet/third-party-licenses.md`，逐项写明 LGPL（`psycopg` 一族、`python-telegram-bot`、`pynput`、`edge-tts`）与 AGPL（`pymupdf`）的处置，核实仓库自身 `LICENSE` 声明与实际内容一致。

预估 15 人日（区间 13-17）。本 spec 不写 fork 迁移，不新增 `config.py` 键与 `ErrorCode`，不增删任何 i18n 键，不改 `dashboard/` 源码。

### 背景

以下事实均在基线 `757fd12` 上核实，证据与行号见设计文档"现状"一节。

| 对象 | 基线状态 | 问题 |
|---|---|---|
| `office-automation` 四个技能 | 4 份 `LICENSE.txt`（md5 全部为 `f8515c3694eb11622110ca76c7c15d1b`）首行为 `© 2025 Anthropic, PBC. All rights reserved.`，禁止在 Anthropic 服务之外留存副本、复制、做衍生作品与分发；4 份 `SKILL.md` 第 4 行另有 `license: Proprietary`。四个目录共 186 个文件，经 hatch 打包进 wheel，并在建 Agent 时由 `seed_expert_directory` 复制进用户工作区 | 与根 `LICENSE` 的 MIT 声明直接冲突；每建一个办公 Agent 就发生一次分发 |
| `orcakit-harness-agent` 1.0.11 | 包内 `harness_agent/builtin/skills/{en,zh}/powerpoint/` 带同一份 Anthropic 许可证；`skill-creator` 自述改编自 Anthropic 原版，但包内无任何许可证文件 | 第三方包，本仓库改不了，只能由 `w2-01` 的内部分支处理 |
| 依赖许可证 | 在 Linux x86_64 上按"运行期闭包 + 全部 extra"建环境，共 213 个分发包：AGPL 1 个（`pymupdf`）；LGPL 7 个；MPL 4 个；元数据缺失 3 个；元数据自相矛盾 1 个（`fastembed`）；另有 `opencv-python`、`shapely` 元数据宽松但 wheel 内捆绑 LGPL 共享库 | 没有任何清单、报备材料与闸门 |
| npm 生产依赖 | `dashboard/package-lock.json` 1125 个条目中 500 个非 dev；81 个非 dev 条目缺 `license` 字段；`jsmin` 为 JSON 许可证（"Good, not Evil"，经 `build@0.1.4` 引入，`w1-04` 删除） | 只读锁文件不足以出结论 |
| 流水线 | `Makefile` 与 9 个工作流中零处许可证、SBOM、SCA、签名步骤；唯一的静态扫描是只扫 Python 的 `codeql.yml`，被 `w1-04` 按全局约束第 3 节保留待替代 | 等保与行方供应链检查常查的四项全部落空 |
| 仓库自身声明 | `LICENSE` 为 MIT（`Copyright (c) 2026 Octop`），`pyproject.toml` 声明 MIT，README 称"本项目采用 MIT License"；根目录没有 `NOTICE` | 在清理前，README 那句话不是事实陈述 |

### 为什么做

1. 许可证是交付前的法律硬门槛。专有材料只要还在 wheel 里，任何一次部署都构成分发。
2. 等保与行方供应链管理通常要求提供 SBOM、开源组件漏洞扫描、静态扫描与制品签名。`w1-04` 按约定保留了 `codeql.yml`，等本 spec 提供替代后再删；在此之前不能删，删了就是"拆掉现有能力"。
3. 全局约束 1.5"先删后改"已经让 `w1-02`、`w1-04`、`w1-05` 删掉了大部分问题包（`playwright`、`edge-tts`、`jsmin`、腾讯专有头文件）。本 spec 负责把剩下的收口，并用闸门保证后续上游同步或新依赖无法绕过。

### 范围内

1. **专有内容清除**：删除 `office-automation/skills/{docx,pdf,pptx,xlsx}/`；改写该专家的 `SOUL.md`、`IDENTITY.md`、`USER.md`、`manifest.json`，不再声称内置 Office 技能；同步调整 `tests/unit/agents/test_expert_catalog.py`。
2. **AGPL 移除**：从 `knowledge-ocr` extra 删除 `pymupdf`，改写 `src/octop/infra/knowledge/ocr.py` 的 PDF 转图路径，`make relock`。
3. **许可证闸门**：`scripts/intranet/supply_chain.py`（新增，只依赖标准库）与 `supply-chain/license-policy.toml`（新增）；`make license-check`、`license-check-python`、`license-check-npm`；专有内容指纹扫描。
4. **LGPL/AGPL 处置**：`psycopg`、`psycopg-binary`、`psycopg-pool` 报备保留；`python-telegram-bot`、`pynput`、`python-xlib` 由 `w2-01` 移除，本 spec 以带 owner 的过渡条目承接；`edge-tts`（`w1-05` 已删）与 `pymupdf`（本 spec 删）核验不存在；捆绑 LGPL 共享库的 `opencv-python`、`shapely` 人工裁定为报备。
5. **报备材料**：`NOTICE`、`docs/intranet/third-party-licenses.md`、README 两处指针；仓库内置第三方内容（子智能体库、字体等）的来源登记。
6. **SBOM**：`make sbom` 产出 Python 与 npm 两份 CycloneDX 1.5 JSON 与 `THIRD-PARTY-NOTICES.txt`。
7. **SCA**：`make sca` 以 grype 离线扫描 SBOM，`supply-chain/grype.yaml` 禁止出网。
8. **SAST**：`make sast` 以 bandit 扫描 `src/octop`，带基线；接入 CI 后删除 `.github/workflows/codeql.yml` 与 `.github/codeql/`。
9. **签名**：`make sign` / `make verify-signature`，基于 `SHA256SUMS` 与 `openssl dgst`。
10. **CI 与参考流水线**：`ci.yml` 三个 job 各加步骤；`supply-chain/pipeline.reference.yml`（新增）；契约测试 `tests/unit/test_supply_chain_contract.py`（新增）。

### 范围外

| 事项 | 归属 |
|---|---|
| 自研 Office 技能（docx / xlsx / pptx / pdf 的创建、读取、编辑、转换） | `p2-10-office-skills-rewrite` |
| `edge-tts` 依赖、edge 语音预设与前端 edge 分支的删除 | `w1-05-saas-decoupling`（已合入；前端残留见设计文档"与其他 spec 的交接"） |
| 飞书 / 元宝 bot creator 两个腾讯专有声明文件 | `w1-05-saas-decoupling`（已删除） |
| `desktop/`、`fnos/`、一键安装脚本及其中的 `pynput` 注释与 `.[desktop]` 安装 | `w1-04-content-trim`（已删除） |
| `src/octop/infra/desktop/` 及其 `pynput` 导入与测试 | `w1-02-capability-trim`（已删除） |
| `desktop` extra 与 `orcakit-harness-agent[all]` 收窄（移除 `pynput`、`python-xlib`、`evdev`、`pyobjc` 一族）；`harness-gateway` 重打包去掉 `python-telegram-bot` 等 IM SDK | `w2-01-offline-build` |
| `harness_agent` 包内 `powerpoint` 技能删除、`skill-creator` 补署名（harness-* 内部分支，D13） | `w2-01-offline-build`（本 spec 提供检测与过渡条目） |
| 运行期下载与 `install_packages` 的关闭（含 OCR 的 `ensure_ocr_deps`）；离线包中附带报备组件的 sdist；模型权重许可证 | `w2-01-offline-build` |
| `psycopg[binary]` 与系统 `libpq` 的取舍、信创数据库驱动 | `w2-03-database-adaptation` |
| SCA 分诊后具体组件的升级或替换（如 `xlsx`） | 各组件所属 spec，前端依赖归 `w4-01-frontend-baseline` |
| SM2/SM3 签名与密钥托管 | `p2-02-kms-sm-crypto` |
| 存量工作区与已发布专家快照中的历史副本清理 | 默认不做，见设计文档"待行方确认" |

## 需求

### 需求 1：清除 `office-automation` 下的 Anthropic 专有技能

**用户故事：** 作为行方法务，我希望交付物中不再包含任何禁止分发的第三方专有材料，以便 Octop 的 MIT 声明成立、部署不构成违约分发。

#### 验收标准

1. 当在仓库根执行 `rg -l -e 'Anthropic, PBC\. All rights reserved' -e '^license: Proprietary' src dashboard/src dashboard/public docker scripts plugins` 时，命令应当没有任何输出。
2. 目录 `src/octop/infra/agents/experts/library/office-automation/skills/` 下的 `docx`、`pdf`、`pptx`、`xlsx` 四个子目录应当始终不存在。
3. 当 `ExpertCatalog(default_library_root())` 刷新后读取 `office-automation` 时，该专家应当仍然存在，`prompt_files` 非空，`files` 含 `skills/file_reader/SKILL.md`，且不含任何以 `skills/docx/`、`skills/pdf/`、`skills/pptx/`、`skills/xlsx/` 开头的路径。
4. `office-automation` 的 `SOUL.md`、`IDENTITY.md`、`USER.md` 与 `manifest.json` 应当始终不声称"内置 / 开箱即用"的 Word、Excel、PPT、PDF 技能，并写明这些能力由管理员通过本地 ZIP 技能导入提供。
5. `src/octop/i18n/{en,zh}.json` 与 `dashboard/src/locales/{en,zh}.json` 应当始终不因本 spec 改变（相对任务 1 记录的基线 `git diff` 为空），`uv run pytest tests/unit/i18n -q` 通过。

### 需求 2：移除 AGPL 依赖 `pymupdf`

**用户故事：** 作为行方法务，我希望运行期依赖中不存在 AGPL 组件，以便交付物不触发强 copyleft 的源码公开义务。

#### 验收标准

1. `pyproject.toml` 与 `uv.lock` 应当始终不含 `pymupdf`；`knowledge-ocr` extra 只剩 `rapidocr` 与 `onnxruntime`。
2. 当本地或远程 OCR 后端处理 PDF 时，`_image_inputs` 应当按页序用 `pypdf` 抽取每页内嵌图片，逐张转换为 PNG 字节后产出，媒体类型为 `image/png`。
3. 如果某页没有内嵌图片，那么该页应当不产出 OCR 输入且不抛异常；如果某张图片无法解码，那么应当跳过该图并记录一条 warning 日志。
4. 当调用 `ensure_ocr_deps(backend="remote")` 时，函数应当直接返回 `"ready"`，不调用 `install_packages`。
5. `src/` 与 `pyproject.toml` 中应当始终不出现 `pymupdf`（`tests/` 中只允许出现在断言其不存在的守卫用例里）；`uv run pytest tests/unit/knowledge -q` 通过。

### 需求 3：Python 运行期依赖的许可证闸门

**用户故事：** 作为供应链负责人，我希望每个随产品交付的 Python 包都有经过判定的许可证类别，以便新依赖或上游同步引入的问题包在合入前被拦下。

#### 验收标准

1. 当执行 `make license-check-python` 时，Makefile 应当在 `build/compliance-venv` 用 `uv sync --frozen --no-dev --all-extras --no-extra dev --no-install-project` 建立运行期闭包，然后对其中每个分发包输出类别（`allow` / `report` / `deny` / `review`）与判定依据，报告写入 `dist/compliance/licenses-python.json`。
2. 如果闭包中存在 `deny` 类包（AGPL、GPL、SSPL、专有、JSON 等），且策略文件中没有该包的 `overrides` 或 `transitional` 条目，那么目标应当以退出码 1 失败，并打印包名、版本与判定依据。
3. 如果 `report` 类包未登记在策略文件的 `reported` 表，或者 `report` 类包、以及 `OR` 表达式中舍弃了 `report` / `deny` 分支的包没有出现在根目录 `NOTICE` 中，那么目标应当以退出码 1 失败。
4. 如果某包的许可证元数据缺失、多个来源的类别互相矛盾，或元数据为宽松许可但随包许可证文件中含有 GNU GPL / LGPL / AGPL 的标题行，那么该包应当判为 `review`；策略文件没有对应的 `overrides` 或 `reviewed` 条目时，目标应当以退出码 1 失败。
5. 在判定 SPDX 表达式期间，闸门应当对 `OR` 取最宽松分支、对 `AND` 取最严格分支，并把包名按 PEP 503 规范化（`[-_.]+` 归一为 `-` 并转小写）后再与策略文件匹配。
6. 如果策略文件中任一包级条目指向 `uv.lock` 中已不存在的包，或 `reported` 条目登记的许可证与判定结果不一致，那么目标应当以退出码 1 失败并指出该条目。
7. 如果执行环境中没有 `uv`，或 compliance 环境无法建立，那么目标应当以退出码 2 失败，而不是退回读取开发环境。
8. 判定步骤应当始终只读取已安装分发包的元数据与许可证文件，不发起网络请求；建环境只访问 uv 已配置的索引（行内为私服）。

### 需求 4：npm 生产依赖的许可证闸门

**用户故事：** 作为供应链负责人，我希望打包进前端产物的 npm 依赖同样经过许可证判定，以便前端依赖不成为盲区。

#### 验收标准

1. 当执行 `make license-check-npm` 时，闸门应当只评估 `dashboard/package-lock.json` 中不带 `dev` 或 `devOptional` 标记的条目，许可证优先取 `dashboard/node_modules/<条目路径>/package.json`，其次取锁文件条目的 `license` 字段，报告写入 `dist/compliance/licenses-npm.json`。
2. 如果 `dashboard/node_modules` 不存在，那么目标应当以退出码 2 失败，并提示先执行 `make install-frontend`。
3. 如果生产依赖中有 `deny` 类或未登记的 `report` / `review` 类条目，那么目标应当以退出码 1 失败，判定规则与需求 3 相同（策略写在 `npm` 命名空间下）。
4. `make license-check` 应当始终等价于依次执行 `license-check-python` 与 `license-check-npm`。

### 需求 5：专有内容指纹扫描

**用户故事：** 作为行方法务，我希望被删除的专有材料不会随上游同步或第三方包更新悄悄回来，以便清理结果可以长期保持。

#### 验收标准

1. 当执行 `make license-check-python` 时，闸门应当扫描仓库目录 `src`、`dashboard/src`、`dashboard/public`、`docker`、`scripts`、`plugins` 与 compliance 环境的 site-packages，命中策略文件 `proprietary.markers` 中任一标记即以退出码 1 失败并列出文件。
2. 如果命中文件被 `proprietary.transitional` 条目的路径模式覆盖，那么闸门应当只打印带 owner spec 的警告，不使目标失败。
3. 如果某条 `proprietary.transitional` 条目没有匹配到任何文件，那么目标应当以退出码 1 失败，提示删除陈旧条目。
4. 标记集应当始终至少包含 `Anthropic, PBC. All rights reserved`、行首的 `license: Proprietary`、`Unauthorized copying, modification, distribution` 三项，且在基线 compliance 环境中不误报 `anthropic` 与 `mcp` 两个 MIT 包（它们的版权行含 `Anthropic, PBC`）。

### 需求 6：LGPL 与 AGPL 依赖的逐项处置

**用户故事：** 作为行方法务，我希望每个弱 copyleft 与强 copyleft 依赖都有明确的去留结论和责任 spec，以便报备材料可以直接提交审批。

#### 验收标准

1. `psycopg`、`psycopg-binary`、`psycopg-pool` 应当始终登记在策略文件 `reported` 表中，写明许可证、用途（Python import 动态加载、未修改）与源码获取方式，并出现在 `NOTICE` 中。
2. 如果本 spec 合入时 `uv.lock` 仍含 `python-telegram-bot`、`pynput`、`python-xlib`，那么它们应当以 owner 为 `w2-01-offline-build` 的 `transitional` 条目登记；这些包从 `uv.lock` 消失后，条目应当同批删除（由需求 3.6 强制）。
3. `uv.lock` 应当始终不含名为 `edge-tts` 与 `pymupdf` 的包。
4. `opencv-python`、`shapely`、`numpy` 若在闭包中，应当以 `reviewed` 条目登记人工结论（前两者为 `report`，写明 wheel 内捆绑的 LGPL 共享库）；`fastembed`、`agent-client-protocol`、`deepagents-backends`、`py-rust-stemmers` 若在闭包中，应当以 `overrides` 条目登记附证据的人工结论。
5. `docs/intranet/third-party-licenses.md` 应当对上述每个包写明处置（删除 / 报备保留 / 可保留）、owner spec 与依据。

### 需求 7：`NOTICE`、许可证文档与仓库自身声明

**用户故事：** 作为交付接收方，我希望从交付物本身就能看到 Octop 自身的许可证与全部第三方许可证义务，以便不必翻源码仓库。

#### 验收标准

1. 仓库根应当新增 `NOTICE`，包含：Octop 自身代码采用 MIT；需报备组件清单；双许可组件的择一声明；随仓库分发的第三方内容及其许可证全文或获取方式；SBOM 与 `THIRD-PARTY-NOTICES.txt` 的位置说明。
2. 当执行 `make build-wheel` 时，产出的 wheel 应当在 `*.dist-info/licenses/` 下包含 `NOTICE`。
3. `README.md` 与 `README_CN.md` 的 MIT 声明之后应当各有一句话指向 `NOTICE` 与 `docs/intranet/third-party-licenses.md`。
4. `LICENSE` 应当始终保持基线的 MIT 全文不变，并与 `pyproject.toml` 的 `license` 字段一致。
5. `docs/intranet/third-party-licenses.md` 应当包含分类规则、报备清单、人工裁定清单与仓库内置第三方内容的来源登记（含待法务取证项）。

### 需求 8：SBOM 与第三方许可证文本汇编

**用户故事：** 作为行方供应链管理员，我希望每次构建都附带机器可读的 SBOM 与许可证文本，以便导入行内的开源治理平台。

#### 验收标准

1. 当执行 `make sbom` 时，应当生成 `dist/compliance/sbom-python.cdx.json` 与 `dist/compliance/sbom-npm.cdx.json`，二者均为 CycloneDX 1.5 JSON，每个组件含 `name`、`version`、`purl` 与 `licenses`。
2. 两份 SBOM 的组件集合应当始终分别与同一次运行生成的 `licenses-python.json`、`licenses-npm.json` 的包集合相同。
3. 当执行 `make sbom` 时，应当生成 `dist/compliance/THIRD-PARTY-NOTICES.txt`，汇编闭包中每个包随包提供的许可证文本；没有随包许可证文件的包应当显式标注。
4. 在输入不变期间，连续两次执行 `make sbom` 的三个输出文件应当逐字节相同。

### 需求 9：SCA 漏洞扫描

**用户故事：** 作为安全负责人，我希望在完全断网的环境里对全部组件做已知漏洞扫描，以便高危漏洞在交付前被处置。

#### 验收标准

1. 当执行 `make sca` 时，应当用 grype 与 `supply-chain/grype.yaml` 分别扫描两份 SBOM；任一份存在严重度不低于 `SCA_FAIL_ON`（默认 `high`）且未被忽略的漏洞时以非零退出码结束，并把 JSON 报告写入 `dist/compliance/sca-python.json` 与 `dist/compliance/sca-npm.json`。
2. 如果找不到 grype 可执行文件或 SBOM 文件，那么目标应当以退出码 2 失败；如果漏洞库缺失或超过 `max-allowed-built-age`，那么目标应当以非零退出码失败。
3. `supply-chain/grype.yaml` 应当始终设置 `check-for-app-update: false` 与 `db.auto-update: false`，使扫描不发起任何出网连接。
4. 如果 `supply-chain/grype.yaml` 中某条 `ignore` 规则前没有写明理由、审批人与到期日期的注释，那么 `make sca` 应当以退出码 1 失败。
5. 首次在行内环境执行 `make sca` 后，全部 high 及以上结果应当在 `docs/intranet/supply-chain.md` 的分诊表中有处置记录（升级、交给 owner spec，或带到期日的忽略）。

### 需求 10：SAST 替代 CodeQL

**用户故事：** 作为安全负责人，我希望静态扫描在离线环境可执行并能阻断新增高危问题，以便删除 GitHub CodeQL 后能力不倒退。

#### 验收标准

1. 当执行 `make sast` 时，应当用 bandit 扫描 `src/octop`（排除 `src/octop/dashboard`）；出现不在 `supply-chain/bandit-baseline.json` 中的 HIGH 严重度且置信度不低于 MEDIUM 的结果时，目标应当以退出码 1 失败，并把全部严重度的结果写入 `dist/compliance/sast-bandit.json`。
2. `bandit` 应当登记在 `pyproject.toml` 的 `[project.optional-dependencies].dev` 与 `[dependency-groups].dev` 两处，并由 `make relock` 写入 `uv.lock`；它应当始终不进入运行期闭包。
3. `supply-chain/bandit-baseline.json` 应当只含经人工确认的误报，每一条在 `docs/intranet/supply-chain.md` 写明理由。
4. 当 CI 的 `quality` job 已执行 `make sast` 时，`.github/workflows/codeql.yml` 与 `.github/codeql/` 应当不存在。
5. 当在 `src/octop` 下临时加入一个调用 `hashlib.md5(data)` 的文件时，`make sast` 应当失败。

### 需求 11：制品签名

**用户故事：** 作为行方运维，我希望能离线验证收到的制品未被篡改，以便满足制品完整性要求。

#### 验收标准

1. 当执行 `make sign SIGNING_KEY=<私钥文件>` 时，应当对 `SIGN_DIR`（默认 `dist`）下的全部文件生成 `SHA256SUMS`（与 `sha256sum -c` 兼容、使用 `/` 分隔的相对路径、按路径排序），并用 `openssl dgst -sha256 -sign` 生成 `SHA256SUMS.sig`。
2. 当执行 `make verify-signature SIGNING_PUBKEY=<公钥文件>` 时，应当依次验证签名与每个文件的摘要；任一文件被改动或签名不匹配时以非零退出码结束。
3. 如果未提供 `SIGNING_KEY`，或执行环境中找不到 `openssl`，那么 `make sign` 应当以退出码 2 失败。
4. 仓库中应当始终没有私钥：`supply-chain/`、`scripts/intranet/`、`docs/intranet/` 与 `NOTICE` 中不出现 `PRIVATE KEY` 字样。

### 需求 12：CI 接线、行内流水线参考定义与维护

**用户故事：** 作为 fork 维护者，我希望供应链门禁在 GitHub CI 与行内流水线上以同一组 Makefile 目标运行，并在上游同步时不被悄悄丢掉，以便门禁长期有效。

#### 验收标准

1. `.github/workflows/ci.yml` 的 `quality` 与 `test-windows` 两个 job 应当在 `make test` 之后执行 `make license-check-python`；`quality` job 还应当执行 `make sast`；`frontend` job 应当在 `make check-frontend` 之后执行 `make license-check-npm`。
2. `supply-chain/pipeline.reference.yml` 应当按阶段调用 `make install`、`lint`、`typecheck`、`test`、`install-frontend`、`check-frontend`、`test-postgresql`、`build`、`license-check`、`sast`、`sbom`、`sca`、`sign`，`build` 所在阶段先于 `sbom`、`sca`、`sign` 所在阶段，凭据只来自流水线变量。
3. `tests/unit/test_supply_chain_contract.py` 应当断言本需求 1、2 条、需求 9.3、需求 10.4、需求 11.4 与 `Makefile.intranet` 中全部供应链目标的定义；任一项被删除时 `make test` 变红。
4. `make help-intranet` 应当列出 `license-check`、`license-check-python`、`license-check-npm`、`sbom`、`sca`、`sast`、`sign`、`verify-signature`、`supply-chain` 九个目标。
5. `docs/intranet/upstream-sync.md` 的验证命令应当包含 `make license-check`；`CHANGELOG-intranet.md` 应当有以 `w2-02-supply-chain-compliance` 开头的条目；`AGENTS.md` §9 应当有指向供应链门禁的一行。
