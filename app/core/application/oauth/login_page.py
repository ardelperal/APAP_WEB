"""Use case: render the ``/login`` page or 503 when NO credential channel is configured.

The use case returns a dict (or ``None`` when no credential channel is
configured) so the login template can show whichever forms the operator
has set up:
- Google OAuth button — when ``google_client_id`` and ``google_client_secret`` are set
- Magic-link form — when ``APAP_AUTH_ENABLE_MAGIC_LINK`` is truthy AND ``APAP_SMTP_HOST`` is set

The route layer translates the ``None`` outcome into a ``503 Service
Unavailable`` JSON response with the operator's remediation hint.

M3 fix (post-archive):
- The previous version only checked Google OAuth, which 503'd the
  entire /login page if the operator switched to magic-link-only
  (leaving Google env vars empty). This M3 fix unblocks the page
  when magic-link is the active channel.
- The route still emits a 503 ONLY when BOTH channels are unconfigured,
  so the operator sees a clear "set up at least one channel" hint.

Hexagonal contract:
- Inputs: the configured :class:`Settings` (read once via
  ``app.core.config.get_settings``).
- Outputs: a dict ``{"app_name", "google_enabled", "magic_link_enabled"}``
  for the template, or ``None`` if neither channel is configured.
- Side effects: none.
"""
from __future__ import annotations

import os

from app.core.config import Settings


def _env_truthy(name: str) -> bool:
    """Return True iff env var ``name`` is set to a truthy value (1/true/yes/on)."""
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def login_page(settings: Settings) -> dict[str, object] | None:
    """Return a context dict for the login template, or None if no channel is configured.

    The check: at least one of
    - Google OAuth (``google_client_id`` + ``google_client_secret``)
    - Magic link (``APAP_AUTH_ENABLE_MAGIC_LINK=true`` AND ``APAP_SMTP_HOST`` set)
    must be configured. Otherwise the page would 503 and the operator
    has no path to log in.
    """
    google_enabled = bool(settings.google_client_id and settings.google_client_secret)
    magic_link_enabled = (
        _env_truthy("APAP_AUTH_ENABLE_MAGIC_LINK")
        and bool(os.environ.get("APAP_SMTP_HOST", "").strip())
    )
    if not google_enabled and not magic_link_enabled:
        return None
    return {
        "app_name": settings.app_name,
        "google_enabled": google_enabled,
        "magic_link_enabled": magic_link_enabled,
    }


__all__ = ["login_page"]
