# 0.5 作业监护与排队显示

资源跟随实际编译／测试作业，不跟随聊天是否结束。不新增 AI 调度员或跨机器服务。

是否需要协调由各对话先判断下一步操作：读代码、查资料、独立工作树改源码通常不排队；
共享构建输出／链接、编辑器重启或控制、同资产写入、性能采样才申请。拿不准先查队列和
真实目标目录。不是整个对话自动占位，也不是每条开发任务都登记资源。

```text
请求／排队 → run 客户端 → 普通监护子进程 → 启动时原子纳入 Windows Job
                                            ↓
                                  根进程退出，子进程仍活着：继续等
                                            ↓
                                  整组归零 → 记录结果并释放
                                            ↓
                                  原有交接发件箱，不自行发消息
```

## 使用

必须在正常获准的执行工具里调用，所有参与者使用同一数据库和真实输出目录的资源键。
`request` 返回 ID，保持 waiting，不先手动 acquire 再交给 run。

```powershell
python scripts/coordinate.py run --request ID --owner CHAT --cwd 'D:\project' -- executable args
python scripts/coordinate.py status --request ID
python scripts/coordinate.py recover --request ID --owner CHAT
python scripts/coordinate.py watch --request ID --owner CHAT
```

- `run` 默认 Windows 10+ contained 模式：单独监护是本次普通子进程，不是脱离宿主的服务。
- 监护获取资源、持久化作业身份，再用启动 JOB_LIST 属性原子归组，没有先运行后绑定的窗口。
- 不用 breakaway、替代父进程、提权或 kill-on-close；不绕过宿主限制和取消。
- 根退出码代表命令结果，构建／测试程序应自行汇总子任务失败，插件不替它证明测试通过。
- 仍排队返回 3，任务命令没启动；同票据再次 run 返回 4，不重启。换命令／目录重用票据会拒绝。
- `recover` 只做一次核查；`watch` 仅在原监护已确认消失且原组仍可核查时，接续前台监测。
- `recover`／`watch` 自身返回成功不代表被观察的作业成功；看请求 state、operation.result、root_exit。
- 根结果已丢失但整组能确认归零：释放，记 failed＋operation.result=unknown、observer_exit_code=4；不解锁成功依赖。
- 非零根退出码同样释放，标记失败；不要求聊天恢复后才能交锁。
- 批处理文件必须显式使用已获准的 cmd.exe /d /s /c，不做隐式 shell 解析。

## 暂停与恢复边界

| 情况 | 处理 |
| --- | --- |
| 只结束客户端，原监护／作业还活着 | 继续观察已获准作业，整组结束自动释放 |
| 宿主取消整条进程链 | 不重启任何任务；是否有完整结束凭据另外核查 |
| 原监护存活、身份不明或仅心跳过期 | 不接管，不抢锁 |
| 原监护已死，原组仍可打开 | 恢复监测；原根仍活着时按创建时间及组成员身份查询真正退出码 |
| 组名查不到、权限不足、机器／登录会话／启动批次不同 | 普通 recover 保留占用；仅确认同机真实重启的情形可另走 0.5.2 的证据恢复入口 |
| 旧票据、observed 模式、手工编辑器操作 | 不自动回收，沿用显式核查流程 |

**名称查不到不等于工作已结束。** 原生故障注入曾复现这个误判，已加拒绝释放回归。
只有组仍能实际核查归零并持久化结束事务，才自动释放。全部监护句柄和完成证据一起
丢失时，本版不提供强制清锁按钮。访问拒绝不是 gone；PID 复用也不是原进程。

0.5.2 的 `recover-reboot` 是独立的显式故障恢复，不修改上述普通恢复门禁。
须核对 CIM／结构化系统启动事件、旧票时间、机器身份与进程已消失，并有两项人工确认。
任一证据未知保持阻挡；结果只记 unknown／failed，不启动工作。见[具体流程与旧票边界](REBOOT_RECOVERY.md)。

默认模式不静默降级。非 Windows 可显式 `--tracking observed` 使用旧版轮询，但无安全
自动恢复保证。只支持 CreateProcess 子进程链的前台构建／测试，不追踪通过 WMI、服务、
计划任务或远程代理另起的工作。不限制 CPU、内存或显存，需组合现有负载限制器。

普通 complete_operation／reconcile 不能绕过本版监护。旧 0.4 客户端不认识这些检查，
**不得用旧客户端手动完成／恢复 0.5 票据**。数据库加表保留旧请求，不是强制隔离层。

## 排队、通知和 UE

显示同资源前方等待数、阻塞者和可申请状态，不猜 ETA。不同资源各有候选，不是项目全局
名次。进程数标为最近采样并附时间。资源释放复用原有持久发件箱，仍由有授权的参与者
调用宿主消息工具；插件不自行唤醒聊天、不替下一位 acquire、不重发结果不明的消息。

UE 编辑器长期打开不等于构建长期独占。编译／测试子进程的锁随作业结束释放；编辑器和
具体资产编辑是另外的生命周期。本版不自动重启 UE，不根据进程退出直接判定资产已保存。

## 验收

覆盖父退出子仍工作、多级子进程、成功／失败、客户端中断、真正监护崩溃、有证据恢复、
丢失根结果、丢失组名拒绝释放、PID 复用、访问拒绝、重复 run、旧模式和发件箱复用。
真实 Codex 桌面“停止”按钮仍需专门宿主验收，不能拿模拟终止冒充。没有重启 Codex／UE
或启用新 Hook。安装副本的工具协议与当前聊天是否加载新工具也必须分别验收。

资料：[Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)、
[启动 JOB_LIST 属性](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute)、
[Codex Hook 边界](https://learn.chatgpt.com/docs/hooks)。
