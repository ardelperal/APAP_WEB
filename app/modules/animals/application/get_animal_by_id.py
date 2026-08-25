"""Use case: look up an animal by its database primary key."""
from __future__ import annotations

from app.modules.animals.domain.animal import Animal
from app.modules.animals.ports.animals_port import AnimalsPort


def get_animal_by_id(port: AnimalsPort, animal_id: str) -> Animal | None:
    """Validate and delegate one database-primary-key lookup."""
    if not animal_id or not animal_id.strip():
        raise ValueError("animal_id is required")
    return port.get_animal_by_id(animal_id.strip())


__all__ = ["get_animal_by_id"]
