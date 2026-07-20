"""Public package contract for cross-domain animal lookups."""

from app.modules.animals import get_animal_by_id
from app.modules.animals.service import get_animal_by_id as service_get_animal_by_id


def test_animals_package_exports_get_animal_by_id() -> None:
    assert get_animal_by_id is service_get_animal_by_id
