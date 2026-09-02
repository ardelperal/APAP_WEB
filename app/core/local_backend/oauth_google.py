"""OAuth flow stub (M0 of self-host-backend-coolify).

The full implementation will follow the next TDD step. M0 stubs the
endpoints that ``InsForgeClient.start_google_oauth`` and
``InsForgeClient.exchange_google_oauth_code`` call so the integration
tests for the rest of the local backend can pass without a real
Google OAuth provider.

The stub returns:
- ``POST /api/auth/oauth/google?code_challenge=...&redirect_uri=...``
  → ``{"authUrl": "https://accounts.google.com/o/oauth2/v2/auth?..."}``
- ``POST /api/auth/oauth/google/callback`` with code, code_verifier, redirect_uri
  → ``{"token": "<session_jwt>", "user": {"id": "local-user", "email": "local@apap"}}``

M3 will replace this with a real Google OAuth provider; the JWT
generation and the URL shape are stable contracts that
``InsForgeClient`` consumes.
"""

from __future__ import annotations

import json
import base64
import hashlib
import hmac
import os
import time

from fastapi import APIRouter, Form, Query

router = APIRouter()


def _make_signed_jwt(email: str) -> str:
    """Return a minimal signed JWT for the stub OAuth response.

    The real InsForge returns a JWT signed with a service key. M0
    stubs the shape (header.payload.signature) so the client can parse
    it; the signature is not verified in M0 (the client just sets a
    cookie and reads the payload). M3 uses a real signing key.
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


@router.post("/auth/oauth/google")
async def start_google_oauth(
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
async def google_oauth_callback(
    code: str = Form(...),
    code_verifier: str = Form(...),
    redirect_uri: str = Form(...),
) -> dict:
    """Return a stub session JWT (M0).

    The real implementation validates the Google code with PKCE and
    signs the JWT with the service key. M0 returns a deterministic JWT
    for the test, no validation.
    """
    return {
        "token": _make_signed_jwt("local@apap"),
        "user": {"id": "local-user", "email": "local@apap"},
    }
