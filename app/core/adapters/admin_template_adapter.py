"""Jinja template adapter for the admin pages.

The admin use cases need to render ``admin.html`` with a fixed context
shape (app_name, current_user, users, roles, optional error flash).
This adapter wraps :class:`fastapi.templating.Jinja2Templates` so the
use cases depend on a typed seam (``AdminTemplateAdapter``) rather
than the concrete Jinja object — consistent with rule §31 (domain
services depend on Protocol abstractions, not concrete transports).

The adapter does NOT talk to LocalBackend. The application lifespan
already owns the pooled ``Jinja2Templates`` instance on
``app.state.templates``; the DI helper
:func:`app.core.di.admin_di.get_admin_template_adapter` wraps it in
this adapter per request.

The ``to_dict()`` projection on each :class:`AuthorizedUser` keeps the
legacy template contract (the Jinja ``admin.html`` reads
``u.email`` / ``u.rol`` / ``u.activo`` — the keys
:meth:`AuthorizedUser.to_dict` returns). A future slice that
re-renders the admin table from typed entities directly can replace
this projection; it is left unchanged here to preserve the template
contract bit-for-bit.

The port-level entry point takes an :class:`AdminPanelContext`
dataclass (transport-agnostic) instead of seven keyword arguments;
the adapter destructures it and narrows the concrete ``Request`` /
``list[AuthorizedUser]`` types that the Jinja renderer needs.
"""
from __future__ import annotations

from fastapi.responses import Response
from fastapi.templating import Jinja2Templates

from app.core.ports.admin_port import AdminPanelContext, AdminTemplatePort


class AdminTemplateAdapter(AdminTemplatePort):
    """Typed seam for rendering the admin pages.

    Wraps the application-lifespan-owned ``Jinja2Templates`` so the
    admin use cases never import Jinja directly (rule §31). The
    adapter is stateless; instantiation is cheap and the DI helper
    builds a fresh instance per request.
    """

    def __init__(self, templates: Jinja2Templates) -> None:
        self._templates = templates

    def render_panel(self, context: AdminPanelContext) -> Response:
        """Render ``admin.html`` with the admin-panel context.

        The ``error_message`` / ``error_type`` pair populates the
        flash alert slot above the form when set; otherwise the
        template renders the table without a flash (the happy-path
        branch). The CSRF token comes from
        :func:`app.core.csrf.csrf_token_context_processor` — the
        adapter does not pass it explicitly because the lifespan
        installs the context processor on the shared
        ``Jinja2Templates`` instance.
        """
        return self._templates.TemplateResponse(
            request=context.request,
            name="admin.html",
            context={
                "app_name": context.app_name,
                "current_user": context.current_user,
                "users": [user.to_dict() for user in context.users],
                "roles": sorted(context.roles),
                "error_message": context.error_message,
                "error_type": context.error_type,
            },
        )
