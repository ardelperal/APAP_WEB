"""Use case: partial update of a material's text fields (PR 3 of #752).

Mirrors :func:`app.modules.materiales.application.create_material.create_material`:
only the keys the caller actually passes are written (the adapter's SQL
builder skips None-valued fields). Required-text validators run on any
of the three required fields the caller passed; a blank value raises
:class:`MaterialValidationError` before the port sees anything.

The kwargs signature mirrors the legacy ``update_material``
positional contract (a ``params: dict`` that may carry any of the
four writable fields) but converts it to explicit kwargs so the
caller cannot typo a key — a typo would have been silently
ignored before.
"""

from __future__ import annotations

from app.modules.materiales.application.create_material import (
    MaterialValidationError,
    _require_non_blank,
)
from app.modules.materiales.domain.material import Material
from app.modules.materiales.ports.materiales_port import MaterialesPort


def update_material(
    materiales_port: MaterialesPort,
    material_id: str,
    *,
    material: str | None = None,
    tamano: str | None = None,
    color: str | None = None,
    observaciones: str | None = None,
) -> Material | None:
    """Update a material's text fields and bump ``updated_at``.

    Validates the required text fields BEFORE the port call (only
    the keys actually present in ``params`` are stripped + checked;
    the adapter's SQL builder skips the rest). Returns ``None`` when no
    row matches the id (the adapter's UPDATE with RETURNING yields zero
    rows).

    Mirrors the partial-update contract the legacy
    ``update_material`` exported.
    """
    cleaned = _clean_update_payload(material, tamano, color, observaciones)
    if not cleaned:
        raise MaterialValidationError(  # noqa: TRY003 — operator-facing diagnostic
            "update_material requiere al menos un campo a actualizar"
        )

    return materiales_port.update_material(material_id, cleaned)


def _clean_update_payload(
    material: str | None,
    tamano: str | None,
    color: str | None,
    observaciones: str | None,
) -> dict[str, str | None]:
    """Strip + validate the kwargs into a partial-update payload dict.

    Splitting this out of :func:`update_material` keeps the use case
    function's CC below the ratchet's grade-A threshold (CC < 6).
    """
    cleaned: dict[str, str | None] = {}
    _add_text_field(cleaned, "material", material)
    _add_text_field(cleaned, "tamano", tamano)
    _add_text_field(cleaned, "color", color)
    if observaciones is not None:
        cleaned["observaciones"] = observaciones.strip()
    return cleaned


def _add_text_field(
    cleaned: dict[str, str | None], key: str, value: str | None
) -> None:
    """Strip + validate ``value`` and store it under ``key`` if non-None.

    A single-branch helper keeps the :func:`_clean_update_payload`
    function's CC at 1 (the four call sites are independent).
    """
    if value is None:
        return
    cleaned[key] = _require_non_blank(value, key)


__all__ = ["update_material"]
