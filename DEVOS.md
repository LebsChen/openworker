# DevOS OpenWorker fork

## 目标

`LebsChen/openworker` 是面向 DevOS 方向的 OpenWorker 增量 fork。目标产品是以 OpenWorker 自己的 Tauri 客户端为外壳，逐步补强到 Devin 级 coding agent，并把 Cloud-Dev/RVM 作为执行 VM；OpenHands 不在当前选型范围内。

当前增量优先解决：

1. 在 RVM 主机上运行可远程连接的 `openworker-server`；
2. 保持 OpenWorker 上游 agent loop、provider、工具和客户端的持续可同步性；
3. 后续以独立模块渐进补强 coding agent，而不是重写上游架构。

## Remote 与分支模型

```text
origin   https://github.com/LebsChen/openworker.git
upstream https://github.com/andrewyng/openworker.git
```

- `main`：纯 upstream 镜像，只允许从 `upstream/main` fast-forward；不落自研提交。
- `devos/main`：长期自研分支，从 `upstream/main` 切出；所有功能分支从 `devos/main` 切出，功能 PR 合回 `devos/main`。
- 功能分支命名：`devos/<unix秒>-<topic>`。
- `upstream` push URL 已禁用，避免误推上游。
- 当前功能分支的提交不会直接合入 `main`。

## 增量原则

1. 自研代码优先新增独立文件/模块，尽量零改上游文件。
2. 不可避免的上游文件改动必须是最小接缝：注册点、参数解析、依赖注入或少量路由/auth 逻辑。
3. 不重排、不格式化上游代码，不动上游测试；新增行为的测试放在上游既有 `tests/` 约定中。
4. 每一处上游文件接缝都登记到 `UPSTREAM_PATCHES.md`，包括路径、变更、原因和 rebase 校验方式。
5. 不提交 `.venv`、状态目录、token 文件、API key 或其他凭据。

## 同步流程

在工作树干净且没有需要保留的未提交改动时运行：

```bash
./scripts/sync-upstream.sh
```

脚本执行：

1. `git fetch upstream`；
2. 切换到 `main`；
3. `git merge --ff-only upstream/main`；
4. 打印但不自动执行 `devos` rebase 命令。

随后人工审阅并执行：

```bash
git switch devos/main
git rebase upstream/main
git push origin devos/main
```

若 rebase 发生冲突，先根据 `UPSTREAM_PATCHES.md` 逐条检查接缝，再运行完整基线/改动测试。不得把自研提交直接写入 `main`。

## 当前增量清单

- 远程 token/server 模式：功能分支 `devos/1785422207-remote-token`，为 server 增加显式 token、token file、非回环绑定安全约束和常数时间鉴权。
- 客户端远程主机模式：功能分支 `devos/1785423280-remote-host`。Tauri 客户端可保存多个远程 profile，profile 保存在独立的 `remote-hosts.json`（权限 `0600`，临时文件写入后原子替换），Rust 不读取或改写 Python SecretStore 的 `secrets.json`。本机 Local 始终是默认主机，登记远程 profile 后新建会话 picker 才提供远程选项；切换会话主机不需要重启客户端。
- token 环境优先级：`COWORKER_API_TOKEN` 高于 `OPENWORKER_TOKEN`，因为前者是 Tauri 按会话显式注入的 token；两者都低于 CLI/token-file。
- RVM 执行 VM 的首选方向：让整个 OpenWorker server 运行在 RVM 主机上，使现有 `LocalExecutor` 就地执行；只有确实需要客户端本机 server 时才考虑 `RvmExecutor`。
- 当前增量的每个上游接缝见 `UPSTREAM_PATCHES.md`。

## 远程主机模式

在 RVM 主机上启动 server（token 文件应为用户可读、权限 `0600`）：

```bash
openworker-server \
  --host 0.0.0.0 \
  --token-file /path/to/rvm-openworker.token
```

在客户端 Settings → Remote host 中保存名称、`http(s)` base URL 和 token。新建会话时
默认选择 Local，也可以在 VM picker 中选择已登记的远程主机；切换会话主机不需要重启。
WS endpoint 从 `http://`/`https://` 分别派生为 `ws://`/`wss://`。HTTPS 一律校验证书，
不提供关闭证书校验的开关，token 不进入 URL query、普通配置或日志。远程会话的 server
及其 `LocalExecutor` 全部运行在 RVM 主机。

如果 `remote-hosts.json` 无法解析，客户端按“没有远程 profile”处理并启动本机
sidecar，同时在 GUI/server 日志和 Settings → Remote host 页面显示明确的解析警告；
这只适用于配置文件损坏或不可读。已成功解析的 profile 如果远程不可达
或鉴权失败，客户端保持远程模式，绝不会回退本机执行。

远程地址不可达或返回 401/403 时，客户端显示明确的连接/鉴权错误并保持远程模式；
绝不会静默切回本机执行。使用 “Use local server” 或取消 active profile 才恢复本机
sidecar。

## Session host mode (Increment 3)

The desktop keeps the implicit local sidecar available as the `local` host even when remote
profiles are registered. New sessions can select a host from the session-host picker; the selected
host is carried by that session's HTTP/WS client and is persisted in the desktop remote-host state.
Session lists are tagged with their host, and a failed host is never replaced by another host.

Each server stores session workspace metadata below its own data root. Session workspaces are under
`<root>/sessions/<session_id>/`; repository-backed sessions use `git worktree add` and archive uses
`git worktree remove`, never recursive deletion of repository internals. Root checks reject paths
outside the owning session workspace, so one session cannot read or write another session's files.

### Explicit workspace isolation

A user-selected workspace is used directly by default. OpenWorker never silently replaces a
selected checkout with a worktree. New-session clients may pass `isolate=true`; only then does the
server create `<root>/sessions/<session_id>/`. A Git checkout becomes a worktree on
`openworker/session-<session_id>`; a non-Git directory gets a normal isolated directory. Session
listing reports `workspace`, `workspace_isolated`, `workspace_worktree`, and `workspace_branch`.
