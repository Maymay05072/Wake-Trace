from __future__ import annotations

import random
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from zoneinfo import ZoneInfo

from .config import Settings
from .storage import SQLiteStore


@dataclass(frozen=True, slots=True)
class GateDecision:
    allowed: bool
    reason: str = ""
    retry_at: datetime | None = None


class WakePolicy:
    def __init__(self, settings: Settings, store: SQLiteStore):
        self.settings = settings
        self.store = store
        self.rng = random.SystemRandom()

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.settings.timezone)

    def allow_wake(self, now: datetime) -> GateDecision:
        local = now.astimezone(self.zone)
        date_key = local.date().isoformat()
        counters = self.store.get_state("wake_counters", {})
        if counters.get("date") != date_key:
            counters = {"date": date_key, "count": 0, "push_count": 0}
            self.store.set_state("wake_counters", counters, now)
        if int(counters.get("count", 0)) >= self.settings.max_wakes_per_day:
            tomorrow = (local + timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)
            return GateDecision(False, "daily_wake_limit", tomorrow)

        last_raw = self.store.get_state("last_successful_wake_at", "")
        if last_raw:
            try:
                last = datetime.fromisoformat(last_raw)
                minimum = self._minimum_minutes(local)
                retry = last + timedelta(minutes=minimum)
                if now < retry:
                    return GateDecision(False, "minimum_interval", retry)
            except ValueError:
                pass
        return GateDecision(True)

    def mark_wake(self, now: datetime) -> None:
        local = now.astimezone(self.zone)
        counters = self.store.get_state("wake_counters", {})
        if counters.get("date") != local.date().isoformat():
            counters = {"date": local.date().isoformat(), "count": 0, "push_count": 0}
        counters["count"] = int(counters.get("count", 0)) + 1
        self.store.set_state("wake_counters", counters, now)
        self.store.set_state("last_successful_wake_at", now.isoformat(), now)

    def mark_push(self, now: datetime) -> None:
        local = now.astimezone(self.zone)
        counters = self.store.get_state("wake_counters", {})
        if counters.get("date") != local.date().isoformat():
            counters = {"date": local.date().isoformat(), "count": 0, "push_count": 0}
        counters["push_count"] = int(counters.get("push_count", 0)) + 1
        self.store.set_state("wake_counters", counters, now)

    def can_notify(self, now: datetime) -> bool:
        hour = now.astimezone(self.zone).hour
        start, end = self.settings.quiet_hours_start, self.settings.quiet_hours_end
        if start == end:
            return True
        return not (hour >= start or hour < end) if start > end else not (start <= hour < end)

    def choose_next(
        self,
        now: datetime,
        requested_min: int | None = None,
        requested_max: int | None = None,
    ) -> datetime:
        local = now.astimezone(self.zone)
        floor = self._minimum_minutes(local)
        ceiling = max(floor, self.settings.max_interval_minutes)
        low = min(ceiling, max(floor, requested_min or floor))
        high = min(ceiling, requested_max or ceiling)
        high = max(high, low)
        history = self.store.get_state("interval_history", [])
        recent = [int(value) for value in history[-3:] if isinstance(value, int)]
        candidates = list(range(low, high + 1))
        varied = [value for value in candidates if all(abs(value - old) >= 4 for old in recent)]
        minutes = self.rng.choice(varied or candidates)
        self.store.set_state("interval_history", (history + [minutes])[-5:], now)
        next_at = now + timedelta(minutes=minutes)
        self.store.set_state("next_wake_at", next_at.isoformat(), now)
        return next_at

    def is_duplicate(self, candidate: str, threshold: float = 0.82) -> bool:
        previous = str(self.store.get_state("last_share", ""))
        current = _normalize(candidate)
        old = _normalize(previous)
        if not current or not old:
            return False
        return current == old or current in old or old in current or SequenceMatcher(None, current, old).ratio() >= threshold

    def _minimum_minutes(self, local: datetime) -> int:
        if local.hour >= 23 or local.hour < 6:
            return self.settings.night_min_interval_minutes
        return self.settings.min_interval_minutes


def _normalize(text: str) -> str:
    return re.sub(r"[\s，。！？、；：,.!?;:'\"（）()\[\]【】]+", "", text).lower()
