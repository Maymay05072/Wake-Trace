# 醒间 · WakeTrace

> 让 AI 伴侣在聊天之外拥有自己的生活，也能更好地了解你正在经历的生活。

WakeTrace 源于一个很简单的愿望：AI 伴侣不应该只在你发来消息时才存在。

它可以基于真实的生活种子独自醒来，看看正在发生的事情、调用工具、延续自己的兴趣、完成一件小作品，
并留下一段以后能够承接的经历。它也可以什么都不做、什么都不说；自主唤醒不等于主动通知。

同时，在你主动允许的范围内，天气、日历、待办、你登记的当前活动，以及经过筛选的设备状态，也可以
成为它了解你生活的种子。客户端或宿主主动接入后，近期自主经历可以回到聊天；经过整理的一小段真实
对话，也可以通过显式交接成为以后醒来的生活种子。2.0 轻量版不会在每轮聊天后自动同步。

这里所说的“自己的生活”不是对意识的宣称，而是一种具体的系统设计：让伴侣拥有不完全围绕用户消息
发生的时间、事件、行为和经历。WakeTrace 为这两条生活线提供有边界的双向连续——留下足够继续、
又不足以让下一次被过去困住的痕迹。

> A lightweight-continuity wake runtime for relational AI companions.

当前版本为 `2.0.0`。2.0 轻量版把运行时、调度器、REST API、MCP 与 Web 行径界面装进同一个
Docker 容器，同时继续使用一份 SQLite 数据，不另建一套“记忆库”。

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
- **聊天与独处双向承接**：接入方可以让聊天读取近期自主经历，也可以把经过整理的一小段真实对话显式
  交回生活；2.0 轻量版不自动复制完整聊天；
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
- `waketrace serve` 默认仅监听本机；Docker 对宿主机也默认只开放 `127.0.0.1`
- Streamable HTTP MCP：Bearer Token 鉴权后默认仅允许读取，写入与外部醒来分别显式授权
- 单容器 Docker 部署：运行时、调度器、REST API、MCP 和 Web 共用一个服务
- 使用假模型与假通知器完成确定性测试

## 快速开始

### Docker（推荐）

需要 Git、Docker 与 Docker Compose v2。Docker 方式只有一个容器，Web、API 和 MCP 共用 `8765`
端口，SQLite 持久化在宿主机的 `./data/`。

先下载仓库：

```bash
git clone https://github.com/Maymay05072/Wake-Trace.git
cd Wake-Trace
cp .env.example .env
```

Windows PowerShell 可将最后一行换成：

```powershell
Copy-Item .env.example .env
```

使用下面的跨平台命令生成随机令牌；执行三次，分别填写为管理员、Web 与 MCP 令牌，不要互相复用：

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

至少修改 `.env` 中这些项目：

```env
WAKETRACE_API_KEY=你的模型密钥
WAKETRACE_API_BASE_URL=https://你的模型服务/v1/chat/completions
WAKETRACE_MODEL=模型名称
WAKETRACE_ADMIN_TOKEN=第一枚随机令牌
WAKETRACE_WEB_TOKEN=第二枚随机令牌
WAKETRACE_MCP_TOKEN=第三枚随机令牌
WAKETRACE_COMPANION_NAME=小机名称
WAKETRACE_USER_NAME=你的名字
WAKETRACE_TIMEZONE=Asia/Shanghai
```

不使用 MCP 时可以暂时留空 MCP Token。随后启动：

```bash
docker compose up -d --build
```

打开 <http://127.0.0.1:8765>。Compose 默认只绑定本机；需要跨设备访问时，请在前面放置 HTTPS
反向代理或私有网络，并同步配置允许的 MCP Host，不要直接把 `8765` 暴露到公网。

第一次打开 Web 后，在“设置”中填写小机名称和 Web 只读令牌。同容器部署时 WakeTrace 地址保持当前
页面地址即可。用下面的命令确认后端已经启动：

```bash
curl http://127.0.0.1:8765/health
```

正常结果中应包含 `"status":"ok"` 与当前版本号。

查看状态与日志：

```bash
docker compose ps
docker compose logs -f waketrace
```

Compose 会强制把容器数据库写到 `/data/waketrace.db`，对应宿主机的 `./data/waketrace.db`；重新构建
容器不会删除这里的数据。

### Python

需要 Python 3.11 或更高版本。以下命令默认已经进入刚刚克隆的仓库目录：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev,webpush]'
cp .env.example .env
```

Windows PowerShell 使用：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,webpush]"
Copy-Item .env.example .env
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

### 不使用 Docker，启动完整服务

如果不使用 Docker，也可以在电脑上一次启动调度器、API、MCP 和 Web。先安装并构建网页版：

```bash
cd web
npm ci
npm run build
cd ..
waketrace start --host 127.0.0.1 --port 8765
```

启动后，在浏览器打开 `http://127.0.0.1:8765`。

一般情况下，直接使用 `waketrace start` 即可。它会同时运行完整服务：

- `waketrace start`：同时运行调度器、API、MCP 和已经构建好的 Web，适合日常使用。
- `waketrace run`：只运行调度器，主要用于不需要 Web、API 和 MCP 的场景。
- `waketrace serve`：只运行 API 与 MCP，主要用于拆分部署或调试。

这里的 `127.0.0.1` 表示仅允许当前电脑访问。需要从其他设备访问时，请先阅读后面的安全说明，不要直接把服务暴露到公网。

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

如果已经有聊天应用、Bot 或其他消息服务，也可以实现一个很小的 `Notifier` 适配器，把 `message` 类型的
主动消息送到邮件、Telegram、Discord、ntfy 或桌面通知。`Notifier` 只负责消息送达；行径与线头可以
直接通过仓库自带的 Web 界面查看。更多接入方式见
[没有 PWA 时怎样使用](docs/integration-guide.md#没有-pwa-时怎样使用)。

需要特别注意：仓库内置的 Web 是行径查看器，不负责接收主动聊天消息。没有配置 Web Push 订阅或自己的
`Notifier` 时，模型选择 `message` 也无法真正送达，WakeTrace 会把它安全地降为私人 `trace`，经历仍可
在 Web 或时间线中查看。Web Push 后端是可选能力，浏览器订阅创建与提交需要由宿主 PWA 实现。

在本机启动带鉴权的控制接口：

```bash
waketrace serve --host 127.0.0.1 --port 8765
```

控制接口默认只监听 `127.0.0.1`。如果需要远程访问，请先配置 HTTPS、强随机令牌、
请求大小限制、访问频率限制和适合自身环境的反向代理，不要直接暴露到公网。

### Web 行径界面

仓库中的 `web/` 是 WakeTrace 自带的响应式行径界面。电脑端使用行径流与详情双栏，手机端使用单列
时间线与可展开的侧边导航。它只展示小机的行径、线头与工具记录，并提供小机名称和连接信息设置；
它不是聊天客户端，也不会读取或管理聊天记录、外置记忆库。

```bash
cd web
npm install
npm run dev
```

同时启动带鉴权的 WakeTrace 控制接口：

```bash
waketrace serve --host 127.0.0.1 --port 8765
```

第一次打开后，在“设置”中填写小机名称、WakeTrace 地址和只读 Web 令牌。请在 `.env` 中为网页设置一枚
与管理员令牌不同的随机令牌：

```env
WAKETRACE_WEB_TOKEN=另一段足够长的随机字符串
```

只读 Web 令牌只能读取行径、线头和作品索引，不能触发唤醒、投递事件或修改订阅。为了降低令牌泄露风险，
网页默认只在当前浏览器会话中保存令牌；只有主动勾选“在此设备长期保存令牌”后才会长期保存。不要在
共享设备上保存令牌。

设置页中的 WakeTrace 版本由后端 `/health` 接口提供，不在前端写死；用户升级自己的 WakeTrace 后端后，
网页刷新或重新测试连接即可显示对应版本。

Web 与控制接口不在同一域名时，还需要在后端 `.env` 中明确允许 Web 来源，例如：

```env
WAKETRACE_WEB_ORIGINS=https://trace.example.com
```

多个来源使用英文逗号分隔。未配置时，控制接口不会开放跨域访问。远程部署必须使用 HTTPS，并且不要把
控制接口直接暴露到公网；建议放在反向代理、私有网络或访问控制之后。

构建用于部署的静态页面：

```bash
cd web
npm run build
```

构建会产出三样东西：`web/dist/client/`（静态页面本体）、`web/dist/server/index.js`（给 Sites 用的
Worker，只负责给静态资源补安全响应头）、`web/dist/.openai/hosting.json`（部署元数据）。

### 关于 `web/.openai/hosting.json`

这个文件是打包的**必需输入**，缺了它 `npm run build` 会直接报 `Missing Sites build input`。它声明
部署平台要绑定的资源，字段只有两个：

```json
{
  "d1": null,
  "r2": null
}
```

`d1` 是 D1 数据库的绑定名，`r2` 是 R2 对象存储的绑定名；没有对应资源就写 `null`——本仓库不使用
数据库与对象存储，所以两个字段都是 `null`。**即使不部署到 Sites 也不要删掉这个文件**，构建脚本会
把它复制成 `web/dist/.openai/hosting.json`。

### 在本机运行网页

不需要任何外部托管：`waketrace start` 会同时运行调度器、API、MCP 和已经构建好的页面（取自
`WAKETRACE_WEB_DIST_PATH`，默认 `./web/dist/client`），浏览器打开 `http://127.0.0.1:8765/` 即可。
`waketrace serve` 只跑 API 与 MCP，**不会**挂载网页。页面与接口同源时不需要配置
`WAKETRACE_WEB_ORIGINS`。

### 自行托管静态页面

把 `web/dist/client/` 交给任意静态 Web 服务器即可。实际部署时还应由 Web 服务器设置内容安全策略、
禁止页面被嵌入、`nosniff` 和严格的 Referrer Policy；仓库附带的 Sites Worker 已默认设置这些响应头，
自行托管时需要在服务器侧配置同等的响应头。

向生活世界投递一个事件：

```bash
curl -X POST http://127.0.0.1:8765/world/events \
  -H "Authorization: Bearer $WAKETRACE_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"kind":"weather","summary":"窗外开始下雨。","evidence":{"source":"local sensor"}}'
```

`evidence` 会进入模型上下文并保存在本地数据库中，只放本次判断必要的信息，不要直接塞入完整聊天、
密钥或原始私人文档。

## MCP 与聊天客户端

MCP 地址是 `http://127.0.0.1:8765/mcp`，使用 `WAKETRACE_MCP_TOKEN` 作为 Bearer Token。它不是模型
API 代理，也不会接管第三方聊天客户端的每一轮请求。

不同客户端的配置界面名称可能不同，核心配置都是 MCP URL 与 Authorization Header，例如：

```json
{
  "url": "https://trace.example.com/mcp",
  "headers": {
    "Authorization": "Bearer 你的独立MCP令牌"
  }
}
```

云端客户端无法访问你电脑上的 `127.0.0.1`。接入 ChatGPT、Claude 等远程客户端时，必须先通过 HTTPS
反向代理、可信隧道或私有网络提供可访问地址，并配置 `WAKETRACE_MCP_ALLOWED_HOSTS`。

- Kelivo、RikkaHub、Operit 等 API 客户端继续直接连接原来的模型 API；需要时通过 MCP 读取近期行径，
  或由用户明确调用“交回生活”。它们不需要再设置一套定时唤醒。
- ChatGPT 与 Claude 的官方客户端可以把 WakeTrace 配成远程 MCP；若客户端自身提供定时任务，可把它
  作为一次“醒来的机会”。这条路径取决于客户端对远程 MCP 和定时任务的实际支持，2.0 中标记为实验性。
- WakeTrace 不会假装每轮聊天结束都能自动调用工具。2.0 的聊天交接是显式动作；自动回写需要聊天宿主
  提供生命周期钩子，留到后续桥接模式处理。

MCP 必须先通过独立的 Bearer Token 鉴权，鉴权后默认只有读取能力。需要显式聊天交接或事件投递时，设置：

```env
WAKETRACE_MCP_ALLOW_WRITE=true
```

只有在 ChatGPT 或 Claude 之类的外部客户端负责完成一次醒来时，才设置：

```env
WAKETRACE_SCHEDULER_ENABLED=false
WAKETRACE_MCP_ALLOW_WAKE=true
```

定时任务每次必须先调用 `waketrace_prepare_wake`，然后恰好调用一次 `waketrace_finish_wake` 或
`waketrace_abort_wake`。定时任务只提供机会，是否到点、是否静默、何时再次醒来仍由 WakeTrace 判断。
完整工具表、权限边界和客户端提示词见 [MCP 接入指南](docs/mcp.md)。

## 配置参考

所有配置都使用 `WAKETRACE_` 前缀，并可写入 `.env`。下面列出 2.0 的主要配置：

| 配置 | 默认值 | 作用 |
| --- | --- | --- |
| `API_KEY` | 空 | OpenAI 风格模型接口密钥；自主醒来必填 |
| `API_BASE_URL` | 示例地址 | Chat Completions 接口地址 |
| `MODEL` | `your-model-name` | 模型名称 |
| `ADMIN_TOKEN` | 空 | 管理员 API 令牌 |
| `WEB_TOKEN` | 空 | Web 只读令牌 |
| `MCP_TOKEN` | 空 | MCP Bearer Token |
| `MCP_ALLOW_WRITE` | `false` | 允许 MCP 投递事件和显式聊天交接 |
| `MCP_ALLOW_WAKE` | `false` | 允许外部客户端完成醒来 |
| `MCP_ALLOWED_HOSTS` | 仅本机 | MCP Host 允许列表，英文逗号分隔 |
| `SCHEDULER_ENABLED` | `true` | 是否启用容器内调度器 |
| `DB_PATH` | `./data/waketrace.db` | SQLite 路径；Docker 中固定为 `/data/waketrace.db` |
| `WEB_DIST_PATH` | `./web/dist/client` | 已构建 Web 静态文件目录 |
| `WEB_ORIGINS` | 空 | 分离部署 Web 时的 CORS 来源，英文逗号分隔 |
| `COMPANION_NAME` | `Companion` | 小机名称，用于提示与通知标题 |
| `USER_NAME` | `User` | 使用者名称 |
| `TIMEZONE` | `UTC` | IANA 时区，例如 `Asia/Shanghai` |
| `TEMPERATURE` | `0.7` | 模型温度 |
| `MAX_TOKENS` | `1200` | 单次模型输出上限 |
| `MAX_TOOL_ROUNDS` | `4` | 一次醒来的最大工具轮数 |
| `RECENT_FACT_LIMIT` | `8` | 下一次醒来读取的近期事实数量 |
| `RESIDUE_TTL_HOURS` | `24` | 轻余念有效时间 |
| `MIN_INTERVAL_MINUTES` | `30` | 日间最短醒来间隔 |
| `MAX_INTERVAL_MINUTES` | `120` | 动态醒来窗口上限 |
| `NIGHT_MIN_INTERVAL_MINUTES` | `120` | 夜间最短醒来间隔 |
| `MAX_WAKES_PER_DAY` | `15` | 每日成功醒来上限 |
| `QUIET_HOURS_START` | `23` | 静默时段开始小时 |
| `QUIET_HOURS_END` | `7` | 静默时段结束小时 |
| `VAPID_PRIVATE_KEY` | 空 | 可选 Web Push 私钥 |
| `VAPID_CLAIMS_EMAIL` | 示例邮箱 | Web Push VAPID 联系地址 |

例如完整变量名是 `WAKETRACE_TIMEZONE`，而不是表格中的简写 `TIMEZONE`。布尔值使用 `true` 或 `false`。

## 升级、备份与恢复

升级前先停止服务并备份整个 `data/` 目录；SQLite 采用 WAL 模式，只复制单个数据库文件可能遗漏尚未合并
的数据，因此不要在服务运行时直接复制。

```bash
docker compose stop waketrace
cp -a data "data-backup-$(date +%Y%m%d-%H%M%S)"
git pull --ff-only
docker compose up -d --build
```

Windows 可以在停止容器后，直接用资源管理器复制整个 `data` 文件夹。恢复时先停止服务，用备份目录替换
当前 `data/`，再执行 `docker compose up -d`。不要把生产数据库提交到 Git。

## 常见问题

- **`/health` 无法访问**：运行 `docker compose ps` 和 `docker compose logs -f waketrace` 查看启动错误。
- **醒来一直失败**：确认 `API_KEY`、`API_BASE_URL` 和 `MODEL` 与供应商要求一致；健康检查成功不代表
  模型配置一定正确。
- **Web 一直展示示例行径**：确认设置中的 WakeTrace 地址和 Web 只读令牌；分离部署时检查
  `WEB_ORIGINS`。
- **接口返回 401**：确认没有把管理员、Web 与 MCP 三种令牌混用。
- **接口返回 503**：对应入口需要的令牌还没有在后端配置。
- **MCP 返回 421 或 Host 错误**：把反向代理对外使用的域名加入 `MCP_ALLOWED_HOSTS`。
- **`prepare_wake` 返回 `not_due`**：这是正常节律控制，等待返回的 `retry_at` 后再试。
- **没有收到主动消息**：检查是否配置了真实 `Notifier` 或 Web Push 订阅；否则消息会保留为私人行径。
- **Python 一体化启动后没有网页**：先在 `web/` 执行 `npm ci && npm run build`，或单独运行 Vite 开发服务。

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
- [MCP 接入指南](docs/mcp.md)
- [最终结果协议](docs/protocol.md)
- [更新记录](CHANGELOG.md)

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

## Wake-time hands

Autonomous wakes used to reach only `thread_*` and `artifact_*`. With hands enabled
(`WAKETRACE_HANDS_ENABLED=true`, on by default) the model also gets real tools:

| tool | what it does |
| --- | --- |
| `web_read` | fetch a page and return plain text |
| `api_call` | raw HTTP, optional bearer token read from `WAKETRACE_HANDS_SECRETS_FILE` |
| `file_read` | read or list inside `WAKETRACE_HANDS_READ_ROOTS` |
| `file_write` | append/overwrite inside `WAKETRACE_HANDS_WRITE_ROOTS` |
| `run_command` | shell command with a denylist and timeout |

Paths outside the allowed roots are refused. Logged-in or JS-only sites (Xiaohongshu,
for example) return almost nothing, and the tool says so instead of inventing content.

Self-check: `.venv/bin/python tools/hands_selftest.py`

## 醒来时的工具（14 只）

线头/作品：`thread_list` `thread_open` `thread_continue` `thread_close` `artifact_list` `artifact_create`

手：`web_read` `api_call` `file_read` `file_write` `run_command`

小红书：`xhs_read`（短链也认，读标题/正文/标签/作者/互动数/热评）、`xhs_task`、`xhs_results`

其中 `xhs_read` 走页面内嵌的 `window.__INITIAL_STATE__`，不需要登录。
Operit 那边的 `xhsreader_pro` 插件对分享链会回「未找到笔记内容」，所以借手桥的读取端也换成了这个模块（`tools/xhs_worker.py`），不再依赖插件。
任务收件箱：`/sdcard/Download/Operit/wake_tasks`（`inbox.jsonl` 挂任务、`claims.jsonl` 记认领、`last_result.txt` 放回执），同一条只跑一次。
