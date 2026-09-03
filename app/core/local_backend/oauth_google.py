"""OAuth flow stubs for the local backend (M0).

M0 ships three endpoints that pretend to drive a Google OAuth handshake
and to exchange an ``insforge_code`` for a session JWT. The integration
with Google itself is M1; here the handlers are honest stubs that return
deterministic, signed tokens so the front-end and the local backend can
exercise the same call sites they will use against real Google later.

JWTs are HS256-signed with ``APAP_SESSION_SECRET`` (or the constant
``stub-secret`` when the env var is unset) using only stdlib — the
project has no PyJWT dependency in production, so this module does not
introduce one.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import time

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

oauth_router = APIRouter()

_INSFORGE_CODE_PATTERN = r"^insforge_[A-Za-z0-9]{8,64}$"
_INSFORGE_CODE_RE = re.compile(_INSFORGE_CODE_PATTERN)

_SESSION_SECRET_ENV = "APAP_SESSION_SECRET"
_STUB_SECRET = "stub-secret"

_LOCAL_USER_ID = "local-user"
_LOCAL_USER_EMAIL = "local@apap"

_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_SCOPE = "openid email profile"
_GOOGLE_CLIENT_ID_STUB = "test"


def _b64url_encode(data: bytes) -> str:
    """Base64-url-encode ``data`` without padding (RFC 7515 §2)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _sign_jwt(claims: dict[str, object]) -> str:
    """Return an HS256-signed JWT for ``claims`` using the session secret."""
    secret = os.environ.get(_SESSION_SECRET_ENV) or _STUB_SECRET
    header = {"alg": "HS256", "typ": "JWT"}
    header_b64 = _b64url_encode(
        json.dumps(header, separators=(",", ":")).encode("utf-8")
    )
    payload_b64 = _b64url_encode(
        json.dumps(claims, separators=(",", ":")).encode("utf-8")
    )
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    digest = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    signature_b64 = _b64url_encode(digest)
    return f"{header_b64}.{payload_b64}.{signature_b64}"


def _build_token_envelope() -> dict[str, object]:
    """Build the canonical ``{token, user}`` envelope using a fresh JWT."""
    now = int(time.time())
    claims = {
        "email": _LOCAL_USER_EMAIL,
        "sub": _LOCAL_USER_ID,
        "iat": now,
        "exp": now + 3600,
    }
    return {
        "token": _sign_jwt(claims),
        "user": {"id": _LOCAL_USER_ID, "email": _LOCAL_USER_EMAIL},
    }


@oauth_router.post("/auth/oauth/google")
async def start_google_oauth(
    code_challenge: str = Query(...),
    redirect_uri: str = Query(...),
) -> dict[str, str]:
    """Return the Google OAuth ``authUrl`` stub.

    The URL is a static template with the supplied ``code_challenge`` and
    ``redirect_uri`` interpolated. M0 does not call Google; the front-end
    accepts the stub URL the same way it will accept the real one.
    """
    scope = _GOOGLE_SCOPE.replace(" ", "+")
    auth_url = (
        f"{_GOOGLE_AUTH_URL}?client_id={_GOOGLE_CLIENT_ID_STUB}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code"
        f"&scope={scope}"
        f"&code_challenge={code_challenge}"
        f"&code_challenge_method=S256"
    )
    return {"authUrl": auth_url}


@oauth_router.post("/auth/oauth/google/callback")
async def google_oauth_callback(request: Request) -> dict[str, object]:
    """Return the JWT + user envelope for the Google OAuth callback stub."""
    return _build_token_envelope()


@oauth_router.post("/auth/oauth/exchange")
async def exchange_insforge_code(request: Request) -> JSONResponse:
    """Validate ``code`` against the insforge_code pattern and return the envelope.

    M0 does not perform a real code-for-token handshake with InsForge; the
    pattern check is the only acceptance gate. ``client_type`` is read
    from the query string for forward-compatibility with the eventual
    web/mobile branching — M0 ignores its value.
    """
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_request", "detail": "request body must be valid JSON"},
        )
    if not isinstance(payload, dict):
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_request", "detail": "request body must be an object"},
        )
    code = payload.get("code", "")
    if not isinstance(code, str) or not _INSFORGE_CODE_RE.match(code):
        return JSONResponse(
            status_code=401,
            content={
                "error": "invalid_code",
                "detail": f"code must match {_INSFORGE_CODE_PATTERN}",
            },
        )
    return JSONResponse(content=_build_token_envelope())


__all__ = [
    "oauth_router",
    "start_google_oauth",
    "google_oauth_callback",
    "exchange_insforge_code",
    "_sign_jwt",
]
