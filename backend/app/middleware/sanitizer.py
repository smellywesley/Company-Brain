"""
Input Sanitization & Security-Headers Middleware for Company Brain.

Two concerns are handled in a single module:

1. **SecurityHeadersMiddleware** – injects OWASP-recommended response
   headers (CSP, HSTS, X-Frame-Options, X-Content-Type-Options, etc.).

2. **InputSanitizationMiddleware** – intercepts incoming JSON request
   bodies, strips HTML tags, and blocks common SQL-injection patterns
   before the payload reaches route handlers.

OWASP considerations:
    - Content-Security-Policy restricts script / object sources.
    - HSTS enforces HTTPS for one year (including sub-domains).
    - XSS patterns and SQL injection patterns are detected and rejected.
    - HTML tags are stripped from all string values in JSON payloads.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Pattern, Set, Union

from starlette.datastructures import MutableHeaders
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger("company_brain.sanitizer")


# ---------------------------------------------------------------------------
# Security headers
# ---------------------------------------------------------------------------

_DEFAULT_SECURITY_HEADERS: Dict[str, str] = {
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "font-src 'self'; "
        "object-src 'none'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    ),
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "X-XSS-Protection": "0",  # Modern recommendation: rely on CSP instead
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), camera=(), microphone=()",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains; preload",
    "Cache-Control": "no-store",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Injects security-related HTTP response headers.

    Parameters
    ----------
    app:
        The ASGI application.
    extra_headers:
        Additional or overriding headers merged with the defaults.
    """

    def __init__(self, app: Any, extra_headers: Optional[Dict[str, str]] = None) -> None:
        super().__init__(app)
        self.headers = {**_DEFAULT_SECURITY_HEADERS, **(extra_headers or {})}

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)
        for name, value in self.headers.items():
            response.headers[name] = value
        return response


# ---------------------------------------------------------------------------
# XSS / SQL-injection patterns
# ---------------------------------------------------------------------------

# HTML tag stripper (greedy – removes all HTML-like elements)
_HTML_TAG_RE: Pattern[str] = re.compile(r"<[^>]+>")

# Common XSS vectors (case-insensitive)
_XSS_PATTERNS: List[Pattern[str]] = [
    re.compile(r"<\s*script", re.IGNORECASE),
    re.compile(r"javascript\s*:", re.IGNORECASE),
    re.compile(r"on\w+\s*=", re.IGNORECASE),          # onclick=, onerror=, …
    re.compile(r"<\s*iframe", re.IGNORECASE),
    re.compile(r"<\s*object", re.IGNORECASE),
    re.compile(r"<\s*embed", re.IGNORECASE),
    re.compile(r"<\s*svg[^>]*onload", re.IGNORECASE),
    re.compile(r"expression\s*\(", re.IGNORECASE),     # CSS expression()
    re.compile(r"vbscript\s*:", re.IGNORECASE),
    re.compile(r"data\s*:\s*text/html", re.IGNORECASE),
]

# Common SQL-injection patterns
_SQL_PATTERNS: List[Pattern[str]] = [
    re.compile(r"(\b(union)\b.*\b(select)\b)", re.IGNORECASE),
    re.compile(r"(\b(insert)\b.*\b(into)\b)", re.IGNORECASE),
    re.compile(r"(\b(drop)\b.*\b(table|database)\b)", re.IGNORECASE),
    re.compile(r"(\b(delete)\b.*\b(from)\b)", re.IGNORECASE),
    re.compile(r"(\b(update)\b.*\b(set)\b)", re.IGNORECASE),
    re.compile(r"(--|#|/\*)\s*$", re.MULTILINE),  # SQL comment terminators
    re.compile(r"'\s*(or|and)\s+\d+\s*=\s*\d+", re.IGNORECASE),  # ' or 1=1
    re.compile(r"\b(or|and)\s+\d+\s*=\s*\d+", re.IGNORECASE),  # boolean tautology: 1 OR 1=1
    re.compile(r";\s*(drop|alter|create|truncate)\b", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Sanitization helpers
# ---------------------------------------------------------------------------

def _contains_xss(value: str) -> bool:
    """Return ``True`` if *value* matches any known XSS pattern."""
    return any(p.search(value) for p in _XSS_PATTERNS)


def _contains_sql_injection(value: str) -> bool:
    """Return ``True`` if *value* matches any known SQL-injection pattern."""
    return any(p.search(value) for p in _SQL_PATTERNS)


def _strip_html(value: str) -> str:
    """Remove all HTML tags from *value*."""
    return _HTML_TAG_RE.sub("", value)


def _sanitize_value(value: Any) -> Any:
    """Recursively sanitize a JSON-decoded value.

    - Strings: strip HTML tags.
    - Dicts / Lists: recurse.
    - Other types: pass through unchanged.
    """
    if isinstance(value, str):
        return _strip_html(value)
    if isinstance(value, dict):
        return {k: _sanitize_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_value(v) for v in value]
    return value


def _detect_malicious_strings(value: Any, path: str = "$") -> Optional[str]:
    """Walk a JSON-decoded structure and return a description of the first
    malicious pattern detected, or ``None`` if clean."""
    if isinstance(value, str):
        if _contains_xss(value):
            return f"Potential XSS payload detected at {path}"
        if _contains_sql_injection(value):
            return f"Potential SQL injection detected at {path}"
    elif isinstance(value, dict):
        for k, v in value.items():
            result = _detect_malicious_strings(v, f"{path}.{k}")
            if result:
                return result
    elif isinstance(value, list):
        for idx, v in enumerate(value):
            result = _detect_malicious_strings(v, f"{path}[{idx}]")
            if result:
                return result
    return None


# ---------------------------------------------------------------------------
# Input sanitization middleware
# ---------------------------------------------------------------------------

_METHODS_WITH_BODY: Set[str] = {"POST", "PUT", "PATCH"}


class InputSanitizationMiddleware(BaseHTTPMiddleware):
    """Intercepts JSON request bodies, detects XSS/SQL-injection patterns,
    and strips HTML tags from all string values.

    Parameters
    ----------
    app:
        The ASGI application.
    block_on_detection:
        If ``True`` (default), requests containing malicious patterns are
        rejected with ``400 Bad Request``.  If ``False``, the offending
        content is sanitised but allowed through.
    exempt_paths:
        Set of path prefixes that bypass sanitization.
    """

    def __init__(
        self,
        app: Any,
        block_on_detection: bool = True,
        exempt_paths: Optional[Set[str]] = None,
    ) -> None:
        super().__init__(app)
        self.block_on_detection = block_on_detection
        self.exempt_paths: Set[str] = exempt_paths or {"/health", "/docs", "/redoc", "/openapi.json"}

    def _is_exempt(self, path: str) -> bool:
        return any(path.startswith(p) for p in self.exempt_paths)

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Only inspect methods that carry a body
        if (
            request.method not in _METHODS_WITH_BODY
            or self._is_exempt(request.url.path)
        ):
            return await call_next(request)

        content_type = request.headers.get("content-type", "")
        if "application/json" not in content_type:
            return await call_next(request)

        # Read and parse JSON body
        body_bytes = await request.body()
        if not body_bytes:
            return await call_next(request)

        try:
            payload = json.loads(body_bytes)
        except (json.JSONDecodeError, ValueError):
            # Not valid JSON – let downstream handle the error
            return await call_next(request)

        # Detect malicious patterns
        threat = _detect_malicious_strings(payload)
        if threat:
            logger.warning(
                "Blocked malicious input: %s | path=%s ip=%s",
                threat,
                request.url.path,
                request.client.host if request.client else "unknown",
            )
            if self.block_on_detection:
                return JSONResponse(
                    status_code=400,
                    content={"detail": "Request blocked: malicious content detected"},
                )

        # Sanitize (strip HTML) regardless
        sanitized = _sanitize_value(payload)

        # Replace request body with sanitized version so downstream reads clean data
        sanitized_bytes = json.dumps(sanitized).encode("utf-8")

        # We override the internal _body cache used by Starlette
        request._body = sanitized_bytes  # noqa: SLF001

        return await call_next(request)
