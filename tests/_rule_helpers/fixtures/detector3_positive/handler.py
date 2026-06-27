"""Positive fixture for Detector 3 (http_exception_redirect).

Uses an alias (`HTTPException as HE`) so the detector must resolve the
import chain. Per spec REQ-1 scenario 3, aliases must NOT hide the
violation.
"""

from fastapi import HTTPException as HE


def handler_redirect():
    """302 via alias is still a Rule 7 violation."""
    raise HE(status_code=302, headers={"location": "/login"})
