"""In-memory :class:`AuthUsersPort` for the local backend (M1, F3).

The local FastAPI backend that ships in M0 does NOT have a real
``usuarios_autorizados`` table — M0 only provisions the raw SQL
backend, the OAuth callback stub, and the storage router. F3 needs an
:class:`AuthUsersPort` that the magic-link routes (F2) can call so
the round-trip gate can exercise the start / verify endpoints
end-to-end without standing up an InsForge instance.

The seam follows the existing F2 test stub shape
(``tests/integration/test_magic_link_routes.py::_StubAuthPort``)
but lifts it into a module that the lifespan can import. The F2
test stub stays in the integration test file because it is only
used by the F2 AS1–AS6 atoms; F3 needs the same primitive at the
factory boundary so the local backend under the magic-link feature
flag can resolve ``app.state.auth_port`` to something that returns
``AuthorizedUser`` rows for the seeded test emails.

Surface area mirrors :class:`app.core.ports.auth_port.AuthUsersPort`
exactly:

- :meth:`get_user_by_email` — the only method the magic-link
  routes call (F2 routes do ``auth_port.get_user_by_email(email)``
  inside ``start_magic`` and inside ``_verify_magic_impl``).
- :meth:`check_email_taken` — referenced by the F2 spec R4 contract
  as a constant-time lookup helper; the route currently uses
  ``get_user_by_email`` but the spec keeps the seam so a future
  route can switch without forking the Protocol.
- :meth:`add` — not on the Protocol but the helper the F3 round-trip
  uses to seed a known user via ``POST /_test/seed_user`` (a
  debug-only route mounted only when the F3 flag is set).

Every other Protocol method raises :class:`NotImplementedError` so
an accidental call surfaces as a clear runtime error instead of a
silent no-op (defense-in-depth, mirrors ``_StubAuthPort`` in the
F2 test file). Production wiring (the InsForge-backed adapter)
implements all eight methods.

Layer compliance (AGENTS.md rule 33): the module lives under
``app/core/local_backend/`` (classified ``infrastructure`` by
``scripts/check_layers.py``) and imports from ``app.core.domain.auth``
and ``app.core.ports.auth_port``. It does NOT import from
``app.core.adapters.*`` or ``app.core.application.*`` (the stub is
its own implementation, not a thin wrapper around an adapter).
"""

from __future__ import annotations

import uuid
from typing import Any

from app.core.domain.auth.rol import Rol
from app.core.domain.auth.user import AuthorizedUser
from app.core.ports.auth_port import AuthUsersPort


class StubAuthPort:
    """In-memory :class:`AuthUsersPort` for the F3 round-trip gate.

    Two surface areas:

    - The Protocol methods (:meth:`get_user_by_email`,
      :meth:`check_email_taken`, etc.) — what the F2 routes call.
    - The seed helper :meth:`add` — what the F3 ``/_test/seed_user``
      route calls to plant a known user for the round-trip atom.

    The instance is created in the F3 lifespan and attached to
    ``app.state.auth_port``. The lifespan is the sole owner; tests
    that want a fresh stub re-build the FastAPI app via
    :func:`allocate_local_backend` (the M0 fixture) which restarts
    the lifespan.
    """

    def __init__(self) -> None:
        self._users: dict[str, AuthorizedUser] = {}
        self._calls: list[tuple[str, tuple[Any, ...]]] = []

    def add(
        self, email: str, rol: Rol | str | None = None
    ) -> AuthorizedUser:
        """Seed an active user with a fresh UUID; return the row.

        Mirrors the F2 test stub's ``add`` helper. The ``rol``
        argument defaults to :attr:`Rol.DEVELOPER` (the F2 stub's
        default) when ``None``. An existing user with the same email
        is overwritten so the F3 round-trip can re-seed across
        runs without first clearing state.
        """
        resolved_rol: Rol
        if rol is None:
            resolved_rol = Rol.DEVELOPER
        elif isinstance(rol, Rol):
            resolved_rol = rol
        else:
            resolved_rol = Rol(str(rol))
        user = AuthorizedUser(
            id=str(uuid.uuid4()),
            email=email,
            rol=resolved_rol,
            active=True,
            added_by=None,
            added_at=None,
        )
        self._users[email] = user
        return user

    def get_user_by_email(self, email: str) -> AuthorizedUser | None:
        """Return the active user with ``email`` or ``None``.

        Logs the call into ``self._calls`` so F3's ``/_test/seed_user``
        follow-up asserts can confirm the route layer actually hit the
        stub (the round-trip gate asserts the magic-link issued a
        cookie, not that the auth lookup ran — but the call log is
        useful debugging surface for the future ``check_magic_link``
        gate that may need to verify the lookup happened).
        """
        self._calls.append(("get_user_by_email", (email,)))
        return self._users.get(email)

    def check_email_taken(self, email: str) -> bool:
        """Return ``True`` when an active user with ``email`` exists.

        Logs the call into ``self._calls`` (same rationale as
        :meth:`get_user_by_email`).
        """
        self._calls.append(("check_email_taken", (email,)))
        return email in self._users

    # --- unused Protocol methods (defense-in-depth) ------------------

    def ensure_schema_and_seed(self, initial_admin_email: str) -> None:  # noqa: ARG002
        """Stub seam — raise :class:`NotImplementedError`.

        The F3 lifespan does not need to seed a bootstrap admin
        because the round-trip gate plants its own user via
        :meth:`add`. A future operator flow that needs the bootstrap
        admin would have to add a real InsForge-backed adapter; this
        stub raises so a regression surfaces as a clear runtime
        error instead of a silent no-op.
        """
        raise NotImplementedError(
            "StubAuthPort.ensure_schema_and_seed is a stub — the F3 round-trip "
            "gate uses StubAuthPort.add() to plant a known user, not the "
            "bootstrap seed path."
        )

    def list_authorized_users(self) -> list[AuthorizedUser]:
        """Stub seam — raise :class:`NotImplementedError`.

        The F3 routes do not call this method; raising keeps the
        Protocol surface honest.
        """
        raise NotImplementedError(
            "StubAuthPort.list_authorized_users is a stub — no F3 route uses it."
        )

    def add_authorized_user(
        self,
        email: str,
        rol: Rol,
        added_by: str,
    ) -> AuthorizedUser:
        """Stub seam — raise :class:`NotImplementedError`.

        The F3 round-trip gate uses :meth:`add` (which matches the
        F2 ``_StubAuthPort.add`` helper) to plant its user. The
        Protocol-level ``add_authorized_user`` is the use-case-layer
        shape and is not invoked by any F2 / F3 route.
        """
        raise NotImplementedError(
            "StubAuthPort.add_authorized_user is a stub — the F3 round-trip "
            "gate calls add() (the F2 test-helper shape), not the use-case "
            "Protocol seam."
        )

    def get_user_by_id(self, user_id: str) -> AuthorizedUser | None:  # noqa: ARG002
        """Stub seam — raise :class:`NotImplementedError`."""
        raise NotImplementedError(
            "StubAuthPort.get_user_by_id is a stub — no F3 route uses it."
        )

    def deactivate_authorized_user(self, user_id: str) -> AuthorizedUser:  # noqa: ARG002
        """Stub seam — raise :class:`NotImplementedError`."""
        raise NotImplementedError(
            "StubAuthPort.deactivate_authorized_user is a stub — no F3 route uses it."
        )


# Tell the type-checker this concrete class implements the Protocol.
# ``runtime_checkable`` is not enabled on AuthUsersPort, so this is
# documentation-only; ``isinstance(..., AuthUsersPort)`` would raise
# ``TypeError`` if it ever ran. The F3 lifespan attaches the instance
# to ``app.state.auth_port`` and the F2 routes use it as the duck-typed
# Protocol — no isinstance check happens in the hot path.
_ = AuthUsersPort


__all__ = ["StubAuthPort"]
