"""InsForge adapter implementing :class:`SchemaBootstrapPort`.

The adapter is the seam where the DDL statements and the ordered
SQL execution live. Tests swap the adapter for an in-memory fake by
implementing :class:`SchemaBootstrapPort` directly; the use cases in
:mod:`app.core.application.schema_bootstrap` are agnostic to which
one backs the port.

Rule §22 (SQL/service separation): the 27-statement DDL sequence that
constitutes ``ensure_domain_schema`` is assembled here, not interpolated
inside validation or orchestration. The individual SQL constants live
in the existing ``app.core.domain_*`` submodules (``domain_animales``,
``domain_voluntarios``, ...) because that is the structure the rest of
the codebase and ``tests/test_domain_*.py`` already depend on; the
adapter imports them by name rather than redefining them.

Rule §31 (domain depends on Protocol): the adapter constructor takes
a :class:`SqlExecutor`, not an :class:`InsForgeClient`. The
:class:`InsForgeClient` happens to satisfy the Protocol structurally
(it has ``execute_sql(query, params)`` returning ``list[dict]``), so
the DI helper can pass either without an explicit cast.
"""

# Deprecated 2026-09-06: this module is no longer the production
# transport. The Coolify-hosted local backend (LocalPostgresExecutor)
# is the only supported backend as of issue #641 closing the
# self-host umbrella. This file remains so the legacy InsForge-
# touching tests can run in CI; production deploys use the
# SqlExecutor-based adapter (a follow-up slice).



from __future__ import annotations

from collections.abc import Sequence

from app.core.data_access import SqlExecutor
from app.core.domain_adopciones import ADOPCIONES_CREATE_TABLE_SQL
from app.core.domain_animales import ANIMALS_CREATE_TABLE_SQL
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
from app.core.domain_terapias import (
    RECOMENDACIONES_CREATE_TABLE_SQL,
    TERAPIAS_CREATE_TABLE_SQL,
)
from app.core.domain_voluntarios import (
    ROLES_VOLUNTARIO_CREATE_TABLE_SQL,
    VOLUNTARIOS_CREATE_TABLE_SQL,
)
from app.core.logging import log_safe
from app.core.ports.schema_bootstrap_port import SqlStatement

# The canonical 27-statement DDL sequence that bootstraps every domain
# table in FK-dependency order. Order matches the legacy
# ``ensure_domain_schema`` exactly so the lifespan replay behaviour is
# preserved.
_DOMAIN_DDL_STATEMENTS: tuple[SqlStatement, ...] = (
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
    SqlStatement(TERAPIAS_CREATE_TABLE_SQL),
    SqlStatement(RECOMENDACIONES_CREATE_TABLE_SQL),
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


class InsForgeSchemaBootstrapAdapter:
    """InsForge implementation of :class:`SchemaBootstrapPort`.

    The adapter is stateless and thread-safe. It holds a single
    :class:`SqlExecutor` reference passed at construction time; the
    DI layer (``app/core/di/schema_bootstrap_di.py``) owns the
    executor's lifecycle, not the adapter.
    """

    def __init__(self, executor: SqlExecutor) -> None:
        """Store the executor used for every bootstrap statement.

        Args:
            executor: Any object that satisfies the
                :class:`app.core.data_access.SqlExecutor` Protocol.
                In production this is the :class:`InsForgeClient`
                stored on ``app.state.insforge_client``; in tests it
                can be an ``httpx.MockTransport``-backed fake.
        """
        self._executor = executor

    def ensure_domain_schema(self) -> None:
        """Bootstrap every domain table in the canonical dependency order.

        Mirrors the original :func:`app.core.domain.ensure_domain_schema`
        contract:

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
        self.run_idempotent_sql(_DOMAIN_DDL_STATEMENTS, step_name="domain")

    def run_idempotent_sql(
        self,
        statements: Sequence[SqlStatement],
        *,
        step_name: str,
    ) -> None:
        """Execute replay-safe statements in order and fail fast on errors.

        Idempotence remains a property of each supplied SQL statement
        (for example ``IF NOT EXISTS`` or ``ON CONFLICT DO NOTHING``).
        On the first failure the adapter emits one
        ``schema_bootstrap.failed`` log event with ``step_name`` and
        ``statement_index`` and re-raises the original exception
        untouched so the global exception handler can translate it.
        """
        for statement_index, statement in enumerate(statements):
            try:
                self._executor.execute_sql(statement.query, statement.params)
            except Exception as exc:
                log_safe(
                    "schema_bootstrap.failed",
                    step_name=step_name,
                    statement_index=statement_index,
                    error_type=type(exc).__name__,
                )
                raise


__all__ = ["InsForgeSchemaBootstrapAdapter"]
