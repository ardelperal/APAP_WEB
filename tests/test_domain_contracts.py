"""Contract tests for domain_contracts module."""

from __future__ import annotations

from pydantic import BaseModel

from app.core.domain_contracts import CONTRATOS_CREATE_TABLE_SQL


def test_contratos_sql() -> None:
    assert CONTRATOS_CREATE_TABLE_SQL is not None
    assert "CREATE TABLE IF NOT EXISTS contratos" in CONTRATOS_CREATE_TABLE_SQL


def test_contratos_fk_to_all_lifecycle_entities() -> None:
    assert "REFERENCES entradas(id)" in CONTRATOS_CREATE_TABLE_SQL
    assert "REFERENCES acogidas(id)" in CONTRATOS_CREATE_TABLE_SQL
    assert "REFERENCES adopciones(id)" in CONTRATOS_CREATE_TABLE_SQL
    assert "REFERENCES cesiones_propietario(id)" in CONTRATOS_CREATE_TABLE_SQL


def test_contratos_xor_check_constraint() -> None:
    assert "CONSTRAINT contratos_exactly_one_entity" in CONTRATOS_CREATE_TABLE_SQL
    assert "CHECK" in CONTRATOS_CREATE_TABLE_SQL


def test_contratos_required_fields_not_null() -> None:
    assert "tipo_contrato_id UUID NOT NULL" in CONTRATOS_CREATE_TABLE_SQL
    assert "numero_contrato TEXT NOT NULL" in CONTRATOS_CREATE_TABLE_SQL
    assert "fecha DATE NOT NULL" in CONTRATOS_CREATE_TABLE_SQL


def test_contrato_has_pydantic_model() -> None:
    from app.core.domain_contracts import Contrato

    assert issubclass(Contrato, BaseModel)
