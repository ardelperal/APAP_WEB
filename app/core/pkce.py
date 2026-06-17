"""PKCE (Proof Key for Code Exchange) helpers for OAuth 2.0.

Generates the ``code_verifier`` (a random secret held in the session
until the callback) and the ``code_challenge`` (the SHA-256 hash of
the verifier, sent to the authorization server in the auth request).
"""

from __future__ import annotations

import base64
import hashlib
import secrets


def _b64url_no_pad(raw: bytes) -> str:
    """Base64 URL-safe with padding stripped (RFC 7636)."""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def generate_pkce_pair() -> tuple[str, str]:
    """Return a fresh ``(code_verifier, code_challenge)`` tuple.

    The verifier is 32 random bytes (256 bits) encoded as URL-safe
    base64 without padding (43 ASCII characters). The challenge is
    the SHA-256 of the verifier encoded the same way.
    """
    verifier = _b64url_no_pad(secrets.token_bytes(32))
    challenge = _b64url_no_pad(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge
