"""Contract tests for domain_casas_acogida module (FOSTER-01, issue #43)."""

from __future__ import annotations

from pydantic import BaseModel

from app.core.domain_casas_acogida import CASAS_ACOGIDA_CREATE_TABLE_SQL, CasaAcogida


def test_casas_acogida_sql() -> None:
    assert CASAS_ACOGIDA_CREATE_TABLE_SQL is not None
    assert "CREATE TABLE IF NOT EXISTS casas_acogida" in CASAS_ACOGIDA_CREATE_TABLE_SQL


def test_casas_acogida_has_capacidad() -> None:
    assert "capacidad INTEGER NOT NULL CHECK (capacidad > 0)" in CASAS_ACOGIDA_CREATE_TABLE_SQL


def test_casa_acogida_has_pydantic_model() -> None:
    assert issubclass(CasaAcogida, BaseModel)


def test_casa_acogida_model_fields() -> None:
    model = CasaAcogida.model_fields
    required_fields = {"id", "nombre", "apellidos", "capacidad", "telefono"}
    missing = required_fields - set(model)
    assert not missing, f"CasaAcogida model missing fields: {missing}"
