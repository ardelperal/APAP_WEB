"""Post-callback session payload domain value object.

The OAuth callback use case returns an
:class:`AuthenticatedSession` once the email returned by LocalBackend
has been resolved against ``usuarios_autorizados``. The route
layer projects it to the signed ``apap_session`` payload via
:func:`app.core.csrf.issue_csrf_to_session`.

The class is a frozen dataclass so the use case can return it as
a value object across the port boundary. The ``is_authorized`` flag
defaults to ``False`` if the source row's projection is incomplete
(rule §6 — security defaults deny, not permit), although in
practice every read path in :mod:`app.core.adapters.local_backend`
projects the ``activo`` column so the default is never hit.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.domain.auth.rol import Rol
from app.core.domain.auth.user import AuthorizedUser


@dataclass(frozen=True, slots=True)
class AuthenticatedSession:
    """The post-callback user identity, ready to be signed into a session cookie.

    Attributes:
        email: Canonical email of the authorized user.
        rol: The user's role; the session cookie carries it as
            ``rol`` for the role-based revalidation path
            (``app.core.auth_dependencies.require_authorized_user``).
        user_id: The UUID string of the row in
            ``usuarios_autorizados``. Used as a non-PII identifier
            in ``log_safe`` events.
        is_authorized: The ``activo`` flag at the moment of exchange.
            Per the fix to the P0 VOL-01 (issue #143) this is the
            first, DB-free gate — the cookie is signed with the
            value, but the middleware re-validates against the
            database on every request via the TTL cache.
    """

    email: str
    rol: Rol
    user_id: str
    is_authorized: bool

    @classmethod
    def from_authorized_user(cls, user: AuthorizedUser) -> AuthenticatedSession:
        """Project an :class:`AuthorizedUser` to the session-payload shape.

        Centralises the ``rol`` value extraction and the
        ``is_authorized`` default-deny mapping (rule §6: a missing
        flag MUST default to the most restrictive value). When the
        source row was projected without an ``activo`` column the
        entity defaults to ``active=True`` (the read paths always
        project it; this guard is the defense-in-depth).
        """
        return cls(
            email=user.email,
            rol=user.rol,
            user_id=user.id,
            is_authorized=bool(user.active),
        )


__all__ = ["AuthenticatedSession"]
