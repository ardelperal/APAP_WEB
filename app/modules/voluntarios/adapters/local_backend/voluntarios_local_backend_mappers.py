"""Row-to-domain mappers for the voluntarios LocalBackend adapter.

All functions are pure: no I/O, no protocol calls, no FastAPI.
"""

from __future__ import annotations

from app.modules.voluntarios.domain.voluntario import Voluntario


def _optional_str(row: dict[str, object], key: str) -> str | None:
    value = row.get(key)
    return None if value is None else str(value)


def row_to_voluntario(row: dict[str, object]) -> Voluntario:
    """Translate a PostgREST row dict to the hexagonal ``Voluntario`` entity.

    All column names are lowercase per ``app/core/domain_voluntarios.py``.
    """
    return Voluntario(
        id=str(row["id"]),
        voluntario=str(row["voluntario"]),
        activo=bool(row.get("activo", True)),
        tel1=_optional_str(row, "tel1"),
        tel2=_optional_str(row, "tel2"),
        email=_optional_str(row, "email"),
        dni=_optional_str(row, "dni"),
        fecha_alta=_optional_str(row, "fecha_alta"),
        updated_at=_optional_str(row, "updated_at"),
    )


__all__ = ["row_to_voluntario"]
