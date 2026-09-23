# 设计文档：SSRF 守卫内网白名单

> spec：`w0-05-ssrf-intranet-allowlist` ｜ 波次：Wave 0 ｜ 基线：`757fd12` ｜ 预估：3 人日
> 前置：无 ｜ 全局约束：`.kiro/steering/intranet-transformation.md`

## 概述

**结论：** 新增纯 utils 模块 `src/octop/infra/utils/intranet_allowlist.py`，负责白名单的数据模型、校验、硬拒集和进程级 setter / getter。`ssrf_guard.py` 只在四个放行点各加几行调用，全部是"基线判定为拒绝时，再查白名单能否放行"的形式：

- `_parse_https_host`：对白名单内主机允许 `http`，受独立开关控制；
- `_check_ip_not_private`：对白名单网段内的地址放行，硬拒集除外；
- `validate_https_url`：函数体不变，通过前两者对 IP 字面量与 http 生效；
- `_resolve_validated_ip`：主机名必须命中后缀，并且每一个解析结果都落在网段内，才放行。

另外新增公开函数 `intranet_http_allowed(url)`，供 `custom_mcp.validate_mcp_http_url` 放宽它自己的 http 前置拦截。

配置走 `config.py` 三触点，新增三个键：`intranet_allow_cidrs`、`intranet_allow_host_suffixes`、`intranet_allow_http`。注入点有三处：`OctopServer.start()`、`OctopServer.bind_control_plane()`、`cli/support/db.py::open_cli_services()`。配置非法时 fail-fast。

白名单为空时，所有新分支都在求值任何新表达式之前短路，默认行为与基线逐字节相同，由一份基线快照测试守护。除 `custom_mcp.py` 外，四个消费模块零改动。本 spec 不新增路由、`ErrorCode`、权限键、i18n 键和迁移，也不改前端。

## 现状

以下事实均在基线 `757fd12` 上亲自核实。

### 守卫本体：`src/octop/infra/utils/ssrf_guard.py`

- `UnsafeOutboundUrl(ValueError)`（≈L16）是守卫唯一的异常类型。
- `_parse_https_host`（≈L20-27）先 `urlparse`，`if parsed.scheme != "https": raise UnsafeOutboundUrl("only https URLs are allowed")`（≈L22-23）；主机名为空时抛 `missing hostname`；返回 `(host.lower().rstrip("."), parsed.port)`。它是 `validate_https_url`（≈L73）、`_resolve_validated_ip`（≈L94）与 `safe_request`（≈L181）的共同第一步。
- `_check_ip_not_private`（≈L30-39）对 `is_private or is_loopback or is_link_local or is_reserved or is_multicast` 一律抛 `private or reserved IP addresses are not allowed`。`_check_ip_literal`（≈L42-47）只在 host 是 IP 字面量时调用它；`_check_resolved_ip`（≈L50-51）是它的别名。
- `validate_https_url`（≈L71-77）：解析 → `host == "localhost"` 时抛 `f"{field}: localhost is not allowed"`（≈L74-75）→ `_check_ip_literal`。**不做 DNS 解析**，所以"内部主机名 + https"能通过这一步（S05 refuted_claims[5] 所说的"能存不能测"）。
- `validate_https_url_resolved`（≈L80-84）= `validate_https_url` + `_resolve_validated_ip`。
- `_resolve_validated_ip`（≈L87-109）：`loop.getaddrinfo(host, port or 443, …)`（≈L97-102）；`socket.gaierror` 或空结果时抛 `cannot resolve hostname {host!r}`（≈L103-106）；对**每一个**解析结果调 `_check_resolved_ip`（≈L107-108）；返回第一个地址。
- `_PinnedNetworkBackend`（≈L112）与 `PinnedIPTransport`（≈L152）把目标主机的 TCP 连接钉到校验过的 IP，SNI 仍用原主机名。`PinnedIPTransport.__init__` 调用无参的 `httpx.AsyncHTTPTransport()`；httpx 0.28.1 的默认值是 `trust_env=True`，因此 `SSL_CERT_FILE` / `SSL_CERT_DIR` 生效。
- `safe_request`（≈L165-185）：`_parse_https_host` → `_resolve_validated_ip` → `httpx.AsyncClient(transport=PinnedIPTransport(...))`（≈L181-185）。显式传入 `transport` 时，httpx 的 `allow_env_proxies = trust_env and transport is None` 为假，所以**不读取 `HTTPS_PROXY`**。`AsyncClient` 的 `follow_redirects` 默认为 `False`。
- `issuer_base_domain`（≈L54）与 `host_allowed_for_issuer`（≈L62）用"取末两段"判断同域。这对 `*.com.cn` 这类多段公共后缀过宽（`auth.a.com.cn` 的 base 是 `com.cn`）。本 spec 不改它。
- 模块只 import 标准库、`httpx`、`httpcore`，不 import 任何 `octop.*`。

### 基线行为实测（快照语料的来源）

用基线代码逐条执行，`validate_https_url(url, field="f")` 与 `validate_mcp_http_url(url)` 的结果如下：

| 输入 | `validate_https_url` | `validate_mcp_http_url` |
|---|---|---|
| `http://mcp.notion.com/token` | `UnsafeOutboundUrl: only https URLs are allowed` | `ValueError: non-local url must use https` |
| `https://127.0.0.1/token` | `…: private or reserved IP addresses are not allowed` | 放行（loopback 分支） |
| `https://10.0.0.1/token` | `…: private or reserved …` | `ValueError: private or reserved …` |
| `https://localhost/token` | `UnsafeOutboundUrl: f: localhost is not allowed` | 放行（loopback 分支） |
| `https://169.254.169.254/latest/meta-data` | `…: private or reserved …` | `ValueError: private or reserved …` |
| `https://[::1]/x` | `…: private or reserved …` | 放行 |
| `https://[::ffff:10.0.0.1]/x` | `…: private or reserved …` | `ValueError: private or reserved …` |
| `https://0.0.0.0/`、`https://224.0.0.1/`、`https://240.0.0.1/`、`https://[fe80::1]/` | `…: private or reserved …` | `ValueError: private or reserved …` |
| `https:///nohost` | `UnsafeOutboundUrl: missing hostname` | `ValueError: url missing hostname` |
| `ftp://example.com/` | `UnsafeOutboundUrl: only https URLs are allowed` | `ValueError: url must be http or https` |
| `HTTPS://Example.COM./a` | 放行 | 放行 |
| `https://100.100.100.200/latest/meta-data` | **放行** | **放行** |
| `http://10.20.30.40:8080/mcp` | `…: only https URLs are allowed` | `ValueError: non-local url must use https` |
| `https://10.20.30.40/mcp` | `…: private or reserved …` | `ValueError: private or reserved …` |
| `https://example.com:abc/` | `ValueError: Port could not be cast to integer value as 'abc'`（不是 `UnsafeOutboundUrl`） | 同左 |
| `http://localhost:8080/mcp` | `…: only https URLs are allowed` | 放行 |
| `https://oa.bank.intra/x` | 放行（不解析 DNS） | 放行 |

用 `monkeypatch` 替换 `socket.getaddrinfo` 后，`validate_https_url_resolved` 的结果如下：`oa.bank.intra → 10.1.2.3`、`evil.example.com → 10.1.2.3`、`mixed.bank.intra → [10.1.2.3, 169.254.169.254]` 三者都抛 `private or reserved …`；无法解析的主机抛 `cannot resolve hostname 'nodns.bank.intra'`。已确认 `asyncio` 的 `loop.getaddrinfo` 在每次调用时才取 `socket.getaddrinfo`，所以该桩法有效。对 IP 字面量调用 `getaddrinfo` 不需要 DNS（实测 `10.1.2.3` 直接返回自身）。

`https://100.100.100.200`（阿里云元数据地址，位于 `100.64.0.0/10`）被放行，原因是 Python 3.12 的 `ipaddress` 对该段 `is_private`、`is_reserved` 都为假。这是基线已有的缺口，见"风险与回滚"。

### 消费方（5 个模块、15 个守卫调用点）

| 模块 | 调用点 | 调用 | 经过的放行点 |
|---|---|---|---|
| `src/octop/infra/voice/adapters.py` | `_guard_voice_base_url`（≈L89-91，被 L101、L133 调用） | `validate_https_url_resolved(f"{base_url}/v1/audio")` | 四个都经过 |
| 同上 | `_guard_mimo_base_url`（≈L271-273，被 L343、L401 调用；将由 `w1-05` 删除） | `validate_https_url_resolved(base_url)` | 四个都经过 |
| `src/octop/infra/connectors/oauth/discovery.py` | `_fetch_prm_document`（≈L70）：L72、L76 | `validate_https_url` + `safe_request("GET")` | 四个都经过 |
| 同上 | `_probe_401_resource_metadata`（≈L93）：L103、L107 | 同上（`POST`） | 四个都经过；但 ≈L100 自带 `if parsed.scheme != "https": return None`，http 的 MCP 不做 PRM 探测，本 spec 保持不变 |
| `src/octop/infra/connectors/oauth/mcp.py` | `_ensure_mcp_oauth_url`（≈L46-59）：L49、L56（L53 为 `host_allowed_for_issuer`） | `validate_https_url` + `validate_https_url_resolved` | 四个都经过 |
| 同上 | `fetch_authorization_metadata` L74、`register_dynamic_client` L106、`exchange_authorization_code` L176、`refresh_access_token` L216 | `safe_request` | 四个都经过 |
| `src/octop/infra/connectors/custom_mcp.py` | `validate_mcp_http_url`（≈L113-140）：L137 | `validate_https_url(text, field="url")` | 前三个；且 L134-135 自带 `if parsed.scheme != "https": raise ValueError("non-local url must use https")` |
| `src/octop/infra/connectors/probe.py` | `probe_connector`（≈L369）的 raw http 分支：L419、L454 | `safe_request("POST")` | 四个都经过 |

`validate_mcp_http_url` 的间接调用方有：`custom_mcp.normalize_server_spec`（≈L168），`builder.normalize_weknora_base_url`（≈L44-46；它又被 `builder.py` ≈L398 与 `gateway/adapters/weknora.py` ≈L91 调用），`builder.py` ≈L99 与 ≈L418（Dify）。`custom_mcp.py` 的 ≈L130-131 对 `localhost`、`127.0.0.1`、`::1` 直接放行 http 与 https，这一段不经过守卫。

已知不经过守卫的路径（基线缺口，本 spec 不改）：

- `probe.probe_streamable_http_mcp`（≈L329）在 ≈L341 直接 `streamablehttp_client(url)`；`probe_connector` 在 ≈L415 对 OAuth 远程与 streamable_http 类型优先走它；自定义 MCP 探测 `probe_custom_mcp_server`（≈L497）只经过保存时的 `normalize_server_spec`（≈L502）。
- `transcribe_openai`（≈L94）/ `synthesize_openai`（≈L122）在守卫之后用普通 `httpx.AsyncClient` 发请求（≈L109、≈L145），没有钉 IP，存在校验与连接之间的 TOCTOU 窗口。
- 模型供应商相关的路由与 store 不 import `ssrf_guard`（上表即 `rg` 得到的全部引用）。

### 既有守护用例

- `tests/unit/utils/test_ssrf_guard.py`：`test_host_allowed_for_issuer`（≈L28）与 ≈L32-44 的 5 个拒绝参数（`http://`、`127.0.0.1`、`10.0.0.1`、`localhost`、`169.254.169.254`）。
- `tests/unit/connectors/test_mcp_oauth_ssrf.py`：内网 token 端点、外域、被投毒的元数据，以及 `safe_request("POST", "https://127.0.0.1/token")` 抛 `private or reserved`（≈L89-93）。
- `tests/unit/connectors/test_custom_mcp.py`：`test_rejects_http_scheme_and_private_host`（≈L127，匹配 `https` 与 `private|not allowed|blocked`），`test_allows_loopback_http_and_https`（≈L140）。
- `tests/unit/test_connectors.py`：`test_weknora_rejects_non_https_remote_url`（≈L202-212）断言 `non-local url must use https` 与 `query string or fragment`。
- 以上四个文件加上 `tests/unit/connectors/test_oauth_discovery.py`、`tests/unit/test_config.py`，基线实测共 157 个用例全部通过。

### 配置与注入点

- `src/octop/config.py`：`OctopConfig`（≈L125，最后一个字段 `browser_idle_timeout_minutes` 在 ≈L145）；`_defaults_for_file`（≈L152）用 `asdict(OctopConfig())` 生成首次写出的 `config.json`，**不需要改**；`load_config`（≈L412）的 env 覆盖是函数体内联的 `if v := os.environ.get(...)` 串（如 ≈L477 `OCTOP_CORS_ORIGINS`、≈L499 `OCTOP_BROWSER_IDLE_TIMEOUT_MINUTES`）；`return OctopConfig(...)`（≈L592）逐字段构造。`_coerce_bool`（≈L283）是既有的 env 布尔解析。≈L511 与 ≈L523 的 capabilities 重复块归 `w1-02` 修，本 spec 不碰。
- `src/octop/infra/server.py`：`start()`（≈L281）在 ≈L294-295 得到 `config` 并赋给 `self.config`，随后才 `open_database`；`bind_control_plane()`（≈L334）在 ≈L343-344 重新 `load_config`。`_boot_runtime`（≈L362）在 ≈L371 调用 `configure_browser_idle_timeout(...)`，这是"server 把配置注入 utils 层"的现成先例。`infra/db/rebind.py::rebind_control_plane` 只重读 `database` 段用于换库，不重设 `server.config`。
- `src/octop/cli/support/db.py::open_cli_services`（≈L21）在 ≈L25 `load_config`。
- 边界：`rg -n "^\s*(from|import) octop\." src/octop/infra/utils | rg -v "octop\.infra\.utils"` 在基线上无输出。
- 错误映射：`PUT /api/connectors/custom-mcp`（`api/routers/connectors.py` ≈L532）把 `ValueError` 映射为 `CONNECTOR_INVALID_CREDENTIALS`（≈L543-544）；该码在 `infra/errors.py` ≈L52 定义，`_DEFAULT_STATUS` ≈L154 为 400。
- 测试支撑：`tests/support/app.py::write_octop_config`（≈L20）可在启动前写入 `config.json` 覆盖项；`octop_client` 负责启动与停止服务。

## 方案

### 1. 白名单语义

白名单由三部分组成：

| 部分 | 含义 |
|---|---|
| `networks` | 允许的网段。它是**唯一**能让私网、保留地址被放行的依据 |
| `host_suffixes` | 可信的行内域名后缀。它只决定"这个主机名是否有资格使用网段放行"以及"是否可以用 http"，本身不放行任何 IP |
| `allow_http` | 是否允许明文 http。只对白名单主机生效，且解析结果必须全部落在网段内 |

放行规则采用两因子：

- **IP 字面量**：基线会拒绝时，若该地址（IPv4 映射 IPv6 先归一化为 IPv4）不在硬拒集、且落在某个网段内，则放行。
- **主机名（https）**：基线会拒绝某个解析结果时，只有主机名命中后缀、且该地址不在硬拒集、且落在网段内，才放行该结果。**任一**解析结果不满足，整体拒绝。未命中后缀的主机名即使解析到网段内也拒绝，用来防止外部域名通过 DNS 指向行内网段（重绑定）。
- **http**：`allow_http` 为真，且主机是"网段内的 IP 字面量"或"命中后缀的主机名"，才允许进入后续检查；解析结果必须**全部**落在网段内（公网地址也不行），否则抛 `only https URLs are allowed`。
- **硬拒集**：链路本地、环回、组播、未指定、保留（`is_link_local`、`is_loopback`、`is_multicast`、`is_unspecified`、`is_reserved`，先做 IPv4 映射归一化），以及字面量 `localhost`（沿用 `validate_https_url` ≈L74-75，不动）。
- **不变式**：白名单只能把基线的"拒绝"改成"放行"，不会新增任何拒绝。基线放行的输入在任意白名单下仍然放行；空白名单时所有新分支在求值新表达式之前短路。

防重绑定的第二道闸沿用基线：`safe_request` 把连接钉在校验过的 IP 上，不做二次解析；`follow_redirects` 默认关闭，3xx 不会被跟随到白名单外。只调用 `validate_https_url`（不解析 DNS）的保存路径与基线一致，只校验字面量。

### 2. 配置期校验（fail-fast）

`build_intranet_allowlist` 在注入时统一校验，任何一条不满足都抛 `ValueError`，并且不替换当前白名单：

- **网段**：`ipaddress.ip_network(s, strict=True)`，主机位非零视为错误（防手误）；与 `HARD_DENY_NETWORKS` 或 `::ffff:0:0/96` 相交视为错误，这样 `0.0.0.0/0`、`::/0`、`127.0.0.0/8`、`169.254.0.0/16` 都无法配置；去重但保持顺序。
- **后缀**：小写，去掉首尾 `.` 和空白；不能为空；不能含 `*`、`/`、`:` 或空白；不能是 IP 字面量；不能是 `localhost` 或以 `.localhost` 结尾；至少两段，且没有空标签。
- **跨字段**：配置了后缀或打开 `allow_http`，但 `networks` 为空，视为错误。否则会出现"配了却永远不生效"的死配置。
- 错误消息以配置键名开头（`intranet_allow_cidrs: …`、`intranet_allow_host_suffixes: …`、`intranet_allow_http requires intranet_allow_cidrs`），与 `config.py` 既有的英文 `ValueError` 一样面向运维，不是终端用户文案，不进 i18n。

### 3. 四个放行点（伪代码，只列增量）

```python
# ssrf_guard.py
from urllib.parse import ParseResult, urlparse
from octop.infra.utils.intranet_allowlist import IntranetAllowlist, current_intranet_allowlist

def _http_host_permitted(parsed: ParseResult, allow: IntranetAllowlist) -> bool:
    if parsed.scheme != "http" or not allow.allow_http:      # 空白名单在此短路
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    return bool(host) and allow.permits_http_host(host)

def intranet_http_allowed(url: str) -> bool:                 # 新增公开函数
    return _http_host_permitted(urlparse(url), current_intranet_allowlist())

def _parse_https_host(url):                                  # 放行点 1
    parsed = urlparse(url)
    if parsed.scheme != "https" and not _http_host_permitted(parsed, current_intranet_allowlist()):
        raise UnsafeOutboundUrl("only https URLs are allowed")
    ...                                                      # 其余不变

def _check_ip_not_private(ip_str, *, allow: IntranetAllowlist | None = None):   # 放行点 2
    addr = ipaddress.ip_address(ip_str)
    if <基线条件>:
        if allow is not None and allow.permits_ip(addr):
            return
        raise UnsafeOutboundUrl("private or reserved IP addresses are not allowed")

def _check_ip_literal(host):                                 # 放行点 3 的落点（validate_https_url 经由它）
    ...
    _check_ip_not_private(host, allow=current_intranet_allowlist())

def _check_resolved_ip(ip_str, *, allow=None, plaintext=False):
    if plaintext:
        if allow is None or not allow.permits_ip(ipaddress.ip_address(ip_str)):
            raise UnsafeOutboundUrl("only https URLs are allowed")
        return
    _check_ip_not_private(ip_str, allow=allow)

async def _resolve_validated_ip(url):                        # 放行点 4
    host, port = _parse_https_host(url)
    allow = current_intranet_allowlist()
    plaintext = urlparse(url).scheme == "http"               # 只有放行点 1 放过的 http 才能走到这里
    infos = await loop.getaddrinfo(host, port or (80 if plaintext else 443), ...)
    ...                                                      # gaierror / 空结果处理不变
    trusted = allow if allow.host_is_trusted(host) else None
    for info in infos:
        _check_resolved_ip(info[4][0], allow=trusted, plaintext=plaintext)
    return infos[0][4][0]
```

`validate_https_url`、`validate_https_url_resolved`、`safe_request` 的函数体不变，只更新 docstring。它们通过放行点 1 与放行点 2、3 获得 http 与字面量放行，通过放行点 4 获得解析期放行。`_PinnedNetworkBackend` 的 `connect_tcp` 对 http 同样生效（http 只是不做 `start_tls`），不需要改。

**空白名单逐字节不变的论证：**

- 放行点 1：默认 `allow_http=False`，`_http_host_permitted` 在读取 `parsed.hostname` / `parsed.port` 之前就返回 `False`，异常类型、消息与抛出顺序都和基线相同。`https://example.com:abc/` 仍由原位置的 `parsed.port` 抛 `ValueError`。
- 放行点 2、3：`permits_ip` 在 `networks` 为空时恒为假，所以仍抛原消息。
- 放行点 4：`plaintext` 恒为假，端口仍是 `port or 443`；`host_is_trusted` 是纯字符串运算，结果只在 `permits_ip` 为真时才有影响。

### 4. 消费方

- `custom_mcp.validate_mcp_http_url`：≈L134 改为 `if parsed.scheme != "https" and not intranet_http_allowed(text): raise ValueError("non-local url must use https")`，消息不变；import 行（≈L9）加上 `intranet_http_allowed`。loopback 分支（≈L130-131）不动。
- 其余四个模块零改动，由需求 7.1 的 diff 检查守护。

### 5. 注入

- `OctopServer` 新增私有方法 `_apply_intranet_allowlist(config)`，在 `start()` ≈L295 与 `bind_control_plane()` ≈L344 两处 `self.config = config` 之后各调一次。两处都在 `open_database` 之前，配置非法时不会留下打开的连接池。延迟控制面（首装向导）模式也会注入。白名单非空时打一条 INFO 日志。
- 默认配置同样调用 setter，于是每次启动都会把白名单重置为配置值，不会残留同进程前一次注入的值（需求 6.2）。
- `rebind_control_plane` 不重读白名单：向导只写 `database` 段，白名单键不变；改白名单须重启，这与 AGENTS.md "config 写入在重启后生效"的约定一致。
- CLI 离线：`open_cli_services` 在 `load_config` 之后调用同一个 setter。今天没有离线 CLI 命令触达守卫消费方，这里接线是为了遵守全局约束第 2 节，防止将来新增命令时成为死开关。内嵌命令（`cli/support/embedded_ops.py`）经 `OctopServer.start()` 自动覆盖。

## 组件与接口

| 文件 | 类型 | 改动 |
|---|---|---|
| `src/octop/infra/utils/intranet_allowlist.py` | 新增 | 白名单模型、校验、硬拒集、setter / getter；只依赖标准库 |
| `src/octop/infra/utils/ssrf_guard.py` | 修改 | 四个放行点 + `_http_host_permitted` + `intranet_http_allowed`；docstring |
| `src/octop/infra/connectors/custom_mcp.py` | 修改 | ≈L9 import，≈L134 条件 |
| `src/octop/config.py` | 修改 | 三触点 + `_parse_str_list` / `_parse_json_bool` / `_split_env_list` 三个私有 helper |
| `src/octop/infra/server.py` | 修改 | `_apply_intranet_allowlist` + 两处单行调用 |
| `src/octop/cli/support/db.py` | 修改 | import + `open_cli_services` 内一处调用 |
| `tests/support/outbound.py` | 新增 | 测试辅助：`fake_getaddrinfo(monkeypatch, table)` 与 `record_pinned_transport(monkeypatch, handler)`（不依赖新模块，基线上即可用）；`use_intranet_allowlist(**kw)` 上下文管理器（退出时重置为空，新模块落地后追加） |
| `tests/unit/utils/test_ssrf_guard_baseline.py` | 新增 | 默认行为快照 |
| `tests/unit/utils/test_intranet_allowlist.py` | 新增 | 模型与校验 |
| `tests/unit/utils/test_ssrf_guard_intranet.py` | 新增 | 放行点、防重绑定、http 开关、钉 IP、重定向、只放宽不变式 |
| `tests/unit/connectors/test_ssrf_intranet_consumers.py` | 新增 | custom_mcp、weknora、OAuth、语音 |
| `tests/unit/test_config_intranet_allowlist.py` | 新增 | 三触点与类型校验 |
| `tests/unit/cli/test_open_cli_services_intranet_allowlist.py` | 新增 | CLI 离线注入 |
| `tests/integration/test_ssrf_intranet_allowlist.py` | 新增 | 服务启动注入、fail-fast、INFO 日志、API 端到端 |
| `docs/intranet/ssrf-intranet-allowlist.md` | 新增 | 部署文档 |
| `CHANGELOG-intranet.md` | 修改 | 追加条目（文件由 `w0-04` 建立） |

### `src/octop/infra/utils/intranet_allowlist.py`（新增）

```python
IPNetwork: TypeAlias = ipaddress.IPv4Network | ipaddress.IPv6Network
IPAddress: TypeAlias = ipaddress.IPv4Address | ipaddress.IPv6Address

HARD_DENY_NETWORKS: tuple[IPNetwork, ...]
# 0.0.0.0/8, 127.0.0.0/8, 169.254.0.0/16, 224.0.0.0/4, 240.0.0.0/4,
# ::/128, ::1/128, fe80::/10, ff00::/8。配置期另拒 ::ffff:0:0/96

def normalize_ip(addr: IPAddress) -> IPAddress: ...          # IPv4 映射 IPv6 → IPv4
def is_hard_denied(addr: IPAddress) -> bool: ...             # 归一化后判 loopback/link_local/multicast/unspecified/reserved

@dataclass(frozen=True)
class IntranetAllowlist:
    networks: tuple[IPNetwork, ...] = ()
    host_suffixes: tuple[str, ...] = ()
    allow_http: bool = False

    @property
    def is_empty(self) -> bool: ...                          # not self.networks
    def permits_ip(self, addr: IPAddress) -> bool: ...       # 非硬拒 且 落在某个网段内
    def host_is_trusted(self, host: str) -> bool: ...        # IP 字面量 → True；主机名 → 按标签边界匹配后缀
    def permits_http_host(self, host: str) -> bool: ...      # allow_http 且（字面量 → permits_ip；主机名 → 后缀匹配）

def build_intranet_allowlist(
    *, cidrs: Iterable[str], host_suffixes: Iterable[str], allow_http: bool
) -> IntranetAllowlist: ...                                  # 校验失败抛 ValueError

def configure_intranet_allowlist(
    *, cidrs: Iterable[str] = (), host_suffixes: Iterable[str] = (), allow_http: bool = False
) -> IntranetAllowlist: ...                                  # 先 build，成功后原子替换模块级 _current；无参调用 = 重置为空

def current_intranet_allowlist() -> IntranetAllowlist: ...
```

模块级状态是一个不可变对象的引用。替换是一次赋值，读取方在单次调用内只读一次快照（`_resolve_validated_ip` 显式持有 `allow`）。setter 只在启动期调用。

### `src/octop/infra/utils/ssrf_guard.py`（修改）

```python
def intranet_http_allowed(url: str) -> bool: ...                                   # 新增公开函数
def _http_host_permitted(parsed: ParseResult, allow: IntranetAllowlist) -> bool: ... # 新增私有函数
def _check_ip_not_private(ip_str: str, *, allow: IntranetAllowlist | None = None) -> None: ...
def _check_resolved_ip(ip_str: str, *, allow: IntranetAllowlist | None = None, plaintext: bool = False) -> None: ...
```

新增参数都是仅限关键字并带默认值，未知的外部调用方保持基线行为。

### `src/octop/infra/server.py`（修改）

```python
def _apply_intranet_allowlist(self, config: OctopConfig) -> None:
    allowlist = configure_intranet_allowlist(
        cidrs=config.intranet_allow_cidrs,
        host_suffixes=config.intranet_allow_host_suffixes,
        allow_http=config.intranet_allow_http,
    )
    if not allowlist.is_empty:
        logger.info(
            "intranet outbound allowlist active: cidrs=%s host_suffixes=%s allow_http=%s",
            [str(n) for n in allowlist.networks], list(allowlist.host_suffixes), allowlist.allow_http,
        )
```

## 数据模型

无。本 spec 不建表、不加列，没有 `forkNNN_` 迁移；白名单不落库。

## 配置

三个新键，均为部署级配置，只能通过 `config.json` 或环境变量设置，改后需重启。

| 键 | 类型 / 默认 | 环境变量 | 文件值校验 |
|---|---|---|---|
| `intranet_allow_cidrs` | `list[str]` / `[]` | `OCTOP_INTRANET_ALLOW_CIDRS`（逗号分隔） | 必须是字符串数组 |
| `intranet_allow_host_suffixes` | `list[str]` / `[]` | `OCTOP_INTRANET_ALLOW_HOST_SUFFIXES`（逗号分隔） | 必须是字符串数组 |
| `intranet_allow_http` | `bool` / `false` | `OCTOP_INTRANET_ALLOW_HTTP`（`_coerce_bool` 语义） | 必须是 JSON 布尔值 |

`config.py` 三触点，每个键都要动以下三处：

1. **dataclass 字段**：在 `OctopConfig` 末尾（`browser_idle_timeout_minutes` ≈L145 之后）追加
   `intranet_allow_cidrs: list[str] = field(default_factory=list)`、
   `intranet_allow_host_suffixes: list[str] = field(default_factory=list)`、
   `intranet_allow_http: bool = False`。
2. **env 覆盖块**：在 `load_config` 的 `OCTOP_BROWSER_IDLE_TIMEOUT_MINUTES` 块（≈L499-509）之后追加三段 `if v := os.environ.get(...)`。列表键用 `_split_env_list(v)`；布尔键用 `_coerce_bool("OCTOP_INTRANET_ALLOW_HTTP", v, merged.get("intranet_allow_http") is True)`。
3. **逐字段构造**：在 `return OctopConfig(...)`（≈L592）末尾追加
   `intranet_allow_cidrs=_parse_str_list("intranet_allow_cidrs", merged.get("intranet_allow_cidrs"))`、
   `intranet_allow_host_suffixes=_parse_str_list("intranet_allow_host_suffixes", merged.get("intranet_allow_host_suffixes"))`、
   `intranet_allow_http=_parse_json_bool("intranet_allow_http", merged.get("intranet_allow_http", False))`。

`_defaults_for_file` 不改。它自动把三个默认值写进首次生成的 `config.json`（需求 5.3）。与既有的 `OCTOP_CORS_ORIGINS` 一致，环境变量设为空串不会清空文件值，要清空须改文件。`w1-02` 合入的"三触点单测"会自动覆盖这三个字段。

`config.py` 只做类型校验；语义校验（网段、后缀、跨字段）在 `intranet_allowlist.build_intranet_allowlist` 里做，因为硬拒集属于 utils 层，而 `config.py` 不得 import `infra`。

## 错误处理

- **不新增 `ErrorCode`**，也不改 `_DEFAULT_STATUS`。
- 守卫的异常类型与三条消息（`only https URLs are allowed`、`private or reserved IP addresses are not allowed`、`cannot resolve hostname …`）全部复用，不新增守卫消息。"明文请求解析到网段外"复用 `only https URLs are allowed`，语义上就是"这个地址必须走 https"。
- 消费方的映射沿用基线：自定义 MCP 保存时 `ValueError` → `CONNECTOR_INVALID_CREDENTIALS`（400）；连接器探测返回 `{"ok": False, "error": str(exc)}`；OAuth 路径把 `UnsafeOutboundUrl` 转为 `ValueError`；语音路径原样上抛。
- 配置错误：`load_config` 对类型错误抛 `ValueError`（消息含键名，不回显文件内容）；`configure_intranet_allowlist` 对语义错误抛 `ValueError`（消息含键名与出错条目）。二者都让 `OctopServer.start()` 或 CLI 命令直接失败，与 `config.py` 对非法 `database` 段的既有处理一致。

## 安全考虑

- **放行面最小化**：网段是唯一能放行私网地址的依据；主机名必须同时命中后缀；硬拒集（含 `169.254.169.254`、环回、`localhost`）无法配置放行；`0.0.0.0/0`、`::/0` 这类超网在配置期被拒。
- **DNS 重绑定**：比对的是解析后的**每一个**地址，并且 `safe_request` 把连接钉在校验过的地址上、不跟随重定向。未命中后缀的主机名即使解析进网段也被拒。
- **明文**：默认关闭；打开后只到网段内。OAuth 端点若走 http，令牌会以明文传输，文档要求 http 只用于不走 OAuth 的内部服务。`discovery.py` ≈L100 对 http 的 MCP 不做 PRM 探测，保持不变。
- **配置面**：只能由部署方改 `config.json` 或 env；不提供在线管理端点，应用管理员账号被盗也无法放宽出站边界。启动 INFO 日志列出生效值，供变更核对。
- **放行面评审清单**：打开白名单会同时放开 15 个调用点，其中语音两处（`_guard_voice_base_url`、`_guard_mimo_base_url`）最容易被漏看。`docs/intranet/ssrf-intranet-allowlist.md` 逐条列出。
- **残余风险（基线就有，本 spec 不扩大也不修复）**：
  - `probe_streamable_http_mcp` 与 harness 运行期的 MCP 连接不做解析期校验。
  - OpenAI 兼容语音在守卫之后用未钉 IP 的客户端。
  - `100.64.0.0/10`（含 `100.100.100.200`）不被拒。
  - `issuer_base_domain` 取末两段过宽。

  这些都登记在"与其他 spec 的交接"与"待行方确认"中。
- **进程级状态**：`octop run` 是单进程；测试在 xdist 下每个 worker 是独立进程，由 `use_intranet_allowlist` 在退出时重置，并由集成用例验证"默认配置启动即重置"。

## 测试策略

所有新增用例只用 `tmp_path` / `tmp_octop_home` 与 `monkeypatch`，不触网，不依赖 POSIX（DNS 用 `socket.getaddrinfo` 桩，HTTP 用 `httpx.MockTransport` 替换 `ssrf_guard.PinnedIPTransport`），Linux 与 Windows CI 都能跑。

| 类别 | 内容 | 本地命令 |
|---|---|---|
| 单测：基线快照 | 上文"基线行为实测"整张表，外加解析期三类（放行、私网、无法解析）与 `safe_request` 的钉 IP 与拒绝；精确比对返回值、异常类型与 `str(exc)`；在基线代码上先跑通 | `uv run pytest tests/unit/utils/test_ssrf_guard_baseline.py -q` |
| 单测：模型与校验 | 网段、后缀、跨字段校验；硬拒集；IPv4 映射归一化；标签边界匹配；非法配置不替换当前值；无参调用重置 | `uv run pytest tests/unit/utils/test_intranet_allowlist.py -q` |
| 单测：放行点 | 需求 2、3、4 全部条目；3xx 不跟随；只放宽不变式（对快照语料中基线放行的输入，在代表性白名单下断言结果不变） | `uv run pytest tests/unit/utils/test_ssrf_guard_intranet.py -q` |
| 单测：消费方 | `validate_mcp_http_url`、`normalize_weknora_base_url`、`_ensure_mcp_oauth_url`、`_guard_voice_base_url` | `uv run pytest tests/unit/connectors/test_ssrf_intranet_consumers.py -q` |
| 单测：配置 | 文件值、env 覆盖、首次写出默认值、类型错误 | `uv run pytest tests/unit/test_config_intranet_allowlist.py tests/unit/test_config.py -q` |
| 单测：CLI 离线 | `open_cli_services(home=tmp_octop_home)` 后 getter 等于配置值 | `uv run pytest tests/unit/cli/test_open_cli_services_intranet_allowlist.py -q` |
| 回归：既有用例 | 4 个既有守护文件 + OAuth discovery，不改一字 | `uv run pytest tests/unit/utils/test_ssrf_guard.py tests/unit/connectors/test_custom_mcp.py tests/unit/connectors/test_mcp_oauth_ssrf.py tests/unit/connectors/test_oauth_discovery.py tests/unit/test_connectors.py -q` |
| 集成 | 写 `config.json` 后经 `octop_client` 启动：getter 等于配置值；默认配置启动即重置；非法网段时 `OctopServer.start()` 抛 `ValueError`；INFO 日志（`caplog`，logger `octop.infra.server`）；管理员 `PUT /api/connectors/custom-mcp` 放行与拒绝两向。鉴权沿用 `tests/integration/conftest.py` 的 `bootstrap_admin` + `auth_header` 写法，以 `w0-03` 合入后的签名为准 | `uv run pytest tests/integration/test_ssrf_intranet_allowlist.py -q` |
| 前端 | 无（不改 `dashboard/`） | — |
| PostgreSQL | 无（不涉及数据库） | — |
| 全量 | ship bar | `make all` |

## 与其他 spec 的交接

**依赖：** 无。本 spec 属于 Wave 0，与 `w0-01` 到 `w0-04` 互相独立，文件不重叠。唯一的软依赖是 `w0-04` 建立的 `CHANGELOG-intranet.md` 与 `docs/intranet/` 目录：若 `w0-04` 尚未合入，条目先写进 PR 描述，由 `w0-04` 补录；`docs/intranet/` 目录由本 spec 的新文件自然创建。

**交付给：**

- `w1-05`（公网 SaaS 断开）：它保留的 WeKnora、Dify、自定义 MCP 与 OpenAI 兼容语音，在行内地址上变得可用，这是 S05 prerequisites[0] 所说的硬阻塞。`w1-05` 删除 `_guard_mimo_base_url` 时不需要改本 spec 的测试（本 spec 只测 `_guard_voice_base_url`）。"无 DNS 时 `cannot resolve hostname` 必须映射为 4xx 而非 500"的断网冒烟（S05 acceptance[12]）归 `w1-05`。
- `w2-04`（行内大模型网关）：模型供应商的 `base_url` 不经过 `ssrf_guard`，本 spec 不为它加守卫，`w2-04` 也不需要白名单。进程级 CA：`PinnedIPTransport` 默认 `trust_env=True`，`SSL_CERT_FILE` 对 `safe_request` 生效；`safe_request` 显式传 transport，不读 `HTTPS_PROXY`，若行内必须走代理，由 `w2-04` 决定是否改 transport。
- `w3-06`（Agent 执行面收紧）：建议它在收敛自定义 MCP（只留 streamable_http 并收归 connectors 权限）的同时，在 `probe_streamable_http_mcp` 建连前调用 `validate_https_url_resolved`，补上解析期校验的既有缺口。该函数已具备白名单语义，`w3-06` 只消费、不重复实现。
- `w3-02`（审计）：白名单是部署级配置，变更不进 `audit_log`，本 spec 只打启动 INFO 日志；如需统一留痕，由 `w3-02` 决定。
- `w2-01`（离线构建）：出网静态门禁的口径可以引用本 spec 的硬拒集与配置键。
- `p2-01`（沙箱网络出口）、`p2-05`（检索服务若经过守卫）、`p2-06`（行内 OA / 知识库 / 工单连接器）：只读 `current_intranet_allowlist()` 或调用守卫，不重复实现白名单。
- `w1-02`：它的"配置三触点单测"会覆盖本 spec 的三个字段；它修 `config.py` ≈L511-531 的重复块时，与本 spec 在 ≈L499 之后追加的 env 段相邻但不重叠。

**看似相关但不归本 spec：**

- S10 changes[31] 的在线管理端点：不做（见"安全考虑"），列入待确认。
- S10 changes[30] 附带的 `issuer_base_domain` 修正：会改变默认行为，不做，列入风险。
- S10 changes[21] / [23] 的 stdio 移除、`probe_streamable_http_mcp` 加校验：归 `w3-06`。
- S10 changes[51] 的 dashboard `security.egressAllowlist*` 文案与新 ErrorCode：随管理端点一起不做。
- S21 changes[30] 的"custom_mcp 自建白名单分支"：改为复用守卫的 `intranet_http_allowed`，不在消费方复制判断逻辑。
- S05 changes[32] 的"allowlist 短路 gaierror"：不采纳。无法解析的主机名本来就无法建连；无 DNS 环境请用 IP 字面量或 `/etc/hosts`，对字面量调用 `getaddrinfo` 不需要 DNS（已实测）。

## 风险与回滚

| 风险 | 影响 | 缓解 |
|---|---|---|
| 网段配得过宽（如 `10.0.0.0/8` 覆盖了数据库、管理网） | 连接器 / 语音可以打到这些主机 | 文档要求按服务配最小网段与后缀；启动日志列出生效值；超网与硬拒段在配置期被拒 |
| 打开 http 后，OAuth 令牌可能明文传输 | 令牌泄露 | 默认关闭；文档写明 http 只给不走 OAuth 的内部服务 |
| fail-fast 让配置错误的实例起不来 | 可用性 | 错误消息指出键与条目；回滚方法是清空三个键 |
| xdist 下模块级状态在测试间泄漏 | 用例互相污染，甚至让安全用例假绿 | 所有新用例经 `use_intranet_allowlist` 在退出时重置；基线快照文件用 autouse fixture 强制空白名单 |
| 基线缺口：`100.64.0.0/10` 不拒（阿里云元数据 `100.100.100.200`） | 部署在阿里云 / 专有云时存在 SSRF 读元数据的风险 | 本 spec 受"默认不变"约束不改；列入待确认，按部署平台决定是否另立热修 |
| 基线缺口：`issuer_base_domain` 取末两段 | 多段公共后缀下 OAuth 同域判断过宽；打开白名单后，被投毒的元数据可能把请求指向网段内其他主机 | 仍受网段、后缀、硬拒集三重约束；列入待确认 |
| 基线缺口：streamable_http 探测与运行期 MCP、语音请求不钉 IP | DNS 重绑定窗口 | 移交 `w3-06`（MCP）；语音列入待确认 |
| 上游同步冲突 | `ssrf_guard.py`、`custom_mcp.py`、`config.py`、`server.py`、`cli/support/db.py` 都是上游文件（浅克隆内可见提交数依次为 7 / 14 / 15 / 23 / 7，仅供参考） | 逻辑下沉到新模块 `intranet_allowlist.py`；上游文件里的增量控制在各自十几行以内，且都是追加或单行条件 |

**回滚：**

- **配置回滚**：清空三个键（或删掉对应 env）并重启，即回到基线行为，由需求 1 保证。
- **代码回滚**：revert 本 spec 的 PR 即可。没有迁移，没有数据，不影响其他 spec 的表结构。回滚前须确认 `w1-05` / `p2-06` 等消费方没有依赖 `intranet_http_allowed` 这类新符号。

## 待行方确认

- **D10（语音能力）**：默认保留 OpenAI 兼容 STT/TTS 并指向行内。本 spec 使该路径在白名单下可用，并把语音列入放行面评审清单。若行方决定整体下线语音，`w1-05` 删除语音路由后，本 spec 的 `_guard_voice_base_url` 用例随之删除。
- **D4（部署形态）**：请确认容器平台所在的云底座。若是阿里云或其专有云，元数据地址 `100.100.100.200` 不被基线守卫拒绝，建议另立热修把 `100.64.0.0/10` 纳入拒绝（这会改变默认行为，不宜放在本 spec）。
- **D2（行内大模型平台）**：模型网关走供应商配置，不经过 `ssrf_guard`，与本 spec 无依赖；若行方要求对供应商出站也做网段管控，需另行立项。
- 以下各项不在第 4 节 D 表中，列为补充确认项：
  - 行内系统是否普遍只有 http（决定部署时是否打开 `intranet_allow_http`）；
  - 是否要求在线维护白名单（若要，需要管理端点、审计与 `ErrorCode`，另立 spec）；
  - 是否存在本机环回上的语音 sidecar（今天环回属于硬拒集）。
