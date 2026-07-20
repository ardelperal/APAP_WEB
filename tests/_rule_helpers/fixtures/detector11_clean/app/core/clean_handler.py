"""Clean fixture for Detector 11 (Rule 26): a local import inside a
function body IS justified by a 'lazy-import:' marker comment."""

from __future__ import annotations


def get_rol():
    # lazy-import: avoids circular import with app.core.auth
    from app.core.auth import Rol

    return Rol
