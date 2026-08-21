"""Use case: add an authorized user from the admin form.

This use case preserves the legacy ``admin_add_user`` route's exact
behavior:

- An **invalid ``rol``** short-circuits before any DB call and returns a
  ``RedirectResponse`` with a flash (issue #277 — operator feedback
  goes through the session cookie, not through a re-render).
- An **empty / malformed email** or a **duplicate canonical email**
  re-renders ``admin.html`` with the error in the flash slot (issues
  #277 + the duplicate-email pre-check from PR #414).
- **Success** re-renders ``admin.html`` without a flash, so the new
  row is immediately visible (the legacy route never redirected on
  success — it always re-rendered).

The use case delegates the actual domain validation to
:func:`app.core.application.auth.add_authorized_user.add_authorized_user`
so this slice does not re-implement the email-normalization /
duplicate-detection rules (rule §25 — no copy-paste helpers).
"""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import Response

from app.core.admin_helpers import _redirect_with_flash
from app.core.application.auth.add_authorized_user import (
    add_authorized_user as _add_user_use_case,
)
from app.core.domain.auth.rol import Rol
from app.core.ports.admin_port import AdminPanelContext, AdminTemplatePort
from app.core.ports.auth_port import AuthUsersPort


def add_user(
    auth_port: AuthUsersPort,
    template_adapter: AdminTemplatePort,
    request: Request,
    *,
    current_user: dict,
    email: str,
    rol: str,
    app_name: str,
    roles: frozenset[str],
) -> Response:
    """Insert a new authorized user and re-render ``admin.html``.

    The redirect-with-flash on invalid role and the re-render on every
    other outcome are the legacy contract preserved verbatim — see the
    module docstring for the per-path rationale.

    Raises ``ValueError`` on:
    - empty / malformed email (translated from the auth use case's
      email-format check)
    - duplicate canonical email (translated from the auth use case's
      pre-insert check or the race-condition ``DuplicateKeyError``
      catch)
    """
    rol_stripped = rol.strip()
    valid_roles = frozenset(r.value for r in Rol)

    # Invalid role → redirect with flash (legacy contract; the auth use
    # case would also raise ValueError, but the legacy admin route
    # distinguishes "invalid role" via a redirect so the operator sees
    # the message in the next GET rather than re-rendering the same
    # form state).
    if rol_stripped not in valid_roles:
        return _redirect_with_flash(
            request,
            "/admin",
            "danger",
            (
                f"invalid role: {rol_stripped!r}; "
                f"must be one of {sorted(valid_roles)}"
            ),
        )

    added_by = str(current_user.get("user_id", ""))
    try:
        _add_user_use_case(auth_port, email, Rol(rol_stripped), added_by)
    except ValueError as exc:
        # Domain validation failure (empty / malformed email,
        # duplicate). Re-render admin.html with the message in the
        # flash slot so the operator sees it next to the form.
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

    # Success: re-render so the new row is immediately visible.
    return template_adapter.render_panel(
        AdminPanelContext(
            request=request,
            current_user=current_user,
            users=auth_port.list_authorized_users(),
            app_name=app_name,
            roles=roles,
        )
    )
