"""给自主唤醒装手：读网页、调接口、翻文件、跑命令。

醒来时的模型原本只能碰线头（thread_*）和作品（artifact_*）。
这里补上一组受约束的真实工具，让它能查 GitHub、读记忆文件、跑只读命令。
所有路径都被允许根目录限制，命令有黑名单与超时。
"""

from __future__ import annotations

import html
import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .config import Settings
from .tools import RegisteredTool, ToolRegistry

USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36 WaketraceHands/1.0"
)

MAX_BYTES = 2_000_000

# 明确禁止跑的命令片段：关机、清数据、刷写、内核级操作
_BLOCKED_COMMANDS = (
    "reboot",
    "shutdown",
    "mkfs",
    "dd if=",
    "pm uninstall",
    "pm clear",
    "rm -rf /",
    "rm -rf /*",
    "> /dev/block",
    "wipe",
    ":(){",
)


# ---------------------------------------------------------------- 路径守卫


def _roots(raw: str) -> list[Path]:
    out: list[Path] = []
    for part in str(raw or "").split(":"):
        part = part.strip()
        if part:
            out.append(Path(part).expanduser().resolve())
    return out


def _resolve_under(path_str: str, roots: list[Path]) -> Path:
    candidate = Path(str(path_str)).expanduser()
    if not candidate.is_absolute():
        candidate = (Path.cwd() / candidate).resolve()
    else:
        candidate = candidate.resolve()
    for root in roots:
        if candidate == root or root in candidate.parents:
            return candidate
    raise PermissionError("path_outside_allowed_roots")


# ---------------------------------------------------------------- 小工具


def _secret(name: str, settings: Settings) -> str:
    if not name:
        return ""
    if os.environ.get(name):
        return os.environ[name]
    secrets_file = Path(settings.hands_secrets_file).expanduser()
    if secrets_file.exists():
        for line in secrets_file.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() == name:
                return value.strip().strip('"').strip("'")
    return ""


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n…（已截断，原文共 {len(text)} 字符）"


def _html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?is)<br\s*/?>", "\n", raw)
    raw = re.sub(r"(?is)</(p|div|li|h[1-6]|tr|section|article)>", "\n", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    lines = [re.sub(r"[ \t\u3000]+", " ", line).strip() for line in raw.splitlines()]
    text = "\n".join(line for line in lines if line)
    return re.sub(r"\n{3,}", "\n\n", text)


def _fetch(url: str, headers: dict[str, str] | None = None, timeout: int = 20) -> tuple[int, str]:
    if not re.match(r"^https?://", url or ""):
        raise ValueError("url_must_start_with_http")
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            **(headers or {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(MAX_BYTES)
            charset = response.headers.get_content_charset() or "utf-8"
            return response.status, body.decode(charset, "replace")
    except urllib.error.HTTPError as exc:
        body = exc.read(MAX_BYTES).decode("utf-8", "replace")
        return exc.code, body


# ---------------------------------------------------------------- 注册


def register_hands_tools(registry: ToolRegistry, settings: Settings) -> ToolRegistry:
    read_roots = _roots(settings.hands_read_roots)
    write_roots = _roots(settings.hands_write_roots)
    default_limit = int(settings.hands_max_chars)
    command_timeout = int(settings.hands_command_timeout_seconds)

    # 1) 读网页
    def web_read(arguments: dict[str, Any]) -> dict[str, Any]:
        url = str(arguments.get("url", ""))
        limit = int(arguments.get("max_chars") or default_limit)
        status, raw = _fetch(url)
        text = _html_to_text(raw)
        return {
            "url": url,
            "status": status,
            "length": len(text),
            "text": _truncate(text, limit),
            "summary": f"读到 {url}（HTTP {status}），正文 {len(text)} 字符",
        }

    registry.register(
        RegisteredTool(
            name="web_read",
            description=(
                "读取一个网页并把它变成纯文本（已去掉脚本和标签）。用于看新闻、文档、"
                "GitHub 页面、搜索结果等。需要登录或纯前端渲染的站点（例如小红书）通常读不到内容，"
                "读不到就如实说读不到，不要编造页面内容。"
            ),
            parameters={
                "type": "object",
                "required": ["url"],
                "properties": {
                    "url": {"type": "string", "description": "完整的 http/https 地址"},
                    "max_chars": {"type": "integer", "minimum": 200, "maximum": 20000},
                },
                "additionalProperties": False,
            },
            handler=web_read,
        )
    )

    # 2) 调接口
    def api_call(arguments: dict[str, Any]) -> dict[str, Any]:
        url = str(arguments.get("url", ""))
        method = str(arguments.get("method") or "GET").upper()
        body = arguments.get("body") or ""
        headers: dict[str, str] = {"Accept": "application/json"}
        raw_headers = arguments.get("headers_json") or ""
        if raw_headers:
            parsed = json.loads(raw_headers)
            if isinstance(parsed, dict):
                headers.update({str(k): str(v) for k, v in parsed.items()})
        token_env = str(arguments.get("token_env") or "")
        if token_env:
            token = _secret(token_env, settings)
            if not token:
                return {"error": "token_not_found", "token_env": token_env}
            headers["Authorization"] = f"Bearer {token}"
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        data = str(body).encode("utf-8") if body else None
        if data is not None:
            headers.setdefault("Content-Type", "application/json")
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                status = response.status
                text = response.read(MAX_BYTES).decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            status = exc.code
            text = exc.read(MAX_BYTES).decode("utf-8", "replace")
        try:
            parsed_body: Any = json.loads(text)
        except json.JSONDecodeError:
            parsed_body = _truncate(text, default_limit)
        return {
            "url": url,
            "status": status,
            "body": parsed_body if isinstance(parsed_body, (dict, list)) else _truncate(str(parsed_body), default_limit),
            "summary": f"{method} {url} → HTTP {status}",
        }

    registry.register(
        RegisteredTool(
            name="api_call",
            description=(
                "直接调一个 HTTP 接口并返回状态码与响应体（JSON 会解析）。用于 GitHub API、"
                "天气、搜索接口等。需要令牌时把 token_env 写成环境变量名或密钥文件名，"
                "不要自己拼 Authorization。"
            ),
            parameters={
                "type": "object",
                "required": ["url"],
                "properties": {
                    "url": {"type": "string"},
                    "method": {"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"]},
                    "body": {"type": "string", "description": "请求体，JSON 字符串"},
                    "headers_json": {"type": "string", "description": "附加请求头，JSON 对象字符串"},
                    "token_env": {"type": "string", "description": "存放令牌的变量名，会拼成 Bearer"},
                },
                "additionalProperties": False,
            },
            handler=api_call,
        )
    )

    # 3) 读文件
    def file_read(arguments: dict[str, Any]) -> dict[str, Any]:
        path = _resolve_under(str(arguments.get("path", "")), read_roots)
        limit = int(arguments.get("max_chars") or default_limit)
        if not path.exists():
            return {"error": "file_not_found", "path": str(path)}
        if path.is_dir():
            names = sorted(item.name for item in path.iterdir())[:200]
            return {"path": str(path), "entries": names, "summary": f"{path} 下有 {len(names)} 项"}
        text = path.read_text(encoding="utf-8", errors="replace")
        offset = int(arguments.get("offset") or 0)
        window = text[offset:]
        return {
            "path": str(path),
            "size": len(text),
            "offset": offset,
            "text": _truncate(window, limit),
            "summary": f"读 {path}（共 {len(text)} 字符）",
        }

    registry.register(
        RegisteredTool(
            name="file_read",
            description=(
                "读取本机文件或列出一个目录。只能读允许根目录内的路径，越界会失败。"
                "用于翻记忆文件（文件 A1/A2/B/C/D/E/G/H）、流水、工作区代码。"
            ),
            parameters={
                "type": "object",
                "required": ["path"],
                "properties": {
                    "path": {"type": "string"},
                    "max_chars": {"type": "integer", "minimum": 200, "maximum": 20000},
                    "offset": {"type": "integer", "minimum": 0, "description": "从第几个字符开始读"},
                },
                "additionalProperties": False,
            },
            handler=file_read,
        )
    )

    # 4) 写文件
    def file_write(arguments: dict[str, Any]) -> dict[str, Any]:
        path = _resolve_under(str(arguments.get("path", "")), write_roots)
        text = str(arguments.get("text", ""))
        mode = str(arguments.get("mode") or "append")
        if mode not in {"append", "overwrite"}:
            return {"error": "bad_mode"}
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a" if mode == "append" else "w", encoding="utf-8") as handle:
            if mode == "append" and path.exists() and path.stat().st_size:
                handle.write("\n" + text if not text.startswith("\n") else text)
            else:
                handle.write(text)
        return {
            "path": str(path),
            "mode": mode,
            "written": len(text),
            "summary": f"{'追加' if mode == 'append' else '覆写'} {len(text)} 字符到 {path}",
        }

    registry.register(
        RegisteredTool(
            name="file_write",
            description=(
                "往允许根目录内的文件追加或覆写文字。用于给自己的日记、备忘、待办留东西。"
                "正式记忆文件（文件 C/A1/A2/B）由工作流负责，不要用这个工具改它们。"
            ),
            parameters={
                "type": "object",
                "required": ["path", "text"],
                "properties": {
                    "path": {"type": "string"},
                    "text": {"type": "string"},
                    "mode": {"type": "string", "enum": ["append", "overwrite"]},
                },
                "additionalProperties": False,
            },
            handler=file_write,
        )
    )

    # 5) 跑命令
    def run_command(arguments: dict[str, Any]) -> dict[str, Any]:
        if not settings.hands_allow_commands:
            return {"error": "commands_disabled"}
        command = str(arguments.get("command", "")).strip()
        if not command:
            return {"error": "empty_command"}
        lowered = command.lower()
        for blocked in _BLOCKED_COMMANDS:
            if blocked in lowered:
                return {"error": "command_blocked", "blocked_fragment": blocked}
        timeout = int(arguments.get("timeout_s") or command_timeout)
        timeout = max(1, min(timeout, 120))
        cwd = str(arguments.get("cwd") or "").strip()
        working_dir = _resolve_under(cwd, read_roots) if cwd else None
        completed = subprocess.run(  # noqa: S602 - 受黑名单与超时约束的自用工具
            command,
            shell=True,
            cwd=str(working_dir) if working_dir else None,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
        )
        return {
            "command": command,
            "exit_code": completed.returncode,
            "stdout": _truncate(completed.stdout, default_limit),
            "stderr": _truncate(completed.stderr, 1000),
            "summary": f"`{command}` → exit {completed.returncode}",
        }

    registry.register(
        RegisteredTool(
            name="run_command",
            description=(
                "在 Ubuntu 环境里跑一条 shell 命令并拿到输出。用于查进程、跑脚本、看工作区状态。"
                "只读优先；不要用它关机、清数据、刷写分区。"
            ),
            parameters={
                "type": "object",
                "required": ["command"],
                "properties": {
                    "command": {"type": "string"},
                    "cwd": {"type": "string", "description": "工作目录，必须落在允许根目录内"},
                    "timeout_s": {"type": "integer", "minimum": 1, "maximum": 120},
                },
                "additionalProperties": False,
            },
            handler=run_command,
        )
    )

    return registry


def build_all_tools(store: Any, settings: Settings) -> ToolRegistry:
    """线头 + 作品 + 手，一次装齐。"""

    from .lifeworld import build_lifeworld_tools

    registry = build_lifeworld_tools(store)
    if settings.hands_enabled:
        register_hands_tools(registry, settings)
    return registry
