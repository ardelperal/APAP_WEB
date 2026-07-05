"""Per-estancia junction routes placeholder for FOSTER-04 (#46).

PR A only ships the service skeleton; the per-estancia junction routes
+ the ``/acogidas/{id}/materiales`` templates + the detail-page
integration land in PR C. This stub keeps
``app.modules.materiales.__init__`` importable so the dataclasses +
service functions resolve cleanly during PR A.

Do NOT add handler functions here in PR A — they belong to PR C per the
SDD chained-PR split.
"""

from fastapi import APIRouter

# Prefix intentionally omitted: the handler URLs are absolute
# (``/acogidas/{id}/materiales``) and the prefix would conflict with
# ``app/modules/acogidas/routes.py``. The router is tagged
# ``materiales-junction`` so the OpenAPI doc groups the per-stay
# material endpoints next to the catalog endpoints without leaking
# the implementation detail into the URL namespace.
router = APIRouter(tags=["materiales-junction"])
