"""
Audit Logging Middleware for Company Brain.

Records every HTTP request/response with structured metadata and writes
tamper-evident JSON log entries (one object per line).  Each entry carries
an HMAC-SHA256 signature of the previous entry, forming a verifiable chain
of trust.

A standalone helper ``log_agent_action`` is provided for auditing
autonomous agent decisions.

OWASP considerations:
    - Request bodies are **never** logged; only a SHA-256 hash is stored.
    - HMAC chain allows offline tamper-detection of the log file.
    - Structured JSON enables downstream SIEM ingestion.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("company_brain.audit")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

from app.services.security.secret_config import require_secret

_AUDIT_LOG_DIR = Path(os.getenv("AUDIT_LOG_DIR", "logs"))
_AUDIT_LOG_FILE = _AUDIT_LOG_DIR / "audit.jsonl"
# Fail closed in production: a default/weak secret makes the tamper-evident
# chain forgeable, defeating the entire audit guarantee.
_HMAC_SECRET = require_secret("AUDIT_HMAC_SECRET", min_length=32).encode()

# Module-level state for the HMAC chain.
# The lock serializes read-modify-write of _last_hmac + file append so the
# tamper-evident chain stays consistent under concurrent requests.
_last_hmac: str = "GENESIS"
_chain_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sha256_hash(data: bytes) -> str:
    """Return hex-encoded SHA-256 digest of *data*."""
    return hashlib.sha256(data).hexdigest()


def _compute_hmac(payload: str, previous_hmac: str) -> str:
    """Compute HMAC-SHA256 of *payload* keyed by the global secret and the
    *previous_hmac* value, creating a chain dependency."""
    message = f"{previous_hmac}:{payload}"
    return hmac.new(_HMAC_SECRET, message.encode(), hashlib.sha256).hexdigest()


def _ensure_log_dir() -> None:
    """Create the log directory if it does not exist."""
    _AUDIT_LOG_DIR.mkdir(parents=True, exist_ok=True)


def _write_entry(entry: Dict[str, Any]) -> None:
    """Append a single JSON line to the audit log file, computing and
    attaching the HMAC chain signature.

    The entire read-modify-write of ``_last_hmac`` plus the file append runs
    under ``_chain_lock`` so concurrent requests cannot interleave and break
    the tamper-evident chain (two entries sharing the same ``_prev_hmac``)."""
    global _last_hmac  # noqa: PLW0603

    with _chain_lock:
        payload = json.dumps(entry, sort_keys=True, default=str)
        entry_hmac = _compute_hmac(payload, _last_hmac)
        entry["_chain_hmac"] = entry_hmac
        entry["_prev_hmac"] = _last_hmac
        _last_hmac = entry_hmac

        _ensure_log_dir()
        with open(_AUDIT_LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, sort_keys=True, default=str) + "\n")


# ---------------------------------------------------------------------------
# Request / Response audit middleware
# ---------------------------------------------------------------------------

class AuditLogMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that logs structured audit records for every
    request/response cycle.

    Fields recorded per entry:
    - ``timestamp`` – ISO-8601 in UTC
    - ``user`` – subject claim (or ``"anonymous"``)
    - ``method`` – HTTP method
    - ``path`` – URL path
    - ``status_code`` – response status
    - ``request_body_hash`` – SHA-256 digest of the raw body (never the body itself)
    - ``response_time_ms`` – wall-clock duration
    - ``ip_address`` – client IP
    - ``_chain_hmac`` / ``_prev_hmac`` – tamper-detection chain
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        start = time.perf_counter()

        # Read body bytes for hashing (then reassign so downstream can read)
        body_bytes = await request.body()
        body_hash = _sha256_hash(body_bytes) if body_bytes else ""

        # Execute downstream
        response: Response = await call_next(request)

        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)

        # Determine user from request.state (set by OIDCAuthMiddleware)
        user_sub: str = "anonymous"
        user = getattr(request.state, "user", None)
        if user is not None:
            user_sub = getattr(user, "sub", "anonymous")

        # Client IP – respect X-Forwarded-For behind a reverse proxy
        client_ip = (
            request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or (request.client.host if request.client else "unknown")
        )

        entry: Dict[str, Any] = {
            "type": "http_request",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user": user_sub,
            "method": request.method,
            "path": str(request.url.path),
            "status_code": response.status_code,
            "request_body_hash": body_hash,
            "response_time_ms": elapsed_ms,
            "ip_address": client_ip,
        }

        try:
            _write_entry(entry)
        except Exception:  # noqa: BLE001 – logging must never crash the app
            logger.exception("Failed to write audit log entry")

        return response


# ---------------------------------------------------------------------------
# Agent-level auditing
# ---------------------------------------------------------------------------

def log_agent_action(
    agent_name: str,
    action: str,
    input_hash: str,
    output_hash: str,
    verdict: str,
    *,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Write a structured audit entry for an autonomous agent action.

    Parameters
    ----------
    agent_name:
        Identifier of the agent (e.g. ``"IngestionAgent"``).
    action:
        Description of the action performed.
    input_hash:
        SHA-256 hash of the input data the agent received.
    output_hash:
        SHA-256 hash of the output / artefact the agent produced.
    verdict:
        Human-readable verdict or rationale (e.g. ``"approved"``, ``"blocked"``).
    extra:
        Optional dictionary of additional metadata.
    """
    entry: Dict[str, Any] = {
        "type": "agent_action",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent_name": agent_name,
        "action": action,
        "input_hash": input_hash,
        "output_hash": output_hash,
        "verdict": verdict,
    }
    if extra:
        entry["extra"] = extra

    try:
        _write_entry(entry)
        logger.info(
            "Agent audit: agent=%s action=%s verdict=%s",
            agent_name,
            action,
            verdict,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Failed to write agent audit entry")
