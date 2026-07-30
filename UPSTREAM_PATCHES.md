# Upstream patch ledger

仅登记对 upstream 文件的最小接缝；新增独立文件不需要登记。每次 rebase 前后都要复核本表。

| 文件 | 变更 | 原因 | rebase 校验 |
|---|---|---|---|
| `coworker/server/run.py` | 增加 `--token`、`--token-file`、环境 token 解析、绑定摘要日志；随机模式仍写入并清理 launch token 文件。`resolve_token` 始终产生非空 token，因此非回环启动不会出现无鉴权 server。 | 允许 RVM 主机以预设凭据安全暴露 server，同时保持默认本机 sidecar 行为。 | rebase 后确认参数解析、`COWORKER_API_TOKEN` 生命周期、随机 token 文件清理和非回环启动日志测试。 |
| `coworker/server/app.py` | HTTP header 与 WebSocket subprotocol 鉴权统一调用 `token_matches`。 | 集中保证两条鉴权路径使用常数时间比较。注意上游 `_websocket_authenticated` 在 `api_token` 为空时仍返回 `True`；本次不改，上游 standalone `run.py` 始终设置 token。 | rebase 后确认 `/v1/*` 与两个 WS 路由均拒绝错误 token、接受正确 token。 |
| `surfaces/gui/src-tauri/src/lib.rs` | 增加独立 `remote-hosts.json`（0600、临时文件原子替换）、session host 注入及 Tauri profile/session 绑定命令；本机 sidecar 始终作为隐式 Local host 保持运行；Rust 不读写 Python `secrets.json`；损坏配置保留本机语义但输出可见警告。 | 让 OpenWorker Tauri 客户端连接运行在 RVM 主机上的 `openworker-server`，避免 agent 工具误在本机执行，并避免破坏 Python SecretStore。 | rebase 后确认 `run()` 始终注入 Local endpoint，远程 profile 通过 session picker 选择；确认损坏的 remote-hosts 文件按未配置处理但 GUI/server 有警告、URL 拒绝凭据/query/fragment。 |
| `surfaces/gui/src/api.ts` | 远程模式 runtime 标记、health 非 2xx 的连接/鉴权错误。 | 让不可达或错误 token 变成用户可见错误，禁止静默本机 fallback。 | rebase 后确认 REST header/WS subprotocol 仍使用 runtime token，并覆盖 401/403 与网络错误测试。 |
| `surfaces/gui/src/tauri.ts` | 暴露远程 profile 管理命令的薄 frontend bridge。 | 连接 Settings UI 与 Rust 的安全存储/激活逻辑。 | rebase 后确认命令名和 snake_case 参数与 Rust `#[tauri::command]` 一致。 |
| `surfaces/gui/src/components/SettingsView.tsx` | 增加 Remote host profile 管理卡片。 | 为多 profile 保存、选择和恢复本机模式提供用户入口。 | rebase 后确认 token 仅作为 password 输入传给 Rust，不写入 localStorage/普通前端配置。 |
| `surfaces/gui/src/App.tsx` | 启动失败时展示远程连接错误和 no-fallback 说明；扩展 Settings deep-link 类型。 | 让远程错误保持在远程模式语义下，而不是落入本机 folder gate。 | rebase 后确认远程 health 失败不会调用任何本机启动逻辑。 |
| `surfaces/gui/src/App.tsx` | 接入右侧 session panel、按绑定 host 加载面板数据；切换 session 时清空旧 transcript/usage，并用请求代次阻止旧消息响应覆盖当前 session。 | 保持右栏和消息历史遵循 session → host 绑定，避免远程 host 离线时串显上一个 session 的内容。 | rebase 后确认 panel 请求继续使用 `hostForSession(sessionId)`，session 切换和失败加载不会恢复旧 `items`。 |
| `surfaces/gui/src/styles.css` | 增加 Cloud-Dev 风格 right-panel shell/drawer/icon rail 布局；同步 380px drawer 占位；为 topbar 标题、host picker 和 remote 状态提供可收缩 flex 与 ellipsis 约束。 | 让右栏展开时不覆盖顶栏，并保证长 session 标题、host picker、offline 提示互不重叠。 | rebase 后确认 `.main-topbar`、`.main-chat` 与 panel drawer 宽度同步，标题和右侧控件均可收缩。 |
| `surfaces/gui/src/components/Icon.tsx` | 增加 `terminal` 与 `monitor` 图标。 | 为 Shell、Browser/Desktop 的 icon rail 入口提供不重复且语义对应的图标。 | rebase 后确认新增 path 与现有 stroke/fill 风格一致，IconName 联合类型同步更新。 |
| `surfaces/gui/src/components/RightRail.tsx` | 将旧 inspector 改为常驻 icon rail + 左侧 drawer；增加 Info、Worklog、File changes 及 RVM-only 空态，pane 保持 mounted；Worklog 使用统一 selector，Artifacts 使用绑定 host。 | 对齐 Cloud-Dev right-shell 交互，同时保留 Progress/Access/Artifacts 和 Local/Remote host 语义。 | rebase 后确认切换 icon 不卸载 pane，Local 禁用 RVM 标签，所有 REST 请求使用 session 绑定 host。 |

- `coworker/server/manager.py`, `coworker/server/app.py`: explicit `isolate` session option; user-selected workspaces remain unchanged unless isolation is requested. Session list exposes actual isolation/worktree metadata.
| `coworker/agents/base.py`, `coworker/catalog.py`, `coworker/permissions.py`, `coworker/roots.py`, `coworker/agent.py`, `coworker/server/manager.py`, `coworker/server/app.py` | Add optional remote target plumbing, remote path-aware permission/root handling, RVM host CRUD/test routes, host-bound engine construction, and remote workspace persistence. Local behavior remains the default when no remote target is supplied. | Keep the client-side agent loop and approval flow while routing batch-1 execution to an RVM without any local fallback. | Rebase: verify `remote_target=None` preserves local engine/tool/catalog behavior; verify unknown host IDs fail instead of constructing LocalExecutor; run remote and full pytest suites. |
