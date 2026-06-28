"""
Cryptographic Skill Signing (HMAC-SHA256).

Signs skill definitions so that any manual tampering in the database
can be detected at runtime. Uses Python's built-in hmac and hashlib.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os

logger = logging.getLogger(__name__)


class SkillSigner:
    """Signs and verifies skill definitions using HMAC-SHA256."""

    def __init__(self, signing_key: str | None = None) -> None:
        # Only fall back to env when caller passes None (not set), not when they explicitly pass ""
        resolved = signing_key if signing_key is not None else os.getenv("SKILL_SIGNING_KEY", "")
        self._key = resolved.encode("utf-8")
        if not self._key:
            logger.warning("SkillSigner: No signing key configured. Signatures will be empty.")

    def sign(self, definition: dict) -> str:
        """Produce an HMAC-SHA256 hex digest of the definition.

        The definition is serialized with sorted keys and no whitespace
        to guarantee deterministic output regardless of dict ordering.
        """
        if not self._key:
            return ""
        canonical = json.dumps(definition, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hmac.new(self._key, canonical, hashlib.sha256).hexdigest()

    def verify(self, definition: dict, signature: str) -> bool:
        """Verify a definition against its stored signature.

        Uses hmac.compare_digest for constant-time comparison to
        prevent timing attacks.
        """
        if not self._key:
            logger.warning("SkillSigner: Cannot verify — no signing key configured.")
            return False
        if not signature:
            logger.warning("SkillSigner: Cannot verify — no signature provided.")
            return False
        expected = self.sign(definition)
        valid = hmac.compare_digest(expected, signature)
        if not valid:
            logger.error("SkillSigner: SIGNATURE MISMATCH — skill definition may have been tampered with!")
        return valid
