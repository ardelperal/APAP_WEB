"""Stub adapter for ``OAuthPort`` — pending local-backend implementation.

This file replaces the deleted :class:`app.core.adapters.local_backend.oauth_local_backend_adapter.LocalBackendOAuthAdapter`.
A real :class:`~app.core.local_backend.oauth_google`-backed adapter lands
in a follow-up slice; until then, every method raises
:class:`NotImplementedError` so the runtime fails loud per route.

Affected routes (return 500 until the real adapter lands):

- ``GET /auth/google/login`` (delegates to :meth:`OAuthPort.start_google_login`)
- ``POST /auth/google/callback`` (delegates to :meth:`OAuthPort.exchange_local_backend_oauth_code` + :meth:`OAuthPort.exchange_google_oauth_code`)

See issue #4b' for the follow-up that replaces this stub with a real
local-backend implementation.
"""

from __future__ import annotations

from app.core.ports.oauth_port import OAuthPort


class StubOAuthPort(OAuthPort):
    """Placeholder :class:`OAuthPort` whose every method raises."""

    def start_google_login(self, *args, **kwargs):
        raise NotImplementedError(
            "OAuthPort.start_google_login: pending local-backend adapter, see #4b'"
        )

    def exchange_local_backend_oauth_code(self, *args, **kwargs):
        raise NotImplementedError(
            "OAuthPort.exchange_local_backend_oauth_code: pending local-backend adapter, see #4b'"
        )

    def exchange_google_oauth_code(self, *args, **kwargs):
        raise NotImplementedError(
            "OAuthPort.exchange_google_oauth_code: pending local-backend adapter, see #4b'"
        )


__all__ = ["StubOAuthPort"]
