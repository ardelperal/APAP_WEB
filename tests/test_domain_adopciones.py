"""Contract tests for domain_adopciones module."""

from __future__ import annotations

from pydantic import BaseModel

from app.core.domain_adopciones import ADOPCIONES_CREATE_TABLE_SQL


def test_adopciones_exports_sql() -> None:
    assert ADOPCIONES_CREATE_TABLE_SQL is not None
    assert "CREATE TABLE IF NOT EXISTS adopciones" in ADOPCIONES_CREATE_TABLE_SQL


def test_adopciones_fk_to_animales() -> None:
    assert "REFERENCES animales(id)" in ADOPCIONES_CREATE_TABLE_SQL


def test_adopciones_nombre_adoptante_not_null() -> None:
    assert "nombre_adoptante TEXT NOT NULL" in ADOPCIONES_CREATE_TABLE_SQL


def test_adopciones_natural_key() -> None:
    assert "CONSTRAINT adopciones_natural_key UNIQUE (animal_id, fecha_adopcion)" in (
        ADOPCIONES_CREATE_TABLE_SQL
    )


def test_adopcion_has_pydantic_model() -> None:
    from app.core.domain_adopciones import Adopcion

    assert issubclass(Adopcion, BaseModel)


def test_adopcion_model_fields() -> None:
    from app.core.domain_adopciones import Adopcion

    model = Adopcion.model_fields
    required_fields = {"id", "animal_id", "fecha_adopcion", "nombre_adoptante"}
    missing = required_fields - set(model)
    assert not missing, f"Adopcion model missing fields: {missing}"
