# Resource Coordinator for Codex

[English](#english) · [简体中文](#简体中文)

## English

**A cooperative local resource queue for parallel coding agents.**

Keep independent work parallel. Queue only the operations that share build outputs,
editors, files, devices or performance-test windows. See who is using a resource,
who is waiting and what is blocking the next operation.

**Version 0.5.2 · MIT · Python 3.11+ · Tested local integration prototype.**
This is an independent project, not an official OpenAI product or an OS-enforced lock.

### Why use it?

Git worktrees isolate source changes, but they do not necessarily isolate a shared
editor, build directory, GPU or test environment. This tool adds explicit resource
reservations around those shared operations. It does not replace Git or decide
which development tasks an agent should perform.

### What it does

| Capability | Behavior |
| --- | --- |
| Resource queues | Shared or exclusive access to agreed resource keys; unrelated work can run concurrently. |
| Atomic reservations | An operation acquires its whole resource set together, not half now and half later. |
| Ordering and dependencies | Earlier eligible conflicting requests have priority; dependencies require successful completion. |
| Development board | Self-reported milestones, freshness, blockers and evidence references; not automatic transcript monitoring. |
| Read-only panel | Local browser view of current users, waiting agents and handoff status. |
| Job supervision | On Windows 10+, track the contained foreground process group before releasing resources. |
| Conservative recovery | Expired or unverifiable work stays blocking; verified reboot recovery is explicit, not a force-unlock command. |
| Durable handoffs | Store release notices; an authorized active host agent sends and records the actual result. |

Typical flow: `request → wait → acquire → work → verify completion → release`.
The next agent still checks the queue and obtains its own reservation.

### Other models and clients

The core makes no model API calls and is not tied to a particular model.

- **CLI:** callable by agents or scripts with local command-execution access.
- **MCP:** a standard local stdio server with 23 tools; an independent Python MCP client has exercised real protocol round trips.
- **Host integration:** Codex plugin loading, hooks and native cross-chat messages are host-specific. Other clients need adapters for those features, or can simply query the queue.

Claude, Cursor and other clients have **not** been individually end-to-end accepted.
Protocol compatibility is not a claim of turnkey integration.
See [client compatibility and configuration](CLIENT_COMPATIBILITY.md) (简体中文).

### Quick start

Clone this repository, then create an isolated environment. Windows / PowerShell:

```powershell
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -e '.[test]'
./.venv/Scripts/python.exe -B plugins/resource-coordinator/scripts/coordinate.py --help
./.venv/Scripts/python.exe -B plugins/resource-coordinator/scripts/coordinate.py status
```

On Linux, use `.venv/bin/python` instead. All participants must use the **same
absolute local database path and matching resource keys**. Use `COORDINATOR_DB` or
place `--db <absolute-local-path>` before the subcommand. Separate databases do not
coordinate with each other. Do not put the SQLite database on a network share.

Before real work, use a new isolated test database and synthetic resources.
Installation does not prove existing chats have reloaded the tool.
Do not overwrite live installation copies or restart active clients just to upgrade.

### Important limits and privacy

- Cooperative scheduling only: unmanaged programs and manual actions are not intercepted.
- A reservation is not permission to restart an editor, discard files or interrupt another agent.
- No independent background chat-wakeup service, automatic preemption, cross-machine lock service or CPU/VRAM quota manager.
- Queue eligibility is not evidence that an unregistered editor or process is idle.
- Non-Windows `run` requires explicit `--tracking observed`; it does not provide equivalent contained-job recovery guarantees.
- The core has no telemetry or automatic upload service. Your model host may still send tool results—including registered paths and summaries—to its provider.
- Keep databases, private receipts, credentials and local reports out of Git. The panel is loopback-only, not a public multi-user service.

### Documentation and verification

- [Detailed operating guide](USAGE.zh-CN.md) (简体中文): setup, panel, resource keys, UE profiles and lifecycle examples.
- [CLI fallback and manual operations](plugins/resource-coordinator/docs/CLI_FALLBACK.md) (简体中文).
- [Windows supervision](plugins/resource-coordinator/docs/SUPERVISION_05.md) and [verified reboot recovery](plugins/resource-coordinator/docs/REBOOT_RECOVERY.md) (简体中文).
- [Security and privacy boundaries](SECURITY.md) · [Acceptance evidence and remaining gates](ACCEPTANCE.md) (English).
- [Publication checks](PUBLICATION_CHECKLIST.md) (简体中文) · [CI runs](https://github.com/kitegs/codex-resource-coordinator/actions) · [MIT license](LICENSE).

Windows/Linux × Python 3.11/3.13 CI covers queue, CLI, MCP and panel regressions.
Windows-only tests are skipped on Linux; passing CI is not full client adoption,
visual acceptance or a production-readiness guarantee. Inspect the run for the
specific commit you intend to use.

## 简体中文

**给并行编程对话使用的本机协作资源队列。**

独立工作继续并行，只有共用编译输出、编辑器、文件、设备或性能测试窗口时才排队。
可以查看谁在占用、谁在等待，以及下一步被什么挡住。

**当前版本 0.5.2 · MIT 许可证 · Python 3.11+ · 经过测试的本地集成原型。**
本项目不是 OpenAI 官方产品，也不是操作系统强制锁。

### 解决什么问题

Git 工作树可以隔离源码修改，却不一定隔离共用的编辑器、构建目录、GPU 或测试环境。
这个工具为共享操作增加明确的申请和释放流程，不替代 Git，也不替对话决定开发任务。

### 主要功能

| 功能 | 实际行为 |
| --- | --- |
| 资源排队 | 按约定的资源名称申请共享或独占；互不冲突的工作可以并行。 |
| 原子占用 | 同一操作一次拿齐所需资源，不先占一半再等待另一半。 |
| 顺序与依赖 | 先到且满足条件的冲突请求优先；前置任务必须成功完成才解锁。 |
| 开发状态板 | 展示自报里程碑、新鲜度、阻塞与证据引用，不自动监视全部聊天。 |
| 只读面板 | 在本机浏览器查看占用者、等待者和交接结果。 |
| 作业监护 | Windows 10+ 等待受监护的整组前台进程结束后再释放。 |
| 保守恢复 | 过期或无法核实的作业继续阻挡；跨重启恢复需要明确证据，不提供强制清锁。 |
| 持久化交接 | 保存释放提醒，由获准的活跃对话通过宿主发送并记录真实结果。 |

基本流程：`请求 → 等待 → 取得占用 → 工作 → 核实结束 → 释放`。
下一位收到提醒后仍需重新查队列、申请占用。

### 其他模型和客户端能用吗

核心不调用模型 API，也不绑定某个模型。

- **CLI：**有本机命令执行权限的代理或脚本可以调用。
- **MCP：**提供标准本机 stdio 服务，共 23 个工具；独立 Python MCP 客户端已验证真实协议往返。
- **宿主接入：**Codex 插件加载、Hook 和原生对话消息属于宿主能力；其他客户端需要适配，或只使用队列查询。

Claude、Cursor 等客户端尚未逐一完成端到端验收，协议可接入不等于开箱即用。
具体配置见[跨客户端接入](CLIENT_COMPATIBILITY.md)。

### 快速开始

克隆仓库后建立独立环境。Windows / PowerShell 示例：

```powershell
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -e '.[test]'
./.venv/Scripts/python.exe -B plugins/resource-coordinator/scripts/coordinate.py --help
./.venv/Scripts/python.exe -B plugins/resource-coordinator/scripts/coordinate.py status
```

Linux 使用 `.venv/bin/python`。所有参与者必须使用**同一个绝对本地数据库路径和一致的资源名称**。
可以设置 `COORDINATOR_DB`，或将 `--db <绝对本地路径>` 放在子命令前。
不同数据库互相不知道占用；不要把 SQLite 状态库放在网络共享磁盘上。

先使用全新的隔离测试库和虚构资源验证，再接真实共享工作。
安装成功不代表旧对话已经重新加载；不要覆盖正在使用的安装副本，也不要为升级中断活跃客户端。

### 限制与隐私

- 这是协作约定，不会拦截未接入的程序或人工操作。
- 拿到占用不等于获准重启编辑器、丢弃文件或中断其他对话。
- 没有独立后台聊天唤醒服务、自动抢占、跨机器锁服务或 CPU／显存配额管理。
- 队列允许申请，不代表未登记的编辑器或进程已经空闲。
- 非 Windows 的 `run` 需要显式选择 `--tracking observed`，不具备同等的受监护作业恢复保证。
- 核心没有遥测或自动上传服务，但模型宿主仍可能把工具输出中的路径、状态摘要等发给服务商。
- 数据库、私有回执、凭据和本机报告不要提交到 Git；面板仅供本机访问，不是公网多人服务。

### 文档与验证

- [详细使用指南](USAGE.zh-CN.md)：安装、面板、资源名称、UE 配置与完整流程。
- [CLI 后备与手动操作](plugins/resource-coordinator/docs/CLI_FALLBACK.md)。
- [Windows 作业监护](plugins/resource-coordinator/docs/SUPERVISION_05.md)与[跨重启恢复](plugins/resource-coordinator/docs/REBOOT_RECOVERY.md)。
- [安全与隐私边界](SECURITY.md)、[验收记录与缺口](ACCEPTANCE.md)（英文）。
- [公开检查说明](PUBLICATION_CHECKLIST.md)、[CI 检查](https://github.com/kitegs/codex-resource-coordinator/actions)、[MIT 许可证](LICENSE)。

Windows／Linux × Python 3.11／3.13 的 CI 覆盖队列、CLI、MCP 和面板回归。
Windows 专属测试在 Linux 上跳过；CI 通过不等于全部客户端接入、视觉验收或发布质量保证。
使用前请核对自己所选提交的检查结果。
