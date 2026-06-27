"""
Schedule due-logic for recurring workflows (pure, dependency-free).

A schedule lives in ``tenant.settings["schedules"]`` (the established config
store — "Product = config", per docs/POSITIONING.md) and looks like::

    {
        "id": "analyst-morning-digest",
        "name": "Analyst morning digest",
        "workflow": "analyst_report",
        "enabled": true,
        "trigger": {"type": "interval", "every_minutes": 60},
        # or {"type": "daily", "at": "08:00"}                 # UTC HH:MM
        # or {"type": "cron",  "expr": "0 8 * * 1-5"}          # if croniter present
        "context_queries": ["overnight incidents", "open approvals"],
        "trigger_data": { ... },   # optional, merged into the run trigger
        "config": { ... },         # optional, merged into the workflow config
        "last_run_at": "2026-06-27T08:00:00+00:00",  # managed by the scheduler
        "last_status": "enqueued"
    }

This module decides *whether* a schedule is due. It does not run anything and
imports nothing from the app, so it is trivially unit-testable. The Celery beat
tick (app.worker) calls :func:`due_schedules`, enqueues a governed run for each,
and stamps ``last_run_at``.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Floor on interval cadence: the beat tick runs once a minute, so anything
# faster is meaningless and risks a run storm.
MIN_INTERVAL_MINUTES = 1

_VALID_TYPES = {"interval", "daily", "cron"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware_utc(dt: datetime) -> datetime:
    """Coerce a datetime to timezone-aware UTC (treat naive as UTC)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_iso(ts: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp to aware UTC; ``None`` on anything invalid."""
    if isinstance(ts, datetime):
        return _as_aware_utc(ts)
    if not isinstance(ts, str) or not ts.strip():
        return None
    raw = ts.strip()
    # Accept a trailing "Z" (Python's fromisoformat is picky before 3.11).
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        return _as_aware_utc(datetime.fromisoformat(raw))
    except ValueError:
        logger.warning("scheduler: unparseable timestamp %r", ts)
        return None


def _parse_hhmm(value: Any) -> time | None:
    """Parse ``"HH:MM"`` (24h) into a ``time``; ``None`` if malformed."""
    if not isinstance(value, str):
        return None
    parts = value.strip().split(":")
    if len(parts) != 2:
        return None
    try:
        hh, mm = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if 0 <= hh <= 23 and 0 <= mm <= 59:
        return time(hour=hh, minute=mm, tzinfo=timezone.utc)
    return None


def _interval_minutes(trigger: dict[str, Any]) -> int | None:
    """Total cadence in minutes from ``every_minutes|every_hours|every_days``."""
    minutes = 0
    for key, mult in (("every_minutes", 1), ("every_hours", 60), ("every_days", 1440)):
        raw = trigger.get(key)
        if raw is None:
            continue
        try:
            minutes += int(raw) * mult
        except (TypeError, ValueError):
            return None
    if minutes <= 0:
        return None
    return max(minutes, MIN_INTERVAL_MINUTES)


def validate_schedule(raw: Any) -> tuple[bool, str]:
    """Lightweight structural validation (for an editor API later).

    Returns ``(ok, reason)``. ``reason`` is empty when ok.
    """
    if not isinstance(raw, dict):
        return False, "schedule must be an object"
    if not raw.get("workflow"):
        return False, "schedule.workflow is required"
    trigger = raw.get("trigger")
    if not isinstance(trigger, dict):
        return False, "schedule.trigger must be an object"
    ttype = trigger.get("type")
    if ttype not in _VALID_TYPES:
        return False, f"trigger.type must be one of {sorted(_VALID_TYPES)}"
    if ttype == "interval":
        if _interval_minutes(trigger) is None:
            return False, "interval trigger needs a positive every_minutes/hours/days"
    elif ttype == "daily":
        if _parse_hhmm(trigger.get("at")) is None:
            return False, "daily trigger needs 'at' as 'HH:MM' (24h, UTC)"
    elif ttype == "cron":
        if not _cron_supported():
            return False, "cron triggers require the 'croniter' package"
        if not trigger.get("expr"):
            return False, "cron trigger needs an 'expr'"
    return True, ""


def _cron_supported() -> bool:
    try:
        import croniter  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def _cron_due(expr: str, *, now: datetime, last_run_at: datetime | None) -> bool:
    """True if a cron firing falls in ``(last_run_at, now]`` (graceful if no lib)."""
    try:
        from croniter import croniter
    except Exception:  # noqa: BLE001
        logger.warning("scheduler: cron schedule skipped — croniter not installed")
        return False
    try:
        prev_fire = _as_aware_utc(croniter(expr, now).get_prev(datetime))
    except Exception as exc:  # noqa: BLE001 — bad expr must not crash the tick
        logger.warning("scheduler: invalid cron expr %r (%s)", expr, exc)
        return False
    if last_run_at is None:
        return True
    return prev_fire > last_run_at


def is_due(
    schedule: dict[str, Any],
    *,
    now: datetime | None = None,
    last_run_at: datetime | None = None,
) -> bool:
    """Decide whether ``schedule`` should fire at ``now``.

    ``last_run_at`` defaults to the schedule's own ``last_run_at`` field. A
    disabled or malformed schedule is never due.
    """
    if not isinstance(schedule, dict) or not schedule.get("enabled", True):
        return False
    trigger = schedule.get("trigger")
    if not isinstance(trigger, dict):
        return False

    now = _as_aware_utc(now or _utcnow())
    if last_run_at is None:
        last_run_at = parse_iso(schedule.get("last_run_at"))
    elif last_run_at is not None:
        last_run_at = _as_aware_utc(last_run_at)

    ttype = trigger.get("type")

    if ttype == "interval":
        minutes = _interval_minutes(trigger)
        if minutes is None:
            return False
        if last_run_at is None:
            return True  # never run -> run now
        return now - last_run_at >= timedelta(minutes=minutes)

    if ttype == "daily":
        at = _parse_hhmm(trigger.get("at"))
        if at is None:
            return False
        scheduled_today = now.replace(
            hour=at.hour, minute=at.minute, second=0, microsecond=0
        )
        if now < scheduled_today:
            return False  # today's slot hasn't arrived yet
        # Due if we haven't already run since today's slot opened.
        return last_run_at is None or last_run_at < scheduled_today

    if ttype == "cron":
        expr = trigger.get("expr")
        if not expr:
            return False
        return _cron_due(expr, now=now, last_run_at=last_run_at)

    return False


def due_schedules(
    schedules: list[dict[str, Any]] | None,
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return the subset of ``schedules`` that are due now.

    Returns the *same* dict references so the caller can stamp ``last_run_at``
    in place and write the list back to ``tenant.settings``.
    """
    if not schedules:
        return []
    now = _as_aware_utc(now or _utcnow())
    out: list[dict[str, Any]] = []
    for sched in schedules:
        try:
            if is_due(sched, now=now):
                out.append(sched)
        except Exception:  # noqa: BLE001 — one bad schedule must not skip the rest
            logger.exception("scheduler: is_due failed for %r", (sched or {}).get("id"))
    return out
