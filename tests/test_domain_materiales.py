"""Contract tests for domain_materiales module (FOSTER-04)."""

from __future__ import annotations

from pydantic import BaseModel

from app.core.domain_materiales import (
    ESTANCIA_MATERIALES_ACTIVE_UNIQUE_INDEX_SQL,
    ESTANCIA_MATERIALES_CREATE_TABLE_SQL,
    MATERIALES_CREATE_TABLE_SQL,
)


def test_materiales_sql() -> None:
    assert MATERIALES_CREATE_TABLE_SQL is not None
    assert "CREATE TABLE IF NOT EXISTS materiales" in MATERIALES_CREATE_TABLE_SQL


def test_materiales_natural_key_unique() -> None:
    assert "UNIQUE (material, tamano, color)" in MATERIALES_CREATE_TABLE_SQL


def test_estancia_materiales_sql() -> None:
    assert ESTANCIA_MATERIALES_CREATE_TABLE_SQL is not None
    assert "CREATE TABLE IF NOT EXISTS estancia_materiales" in (
        ESTANCIA_MATERIALES_CREATE_TABLE_SQL
    )


def test_estancia_materiales_fks() -> None:
    assert "REFERENCES acogidas(id)" in ESTANCIA_MATERIALES_CREATE_TABLE_SQL
    assert "REFERENCES materiales(id)" in ESTANCIA_MATERIALES_CREATE_TABLE_SQL


def test_estancia_materiales_active_unique_index() -> None:
    assert "CREATE UNIQUE INDEX IF NOT EXISTS estancia_materiales_active_unique" in (
        ESTANCIA_MATERIALES_ACTIVE_UNIQUE_INDEX_SQL
    )
    assert "WHERE activo = true" in ESTANCIA_MATERIALES_ACTIVE_UNIQUE_INDEX_SQL


def test_material_has_pydantic_model() -> None:
    from app.core.domain_materiales import Material

    assert issubclass(Material, BaseModel)


def test_estancia_material_has_pydantic_model() -> None:
    from app.core.domain_materiales import EstanciaMaterial

    assert issubclass(EstanciaMaterial, BaseModel)
