"""OAuth flow handlers for the local backend (M0 of self-host-backend-coolify).

Three endpoints mirror what ``LocalPostgresExecutor`` consumes for the
Google OAuth proxy flow:

- ``GET  /api/auth/oauth/google`` (start) → ``{"authUrl": "https://..."}``
- ``POST /api/auth/oauth/google/callback`` (legacy direct Google) →
  ``{"token": "<jwt>", "user": {"id", "email"}}``
- ``POST /api/auth/oauth/exchange`` (InsForge-hosted proxy) →
  ``{"user": {"id", "email"}, "accessToken": "<jwt>", "csrfToken": "..."}``

M0 stubs the URL and the JWT deterministically so the rest of the
integration tests pass without a real Google OAuth provider. M3 swaps
in the real Google OAuth and a proper signing key.

Hard rules (web-tdd-philosophy):
- Rule 4 (no humo): tests assert return shapes and the JWT structure
  (3 dot-separated parts), never absence-of-error.
- Rule 8 (no production mutation): the JWT is signed with a stub secret;
  no real OAuth provider contacted.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

from fastapi import APIRouter, Query

router = APIRouter()


def _make_signed_jwt(email: str) -> str:
    """Return a minimal signed JWT for the stub OAuth response.

    The real InsForge returns a JWT signed with a service key. M0
    stubs the shape (``header.payload.signature``) so the client can
    parse it; the signature is not verified in M0 (the client just
    sets a cookie and reads the payload). M3 uses a real signing key.
    """
    secret = os.environ.get("APAP_SESSION_SECRET", "stub-secret").encode()
    header = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').rstrip(b"=").decode()
    payload = json.dumps(
        {
            "email": email,
            "sub": "local-user",
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        }
    ).encode()
    payload_b64 = base64.urlsafe_b64encode(payload).rstrip(b"=").decode()
    signature = hmac.new(secret, f"{header}.{payload_b64}".encode(), hashlib.sha256).digest()
    signature_b64 = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
    return f"{header}.{payload_b64}.{signature_b64}"


_LOCAL_USER = {"id": "local-user", "email": "local@apap"}


@router.get("/auth/oauth/google")
def start_google_oauth(
    redirect_uri: str = Query(...),
    code_challenge: str = Query(...),
) -> dict:
    """Return a stub Google auth URL (M0).

    The real implementation calls Google OAuth with PKCE and state.
    M0 just returns a deterministic URL — the client only reads
    ``authUrl`` to redirect the user, so the test only needs the shape
    to be correct.
    """
    return {
        "authUrl": (
            f"https://accounts.google.com/o/oauth2/v2/auth"
            f"?client_id=stub"
            f"&redirect_uri={redirect_uri}"
            f"&response_type=code"
            f"&scope=openid+email"
            f"&code_challenge={code_challenge}"
            f"&code_challenge_method=S256"
        )
    }


@router.post("/auth/oauth/google/callback")
def google_oauth_callback(payload: dict) -> dict:
    """Return a stub session JWT (M0) for the legacy direct-callback path.

    The real implementation validates the Google code with PKCE and
    signs the JWT with the service key. M0 returns a deterministic JWT
    for the test, no validation. Body is JSON (matches what
    ``LocalPostgresExecutor.exchange_google_oauth_code`` sends).
    """
    return {
        "token": _make_signed_jwt(_LOCAL_USER["email"]),
        "user": dict(_LOCAL_USER),
    }


@router.post("/auth/oauth/exchange")
def exchange_insforge_oauth_code(
    payload: dict,
    client_type: str = Query("web"),
) -> dict:
    """Return a stub session JWT (M0) for the InsForge-hosted OAuth proxy.

    The real implementation validates the InsForge one-time code with
    PKCE and signs the JWT with the service key. M0 returns a
    deterministic JWT for the test, no validation. Body is JSON
    (matches what ``LocalPostgresExecutor.exchange_insforge_oauth_code``
    sends).
    """
    # ``client_type`` is accepted for parity with the real endpoint but
    # the stub does not branch on it (web / mobile produce the same
    # payload shape).
    _ = client_type
    return {
        "user": dict(_LOCAL_USER),
        "accessToken": _make_signed_jwt(_LOCAL_USER["email"]),
        "csrfToken": "stub-csrf-token",
    }


__all__ = [
    "router",
    "start_google_oauth",
    "google_oauth_callback",
    "exchange_insforge_oauth_code",
]
