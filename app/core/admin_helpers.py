"""Admin-panel helpers shared by the application factory.

Extracted from ``app/main.py`` to keep the factory module under the 700-line
budget (AGENTS.md rule 21).  These helpers are stateless and depend only on
the session configuration, not on the FastAPI application instance.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request
from fastapi.responses import RedirectResponse

from app.core.config import get_settings
from app.core.session import read_session_payload, write_session


@dataclass
class _FlashContext:
    """Parsed flash payload carried in the signed session cookie."""

    message: str
    error_type: str
    cookie_value: str


def _pop_flash(request: Request) -> _FlashContext | None:
    """Extract and clear the flash message from the signed session cookie.

    Called by ``GET /admin`` before rendering so the template receives the
    error context.  The flash is cleared by re-signing the session with
    ``_flash`` removed.
    """
    settings = get_settings()
    payload = read_session_payload(request, secret=settings.session_secret) or {}
    flash = payload.pop("_flash", None)
    if not flash:
        return None
    # Re-sign without the flash so the message is consumed after one render.
    cookie_value = write_session(payload, secret=settings.session_secret)
    return _FlashContext(
        message=flash.get("message", ""),
        error_type=flash.get("type", "danger"),
        cookie_value=cookie_value,
    )


def _redirect_with_flash(
    request: Request, path: str, error_type: str, message: str
) -> RedirectResponse:
    """Redirect with an error flash stored in the signed session cookie.

    The flash is stored in the signed session cookie so it survives the
    redirect. The ``GET /admin`` handler reads and clears it (issue #277).
    """
    settings = get_settings()
    payload = read_session_payload(request, secret=settings.session_secret) or {}
    payload["_flash"] = {"type": error_type, "message": message}
    cookie_value = write_session(payload, secret=settings.session_secret)
    response = RedirectResponse(url=path, status_code=302)
    response.set_cookie(
        key="apap_session",
        value=cookie_value,
        max_age=60 * 60 * 24 * 7,
        httponly=True,
        secure=True,
        samesite="strict",
    )
    return response
