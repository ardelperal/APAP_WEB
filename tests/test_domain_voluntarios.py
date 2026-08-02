"""Contract tests for domain_voluntarios module.

Verifies the public API: SQL constants for voluntarios and roles_voluntario.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.core.domain_voluntarios import (
    ROLES_VOLUNTARIO_CREATE_TABLE_SQL,
    VOLUNTARIOS_CREATE_TABLE_SQL,
)


def test_voluntarios_exports_sql() -> None:
    assert VOLUNTARIOS_CREATE_TABLE_SQL is not None
    assert "CREATE TABLE IF NOT EXISTS voluntarios" in VOLUNTARIOS_CREATE_TABLE_SQL


def test_voluntarios_sql_has_lowercase_columns() -> None:
    """TbVoluntariosParaAutorrellenables (lowercase schema): voluntario, tel1, tel2, email."""
    required = {"voluntario", "tel1", "tel2", "email", "fecha_alta", "activo"}
    for col in required:
        assert col in VOLUNTARIOS_CREATE_TABLE_SQL, f"Missing: {col}"


def test_voluntarios_email_and_dni_unique() -> None:
    assert "email TEXT UNIQUE" in VOLUNTARIOS_CREATE_TABLE_SQL
    assert "dni TEXT UNIQUE" in VOLUNTARIOS_CREATE_TABLE_SQL


def test_roles_voluntario_exports_sql() -> None:
    assert ROLES_VOLUNTARIO_CREATE_TABLE_SQL is not None
    assert "CREATE TABLE IF NOT EXISTS roles_voluntario" in ROLES_VOLUNTARIO_CREATE_TABLE_SQL


def test_roles_voluntario_fk_to_voluntarios() -> None:
    assert "REFERENCES voluntarios(id)" in ROLES_VOLUNTARIO_CREATE_TABLE_SQL


def test_roles_voluntario_tipo_rol_domain() -> None:
    assert "CHECK (tipo_rol IN ('intake', 'seguimiento', 'acogida', 'salud'))" in (
        ROLES_VOLUNTARIO_CREATE_TABLE_SQL
    )


def test_roles_voluntario_unique_constraint() -> None:
    assert "UNIQUE (voluntario_id, tipo_rol)" in ROLES_VOLUNTARIO_CREATE_TABLE_SQL


def test_voluntarios_has_pydantic_model() -> None:
    from app.core.domain_voluntarios import Voluntario

    assert issubclass(Voluntario, BaseModel)


def test_voluntario_model_has_required_fields() -> None:
    from app.core.domain_voluntarios import Voluntario

    model = Voluntario.model_fields
    required_fields = {"id", "voluntario", "email", "dni"}
    missing = required_fields - set(model)
    assert not missing, f"Voluntario model missing fields: {missing}"
