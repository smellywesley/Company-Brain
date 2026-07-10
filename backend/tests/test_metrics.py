"""Stdlib-only metrics registry + /metrics endpoint.

Groundwork counters in the Prometheus text exposition format — explicitly NOT
a Prometheus/OTel integration (no SDK, no scraper, per-process state).
"""

from app.services.observe import metrics


def setup_function(_fn):
    metrics.reset()


# ── registry / rendering ─────────────────────────────────────────────────────

def test_counter_without_labels_renders():
    metrics.inc("company_brain_budget_blocks_total")
    metrics.inc("company_brain_budget_blocks_total", amount=2)
    out = metrics.render()
    assert "# TYPE company_brain_budget_blocks_total counter" in out
    assert "company_brain_budget_blocks_total 3" in out
    # HELP line precedes the TYPE line
    assert out.index("# HELP company_brain_budget_blocks_total") < out.index(
        "# TYPE company_brain_budget_blocks_total"
    )


def test_labeled_counter_renders_per_label_set():
    metrics.inc("company_brain_workflow_runs_total", {"status": "blocked"})
    metrics.inc("company_brain_workflow_runs_total", {"status": "completed"})
    metrics.inc("company_brain_workflow_runs_total", {"status": "completed"})
    out = metrics.render()
    assert 'company_brain_workflow_runs_total{status="blocked"} 1' in out
    assert 'company_brain_workflow_runs_total{status="completed"} 2' in out
    # One TYPE header for the whole family, not one per label set
    assert out.count("# TYPE company_brain_workflow_runs_total counter") == 1


def test_empty_registry_renders_empty():
    assert metrics.render() == ""


def test_inc_never_raises_on_bad_input():
    metrics.inc("x", labels={"k": object()})  # unhashable-ish value scenarios
    # no exception is the assertion


# ── endpoint (auth exemption + content type) ─────────────────────────────────

def test_metrics_endpoint_public_and_plaintext(monkeypatch):
    monkeypatch.setenv("AUTH_BYPASS_DEV", "false")  # ensure exemption, not bypass
    monkeypatch.setenv("AUTO_CREATE_SCHEMA", "false")  # lifespan must not need a live DB
    from fastapi.testclient import TestClient
    from app.main import app

    metrics.inc("company_brain_quarantine_acquires_total")
    # No Authorization header at all — must still be reachable.
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert "company_brain_quarantine_acquires_total 1" in resp.text
