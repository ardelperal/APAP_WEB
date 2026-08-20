"""Hexagonal port for the admin-template rendering seam.

The :class:`AdminTemplatePort` Protocol is the seam between the admin
application (use-case) layer and the Jinja template renderer. Domain
code in :mod:`app.core.application.admin` depends on this Protocol
only; the concrete Jinja-backed implementation lives in
:mod:`app.core.adapters.admin_template_adapter`, and a future
non-Jinja renderer (e.g. an HTMX-fragment-only response) can live
alongside it under :mod:`app.core.adapters` without touching the use
cases.

The render method carries the full context shape the legacy
``admin.html`` template reads (``app_name``, ``current_user``,
``users``, ``roles``, ``error_message`` / ``error_type`` for the flash
slot) so use cases that need a different template (e.g. a future
``admin.html`` redesign) can introduce a sibling port method or a new
port without breaking this contract.

Ports stay free of web-framework imports per rule §33
(``check_layers.py``). The ``request`` and return types use
:class:`~typing.Any` rather than :class:`fastapi.Request` /
:class:`fastapi.Response` so the port file passes the layer-purity
gate at parse time. The adapter re-narrows the contract via its own
``render_panel`` implementation.
"""
from __future__ import annotations

from typing import Any, Protocol


class AdminTemplatePort(Protocol):
    """Backend-agnostic interface for rendering the admin pages.

    A single public method, :meth:`render_panel`, wraps the application
    lifespan-owned template renderer so the admin use cases never
    import Jinja directly (rule §31). Implementations are stateless;
    instantiation is cheap and the DI helper builds a fresh instance
    per request.

    ``error_message`` / ``error_type`` populate the flash alert slot
    above the form when set; otherwise the template renders the table
    without a flash (the happy-path branch).
    """

    def render_panel(
        self,
        request: Any,
        current_user: dict,
        users: list[Any],
        app_name: str,
        roles: frozenset[str] | list[str],
        error_message: str | None = None,
        error_type: str | None = None,
    ) -> Any:
        """Render ``admin.html`` with the admin-panel context."""