"""Use-case layer for the OAuth login flow.

Each function in this package is a thin orchestrator that delegates
to the :class:`OAuthPort` (and, for the callback, the
:class:`AuthUsersPort`) Protocol. The use cases do NOT do transport
work, response building, or cookie parsing — those concerns live in
the route layer (see the new ``app.core.auth_flow`` shim) and in
the adapter (:mod:`app.core.local_backend.oauth_adapter`).

Hexagonal taxonomy:

- Domain     :mod:`app.core.domain.oauth` — entities + Protocol errors.
- Port       :mod:`app.core.ports.oauth_port` — abstract surface.
- THIS      (this module) — use cases.
- Adapter    :mod:`app.core.local_backend.oauth_adapter` — InsForge impl.
- DI         :mod:`app.core.di.oauth_di` — FastAPI wiring.
"""


from __future__ import annotations

from app.core.application.oauth.callback import callback
from app.core.application.oauth.login_page import login_page
from app.core.application.oauth.logout import ClearSessionParams, logout
from app.core.application.oauth.start_google_login import start_google_login

__all__ = [
    "ClearSessionParams",
    "callback",
    "login_page",
    "logout",
    "start_google_login",
]
