"""Use case: partial update of a material's text fields.

PR 3 of issue #752. Mirrors ``create_material``: only the keys the
caller actually passes are written (the adapter's SQL builder skips
None-valued fields). Required-text validators run on any of the
three required fields the caller passed; a blank value raises
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

    Each kwarg is ``None``-skipped by the adapter's SQL builder;
    only the keys actually passed are written. Required-text
    validators run on any of the three required fields the caller
    passed; a blank value raises :class:`MaterialValidationError`
    before the port sees anything. Returns ``None`` when no row
    matches the id (the adapter's UPDATE with RETURNING yields zero
    rows).
    """
    cleaned: dict[str, str | None] = {}
    if material is not None:
        cleaned["material"] = _require_non_blank(material, "material")
    if tamano is not None:
        cleaned["tamano"] = _require_non_blank(tamano, "tamano")
    if color is not None:
        cleaned["color"] = _require_non_blank(color, "color")
    if observaciones is not None:
        cleaned["observaciones"] = observaciones.strip()

    if not cleaned:
        raise MaterialValidationError(  # noqa: TRY003 — operator-facing diagnostic
            "update_material requiere al menos un campo a actualizar"
        )

    return materiales_port.update_material(material_id, cleaned)


__all__ = ["update_material"]
