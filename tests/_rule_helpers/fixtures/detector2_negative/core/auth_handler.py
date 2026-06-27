"""Negative fixture for Detector 2 (auth_defaults_true).

A file in core/auth*.py that defaults is_authorized to False (default-deny).
Detector 2 must NOT flag this.
"""


def load_session_defaults():
    """Default-deny is the correct Rule 6 pattern."""
    payload = {}
    return payload.get("is_authorized", False)
