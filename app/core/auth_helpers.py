"""Canonical email identity helpers for the auth layer.

Single source of truth (AGENTS.md §4 + §25) — every auth boundary that
touches an email MUST go through `normalize_email` + `validate_email_format`.
"""

from __future__ import annotations

import re

_EMAIL_FORMAT_RE = re.compile(r"^[^\@\s]+@[^\@\s]+\.[^\@\s]+$")


def normalize_email(email: str) -> str:
    """Canonical email form: stripped + lowercased."""
    return email.strip().lower()


def validate_email_format(email: str) -> None:
    """Reject empty + malformed emails at the service boundary.

    Raises ValueError with a descriptive message; the admin route renders it.
    """
    if not email:
        raise ValueError("email cannot be empty")
    if not _EMAIL_FORMAT_RE.match(email):
        raise ValueError(f"email format invalid: {email!r}")
