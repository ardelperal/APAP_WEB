"""Hexagonal port for the authenticated-user management slice.

The :class:`AuthUsersPort` Protocol is the seam between the application
(use-case) layer and any transport adapter. Domain code in
``app.core.application.auth`` depends on this Protocol only; the
InsForge implementation lives in
:mod:`app.core.adapters.insforge.auth_insforge_adapter`, and a future
legacy Access adapter will live in its own module under
``app.core.adapters.access`` (Phase 3). A custom DI provider
(:mod:`app.core.di.auth_di`) wires the InsForge adapter into FastAPI
requests.

Adapters MUST translate transport-level errors (HTTP 409, ODBC error
codes, ...) into the Protocol-level exceptions declared in
:mod:`app.core.data_access` — ``DuplicateKeyError`` on uniqueness
violations, ``DataAccessError`` for other transport failures. The
application layer catches these Protocol-level types and re-raises
domain ``ValueError`` so the legacy ``app.core.auth`` shim's contract
(ValueError on duplicate) is preserved.
"""
from __future__ import annotations

from typing import Protocol

from app.core.domain.auth.rol import Rol
from app.core.domain.auth.user import AuthorizedUser


class AuthUsersPort(Protocol):
    """Backend-agnostic interface for ``usuarios_autorizados`` CRUD.

    Six public methods, one per use case:

    - :meth:`ensure_schema_and_seed` — DDL + bootstrap admin seed.
    - :meth:`get_user_by_email` — active-user lookup by canonical email.
    - :meth:`list_authorized_users` — full table (active + inactive).
    - :meth:`add_authorized_user` — INSERT a new user, raise
      :class:`~app.core.data_access.DuplicateKeyError` on the
      pre-insert race where two parallel INSERTs slip past the
      application-level pre-check.
    - :meth:`get_user_by_id` — single-row lookup by UUID.
    - :meth:`deactivate_authorized_user` — conditional UPDATE that
      enforces the last-developer guard at the SQL level and returns
      the deactivated row, or raises a domain error the use case
      translates to ``ValueError``.

    The last-developer-guard helper (:func:`_has_other_active_developers`)
    is intentionally NOT on this Protocol — it is a SQL-only check that
    the adapter calls internally inside
    :meth:`deactivate_authorized_user`. Exposing it on the port would
    invite use-case callers to bypass the guard by reading
    ``port._has_other_active_developers(...)`` directly. The helper
    stays inside the adapter; the use-case shim at
    ``app.core.auth._has_other_active_developers`` is the only
    sanctioned external path.
    """

    def ensure_schema_and_seed(
        self,
        initial_admin_email: str,
    ) -> None:
        """Create the ``usuarios_autorizados`` table and seed the bootstrap developer.

        Idempotent: ``CREATE TABLE IF NOT EXISTS`` plus a ``WHERE NOT
        EXISTS`` guard on the seed INSERT. ``initial_admin_email`` is
        the empty string when no bootstrap admin is configured; the
        adapter is responsible for the "is the env var set?" check
        (the application layer reads ``Settings.initial_admin_email``
        and decides whether to call this at all).
        """
        ...

    def get_user_by_email(
        self,
        email: str,
    ) -> AuthorizedUser | None:
        """Return the active user with this email, or ``None``.

        Adapter MUST look up the row case-insensitively — the
        application layer normalizes the email to its canonical form
        (strip + lower) before calling this, but the adapter is the
        last line of defense against case-variant duplicates that
        pre-existed the normalization (issue #278).
        """
        ...

    def check_email_taken(
        self,
        email: str,
    ) -> bool:
        """Return True if the email already has an active user.

        This is a deliberately narrower projection than
        :meth:`get_user_by_email` (a single ``SELECT id`` rather than
        the full row) for two reasons:

        1. **Test-spy distinguishability (issue #143).** The admin
           test spy in ``tests/test_admin.py`` routes
           ``GET_USER_BY_EMAIL_SQL`` (which includes ``rol,``) to the
           auth-revalidation handler so every request sees a fake
           "logged-in" user row. The duplicate check uses
           ``_CHECK_DUPLICATE_EMAIL_SQL`` (which has ``SELECT id``
           with no ``rol,`` token) so the spy does NOT intercept it
           — a duplicate check on the reval query would always see
           the fake logged-in user and falsely report "already
           authorized".
        2. **Cost.** The duplicate check is the hot path on the
           admin add-user form; projecting only ``id`` skips the
           ``rol`` / ``activo`` column reads.
        """
        ...

    def list_authorized_users(self) -> list[AuthorizedUser]:
        """Return every user (active + inactive) for the admin panel."""
        ...

    def add_authorized_user(
        self,
        email: str,
        rol: Rol,
        added_by: str,
    ) -> AuthorizedUser:
        """INSERT a new authorized user. The pre-insert duplicate check
        lives in the use-case layer; the adapter MUST let
        :class:`~app.core.data_access.DuplicateKeyError` propagate
        when the race-condition INSERT collides with another writer.

        The application-layer pre-check (see
        :func:`app.core.application.auth.add_authorized_user.add_authorized_user`)
        is the cheap path; this Protocol-level exception is the
        defense-in-depth catch for the race where two parallel INSERTs
        slip past the pre-check.
        """
        ...

    def get_user_by_id(
        self,
        user_id: str,
    ) -> AuthorizedUser | None:
        """Return the user with this id, or ``None`` if not found."""
        ...

    def deactivate_authorized_user(
        self,
        user_id: str,
    ) -> AuthorizedUser:
        """Mark the user as inactive. Returns the deactivated row.

        The conditional UPDATE prevents deactivating the last active
        developer at the SQL level (issue #279): on zero rows, the
        adapter disambiguates via :meth:`get_user_by_id` plus the
        private ``_has_other_active_developers`` helper. The use-case
        layer translates the resulting domain exception into the
        ``ValueError`` the legacy ``app.core.auth`` callers expect.
        """
        ...
