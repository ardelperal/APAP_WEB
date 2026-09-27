"""Use case: create the ``usuarios_autorizados`` table and seed the bootstrap admin.

Idempotent on every cold start. The seed is gated on
``settings.initial_admin_email`` being non-empty; the ``WHERE NOT
EXISTS`` clause inside the seed SQL prevents a second bootstrap
admin from being inserted even if a developer already exists.

This use case is the only one that takes a ``Settings`` argument —
``initial_admin_email`` is the only env-flag-driven branch point in
the auth slice. All other use cases derive their inputs from the
request / caller, not from runtime configuration.
"""
from __future__ import annotations

from app.core.config import Settings
from app.core.ports.auth_port import AuthUsersPort


def _canonical_admin_email(email: str) -> str:
    """Strip + lowercase — mirror of :func:`app.core.auth_helpers.normalize_email`.

    Inlined here to keep the application layer free of infrastructure
    imports (``app.core.auth_helpers`` lives under ``app/core/`` which
    the layer-purity gate ``tests/test_layers.py`` treats as
    infrastructure). The existing ``get_user_by_email`` use case has
    the same cross-layer call baselined; inlining avoids expanding
    that debt for a one-line normalization (issue #1003).
    """
    return email.strip().lower()


def ensure_schema_and_seed(
    port: AuthUsersPort,
    settings: Settings,
) -> None:
    """Create the table (idempotent) and seed the bootstrap admin.

    The use case always delegates to the port so the table is
    created on every cold start (the test at
    ``tests/test_auth.py::test_ensure_schema_creates_usuarios_autorizados_table``
    asserts ``len(captured) == 1`` for the ``initial_admin_email=""``
    path). The port then decides whether to append the bootstrap
    INSERT based on whether ``initial_admin_email`` is non-empty.
    Splitting the "should the seed run?" decision into the port
    keeps the test contract (one SQL call for the empty path,
    two SQL calls for the configured path) preserved.

    The ``initial_admin_email`` setting is normalized to its canonical
    form (strip + lowercase) before being passed to the port, so a
    mixed-case value in ``APAP_INITIAL_ADMIN_EMAIL`` (e.g.
    ``Admin@Example.com``) is stored as ``admin@example.com`` —
    matching the canonical form that the case-insensitive lookup in
    ``GET_USER_BY_EMAIL_SQL`` resolves (issue #1003).
    """
    port.ensure_schema_and_seed(_canonical_admin_email(settings.initial_admin_email))
