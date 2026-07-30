# Upstream patch ledger

仅登记对 upstream 文件的最小接缝；新增独立文件不需要登记。每次 rebase 前后都要复核本表。

| 文件 | 变更 | 原因 | rebase 校验 |
|---|---|---|---|
| `coworker/server/run.py` | 增加 `--token`、`--token-file`、环境 token 解析、绑定摘要日志；随机模式仍写入并清理 launch token 文件。`resolve_token` 始终产生非空 token，因此非回环启动不会出现无鉴权 server。 | 允许 RVM 主机以预设凭据安全暴露 server，同时保持默认本机 sidecar 行为。 | rebase 后确认参数解析、`COWORKER_API_TOKEN` 生命周期、随机 token 文件清理和非回环启动日志测试。 |
| `coworker/server/app.py` | HTTP header 与 WebSocket subprotocol 鉴权统一调用 `token_matches`。 | 集中保证两条鉴权路径使用常数时间比较。注意上游 `_websocket_authenticated` 在 `api_token` 为空时仍返回 `True`；本次不改，上游 standalone `run.py` 始终设置 token。 | rebase 后确认 `/v1/*` 与两个 WS 路由均拒绝错误 token、接受正确 token。 |
| `surfaces/gui/src-tauri/src/lib.rs` | 增加独立 `remote-hosts.json`（0600、临时文件原子替换）及 Tauri profile 管理命令、启动时 endpoint 选择及 active profile 下跳过 sidecar spawn；Rust 不读写 Python `secrets.json`，保留原有本机启动路径。 | 让 OpenWorker Tauri 客户端连接运行在 RVM 主机上的 `openworker-server`，避免 agent 工具误在本机执行，并避免破坏 Python SecretStore。 | rebase 后确认 `run()` 的 active-profile 分支仍不调用 `Command::spawn`，未激活时仍注入 127.0.0.1 endpoint；确认损坏的 remote-hosts 文件按未配置处理、URL 拒绝凭据/query/fragment。 |
| `surfaces/gui/src/api.ts` | 远程模式 runtime 标记、health 非 2xx 的连接/鉴权错误。 | 让不可达或错误 token 变成用户可见错误，禁止静默本机 fallback。 | rebase 后确认 REST header/WS subprotocol 仍使用 runtime token，并覆盖 401/403 与网络错误测试。 |
| `surfaces/gui/src/tauri.ts` | 暴露远程 profile 管理命令的薄 frontend bridge。 | 连接 Settings UI 与 Rust 的安全存储/激活逻辑。 | rebase 后确认命令名和 snake_case 参数与 Rust `#[tauri::command]` 一致。 |
| `surfaces/gui/src/components/SettingsView.tsx` | 增加 Remote host profile 管理卡片。 | 为多 profile 保存、选择和恢复本机模式提供用户入口。 | rebase 后确认 token 仅作为 password 输入传给 Rust，不写入 localStorage/普通前端配置。 |
| `surfaces/gui/src/App.tsx` | 启动失败时展示远程连接错误和 no-fallback 说明；扩展 Settings deep-link 类型。 | 让远程错误保持在远程模式语义下，而不是落入本机 folder gate。 | rebase 后确认远程 health 失败不会调用任何本机启动逻辑。 |
