from __future__ import annotations

"""Domain schema bootstrap: backward-compat shim.

This module is the single entry point for domain schema creation.
It re-exports SQL constants from 12 cohesive sub-modules so that
``tests/test_domain.py``, ``tests/integration/conftest.py``, and
other consumers can continue to import from ``app.core.domain`` and
``app.core.domain_<x>`` without modification.

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
    domain_terapias      — terapias, recomendaciones tables

Source of truth for the SQL that creates the domain tables in the
LocalBackend backend. The :func:`ensure_domain_schema` function is the
legacy ``client``-typed entry point that ``app.main`` calls on
startup; the canonical "via port" use case lives at
:func:`app.core.application.schema_bootstrap.ensure_domain_schema.ensure_domain_schema`
and is what future slices will wire into ``app/main.py``.
"""


from app.core.adapters.stubs.schema_bootstrap_stub import (  # noqa: E402
    StubSchemaBootstrapPort,
)
from app.core.data_access import SqlExecutor  # noqa: E402
from app.core.domain_adopciones import (  # noqa: E402
    ADOPCIONES_CREATE_TABLE_SQL,
)
from app.core.domain_animales import (  # noqa: E402
    ANIMALS_CREATE_TABLE_SQL,  # noqa: I001
)
from app.core.domain_casas_acogida import (  # noqa: E402
    CASAS_ACOGIDA_CREATE_TABLE_SQL,
)
from app.core.domain_cesiones import (  # noqa: E402
    CESIONES_PROPIETARIO_CREATE_TABLE_SQL,
)
from app.core.domain_contracts import (  # noqa: E402
    CONTRATOS_CREATE_TABLE_SQL,
)
from app.core.domain_entradas import (  # noqa: E402
    ENTRADAS_BATCH_STAGING_CREATE_TABLE_SQL,
    ENTRADAS_CREATE_TABLE_SQL,
)
from app.core.domain_foster import (  # noqa: F401  # noqa: E402
    ACOGIDAS_ADD_CASA_FK_SQL,
    ACOGIDAS_CREATE_TABLE_SQL,
    FOSTER_CAPACITY_OVERRIDES_ADD_ESTANCIA_FK_SQL,
    FOSTER_CAPACITY_OVERRIDES_CREATE_TABLE_SQL,
)
from app.core.domain_lifecycle import (  # noqa: F401  # noqa: E402
    ANIMAL_CURRENT_STATE_CREATE_TABLE_SQL,
    ANIMAL_CURRENT_STATE_STATE_INDEX_SQL,
    ANIMAL_LIFECYCLE_EVENTS_ANIMAL_TIMESTAMP_INDEX_SQL,
    ANIMAL_LIFECYCLE_EVENTS_APPEND_ONLY_FUNCTION_SQL,
    ANIMAL_LIFECYCLE_EVENTS_APPEND_ONLY_TRIGGER_SQL,
    ANIMAL_LIFECYCLE_EVENTS_CAUSED_BY_INDEX_SQL,
    ANIMAL_LIFECYCLE_EVENTS_CREATE_TABLE_SQL,
    ANIMAL_LIFECYCLE_EVENTS_DROP_APPEND_ONLY_TRIGGER_SQL,
)
from app.core.domain_materiales import (  # noqa: F401  # noqa: E402
    ESTANCIA_MATERIALES_ACTIVE_UNIQUE_INDEX_SQL,
    ESTANCIA_MATERIALES_CREATE_TABLE_SQL,
    MATERIALES_CREATE_TABLE_SQL,
)
from app.core.domain_salud import (  # noqa: E402
    ACTUACION_SANITARIA_CREATE_TABLE_SQL,  # noqa: F401
)
from app.core.domain_terapias import (  # noqa: F401  # noqa: E402
    RECOMENDACIONES_CREATE_TABLE_SQL,
    TERAPIAS_CREATE_TABLE_SQL,
)
from app.core.domain_voluntarios import (  # noqa: F401  # noqa: E402
    ROLES_VOLUNTARIO_CREATE_TABLE_SQL,
    VOLUNTARIOS_CREATE_TABLE_SQL,
)
from app.core.local_backend.db import LocalPostgresExecutor

__all__ = [
    "ACOGIDAS_ADD_CASA_FK_SQL",
    "ACOGIDAS_CREATE_TABLE_SQL",
    "ACTUACION_SANITARIA_CREATE_TABLE_SQL",
    "ADOPCIONES_CREATE_TABLE_SQL",
    "ANIMAL_CURRENT_STATE_CREATE_TABLE_SQL",
    "ANIMAL_CURRENT_STATE_STATE_INDEX_SQL",
    "ANIMAL_LIFECYCLE_EVENTS_ANIMAL_TIMESTAMP_INDEX_SQL",
    "ANIMAL_LIFECYCLE_EVENTS_APPEND_ONLY_FUNCTION_SQL",
    "ANIMAL_LIFECYCLE_EVENTS_APPEND_ONLY_TRIGGER_SQL",
    "ANIMAL_LIFECYCLE_EVENTS_CAUSED_BY_INDEX_SQL",
    "ANIMAL_LIFECYCLE_EVENTS_CREATE_TABLE_SQL",
    "ANIMAL_LIFECYCLE_EVENTS_DROP_APPEND_ONLY_TRIGGER_SQL",
    "ANIMALS_CREATE_TABLE_SQL",
    "CASAS_ACOGIDA_CREATE_TABLE_SQL",
    "CESIONES_PROPIETARIO_CREATE_TABLE_SQL",
    "CONTRATOS_CREATE_TABLE_SQL",
    "ENTRADAS_BATCH_STAGING_CREATE_TABLE_SQL",
    "ENTRADAS_CREATE_TABLE_SQL",
    "ESTANCIA_MATERIALES_ACTIVE_UNIQUE_INDEX_SQL",
    "ESTANCIA_MATERIALES_CREATE_TABLE_SQL",
    "FOSTER_CAPACITY_OVERRIDES_ADD_ESTANCIA_FK_SQL",
    "FOSTER_CAPACITY_OVERRIDES_CREATE_TABLE_SQL",
    "MATERIALES_CREATE_TABLE_SQL",
    "RECOMENDACIONES_CREATE_TABLE_SQL",
    "LocalPostgresExecutor",
    "ROLES_VOLUNTARIO_CREATE_TABLE_SQL",
    "TERAPIAS_CREATE_TABLE_SQL",
    "VOLUNTARIOS_CREATE_TABLE_SQL",
    "ensure_domain_schema",
]


def ensure_domain_schema(client: SqlExecutor) -> None:
    """Create the domain tables (idempotent) in dependency order.

    Backward-compat shim: builds a :class:`StubSchemaBootstrapPort`
    and delegates to :meth:`StubSchemaBootstrapPort.ensure_domain_schema`.

    The LocalBackend adapter was deleted in issue #666; until a real
    :class:`~app.core.local_backend.db.LocalPostgresExecutor`-backed
    adapter lands (tracked as the follow-up), the stub raises
    :class:`NotImplementedError` on every method call. The ``client``
    parameter is preserved for signature compatibility.

    The dependency order is preserved exactly so lifespan replays and
    ``tests/test_domain.py`` assertions (which pin the SQL emission
    sequence) keep working without changes.

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
    StubSchemaBootstrapPort().ensure_domain_schema()
