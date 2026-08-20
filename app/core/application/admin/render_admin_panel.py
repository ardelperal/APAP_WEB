"""Use case: render the admin panel for a developer session.

The use case is a thin delegator over the auth port. The route handler
already has the developer session payload (``current_user``), the
app-level config (``app_name``, ``roles``), and any flash payload
parsed from the session cookie (``error_message``, ``error_type``).
This use case only fetches the user list and delegates the render to
:class:`~app.core.adapters.admin_template_adapter.AdminTemplateAdapter`.
"""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import Response

from app.core.ports.admin_port import AdminTemplatePort
from app.core.ports.auth_port import AuthUsersPort


def render_admin_panel(
    auth_port: AuthUsersPort,
    template_adapter: AdminTemplatePort,
    request: Request,
    *,
    current_user: dict,
    app_name: str,
    roles: frozenset[str],
    error_message: str | None = None,
    error_type: str | None = None,
) -> Response:
    """Render the admin panel with the list of authorized users.

    The ``current_user`` / ``app_name`` / ``roles`` context is provided
    by the caller; the use case only fetches the user list via the
    port. ``error_message`` / ``error_type`` propagate a flash from a
    previous POST that the session cookie carried (see
    :func:`app.core.admin_helpers._pop_flash`).
    """
    users = auth_port.list_authorized_users()
    return template_adapter.render_panel(
        request=request,
        current_user=current_user,
        users=users,
        app_name=app_name,
        roles=roles,
        error_message=error_message,
        error_type=error_type,
    )
