"""读小红书笔记：短链解析 + 正文 / 标签 / 作者 / 互动数 / 评论。

Operit 那边的 xhsreader_pro 插件对这类分享链会回「未找到笔记内容」，
但页面里内嵌了 window.__INITIAL_STATE__，用手机 UA 取回来就能读出正文。
这个模块只做取回与解析，取不到就如实标记 missing，不编造。
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from datetime import UTC, datetime

MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 14; 2211133C) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
)
MAX_BYTES = 3_000_000


def fetch(url: str, timeout: int = 25) -> tuple[int, str, str]:
    """取页面并跟着跳转走，返回 (状态码, 最终地址, 正文)。"""

    if not re.match(r"^https?://", url or ""):
        raise ValueError("url_must_start_with_http")
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": MOBILE_UA,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(MAX_BYTES)
            return response.status, response.geturl(), body.decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, url, exc.read(MAX_BYTES).decode("utf-8", "replace")


# ---------------------------------------------------------------- JSON 小工具


def _decode(raw: str) -> str:
    try:
        return json.loads('"' + raw + '"')
    except Exception:
        return raw


def _strings(text: str, key: str) -> list[tuple[int, str]]:
    pattern = r'"' + key + r'"\s*:\s*"((?:[^"\\]|\\.)*)"'
    return [(m.start(), _decode(m.group(1))) for m in re.finditer(pattern, text)]


def _block(text: str, start: int) -> str:
    """从 text[start]（{ 或 [）开始，取一段配平的 JSON。"""

    opener = text[start]
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return ""


def _state(html: str) -> dict | None:
    """把页面里的 window.__INITIAL_STATE__ 取出来解析成字典。"""

    match = re.search(r"window\.__INITIAL_STATE__\s*=\s*", html)
    if not match:
        return None
    raw = _block(html, match.end())
    if not raw:
        return None
    try:
        return json.loads(re.sub(r"\bundefined\b", "null", raw))
    except Exception:
        return None


# ---------------------------------------------------------------- 解析


def _comment_view(items: object, limit: int) -> list[dict]:
    found: list[dict] = []

    def walk(source: object, depth: int = 0) -> None:
        if not isinstance(source, list) or len(found) >= limit:
            return
        for item in source:
            if not isinstance(item, dict) or len(found) >= limit:
                continue
            user = item.get("user") if isinstance(item.get("user"), dict) else {}
            content = item.get("content")
            if content:
                found.append(
                    {
                        "depth": depth,
                        "user": user.get("nickname") or user.get("nickName") or "",
                        "ip": item.get("ipLocation", ""),
                        "content": content,
                        "likes": item.get("likeViewCount") or item.get("likeCount") or 0,
                    }
                )
            walk(item.get("subComments"), depth + 1)

    walk(items)
    return found


def _stamp(milliseconds: object) -> str:
    try:
        moment = datetime.fromtimestamp(int(milliseconds) / 1000, tz=UTC)
    except Exception:
        return ""
    return moment.astimezone().strftime("%Y-%m-%d %H:%M")


def parse(html: str, comment_limit: int = 8) -> dict:
    state = _state(html)
    bucket = ((state or {}).get("noteData") or {}) if isinstance(state, dict) else {}
    data = bucket.get("data") if isinstance(bucket.get("data"), dict) else {}
    note = data.get("noteData") if isinstance(data.get("noteData"), dict) else {}
    preload = (
        bucket.get("normalNotePreloadData")
        if isinstance(bucket.get("normalNotePreloadData"), dict)
        else {}
    )

    result: dict = {"missing": [], "source": "state" if note else "fallback"}
    if not note:
        # 退回页面里的预载数据，至少把标题和正文捞出来
        title = str(preload.get("title") or "")
        desc = str(preload.get("desc") or "")
        if not desc:
            descs = [value for _, value in _strings(html, "desc") if value]
            desc = max(descs, key=len) if descs else ""
        if not title:
            titles = [value for _, value in _strings(html, "title") if value]
            title = max(titles, key=len) if titles else ""
        if not desc:
            result["missing"].append("desc")
            return result
        result.update(
            {
                "title": title,
                "desc": desc,
                "tags": [],
                "comments": [],
                "image_count": len(preload.get("imagesList") or []),
            }
        )
        return result

    result["title"] = note.get("title") or ""
    result["desc"] = note.get("desc") or ""
    result["note_id"] = note.get("noteId") or ""
    result["type"] = note.get("type") or ""
    result["posted_at"] = _stamp(note.get("time"))

    user = note.get("user") if isinstance(note.get("user"), dict) else {}
    result["author"] = user.get("nickname") or user.get("nickName") or ""
    result["author_id"] = user.get("userId") or ""

    tags = note.get("tagList") if isinstance(note.get("tagList"), list) else []
    result["tags"] = [
        item.get("name") for item in tags if isinstance(item, dict) and item.get("name")
    ]

    interact = note.get("interactInfo") if isinstance(note.get("interactInfo"), dict) else {}
    for key in ("likedCount", "collectedCount", "commentCount", "shareCount"):
        if interact.get(key):
            result[key] = interact[key]

    images = note.get("imageList") if isinstance(note.get("imageList"), list) else []
    result["image_count"] = len(images)
    result["image_urls"] = [
        item.get("url") for item in images if isinstance(item, dict) and item.get("url")
    ][:9]

    comments = data.get("commentData") if isinstance(data.get("commentData"), dict) else {}
    result["comments"] = _comment_view(comments.get("comments"), comment_limit)
    if not result["desc"]:
        result["missing"].append("desc")
    return result


def read(url: str, comment_limit: int = 8) -> dict:
    """读一条分享链或笔记链，返回结构化的笔记内容。"""

    status, final_url, body = fetch(url)
    note = parse(body, comment_limit)
    note.update({"status": status, "final_url": final_url, "html_length": len(body)})
    return note


def render(note: dict, max_chars: int = 4000) -> str:
    """把解析结果排成给人看的纯文本。"""

    if note.get("missing") or not note.get("desc"):
        return (
            f"[没读到笔记内容] 最终地址 {note.get('final_url')}，"
            f"HTTP {note.get('status')}，页面 {note.get('html_length')} 字符。"
            f"缺字段：{', '.join(note.get('missing') or ['desc'])}"
        )

    lines = ["【小红书笔记】"]
    lines.append(f"标题：{note.get('title') or '（无）'}")
    lines.append(f"作者：{note.get('author') or '（未知）'}")
    if note.get("posted_at"):
        lines.append(f"发布：{note['posted_at']}")
    lines.append(f"正文：{note['desc']}")
    if note.get("tags"):
        lines.append("标签：" + " ".join("#" + tag for tag in note["tags"]))
    counts = [
        f"{label} {note[key]}"
        for key, label in (
            ("likedCount", "点赞"),
            ("collectedCount", "收藏"),
            ("commentCount", "评论"),
            ("shareCount", "分享"),
        )
        if note.get(key)
    ]
    if counts:
        lines.append("互动：" + "，".join(counts))
    if note.get("image_count"):
        lines.append(f"图片：{note['image_count']} 张")
    lines.append(f"地址：{note.get('final_url', '')}")

    comments = note.get("comments") or []
    if comments:
        lines.append("")
        lines.append(f"【评论前 {len(comments)} 条】")
        for item in comments:
            indent = "  " * int(item.get("depth") or 0)
            where = f"（{item.get('ip')}）" if item.get("ip") else ""
            likes = f" 赞{item.get('likes')}" if item.get("likes") else ""
            lines.append(
                f"{indent}- {item.get('user') or '匿名'}{where}：{item.get('content')}{likes}"
            )

    text = "\n".join(lines)
    if len(text) > max_chars:
        return text[:max_chars] + f"\n…（已截断，原文共 {len(text)} 字符）"
    return text