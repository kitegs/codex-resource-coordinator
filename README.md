# Resource Coordinator for Codex

给并行本地对话使用的**协作资源队列**：源码可在 Git 工作树里并行修改，共用编译产物、编辑器、资产和性能测试窗口则先申请占用。独立本机 SQLite 保存队列，MCP 提供工具，命令启动器拿到许可才运行。不是 OpenAI 官方产品。

**当前为 0.1.0 验证原型，不是安全隔离层。** 未经接入的构建、应用或手工操作不受它控制。空队列不代表没有 UE 运行。排到队不代表获得关闭编辑器、丢弃资产或停止他人工作的授权。

## 架构

```text
Codex 对话 A ─┐
Codex 对话 B ─┼─ MCP / CLI ── 同一份本地 SQLite
Codex 对话 C ─┘                    │ 原子申请全部资源
                         等待，或拿到短期许可
                                   │
                       受控启动器 → 已批准的前台命令
                                   │
                       心跳、观察到的子进程、完成释放
```

- `shared` 允许多个读取者；`exclusive` 与同一资源上的所有占用冲突。
- 同一请求一次获得全部资源，不持有半套资源等待另一半，避免这种持有式死锁。
- 先到的冲突请求优先；不相关资源可以继续运行。等待者必须自行取消，不会因沉默被自动移除。
- 许可过期进入 `suspect`，**继续阻挡**。确认工作已停止，且记录的进程已经消失后，才显式恢复。
- 许可使用随机令牌；数据库只存哈希，状态和事件不返回令牌。令牌不是本机账户间的身份认证。
- 本项目不读取 Codex 会话数据库，不修改 Git，不结束进程，不操作 UE。

## 安装准备（不打断现有对话）

需要 Python 3.11+。Git 仅用于可选 UE 工作树身份解析。Windows 原生环境是首轮实际测试平台；Linux 和其他 Python 版本需要 CI 结果确认。

在这个独立仓库内创建环境，不要把插件代码放进游戏源码仓库：

```powershell
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -e '.[test]'
./.venv/Scripts/python.exe -m pytest -q
./.venv/Scripts/python.exe scripts/prepare_install.py --python .venv/Scripts/python.exe --target .local/marketplace-v0.1.0
```

Linux 对应解释器为 `.venv/bin/python`。准备脚本拒绝覆盖已有目标，生成独立安装副本，固定其 MCP 和提醒 Hook 使用的解释器；**不修改 Codex 设置、不启动服务、不重启客户端**。源码清单中的默认 `python` 仅适用于已安装依赖的同一解释器，不要误用另一个 Python。

等其他对话到稳定点后，再注册准备好的本地市场：

```text
codex plugin marketplace add <准备脚本返回的marketplace绝对路径>
```

在 Codex 插件目录选择 Resource Coordination → resource-coordinator。需要客户端刷新/重启时先结束或交接活动任务，不能为了安装强行退出它们。Hook 需独立审阅和信任；默认只有 SessionStart 状态提醒，**没有全局 PreToolUse 拦截**。安装文件不等于已经在运行中的对话生效。

MCP 也可直接连接准备副本的 `scripts/server.py`，解释器仍使用上面的独立环境。直接配置 MCP 与通过插件配置二选一，避免重复工具/进程。

## 共享状态

默认数据库在：

- Windows：`%LOCALAPPDATA%/CodexResourceCoordinator/state.sqlite3`
- 其他系统：`$XDG_STATE_HOME/CodexResourceCoordinator/state.sqlite3`，未设置则为用户 `.local/state`。

可用 `COORDINATOR_DB` 或 CLI `--db` 指定**同一个绝对本地磁盘路径**。不得给每个工作树、插件缓存或对话分配不同数据库来假装协调；不支持网络共享磁盘。数据库、WAL、报告和本机路径不应提交到 GitHub。状态保留直到你自行制定清理政策；本版不自动删除历史。

## 怎么使用

在 Codex 中用 `$resource-coordination`。建议先让两个测试对话在测试资源上申请，不要立即接管已运行的 UE。旧任务必须由其负责人明确交接。

MCP 工具有：`queue_status`、`request_resources`、`acquire_resources`、`begin_operation`、`renew_lease`、`complete_operation`、`cancel_waiting`、`reconcile_expired`、`plan_ue_resources`。服务器不提供任意命令执行、杀进程、Git 集成或消息发送能力。

命令行例子（在 PowerShell 中）：

```powershell
$coord = 'plugins/resource-coordinator/scripts/coordinate.py'
./.venv/Scripts/python.exe $coord request --owner demo-chat --purpose 'small foreground test' --resources '[{"key":"demo:build","mode":"exclusive"}]'
# 上一步返回请求 ID。run 负责申请许可及心跳，不能先手动 acquire 再交给 run。
./.venv/Scripts/python.exe $coord run --request <ID> --owner demo-chat -- python -c 'print("hello")'
./.venv/Scripts/python.exe $coord status
```

返回码：`0` 成功；`3` 排队，命令**没有启动**；其他为命令失败或协调错误，先查请求状态，不要自动重跑。

命令仍须通过正常执行工具及其权限审批。只支持前台、不后台脱离的命令；不支持把 `start`/daemon 化程序当已跟踪任务。启动器保守记录观察到的子进程，但不保证看到所有瞬时或脱离的子进程。中断、监控错误或主进程退出但孩子仍活动时，保留占用并人工核查。它不限制 CPU/显存，需组合已有的负载限制器。

## UE 接法

`plan-ue --project <真实集成工程目录> --operation <类别>` 只计算建议资源，不运行 UE，也不检查试玩、未保存资产或特定构建参数是否真的不改 DLL。

| 类别 | 约束 |
| --- | --- |
| `compile-only` | 共享源码读取、独占构建输出、共享运行时；仍须单独验证不链接的实际行为 |
| `cold-build` | 独占输出和运行时；必须先按原权限确认干净关闭 |
| `integrate` | 独占该目录源码、构建输出、运行时 |
| `editor-test` | 共享运行时和机器负载；各自只操作自己的实例 |
| `performance` | 独占参与者的机器负载资源；不能承诺关闭未注册程序 |

不同工作树的源码/输出有不同键，Git 公共目录身份仍一致。共享主工程时必须填**实际主工程路径**。资产可以额外约定 `asset:<稳定资源路径>` 独占键。同一个资源不能用两个不同别名绕过冲突。

## 验收与限制

自测覆盖真实多进程竞争、FIFO、共享/独占、全部资源原子申请、取消、幂等、过期保留、旧令牌、存活/未知进程拒绝释放、命令未启动证明、前台成功/失败、MCP stdio 和安装副本；另有非 UE 的数据库迁移场景。具体结果看本次报告，不以测试数量替代实际 Codex/UE 接入验收。

尚不具备：自动接管旧会话、操作系统级强制互斥、完备命令解析、任意后台进程追踪、跨机器锁服务、自动抢占、UI 面板、GPU 预算、多人安全认证。全局 Hook 不是可靠的 fail-closed 边界；本版不假装提供。

许可：MIT。后续公开前再次检查没有带入项目素材、日志、令牌和私人路径。

官方接入参考：[插件打包](https://developers.openai.com/plugins/build/plugins)、[MCP](https://learn.chatgpt.com/docs/extend/mcp)、[Hooks 的覆盖与限制](https://learn.chatgpt.com/docs/hooks)。
