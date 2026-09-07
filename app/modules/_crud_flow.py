"""Shared CRUD helpers for module routes (slice #681, follow-up to _form_render).

The ``edit_<entity>_form`` route handlers in :mod:`app.modules.acogidas.routes`,
:mod:`app.modules.adopciones.routes`, :mod:`app.modules.materiales.routes`,
and the ``edit_terapia_form`` handler in :mod:`app.modules.salud.routes`
were each a 22-line near-duplicate that:
1. Early-returns if the auth gate redirects.
2. Fetches the entity by id.
3. 404s if not found.
4. Renders the form with form_data mapped from the entity.

With each handler weighing ~105 tokens, the JSCPD ratchet (issue #681)
flagged every pair. This module extracts the shared flow into
:func:`render_edit_form` so each module's wrapper becomes a thin
client of the helper. Per-module wrappers retain their route
decorator and dependency injection so the FastAPI surface is unchanged.

Kept out of :mod:`app.core.rendering` (which is reserved for
cross-cutting rendering seams like auth flash messages) to make the
import direction obvious: ``app.modules._crud_flow`` depends on
``fastapi`` and ``app.modules`` routes depend on this.

Scope kept intentionally small: only the function the duplicate
``edit_<entity>_form`` handlers actually share. The service-layer
``_optional_text`` helper duplicate is a separate refactor and out of
scope here.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import HTTPException, Request, status
from fastapi.responses import HTMLResponse, Response


def render_edit_form(  # noqa: PLR0913  # 8 kwargs needed: request, user, client, entity_id, fetch, to_form_data, render_form, form_action
    *,
    request: Request,
    user: Any,
    client: Any,
    entity_id: str,
    fetch: Callable[[Any, str], Any],
    to_form_data: Callable[[Any], dict[str, Any]],
    render_form: Callable[..., HTMLResponse],
    form_action: str,
) -> Response:
    """Render the edit form for an entity fetched by id (issue #681 — JSCPD ratchet).

    Returns early with the auth-redirect response if the auth gate sends
    one; 404s when the entity does not exist; otherwise renders the
    module's standard form template via ``render_form``.
    """
    # ``return_early_if_response`` is a no-op happy-path helper that
    # returns ``None`` when the user is authorised; importing it at
    # module level would create a circular dependency through
    # ``app.core.auth_dependencies`` (the helper itself is a thin wrapper
    # around the auth cache that ``_crud_flow`` does not otherwise
    # need). The lazy import keeps the module graph acyclic.
    from app.core.auth_dependencies import (
        return_early_if_response,  # lazy-import: avoids circular import through app.core.auth_dependencies
    )

    if (early := return_early_if_response(user)) is not None:
        return early
    entity = fetch(client, entity_id)
    if entity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return render_form(
        request,
        user,
        to_form_data(entity),
        None,
        form_action,
    )


__all__ = ["render_edit_form"]
