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
- token 环境优先级：`COWORKER_API_TOKEN` 高于 `OPENWORKER_TOKEN`，因为前者是 Tauri 按会话显式注入的 token；两者都低于 CLI/token-file。
- RVM 执行 VM 的首选方向：让整个 OpenWorker server 运行在 RVM 主机上，使现有 `LocalExecutor` 就地执行；只有确实需要客户端本机 server 时才考虑 `RvmExecutor`。
- 当前增量的每个上游接缝见 `UPSTREAM_PATCHES.md`。
