"""Shared actor-id extraction for route-layer audit fields (issue #945, A-13).

``adopciones/routes.py`` and ``acogidas/routes.py`` each need the
authenticated user's ``user_id`` for two things: audit logging
(``actor_user_id=`` on service calls) and, since #945, the acting
user's UUID for lifecycle-event ``created_by``
(``animal_lifecycle_events.created_by`` is ``UUID NOT NULL``, and the
maintainer decision — option a — rejects a write instead of inventing
a system actor). ``adopciones/routes.py`` had its own private
``_actor_user_id`` helper before this slice; ``acogidas/routes.py``
needed the same extraction newly added for ``create_acogida`` /
``close_acogida``. Rather than adding a second private copy, this
module gives both route modules one shared extractor.

``sanidad/routes.py``, ``sanidad/batch_routes.py`` and
``salud/routes.py`` still carry their own private duplicates —
migrating them is out of scope for #945's budget (they don't call any
lifecycle-event use case that requires the actor).

Kept out of :mod:`app.core.rendering` (reserved for cross-cutting
rendering seams) for the same reason as ``_crud_flow.py``: the import
direction should stay obvious (routes depend on this, not vice versa).
Typed with a plain ``object`` parameter (not ``AuthenticatedUser``) so
this module has no dependency on ``app.core.di`` — see
``scripts/check_layers.py``'s layer-direction rule.
"""

from __future__ import annotations


def actor_user_id(user: object) -> str | None:
    """Extract ``user_id`` from the auth payload for audit logging.

    ``user`` is the value returned by ``require_authorized_user`` /
    ``require_permission`` (a dict-like). When the upstream dep
    returned a ``RedirectResponse`` (no session, deactivated, etc.)
    callers have already returned early via
    ``return_early_if_response``, so this only sees a dict.
    """
    if isinstance(user, dict):
        uid = user.get("user_id")
        return str(uid) if uid is not None else None
    return None


__all__ = ["actor_user_id"]
