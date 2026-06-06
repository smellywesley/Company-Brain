import os
import hmac
import hashlib
import time
import json
import logging
from uuid import UUID
from typing import Any
from fastapi import APIRouter, HTTPException, Header, Request, status
from fastapi.responses import JSONResponse
import redis

logger = logging.getLogger("company_brain.webhooks")

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

# ── Configuration Secrets ───────────────────────────────────────────────────
SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET", "")
GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")

# Initialize Redis connection for idempotency / deduplication checks
# Using Upstash Redis or local fallback
redis_client = redis.from_url(os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"))

# ── Deduplication Helper ────────────────────────────────────────────────────
def _is_duplicate_event(event_id: str, expire_seconds: int = 86400) -> bool:
    """Check Redis to see if we have already processed this event ID."""
    if not event_id:
        return False
    key = f"webhook:processed:{event_id}"
    # setnx returns True if key was set (i.e. did not exist)
    was_set = redis_client.set(key, "1", ex=expire_seconds, nx=True)
    return not was_set


# ── Slack Signature Verification ─────────────────────────────────────────────
async def _verify_slack_signature(request: Request, body: bytes) -> bool:
    if not SLACK_SIGNING_SECRET:
        logger.error("Slack signing secret not configured")
        return False
    
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")

    # Prevent replay attacks: reject if timestamp is more than 5 minutes old
    if not timestamp or abs(time.time() - int(timestamp)) > 60 * 5:
        return False

    sig_basestring = f"v0:{timestamp}:".encode("utf-8") + body
    computed_signature = "v0=" + hmac.new(
        SLACK_SIGNING_SECRET.encode("utf-8"),
        sig_basestring,
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(computed_signature, signature)


# ── GitHub Signature Verification ────────────────────────────────────────────
async def _verify_github_signature(request: Request, body: bytes) -> bool:
    if not GITHUB_WEBHOOK_SECRET:
        logger.error("GitHub webhook secret not configured")
        return False

    signature = request.headers.get("X-Hub-Signature-256", "")
    if not signature.startswith("sha256="):
        return False

    computed_signature = "sha256=" + hmac.new(
        GITHUB_WEBHOOK_SECRET.encode("utf-8"),
        body,
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(computed_signature, signature)


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/slack")
async def slack_webhook(request: Request):
    """Receive and verify Slack Event API webhooks."""
    body = await request.body()
    
    # 1. Cryptographically verify signature
    if not await _verify_slack_signature(request, body):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Slack webhook signature"
        )

    event_data = json.loads(body.decode("utf-8"))

    # 2. Handle Slack URL Verification challenge
    if event_data.get("type") == "url_verification":
        return {"challenge": event_data.get("challenge")}

    event = event_data.get("event", {})
    event_id = event_data.get("event_id", "")

    # 3. Deduplicate events
    if _is_duplicate_event(event_id):
        logger.warning("Duplicate Slack event ID %s ignored", event_id)
        return {"status": "ignored", "reason": "duplicate"}

    # 4. Enqueue event to Celery worker asynchronously
    # (Slack expects a response within 3 seconds, so we don't block)
    from celery import Celery
    celery_app = Celery("company_brain", broker=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"))
    
    # Send task to Celery
    celery_app.send_task(
        "tasks.process_slack_webhook_event",
        args=[event_data],
        queue="default"
    )

    return {"status": "queued", "event_id": event_id}


@router.post("/github")
async def github_webhook(request: Request, x_github_event: str = Header(...)):
    """Receive and verify GitHub webhooks."""
    body = await request.body()

    # 1. Verify GitHub Signature
    if not await _verify_github_signature(request, body):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid GitHub webhook signature"
        )

    # Resolve event payload
    event_data = json.loads(body.decode("utf-8"))
    
    # GitHub doesn't send a unique event ID header in the body, but provides X-GitHub-Delivery
    delivery_id = request.headers.get("X-GitHub-Delivery", "")
    
    # 2. Deduplicate
    if delivery_id and _is_duplicate_event(delivery_id):
        logger.warning("Duplicate GitHub delivery ID %s ignored", delivery_id)
        return {"status": "ignored", "reason": "duplicate"}

    # 3. Enqueue event to Celery worker
    from celery import Celery
    celery_app = Celery("company_brain", broker=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"))
    
    celery_app.send_task(
        "tasks.process_github_webhook_event",
        args=[x_github_event, event_data],
        queue="default"
    )

    return {"status": "queued", "delivery_id": delivery_id}
