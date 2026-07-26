"""Contract tests for domain_foster module.

Exports: Acogida, ACOGIDAS, ACOGIDAS_ADD_CASA_FK,
FOSTER_CAPACITY_OVERRIDES, FOSTER_CAPACITY_OVERRIDES_ADD_ESTANCIA_FK.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.core.domain_foster import (
    ACOGIDAS_ADD_CASA_FK_SQL,
    ACOGIDAS_CREATE_TABLE_SQL,
    FOSTER_CAPACITY_OVERRIDES_ADD_ESTANCIA_FK_SQL,
    FOSTER_CAPACITY_OVERRIDES_CREATE_TABLE_SQL,
)


def test_acogidas_sql() -> None:
    assert ACOGIDAS_CREATE_TABLE_SQL is not None
    assert "CREATE TABLE IF NOT EXISTS acogidas" in ACOGIDAS_CREATE_TABLE_SQL


def test_acogidas_fk_to_animales() -> None:
    assert "REFERENCES animales(id)" in ACOGIDAS_CREATE_TABLE_SQL


def test_acogidas_add_casa_fk_sql() -> None:
    assert "ALTER TABLE acogidas" in ACOGIDAS_ADD_CASA_FK_SQL
    assert "ADD COLUMN IF NOT EXISTS" in ACOGIDAS_ADD_CASA_FK_SQL
    assert "casa_acogida_id UUID REFERENCES casas_acogida(id)" in ACOGIDAS_ADD_CASA_FK_SQL


def test_foster_capacity_overrides_sql() -> None:
    assert FOSTER_CAPACITY_OVERRIDES_CREATE_TABLE_SQL is not None
    assert "CREATE TABLE IF NOT EXISTS foster_capacity_overrides" in (
        FOSTER_CAPACITY_OVERRIDES_CREATE_TABLE_SQL
    )


def test_foster_capacity_overrides_motivo_not_null() -> None:
    assert "motivo TEXT NOT NULL" in FOSTER_CAPACITY_OVERRIDES_CREATE_TABLE_SQL


def test_foster_capacity_overrides_add_estancia_fk() -> None:
    assert "ALTER TABLE foster_capacity_overrides" in FOSTER_CAPACITY_OVERRIDES_ADD_ESTANCIA_FK_SQL
    assert "ADD COLUMN IF NOT EXISTS" in FOSTER_CAPACITY_OVERRIDES_ADD_ESTANCIA_FK_SQL
    assert "estancia_id UUID NULL REFERENCES acogidas(id)" in FOSTER_CAPACITY_OVERRIDES_ADD_ESTANCIA_FK_SQL


def test_acogida_has_pydantic_model() -> None:
    from app.core.domain_foster import Acogida

    assert issubclass(Acogida, BaseModel)
