# 需求文档：SSRF 守卫内网白名单

> spec：`w0-05-ssrf-intranet-allowlist` ｜ 波次：Wave 0 ｜ 基线：`757fd12` ｜ 预估：3 人日
> 前置：无 ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 引言

**结论：** 本 spec 给 `src/octop/infra/utils/ssrf_guard.py` 加一份可配置的内网白名单，由三项配置组成：网段列表 `intranet_allow_cidrs`、主机名后缀列表 `intranet_allow_host_suffixes`、独立的明文开关 `intranet_allow_http`。放行逻辑落在守卫内部的四个放行点：最底层的 `_parse_https_host`，以及 `_check_ip_not_private`、`validate_https_url`、`_resolve_validated_ip`。因此 5 个消费模块的 15 个调用点不用逐个改，自动获得白名单语义；唯一需要改的消费方是 `custom_mcp.validate_mcp_http_url`，因为它在调用守卫之前自己拦了一次 http。白名单比对基于解析后的 IP，主机名还必须同时命中后缀，用来防 DNS 重绑定。配置走 `config.py` 三触点，由 `OctopServer` 与 CLI 离线路径 `open_cli_services` 注入 setter。三项都取默认值时，守卫行为与基线逐字节相同。

### 背景

- `ssrf_guard.py` 的 `_parse_https_host`（基线 ≈L20-27）第一句就是 `if parsed.scheme != "https": raise UnsafeOutboundUrl("only https URLs are allowed")`；`validate_https_url`、`_resolve_validated_ip`、`safe_request` 都先调用它。`_check_ip_not_private`（≈L30-39）无条件拒绝私网、环回、链路本地、保留与组播地址。结果是行内 10.x / 172.16.x 地址与 http 服务一律被拒。
- 源分析 S10 只列了三处放行点，漏了 `_parse_https_host`。照那份清单实施，会出现"网段配好了，但 http 内网连接器探测仍然 100% 失败"的假完成（S21 refuted_claims[8]、corrections[8]，`shared.txt` 第 11 节）。
- `infra/utils/` 按 AGENTS.md §5 不得 import `octop.config`。基线上 `rg -n "octop\.config" src/octop/infra/utils` 只命中 `json_file.py` 的一行注释，所以白名单只能靠注入。不接线的话，`config.py` 里的键就是死开关（S21 refuted_claims[9]）。
- 已核实的消费方共 5 个模块、15 个守卫调用点：`infra/voice/adapters.py` 2 处，`infra/connectors/oauth/discovery.py` 4 处，`infra/connectors/oauth/mcp.py` 6 处（另有 1 处 `host_allowed_for_issuer` 纯字符串判断），`infra/connectors/custom_mcp.py` 1 处，`infra/connectors/probe.py` 2 处。横向分析 `shared.txt` 写的是"13 个"，但它列出的行号本身就是 15 个。

### 为什么做

这是"接行内系统"类能力共同的地基。`w1-05` 保留的 WeKnora、Dify、自定义 MCP 三个样板连接器，以及 OpenAI 兼容语音，指向行内地址时全部被守卫拒绝；`p2-06` 的行内 OA / 知识库 / 工单连接器也一样。它在源分析里同时被 S05、S10、S21 三个 spec 声明，处于无主状态，所以全局约束第 3 节把它单独归给本 spec，放在 Wave 0。

### 范围内

1. 新模块 `src/octop/infra/utils/intranet_allowlist.py`：白名单数据模型、解析与校验、硬拒集、进程级 setter 与 getter。
2. `ssrf_guard.py` 的四个放行点，外加一个供消费方使用的公开判断函数 `intranet_http_allowed`。
3. `custom_mcp.validate_mcp_http_url` 中 http 前置拦截的放宽。
4. `config.py` 三个新键的三触点，以及文件值的类型校验。
5. 注入接线：`OctopServer.start()`、`OctopServer.bind_control_plane()`、`cli/support/db.py::open_cli_services()`。
6. 默认行为快照、放行与拒绝的双向单测、消费方回归、注入集成测试。
7. 部署文档 `docs/intranet/ssrf-intranet-allowlist.md`，以及 `CHANGELOG-intranet.md` 条目。

### 范围外（归属）

- 在线维护白名单的管理端点（S10 提出的 `GET/PUT /admin/security/egress-allowlist`）：不做。白名单是部署级配置，只能改 `config.json` 或 env 后重启，应用管理员无法在线放宽。是否需要在线维护列为待确认项。
- `issuer_base_domain` / `host_allowed_for_issuer` 的"取末两段域名"过宽问题：不改，因为改动会改变默认行为。本 spec 在设计文档里登记为风险。
- `probe_streamable_http_mcp` 建连前没有解析期校验，harness 运行期的 MCP 连接也不经过守卫：这是基线就有的缺口，建议由 `w3-06` 在收敛自定义 MCP 时补上。
- 基线守卫不拒绝 `100.64.0.0/10`（含阿里云元数据地址 `100.100.100.200`）：本 spec 受"默认行为不变"约束不修，登记为待确认项。
- 无 DNS 时 `cannot resolve hostname` 映射为 4xx 的断网冒烟：归 `w1-05`。
- 进程级 CA 与出站代理：归 `w2-04`。
- 删除 `_guard_mimo_base_url` 等在线语音代码：归 `w1-05`。本 spec 不改 `voice/adapters.py`。
- 模型供应商 `base_url`、知识库检索等不经过 `ssrf_guard` 的出网路径：本 spec 不给它们加守卫。
- 审计留痕：白名单变更不进 `audit_log`，统一审计归 `w3-02`。
- 前端、API 路由、`ErrorCode`、权限键、i18n 键、数据库迁移：本 spec 一概不涉及。

## 需求

### 需求 1：默认配置下行为逐字节不变

**用户故事：** 作为 fork 维护者，我希望在不配置白名单时 SSRF 守卫与上游完全一致，以便合入本 spec 不改变任何现有部署的安全边界，也不影响上游同步。

#### 验收标准

1. 当 `intranet_allow_cidrs`、`intranet_allow_host_suffixes`、`intranet_allow_http` 都取默认值时，`validate_https_url`、`validate_https_url_resolved`、`safe_request`、`custom_mcp.validate_mcp_http_url` 对基线快照语料中的每一条输入，返回值、异常类型与异常消息都应当与基线 `757fd12` 完全相同；`tests/unit/utils/test_ssrf_guard_baseline.py` 在实现前后都应当通过。
2. 在白名单为空期间，以下既有用例应当不加修改地通过：`tests/unit/test_connectors.py::test_weknora_rejects_non_https_remote_url`（≈L202-212，含 `non-local url must use https` 与 `query string or fragment` 两条断言）、`tests/unit/connectors/test_custom_mcp.py::test_rejects_http_scheme_and_private_host`（≈L127）与 `::test_allows_loopback_http_and_https`（≈L140）、`tests/unit/utils/test_ssrf_guard.py` 与 `tests/unit/connectors/test_mcp_oauth_ssrf.py` 的全部用例。
3. 本 spec 应当始终不修改上一条列出的 4 个既有测试文件：`git diff --exit-code w0-05-base -- tests/unit/test_connectors.py tests/unit/connectors/test_custom_mcp.py tests/unit/utils/test_ssrf_guard.py tests/unit/connectors/test_mcp_oauth_ssrf.py` 的退出码为 0（`w0-05-base` 是任务 1 打的本地标签）。
4. 白名单应当始终只放宽、不收紧：快照语料中基线放行的每一条输入，在任意合法的非空白名单配置下仍然放行，并且返回值相同。

### 需求 2：网段白名单按 IP 放行，硬拒集不可放行

**用户故事：** 作为行内部署运维，我希望把行内网段登记进白名单，让指向这些网段的连接器与语音网关可以使用，同时保证云元数据、环回等地址无论怎么配置都拒绝。

#### 验收标准

1. 当配置 `intranet_allow_cidrs=["10.0.0.0/8"]` 时，`validate_https_url("https://10.20.30.40/mcp")` 与 `validate_mcp_http_url("https://10.20.30.40/mcp")` 应当返回原 URL。
2. 如果 IP 字面量不在任何已配置网段内（例如在上述配置下的 `https://172.16.0.5/`），那么 `validate_https_url` 应当仍然抛出 `UnsafeOutboundUrl("private or reserved IP addresses are not allowed")`。
3. `ssrf_guard` 应当始终拒绝硬拒集，与白名单配置无关。硬拒集包括：链路本地地址（`169.254.0.0/16`，含云元数据 `169.254.169.254`；`fe80::/10`）、环回地址（`127.0.0.0/8`、`::1`）与字面量 `localhost`、组播、未指定地址、保留地址（`240.0.0.0/4`），也包括这些地址的 IPv4 映射 IPv6 写法（如 `https://[::ffff:169.254.169.254]/`）。
4. 当地址是 IPv4 映射 IPv6、且其 IPv4 部分落在已配置网段内时（如 `10.0.0.0/8` 下的 `https://[::ffff:10.1.2.3]/`），`validate_https_url` 应当放行。

### 需求 3：主机名后缀与防 DNS 重绑定

**用户故事：** 作为安全负责人，我希望主机名只有在属于行内域、并且解析结果全部落在白名单网段内时才被放行，连接还要钉在校验过的 IP 上，以便外部域名无法通过 DNS 重绑定打进行内网段。

#### 验收标准

1. 当配置网段 `10.0.0.0/8` 与后缀 `bank.intra`、且 `oa.bank.intra` 解析为 `10.1.2.3` 时，`validate_https_url_resolved("https://oa.bank.intra/x")` 应当返回原 URL，`safe_request` 应当以 `PinnedIPTransport("oa.bank.intra", "10.1.2.3")` 建连。
2. 如果命中后缀的主机名的解析结果中，有任意一个地址不在已配置网段内或属于硬拒集（如 `[10.1.2.3, 169.254.169.254]`、`127.0.0.1`、`172.16.0.5`），那么 `validate_https_url_resolved` 与 `safe_request` 应当抛出 `UnsafeOutboundUrl("private or reserved IP addresses are not allowed")`，且不发出任何请求。
3. 如果主机名不命中任何后缀（如 `evil.example.com`），那么即使它解析到已配置网段内的地址，也应当抛出 `UnsafeOutboundUrl("private or reserved IP addresses are not allowed")`。
4. 后缀匹配应当始终按 DNS 标签边界进行：`bank.intra` 匹配 `bank.intra` 与 `a.b.bank.intra`，不匹配 `evilbank.intra` 与 `bank.intra.evil.com`。
5. 当白名单主机返回 3xx 响应时，`safe_request` 应当原样返回该响应，不向 `Location` 发出第二个请求。

### 需求 4：明文 http 独立开关

**用户故事：** 作为行内部署运维，我希望是否允许明文 http 是一个独立开关，默认关闭；打开后也只对白名单内的地址生效，以便行内没有证书的老系统可以接入，又不会顺带放开到公网的明文请求。

#### 验收标准

1. 在 `intranet_allow_http=false`（默认）期间，即使主机命中白名单，`validate_https_url("http://10.20.30.40:8080/")` 也应当抛出 `UnsafeOutboundUrl("only https URLs are allowed")`，`validate_mcp_http_url("http://10.20.30.40:8080/mcp")` 应当抛出 `ValueError("non-local url must use https")`。
2. 当 `intranet_allow_http=true` 且主机命中白名单时，`validate_https_url` 与 `validate_mcp_http_url` 应当放行 `http://10.20.30.40:8080/mcp`；`safe_request("POST", "http://oa.bank.intra/x")`（`oa.bank.intra` 解析为 `10.1.2.3`）应当以明文连接到被钉住的 `10.1.2.3`，`getaddrinfo` 收到的端口为 80。
3. 如果 `intranet_allow_http=true` 但主机不命中白名单（如 `http://example.com/`、`http://172.16.0.5/`），那么 `validate_https_url` 应当仍然抛出 `only https URLs are allowed`，`validate_mcp_http_url` 应当仍然抛出 `non-local url must use https`。
4. 如果明文 URL 的主机名命中后缀，但解析出任意一个不在已配置网段内的地址（包括公网地址 `1.2.3.4`），那么 `validate_https_url_resolved` 与 `safe_request` 应当抛出 `UnsafeOutboundUrl("only https URLs are allowed")`。

### 需求 5：配置三触点与校验

**用户故事：** 作为部署运维，我希望通过 `config.json` 或环境变量配置白名单，配错时服务直接报错并指出错在哪一项，以便不会出现"配了但没生效"或"配得过宽却不自知"。

#### 验收标准

1. 当 `config.json` 写入 `intranet_allow_cidrs`、`intranet_allow_host_suffixes`、`intranet_allow_http` 时，`load_config` 返回的 `OctopConfig` 对应字段应当等于写入值。
2. 当设置 `OCTOP_INTRANET_ALLOW_CIDRS`（逗号分隔）、`OCTOP_INTRANET_ALLOW_HOST_SUFFIXES`（逗号分隔）、`OCTOP_INTRANET_ALLOW_HTTP` 时，环境变量的值应当覆盖文件中的值。
3. 当 `config.json` 不存在时，`load_config` 首次写出的默认文件应当包含这三个键，取值依次为 `[]`、`[]`、`false`。
4. 如果 `config.json` 中两个列表键的值不是字符串数组，或 `intranet_allow_http` 不是 JSON 布尔值，那么 `load_config` 应当抛出 `ValueError`，消息包含出错的键名，并且不回显文件的其他内容。
5. 如果出现以下任一情况，`configure_intranet_allowlist` 应当抛出 `ValueError`，消息指出配置键与出错条目，并且当前生效的白名单保持不变：网段语法非法或主机位非零；网段与硬拒集或 IPv4 映射段 `::ffff:0:0/96` 相交（如 `0.0.0.0/0`、`127.0.0.0/8`、`169.254.0.0/16`、`::/0`）；后缀为空、含 `*`、`/`、`:` 或空白、是 IP 字面量、是 `localhost` 或以 `.localhost` 结尾、少于两段；配置了后缀或打开了 http 开关，却没有配置任何网段。

### 需求 6：注入接线

**用户故事：** 作为 fork 维护者，我希望白名单在服务启动与 CLI 离线路径上都从配置注入，并且遵守 `infra/utils` 不读配置的边界，以便开关在所有入口上都真实生效。

#### 验收标准

1. 当 `OctopServer.start()` 或 `OctopServer.bind_control_plane()` 执行时，`current_intranet_allowlist()` 应当等于由 `config.json` 与环境变量合成的白名单。
2. 当以默认配置启动 `OctopServer` 时，`current_intranet_allowlist().is_empty` 应当为真，即使同一进程先前注入过非空白名单。
3. 如果白名单配置非法，那么 `OctopServer.start()` 应当在打开控制面数据库之前抛出 `ValueError` 并中止启动，不得以空白名单或部分白名单继续运行。
4. 当白名单非空时，服务启动日志应当包含一条 INFO 记录，列出生效的网段、后缀与 http 开关。
5. 当 CLI 离线路径 `open_cli_services()` 打开服务时，`current_intranet_allowlist()` 应当同样等于配置值。
6. 当以 `intranet_allow_cidrs=["10.0.0.0/8"]` 加 `intranet_allow_http=true` 启动时，管理员调用 `PUT /api/connectors/custom-mcp` 保存 `http://10.20.30.40:8080/mcp` 应当返回 200；以默认配置启动时，同一请求应当返回 400，且 `error.code` 为 `CONNECTOR_INVALID_CREDENTIALS`。
7. `src/octop/infra/utils/` 下的模块应当始终不 import `octop.config`，也不 import `octop.infra.utils` 以外的 `octop.infra` 包。

### 需求 7：消费方全覆盖

**用户故事：** 作为安全评审人，我希望白名单对全部出站消费方的效果是确定且可测的，特别是语音网关这条容易被漏掉的路径，以便评审材料可以逐条列出放行面。

#### 验收标准

1. 5 个消费模块的 15 个调用点应当始终通过 `ssrf_guard` 的四个放行点获得白名单语义：除 `custom_mcp.py` 外，`src/octop/infra/voice/adapters.py`、`src/octop/infra/connectors/oauth/discovery.py`、`src/octop/infra/connectors/oauth/mcp.py`、`src/octop/infra/connectors/probe.py` 相对 `w0-05-base` 应当没有 diff。
2. 当配置网段 `10.0.0.0/8` 且打开 http 开关时，`voice.adapters._guard_voice_base_url("http://10.1.2.3:8000/v1")` 应当通过；关闭 http 开关时应当抛出 `only https URLs are allowed`；对 `https://169.254.169.254` 应当始终抛出异常。
3. 当配置网段 `10.0.0.0/8` 与后缀 `bank.intra`、且 `sso.bank.intra` 解析为 `10.2.3.4` 时，`oauth.mcp._ensure_mcp_oauth_url("https://sso.bank.intra/token", issuer="https://sso.bank.intra", field="token_endpoint")` 应当返回原 URL；默认配置下应当抛出 `ValueError`，消息含 `private or reserved`。
4. 当配置网段 `10.0.0.0/8` 且打开 http 开关时，间接消费方 `builder.normalize_weknora_base_url("http://10.20.30.40:8080")` 应当返回 `http://10.20.30.40:8080/api/v1`。

### 需求 8：文档与收尾

**用户故事：** 作为行内部署运维，我希望有一份说明白名单语义、配置方法与排障方式的文档，并在 fork 变更记录里可查，以便上线与等保评审时有据可依。

#### 验收标准

1. 仓库应当新增 `docs/intranet/ssrf-intranet-allowlist.md`，覆盖：三个配置键与对应环境变量、两因子放行语义、硬拒集、http 开关、15 个消费调用点清单、配置示例、fail-fast 行为、"能存不能测"的排障说明、已知缺口。
2. `CHANGELOG-intranet.md` 应当新增一条以 `w0-05-ssrf-intranet-allowlist` 开头的"安全"条目。
3. `make all` 应当全绿；`git diff --name-only w0-05-base -- dashboard src/octop/i18n src/octop/infra/errors.py src/octop/infra/db/migrations src/octop/api` 应当无输出。
