# 实施计划：许可证与供应链合规

> spec：`w2-02-supply-chain-compliance` ｜ 波次：Wave 2 ｜ 基线：`757fd12` ｜ 预估：15 人日
> 前置：`w0-02-ci-gates`、`w0-04-fork-isolation-points`、`w1-02-capability-trim`、`w1-03-online-fetch-trim`、`w1-04-content-trim`、`w1-05-saas-decoupling` ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

每个顶层任务完成后可独立提交；提交前运行任务内的验证命令。

约定：

- 任务 1 记录的起始提交记为 `W202_BASE`；用到它的命令执行前先 `export W202_BASE=<任务 1 记录的提交>`。
- 改依赖的任务把 `make relock PYPI_INDEX=<行内 PyPI 私服> NPM_REGISTRY=<行内 npm 私服>`（参数与上一次重生成锁文件时一致）作为该任务最后一个单独提交，不手改锁文件。
- 新增测试遵守 AGENTS.md §7 的跨平台约定：`pathlib`、`tmp_path`、`encoding="utf-8"`，不断言 POSIX 路径。
- 本 spec 不修改任何 i18n JSON，不改 `dashboard/` 源码，不新增 `config.py` 键、`ErrorCode` 与 fork 迁移。
- `w2-01-offline-build` 与本 spec 并行。后合入的一方先 rebase，再执行 `make relock` 与 `make license-check`，并按设计文档"与其他 spec 的交接"增删 `transitional` 条目。

- [ ] 1. 确认前置 spec 已合入并记录基线（0.25 人日）
  - 改动：无代码改动。在 PR 描述里记录 `git rev-parse HEAD`（即 `W202_BASE`）、`make all` 的结果，以及下面几条命令的输出；这些输出决定任务 5.2 是否写 `transitional` 条目。
  - 验证：`test -f Makefile.intranet && rg -n '^(install-frontend|check-frontend|test-postgresql|relock|help-intranet):' Makefile.intranet && test -f CHANGELOG-intranet.md && test -f docs/intranet/upstream-sync.md && test -f tests/unit/test_ci_gates_contract.py && rg -n '^  frontend:' .github/workflows/ci.yml`
  - 验证：`test ! -e src/octop/infra/desktop && test ! -e src/octop/infra/gateway/bot_creators && test ! -e src/octop/infra/agents/experts/library/office-automation/skills/news && test -f .github/workflows/codeql.yml && test -d .github/codeql && ! rg -n '^name = "(edge-tts|playwright)"$' uv.lock && ! rg -n '"node_modules/(build|jsmin)"' dashboard/package-lock.json`
  - 验证（记录，决定过渡条目）：`rg -n '^name = "(pynput|python-xlib|python-telegram-bot|evdev|agent-client-protocol|fastembed|pymupdf)"$' uv.lock`
  - 验证（记录，决定专有过渡条目）：`uv run --no-sync python -c "import pathlib, harness_agent; print((pathlib.Path(harness_agent.__file__).parent / 'builtin' / 'skills' / 'en' / 'powerpoint').exists())"`
  - 验证（核对 `w1-05` 的遗漏，有输出时在 PR 中提示 `w1-05` 负责人，本 spec 不修）：`rg -n '"edge"|browserNoChineseVoice' dashboard/src/hooks/useVoiceOutput.ts`
  - 验证：`make install-frontend && make all`
  - _需求：1.5, 6.2, 6.3_

- [ ] 2. 删除 `office-automation` 的四个专有技能（1 人日）
  - [ ] 2.1 先改测试
    - 改动：`tests/unit/agents/test_expert_catalog.py` 删除 `test_bundled_office_automation_discovers_skills`（≈L235-251），新增 `test_bundled_office_automation_has_no_proprietary_skills`：刷新 `ExpertCatalog(default_library_root())` 后断言 `office-automation` 存在、`prompt_files` 非空、`"skills/file_reader/SKILL.md" in expert.files`、`expert.files` 中没有以 `skills/docx/`、`skills/pdf/`、`skills/pptx/`、`skills/xlsx/` 开头的路径，且 `read_file_contents("office-automation")` 的每个 `content` 都不含 `Anthropic, PBC` 与 `license: Proprietary`。
    - 验证：`uv run pytest tests/unit/agents/test_expert_catalog.py -q -k office_automation`（此时应失败）
    - _需求：1.3_
  - [ ] 2.2 删除四个技能目录
    - 改动：删除 `src/octop/infra/agents/experts/library/office-automation/skills/docx/`、`skills/pdf/`、`skills/pptx/`、`skills/xlsx/`（含 `LICENSE.txt`、`SKILL.md`、`scripts/` 与 `editing.md`、`pptxgenjs.md`、`forms.md`、`reference.md`）。不从被删目录保留或挪用任何文件。
    - 验证：`test "$(ls src/octop/infra/agents/experts/library/office-automation/skills)" = "file_reader" && ! rg -l -e 'Anthropic, PBC\. All rights reserved' -e '^license: Proprietary' src dashboard/src dashboard/public docker scripts plugins && uv run pytest tests/unit/agents/test_expert_catalog.py -q`
    - _需求：1.1, 1.2, 1.3_
  - [ ] 2.3 改写人设
    - 改动：`office-automation/SOUL.md`：技能表只留 `file_reader` 一行；新增"Word、Excel、PPT、PDF 文档技能由管理员以技能包（本地 ZIP）导入；先检查工作区里是否已有对应技能，没有时告诉用户联系管理员导入，不要自行编写解析 Office 文件的脚本"；删除 ≈L23 以"matching skill has scripts"为前提的边界句。
    - 改动：`office-automation/IDENTITY.md` 与 `USER.md`（改完保持逐字相同）：自我介绍（≈L18）改为"导入对应技能包后可处理 Word、Excel、PPT、PDF"；"务实"一条（≈L29）去掉"优先调用对应技能（docx / xlsx / pptx / pdf）"；"Bundled Skills"（≈L31-38）只留 `file_reader`。
    - 改动：`office-automation/manifest.json`：`description.zh` 与 `description.en` 删去"内置 Word、Excel、PPT、PDF 全套文档技能"与 "bundled Word, Excel, PPT, and PDF skills"，改为"导入文档技能包后可处理 Word、Excel、PPT、PDF"；其余字段不动。不引入 `MBTI`、`browser_use` 字样。
    - 验证：`! rg -n -e '\| `(docx|xlsx|pptx|pdf)` \|' -e '\*\*(docx|xlsx|pptx|pdf)\*\*' -e '开箱即用' -e '内置 Word' -e 'bundled Word' src/octop/infra/agents/experts/library/office-automation && rg -n '技能包' src/octop/infra/agents/experts/library/office-automation/SOUL.md src/octop/infra/agents/experts/library/office-automation/IDENTITY.md src/octop/infra/agents/experts/library/office-automation/manifest.json && cmp src/octop/infra/agents/experts/library/office-automation/IDENTITY.md src/octop/infra/agents/experts/library/office-automation/USER.md`
    - 验证：`uv run python -c "import json, pathlib; json.loads(pathlib.Path('src/octop/infra/agents/experts/library/office-automation/manifest.json').read_text(encoding='utf-8'))" && uv run pytest tests/unit/agents/test_expert_catalog.py tests/unit/test_content_trim_guard.py tests/unit/i18n -q`
    - 验证：`git diff --exit-code "$W202_BASE" -- src/octop/i18n/en.json src/octop/i18n/zh.json dashboard/src/locales/en.json dashboard/src/locales/zh.json`
    - _需求：1.4, 1.5_

- [ ] 3. 移除 AGPL 依赖 `pymupdf`（1.5 人日）
  - [ ] 3.1 先写会失败的测试
    - 改动：`tests/unit/knowledge/test_ocr.py` 新增：`test_pdf_image_inputs_extract_embedded_images`（用 `PIL.Image.save(pdf, save_all=True, append_images=[...])` 生成两页 PDF，`list(ocr._image_inputs(pdf))` 为两项，每项字节以 `b"\x89PNG"` 开头、媒体类型为 `image/png`）；`test_pdf_without_images_yields_nothing`（`pypdf.PdfWriter().add_blank_page(...)` 生成的 PDF 产出空列表）；`test_undecodable_pdf_image_is_skipped`（`monkeypatch` 把 `pypdf.PdfReader` 换成返回一页、其图片的 `image` 属性抛异常的假对象，断言产出空列表且 `caplog` 有 warning）；`test_remote_ocr_deps_need_no_install`（把 `ocr.install_packages` 换成抛 `AssertionError` 的函数，`ocr.ensure_ocr_deps(backend="remote") == "ready"`）；`test_ocr_module_does_not_reference_pymupdf`（`ocr.py` 源码不含 `pymupdf`）。
    - 验证：`uv run pytest tests/unit/knowledge/test_ocr.py -q`（此时应失败）
    - _需求：2.2, 2.3, 2.4_
  - [ ] 3.2 改写 `ocr.py`
    - 改动：`src/octop/infra/knowledge/ocr.py`：`_LOCAL_PACKAGES`（≈L27）去掉 `pymupdf>=1.24`；删除 `_PDF_SPEC`（≈L29）与 `pdf_ocr_deps_available`（≈L82）；`local_ocr_deps_available`（≈L73）只探测 `rapidocr`；`ensure_ocr_deps`（≈L90）的 `import_modules` 改为 `("rapidocr", "onnxruntime")`，非 `onnx` 分支直接返回 `"ready"`；`get_ocr_capability`（≈L140）中 remote 的 `deps_available` 改为 `True`；`_image_inputs`（≈L232）的 PDF 分支改为 `pypdf.PdfReader` 逐页抽取 `page.images`，经 pillow 存为 PNG，单张失败时 `logger.warning` 后跳过（新增模块级 `logger` 与 `io` 导入）。不动 `install_packages` 的调用方式（归 `w2-01`）。
    - 验证：`uv run pytest tests/unit/knowledge tests/unit/api/test_knowledge_bases.py -q && ! rg -n pymupdf src`
    - _需求：2.2, 2.3, 2.4, 2.5_
  - [ ] 3.3 删除依赖并重生成锁文件
    - 改动：`pyproject.toml` 的 `knowledge-ocr` extra（≈L73-77）删除 `"pymupdf>=1.24",`；执行 `make relock`，锁文件单独一个提交。
    - 验证：`! rg -n pymupdf pyproject.toml && ! rg -n '^name = "(pymupdf|edge-tts)"$' uv.lock && uv lock --check && uv run pytest tests/unit/knowledge -q`
    - _需求：2.1, 2.5, 6.3_

- [ ] 4. 许可证判定脚本 `scripts/intranet/supply_chain.py`（2.5 人日）
  - [ ] 4.1 先写 Python 侧的失败用例
    - 改动：新增 `tests/unit/test_supply_chain.py`：用 `importlib.util.spec_from_file_location` 加载 `scripts/intranet/supply_chain.py` 并先注册进 `sys.modules`；夹具在 `tmp_path` 下伪造 `<name>-<ver>.dist-info/METADATA` 与 `licenses/` 文件、最小策略文件、最小 `uv.lock` 与 `NOTICE`。用例名统一以 `test_python_` 开头，覆盖设计文档"测试策略"第 1-9 条：MIT 放行；AGPL 判 `deny` 且 `main()` 返回 1；`pymupdf` 双许可字符串经别名判 `deny`；LGPL 未登记 / 已登记且在 NOTICE / 已登记但 NOTICE 缺名；`EPL-2.0 OR BSD-3-Clause` 的择一与 NOTICE 要求；`MPL-2.0 AND MIT` 判 `report`；元数据全空判 `review` 与 `overrides` 生效；`Apache License` 与 `Other/Proprietary License` 矛盾判 `review`；许可证文件含 LGPL 标题行判 `review`、仅正文提及不判；陈旧条目判红；`discord.py` 与 `discord-py` 同名；`transitional` 放行并带 owner 警告；`reported` 许可证与判定不一致判红。另加 `test_python_script_has_no_network_imports`（脚本源码不导入 `socket`、`http.client`、`urllib.request`、`requests`）。
    - 验证：`uv run pytest tests/unit/test_supply_chain.py -q -k python`（此时应失败：脚本不存在）
    - _需求：3.2, 3.3, 3.4, 3.5, 3.6, 3.8_
  - [ ] 4.2 实现 Python 侧判定
    - 改动：新增 `scripts/intranet/supply_chain.py`（只用标准库，启动时检查 Python ≥ 3.11，否则退出码 2）：`normalize_name`、`load_policy`、`evaluate_expression`（括号、`AND`、`OR`、`WITH`；类别序 `allow < report < review < deny`）、`classify_python`（`License-Expression` 优先；否则汇总 `License` 字段与 classifier；许可证文件标题行检查）、`check`、`main` 的 `licenses python` 子命令与报告 JSON（按包名排序）。签名见设计文档。
    - 验证：`uv run pytest tests/unit/test_supply_chain.py -q -k python && uv run python scripts/intranet/supply_chain.py --help`
    - _需求：3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.8_
  - [ ] 4.3 npm 侧判定（测试先行）
    - 改动：先在 `tests/unit/test_supply_chain.py` 加 `test_npm_*` 用例（设计文档"测试策略"第 10 条），确认失败；再实现 `classify_npm` 与 `licenses npm` 子命令：只取不带 `dev` / `devOptional` 的条目；许可证优先读 `node_modules/<条目路径>/package.json` 的 `license`（兼容旧式 `licenses` 数组），其次读锁文件条目；`node_modules` 不存在时退出码 2；策略读 `npm` 命名空间。
    - 验证：`uv run pytest tests/unit/test_supply_chain.py -q -k npm`
    - _需求：4.1, 4.2, 4.3_
  - [ ] 4.4 专有内容指纹扫描（测试先行）
    - 改动：先加 `test_proprietary_*` 用例（设计文档"测试策略"第 11 条，含 `Copyright 2023 Anthropic, PBC` 不命中），确认失败；再实现 `scan_proprietary` 与 `proprietary` 子命令：扫描给定仓库目录与当前解释器 `sysconfig.get_paths()` 的 `purelib`、`platlib`；只读 `.py`、`.md`、`.txt`、无后缀文件与以 `LICENSE`/`COPYING`/`NOTICE` 开头的文件，单文件 2 MB 以内；`markers` 为子串匹配，`line_start_markers` 为行首匹配；`transitional` 路径用 `fnmatch` 相对 site-packages 根匹配。
    - 验证：`uv run pytest tests/unit/test_supply_chain.py -q`
    - _需求：5.1, 5.2, 5.3, 5.4_

- [ ] 5. 策略分诊、`NOTICE` 与许可证目标（2 人日）
  - [ ] 5.1 `Makefile.intranet` 许可证目标
    - 改动：`Makefile.intranet` 追加设计文档中的变量与 `compliance-env`、`license-check-python`、`license-check-npm`、`license-check` 四个目标（路径一律相对）；`help-intranet` 追加对应说明行。不改根 `Makefile`。
    - 验证：`make -n license-check-python | rg -e 'UV_PROJECT_ENVIRONMENT=build/compliance-venv' -e '--no-extra dev' -e '--no-install-project'`（期望三处都命中）
    - 验证：`env PATH=/nonexistent "$(command -v make)" compliance-env; echo "rc=$?"`（期望输出 `[compliance] uv is required` 且 `rc=2`）
    - 验证：`mkdir -p build && mv dashboard/node_modules build/node_modules.bak; make license-check-npm; echo "rc=$?"; mv build/node_modules.bak dashboard/node_modules`（期望 `rc=2`，并提示执行 `make install-frontend`）
    - _需求：3.1, 3.7, 4.2, 4.4, 12.4_
  - [ ] 5.2 初始策略文件与人工裁定
    - 改动：新增 `supply-chain/license-policy.toml`：三张类别表、别名表、classifier 映射表；执行 `make license-check-python` 与 `make license-check-npm`，逐条处理报告中的未映射字符串与违规，补齐：`reported`（`psycopg`、`psycopg-binary`、`psycopg-pool`、`certifi`、`bidict`、`orjson`、`tqdm`）、`reviewed`（`opencv-python`、`shapely` 为 `report`，`numpy` 为 `allow`，理由写捆绑的共享库与版本）、`overrides`（`fastembed`、`agent-client-protocol`、`deepagents-backends`、`py-rust-stemmers` 中仍在锁文件里的，证据写随包许可证文件）、`transitional`（仅任务 1 记录到仍在锁文件中的 `pynput`、`python-xlib`、`python-telegram-bot`，owner 为 `w2-01-offline-build`）、`proprietary` 标记与（仅当任务 1 记录到 `powerpoint` 存在时）`harness_agent/builtin/skills/*/powerpoint/*` 过渡条目。每个 `reviewed` 与 `overrides` 条目在 `docs/intranet/third-party-licenses.md` 草稿里写明核验过程。
    - 验证：`uv run python -c "import tomllib; tomllib.load(open('supply-chain/license-policy.toml', 'rb'))"`
    - 验证：`make license-check-python; uv run --no-sync python -c "import json; r = json.load(open('dist/compliance/licenses-python.json', encoding='utf-8')); bad = [v for v in r['violations'] if 'NOTICE' not in v]; assert not bad, bad"`（`NOTICE` 在任务 5.3 才新增，此时剩余违规应只与 `NOTICE` 缺名有关）
    - _需求：5.4, 6.1, 6.2, 6.4_
  - [ ] 5.3 新增 `NOTICE`
    - 改动：新增根目录 `NOTICE`，内容按设计文档：Octop 自身 MIT；SBOM 与 `THIRD-PARTY-NOTICES.txt` 位置；报备组件（含捆绑共享库清单）；双许可择一（`paho-mqtt` 择 BSD-3-Clause、`dompurify` 择 Apache-2.0、`orjson` 的 `(Apache-2.0 OR MIT)` 择 MIT）；随仓库分发的第三方内容（字体附 OFL-1.1 全文；子智能体库注明来源，许可证全文待法务取回）。
    - 验证：`make license-check-python && make install-frontend && make license-check-npm && test -s dist/compliance/licenses-python.json && test -s dist/compliance/licenses-npm.json`
    - _需求：3.3, 6.1, 7.1_
  - [ ] 5.4 负向验证
    - 改动：无代码改动，临时修改后恢复。
    - 验证：`cp supply-chain/license-policy.toml build/policy.bak && sed -i '/^\[reported\.psycopg\]/,/^$/d' supply-chain/license-policy.toml; make license-check-python; echo "rc=$?"; cp build/policy.bak supply-chain/license-policy.toml`（期望 `rc` 非零，报告指出 `psycopg` 未登记）
    - 验证：`cp NOTICE build/NOTICE.bak && sed -i 's/paho-mqtt/paho_mqtt_removed/' NOTICE; make license-check-python; echo "rc=$?"; cp build/NOTICE.bak NOTICE`（期望 `rc` 非零，指出 `paho-mqtt` 的择一未写入 NOTICE）
    - 验证：`git status --short supply-chain/license-policy.toml NOTICE`（期望恢复后无改动）
    - _需求：3.2, 3.3_

- [ ] 6. 许可证文档与仓库自身声明（1 人日）
  - [ ] 6.1 `docs/intranet/third-party-licenses.md`
    - 改动：新增该文档，章节：分类规则（三张表与 `review` 的触发条件）；处置总表（`pymupdf`、`edge-tts`、`pynput`、`python-xlib`、`python-telegram-bot`、`psycopg` 一族、MPL 四包、`paho-mqtt`、`opencv-python`、`shapely`、`numpy`、`fastembed` 等，列出处置、owner spec、依据）；人工裁定与证据；第三方包内的专有内容（`harness_agent` 的 `powerpoint` 与 `skill-creator`，owner `w2-01`）；仓库内置第三方内容来源登记（子智能体库、`superpowers-methodology`、`multi-agent-orchestrator`、`ai-coding-coach`、字体），待取证项单列；报备材料清单与更新流程（改依赖 → `make relock` → `make license-check` → 补条目）。
    - 验证：`for p in pymupdf edge-tts pynput python-xlib python-telegram-bot psycopg-binary psycopg-pool certifi orjson paho-mqtt opencv-python shapely numpy fastembed powerpoint skill-creator agency-agents superpowers-zh FSPixelSans; do rg -q -F -e "$p" docs/intranet/third-party-licenses.md || echo "missing $p"; done`（期望无输出）
    - _需求：6.5, 7.5_
  - [ ] 6.2 README 指针、wheel 中的 `NOTICE` 与 `LICENSE` 核实
    - 改动：`README.md` ≈L540 与 `README_CN.md` ≈L534 的 MIT 句之后各加一句：第三方组件的许可证与报备见 `NOTICE` 与 `docs/intranet/third-party-licenses.md`。`LICENSE` 与 `pyproject.toml` 的 `license` 字段不改。
    - 验证：`rg -n 'NOTICE' README.md README_CN.md && git diff --exit-code "$W202_BASE" -- LICENSE && rg -n '^license = \{ text = "MIT" \}' pyproject.toml`
    - 验证：`make build-wheel && uv run --no-sync python -c "import glob, zipfile; names = zipfile.ZipFile(sorted(glob.glob('dist/octop-*.whl'))[-1]).namelist(); assert any(n.endswith('.dist-info/licenses/NOTICE') for n in names), 'NOTICE missing'"`
    - _需求：7.2, 7.3, 7.4_

- [ ] 7. SBOM 与第三方许可证文本（1.5 人日）
  - [ ] 7.1 先写失败用例
    - 改动：`tests/unit/test_supply_chain.py` 加 `test_sbom_*` 与 `test_notices_*`（设计文档"测试策略"第 12 条）：CycloneDX 必备字段与 `specVersion == "1.5"`；purl 规范化；组件集合等于判定结果集合；同一输入两次输出逐字节相同；`notices` 汇编随包许可证文本，没有许可证文件的包输出"未随包提供许可证文本"标注。
    - 验证：`uv run pytest tests/unit/test_supply_chain.py -q -k "sbom or notices"`（此时应失败）
    - _需求：8.1, 8.2, 8.3, 8.4_
  - [ ] 7.2 实现并接入 `make sbom`
    - 改动：`scripts/intranet/supply_chain.py` 实现 `to_cyclonedx`、`write_notices`、`sbom` 与 `notices` 子命令（`serialNumber` 用组件列表的 uuid5；仅在设置 `SOURCE_DATE_EPOCH` 时写时间戳；`metadata.component` 的版本读 `pyproject.toml`；`properties` 写类别与 `sysconfig.get_platform()`）；`Makefile.intranet` 追加 `sbom` 目标与 `help-intranet` 行。
    - 验证：`uv run pytest tests/unit/test_supply_chain.py -q && make install-frontend && make sbom && test -s dist/compliance/sbom-python.cdx.json && test -s dist/compliance/sbom-npm.cdx.json && test -s dist/compliance/THIRD-PARTY-NOTICES.txt`
    - 验证：`mkdir -p build/sbom-prev && cp dist/compliance/sbom-python.cdx.json dist/compliance/sbom-npm.cdx.json dist/compliance/THIRD-PARTY-NOTICES.txt build/sbom-prev/ && make sbom && cmp build/sbom-prev/sbom-python.cdx.json dist/compliance/sbom-python.cdx.json && cmp build/sbom-prev/sbom-npm.cdx.json dist/compliance/sbom-npm.cdx.json && cmp build/sbom-prev/THIRD-PARTY-NOTICES.txt dist/compliance/THIRD-PARTY-NOTICES.txt`
    - _需求：8.1, 8.2, 8.3, 8.4_

- [ ] 8. SAST 替代 CodeQL（1 人日）
  - [ ] 8.1 加入 bandit
    - 改动：`pyproject.toml` 的 `[project.optional-dependencies].dev`（≈L53-64）与 `[dependency-groups].dev`（≈L82-93）各追加 `"bandit>=1.9"`；执行 `make relock`，锁文件单独一个提交。
    - 验证：`uv sync && uv run bandit --version && uv lock --check && make compliance-env && UV_PROJECT_ENVIRONMENT=build/compliance-venv uv run --frozen --no-sync python -c "import importlib.util as u; assert u.find_spec('bandit') is None"`
    - _需求：10.2_
  - [ ] 8.2 `make sast` 与基线
    - 改动：`Makefile.intranet` 追加 `sast`、`sast-baseline` 目标与 `help-intranet` 行；执行 `make sast-baseline` 生成 `supply-chain/bandit-baseline.json`，逐条复核：确认是误报的保留（基线实测应只有 `src/octop/infra/backup/system_archive.py::_extract_archive` 的两条 B202，两处已传 `filter=tarfile.data_filter`），真问题交给 owner spec 修复后重新生成；新增 `docs/intranet/supply-chain.md` 并写"SAST 基线"一节逐条说明理由。
    - 验证：`make sast && test -s dist/compliance/sast-bandit.json && rg -n 'B202' docs/intranet/supply-chain.md`
    - 验证：`printf 'import hashlib\n\n\ndef probe(data: bytes) -> str:\n    return hashlib.md5(data).hexdigest()\n' > src/octop/_sast_probe.py; make sast; echo "rc=$?"; rm -f src/octop/_sast_probe.py`（期望 `rc` 非零，输出含 B324）
    - _需求：10.1, 10.3, 10.5_
  - [ ] 8.3 接入 CI 并删除 CodeQL
    - 改动：`.github/workflows/ci.yml` 的 `quality` job 在 `Test` 之后追加 `- name: SAST (bandit)` / `run: make sast`；删除 `.github/workflows/codeql.yml` 与 `.github/codeql/`。若 `w1-04` 的 `tests/unit/test_content_trim_guard.py` 断言了工作流恰为三个文件，同一提交里改为 `anti-spam-issues.yml`、`ci.yml` 两个。
    - 验证：`test ! -e .github/workflows/codeql.yml && test ! -e .github/codeql && rg -n 'make sast' .github/workflows/ci.yml && uv run pytest tests/unit/test_content_trim_guard.py tests/unit/test_ci_gates_contract.py -q`
    - _需求：10.4, 12.1_

- [ ] 9. SCA 漏洞扫描（1.5 人日）
  - [ ] 9.1 离线配置与 `make sca`
    - 改动：新增 `supply-chain/grype.yaml`（`check-for-app-update: false`、`db.auto-update: false`、`db.validate-age: true`、`db.max-allowed-built-age: 720h`、空 `ignore`，头部注释写明漏洞库导入方式）；先在 `tests/unit/test_supply_chain.py` 加 `test_grype_ignore_rules_require_comment` 并确认失败，再实现 `check_grype_ignores` 与 `sca-ignore-check` 子命令（规则前一行注释须同时含"理由"、"审批"、"到期"与 `YYYY-MM-DD` 日期）；`Makefile.intranet` 追加 `sca` 目标与 `help-intranet` 行。
    - 验证：`uv run pytest tests/unit/test_supply_chain.py -q -k grype && make sca GRYPE=/nonexistent/grype; echo "rc=$?"`（期望 `rc=2`）
    - 验证（有 grype、无漏洞库的机器上）：`mkdir -p build/empty-grype-db && GRYPE_DB_CACHE_DIR=build/empty-grype-db make sca; echo "rc=$?"`（期望非零，stderr 中没有 `toolbox-data.anchore.io`）
    - _需求：9.1, 9.2, 9.3, 9.4_
  - [ ] 9.2 行内环境首次分诊
    - 改动：在行方提供的工具镜像上用 `grype db import <离线漏洞库归档>` 导入漏洞库，执行 `make sbom` 与 `make sca`；把全部 high 及以上结果写进 `docs/intranet/supply-chain.md` 的"SCA 分诊"表（组件、版本、漏洞编号、处置、owner spec、到期日）；需要忽略的写进 `supply-chain/grype.yaml` 并带注释。核实行方 grype 版本支持设计文档用到的参数与 `sbom:` 读取 CycloneDX；不支持时改用 `purl:` 输入并记录。
    - 验证：`GRYPE_DB_CACHE_DIR=<漏洞库目录> make sca && test -s dist/compliance/sca-python.json && test -s dist/compliance/sca-npm.json && rg -n 'SCA 分诊' docs/intranet/supply-chain.md`
    - _需求：9.1, 9.5_

- [ ] 10. 制品签名（0.75 人日）
  - 改动：先在 `tests/unit/test_supply_chain.py` 加 `test_checksums_*`（设计文档"测试策略"第 13 条）并确认失败；再实现 `write_checksums`、`verify_checksums` 与 `checksums` 子命令；`Makefile.intranet` 追加 `sign`、`verify-signature`、`supply-chain` 目标与 `help-intranet` 行；`docs/intranet/supply-chain.md` 写"签名与密钥托管"一节（私钥只以流水线文件型密文传入，公钥随交付文档分发，D8 国密由 `p2-02` 替换）。
  - 验证：`uv run pytest tests/unit/test_supply_chain.py -q -k checksums && make sign; echo "rc=$?"`（期望 `rc=2`，提示需要 `SIGNING_KEY`）
  - 验证：`openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out build/test-sign.pem && openssl pkey -in build/test-sign.pem -pubout -out build/test-sign.pub && make sign SIGNING_KEY=build/test-sign.pem && make verify-signature SIGNING_PUBKEY=build/test-sign.pub`
  - 验证：`echo tampered >> dist/compliance/licenses-python.json; make verify-signature SIGNING_PUBKEY=build/test-sign.pub; echo "rc=$?"`（期望 `rc` 非零；测试密钥在已忽略的 `build/` 下，不提交）
  - _需求：11.1, 11.2, 11.3_

- [ ] 11. CI 接线、参考流水线与契约测试（1 人日）
  - [ ] 11.1 先写契约测试
    - 改动：新增 `tests/unit/test_supply_chain_contract.py`，用例见设计文档"契约测试"一节：三个 CI job 的步骤；`codeql` 已删；`Makefile.intranet` 定义全部供应链目标且 `help-intranet` 列出九个目标；参考流水线调用全部契约目标、`build` 阶段先于 `sbom`/`sca`/`sign` 所在阶段、无明文凭据；`grype.yaml` 离线；仓库无私钥；`NOTICE` 覆盖策略中的报备包；`scripts/intranet` 通过 `ruff check` 与 `ruff format --check`。
    - 验证：`uv run pytest tests/unit/test_supply_chain_contract.py -q`（此时应失败：CI 步骤与参考流水线尚不存在）
    - _需求：12.3, 12.4, 9.3, 10.4, 11.4_
  - [ ] 11.2 接线与参考流水线
    - 改动：`.github/workflows/ci.yml`：`quality` 与 `test-windows` 在 `Test` 之后追加 `- name: License check (Python)` / `run: make license-check-python`；`frontend` job 在 `Frontend checks` 之后追加 `- name: License check (npm)` / `run: make license-check-npm`；其余 job 不改。新增 `supply-chain/pipeline.reference.yml`（GitLab CI 语法，阶段 `verify → build → compliance → sign`，内容见设计文档），凭据只写成 `$PG_TEST_DSN`、`$SIGNING_KEY_FILE`、`$PYPI_MIRROR`、`$NPM_MIRROR` 这类变量引用。
    - 验证：`uv run pytest tests/unit/test_supply_chain_contract.py tests/unit/test_ci_gates_contract.py -q`
    - 验证：开 PR 后 `Python 3.12`、`Windows / Python 3.12`、`Frontend (tsc / eslint / prettier / vitest)` 三个检查均为绿，日志中分别出现 `licenses-python.json`、`sast-bandit.json`、`licenses-npm.json` 的写出记录。
    - _需求：12.1, 12.2, 12.3_

- [ ] 12. 收尾（0.75 人日）
  - 改动：补全 `docs/intranet/supply-chain.md`：九个目标与变量、离线前置条件（uv、行内索引、grype 二进制与漏洞库导入、openssl）、`LICENSE_EXTRAS` 与离线包 extra 对齐的要求、门禁失败时的处理流程。
  - 改动：`docs/intranet/upstream-sync.md`：第 8 节"验证命令"追加 `make license-check`；第 7 节"同步后核对"追加"`ci.yml` 中 `license-check-python`、`license-check-npm`、`sast` 三类步骤与 `supply-chain/` 目录仍在（契约测试会拦截）"。
  - 改动：`CHANGELOG-intranet.md` 的 `## [Unreleased]` 下：“移除”记 `w2-02-supply-chain-compliance`：`office-automation` 的四个专有技能、`pymupdf`、`codeql.yml`；“新增”记九个 Makefile 目标、`NOTICE`、两份文档与参考流水线；“变更”记 PDF OCR 改为抽取页内图片；附本地复现命令 `make license-check && make sast && make sbom`。
  - 改动：`AGENTS.md` §9 表格追加一行：`Supply chain / license gate | Makefile.intranet (license-check, sbom, sca, sast, sign), supply-chain/, docs/intranet/supply-chain.md, NOTICE`。
  - 改动：本 spec 不改 API，`docs/api-intranet.md` 不更新；不改 `dashboard/` 源码，不需要 `npx tsc -b`、`npm run lint` 与 vitest。
  - 验证：`rg -n 'make license-check' docs/intranet/upstream-sync.md && rg -n 'w2-02-supply-chain-compliance' CHANGELOG-intranet.md && rg -n 'supply-chain' AGENTS.md`
  - 验证：`for t in license-check-python license-check-npm license-check sbom sca sast verify-signature sign supply-chain; do make help-intranet | rg -q -F -e "$t" || echo "missing $t"; done`（期望无输出）
  - 验证：`make install-frontend && make all && make license-check && make sast && make sbom`
  - 验证：`git diff --exit-code "$W202_BASE" -- src/octop/i18n dashboard/src LICENSE`
  - _需求：12.4, 12.5, 1.5_
