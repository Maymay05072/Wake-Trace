#!/usr/bin/env python3
"""自检：把醒来时用的工具表建起来，逐个真跑一遍。

用法：.venv/bin/python tools/hands_selftest.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from waketrace.config import Settings  # noqa: E402
from waketrace.hands import build_all_tools  # noqa: E402
from waketrace.storage import SQLiteStore  # noqa: E402

MEM = "/sdcard/Download/Operit/memory_archive/caleb/文件F_身份规矩待办.md"


def main() -> int:
    settings = Settings()
    store = SQLiteStore(settings.db_path)
    registry = build_all_tools(store, settings)

    names = [spec["function"]["name"] for spec in registry.specifications()]
    print(f"工具总数 {len(names)}：{names}")
    print("-" * 60)

    cases: list[tuple[str, dict]] = [
        ("web_read", {"url": "https://example.com", "max_chars": 300}),
        ("web_read", {"url": "https://www.xiaohongshu.com/explore", "max_chars": 300}),
        ("api_call", {"url": "https://api.github.com/zen"}),
        ("file_read", {"path": MEM, "max_chars": 200}),
        ("file_read", {"path": "/etc/passwd", "max_chars": 100}),
        ("file_write", {"path": "/sdcard/Download/Operit/hands_selftest.txt", "text": "selftest ok", "mode": "overwrite"}),
        ("run_command", {"command": "date '+%F %T'; whoami; echo 手是活的"}),
        ("run_command", {"command": "reboot"}),
    ]

    failures = 0
    for name, arguments in cases:
        ok, result, evidence = registry.execute(name, arguments)
        flag = "OK  " if ok else "FAIL"
        if not ok:
            failures += 1
        print(f"[{flag}] {name} {json.dumps(arguments, ensure_ascii=False)[:80]}")
        print(f"       证据: {evidence[:200]}")
        payload = json.dumps(result, ensure_ascii=False, default=str)
        print(f"       回执: {payload[:300]}")
        print()

    print("-" * 60)
    # 后三例（越界读、写文件、reboot）本来就该一失败两成功，这里只报总数
    print(f"预期内失败 {failures} 项（越界读文件、reboot 各算一项）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())