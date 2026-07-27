"""Domain schema bootstrap: re-export shim for backward compatibility.

This module is the single entry point for domain schema creation.
It re-exports SQL constants from 9 cohesive sub-modules so that
``tests/test_domain.py`` and other consumers can continue to import
from ``app.core.domain`` without modification.

The sub-modules are:
    domain_animales       — animales table
    domain_voluntarios   — voluntarios, roles_voluntario tables
    domain_entradas      — entradas, entradas_batch_staging tables
    domain_foster        — acogidas table + foster_capacity_overrides
    domain_casas_acogida — casas_acogida table
    domain_adopciones    — adopciones table
    domain_lifecycle     — animal_lifecycle_events, animal_current_state
    domain_cesiones      — cesiones_propietario table
    domain_contracts     — contratos table
    domain_salud         — actuacion_sanitaria table
    domain_materiales    — materiales, estancia_materiales tables

Source of truth for the SQL that creates the domain tables in the
InsForge backend. The ``ensure_domain_schema`` function is the single
entry point that ``app.main`` calls on startup.
"""

from __future__ import annotations

from app.core.domain_adopciones import ADOPCIONES_CREATE_TABLE_SQL
from app.core.domain_animales import ANIMALS_CREATE_TABLE_SQL  # noqa: I001
from app.core.domain_casas_acogida import CASAS_ACOGIDA_CREATE_TABLE_SQL
from app.core.domain_cesiones import CESIONES_PROPIETARIO_CREATE_TABLE_SQL
from app.core.domain_contracts import CONTRATOS_CREATE_TABLE_SQL
from app.core.domain_entradas import (
    ENTRADAS_BATCH_STAGING_CREATE_TABLE_SQL,
    ENTRADAS_CREATE_TABLE_SQL,
)
from app.core.domain_foster import (
    ACOGIDAS_ADD_CASA_FK_SQL,
    ACOGIDAS_CREATE_TABLE_SQL,
    FOSTER_CAPACITY_OVERRIDES_ADD_ESTANCIA_FK_SQL,
    FOSTER_CAPACITY_OVERRIDES_CREATE_TABLE_SQL,
)
from app.core.domain_lifecycle import (
    ANIMAL_CURRENT_STATE_CREATE_TABLE_SQL,
    ANIMAL_CURRENT_STATE_STATE_INDEX_SQL,
    ANIMAL_LIFECYCLE_EVENTS_ANIMAL_TIMESTAMP_INDEX_SQL,
    ANIMAL_LIFECYCLE_EVENTS_APPEND_ONLY_FUNCTION_SQL,
    ANIMAL_LIFECYCLE_EVENTS_APPEND_ONLY_TRIGGER_SQL,
    ANIMAL_LIFECYCLE_EVENTS_CAUSED_BY_INDEX_SQL,
    ANIMAL_LIFECYCLE_EVENTS_CREATE_TABLE_SQL,
    ANIMAL_LIFECYCLE_EVENTS_DROP_APPEND_ONLY_TRIGGER_SQL,
)
from app.core.domain_materiales import (
    ESTANCIA_MATERIALES_ACTIVE_UNIQUE_INDEX_SQL,
    ESTANCIA_MATERIALES_CREATE_TABLE_SQL,
    MATERIALES_CREATE_TABLE_SQL,
)
from app.core.domain_salud import ACTUACION_SANITARIA_CREATE_TABLE_SQL
from app.core.domain_voluntarios import (
    ROLES_VOLUNTARIO_CREATE_TABLE_SQL,
    VOLUNTARIOS_CREATE_TABLE_SQL,
)
from app.core.insforge import InsForgeClient
from app.core.schema_bootstrap import SqlStatement, run_idempotent_sql


def ensure_domain_schema(client: InsForgeClient) -> None:
    """Create the domain tables (idempotent) in dependency order.

    Order respects FK dependencies:

    1. ``animales`` and ``voluntarios`` are independent roots.
    2. ``roles_voluntario`` depends on ``voluntarios``.
    3. ``entradas`` depends on ``animales`` and ``voluntarios``.
    4. ``acogidas`` depends on ``animales``, ``voluntarios`` and ``entradas``.
    5. ``adopciones`` depends on ``animales``, ``voluntarios`` and ``entradas``.
    6. ``animal_lifecycle_events`` depends on ``animales`` (event log).
    7. ``animal_current_state`` depends on ``animales`` and the event log.
    8. ``cesiones_propietario`` depends on ``entradas`` (FK UNIQUE).
    9. ``contratos`` FKs to several domain tables plus ``catalogos_tipos_contrato``.
    10. ``actuacion_sanitaria`` FKs to ``animales``, ``catalogos_pruebas``,
        ``voluntarios``.
    11. ``materiales`` and ``estancia_materiales`` at the end so their
        junction FKs to ``acogidas`` and ``materiales`` resolve.
    """
    statements = (
        SqlStatement(ANIMALS_CREATE_TABLE_SQL),
        SqlStatement(VOLUNTARIOS_CREATE_TABLE_SQL),
        SqlStatement(ROLES_VOLUNTARIO_CREATE_TABLE_SQL),
        SqlStatement(ENTRADAS_CREATE_TABLE_SQL),
        SqlStatement(ENTRADAS_BATCH_STAGING_CREATE_TABLE_SQL),
        SqlStatement(CASAS_ACOGIDA_CREATE_TABLE_SQL),
        SqlStatement(ACOGIDAS_CREATE_TABLE_SQL),
        SqlStatement(ACOGIDAS_ADD_CASA_FK_SQL),
        SqlStatement(FOSTER_CAPACITY_OVERRIDES_CREATE_TABLE_SQL),
        SqlStatement(FOSTER_CAPACITY_OVERRIDES_ADD_ESTANCIA_FK_SQL),
        SqlStatement(ADOPCIONES_CREATE_TABLE_SQL),
        SqlStatement(ANIMAL_LIFECYCLE_EVENTS_CREATE_TABLE_SQL),
        SqlStatement(ANIMAL_LIFECYCLE_EVENTS_ANIMAL_TIMESTAMP_INDEX_SQL),
        SqlStatement(ANIMAL_LIFECYCLE_EVENTS_CAUSED_BY_INDEX_SQL),
        SqlStatement(ANIMAL_CURRENT_STATE_CREATE_TABLE_SQL),
        SqlStatement(ANIMAL_CURRENT_STATE_STATE_INDEX_SQL),
        SqlStatement(CESIONES_PROPIETARIO_CREATE_TABLE_SQL),
        SqlStatement(CONTRATOS_CREATE_TABLE_SQL),
        SqlStatement(ACTUACION_SANITARIA_CREATE_TABLE_SQL),
        SqlStatement(MATERIALES_CREATE_TABLE_SQL),
        SqlStatement(ESTANCIA_MATERIALES_CREATE_TABLE_SQL),
        SqlStatement(ESTANCIA_MATERIALES_ACTIVE_UNIQUE_INDEX_SQL),
        # Append-only enforcement on the lifecycle-event log (issue
        # #32, LIFECYCLE-02). The trigger function is created first so
        # the ``CREATE TRIGGER`` that references it does not race with
        # the function existence; ``DROP TRIGGER IF EXISTS`` then
        # ``CREATE TRIGGER`` makes the installation replay-safe
        # (lifespan runs every cold start).
        SqlStatement(ANIMAL_LIFECYCLE_EVENTS_APPEND_ONLY_FUNCTION_SQL),
        SqlStatement(ANIMAL_LIFECYCLE_EVENTS_DROP_APPEND_ONLY_TRIGGER_SQL),
        SqlStatement(ANIMAL_LIFECYCLE_EVENTS_APPEND_ONLY_TRIGGER_SQL),
    )
    run_idempotent_sql(client, statements, step_name="domain")
