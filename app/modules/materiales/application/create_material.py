"""Use case: create a new material in the catalog.

PR 3 of issue #752 (materiales hexagonal refactor). The application
layer owns the validation policy the legacy ``create_material``
exported: ``material``, ``tamano``, ``color`` are required, non-blank
after ``.strip()``; ``observaciones`` is optional. Validation runs
BEFORE the port call so a blank submission raises
:class:`MaterialValidationError` without touching transport.

Rule §22: no SQL or transport imports. The dataclass return type
(:class:`Material`) lives in the domain module.

Mirrors the pattern in
:mod:`app.modules.animals.application.create_animal`: one file per
use case, ``__all__`` exposes the public surface, the validation
exception subclasses :class:`ValueError` so legacy
``except ValueError`` clauses keep working.
"""

from __future__ import annotations

from app.modules.materiales.domain.material import Material
from app.modules.materiales.ports.materiales_port import MaterialesPort


class MaterialValidationError(ValueError):
    """Raised when material inputs fail the domain-validation rules.

    Subclasses :class:`ValueError` so existing ``except ValueError``
    clauses in legacy callers keep catching it. The use case carries
    the operator-facing message verbatim to the route layer.
    """


def _require_non_blank(value: str, field_name: str) -> str:
    """Strip ``value`` and raise :class:`MaterialValidationError` if empty."""
    stripped = value.strip()
    if not stripped:
        raise MaterialValidationError(  # noqa: TRY003 — operator-facing diagnostic
            f"{field_name} es obligatorio y no puede estar vacio"
        )
    return stripped


def create_material(
    materiales_port: MaterialesPort,
    *,
    material: str,
    tamano: str,
    color: str,
    observaciones: str | None = None,
) -> Material:
    """Insert a new material and return the persisted row.

    Strips the three required text fields before delegating to the
    port. ``observaciones`` passes through unchanged (None or
    blank-string — both are valid legacy values).

    The adapter raises :class:`MaterialConflictError` when the
    natural-key UNIQUE constraint trips; the application layer does
    NOT translate that — the route layer maps it to HTTP 409 (the
    legacy route handler at ``app/modules/materiales/routes.py``
    already does this translation).
    """
    clean_material = _require_non_blank(material, "material")
    clean_tamano = _require_non_blank(tamano, "tamano")
    clean_color = _require_non_blank(color, "color")
    clean_observaciones = (
        observaciones.strip() if isinstance(observaciones, str) else observaciones
    )
    return materiales_port.create_material(
        {
            "material": clean_material,
            "tamano": clean_tamano,
            "color": clean_color,
            "observaciones": clean_observaciones,
        }
    )


__all__ = ["MaterialValidationError", "create_material"]
