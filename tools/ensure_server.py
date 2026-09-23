#!/usr/bin/env python3
"""醒来服务守护：摸一次 Wake-Trace 的脉搏，倒了就重新拉起来。

给 Operit 工作流调用：

  ALIVE    服务本来就在跑，什么都没做
  STARTED  服务原本不在，已经被拉起来并且 /health 通过
  FAILED   试图拉起但没起来（工作流会据此通知小楠）

拉起时使用 start_new_session，让服务脱离调用它的进程独立存活。
"""

from __future__ import annotations

import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV_BIN = ROOT / ".venv" / "bin" / "waketrace"
LOG = ROOT / "data" / "waketrace_run.log"
HEALTH = "http://127.0.0.1:8765/health"


def healthy(timeout: float = 3.0) -> bool:
    try:
        with urllib.request.urlopen(HEALTH, timeout=timeout) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def spawn() -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    log = open(LOG, "a", encoding="utf-8")  # noqa: SIM115 - 交给子进程持有
    subprocess.Popen(
        [str(VENV_BIN), "start", "--host", "127.0.0.1", "--port", "8765"],
        cwd=str(ROOT),
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=log,
        start_new_session=True,
        close_fds=True,
    )


def main() -> int:
    if healthy():
        print("ALIVE")
        return 0

    spawn()
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        if healthy():
            print("STARTED")
            return 0
        time.sleep(1.5)

    print("FAILED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())