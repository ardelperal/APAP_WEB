"""Positive fixture for Detector 11 (Rule 26): a local import inside a
function body with NO justification comment must be flagged."""

from __future__ import annotations


def get_rol():
    from app.core.auth import Rol

    return Rol
