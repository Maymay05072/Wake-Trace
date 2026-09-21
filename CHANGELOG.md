# 更新记录

## 2.0.0

- 新增同时适配电脑和手机的 Web 行径界面；
- 新增 Streamable HTTP MCP，以及读取、显式写入和外部醒来三层能力边界；
- 新增 ChatGPT、Claude 等官方客户端的实验性外部醒来协议；
- 新增单容器 Docker 部署，统一运行调度器、REST API、MCP、Web 与 SQLite；
- 新增管理员、Web 只读和 MCP 三类独立令牌；
- 新增 CORS 白名单、MCP Host 校验和 Web 安全响应头；
- Web 版本号改为读取后端 `/health`；
- 外部醒来会检查 `next_wake_at`、最短间隔、每日上限和跨进程租约；
- 补充 MCP、部署、安全、无 PWA 使用方式与生活世界文档。

## 0.1.0-alpha

- 建立自主唤醒核心、动态间隔与三种醒来结局；
- 建立 `fact / content` 双通道、轻余念和工具证据；
- 加入生活事件、线头、作品、SQLite 持久化与可选 Web Push。
