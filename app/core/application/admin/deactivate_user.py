"""Use case: deactivate an authorized user from the admin form.

This use case preserves the legacy ``admin_deactivate_user`` route's
exact behavior (issue #279):

- A ``ValueError`` from the auth use case (last active developer, user
  not found, defensive zero-row disambiguation) re-renders
  ``admin.html`` with the message in the flash slot, instead of a
  silent redirect.
- Success returns a ``RedirectResponse`` to ``/admin`` — the operator
  sees the refreshed table on the next GET.

The use case delegates the domain logic (last-developer guard,
disambiguation) to
:func:`app.core.application.auth.deactivate_authorized_user.deactivate_authorized_user`
so this slice does not re-implement the SQL-level guard (rule §1 —
domain rules live in the application layer, the adapter enforces the
SQL shape).
"""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import RedirectResponse, Response

from app.core.application.auth.deactivate_authorized_user import (
    deactivate_authorized_user as _deactivate_use_case,
)
from app.core.ports.admin_port import AdminPanelContext, AdminTemplatePort
from app.core.ports.auth_port import AuthUsersPort


def deactivate_user(
    auth_port: AuthUsersPort,
    template_adapter: AdminTemplatePort,
    request: Request,
    *,
    current_user: dict,
    user_id: str,
    app_name: str,
    roles: frozenset[str],
) -> Response:
    """Deactivate the user and either redirect or re-render with flash.

    Raises ``ValueError`` are caught and rendered with the legacy
    "re-render admin.html with flash" shape (issue #279).
    """
    try:
        _deactivate_use_case(auth_port, user_id)
    except ValueError as exc:
        return template_adapter.render_panel(
            AdminPanelContext(
                request=request,
                current_user=current_user,
                users=auth_port.list_authorized_users(),
                app_name=app_name,
                roles=roles,
                error_message=str(exc),
                error_type="danger",
            )
        )
    return RedirectResponse(url="/admin", status_code=302)
