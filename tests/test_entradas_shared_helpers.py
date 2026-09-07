"""Contracts for helpers intentionally shared inside the entradas package."""

from app.core.data_access import BackendError
from app.modules.entradas.service import is_duplicate_error, row_to_entrada


def test_shared_row_mapper_preserves_entrada_contract() -> None:
    entrada = row_to_entrada(
        {
            "id": "entrada-1",
            "animal_id": "animal-1",
            "fecha_entrada": "2026-07-20",
            "activo": True,
        }
    )

    assert entrada.id == "entrada-1"
    assert entrada.animal_id == "animal-1"
    assert entrada.fecha_entrada == "2026-07-20"


def test_shared_duplicate_classifier_preserves_conflict_contract() -> None:
    duplicate = BackendError(409, {"message": "entradas_natural_key duplicate"})
    unrelated = BackendError(500, {"message": "unique"})

    assert is_duplicate_error(duplicate) is True
    assert is_duplicate_error(unrelated) is False
