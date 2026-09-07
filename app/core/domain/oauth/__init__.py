"""Domain layer for the OAuth login flow.

Re-exports the entities and Protocol-level errors that the
application and adapter layers exchange. The OAuth flow has three
domain concepts:

- :class:`PkcePair` (in :mod:`app.core.domain.oauth.pkce_pair`) —
  the (verifier, challenge) tuple minted at the start of the flow.
- :class:`AuthenticatedSession` (in
  :mod:`app.core.domain.oauth.session`) — the post-callback user
  identity, projected from ``usuarios_autorizados`` after a
  successful exchange.
- :class:`OAuthError` and its three Protocol-level subclasses (in
  :mod:`app.core.domain.oauth.errors`) — domain errors the use case
  raises when the transport (or the configured state) does not
  allow the requested transition.

The entities are frozen dataclasses (rule §1 — no in-place mutation
across the layered boundary) so the application layer can pass them
across the port boundary as values.

Hexagonal taxonomy:

- Domain   (this module) — entities + Protocol-level errors, no I/O.
- Port     :mod:`app.core.ports.oauth_port` — abstract surface.
- Application :mod:`app.core.application.oauth` — use cases.
- Adapter  :mod:`app.core.adapters.local_backend.oauth_local_backend_adapter` — LocalBackend impl.
- DI       :mod:`app.core.di.oauth_di` — wiring.
"""


from __future__ import annotations

from app.core.domain.oauth.errors import (
    CallbackInvalidError,
    OAuthError,
    OAuthNotConfiguredError,
    UserNotAuthorizedError,
)
from app.core.domain.oauth.pkce_pair import PkcePair
from app.core.domain.oauth.session import AuthenticatedSession

__all__ = [
    "AuthenticatedSession",
    "CallbackInvalidError",
    "OAuthError",
    "OAuthNotConfiguredError",
    "PkcePair",
    "UserNotAuthorizedError",
]
