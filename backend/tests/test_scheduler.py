"""Tests for the recurring-workflow due-logic (pure, no DB/Celery)."""

from datetime import datetime, timedelta, timezone

from app.services.scheduler.schedules import (
    due_schedules,
    is_due,
    parse_iso,
    validate_schedule,
)


def _now() -> datetime:
    return datetime(2026, 6, 27, 9, 0, tzinfo=timezone.utc)


# ── interval ─────────────────────────────────────────────────────────────────

def test_interval_due_when_never_run():
    s = {"workflow": "w", "trigger": {"type": "interval", "every_minutes": 60}}
    assert is_due(s, now=_now(), last_run_at=None) is True


def test_interval_not_due_before_period_elapses():
    s = {"workflow": "w", "trigger": {"type": "interval", "every_minutes": 60}}
    last = _now() - timedelta(minutes=30)
    assert is_due(s, now=_now(), last_run_at=last) is False


def test_interval_due_after_period_elapses():
    s = {"workflow": "w", "trigger": {"type": "interval", "every_minutes": 60}}
    last = _now() - timedelta(minutes=61)
    assert is_due(s, now=_now(), last_run_at=last) is True


def test_interval_hours_and_days_accumulate():
    s = {"workflow": "w", "trigger": {"type": "interval", "every_hours": 1, "every_days": 1}}
    # 25h cadence: 24h elapsed is not enough, 26h is.
    assert is_due(s, now=_now(), last_run_at=_now() - timedelta(hours=24)) is False
    assert is_due(s, now=_now(), last_run_at=_now() - timedelta(hours=26)) is True


# ── daily ────────────────────────────────────────────────────────────────────

def test_daily_due_after_slot_and_not_yet_run_today():
    s = {"workflow": "w", "trigger": {"type": "daily", "at": "08:00"}}
    # now is 09:00; ran yesterday -> due today.
    last = _now() - timedelta(days=1)
    assert is_due(s, now=_now(), last_run_at=last) is True


def test_daily_not_due_before_slot():
    s = {"workflow": "w", "trigger": {"type": "daily", "at": "08:00"}}
    early = datetime(2026, 6, 27, 7, 30, tzinfo=timezone.utc)
    assert is_due(s, now=early, last_run_at=None) is False


def test_daily_not_due_if_already_ran_after_slot():
    s = {"workflow": "w", "trigger": {"type": "daily", "at": "08:00"}}
    ran_today = datetime(2026, 6, 27, 8, 0, tzinfo=timezone.utc)
    assert is_due(s, now=_now(), last_run_at=ran_today) is False


# ── guards ───────────────────────────────────────────────────────────────────

def test_disabled_schedule_never_due():
    s = {"workflow": "w", "enabled": False, "trigger": {"type": "interval", "every_minutes": 1}}
    assert is_due(s, now=_now(), last_run_at=None) is False


def test_malformed_trigger_never_due():
    assert is_due({"workflow": "w"}, now=_now()) is False
    assert is_due({"workflow": "w", "trigger": {"type": "bogus"}}, now=_now()) is False


def test_due_schedules_filters_and_reads_last_run_at_field():
    schedules = [
        {"id": "a", "workflow": "w", "trigger": {"type": "interval", "every_minutes": 60},
         "last_run_at": (_now() - timedelta(minutes=90)).isoformat()},
        {"id": "b", "workflow": "w", "trigger": {"type": "interval", "every_minutes": 60},
         "last_run_at": (_now() - timedelta(minutes=10)).isoformat()},
        {"id": "c", "enabled": False, "workflow": "w",
         "trigger": {"type": "interval", "every_minutes": 1}},
    ]
    due = due_schedules(schedules, now=_now())
    assert [s["id"] for s in due] == ["a"]
    # returns the same dict refs so the caller can stamp last_run_at in place
    assert due[0] is schedules[0]


def test_one_bad_schedule_does_not_block_others():
    schedules = [
        None,  # garbage
        {"id": "ok", "workflow": "w", "trigger": {"type": "interval", "every_minutes": 60}},
    ]
    due = due_schedules(schedules, now=_now())
    assert [s["id"] for s in due] == ["ok"]


# ── validation + parsing ─────────────────────────────────────────────────────

def test_validate_schedule_accepts_good_and_rejects_bad():
    ok, _ = validate_schedule(
        {"workflow": "w", "trigger": {"type": "daily", "at": "08:00"}}
    )
    assert ok is True
    bad, reason = validate_schedule({"trigger": {"type": "daily", "at": "08:00"}})
    assert bad is False and "workflow" in reason
    bad2, reason2 = validate_schedule(
        {"workflow": "w", "trigger": {"type": "daily", "at": "25:99"}}
    )
    assert bad2 is False and "HH:MM" in reason2


def test_parse_iso_handles_z_suffix_and_naive():
    assert parse_iso("2026-06-27T08:00:00Z").tzinfo is not None
    assert parse_iso("not-a-date") is None
    assert parse_iso("") is None
