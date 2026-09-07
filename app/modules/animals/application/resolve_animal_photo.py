"""Use case: resolve the animal's photo stream (issue #285).

Slice #420-7 ninth surface (joins get_animal_by_nchip #587,
list_animals #596, create_animal #597, update_animal #603,
delete_animal #604, record_lifecycle_event #609,
list_lifecycle_events #610 and change_animal_chip #612). The
single application-layer entry point for hexagonal photo
streaming. Delegates to
:class:`~app.modules.animals.ports.AnimalsPort` so the application
code stays transport-agnostic (AGENTS.md §31) — no FastAPI, no
LocalBackend storage client, no Jinja in this file.

The use case enforces the only pre-flight invariant the legacy
``photo_service.resolve_animal_photo`` did: ``animal_id`` is
mandatory and non-blank. The streaming semantics — placeholder
PNG when the animal has no photo and storage-error fallback — live
behind the port. HTTP cache policy remains a delivery-layer concern.
"""
from __future__ import annotations

from app.modules.animals.ports.animals_port import AnimalsPort
from app.modules.animals.ports.photo_asset import PhotoAsset


class PhotoResolutionValidationError(ValueError):
    """Raised when ``animal_id`` fails the domain-validation rules.

    Subclasses :class:`ValueError` so existing ``except ValueError``
    clauses in legacy callers keep catching it.
    """


def _require_animal_id(animal_id: str | None) -> str:
    if animal_id is None:
        raise PhotoResolutionValidationError(  # noqa: TRY003 — operator-facing diagnostic
            "animal_id es obligatorio"
        )
    stripped = animal_id.strip()
    if not stripped:
        raise PhotoResolutionValidationError(  # noqa: TRY003 — operator-facing diagnostic
            "animal_id es obligatorio y no puede estar vacio"
        )
    return stripped


def resolve_animal_photo(
    animals_port: AnimalsPort,
    animal_id: str,
) -> PhotoAsset | None:
    """Return the owned photo asset for ``animal_id`` or ``None``.

    ``None`` means the animal does not exist. Every returned asset owns
    its stream; the future delivery caller must close it deterministically.
    """
    clean_animal_id = _require_animal_id(animal_id)
    return animals_port.resolve_animal_photo(clean_animal_id)


__all__ = [
    "resolve_animal_photo",
    "PhotoResolutionValidationError",
]
