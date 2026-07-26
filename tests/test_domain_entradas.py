"""Contract tests for domain_entradas module."""

from __future__ import annotations

from pydantic import BaseModel

from app.core.domain_entradas import (
    ENTRADAS_BATCH_STAGING_CREATE_TABLE_SQL,
    ENTRADAS_CREATE_TABLE_SQL,
)


def test_entradas_exports_sql() -> None:
    assert ENTRADAS_CREATE_TABLE_SQL is not None
    assert "CREATE TABLE IF NOT EXISTS entradas" in ENTRADAS_CREATE_TABLE_SQL


def test_entradas_sql_fk_to_animales() -> None:
    assert "REFERENCES animales(id)" in ENTRADAS_CREATE_TABLE_SQL


def test_entradas_sql_natural_key() -> None:
    assert "CONSTRAINT entradas_natural_key UNIQUE (animal_id, fecha_entrada)" in (
        ENTRADAS_CREATE_TABLE_SQL
    )


def test_entradas_batch_staging_exports_sql() -> None:
    assert ENTRADAS_BATCH_STAGING_CREATE_TABLE_SQL is not None
    assert "CREATE TABLE IF NOT EXISTS entradas_batch_staging" in (
        ENTRADAS_BATCH_STAGING_CREATE_TABLE_SQL
    )


def test_entradas_batch_staging_primary_key() -> None:
    assert "PRIMARY KEY (batch_id, sequence)" in ENTRADAS_BATCH_STAGING_CREATE_TABLE_SQL


def test_entradas_has_pydantic_model() -> None:
    from app.core.domain_entradas import Entrada

    assert issubclass(Entrada, BaseModel)


def test_entrada_model_has_required_fields() -> None:
    from app.core.domain_entradas import Entrada

    model = Entrada.model_fields
    required_fields = {"id", "animal_id", "fecha_entrada"}
    missing = required_fields - set(model)
    assert not missing, f"Entrada model missing fields: {missing}"
