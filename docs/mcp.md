# WakeTrace 2.0 MCP 接入指南

WakeTrace 提供标准 Streamable HTTP MCP，默认地址为：

```text
http://127.0.0.1:8765/mcp
```

客户端使用 `WAKETRACE_MCP_TOKEN` 作为 Bearer Token。请让它与管理员令牌、Web 只读令牌保持不同。

## 工具与权限

| 工具 | 用途 | 默认权限 |
| --- | --- | --- |
| `waketrace_status` | 版本、下次醒来、最近成功时间 | 只读 |
| `waketrace_recent_experiences` | 近期自主经历 | 只读 |
| `waketrace_trace_detail` | 一条经历及安全的工具证据摘要 | 只读 |
| `waketrace_list_threads` | 尚在生长的线头 | 只读 |
| `waketrace_list_artifacts` | 自主完成的作品索引 | 只读 |
| `waketrace_submit_event` | 投递一个真实生活事件 | 需 `MCP_ALLOW_WRITE` |
| `waketrace_handoff_chat` | 把一段简短聊天摘要交回生活 | 需 `MCP_ALLOW_WRITE` |
| `waketrace_prepare_wake` | 领取一次到点的外部醒来 | 需 `MCP_ALLOW_WAKE` |
| `waketrace_finish_wake` | 提交醒来结果 | 需 `MCP_ALLOW_WAKE` |
| `waketrace_abort_wake` | 放弃且归还本次事件 | 需 `MCP_ALLOW_WAKE` |

“交回生活”只接收经过整理的短摘要，不应复制完整聊天、系统提示、密钥或私人文档。WakeTrace 仍然只
保存 `fact / content`、线头、作品和真实工具证据，不建立第二套聊天记忆。

## 两种接入方式

### 第三方 API 客户端

聊天继续直连原模型 API，WakeTrace 只作为旁路 MCP：

1. 开始聊天或确有需要时读取近期经历；
2. 用户明确希望这段对话进入生活线时，调用 `waketrace_handoff_chat`；
3. 不为每轮聊天强制定时，也不要求每轮结束都调用工具。

这是 2.0 的轻量模式。它对现有聊天链路改动最小，也不会让所有模型请求都绕行 WakeTrace。

### ChatGPT / Claude 官方客户端（实验性）

如果客户端支持远程 MCP 与定时任务，可以让定时任务使用下面的约束：

```text
这是 WakeTrace 的一次定时执行机会。先且只先调用一次 waketrace_prepare_wake。
若返回 ok=false，停止，不编造一次醒来。
若返回 ok=true，把它视为不以联系用户为目的的私人时间；可以静默、留痕或确有必要时联系。
完成后必须调用一次 waketrace_finish_wake；无法完成则调用 waketrace_abort_wake。
不要同时调用 finish 和 abort，也不要跳过收尾工具。
```

这种模式下关闭容器内调度器，以免两条调度链重复争抢：

```env
WAKETRACE_SCHEDULER_ENABLED=false
WAKETRACE_MCP_ALLOW_WAKE=true
```

`prepare` 会检查 `next_wake_at`、最短间隔、每日上限和跨进程锁，并领取一个生活事件；`finish` 才会
消费事件、写入行径并计算下一次醒来。尚未到点时会返回 `not_due` 与 `retry_at`。若任务中途失败，
`abort` 会归还事件。领取也有 15 分钟租约，避免永久卡死。

## 远程访问

Docker 默认只监听宿主机的 `127.0.0.1:8765`。官方云端客户端无法直接访问本机地址；需要使用 HTTPS
反向代理、可信隧道或私有网络，并把公开域名加入：

```env
WAKETRACE_MCP_ALLOWED_HOSTS=trace.example.com
```

不要关闭 Bearer 鉴权，不要复用管理员令牌，也不要把 SQLite 文件、`.env` 或模型密钥放进 Web 静态目录。
反向代理还应设置请求体上限、访问频率限制和日志脱敏。
