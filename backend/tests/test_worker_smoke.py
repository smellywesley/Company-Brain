"""
Worker smoke test.

Proves the Celery app is importable, the expected tasks are registered, and the
no-side-effect ``tasks.ping`` task runs end to end (eager mode — no live broker
needed). The live enqueue→consume proof against the compose Redis broker is the
documented command in the ping task's docstring / DEPLOY.md.
"""

from __future__ import annotations

import pytest

pytest.importorskip("celery")

from app.worker import celery_app, ping

_EXPECTED_TASKS = {
    "tasks.ping",
    "tasks.accumulate_llm_cost",
    "tasks.scheduler_tick",
    "tasks.execute_scheduled_workflow",
    "tasks.process_feedback",
    "tasks.process_ingestion_batch",
    "tasks.trigger_skill_discovery",
}


def test_expected_tasks_registered():
    registered = set(celery_app.tasks.keys())
    missing = _EXPECTED_TASKS - registered
    assert not missing, f"tasks missing from registry: {missing}"


def test_broker_configured():
    assert celery_app.conf.broker_url, "Celery broker_url must be configured"


def test_ping_runs_eagerly_and_echoes():
    # apply() runs the task in-process (no broker) and returns an EagerResult.
    result = ping.apply(args=["hello"]).get()
    assert result["ok"] is True
    assert result["echo"] == "hello"


def test_ping_default_echo():
    result = ping.apply().get()
    assert result["echo"] == "pong"
