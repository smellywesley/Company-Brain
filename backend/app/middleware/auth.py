"""
OIDC / JWT Authentication Middleware for Company Brain.

Validates Bearer JWT tokens against an OIDC-compliant provider (e.g. Okta).
JWKS keys are fetched from the provider's .well-known endpoint and cached
to minimise network round-trips.

Usage:
    app.add_middleware(OIDCAuthMiddleware, oidc_issuer="https://…", audience="…")

OWASP considerations:
    - Token signature is verified against cached JWKS.
    - Clock-skew leeway is configurable but defaults to 30 s.
    - Expired / malformed / unsigned tokens are rejected with 401.
    - Public paths can be allow-listed to skip authentication.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

import httpx
import jwt
from jwt import PyJWKClient, PyJWKClientError
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger("company_brain.auth")


# ---------------------------------------------------------------------------
# Data-classes
# ---------------------------------------------------------------------------

@dataclass
class AuthenticatedUser:
    """Structured representation of the authenticated user attached to request.state."""

    sub: str
    email: Optional[str] = None
    groups: List[str] = field(default_factory=list)
    roles: List[str] = field(default_factory=list)
    # Tenant identifier carried in the token (custom claim). Used to scope every
    # request to one organisation. May be a UUID or a slug; resolution happens
    # in app.db.tenancy.resolve_tenant.
    tenant: Optional[str] = None
    raw_claims: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# JWKS cache wrapper
# ---------------------------------------------------------------------------

class _JWKSCache:
    """Thin wrapper around PyJWKClient that adds a TTL-based cache."""

    def __init__(self, jwks_uri: str, cache_ttl_seconds: int = 3600) -> None:
        self._jwks_uri = jwks_uri
        self._cache_ttl = cache_ttl_seconds
        self._client = PyJWKClient(jwks_uri, cache_keys=True, lifespan=cache_ttl_seconds)

    def get_signing_key(self, token: str) -> jwt.algorithms.RSAPublicKey:
        """Return the public key that matches the token's ``kid`` header."""
        signing_key = self._client.get_signing_key_from_jwt(token)
        return signing_key.key


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

DEFAULT_PUBLIC_PATHS: Set[str] = {
    "/health",
    "/metrics",  # Prometheus-format counters — a scraper can't carry OIDC
    "/docs",
    "/redoc",
    "/openapi.json",
    # Inbound from external systems that cannot carry a user bearer token.
    # These are NOT unauthenticated — each verifies its own credential:
    # webhooks check an HMAC signature; the OAuth callback verifies a signed
    # state token. "/oauth/connect" is deliberately NOT here: it stays behind
    # auth so tenant/user are derived from the session, not query params.
    "/webhooks",
    "/oauth/callback",
}


class OIDCAuthMiddleware(BaseHTTPMiddleware):
    """Starlette/FastAPI middleware that validates OIDC JWT bearer tokens.

    Parameters
    ----------
    app:
        The ASGI application.
    oidc_issuer:
        Base URL of the OIDC provider (e.g. ``https://dev-123.okta.com/oauth2/default``).
        If not supplied, falls back to the ``OIDC_ISSUER`` environment variable.
    audience:
        Expected ``aud`` claim value.  Falls back to ``OIDC_AUDIENCE`` env var.
    public_paths:
        Iterable of path prefixes that do **not** require authentication.
    leeway_seconds:
        Clock-skew tolerance for expiry validation.
    jwks_cache_ttl:
        How long (seconds) to cache JWKS keys before re-fetching.
    """

    def __init__(
        self,
        app: Any,
        oidc_issuer: Optional[str] = None,
        audience: Optional[str] = None,
        public_paths: Optional[Set[str]] = None,
        leeway_seconds: int = 30,
        jwks_cache_ttl: int = 3600,
    ) -> None:
        super().__init__(app)

        self.issuer: str = oidc_issuer or os.getenv("OIDC_ISSUER", "")
        self.audience: str = audience or os.getenv("OIDC_AUDIENCE", "")
        self.leeway: int = leeway_seconds
        self.public_paths: Set[str] = public_paths or DEFAULT_PUBLIC_PATHS

        if not self.issuer:
            logger.warning(
                "OIDC_ISSUER is not configured – all authenticated requests will be rejected."
            )

        # Derive JWKS URI from the issuer's .well-known endpoint
        jwks_uri = self._resolve_jwks_uri(self.issuer, jwks_cache_ttl)
        self._jwks_cache: Optional[_JWKSCache] = (
            _JWKSCache(jwks_uri, jwks_cache_ttl) if jwks_uri else None
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_jwks_uri(issuer: str, cache_ttl: int) -> Optional[str]:
        """Fetch ``jwks_uri`` from the OIDC discovery document."""
        if not issuer:
            return None

        well_known_url = f"{issuer.rstrip('/')}/.well-known/openid-configuration"
        try:
            response = httpx.get(well_known_url, timeout=10.0)
            response.raise_for_status()
            discovery = response.json()
            jwks_uri = discovery.get("jwks_uri")
            if jwks_uri:
                logger.info("JWKS URI resolved: %s", jwks_uri)
            return jwks_uri
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to fetch OIDC discovery document: %s", exc)
            return None

    def _is_public(self, path: str) -> bool:
        """Return ``True`` if *path* matches any configured public-path prefix."""
        return any(path.startswith(p) for p in self.public_paths)

    def _extract_bearer_token(self, request: Request) -> Optional[str]:
        """Extract the raw JWT from the ``Authorization: Bearer …`` header."""
        auth_header: Optional[str] = request.headers.get("Authorization")
        if not auth_header:
            return None
        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return None
        return parts[1]

    def _decode_and_validate(self, token: str) -> Dict[str, Any]:
        """Decode a JWT and validate signature, expiry, audience, and issuer.

        Raises
        ------
        jwt.PyJWTError
            On any validation failure.
        """
        if self._jwks_cache is None:
            raise jwt.PyJWTError("JWKS client is not initialised (missing issuer?)")

        public_key = self._jwks_cache.get_signing_key(token)

        claims: Dict[str, Any] = jwt.decode(
            token,
            public_key,
            algorithms=["RS256", "ES256"],
            audience=self.audience,
            issuer=self.issuer,
            leeway=self.leeway,
            options={
                "require": ["exp", "iss", "sub"],
                "verify_exp": True,
                "verify_iss": True,
                "verify_aud": bool(self.audience),
            },
        )
        return claims

    @staticmethod
    def _build_user(claims: Dict[str, Any]) -> AuthenticatedUser:
        """Map decoded JWT claims to an ``AuthenticatedUser``."""
        groups: List[str] = claims.get("groups", claims.get("cognito:groups", []))
        if isinstance(groups, str):
            groups = [groups]

        roles: List[str] = claims.get("roles", [])
        if isinstance(roles, str):
            roles = [roles]

        # Tenant claim — try common custom-claim names in priority order.
        tenant: Optional[str] = (
            claims.get("tenant_id")
            or claims.get("tenant")
            or claims.get("org_id")
            or claims.get("org")
        )
        if tenant is not None:
            tenant = str(tenant)

        return AuthenticatedUser(
            sub=claims["sub"],
            email=claims.get("email"),
            groups=groups,
            roles=roles,
            tenant=tenant,
            raw_claims=claims,
        )

    # ------------------------------------------------------------------
    # Middleware entry-point
    # ------------------------------------------------------------------

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Intercept every request, validate the JWT, and populate ``request.state.user``."""

        # Allow-listed paths skip authentication entirely.
        if self._is_public(request.url.path):
            return await call_next(request)

        # ------------------------------------------------------------------
        # DEV / DEMO ESCAPE HATCH — never enable in production.
        # When AUTH_BYPASS_DEV is truthy, inject a synthetic admin user so a
        # tokenless frontend (local demo) can reach authenticated endpoints.
        # Gated off by default; emits a loud warning on every request so it
        # can never be silently shipped.
        # ------------------------------------------------------------------
        from app.services.security.secret_config import is_production

        bypass_requested = os.getenv("AUTH_BYPASS_DEV", "").lower() in ("1", "true", "yes", "on")
        if bypass_requested and is_production():
            # Fail closed: never honour the escape hatch in production, even if
            # the env var leaks into the prod config.
            logger.error(
                "AUTH_BYPASS_DEV is set in a production environment — IGNORING it. "
                "Remove this variable from production config immediately."
            )
            bypass_requested = False

        if bypass_requested:
            logger.warning(
                "AUTH_BYPASS_DEV active — injecting synthetic admin user for %s %s. "
                "DO NOT USE IN PRODUCTION.",
                request.method,
                request.url.path,
            )
            request.state.user = AuthenticatedUser(
                sub="dev-bypass",
                email="dev@local",
                groups=["admin"],
                roles=["admin"],
                tenant=None,
                raw_claims={"bypass": True},
            )
            return await call_next(request)

        token = self._extract_bearer_token(request)
        if token is None:
            logger.info("Missing bearer token for %s %s", request.method, request.url.path)
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing authentication credentials"},
            )

        try:
            claims = self._decode_and_validate(token)
        except (jwt.ExpiredSignatureError,):
            logger.warning("Expired token for %s", request.url.path)
            return JSONResponse(status_code=401, content={"detail": "Token has expired"})
        except (jwt.InvalidAudienceError,):
            logger.warning("Invalid audience in token for %s", request.url.path)
            return JSONResponse(status_code=401, content={"detail": "Invalid token audience"})
        except (jwt.InvalidIssuerError,):
            logger.warning("Invalid issuer in token for %s", request.url.path)
            return JSONResponse(status_code=401, content={"detail": "Invalid token issuer"})
        except (jwt.PyJWTError, PyJWKClientError) as exc:
            logger.warning("JWT validation failed for %s: %s", request.url.path, exc)
            return JSONResponse(status_code=401, content={"detail": "Invalid or malformed token"})

        request.state.user = self._build_user(claims)

        logger.debug(
            "Authenticated user=%s path=%s",
            request.state.user.sub,
            request.url.path,
        )

        return await call_next(request)
