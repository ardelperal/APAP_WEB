"""Use cases for the admin slice.

The admin slice composes the :class:`~app.core.ports.auth_port.AuthUsersPort`
for data access (already merged in PR #414) and the
:class:`~app.core.adapters.admin_template_adapter.AdminTemplateAdapter`
for rendering. Each module in this package is one use case: a thin
function that takes its dependencies, applies the route-specific
response-shape decision (redirect vs re-render), and returns a
``Response``.

The legacy ``app.core.admin_handlers`` module now imports these use
cases so the route bodies stay thin (rule §1 — routes handle HTTP only).
The pre-Phase-1 helpers (``_pop_flash``, ``_redirect_with_flash``) stay
in ``app.core.admin_helpers`` so the admin use case that needs the
flash-cookie redirect (the invalid-role path of ``add_user``) keeps
working without re-importing session machinery.

Hexagonal taxonomy:

- Port       :mod:`app.core.ports.auth_port` (data seam, PR #414)
- THIS       :mod:`app.core.application.admin` (use cases)
- Adapter    :mod:`app.core.adapters.admin_template_adapter` (Jinja renderer)
- DI         :mod:`app.core.di.admin_di` (FastAPI wiring)
"""

from __future__ import annotations

from app.core.application.admin.add_user import add_user
from app.core.application.admin.deactivate_user import deactivate_user
from app.core.application.admin.render_admin_panel import render_admin_panel

__all__ = ["add_user", "deactivate_user", "render_admin_panel"]
