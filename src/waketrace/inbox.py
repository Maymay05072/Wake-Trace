"""醒来任务的收件箱：任务怎么挂、怎么认领、回执写哪儿。"""

from __future__ import annotations

import json
import zlib
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_DIR = Path("/sdcard/Download/Operit/wake_tasks")


def _lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _append(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


class Inbox:
    """inbox.jsonl 挂任务，claims.jsonl 记认领，last_result.txt 放回执。"""

    def __init__(self, directory: Path | str = DEFAULT_DIR) -> None:
        self.dir = Path(directory)
        self.inbox = self.dir / "inbox.jsonl"
        self.claims = self.dir / "claims.jsonl"
        self.result = self.dir / "last_result.txt"

    def add(self, target: str, note: str = "") -> dict:
        stamp = datetime.now().strftime("%Y%m%d%H%M%S")
        tail = zlib.crc32(target.encode("utf-8")) % 10000
        record = {
            "id": f"xhs-{stamp}-{tail:04d}",
            "target": target,
            "note": note,
            "created_at": datetime.now(UTC).isoformat(),
        }
        _append(self.inbox, record)
        return record

    def next(self) -> dict | None:
        """取一条还没认领过的任务，取的同时写下认领，同一条不会再给第二次。"""

        claimed = {item.get("id") for item in _lines(self.claims)}
        for task in _lines(self.inbox):
            if task.get("id") in claimed:
                continue
            _append(
                self.claims,
                {
                    "id": task.get("id"),
                    "target": task.get("target"),
                    "claimed_at": datetime.now(UTC).isoformat(),
                },
            )
            return task
        return None

    def pending(self) -> list[tuple[dict, dict | None]]:
        claims = {item.get("id"): item for item in _lines(self.claims)}
        return [(task, claims.get(task.get("id"))) for task in _lines(self.inbox)]

    def save_result(self, text: str) -> Path:
        self.result.parent.mkdir(parents=True, exist_ok=True)
        self.result.write_text(
            f"# 回执 {datetime.now(UTC).isoformat()}\n\n{text}", encoding="utf-8"
        )
        return self.result

    def result_text(self) -> str:
        if not self.result.exists():
            return ""
        return self.result.read_text(encoding="utf-8", errors="replace")