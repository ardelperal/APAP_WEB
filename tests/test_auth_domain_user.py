"""Fail-closed role mapping for ``AuthorizedUser.from_row`` (issue #1032).

``from_row`` used to map ANY unknown ``rol`` string (a legacy row, a
typo like ``kay_user``) to ``KEY_USER`` — the write-capable role — so
templates would render a valid display. ``AuthorizedUser`` is the
identity object authorization layers consume, so the silent promotion
was fail-open: a typographic DB role became a writer. The fail-closed
substitute is ``READER`` (read-only, still renders a valid display).
"""

from __future__ import annotations

import pytest

from app.core.domain.auth.user import AuthorizedUser
from app.core.roles import Rol


def _row(rol: object) -> dict[str, object]:
    return {"id": "u-1", "email": "user@example.com", "rol": rol, "activo": True}


def test_from_row_unknown_rol_falls_back_to_reader_not_key_user() -> None:
    """A typographic DB rol must never gain key_user's write permissions."""
    user = AuthorizedUser.from_row(_row("kay_user"))

    assert user.rol is Rol.READER
    assert user.rol is not Rol.KEY_USER


def test_from_row_missing_rol_falls_back_to_reader() -> None:
    """An incomplete row (no ``rol`` projected) is a shell: render-valid,
    read-only."""
    user = AuthorizedUser.from_row({"id": "u-1", "email": "user@example.com"})

    assert user.rol is Rol.READER


@pytest.mark.parametrize("rol", ["admin", "developer", "key_user", "reader"])
def test_from_row_canonical_roles_keep_their_value(rol: str) -> None:
    """Canonical roles pass through unchanged."""
    assert AuthorizedUser.from_row(_row(rol)).rol is Rol(rol)


def test_from_row_unknown_rol_still_renders_email_and_id() -> None:
    """The shell contract holds: unknown rol degrades capabilities, not
    the template display fields."""
    user = AuthorizedUser.from_row(_row("ghost_role"))

    assert user.id == "u-1"
    assert user.email == "user@example.com"
    assert user.active is True
