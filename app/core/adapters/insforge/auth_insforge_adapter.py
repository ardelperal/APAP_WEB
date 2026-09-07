"""InsForge adapter implementing :class:`AuthUsersPort` for ``usuarios_autorizados``.

The adapter is the only place in the auth slice that talks to the
InsForge transport (via the :class:`~app.core.data_access.SqlExecutor`
Protocol — the foundation work's backend-agnostic contract). The
SQL lives in :mod:`app.core.adapters.insforge.auth_insforge_queries`
per AGENTS.md §22; this module is pure orchestration: take the
use-case input, run the SQL, build the domain entity, propagate
Protocol-level exceptions.

The adapter is a thin, stateless object — instantiation is cheap
(no I/O, no connection). The DI provider in
:mod:`app.core.di.auth_di` constructs one per request from the
already-pooled :class:`~app.core.insforge.LocalPostgresExecutor` that the
application lifespan owns.
"""

# Deprecated 2026-09-06: this module is no longer the production
# transport. The Coolify-hosted local backend (LocalPostgresExecutor)
# is the only supported backend as of issue #641 closing the
# self-host umbrella. This file remains so the legacy InsForge-
# touching tests can run in CI; production deploys use the
# SqlExecutor-based adapter (a follow-up slice).

from __future__ import annotations

from app.core.adapters.insforge.auth_insforge_queries import (
    _CHECK_DUPLICATE_EMAIL_SQL,
    _CHECK_OTHER_DEVELOPERS_SQL,
    ADD_USER_SQL,
    CREATE_TABLE_SQL,
    DEACTIVATE_USER_SQL,
    GET_USER_BY_EMAIL_SQL,
    GET_USER_BY_ID_SQL,
    LIST_USERS_SQL,
    SEED_ADMIN_SQL,
)
from app.core.application.auth._domain_errors import (
    LastActiveDeveloperError,
    UnexpectedDeactivateError,
    UserNotFoundError,
)
from app.core.data_access import SqlExecutor
from app.core.domain.auth.rol import Rol
from app.core.domain.auth.user import AuthorizedUser

# ``SqlStatement`` and ``run_idempotent_sql`` are imported lazily
# inside ``ensure_schema_and_seed`` to break the pre-existing
# ``app.core.schema_bootstrap`` ↔ ``app.core.adapters.insforge`` cycle:
# loading ``app.core.ports`` eagerly imports this adapter, which used
# to import ``app.core.schema_bootstrap`` at module level; in turn the
# bootstrap module imports ``app.core.ports.schema_bootstrap_port``
# which closes the loop. Deferring the import to the only call site
# removes the cycle while preserving the runtime contract.


class InsForgeAuthUsersAdapter:
    """InsForge implementation of :class:`AuthUsersPort`.

    The adapter is constructed per request by the DI provider. It
    holds only the executor (no mutable state) so it is safe to
    share across the request lifetime.
    """

    def __init__(self, executor: SqlExecutor) -> None:
        self._executor = executor

    def ensure_schema_and_seed(self, initial_admin_email: str) -> None:
        """Create the table and seed the bootstrap developer.

        ``initial_admin_email`` is the canonical email of the
        bootstrap admin (stripped + lowercased). The seed is
        guarded by a ``WHERE NOT EXISTS`` clause so it is safe to
        call on every cold start: the admin is seeded at most once.
        """
        # Lazy import: see module-level comment. ``SqlStatement`` and
        # ``run_idempotent_sql`` live in ``app.core.schema_bootstrap``,
        # which is mid-import when this adapter is loaded via
        # ``app.core.ports.__init__`` -> ``app.core.adapters.insforge.__init__``.
        from app.core.schema_bootstrap import SqlStatement, run_idempotent_sql

        statements = [SqlStatement(CREATE_TABLE_SQL)]
        if initial_admin_email:
            statements.append(
                SqlStatement(SEED_ADMIN_SQL, [initial_admin_email])
            )
        run_idempotent_sql(self._executor, statements, step_name="auth")

    def get_user_by_email(self, email: str) -> AuthorizedUser | None:
        """Return the active user with this email, or ``None``.

        The application layer is responsible for normalizing the
        email before this call; the adapter still uses a
        case-insensitive WHERE clause as a defense-in-depth against
        pre-existing case-variant duplicates (issue #278).
        """
        rows = self._executor.execute_sql(GET_USER_BY_EMAIL_SQL, [email])
        if not rows:
            return None
        return AuthorizedUser.from_row(rows[0])

    def check_email_taken(self, email: str) -> bool:
        """Return True if the email already has an active user.

        Distinct from :meth:`get_user_by_email` (narrower projection,
        ``SELECT id`` only) so the admin test spy can differentiate
        the duplicate pre-check from the auth-revalidation SELECT
        (issue #143). See :meth:`AuthUsersPort.check_email_taken`
        for the full rationale.
        """
        rows = self._executor.execute_sql(_CHECK_DUPLICATE_EMAIL_SQL, [email])
        return bool(rows)

    def list_authorized_users(self) -> list[AuthorizedUser]:
        """Return every user (active + inactive) for the admin panel."""
        rows = self._executor.execute_sql(LIST_USERS_SQL)
        return [AuthorizedUser.from_row(row) for row in rows]

    def add_authorized_user(
        self,
        email: str,
        rol: Rol,
        added_by: str,
    ) -> AuthorizedUser:
        """INSERT a new authorized user.

        The application-layer pre-check has already run; if the
        pre-check missed a race, the executor translates the 23505
        unique-key violation into
        :class:`~app.core.data_access.DuplicateKeyError` which the
        use case catches and re-raises as ``ValueError``.
        """
        rows = self._executor.execute_sql(
            ADD_USER_SQL, [email, rol.value, added_by]
        )
        return AuthorizedUser.from_row(rows[0])

    def get_user_by_id(self, user_id: str) -> AuthorizedUser | None:
        """Return the user with this id, or ``None`` if not found."""
        rows = self._executor.execute_sql(GET_USER_BY_ID_SQL, [user_id])
        if not rows:
            return None
        return AuthorizedUser.from_row(rows[0])

    def deactivate_authorized_user(self, user_id: str) -> AuthorizedUser:
        """Mark the user as inactive and return the deactivated row.

        The atomic conditional UPDATE prevents deactivating the
        last active developer at the SQL level (issue #279). On
        zero rows, the adapter disambiguates:

        - ``UserNotFoundError`` — the user_id does not match any
          row.
        - ``LastActiveDeveloperError`` — the user is the last
          active developer.
        - ``UnexpectedDeactivateError`` — defensive catch-all so a
          future refactor that drops one of the disambiguation
          branches does not silently deactivate nothing.
        """
        rows = self._executor.execute_sql(DEACTIVATE_USER_SQL, [user_id])
        if rows:
            return AuthorizedUser.from_row(rows[0])
        user = self.get_user_by_id(user_id)
        if user is None:
            raise UserNotFoundError(f"user not found: {user_id!r}")
        if (
            user.rol == Rol.DEVELOPER
            and not self._has_other_active_developers(user_id)
        ):
            raise LastActiveDeveloperError(
                "cannot deactivate the last active developer"
            )
        raise UnexpectedDeactivateError(
            f"deactivate failed unexpectedly for user {user_id!r}"
        )

    def _has_other_active_developers(self, exclude_user_id: str) -> bool:
        """Return True if at least one other active developer exists.

        Private to the adapter — the use case in
        :mod:`app.core.application.auth._has_other_active_developers`
        reaches it via ``getattr`` so a future adapter that drops
        the helper is caught at first call (``NotImplementedError``).
        """
        rows = self._executor.execute_sql(
            _CHECK_OTHER_DEVELOPERS_SQL, [exclude_user_id]
        )
        return bool(rows and rows[0].get("exists"))

    # --- M1 backward-compat defaults (issue #641) -----------------
    # Classic password auth is not supported by InsForge. The
    # M1 local adapter (ClassicPasswordAuthPort) overrides
    # these; the InsForge adapter is the fallback when
    # APAP_LOCAL_BACKEND is false. The defaults keep the
    # endpoint contract clean: a user without a password cannot
    # log in via classic auth (None), and setting a password on
    # InsForge is unsupported (raises).

    def verify_password(
        self, email: str, password: str
    ) -> AuthorizedUser | None:
        """InsForge has no password store. Always returns None.

        The caller (the login endpoint) must NOT distinguish this
        from "wrong password" — both yield None and the endpoint
        responds with the same generic error to prevent email
        enumeration.
        """
        return None

    def set_password(self, email: str, password: str) -> None:
        """InsForge cannot store password hashes. Always raises.

        The login endpoint must not reach this path for InsForge
        deployments because the local adapter is wired in when
        APAP_LOCAL_BACKEND=true (and InsForge is not). The raise
        is a defensive guard: if a future code path wires the
        wrong adapter, the failure is loud.
        """
        raise NotImplementedError(
            "InsForge adapter cannot set_password; configure "
            "APAP_LOCAL_BACKEND=true to use the local adapter."
        )
