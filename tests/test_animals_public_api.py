"""Public package contract for cross-domain animal lookups."""

from app.modules.animals import get_animal_by_id
from app.modules.animals.application.get_animal_by_id import (
    get_animal_by_id as application_get_animal_by_id,
)


def test_animals_package_exports_get_animal_by_id() -> None:
    assert get_animal_by_id is application_get_animal_by_id, (
        "the animals package must expose the hexagonal primary-key use case"
    )
