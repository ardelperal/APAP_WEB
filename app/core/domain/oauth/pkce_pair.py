"""PKCE (Proof Key for Code Exchange) domain value object.

A :class:`PkcePair` is the (verifier, challenge) tuple minted at the
start of the OAuth flow. The verifier is the random secret held in
the short-lived ``apap_pkce`` cookie until the callback; the
challenge is the SHA-256 of the verifier, sent to the authorization
server in the auth request (RFC 7636).

The actual generation lives in :func:`app.core.pkce.generate_pkce_pair`
(an :class:`app.core.insforge`-free helper that uses
:mod:`secrets` and :mod:`hashlib`). The adapter calls it and wraps
the tuple in a :class:`PkcePair` so the application layer sees a
typed value object rather than a bare ``tuple[str, str]``.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PkcePair:
    """A freshly minted PKCE (verifier, challenge) pair.

    Attributes:
        code_verifier: A 43-character URL-safe base64 string (the
            RFC 7636-recommended 256-bit secret). The route stores
            this in the ``apap_pkce`` cookie.
        code_challenge: The SHA-256 of the verifier, encoded the same
            way. The adapter sends this to the authorization server
            in the auth request.
    """

    code_verifier: str
    code_challenge: str


__all__ = ["PkcePair"]
