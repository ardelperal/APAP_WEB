"""Contract tests for domain_salud module (HEALTH-01)."""

from __future__ import annotations

from pydantic import BaseModel

from app.core.domain_salud import ACTUACION_SANITARIA_CREATE_TABLE_SQL


def test_actuacion_sanitaria_sql() -> None:
    assert ACTUACION_SANITARIA_CREATE_TABLE_SQL is not None
    assert "CREATE TABLE IF NOT EXISTS actuacion_sanitaria" in (
        ACTUACION_SANITARIA_CREATE_TABLE_SQL
    )


def test_actuacion_sanitaria_fk_to_animales() -> None:
    assert "REFERENCES animales(id)" in ACTUACION_SANITARIA_CREATE_TABLE_SQL


def test_actuacion_sanitaria_required_columns() -> None:
    assert "animal_id UUID NOT NULL" in ACTUACION_SANITARIA_CREATE_TABLE_SQL
    assert "fecha DATE NOT NULL" in ACTUACION_SANITARIA_CREATE_TABLE_SQL


def test_actuacion_sanitaria_has_pydantic_model() -> None:
    from app.core.domain_salud import ActuacionSanitaria

    assert issubclass(ActuacionSanitaria, BaseModel)
