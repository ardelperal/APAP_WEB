"""Positive fixture for Detector 2 (auth_defaults_true).

A file in core/auth*.py that defaults is_authorized to True (permit-by-default).
Detector 2 must flag this.
"""


def load_session_defaults():
    """Default-permit violates Rule 6 (default-deny)."""
    payload = {}
    return payload.get("is_authorized", True)
