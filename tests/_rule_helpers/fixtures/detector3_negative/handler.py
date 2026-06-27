"""Negative fixture for Detector 3 (http_exception_redirect).

HTTPException with status_code=404 (not a redirect) — Detector 3 must NOT
flag this.
"""

from fastapi import HTTPException


def handler_not_found():
    """404 is a real error, not a redirect."""
    raise HTTPException(status_code=404)
