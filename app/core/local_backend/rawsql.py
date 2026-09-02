"""``POST /api/database/advance/rawsql`` handler stub (M0 of self-host-backend-coolify).

The full implementation will follow the next TDD step. The stub returns
``{"rows": [], "rowCount": 0}`` so the import-time wiring does not
break; the test for this handler is not yet written.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.post("/database/advance/rawsql")
async def execute_rawsql() -> dict:
    return {"rows": [], "rowCount": 0}
