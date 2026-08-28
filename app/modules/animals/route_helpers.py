"""Pure and transport-translation helpers shared by animal routes."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from app.modules.animals.application.get_animal_by_id import get_animal_by_id
from app.modules.animals.domain.animal import Animal, Especie, Sexo
from app.modules.animals.domain.change_chip_result import ChangeChipResult
from app.modules.animals.ports.animals_port import AnimalsPort

_ANIMAL_CORE_FORM_FIELDS = {
    "NCHIP",
    "NombreAnimal",
    "Especie",
    "Sexo",
    "FNacimiento",
}


def _optional_animal_fields(form_data: dict[str, Any]) -> dict[str, Any]:
    """Return only the writable fields outside the core update arguments."""
    optional_fields = dict(form_data)
    for key in _ANIMAL_CORE_FORM_FIELDS:
        optional_fields.pop(key, None)
    return optional_fields


def _optional_domain_value(
    form_data: dict[str, Any],
    key: str,
    enum_type: type[Especie] | type[Sexo],
) -> Especie | Sexo | None:
    """Convert one optional form value to its domain enum."""
    value = form_data.get(key)
    return enum_type(value) if value is not None else None


def _animal_update_kwargs(form_data: dict[str, Any]) -> dict[str, Any]:
    """Build the typed keyword arguments accepted by ``AnimalsPort``."""
    return {
        "nombre": form_data.get("NombreAnimal"),
        "especie": _optional_domain_value(form_data, "Especie", Especie),
        "sexo": _optional_domain_value(form_data, "Sexo", Sexo),
        "fnacimiento": form_data.get("FNacimiento"),
        **_optional_animal_fields(form_data),
    }


def _chip_change_user_id(user: object) -> str:
    """Read the operator id from the authorized-user transport shape."""
    return str(user.get("user_id", "")) if isinstance(user, dict) else ""


def _require_animal(port: AnimalsPort, animal_id: str) -> Animal:
    """Return the requested animal or translate absence to HTTP 404."""
    animal = get_animal_by_id(port, animal_id)
    if animal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return animal


def _execute_chip_change(
    port: AnimalsPort,
    animal_id: str,
    new_chip: str,
    reason: str,
    user: object,
) -> ChangeChipResult:
    """Load the current chip and delegate the complete cascade command."""
    animal = _require_animal(port, animal_id)
    return port.change_animal_chip(
        animal_id=animal_id,
        old_chip=animal.NCHIP,
        new_chip=new_chip,
        reason=reason,
        operador_user_id=_chip_change_user_id(user),
    )


def _chip_change_response(result: ChangeChipResult) -> dict[str, Any]:
    """Translate a domain cascade result to its HTTP response contract."""
    if not result.success:
        raise HTTPException(
            status_code=_chip_change_error_status(result.error),
            detail=result.error,
        )
    return {
        "success": True,
        "old_chip": result.old_chip,
        "new_chip": result.new_chip,
        "updated_tables": result.updated_tables,
    }


def _chip_change_error_status(error: str | None) -> int:
    """Return conflict for duplicate chips and validation status otherwise."""
    message = str(error)
    conflict = any(
        ("ya esta asignado" in message, "ya está asignado" in message)
    )
    if conflict:
        return status.HTTP_409_CONFLICT
    return status.HTTP_422_UNPROCESSABLE_CONTENT
