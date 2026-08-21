"""Hexagonal port for the admin-template rendering seam.

The :class:`AdminTemplatePort` Protocol is the seam between the admin
application (use-case) layer and the Jinja template renderer. Domain
code in :mod:`app.core.application.admin` depends on this Protocol
only; the concrete Jinja-backed implementation lives in
:mod:`app.core.adapters.admin_template_adapter`, and a future
non-Jinja renderer (e.g. an HTMX-fragment-only response) can live
alongside it under :mod:`app.core.adapters` without touching the use
cases.

:class:`AdminPanelContext` bundles the kwargs the legacy
``admin.html`` template reads (``app_name``, ``current_user``,
``users``, ``roles``, ``error_message`` / ``error_type`` for the flash
slot) so a use case can introduce a sibling port method or a new port
without breaking this contract. The dataclass replaces a seven-arg
``render_panel`` signature that would otherwise trip
``PLR0913`` (too-many-arguments) in the ratchet.

Ports stay free of web-framework imports per rule §33
(``check_layers.py``). The ``request`` field on the dataclass and the
return type use :class:`~typing.Any` rather than
:class:`fastapi.Request` / :class:`fastapi.Response` so the port file
passes the layer-purity gate at parse time. The adapter re-narrows
the concrete types.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class AdminPanelContext:
    """Transport-agnostic payload required to render ``admin.html``.

    Bundles the seven keyword arguments that the legacy template reads
    so :meth:`AdminTemplatePort.render_panel` stays under the
    ``PLR0913`` five-argument ceiling (issue #380 + ratchet). The
    dataclass itself is framework-free; concrete ``request`` /
    ``users`` types are narrowed at the adapter boundary.

    Use cases build one of these per render call::

        ctx = AdminPanelContext(
            request=request,
            current_user=current_user,
            users=auth_port.list_authorized_users(),
            app_name=app_name,
            roles=roles,
            error_message=str(exc),
            error_type="danger",
        )
        return template_adapter.render_panel(ctx)

    ``frozen=True`` blocks accidental mutation after the use case hands
    the context off; the inner ``list`` / ``dict`` fields remain
    mutable by reference, which matches the read-only contract the
    adapter relies on.
    """

    request: Any
    current_user: dict[str, Any]
    users: list[Any]
    app_name: str
    roles: frozenset[str] | list[str]
    error_message: str | None = None
    error_type: str | None = None


class AdminTemplatePort(Protocol):
    """Backend-agnostic interface for rendering the admin pages.

    A single public method, :meth:`render_panel`, wraps the application
    lifespan-owned template renderer so the admin use cases never
    import Jinja directly (rule §31). Implementations are stateless;
    instantiation is cheap and the DI helper builds a fresh instance
    per request.

    ``AdminPanelContext.error_message`` / ``error_type`` populate the
    flash alert slot above the form when set; otherwise the template
    renders the table without a flash (the happy-path branch).
    """

    def render_panel(self, context: AdminPanelContext) -> Any:
        """Render ``admin.html`` with the admin-panel context."""
