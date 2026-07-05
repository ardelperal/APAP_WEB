"""Catalog routes placeholder for FOSTER-04 (#46).

PR A only ships the service skeleton; the catalog CRUD routes land in
PR B. This stub keeps ``app.modules.materiales.__init__`` importable
so subagent and test code can pull the dataclasses + service functions
without circular-import headaches.

Do NOT add handler functions here in PR A — they belong to PR B per the
SDD chained-PR split.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/materiales", tags=["materiales"])
