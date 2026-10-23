# 详细使用指南 · Resource Coordinator

[English / 简体中文首页](README.md)

给并行本地对话使用的**协作资源队列**：源码可在 Git 工作树里并行修改，共用编译产物、编辑器、资产和性能测试窗口则先申请占用。独立本机 SQLite 保存队列，MCP 提供工具，命令启动器拿到许可才运行。不是 OpenAI 官方产品。

**当前为 0.5.2 本地集成原型，不是安全隔离层。** 未经接入的构建、应用或手工操作不受它控制。空队列不代表没有 UE 运行。排到队不代表获得关闭编辑器、丢弃资产或停止他人工作的授权。

0.2 新增共享开发状态板、状态新鲜度、成功依赖排序和低噪声变更游标。详见[协作信息与缺口](COORDINATION_DESIGN.md)。它不是完整的 Agent Teams 总控，不自动创建／接管对话或发送消息。

0.3 增加本机只读面板：项目筛选、对话状态、资源队列、版本／证据详情、过期与断线提示。可在普通浏览器或 Codex 浏览器侧栏查看，不是 Codex 原生插件侧栏扩展。

0.4 增加持久化交接通知：真实释放后挑选下一候选，由完成方使用宿主消息工具代发，记录投递受理、明确失败或结果不明；面板显示接收者和通知状态。没有独立后台通知服务，也没有保证消息已读。

0.4.1 补齐CLI登记、版本保护的进度上报、变化／游标、依赖与完整通知处理入口；领取凭据留在私有文件，不打印token。增加未发送失效提醒的显式归档，不清除结果不明记录。MCP未加载时也能沿同一队列工作，详见[CLI后备流程](plugins/resource-coordinator/docs/CLI_FALLBACK.md)。不热覆盖其他对话正在使用的旧缓存。

0.5 增加 Windows 作业监护、重复启动保护和有证据的恢复；前台只突出“谁在用、下一位、提醒结果”。正常释放后沿用同一发件箱提醒，不广播每种状态，不把失败当验收成功。[使用与边界](plugins/resource-coordinator/docs/SUPERVISION_05.md)。

0.5.1 补齐手动GUI／资产操作的 CLI `acquire → begin → renew → complete`。令牌只留私有回执，排队不会启动工作；过期仍阻挡，不能绕过受监护作业。自动编译继续使用 `run`，不要求人手动操作四个步骤。详见[CLI流程第2a节](plugins/resource-coordinator/docs/CLI_FALLBACK.md)。MCP配置保持不变。

0.5.2 增加仅 CLI 的[跨重启恢复](plugins/resource-coordinator/docs/REBOOT_RECOVERY.md)：先只读核对，再显式确认；CIM 与两次真实系统启动事件、同机身份及旧进程时间必须同时成立。旧作业记为中断／结果未知，不解锁成功依赖，不重跑命令。旧票缺少机器指纹时额外依赖操作者同机确认，不能称自动证明。旧版准备副本／运行进程不热覆盖。

各对话先自行判断下一操作是否需要协调：普通读取和独立源码修改不排队；共享输出、编辑器重启／控制、同资产写入、性能采样再申请。不自动扫描对话、把所有任务入队或让整个对话长期占资源。

## 其他模型和客户端能否使用

**队列核心不绑定模型，也不调用模型 API。** CLI 可由有本机命令执行权限的客户端
调用；MCP 服务使用标准 stdio。Codex 的插件安装、提醒 Hook 和原生对话消息接口
则属于宿主接入，不能自动搬到其他客户端。详见[跨客户端接入](CLIENT_COMPATIBILITY.md)。

| 入口 | 可复用范围 | 已验证边界 |
| --- | --- | --- |
| CLI | 能执行本机 Python 命令的代理／脚本 | Windows 本机 CLI 和独立队列场景已测 |
| MCP stdio | 支持本机 stdio MCP 的客户端 | 独立 Python MCP 客户端真实握手与调用已测；不代表所有产品已适配 |
| 只读面板 | 能访问本机回环地址的浏览器 | HTTP／DOM 测试已覆盖；不是任意宿主的原生侧栏 |
| 跨对话提醒 | 需要宿主提供消息发送能力与真实授权 | 当前返回 Codex 宿主调用参数；其他宿主需适配或只查队列 |

公开源码不包含本机状态库、安装副本、凭据和测试日志。运行时的状态、路径等仍可能
作为工具结果交给你的模型客户端；这不等于完全离线或不会被宿主上传。
发布前检查及剩余风险见[公开检查说明](PUBLICATION_CHECKLIST.md)和[安全边界](SECURITY.md)。

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

需要 Python 3.11+。Git 仅用于可选 UE 工作树身份解析。Windows／Linux、Python 3.11／3.13 的回归结果见[对应提交的 CI](https://github.com/kitegs/codex-resource-coordinator/actions)。Windows 原生作业监护和重启恢复不能当作 Linux 已具备的能力。

在这个独立仓库内创建环境，不要把插件代码放进游戏源码仓库：

```powershell
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -e '.[test]'
./.venv/Scripts/python.exe -m pytest -q
./.venv/Scripts/python.exe scripts/prepare_install.py --python .venv/Scripts/python.exe --target .local/marketplace-v0.5.2
```

Linux 对应解释器为 `.venv/bin/python`。准备脚本拒绝覆盖已有目标，生成独立安装副本，固定其 MCP 和提醒 Hook 使用的解释器；**不修改 Codex 设置、不启动服务、不重启客户端**。源码清单中的默认 `python` 仅适用于已安装依赖的同一解释器，不要误用另一个 Python。

等其他对话到稳定点后，再注册准备好的本地市场：

```text
codex plugin marketplace add <准备脚本返回的marketplace绝对路径>
```

在 Codex 插件目录选择 Resource Coordination → resource-coordinator。需要客户端刷新/重启时先结束或交接活动任务，不能为了安装强行退出它们。Hook 需独立审阅和信任；默认只有 SessionStart 状态提醒，**没有全局 PreToolUse 拦截**。安装文件不等于已经在运行中的对话生效。

MCP 也可直接连接准备副本的 `scripts/server.py`，解释器仍使用上面的独立环境。直接配置 MCP 与通过插件配置二选一，避免重复工具/进程。

## 共享状态

### 打开本机面板

```powershell
./.venv/Scripts/python.exe -B plugins/resource-coordinator/scripts/coordinate.py panel --port 0
# 使用输出的完整 local_url（含片段凭据），不是只复制主机地址。
# 指定另一状态库时，把 --db <绝对路径> 放在 panel 之前。
```

面板仅监听 `127.0.0.1`，没有修改／取消／终止操作；不创建或升级状态库。API 需要随机访问凭据，拒绝其他来源，不公开本机文件。每 5 秒读取状态库，页面隐藏时暂停刷新；**不自动调用宿主工具监控其他对话**。默认无有效访问 30 分钟后退出，也可在自己的面板终端按 Ctrl+C 正常停止。

未初始化、过期、连接失败和“仅观察未接入”会明确显示，不使用虚构进度。访问凭据只用于本机页面读取，不应复制到报告或 GitHub。升级前检查旧 MCP 是否活动；CLI 安装可能清理旧版本缓存，保留旧安装源用于回滚，不把缓存当备份。

默认数据库在：

- Windows：`%LOCALAPPDATA%/CodexResourceCoordinator/state.sqlite3`
- 其他系统：`$XDG_STATE_HOME/CodexResourceCoordinator/state.sqlite3`，未设置则为用户 `.local/state`。

可用 `COORDINATOR_DB` 或 CLI `--db` 指定**同一个绝对本地磁盘路径**。不得给每个工作树、插件缓存或对话分配不同数据库来假装协调；不支持网络共享磁盘。数据库、WAL、报告和本机路径不应提交到 GitHub。状态保留直到你自行制定清理政策；本版不自动删除历史。

## 怎么使用

在 Codex 中用 `$resource-coordination`。建议先让两个测试对话在测试资源上申请，不要立即接管已运行的 UE。旧任务必须由其负责人明确交接。

MCP 工具有 23 个（新增 recover_managed_operation，仅核查、不执行命令）；CLI后备不要求当前对话已经载入这些工具：

- 原子占用：`queue_status`、`request_resources`、`set_request_dependencies`、`acquire_resources`、`begin_operation`、`renew_lease`、`complete_operation`、`cancel_waiting`、`reconcile_expired`、`plan_ue_resources`。
- 共享状态：`register_coordination_chat`、`report_development_status`、`import_codex_status_snapshot`、`coordination_board`、`coordination_changes`、`acknowledge_coordination_changes`。
- 交接通知：`configure_release_notifications`、`release_notifications`、`claim_release_notification`、`acknowledge_release_notification`、`retry_failed_release_notification`、`archive_obsolete_release_notification`。

服务器不提供任意命令执行、杀进程、Git 集成或消息发送能力。

### 谁提醒下一位，失败怎么办？

```text
登记并获准参与 → 请求资源／排队 → 原子占用 → 工作与记录进程结束
  → 真实释放＋持久化下一候选通知（同一事务）
  → 完成方领取通知 → 宿主发送一次 → 记录真实回执
  → 接收方查队列、重新申请 → 执行前检查 → 原任务内继续工作
```

同一项目、启用提醒、有受影响且当前满足条件的等待请求，才生成通知。多个共享读取者可同时成为候选；独占请求仍按队列顺序。不因对话回复结束、租期过期或未核查的进程消失而发出“轮到你”。

完成方在结束前查询 `release_notifications`，先核实用户对接收者的授权，再领取 eligible 的 pending 通知；领取后最多调用一次原生 `send_message_to_thread`，再写回真实结果。原子领取防止两个完成方同时代发。通知不会替接收方占位或授权新操作，也不要求对方自动回复。

| 状态 | 处理 |
| --- | --- |
| 待发送 `pending` | 已落盘、尚未发；原完成方退出后，其他获准参与者可接手 |
| 发送中 `sending` | 已领取；领取超时后按结果不明展示，不自动重新分配 |
| 投递受理 `delivered` | 宿主成功回执匹配目标；不证明已读、开始执行或取得资源 |
| 明确未发送 `failed` | 保留原因；修复工具／授权等问题并确认未发送后，可显式重新排队 |
| 结果不明 `uncertain` | 可能已发出；核对原回执，不盲目重发或改用另一通道补发 |
| 已失效 `obsolete` | 领取前目标已不再等待；显式归档、保留历史，未发送，也不计作待处理 |

普通队列查询是兜底。**若所有对话都已停止，本版没有后台服务独立唤醒它们。** 官方也提供 [`codex queue`](https://learn.chatgpt.com/docs/developer-commands) 给既有会话排消息，但该通道未在本插件内接入／验证，不能把“已入队”当“已处理”。

启用记录只是协作范围，不是用户授权的独立证明；本机受信任参与者仍需遵守宿主权限。通知回执和租约令牌不要写入 Git。详见[验收边界](ACCEPTANCE.md)。

### 查看其他对话与安排下一步

1. 注册明确参与同一项目的对话。`report_development_status` 只上报本对话的工作和证据；不能替其他人声明验收通过。
2. 需要新鲜状态时，调用宿主已有的 `wait_threads`/`read_thread`，将紧凑结果及实际采集时间传给 `import_codex_status_snapshot`。本地 MCP 本身不会自动调用宿主工具，也不读 Codex 内部数据库。
3. `coordination_board` 显示自报开发状态、宿主／本轮状态、来源与更新时间、责任范围／版本／证据指针、阻塞原因和队列候选顺序。证据是声明，插件不自动核实日志或执行其引用。
4. 请求可以附 `depends_on` 成功依赖。只认前置请求 `completed`，不把失败、取消或对话本轮结束当成功。拒绝依赖环；没满足依赖的请求不挡住可执行的前置任务。
5. 用变更游标只看相关项目的新变化，跨项目但实际冲突的资源释放仍可见。处理后确认 `next_cursor`，恢复对话不重复提醒。无相关变化保持安静，不反复催问；提醒和发消息是两回事。

CLI 的 `register-chat`／`report-status --input <JSON文件或->`／`board`／`changes`／`ack-changes` 覆盖登记、自己上报及低噪声读取；`ingest-status --snapshot <紧凑JSON文件> --observed-at <采集时Unix秒>` 导入已授权的状态快照。`notifications` 提供configure／list／claim／ack／retry／archive，但不自行发送消息。[完整CLI说明](plugins/resource-coordinator/docs/CLI_FALLBACK.md)。运行数据只留本机，不上传本仓库。

升级需在各参与对话到稳定点后，结束旧 MCP 实例并统一重载 0.2+，再依赖新排序规则。数据库为加表升级，保留旧请求。旧插件不能被默认为已更新，不因安装自动接管已有进程。

命令行例子（在 PowerShell 中）：

```powershell
$coord = 'plugins/resource-coordinator/scripts/coordinate.py'
./.venv/Scripts/python.exe $coord request --owner demo-chat --purpose 'small foreground test' --resources '[{"key":"demo:build","mode":"exclusive"}]'
# 上一步返回请求 ID。run 负责申请许可及心跳，不能先手动 acquire 再交给 run。
./.venv/Scripts/python.exe $coord run --request <ID> --owner demo-chat -- python -c 'print("hello")'
./.venv/Scripts/python.exe $coord status
```

返回码：`0` 成功；`3` 排队，命令**没有启动**；其他为命令失败或协调错误，先查请求状态，不要自动重跑。

命令仍须通过正常执行工具及其权限审批。**0.5 默认 Windows 10+ Job 监护**：普通监护子进程从启动时归组，等整组结束才释放；重复 run 不重启。客户端中断不等于监护结束，宿主取消仍然有效。组名查不到、权限不足或证据丢失时不靠超时回收。新增 recover／watch 只核查／接续监测，不重跑命令。[完整规则、用法与边界](plugins/resource-coordinator/docs/SUPERVISION_05.md)。

非 Windows 不静默降级；可显式 `--tracking observed` 使用旧轮询，但无安全自动恢复保证。不追踪 WMI、服务、计划任务或远程代理另起的工作；不限制 CPU/显存。不得用旧客户端手动完成／恢复 0.5 票据。面板显示同资源前方等待数和阻塞者，不估算 ETA。

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

安装后可用 `scripts/smoke_install.py --plugin <安装副本目录> --db <全新的隔离数据库绝对路径>` 检查真实 MCP 通信、23 个工具、成功依赖、状态上报、变更确认及模拟消息回执。它拒绝覆盖已有数据库，不启动 UE、不向真实对话发测试消息，也不证明当前 Codex 对话已加载插件。[验收记录](ACCEPTANCE.md) 区分自动测试、安装副本与宿主实际接入。

尚不具备：自动接管旧会话、后台原生事件订阅、操作系统级强制互斥、完备命令解析、任意后台进程追踪、跨机器锁服务、自动抢占、GPU 预算、多人安全认证。状态桥接和里程碑上报仍需参与者执行。全局 Hook 不是可靠的 fail-closed 边界；本版不假装提供。

许可：MIT。每次提交前检查没有带入项目素材、日志、令牌和私人路径。

官方接入参考：[插件打包](https://developers.openai.com/plugins/build/plugins)、[MCP](https://learn.chatgpt.com/docs/extend/mcp)、[Hooks 的覆盖与限制](https://learn.chatgpt.com/docs/hooks)。
