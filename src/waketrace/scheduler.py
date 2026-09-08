from __future__ import annotations

import logging
from datetime import UTC, datetime
from threading import Event

from .engine import WakeEngine
from .lifeworld import LifeWorld

logger = logging.getLogger(__name__)


class WakeScheduler:
    """轻量轮询调度器；生产环境也可以替换为 cron 或任务队列。"""

    def __init__(
        self,
        engine: WakeEngine,
        poll_seconds: float = 5.0,
        lifeworld: LifeWorld | None = None,
    ):
        self.engine = engine
        self.poll_seconds = max(1.0, poll_seconds)
        self.lifeworld = lifeworld or LifeWorld(engine.settings, engine.store)

    def run_forever(self, stop: Event | None = None) -> None:
        stop = stop or Event()
        while not stop.is_set():
            now = datetime.now(UTC)
            due_raw = self.engine.store.get_state("next_wake_at", "")
            if not due_raw:
                self.engine.policy.choose_next(now)
            else:
                try:
                    due = datetime.fromisoformat(due_raw)
                except ValueError:
                    due = now
                if now >= due:
                    selected = self.lifeworld.select_seed(now)
                    try:
                        result = self.engine.run(selected.seed, now=now)
                    except Exception:
                        self.lifeworld.release_seed(selected)
                        logger.exception("wake cycle failed unexpectedly")
                    else:
                        self.lifeworld.settle_seed(selected, result)
            stop.wait(self.poll_seconds)
