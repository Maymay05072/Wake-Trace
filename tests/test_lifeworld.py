from datetime import UTC, datetime, timedelta

from waketrace.config import Settings
from waketrace.lifeworld import LifeWorld, build_lifeworld_tools
from waketrace.models import WakeResult
from waketrace.storage import SQLiteStore


def make_world(tmp_path):
    settings = Settings(db_path=tmp_path / "wake.db", timezone="UTC")
    store = SQLiteStore(settings.db_path)
    return LifeWorld(settings, store), store


def result(outcome: str, now: datetime) -> WakeResult:
    return WakeResult(1, outcome, False, now + timedelta(minutes=30))


def test_world_events_are_claimed_once_in_order(tmp_path):
    world, store = make_world(tmp_path)
    now = datetime(2026, 1, 2, 9, tzinfo=UTC)
    first_id = store.enqueue_world_event("weather", "窗外开始下雨。", now=now)
    store.enqueue_world_event("calendar", "下午有一项安排。", now=now)

    selected = world.select_seed(now)
    assert selected.event_id == first_id
    assert selected.seed.kind == "weather"
    world.settle_seed(selected, result("trace", now))

    assert world.select_seed(now).seed.kind == "calendar"


def test_failed_wake_releases_claimed_event(tmp_path):
    world, store = make_world(tmp_path)
    now = datetime(2026, 1, 2, 9, tzinfo=UTC)
    event_id = store.enqueue_world_event("external", "一件可重试的事。", now=now)

    selected = world.select_seed(now)
    world.settle_seed(selected, result("error", now))

    assert world.select_seed(now).event_id == event_id


def test_thread_can_reappear_and_closed_thread_is_skipped(tmp_path):
    world, store = make_world(tmp_path)
    now = datetime(2026, 1, 2, 9, tzinfo=UTC)
    opened = store.create_life_thread(
        "窗边的声音",
        "想分辨清晨最先出现的声音。",
        next_pull="下次留意第一声鸟叫",
        revisit_after_minutes=30,
        now=now,
    )
    assert opened["ok"] is True
    assert world.select_seed(now).seed.kind == "free_window"

    due = now + timedelta(minutes=30)
    selected = world.select_seed(due)
    assert selected.seed.kind == "thread_due"
    world.release_seed(selected)
    store.close_life_thread(opened["thread_id"], now=due)

    assert world.select_seed(due).seed.kind == "free_window"


def test_lifeworld_tools_validate_threads_and_artifacts(tmp_path):
    _, store = make_world(tmp_path)
    tools = build_lifeworld_tools(store)

    ok, _, _ = tools.execute("thread_open", {"title": "", "origin": "起点"})
    assert ok is False
    ok, created, _ = tools.execute(
        "artifact_create", {"title": "小纸片", "content": "写完了一句话。"}
    )
    assert ok is True
    assert created["media_type"] == "text/markdown"
    ok, _, _ = tools.execute(
        "artifact_create",
        {"title": "页面", "content": "<h1>hi</h1>", "media_type": "text/html"},
    )
    assert ok is False
