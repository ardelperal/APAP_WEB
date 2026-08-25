"""Use case: search animals with optional filters and pagination."""
from __future__ import annotations

from app.modules.animals.application.list_animals import MAX_PAGE_SIZE
from app.modules.animals.domain.animal import (
    AnimalSearchResult,
    Especie,
    Sexo,
)
from app.modules.animals.ports.animals_port import AnimalsPort

MAX_LIMIT: int = MAX_PAGE_SIZE


def _validate_optional_text(field_name: str, value: object) -> None:
    if value is not None and not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string or None")


def search_animals(  # noqa: PLR0913
    port: AnimalsPort,
    *,
    q: str | None = None,
    chip: str | None = None,
    especie: Especie | None = None,
    sexo: Sexo | None = None,
    estado: str | None = None,
    fecha_alta_since: str | None = None,
    fecha_alta_until: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> AnimalSearchResult:
    """Validate filters, clamp pagination, and delegate to ``AnimalsPort``."""
    for field_name, value in (
        ("q", q),
        ("chip", chip),
        ("fecha_alta_since", fecha_alta_since),
        ("fecha_alta_until", fecha_alta_until),
    ):
        _validate_optional_text(field_name, value)

    return port.search_animals(
        q=q,
        chip=chip,
        especie=especie,
        sexo=sexo,
        estado=estado,
        fecha_alta_since=fecha_alta_since,
        fecha_alta_until=fecha_alta_until,
        limit=max(0, min(int(limit), MAX_LIMIT)),
        offset=max(0, int(offset)),
    )


__all__ = ["MAX_LIMIT", "search_animals"]
