"""Use case: render the ``/login`` page or 503 when OAuth is unconfigured.

The use case returns either the ``app_name`` (a string the route
template needs) or ``None`` when Google OAuth is not configured for
this environment. The route layer translates the ``None`` outcome
into a ``503 Service Unavailable`` JSON response — the operator's
message is identical to the legacy ``app.core.auth_flow`` output
so the existing ``tests/test_auth_flow.py::test_login_returns_503_...``
keeps passing without a body change.

Hexagonal contract:

- Inputs: the configured :class:`Settings` (read once via
  ``app.core.config.get_settings``).
- Outputs: the ``app_name`` string, or ``None`` if OAuth is not
  configured.
- Side effects: none.

The use case is intentionally NOT a port call: the configuration
check is a pure read of the settings singleton, not a transport
operation. The port boundary is reserved for operations that
actually touch the backend; the config check is a precondition
that runs BEFORE the port is consulted.
"""


from __future__ import annotations

from app.core.config import Settings


def login_page(settings: Settings) -> str | None:
    """Return the ``app_name`` for the login template, or ``None`` when unconfigured.

    The check matches the legacy
    ``app.core.auth_flow.register_auth_flow_routes::login`` gate
    exactly: when EITHER ``google_client_id`` OR
    ``google_client_secret`` is empty, the use case returns
    ``None`` and the route renders the 503. The legacy code reads
    the check inline in the route; this use case lifts it to a
    single-source-of-truth so a future admin UI that wants to
    surface the same state (e.g. "OAuth not configured" banner) can
    call this use case without re-implementing the rule.
    """
    if not settings.google_client_id or not settings.google_client_secret:
        return None
    return settings.app_name


__all__ = ["login_page"]
