"""Contract tests for domain_cesiones module."""

from __future__ import annotations

from pydantic import BaseModel

from app.core.domain_cesiones import CESIONES_PROPIETARIO_CREATE_TABLE_SQL


def test_cesiones_sql() -> None:
    assert CESIONES_PROPIETARIO_CREATE_TABLE_SQL is not None
    assert "CREATE TABLE IF NOT EXISTS cesiones_propietario" in CESIONES_PROPIETARIO_CREATE_TABLE_SQL


def test_cesiones_fk_to_entradas() -> None:
    assert "REFERENCES entradas(id)" in CESIONES_PROPIETARIO_CREATE_TABLE_SQL


def test_cesiones_entrada_id_unique() -> None:
    assert "entrada_id UUID NOT NULL UNIQUE" in CESIONES_PROPIETARIO_CREATE_TABLE_SQL


def test_cesiones_required_fields_not_null() -> None:
    assert "numero_contrato TEXT NOT NULL" in CESIONES_PROPIETARIO_CREATE_TABLE_SQL
    assert "nombre_representante TEXT NOT NULL" in CESIONES_PROPIETARIO_CREATE_TABLE_SQL


def test_cesion_has_pydantic_model() -> None:
    from app.core.domain_cesiones import CesionPropietario

    assert issubclass(CesionPropietario, BaseModel)
