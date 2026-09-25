"""Actor-required create/close flow for acogidas (issue #945, A-13).

``create_acogida`` and ``close_acogida`` both require the acting
user's UUID as ``created_by`` on the lifecycle events they emit
(``animal_lifecycle_events.created_by`` is ``UUID NOT NULL``;
maintainer decision, option a: reject the write instead of inventing
a system actor). ``acogidas/routes.py`` is a mutation-site ratchet
baseline (``scripts/check_mutation_sites.py``) with no headroom, so
the actor lookup and the close path's ``ActorRequiredError`` -> 403
mapping live here instead of growing the route bodies.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

import app.modules.acogidas.service as acogidas_service
from app.core._module_helpers._actor import actor_user_id
from app.core.data_access import SqlExecutor
from app.modules.animals import ActorRequiredError


def create_acogida_with_actor(
    client: SqlExecutor, form_data: dict[str, Any], user: object
) -> acogidas_service.Acogida:
    """Create a stay, resolving the acting user's UUID from ``user``.

    ``ActorRequiredError`` is a ``ValueError`` subclass; the route's
    existing ``except ValueError`` 422 path handles a missing actor
    the same way it handles any other validation failure, so no new
    branch is needed in ``create_acogida_view``.
    """
    return acogidas_service.create_acogida(
        client, form_data, actor_user_id=actor_user_id(user)
    )


def close_acogida_or_403(
    client: SqlExecutor, acogida_id: str, user: object
) -> acogidas_service.Acogida | None:
    """Close a stay, mapping a missing actor to an HTTP 403.

    Unlike create, a close has no form to re-render with a 422: a
    session without an acting user cannot close a stay at all, so a
    missing actor maps straight to 403 instead.
    """
    try:
        return acogidas_service.close_acogida(
            client, acogida_id, actor_user_id=actor_user_id(user)
        )
    except ActorRequiredError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN) from exc


__all__ = ["close_acogida_or_403", "create_acogida_with_actor"]
