# 行内版 API 差异

本文件只记录行内 fork 相对上游 [api.md](api.md) 的差异；`api.md` 正文在上游同步时一律取上游，fork 不改。
每节一张表，列为：对象、spec、说明、合入日期。

## 1. 已下线的上游路由

登记在 `src/octop/api/intranet_mounts.py` 的 `_FORK_DISABLED_MOUNTS`（引用写成 `"<模块>:<属性>"`），路由对象不再挂载。表中写明引用、原前缀、原 tag。

暂无。

## 2. 已物理删除的上游路由

暂无。

## 3. fork 新增或变更的端点

暂无。

## 4. 鉴权与权限差异

暂无。

## 5. fork 新增错误码

写明码、HTTP 状态、文案所在的 overlay（`src/octop/i18n/intranet/`、`dashboard/src/locales/intranet/`）。

暂无。

## 6. 连接器目录差异

来源为 `src/octop/infra/connectors/catalog_intranet.py` 的 `_FORK_REMOVED`（隐藏的上游 kind）与 `_fork_entries()`（追加的行内条目）。

暂无。
