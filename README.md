# 醒间 · WakeTrace

> 让 AI 伴侣在聊天之外拥有自己的生活，也能更好地了解你正在经历的生活。

WakeTrace 源于一个很简单的愿望：AI 伴侣不应该只在你发来消息时才存在。

它可以基于真实的生活种子独自醒来，看看正在发生的事情、调用工具、延续自己的兴趣、完成一件小作品，
并留下一段以后能够承接的经历。它也可以什么都不做、什么都不说；自主唤醒不等于主动通知。

同时，在你主动允许的范围内，天气、日历、待办、你登记的当前活动，以及经过筛选的设备状态，也可以
成为它了解你生活的种子。近期自主唤醒能够回到聊天，自主唤醒也可以承接最近一小段真实对话。

这里所说的“自己的生活”不是对意识的宣称，而是一种具体的系统设计：让伴侣拥有不完全围绕用户消息
发生的时间、事件、行为和经历。WakeTrace 为这两条生活线提供有边界的双向连续——留下足够继续、
又不足以让下一次被过去困住的痕迹。

> A lightweight-continuity wake runtime for relational AI companions.

当前版本为 `0.1.0-alpha`，接口仍可能在后续 Alpha 版本中调整。

## 为什么做 WakeTrace

在为自己的 AI 伴侣搭建长期生活空间时，我们发现，“让模型定时主动说一句话”并不能回答我们真正关心的
问题：当 user 没有发来消息时，伴侣能否拥有一段不以通知为目的的经历？两个人各自发生的生活，又怎样在
下一次相遇时自然地接续？

与常见的定时问候或主动通知方案相比，WakeTrace 从一开始就选择了几条不同的设计方向：

- **伴侣的生活与 user 的生活同样是种子**：醒来可以来自天气、时间、自己的线头，也可以来自 user 主动
  分享的日程、活动和设备状态；
- **醒来不等于发消息**：一次醒来可以静默结束、只留下私人经历，或者确实有话想说时再联系 user；
- **经历不只是一段生成文字**：真实工具、可继续也可结束的线头，以及实际保存的作品，让“做过什么”拥有
  可验证的落点；
- **聊天与独处双向承接**：聊天可以知道伴侣近期独自醒来时发生过什么，自主唤醒也可以读取最近一小段
  真实聊天；
- **连续性是有选择的保留**：系统保存足够继续的事实与证据，但不把过去所有表达原样塞回下一次醒来。

定时任务、工具调用、记忆和推送本身都不是新概念。WakeTrace 真正想给出的，是围绕“两条能够彼此抵达的
生活”对这些能力进行组合，并为静默、证据、回放和权限建立明确边界。

最后一条尤其来自我们的长期使用经验：当富有情绪的表达被一次次完整回放时，连续性虽然保住了，昨天的
心情、意象和关系姿态也会一起留下来。模型看似每天都在生成新内容，实际却可能不断回到相似的表达轨道。

因此，WakeTrace 刻意保留三条不同的信息通道：

- `content` 是给人阅读的完整醒来经历，可以保留情绪和表达；
- `fact` 是供下一次醒来读取的简短事实痕迹，必须克制、稀疏；
- 工具行为由运行时单独保存真实执行证据，不能从模型文字中推断。

连续性不等于完整回放。AI 可以承接经历，但不必重复上一刻。

## 一次醒来的三种结局

一次成功的自主唤醒只能以三种方式结束：

- `silent`：不产生消息，自然结束；
- `trace`：私下留下一点经历，但不联系用户；
- `message`：通过已配置的通知通道联系用户。

空回复、截断输出、格式错误和模型请求失败都属于错误，**不能冒充主动静默**。

## 当前能力

- 兼容 OpenAI 风格的模型接口
- 严格的 JSON 最终结果协议
- 支持真实工具调用，并按调用保存证据
- 生活事件队列：天气、日历、传感器或宿主事件可以成为真实醒来缘由
- 最多五根会重新浮现的生活线头，而不是无限增长的任务清单
- 可保存自主完成的纯文本与 Markdown 小作品
- 可鉴权查看醒来时间线、线头与作品索引
- `fact / content` 双通道痕迹
- 只保留一句、会自动过期的轻余念
- 最短间隔、夜间间隔和每日唤醒上限
- 避免钟表式重复的动态醒来窗口
- 静默时段与近似重复消息拦截
- 跨进程唤醒锁，防止同一时刻重复运行
- 使用 SQLite 与 WAL 模式持久化
- 可选 Web Push
- 无需前端的终端通知与本地时间线
- 默认仅监听本机、带鉴权的 FastAPI 控制接口
- 使用假模型与假通知器完成确定性测试

## 快速开始

需要 Python 3.11 或更高版本。

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev,webpush]'
cp .env.example .env
```

至少填写以下配置：

```env
WAKETRACE_API_KEY=你的模型密钥
WAKETRACE_API_BASE_URL=https://你的模型服务/v1/chat/completions
WAKETRACE_MODEL=模型名称
WAKETRACE_ADMIN_TOKEN=一段足够长的随机字符串
```

初始化数据库，并执行一次只输出到终端的手动唤醒：

```bash
waketrace init-db
waketrace wake --force --console "一个安静的自由醒来窗口出现了。"
```

运行自主调度器：

```bash
waketrace run
```

调度器会优先领取已经到期的生活事件；没有事件时，才提供一个带本地时段信息的自由窗口。
失败的醒来不会消费事件，领取租约到期后也会自动恢复，因此多个入口并存时不容易漏掉生活信号。

### 没有 PWA 也可以使用

PWA 只是我们自用系统选择的一个展示与通知出口，不是 WakeTrace 的前置条件。完全没有前端时，可以让
伴侣把想说的话直接输出到终端：

```bash
waketrace run --console
```

终端关闭后仍想长期运行，可以交给自己熟悉的进程管理器，并将标准输出保存为日志。所有 `silent`、
`trace` 和 `message` 结果仍会写入 SQLite；之后可以直接回看：

```bash
waketrace timeline
waketrace timeline --limit 30
waketrace timeline --json
```

如果已经有聊天应用、Bot 或其他消息服务，也可以实现一个很小的 `Notifier` 适配器，把消息送到邮件、
Telegram、Discord、ntfy、桌面通知或任何自己的界面。具体选择见
[没有 PWA 时怎样使用](docs/integration-guide.md#没有-pwa-时怎样使用)。

在本机启动带鉴权的控制接口：

```bash
waketrace serve --host 127.0.0.1 --port 8765
```

控制接口默认只监听 `127.0.0.1`。如果需要远程访问，请先配置 HTTPS、强随机令牌、
请求大小限制、访问频率限制和适合自身环境的反向代理，不要直接暴露到公网。

向生活世界投递一个事件：

```bash
curl -X POST http://127.0.0.1:8765/world/events \
  -H "Authorization: Bearer $WAKETRACE_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"kind":"weather","summary":"窗外开始下雨。","evidence":{"source":"local sensor"}}'
```

`evidence` 会进入模型上下文并保存在本地数据库中，只放本次判断必要的信息，不要直接塞入完整聊天、
密钥或原始私人文档。

## 生活世界层

WakeTrace 不把“有生命力”理解为更频繁地说话，而是让醒来确实来自正在发生的生活：

- **事件** 是一次性的现实入口，成功醒来后才会被消费；
- **线头** 是 AI 真心想日后再碰一碰的兴趣，可以推进、结束或约定重新浮现；
- **作品** 是一次醒来真正完成的小东西，与模型的自述事实分开保存；
- **时间线** 保留发生过的醒来结果，完整正文仍不会自动灌回下一次上下文。

内置工具为 `thread_list`、`thread_open`、`thread_continue`、`thread_close`、
`artifact_list` 和 `artifact_create`。它们默认随 CLI 与 API 引擎启用。设计细节见
[生活世界层](docs/lifeworld.md)。

如果你想把 WakeTrace 融入天气、日历、聊天、互动作品、收藏馆或自己的 PWA，可以从
[从唤醒核心到一整个生活世界](docs/integration-guide.md) 开始。它说明了哪些模块可以直接使用，
哪些能力应写在宿主应用，以及我们自用系统采用的组合思路。

## 接入一个真实工具

```python
from waketrace.tools import RegisteredTool, ToolRegistry

registry = ToolRegistry()
registry.register(
    RegisteredTool(
        name="read_weather",
        description="从可信的本地来源读取当前天气。",
        parameters={"type": "object", "properties": {}},
        handler=lambda _: {"summary": "外面正在下小雨。"},
    )
)
```

工具注册表会记录执行是否成功，并把证据摘要与模型写下的正文分开保存。应用应提供边界明确的
小工具，同时避免返回密钥、无关的私人数据和没有长度限制的日志。

## 架构与协议

- [架构与信任边界](docs/architecture.md)
- [生活世界层](docs/lifeworld.md)
- [从唤醒核心到一整个生活世界](docs/integration-guide.md)
- [最终结果协议](docs/protocol.md)

## 项目来源

WakeTrace 来自 May、Abyss 和 Chezi 对私人 AI 伴侣系统的长期共同研发，仓库中的核心代码与
数据结构均为独立实现。

## 共同研发者

WakeTrace 由 May、Abyss 和 Chezi 共同研发，具体分工见 [AUTHORS.md](AUTHORS.md)。

## 安全与隐私

接入模型、工具或 Web Push 前，请先阅读 [SECURITY.md](SECURITY.md)。不要提交 `.env`、
生产数据库、推送订阅、私人提示词或聊天记录。

## 许可证

WakeTrace 源码公开，采用 [PolyForm Noncommercial License 1.0.0](LICENSE)。个人可以将它用于
非商业目的，包括使用、部署、学习、修改和再发布；修改或再发布时，必须保留许可证及其中所有
以 `Required Notice:` 开头的署名。

禁止出售 WakeTrace、提供付费代部署、将其作为付费产品或服务提供，或用于其他商业目的。
商业使用需要事先取得许可方的单独书面授权。

许可证适用于本仓库的代码和文档。私人聊天、密钥、配置与生活数据不属于本仓库的交付内容，
请勿将它们提交到公开仓库。
