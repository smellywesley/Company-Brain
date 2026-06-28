"""
Optional error tracking (Sentry).

Sentry is wired only when ``SENTRY_DSN`` is set AND the ``sentry-sdk`` package
is installed — exactly like Langfuse, so the lean image stays slim and dev runs
need no DSN. When either is missing, error tracking is disabled and we say so in
the logs (no silent "it's on" assumption).

Prometheus / OpenTelemetry metrics are NOT wired here — see DEPLOY.md
("Observability") for the documented next step. We do not claim metrics we
don't emit.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("company_brain.observe")


def init_sentry() -> bool:
    """Initialise Sentry if configured. Returns True if active. Never raises."""
    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        logger.info("Error tracking: disabled (no SENTRY_DSN set).")
        return False

    try:
        import sentry_sdk
    except ImportError:
        logger.warning("Error tracking: SENTRY_DSN set but sentry-sdk not installed — disabled.")
        return False

    try:
        sentry_sdk.init(
            dsn=dsn,
            environment=os.getenv("ENVIRONMENT", "local"),
            release=os.getenv("APP_RELEASE", "company-brain@0.2.0"),
            # Conservative defaults; tune via env for production load.
            traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.0")),
            send_default_pii=False,  # never ship PII to the error tracker
        )
        logger.info("Error tracking: Sentry initialised (env=%s).", os.getenv("ENVIRONMENT", "local"))
        return True
    except Exception as exc:  # noqa: BLE001 — observability must not break boot
        logger.warning("Error tracking: Sentry init failed (%s) — disabled.", exc)
        return False
