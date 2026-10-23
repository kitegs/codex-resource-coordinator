# 跨重启故障恢复（0.5.2 CLI）

用途：Windows 确实重启后，旧 contained 作业无法再打开，但占用仍保留。
不是强制清锁、超时抢占、任意进程恢复或测试成功确认。不结束 UE、不启动命令、不替下一位拿资源。

## 先查，再明确确认

使用同一数据库和新的独立准备副本，不覆盖正在运行的旧副本：

```powershell
& $python -X utf8 -B $coord recover-reboot --request '<旧票ID>' --owner '<原负责人ID>' --check-only
& $python -X utf8 -B $coord recover-reboot --request '<旧票ID>' --owner '<原负责人ID>' --confirmed-reboot --confirmed-same-machine --note '<用户授权及实际重启核查来源>'
```

check-only 返回 eligible 不表示释放；执行入口必须有真实用户授权及两项显式确认。
owner 是协作身份，不是系统账户认证，不能冒充其他人的同意。维护者经用户批准可代原负责人执行限定旧票恢复。

## 每项都需成立

1. 原票归属吻合，仍属未结束的 managed 作业。普通手动／observed 票仍用原核查流程。
2. 当前主机名吻合。0.5.2 新作业还记录 Windows MachineGuid 的 SHA256 指纹，恢复时须匹配，不保留原始 MachineGuid。
3. 从本机固定只读查询获取 CIM LastBootUpTime 与 System／Kernel-General 事件12的结构化 StartTime；不解析本地化 Message。
4. 当前 CIM、普通作用域启动时间与当前启动事件相符；旧作用域时间须对应另一次、更早的系统启动事件。只换会话或调时钟不成立。
5. 请求、监护、根进程与作业记录时间均落在旧启动之后、当前启动之前；监护／根按 PID＋创建时间查为 gone。访问拒绝／unknown 保留阻挡。
6. 进入单一写事务后重新核对记录、当前作用域和机器指纹；竞态变化则回滚，不盲目重试。

时间匹配允许2秒的旧版四舍五入差异，不用该容差把同一次启动解释为重启。
只读取最近128条系统启动记录；旧记录已轮换、日志无权限、CIM不符或其他不确定情形都保持阻挡。

旧版票没有持久机器指纹，不能事后补称有强身份绑定：除同主机名／历史事件／时间匹配之外，
还依赖操作者明确确认本库来自同机。核查结果会标 legacy_host_binding。跨机器复制的旧库若同机来源不明，不能执行。

## 结算与留存

同一事务将原请求置为 failed、作业结果置为 unknown、标记 interrupted_by_verified_reboot，
保存核查证据、原负责人、人工说明和恢复时间，撤销旧租约，并沿原发件箱挑选等待者。
已记录的根退出码保留为历史，不用它证明子进程全部成功；成功依赖仍不解锁。
重复调用不会再次释放或重发通知。消息投递、重新申请、启动 UE 和性能测试仍是分别授权的步骤。

只加两张辅助表，保留原队列／协议版本；旧版不能执行新恢复，但其普通管理入口仍会拒绝绕过 managed 作业。
MCP 工具数不变；本补丁不要求重启 Codex、重载 MCP 或覆盖旧缓存。

## 验证边界

回归用合成启动记录模拟不同启动、故障与竞态；本机原生检查只读取启动日志。
本轮不为测试主动重启 Windows／Codex／UE，也不把模拟启动当真实断电验收。

依据：[Win32_OperatingSystem](https://learn.microsoft.com/en-us/windows/win32/cimwin32prov/win32-operatingsystem)、
[Get-WinEvent](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.diagnostics/get-winevent)、
[Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)。
