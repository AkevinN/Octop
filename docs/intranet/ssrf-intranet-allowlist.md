# SSRF 守卫内网白名单

服务端出站请求由 `src/octop/infra/utils/ssrf_guard.py` 统一把关：默认只放行指向公网地址的 https。行内部署时，连接器、OAuth 与语音网关要访问 10.x、172.16.x 这类地址，以及只有 http 的老系统，需要登记内网白名单。

三个键都取默认值时，守卫行为与上游完全一致。白名单只会放宽，不会新增任何拒绝。

## 配置

白名单是部署级配置，只能改 `~/.octop/config.json` 或环境变量，改后需要重启。没有在线管理端点，应用管理员无法在线放宽出站边界。

| 键 | 类型 / 默认 | 环境变量（覆盖文件值） |
|---|---|---|
| `intranet_allow_cidrs` | 字符串数组 / `[]` | `OCTOP_INTRANET_ALLOW_CIDRS`，逗号分隔 |
| `intranet_allow_host_suffixes` | 字符串数组 / `[]` | `OCTOP_INTRANET_ALLOW_HOST_SUFFIXES`，逗号分隔 |
| `intranet_allow_http` | 布尔 / `false` | `OCTOP_INTRANET_ALLOW_HTTP`（`true/false/1/0/yes/no/on/off`） |

环境变量设为空串不会清空文件值，要清空须改文件。

### 示例

只放行行内网段上的 https 服务：

```json
{
  "intranet_allow_cidrs": ["10.20.0.0/16"],
  "intranet_allow_host_suffixes": ["bank.intra"]
}
```

在此基础上允许老系统使用明文 http（只对白名单内的主机生效）：

```json
{
  "intranet_allow_cidrs": ["10.20.0.0/16", "10.30.5.0/24"],
  "intranet_allow_host_suffixes": ["bank.intra"],
  "intranet_allow_http": true
}
```

请按服务配置最小网段，不要直接登记覆盖数据库、管理网的 `10.0.0.0/8`。

## 放行语义

- **网段**：私网、保留地址只有落在 `intranet_allow_cidrs` 里才会被放行，这是唯一的依据。IPv4 映射的 IPv6 地址（如 `::ffff:10.1.2.3`）按其 IPv4 部分比对。
- **IP 字面量**：URL 里直接写 IP 时，该 IP 在网段内即放行。
- **主机名（防 DNS 重绑定）**：主机名必须按 DNS 标签边界命中某个后缀（`bank.intra` 匹配 `bank.intra`、`a.b.bank.intra`，不匹配 `evilbank.intra`、`bank.intra.evil.com`），并且解析出的**每一个**私网地址都在网段内，才会放行。没有命中后缀的主机名，即使解析进网段也会被拒绝。`safe_request` 把连接钉在校验过的 IP 上，不做二次解析，也不跟随 3xx 重定向。
- **明文 http**：`intranet_allow_http` 默认关闭。打开后，只有网段内的 IP 字面量或命中后缀的主机名可以使用 http，并且解析结果必须**全部**落在网段内（公网地址也不行），否则报 `only https URLs are allowed`。OAuth 端点不要走 http，否则令牌会明文传输；http 只用于不走 OAuth 的内部服务。

### 硬拒集

以下地址无论怎样配置都会被拒绝，含其 IPv4 映射写法：

- 环回 `127.0.0.0/8`、`::1`，以及字面量 `localhost`；
- 链路本地 `169.254.0.0/16`（含云元数据 `169.254.169.254`）、`fe80::/10`；
- 未指定 `0.0.0.0/8`、`::`；组播 `224.0.0.0/4`、`ff00::/8`；保留 `240.0.0.0/4`。

与硬拒集或 `::ffff:0:0/96` 相交的网段（如 `0.0.0.0/0`、`::/0`、`127.0.0.0/8`）在配置期就会被拒绝。

## 配置错误即启动失败

`OctopServer.start()` 在打开控制面数据库之前注入白名单；`bind_control_plane()` 与 CLI 离线路径 `open_cli_services()` 同样注入。配置非法时服务直接启动失败，不会以空白名单或部分白名单运行。错误消息样例：

```
config.intranet_allow_cidrs must be a list of strings
config.intranet_allow_http must be true or false
intranet_allow_cidrs: invalid entry '10.1.2.3/8' (10.1.2.3/8 has host bits set)
intranet_allow_cidrs: invalid entry '0.0.0.0/0' (overlaps 0.0.0.0/8)
intranet_allow_host_suffixes: invalid entry '*.bank.intra'
intranet_allow_http requires intranet_allow_cidrs
```

后缀不能为空，不能含 `*`、`/`、`:` 或空白，不能是 IP 或 `localhost` / `*.localhost`，至少两段。配置了后缀或打开了 http 却没有配置网段，也视为错误。

白名单非空时，启动日志会有一条 INFO：`intranet outbound allowlist active: cidrs=[…] host_suffixes=[…] allow_http=…`，可用于变更核对。回滚方法是清空三个键并重启。

## 受影响的调用点

打开白名单会同时放开以下 5 个模块、15 个守卫调用点，评审时请逐条核对：

| 模块 | 调用点 |
|---|---|
| `infra/voice/adapters.py` | `_guard_voice_base_url`（OpenAI 兼容 STT/TTS）、`_guard_mimo_base_url` |
| `infra/connectors/oauth/discovery.py` | `_fetch_prm_document` 的 `validate_https_url` 与 `safe_request`；`_probe_401_resource_metadata` 的 `validate_https_url` 与 `safe_request`（http 的 MCP 不做该探测） |
| `infra/connectors/oauth/mcp.py` | `_ensure_mcp_oauth_url` 的 `validate_https_url` 与 `validate_https_url_resolved`；`fetch_authorization_metadata`、`register_dynamic_client`、`exchange_authorization_code`、`refresh_access_token` 的 `safe_request` |
| `infra/connectors/custom_mcp.py` | `validate_mcp_http_url`（自定义 MCP、WeKnora、Dify 的 URL 校验；其 http 前置拦截改为调用 `intranet_http_allowed`） |
| `infra/connectors/probe.py` | `probe_connector` raw http 分支的两处 `safe_request` |

## 排障：能保存，但测试连接失败

保存连接器时只调用 `validate_https_url`，它只检查 URL 字面量、不解析 DNS，所以"内部主机名 + https"总能保存成功。测试连接或实际请求时才会解析 DNS 并比对网段。遇到这种情况，请依次检查：

1. 主机名是否命中 `intranet_allow_host_suffixes`；
2. 该主机名解析出的**全部**地址是否都在 `intranet_allow_cidrs` 内（`getent ahosts <主机名>`）；
3. 使用 http 时是否打开了 `intranet_allow_http`；
4. 报 `cannot resolve hostname` 说明服务器上没有可用的 DNS，请改用 IP 字面量或在 `/etc/hosts` 登记。

## 已知缺口

以下是上游基线就存在的缺口，本白名单不扩大、也不修复：

- `100.64.0.0/10`（含阿里云元数据地址 `100.100.100.200`）不被守卫拒绝；
- `probe_streamable_http_mcp` 建连前不做解析期校验，harness 运行期的 MCP 连接也不经过守卫（移交 `w3-06`）；
- OpenAI 兼容语音在守卫之后使用未钉 IP 的客户端，存在校验与建连之间的 DNS 重绑定窗口；
- `issuer_base_domain` 按"末两段"判断 OAuth 同域，对 `*.com.cn` 这类多段公共后缀过宽。
