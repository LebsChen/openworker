# Upstream patch ledger

仅登记对 upstream 文件的最小接缝；新增独立文件不需要登记。每次 rebase 前后都要复核本表。

| 文件 | 变更 | 原因 | rebase 校验 |
|---|---|---|---|
| `coworker/server/run.py` | 增加 `--token`、`--token-file`、环境 token 解析、绑定摘要日志；随机模式仍写入并清理 launch token 文件。 | 允许 RVM 主机以预设凭据安全暴露 server，同时保持默认本机 sidecar 行为。 | rebase 后确认参数解析、`COWORKER_API_TOKEN` 生命周期、随机 token 文件清理和非回环启动日志测试。 |
| `coworker/server/app.py` | HTTP header 与 WebSocket subprotocol 鉴权统一调用 `token_matches`。 | 集中保证两条鉴权路径使用常数时间比较。 | rebase 后确认 `/v1/*` 与两个 WS 路由均拒绝错误 token、接受正确 token。 |
