"""Shared HTML form-render helper for module routes (slice #681).

The ``_render_form`` helper in :mod:`app.modules.acogidas.routes`,
:mod:`app.modules.adopciones.routes`, :mod:`app.modules.foster.routes`,
:mod:`app.modules.materiales.routes`, and the
``_render_terapia_form`` helper in :mod:`app.modules.salud.routes`
were each a 22-line near-duplicate that wrapped a single
``TemplateResponse`` call. With each wrapper weighing ~80 tokens, the
JSCPD ratchet on the lint job (issue #681) flagged every pair as a
duplicate region.

This module exposes the ``render_module_form`` helper that the per-module
``functools.partial`` wrapper closes over (template name + the module's
``_templates`` instance). The per-module wrapper reduces from a
22-line function to a single ``partial(...)`` assignment, which keeps
each module's contribution below the JSCPD 50-token pair threshold
once the helper is shared.

Kept out of :mod:`app.core.rendering` (which is reserved for
cross-cutting rendering seams like auth flash messages) to make the
import direction obvious: ``app.modules._form_render`` depends on
``fastapi.templating`` and ``app.modules`` routes depend on this.

Scope kept intentionally small: only the function the duplicate
``_render_form`` wrappers actually share. Larger refactors (the
``edit_<entity>_form`` route handlers, the service-layer
``_optional_text`` helper) are separate issues and out of scope here.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Any

from fastapi import Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates


def render_module_form(  # noqa: PLR0913  # 8 args is minimal: templates + 4-context-key + form_action + template_name + status_code
    templates: Jinja2Templates,
    request: Request,
    user: Any,
    form_data: dict[str, Any],
    error: str | None,
    form_action: str,
    template_name: str,
    status_code: int = status.HTTP_200_OK,
) -> HTMLResponse:
    """Render a module's ``<module>/form.html`` with the standard context keys."""
    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context={
            "user": user,
            "form_data": form_data,
            "error": error,
            "form_action": form_action,
        },
        status_code=status_code,
    )


def make_render_form(
    templates: Jinja2Templates, template_name: str
) -> Callable[..., HTMLResponse]:
    """Return a partial of :func:`render_module_form` with the module's template bound.

    Each module's wrapper is one line::

        _render_form = make_render_form(_templates, "acogidas/form.html")

    The wrapper preserves the original signature so existing call sites
    (``_render_form(request, user, form_data, error, form_action[, status_code])``)
    continue to work without edits.
    """
    # The partial binds ``templates`` positionally and ``template_name``
    # by keyword, leaving the six per-call kwargs as the only positional
    # arguments the wrapper must accept.
    return partial(
        render_module_form, templates, template_name=template_name
    )


__all__ = ["render_module_form", "make_render_form"]
