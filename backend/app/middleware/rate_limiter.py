"""
Token-Bucket Rate Limiter Middleware for Company Brain.

Enforces per-user (or per-IP for unauthenticated requests) rate limits
using a token-bucket algorithm.  Limits are configurable and two tiers
are supported out of the box:

- **default** – general API traffic (100 requests / minute)
- **workflow** – expensive workflow-execution endpoints (10 requests / minute)

On top of the per-user/IP bucket, requests carrying a tenant claim also
consume from a per-tenant bucket (``RATE_LIMIT_TENANT_MAX``, default 500/min)
shared by every user in that tenant. This closes the gap where the per-tenant
*LLM budget* was enforced (see ``app.services.budget.limiter``) but nothing
stopped a tenant's aggregate *request rate* from ballooning across many users.
The tenant bucket is consumed only after the per-user/IP bucket passes, so a
single over-limit tenant can't starve other tenants, while individual users in
a healthy tenant still get their own per-user protection too.

When the bucket is empty the middleware returns ``429 Too Many Requests``
with a ``Retry-After`` header indicating how many seconds the client
should wait.

The current implementation uses an in-memory store; a Redis backend can
be swapped in later by replacing ``_InMemoryBucketStore``.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger("company_brain.rate_limiter")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class RateLimitTier:
    """Defines a rate-limit bucket configuration.

    Parameters
    ----------
    name:
        Human-readable tier name.
    max_tokens:
        Maximum number of tokens (burst capacity).
    refill_rate:
        Tokens added per second.
    path_patterns:
        Regex patterns that, if matched against the request path, assign
        the request to this tier.
    """

    name: str
    max_tokens: int
    refill_rate: float
    path_patterns: List[re.Pattern[str]] = field(default_factory=list)

    def matches(self, path: str) -> bool:
        """Return ``True`` if *path* matches any of the tier's patterns."""
        return any(p.search(path) for p in self.path_patterns)


# Default tiers
_DEFAULT_TIERS: List[RateLimitTier] = [
    RateLimitTier(
        name="workflow",
        max_tokens=int(os.getenv("RATE_LIMIT_WORKFLOW_MAX", "10")),
        refill_rate=int(os.getenv("RATE_LIMIT_WORKFLOW_MAX", "10")) / 60.0,
        path_patterns=[re.compile(r"^/workflow")],
    ),
    RateLimitTier(
        name="default",
        max_tokens=int(os.getenv("RATE_LIMIT_DEFAULT_MAX", "100")),
        refill_rate=int(os.getenv("RATE_LIMIT_DEFAULT_MAX", "100")) / 60.0,
        path_patterns=[],  # catch-all
    ),
]

# Per-tenant request-rate budget (distinct from the per-user/IP tiers above and
# from the per-tenant *LLM cost* budget in app.services.budget.limiter). Shared
# across every user belonging to the tenant so one tenant can't starve others,
# even though each individual user is still also under their own tier bucket.
_TENANT_MAX = int(os.getenv("RATE_LIMIT_TENANT_MAX", "500"))
_TENANT_REFILL_RATE = _TENANT_MAX / 60.0


# ---------------------------------------------------------------------------
# Bucket store (in-memory, thread-safe)
# ---------------------------------------------------------------------------

@dataclass
class _Bucket:
    """A single token bucket. Thread-safe: all token mutation happens under
    the per-bucket lock so concurrent requests cannot both pass on the same
    token."""

    tokens: float
    max_tokens: int
    refill_rate: float
    last_refill: float = field(default_factory=time.monotonic)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def consume(self) -> bool:
        """Try to consume one token. Returns ``True`` on success."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            # Refill
            self.tokens = min(self.max_tokens, self.tokens + elapsed * self.refill_rate)
            self.last_refill = now

            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return True
            return False

    @property
    def retry_after(self) -> int:
        """Seconds until at least one token is available."""
        with self._lock:
            if self.tokens >= 1.0:
                return 0
            if self.refill_rate <= 0:
                # A never-refilling bucket (e.g. a max of 0 via env misconfig)
                # must still 429 cleanly, not 500 on division by zero.
                return 60
            deficit = 1.0 - self.tokens
            return max(1, int(deficit / self.refill_rate) + 1)


class _InMemoryBucketStore:
    """Thread-safe in-memory store for token buckets, keyed by
    ``(client_id, tier_name)``."""

    def __init__(self) -> None:
        self._buckets: Dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def get_or_create(
        self, key: str, max_tokens: int, refill_rate: float
    ) -> _Bucket:
        with self._lock:
            if key not in self._buckets:
                self._buckets[key] = _Bucket(
                    tokens=float(max_tokens),
                    max_tokens=max_tokens,
                    refill_rate=refill_rate,
                )
            return self._buckets[key]


# Module-level store instance
_store = _InMemoryBucketStore()


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

class RateLimiterMiddleware(BaseHTTPMiddleware):
    """Starlette/FastAPI middleware that enforces per-client rate limits.

    Parameters
    ----------
    app:
        The ASGI application.
    tiers:
        Ordered list of :class:`RateLimitTier` configs.  The first tier
        whose ``path_patterns`` match wins.  If none match, the last tier
        is used as a catch-all.
    exempt_paths:
        Set of path prefixes that are never rate-limited (e.g. ``/health``).
    """

    def __init__(
        self,
        app: Any,
        tiers: Optional[List[RateLimitTier]] = None,
        exempt_paths: Optional[Set[str]] = None,
    ) -> None:
        super().__init__(app)
        self.tiers = tiers or _DEFAULT_TIERS
        self.exempt_paths: Set[str] = exempt_paths or {"/health", "/docs", "/redoc", "/openapi.json"}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _client_id(request: Request) -> str:
        """Derive a stable client identifier: authenticated user sub, or IP.

        The IP comes from the direct TCP peer by default. ``X-Forwarded-For`` is
        only honoured when ``TRUSTED_PROXY_COUNT`` is set (number of trusted
        hops in front of the app), in which case the entry added by the trusted
        edge — the ``count``-th from the right — is used. Trusting the left-most
        XFF entry lets a client spoof the header and mint unlimited buckets.
        """
        user = getattr(request.state, "user", None)
        if user is not None and getattr(user, "sub", None):
            return f"user:{user.sub}"

        peer = request.client.host if request.client else "unknown"
        try:
            trusted = int(os.getenv("TRUSTED_PROXY_COUNT", "0"))
        except ValueError:
            trusted = 0
        if trusted > 0:
            chain = [p.strip() for p in request.headers.get("X-Forwarded-For", "").split(",") if p.strip()]
            if len(chain) >= trusted:
                peer = chain[-trusted]
        return f"ip:{peer}"

    def _resolve_tier(self, path: str) -> RateLimitTier:
        """Return the first matching tier for *path*, or the last (catch-all)."""
        for tier in self.tiers:
            if tier.matches(path):
                return tier
        return self.tiers[-1]

    def _is_exempt(self, path: str) -> bool:
        return any(path.startswith(p) for p in self.exempt_paths)

    @staticmethod
    def _tenant_claim(request: Request) -> Optional[str]:
        """Return the tenant claim on the request, or ``None`` if absent.

        Unauthenticated traffic (no ``request.state.user``) or a token with no
        tenant claim has no tenant bucket to check — it's still covered by the
        per-user/IP bucket above.
        """
        user = getattr(request.state, "user", None)
        return getattr(user, "tenant", None) if user is not None else None

    @staticmethod
    def _429(client: str, tier_name: str, bucket: "_Bucket") -> JSONResponse:
        retry_after = bucket.retry_after
        logger.warning(
            "Rate limit exceeded: client=%s tier=%s retry_after=%ds",
            client,
            tier_name,
            retry_after,
        )
        return JSONResponse(
            status_code=429,
            content={
                "detail": "Rate limit exceeded. Please slow down.",
                "retry_after_seconds": retry_after,
            },
            headers={"Retry-After": str(retry_after)},
        )

    # ------------------------------------------------------------------
    # Middleware entry-point
    # ------------------------------------------------------------------

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if self._is_exempt(request.url.path):
            return await call_next(request)

        tier = self._resolve_tier(request.url.path)
        client = self._client_id(request)
        bucket_key = f"{client}:{tier.name}"

        bucket = _store.get_or_create(bucket_key, tier.max_tokens, tier.refill_rate)

        if not bucket.consume():
            return self._429(client, tier.name, bucket)

        # Per-tenant bucket, consumed only after the per-user/IP bucket passes,
        # so it can't be used to starve a healthy tenant's individual users.
        tenant_claim = self._tenant_claim(request)
        if tenant_claim:
            tenant_key = f"tenant:{tenant_claim}:{tier.name}"
            tenant_bucket = _store.get_or_create(tenant_key, _TENANT_MAX, _TENANT_REFILL_RATE)
            if not tenant_bucket.consume():
                return self._429(f"tenant:{tenant_claim}", tier.name, tenant_bucket)

        response = await call_next(request)
        return response
