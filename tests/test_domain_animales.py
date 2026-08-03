"""Contract tests for domain_animales module.

Verifies the public API: SQL constant + Pydantic model.
Phase 2 RED — these FAIL until the module is properly populated.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.core.domain_animales import ANIMALS_CREATE_TABLE_SQL


def test_animales_module_exports_animal_sql() -> None:
    """ANIMALS_CREATE_TABLE_SQL must be exported from domain_animales."""
    assert ANIMALS_CREATE_TABLE_SQL is not None
    assert "CREATE TABLE IF NOT EXISTS animales" in ANIMALS_CREATE_TABLE_SQL


def test_animales_sql_has_all_required_columns() -> None:
    """The animales CREATE TABLE must include every required column."""
    required = {
        "id", "nchip", "nombreanimal", "especie", "sexo",
        "fnacimiento", "fecha_alta", "updated_at", "activo",
    }
    for col in required:
        assert col in ANIMALS_CREATE_TABLE_SQL, f"Missing column: {col}"


def test_animales_sql_enforces_especie_domain() -> None:
    """especie must be CHECK-constrained to CANINA or FELINA."""
    assert "CHECK (especie IN ('CANINA', 'FELINA'))" in ANIMALS_CREATE_TABLE_SQL


def test_animales_sql_enforces_sexo_domain() -> None:
    """sexo must be CHECK-constrained to M or H."""
    assert "CHECK (sexo IN ('M', 'H'))" in ANIMALS_CREATE_TABLE_SQL


def test_animales_nchip_is_unique() -> None:
    """nchip must be UNIQUE NOT NULL as the legacy natural key."""
    assert "nchip TEXT UNIQUE NOT NULL" in ANIMALS_CREATE_TABLE_SQL


def test_animales_sql_excludes_legacy_situacion() -> None:
    """situacion must NOT be stored — it is derived from the event log."""
    assert "situacion" not in ANIMALS_CREATE_TABLE_SQL.lower(), (
        "situacion must be derived from the event log, not stored on animales"
    )


def test_animales_has_pydantic_base_model() -> None:
    """domain_animales must export an Animal Pydantic model."""
    from app.core.domain_animales import Animal

    assert issubclass(Animal, BaseModel)


def test_animal_model_has_required_fields() -> None:
    """Animal model must have the core fields from the lowercase schema."""
    from app.core.domain_animales import Animal

    model = Animal.model_fields
    required_fields = {"id", "nchip", "nombreanimal", "especie", "sexo", "fnacimiento"}
    missing = required_fields - set(model)
    assert not missing, f"Animal model missing fields: {missing}"
