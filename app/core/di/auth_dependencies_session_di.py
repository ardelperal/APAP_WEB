"""Session and authorization dependencies for the auth-dependencies slice."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, Request
from fastapi.responses import RedirectResponse
from starlette.responses import Response

from app.core.auth import get_user_by_email
from app.core.auth_cache import get_cached_auth, set_cached_auth
from app.core.config import get_settings
from app.core.data_access import InsForgeError
from app.core.insforge import InsForgeClient


def _shim():
    """Return the legacy auth-dependencies shim module."""
    # lazy-import: deferred to call time to avoid the di-to-shim import cycle.
    from app.core import auth_dependencies

    return auth_dependencies


def _deny(payload: dict | None, reason: str, *, url: str = "/unauthorized") -> Response:
    user_id = payload.get("user_id") if payload else None
    _shim().log_safe("auth.denied", reason=reason, user_id=user_id)
    return RedirectResponse(url=url, status_code=302)


def get_insforge_client_dep(request: Request) -> Iterator[InsForgeClient]:
    """Yield the pooled InsForge client owned by the application lifespan."""
    try:
        client = request.app.state.insforge_client
    except AttributeError:
        settings = get_settings()
        client = InsForgeClient(settings.insforge_url, settings.insforge_service_key)
        request.app.state.insforge_client = client
    yield client


def get_current_user_optional(request: Request) -> dict | None:
    """Return the signed session payload, or ``None`` when it is invalid."""
    return _shim().read_session_payload(request, secret=get_settings().session_secret)


def require_authorized_user(
    request: Request,
    payload: dict | None = Depends(get_current_user_optional),
    client: InsForgeClient = Depends(get_insforge_client_dep),
) -> Response | dict:
    """Require an authorized session revalidated against the auth backend."""
    if not payload:
        return _deny(payload, "no_session", url="/login")
    if not payload.get("is_authorized", False):
        return _deny(payload, "cookie_no_flag")

    email = payload.get("email")
    if not isinstance(email, str) or not email:
        return _deny(payload, "no_email")

    cached = get_cached_auth(email, get_settings().auth_cache_ttl_seconds)
    if cached is None:
        try:
            fresh = get_user_by_email(client, email)
        except InsForgeError:
            return _deny(payload, "db_unreachable")
        if fresh is None:
            set_cached_auth(email, is_authorized=False, rol=None)
            return _deny(payload, "db_reval_miss")
        set_cached_auth(email, is_authorized=True, rol=fresh["rol"])
        payload["rol"] = fresh["rol"]
        return payload

    if not cached.is_authorized:
        return _deny(payload, "db_reval_miss")
    payload["rol"] = cached.rol
    return payload


__all__ = [
    "get_insforge_client_dep",
    "get_current_user_optional",
    "require_authorized_user",
]
