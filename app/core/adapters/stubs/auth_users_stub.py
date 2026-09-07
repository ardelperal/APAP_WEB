"""Stub adapter for ``AuthUsersPort`` — pending local-backend implementation.

This file replaces the deleted :class:`app.core.adapters.local_backend.auth_local_backend_adapter.LocalBackendAuthUsersAdapter`.
A real :class:`~app.core.local_backend.db.LocalPostgresExecutor`-backed
adapter lands in a follow-up slice; until then, every method raises
:class:`NotImplementedError` so the runtime fails loud per route.

Affected routes (return 500 until the real adapter lands):

- ``POST /auth/login`` (delegates to :func:`app.core.auth.get_user_by_email`)
- ``POST /auth/callback`` (delegates to OAuth user-lookup)
- ``POST /admin/users`` + ``GET /admin/users`` (delegates to ``add_authorized_user`` / ``list_authorized_users``)
- ``app.core.domain.ensure_domain_schema`` (delegates to ``ensure_schema_and_seed``)

See issue #4b' for the follow-up that replaces this stub with a real
local-backend implementation.
"""

from __future__ import annotations

from app.core.ports.auth_port import AuthUsersPort


class StubAuthUsersPort(AuthUsersPort):
    """Placeholder :class:`AuthUsersPort` whose every method raises.

    Implements the Protocol structurally (no abstract methods left
    unimplemented at the type level) so DI providers can yield an
    instance and Python's type checker stays happy.
    """

    def ensure_schema_and_seed(self, *args, **kwargs):
        raise NotImplementedError(
            "AuthUsersPort.ensure_schema_and_seed: pending local-backend adapter, see #4b'"
        )

    def get_user_by_email(self, *args, **kwargs):
        raise NotImplementedError(
            "AuthUsersPort.get_user_by_email: pending local-backend adapter, see #4b'"
        )

    def check_email_taken(self, *args, **kwargs):
        raise NotImplementedError(
            "AuthUsersPort.check_email_taken: pending local-backend adapter, see #4b'"
        )

    def list_authorized_users(self, *args, **kwargs):
        raise NotImplementedError(
            "AuthUsersPort.list_authorized_users: pending local-backend adapter, see #4b'"
        )

    def add_authorized_user(self, *args, **kwargs):
        raise NotImplementedError(
            "AuthUsersPort.add_authorized_user: pending local-backend adapter, see #4b'"
        )

    def get_user_by_id(self, *args, **kwargs):
        raise NotImplementedError(
            "AuthUsersPort.get_user_by_id: pending local-backend adapter, see #4b'"
        )

    def deactivate_authorized_user(self, *args, **kwargs):
        raise NotImplementedError(
            "AuthUsersPort.deactivate_authorized_user: pending local-backend adapter, see #4b'"
        )


__all__ = ["StubAuthUsersPort"]
