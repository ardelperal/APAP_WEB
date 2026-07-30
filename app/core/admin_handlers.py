"""Admin-panel route handlers extracted from ``app/main.py::create_app``.

These handlers (``admin``, ``admin_add_user``, ``admin_deactivate_user``) are
application-level glue — they share the ``templates`` instance and the
``settings`` singleton. ``create_app`` imports and registers them.

Issue #336: extracted from ``create_app`` to reduce the factory's
cyclomatic complexity (CC) and line count.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.core import config as config_module
from app.core.admin_helpers import _pop_flash, _redirect_with_flash
from app.core.auth import (
    VALID_ROLES,
    add_authorized_user,
    deactivate_authorized_user,
    list_authorized_users,
)
from app.core.auth_dependencies import (
    get_insforge_client_dep as get_insforge_client,
)
from app.core.auth_dependencies import (
    require_developer_user_redirect,
    return_early_if_response,
)
from app.core.insforge import InsForgeClient


@dataclass
class _AddError:
    """Lightweight error carrier for _add_user_or_error."""

    __slots__ = ("message", "error_type")

    message: str
    error_type: str


def _add_user_or_error(
    client: InsForgeClient, email: str, rol: str, added_by: str
) -> _AddError | None:
    """Call add_authorized_user; return an error tuple or None on success."""
    if not email or not rol:
        return _AddError(message="email and rol are required", error_type="danger")
    try:
        add_authorized_user(client, email=email, role=rol, added_by=added_by)
        return None
    except ValueError as exc:
        return _AddError(message=str(exc), error_type="danger")


def register_admin_routes(app: FastAPI, templates) -> None:
    """Register the admin-panel routes on ``app``.

    Registers: ``/admin``, ``/admin/users``, ``/admin/users/{user_id}/deactivate``.
    These are application-level glue routes that share the ``templates``
    instance created inside ``create_app``.
    """
    settings = config_module.get_settings()

    @app.get("/admin", response_class=HTMLResponse)
    def admin(
        request: Request,
        current_user: Response | dict = Depends(require_developer_user_redirect),
        client: InsForgeClient = Depends(get_insforge_client),
    ):
        """Developer-only user management panel.

        ``require_developer_user_redirect`` (issue #146) ya redirige a
        ``/login`` si no hay sesion, a ``/unauthorized`` si la sesion
        expiro o el rol es insuficiente (cualquier rol distinto de
        ``developer``), y emite ``log_safe("auth.denied", ...)`` en cada
        denegacion para audit trail. Antes de #146 este handler repetia
        inline ``current_user.get("rol") != "developer"`` — duplicacion
        eliminada al consolidar la comprobacion del rol en la dep.
        """
        if (early := return_early_if_response(current_user)) is not None:
            return early
        flash_context = _pop_flash(request)
        users = list_authorized_users(client)
        response: Response = templates.TemplateResponse(
            request=request,
            name="admin.html",
            context={
                "app_name": settings.app_name,
                "current_user": current_user,
                "users": users,
                "roles": sorted(VALID_ROLES),
                "error_message": flash_context.message if flash_context else None,
                "error_type": flash_context.error_type if flash_context else None,
            },
        )
        if flash_context:
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
        current_user: Response | dict = Depends(require_developer_user_redirect),
        client: InsForgeClient = Depends(get_insforge_client),
        email: str = Form(""),
        rol: str = Form(""),
    ) -> Response:
        """Add a new authorized user. Developer only.

        Sync ``def`` (not ``async def``) so FastAPI runs the handler
        in the threadpool and the sync InsForgeClient doesn't block
        the event loop. Other admin handlers use the same style.
        Form fields are declared as ``Form(...)`` parameters instead
        of pulling them out of ``await request.form()`` so the
        contract is obvious from the signature.

        Issue #146 — la dep inyectada aplica el check de developer (rol
        insuficiente → redirect ``/unauthorized`` + ``log_safe``).

        Issue #277 — ValueError from add_authorized_user (duplicate or
        validation) is caught and rendered in the admin page instead of
        silently redirecting, giving the operator actionable feedback.
        """
        if (early := return_early_if_response(current_user)) is not None:
            return early
        assert isinstance(current_user, dict)
        email, rol = email.strip(), rol.strip()

        if rol not in VALID_ROLES:
            return _redirect_with_flash(
                request,
                "/admin",
                "danger",
                f"invalid role: {rol!r}; must be one of {sorted(VALID_ROLES)}",
            )

        add_err = _add_user_or_error(client, email, rol, current_user["user_id"])
        users = list_authorized_users(client)
        return templates.TemplateResponse(
            request,
            "admin.html",
            {
                "app_name": settings.app_name,
                "current_user": current_user,
                "users": users,
                "roles": sorted(VALID_ROLES),
                "error_message": add_err.message if add_err else None,
                "error_type": add_err.error_type if add_err else None,
            },
        )

    @app.post("/admin/users/{user_id}/deactivate")
    def admin_deactivate_user(
        request: Request,
        user_id: str,
        current_user: Response | dict = Depends(require_developer_user_redirect),
        client: InsForgeClient = Depends(get_insforge_client),
    ) -> Response:
        """Deactivate an authorized user. Developer only.

        Issue #146 — la dep inyectada aplica el check de developer (rol
        insuficiente → redirect ``/unauthorized`` + ``log_safe``).
        Issue #279 — ValueError from the last-developer guard is caught
        and rendered as a flash error in admin.html.
        """
        if (early := return_early_if_response(current_user)) is not None:
            return early
        try:
            deactivate_authorized_user(client, user_id)
        except ValueError as exc:
            # Issue #279: render admin.html with flash error instead of
            # silently redirecting, mirroring the admin_add_user pattern.
            users = list_authorized_users(client)
            return templates.TemplateResponse(
                request,
                "admin.html",
                {
                    "app_name": settings.app_name,
                    "current_user": current_user,
                    "users": users,
                    "roles": sorted(VALID_ROLES),
                    "error_message": str(exc),
                    "error_type": "danger",
                },
            )
        return _redirect("/admin")

    def _redirect(path: str) -> Response:
        return RedirectResponse(url=path, status_code=302)
