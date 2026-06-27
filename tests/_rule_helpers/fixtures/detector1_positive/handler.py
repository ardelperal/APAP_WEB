"""Positive fixture for Detector 1 (rule_uses_execute_sql).

A POST handler that calls client.execute_sql directly. Detector 1 must
flag this; Detector 2/3/4 must NOT.
"""

from fastapi import APIRouter

router = APIRouter()


@router.post("/things")
def handler_create_thing(client):
    """POST route that bypasses the service layer."""
    client.execute_sql("INSERT INTO things (name) VALUES ($1)", ["x"])
    return None
