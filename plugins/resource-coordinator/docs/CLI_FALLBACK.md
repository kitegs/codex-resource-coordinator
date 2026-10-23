# CLI 后备流程（0.5.1，兼容 0.4.1 后备入口）

MCP 没有加载时使用本插件自带的 CLI，不是 OpenAI 官方协调服务。
两种入口调用同一套 Store／Board／Handoffs，必须指向同一个绝对本地数据库。
不重启 Codex，不修改或接管 UE；排到资源仍需原任务授权和执行前检查。

## 启动与退出码

在 PowerShell 7 中，把解释器和脚本替换成准备副本 `.mcp.json` 所指的真实解释器与脚本路径：

```powershell
$python = '<插件解释器绝对路径>'
$coord = '<准备或安装副本>/scripts/coordinate.py'
& $python -X utf8 -B $coord --help
& $python -X utf8 -B $coord board --project-key '同一个项目组'
& $python -X utf8 -B $coord status
```

省略 `--db` 时沿用系统默认库及 `COORDINATOR_DB`；如需指定，放在子命令之前：
`--db '<共同状态库绝对路径>'`。不得在每个工作树生成不同状态库。
文件／管道JSON为UTF-8，接受BOM；输出为UTF-8 JSON。
退出0只代表该命令成功，不代表提醒已发送或等待请求已取得占用。
`run`／`acquire` 退出3代表仍在等待、没有取得资源；`run` 此时没有启动子进程。普通参数错误退出2，业务／输入错误退出1。
前台程序非零退出码沿用原规则；先查状态，不自动重复运行。

0.5 的 run 默认 Windows 10+ 进程组监护，重复票据返回 4 且不重启。
recover／watch 只核查／接续监测，根结果丢失不算成功。完整规则见[作业监护](SUPERVISION_05.md)。
日常交接只需：真实释放 → 检查通知 → 领取并由宿主发送一次 → 记录结果；下一位仍须重新申请。

## 1. 登记和自己上报

```powershell
& $python -X utf8 -B $coord register-chat --chat '<本对话ID>' --label '负责模块' --project-key '同一个项目组' --host local
& $python -X utf8 -B $coord board --project-key '同一个项目组'
```

从该对话条目读取 `work_revision`。用实际ID／修订号构造JSON，不能替其他对话声称完成：

```json
{
  "chat_id": "chat-a",
  "reporter": "chat-a",
  "work_state": "working",
  "summary": "已完成源码，尚待运行验证",
  "expected_revision": 0,
  "next_step": "排队测试；失败会保留",
  "blockers": [],
  "worktree": "<独立工作树绝对路径>",
  "commit_id": "<实际提交>",
  "provenance": {"base_commit":"<基线>","dirty":true,"write_scope":["负责文件"],"evidence":[]}
}
```

```powershell
& $python -X utf8 -B $coord report-status --input '<UTF-8报告JSON文件>'
# 也支持把同一JSON经管道传入：report-status --input -
```

状态可选：`unknown / working / waiting / needs_input / ready_for_review / finished / paused`。
修订号冲突必须重新读取后合并，不能盲目加1重试；里程碑／阻塞时上报，不每轮刷屏。
`finished`只是自报，不自动释放资源，不等于用户验收。证据引用不是插件已经验证日志。

## 2. 查变化、确认游标与依赖

```powershell
& $python -X utf8 -B $coord changes --observer '<本对话ID>' --limit 50
& $python -X utf8 -B $coord ack-changes --observer '<本对话ID>' --cursor <已处理的next_cursor>
& $python -X utf8 -B $coord set-dependencies --request '<等待票ID>' --owner '<本对话ID>' --depends-on '["<前置票ID>"]'
```

变化为空就保持安静。只确认已经处理的游标；原有 `ingest-status --snapshot <紧凑JSON> --observed-at <真实采集Unix秒>` 可导入宿主原生快照，但CLI不自动监视聊天。
只在等待阶段改依赖；仅 `completed` 解锁，失败／取消留给负责人复核。沿用原有原子占用与依赖环检查。
申请和执行仍是 `request` → 等待中的票 → `run --request ID --owner OWNER -- <前台命令>`，不先手动取得租约再交给run。

## 2a. 手动编辑／GUI 操作：取得 → 开始 → 续期 → 完成

适用于已打开应用中的具体操作，例如编辑并保存某个蓝图；不是整个编辑器或整个对话长期占位。
先用 `request` 申请真实冲突的资源键，如 `asset:项目:蓝图路径`，取得票据ID。
编译和自动化测试仍优先使用 `run`，**两套生命周期不能混用**。

```powershell
# 只把路径放在命令行，绝不复制回执中的令牌；父目录需事先存在且私有。
$lease = '<私有目录>/blueprint-edit.lease.json'
& $python -X utf8 -B $coord acquire --request '<票据ID>' --owner '<本对话ID>' --lease-file $lease --lease-seconds 600
# 仅退出0且 lease_usable=true 才取得资源；随后仍须核查真实应用及操作权限。
& $python -X utf8 -B $coord begin --lease-file $lease
# 现在才进行已获准的蓝图编辑等操作；这些命令本身不操控应用。
& $python -X utf8 -B $coord renew --lease-file $lease --lease-seconds 600
# 确认本次具体操作已经保存／结束，没有仍在写入的工作，再完成并释放：
& $python -X utf8 -B $coord complete --lease-file $lease
# 若操作已经结束但失败／取消，改用 --outcome failed 或 --outcome cancelled。
```

- `acquire` 必须使用**不存在的新文件**，在取得资源前独占创建；已有文件、链接、目录或缺失父目录会拒绝，不覆盖、不先取得资源。业务拒绝可能留下空的预留文件。
- 退出3的回执**不含令牌，不能 begin／renew／complete**；先查队列，轮到后保持原票据、使用另一个新回执路径重试，不重复建票。不能把排队当作取得成功。
- 令牌仅存入回执；标准输出、队列、面板不返回令牌。回执绑定数据库、票据和拥有者。后续操作使用相同状态库与同一回执，不需要把令牌放入命令参数。回执不记录实时状态；当前截止时间和结果看 `status --request ID`。
- 在Windows中仍依赖父目录ACL，`*.lease.json` 的Git忽略规则不是访问保护。不要打印、分享或提交回执；成功结束后按私有凭据处理，不需要为了清理回执重新取得或释放资源。
- 默认租期120秒，`--lease-seconds` 范围10～3600秒；**没有自动续期**。分段操作并提前 `renew`，不要在长时间阻塞的工具调用中假定租约会续上。
- 过期仍阻挡，不能通过 `renew` 或重新 `acquire` 抢回。先确认真实工作已停止，再使用原有 `reconcile --request ID --owner OWNER --confirmed-stopped --note '<实际核查说明>'`，结果记为failed而非成功；需要继续时申请新票。
- 若取得资源后回执写入／刷盘失败，不启动操作、不自动重试或释放；保留文件，查状态并核查。丢失有效凭据需等待进入suspect并按上条恢复，不能凭“文件没写好”认定未占用。
- `begin` 只登记开始，不启动应用；重复开始会拒绝。`complete` 是对本次工作实际结束的明确声明，不自动保存资产，也不替你检查未登记的GUI工作；它沿用原Store检查有效租约及已记录进程。取消尚未开始的已占用操作可直接 `complete --outcome cancelled`。
- 完成后相同回执不能再开始、续期或释放；受监护 `run` 即使持有正确令牌，也不能借本入口提前完成，只能通过原监护／`watch`／`recover` 核查。没有新增强制清锁。
- 释放后继续下一节的通知流程；`release_handoff.pending_count` 不表示消息已经发送，下一对话也不会自动取得资源。

## 3. 释放提醒：查 → 领取 → 宿主发送 → 记录结果

只有用户已经批准的参与者才能启用；文字引用不替代真实授权：

```powershell
& $python -X utf8 -B $coord notifications configure --chat '<已获准对话ID>' --enable --authorization-reference '<真实授权的简短来源>'
& $python -X utf8 -B $coord notifications list --actor '<本对话ID>'
```

没有提醒或没有 eligible 的pending时，不要假定恰有一条、不要崩溃重发。普通队列查询仍可继续。
领取前核对消息权限与宿主 `send_message_to_thread` 是否可用；CLI自己绝不发送消息：

```powershell
& $python -X utf8 -B $coord notifications claim --notice '<提醒ID>' --actor '<本对话ID>' --claim-file '<私有目录>/notice.claim.json'
```

必须是不存在的新文件。文件已存在／父目录不存在时，在领取之前失败，不覆盖任何文件。
标准输出包含宿主调用参数，但不含claim token；秘密只放在此回执文件中，ack不用把token放进进程参数。
在Windows中继承父目录ACL，不承诺新建文件就自动获得私有ACL；必须选私有目录。
`*.claim.json` 已列入本仓库忽略规则，但不要依赖忽略规则代替保护，禁止打印或提交回执文件。
业务拒绝可能留下空的预留文件；不要把它当有效回执。持久化／磁盘错误时不自动重新领取；保留文件，先查状态，恢复不了就留待人工复核，使用普通队列兜底。

若返回 `deferred`，没有领取令牌，绝不发送或ack；重新查询队列。
若返回 `sending`，对话使用返回的 `host_arguments` 调用宿主消息工具**最多一次**，不改模型、任务范围或提示内容。
然后依据真实结果执行以下之一；命令只是写回结果，不证明已读、执行或获得资源：

```powershell
# 只有宿主成功回执的threadId与目标一致，才登记delivered：
& $python -X utf8 -B $coord notifications ack --claim-file '<私有回执文件>' --outcome delivered --receipt-thread-id '<宿主回执threadId>'
# 明确未发送（按实际原因选tool_unavailable/approval_denied/definitive_rejection）：
& $python -X utf8 -B $coord notifications ack --claim-file '<私有回执文件>' --outcome not_sent --result-code tool_unavailable
# 超时或不能确定是否发送：
& $python -X utf8 -B $coord notifications ack --claim-file '<私有回执文件>' --outcome uncertain --result-code transport_uncertain
```

回执文件绑定数据库、领取者与提醒，不能拿到另一个状态库重用。结果不明时保留原回执文件，以便后来核对真实回执；不要删token后换通道重发。
已明确未发送的failed，修复问题并再次确认未发送后，才可以显式重排：

```powershell
& $python -X utf8 -B $coord notifications retry --notice '<提醒ID>' --actor '<获准派发者ID>' --confirmed-not-sent
```

之后用一个**新的**私有回执文件领取。uncertain／sending不允许这样重试，旧token也不能确认新一次领取。

## 4. 已失效、未发送提醒的显式归档

```powershell
& $python -X utf8 -B $coord notifications archive --notice '<提醒ID>' --actor '<获准派发者ID>'
& $python -X utf8 -B $coord notifications list --actor '<本对话ID>' --all
```

仅允许pending且目标请求已不再waiting：变成 `obsolete`，保留历史，不伪造送达、不变更目标请求、不占用资源。重复归档幂等。
只是临时出现其他阻塞而仍waiting的提醒不能归档；sending／uncertain／failed／delivered也不能借此抹掉。
新面板不再把obsolete计入待处理；运行中的旧0.4面板不会热更新，需要以后在稳定点正常换到新版，不为此中断它。

## 升级和验收边界

0.5.2 补充 `recover-reboot --request ID --owner OWNER --check-only`，只检查跨重启证据；
真正释放还须 `--confirmed-reboot --confirmed-same-machine --note '<真实授权与核查来源>'`。
这不是强制清锁，缺少系统日志／同机身份／旧进程证据会拒绝，完整说明见[跨重启恢复](REBOOT_RECOVERY.md)。
结果为 failed／unknown，成功依赖继续阻塞；不会启动下一任务或操作 UE。

CLI可以直接使用经验证的新准备副本，无需当前聊天重新加载MCP。不要覆盖旧安装缓存：已有run包装器或其他对话可能还引用它。全体切换、MCP加载及Hook信任另在稳定点验收。
这套流程仍需要活跃对话处理通知；没有后台独立唤醒服务。不要在一次不确定的发送后改用 `codex queue`，那可能造成重复投递。
