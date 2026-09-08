from datetime import UTC, datetime

from waketrace.config import Settings
from waketrace.policy import WakePolicy
from waketrace.storage import SQLiteStore


def test_model_interval_is_clamped_to_configured_ceiling(tmp_path):
    settings = Settings(
        db_path=tmp_path / "wake.db",
        min_interval_minutes=30,
        max_interval_minutes=60,
        quiet_hours_start=0,
        quiet_hours_end=0,
    )
    store = SQLiteStore(settings.db_path)
    policy = WakePolicy(settings, store)
    now = datetime.now(UTC)
    next_at = policy.choose_next(now, requested_min=500, requested_max=900)
    assert int((next_at - now).total_seconds() / 60) == 60


def test_cross_midnight_quiet_hours(tmp_path):
    settings = Settings(
        db_path=tmp_path / "wake.db",
        timezone="UTC",
        quiet_hours_start=23,
        quiet_hours_end=7,
    )
    policy = WakePolicy(settings, SQLiteStore(settings.db_path))
    assert not policy.can_notify(datetime(2026, 1, 1, 23, tzinfo=UTC))
    assert not policy.can_notify(datetime(2026, 1, 2, 6, tzinfo=UTC))
    assert policy.can_notify(datetime(2026, 1, 2, 12, tzinfo=UTC))
