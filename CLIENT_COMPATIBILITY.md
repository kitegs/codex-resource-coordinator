# 跨客户端接入

协调的是工具操作，不是模型推理。模型本身不能直接取得本机资源；客户端需提供
本机命令执行或 stdio MCP 能力，并让参与者遵守相同的资源约定。

## 通用 CLI

在本仓库建立 Python 3.11+ 环境，并安装已声明的依赖：

```text
python -m venv .venv
<venv-python> -m pip install -e .
<venv-python> -B plugins/resource-coordinator/scripts/coordinate.py --help
<venv-python> -B plugins/resource-coordinator/scripts/coordinate.py --db <absolute-local-db> status
```

`<venv-python>` 和 `<absolute-local-db>` 是要替换的占位符，不是可直接执行的路径。
Windows 解释器通常在 `.venv/Scripts/python.exe`，Linux 在 `.venv/bin/python`。
也可使用安装后的 `codex-coordinate` 命令。程序名称不表示它需要 Codex 模型或账号。

不同客户端必须显式指向同一个本地数据库，并使用一致的资源键。不同项目可共用库；
同一 GPU、设备或输出目录不得用不同别名。私有令牌回执放在用户私有目录，不放代码库。
完整申请、执行、完成和恢复规则见[CLI 流程](plugins/resource-coordinator/docs/CLI_FALLBACK.md)。

## 标准 MCP stdio

下面是通用字段示意，不保证每个客户端使用相同的配置外层结构：

```json
{
  "mcpServers": {
    "resource-coordinator": {
      "command": "<absolute-venv-python>",
      "args": ["<absolute-checkout>/plugins/resource-coordinator/scripts/server.py"],
      "env": {"COORDINATOR_DB": "<absolute-local-db>"}
    }
  }
}
```

将占位符替换为自己机器上的绝对路径，按客户端官方文档选择配置位置。
不要原样复制插件清单中的 `${PLUGIN_ROOT}`：它由插件宿主解析，通用 MCP 客户端
不一定支持。Python 环境需预先安装依赖；服务启动不会自动安装软件。

标准握手、工具发现及队列往返已通过独立 Python MCP 客户端验证，服务有 23 个工具。
尚未逐一验收 Claude、Cursor、其他商业客户端及不同模型的实际操作纪律，因此这里只
声明协议层可接入，不声明开箱即用。CLI 是不依赖这些客户端专用配置的替代入口。

## 需要宿主适配的部分

- 对话状态快照不会自动收集。其他宿主需要提供状态来源，或只使用参与者自报状态。
- 交接发件箱只记录待通知者。当前 `host_arguments` 指向 Codex 原生消息接口；
  其他宿主不能原样执行，需按真实消息回执适配，或保留查询队列的方式。
- 没有独立后台唤醒服务，不会因接入 MCP 就自动提醒暂停／结束的对话。
- Codex 的插件清单、SessionStart Hook、信任与工具审批不是通用客户端配置。
- 前台 Windows 10+ 作业监护与重启恢复是操作系统特定能力。非 Windows 需显式
  `--tracking observed`，不能宣传为同等安全自动恢复。Windows 原生测试不替代其他平台验收。

新客户端先使用全新的隔离测试库和虚构资源完成以下检查，再接真实共享库：两参与者
竞争同资源、互不冲突资源并行、等待时命令不启动、失败/中断不误报成功、正常结束释放、
工具结果与面板不泄露令牌。消息投递和自动化动作需另行授权与验收。

协议参考：[MCP Python SDK stdio 客户端](https://py.sdk.modelcontextprotocol.io/client/transports/)。

## 数据边界

插件没有自带模型 API、遥测或自动上传服务。但宿主可能把 MCP／CLI 输出传给所用的
模型服务；这些输出可能包含你主动登记的路径、资源名、状态摘要和证据引用。
不要在目的、摘要、资源名、命令参数或报告里放凭据。状态库和回执只留本机，面板不要
代理到公网。进一步限制见 [SECURITY.md](SECURITY.md)。
