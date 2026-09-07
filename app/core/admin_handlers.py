"""Admin-panel route handlers extracted from ``app/main.py::create_app``.

These handlers (``admin``, ``admin_add_user``, ``admin_deactivate_user``)
are thin HTTP-only glue that delegates the domain work to the
application-layer use cases:

- :func:`app.core.application.admin.render_admin_panel.render_admin_panel`
- :func:`app.core.application.admin.add_user.add_user`
- :func:`app.core.application.admin.deactivate_user.deactivate_user`

Each handler composes the :class:`AuthUsersPort` (PR #414 data seam)
and the :class:`AdminTemplateAdapter` (this slice's renderer seam)
through FastAPI ``Depends`` providers — the route bodies never import
``AuthUsersPort`` or ``Jinja2Templates`` directly.

``register_admin_routes`` keeps the same signature as the pre-Phase-1
module so ``app/main.py::create_app`` does not need to change.
"""
from __future__ import annotations

from typing import Annotated, cast

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, Response

from app.core import config as config_module
from app.core.adapters.admin_template_adapter import AdminTemplateAdapter
from app.core.admin_helpers import _pop_flash
from app.core.application.admin.add_user import add_user as _add_user_use_case
from app.core.application.admin.deactivate_user import (
    deactivate_user as _deactivate_user_use_case,
)
from app.core.application.admin.render_admin_panel import (
    render_admin_panel as _render_admin_panel_use_case,
)
from app.core.auth import VALID_ROLES
from app.core.auth_dependencies import (
    require_developer_user_redirect,
    return_early_if_response,
)
from app.core.di.admin_di import get_admin_template_adapter
from app.core.di.auth_di import get_auth_users_port
from app.core.ports.auth_port import AuthUsersPort


def register_admin_routes(app: FastAPI, templates) -> None:
    """Register the admin-panel routes on ``app``.

    Registers: ``/admin``, ``/admin/users``, ``/admin/users/{user_id}/deactivate``.
    The shared ``templates`` parameter is accepted for backwards
    compatibility with :func:`app.main.create_app`; the per-request
    ``Jinja2Templates`` instance lives on ``app.state.templates`` and
    is wrapped by the ``AdminTemplateAdapter`` injected via
    :func:`app.core.di.admin_di.get_admin_template_adapter`.
    """
    del templates  # The adapter resolves the per-app templates from app.state.
    settings = config_module.get_settings()

    @app.get("/admin", response_class=HTMLResponse)
    def admin(
        request: Request,
        current_user: Annotated[Response | dict, Depends(require_developer_user_redirect)],
        auth_port: Annotated[AuthUsersPort, Depends(get_auth_users_port)],
        template_adapter: Annotated[AdminTemplateAdapter, Depends(get_admin_template_adapter)],
    ):
        """Developer-only user management panel.

        ``require_developer_user_redirect`` (issue #146) redirects to
        ``/login`` if there is no session and to ``/unauthorized`` if
        the session is expired or the rol is anything other than
        ``developer``; it emits ``log_safe("auth.denied", ...)`` on
        every denial for audit trail. The pre-#146 inline
        ``current_user.get("rol") != "developer"`` check was removed
        when the dep consolidated the role check.
        """
        if (early := return_early_if_response(current_user)) is not None:
            return early
        current_user_typed: dict = cast("dict", current_user)
        flash_context = _pop_flash(request)
        response = _render_admin_panel_use_case(
            auth_port,
            template_adapter,
            request,
            current_user=current_user_typed,
            app_name=settings.app_name,
            roles=VALID_ROLES,
            error_message=flash_context.message if flash_context else None,
            error_type=flash_context.error_type if flash_context else None,
        )
        if flash_context is not None:
            response.set_cookie(
                key="apap_session",
                value=flash_context.cookie_value,
                max_age=60 * 60 * 24 * 7,
                httponly=True,
                secure=True,
                samesite="strict",
            )
        return response

    @app.post("/admin/users")
    def admin_add_user(
        request: Request,
        current_user: Annotated[Response | dict, Depends(require_developer_user_redirect)],
        auth_port: Annotated[AuthUsersPort, Depends(get_auth_users_port)],
        template_adapter: Annotated[AdminTemplateAdapter, Depends(get_admin_template_adapter)],
        email: Annotated[str, Form()] = "",
        rol: Annotated[str, Form()] = "",
    ) -> Response:
        """Add a new authorized user. Developer only.

        Sync ``def`` (not ``async def``) so FastAPI runs the handler
        in the threadpool — the same style as the other admin
        handlers. The domain validation, redirect-with-flash for the
        invalid-role path, and re-render-with-flash for the
        duplicate-email path are owned by
        :func:`app.core.application.admin.add_user.add_user`; the
        route only wires the HTTP boundary.

        Issue #146 — the dep injects the developer check (insufficient
        rol → redirect ``/unauthorized`` + ``log_safe``).
        """
        if (early := return_early_if_response(current_user)) is not None:
            return early
        current_user_typed: dict = cast("dict", current_user)
        return _add_user_use_case(
            auth_port,
            template_adapter,
            request,
            current_user=current_user_typed,
            email=email,
            rol=rol,
            app_name=settings.app_name,
            roles=VALID_ROLES,
        )

    @app.post("/admin/users/{user_id}/deactivate")
    def admin_deactivate_user(
        request: Request,
        user_id: str,
        current_user: Annotated[Response | dict, Depends(require_developer_user_redirect)],
        auth_port: Annotated[AuthUsersPort, Depends(get_auth_users_port)],
        template_adapter: Annotated[AdminTemplateAdapter, Depends(get_admin_template_adapter)],
    ) -> Response:
        """Deactivate an authorized user. Developer only.

        The last-developer guard, the not-found disambiguation, and
        the redirect-vs-re-render response shape are owned by
        :func:`app.core.application.admin.deactivate_user.deactivate_user`
        (issue #279); the route only wires the HTTP boundary.

        Issue #146 — the dep injects the developer check (insufficient
        rol → redirect ``/unauthorized`` + ``log_safe``).
        """
        if (early := return_early_if_response(current_user)) is not None:
            return early
        current_user_typed: dict = cast("dict", current_user)
        return _deactivate_user_use_case(
            auth_port,
            template_adapter,
            request,
            current_user=current_user_typed,
            user_id=user_id,
            app_name=settings.app_name,
            roles=VALID_ROLES,
        )
