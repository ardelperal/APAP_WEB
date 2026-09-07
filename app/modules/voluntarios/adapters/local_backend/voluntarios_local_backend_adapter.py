"""LocalBackend adapter implementing :class:`app.modules.voluntarios.ports.voluntarios_port.VoluntariosPort`.

Slice: app/modules/voluntarios (epic #420 PR-A + VOL-02).
All LocalBackend / PostgreSQL access is isolated here.  The port contract is
the only public API; nothing else in the slice may call ``SqlExecutor`` or
touch ``app.core.data_access`` directly (AGENTS.md §31).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.core.data_access import SqlExecutor
from app.modules.voluntarios.adapters.local_backend.voluntarios_local_backend_mappers import (
    row_to_voluntario,
)
from app.modules.voluntarios.adapters.local_backend.voluntarios_local_backend_queries import (
    GET_VOLUNTARIO_BY_ID_SQL,
    LIST_VOLUNTARIO_ROLES_SQL,
    LIST_VOLUNTARIOS_SQL,
)
from app.modules.voluntarios.adapters.local_backend.voluntarios_local_backend_write_queries import (
    ASSIGN_ROLE_SQL,
    CREATE_VOLUNTARIO_SQL,
    DEACTIVATE_VOLUNTARIO_SQL,
    REMOVE_ROLE_SQL,
)
from app.modules.voluntarios.domain.voluntario import Voluntario


class VoluntariosLocalBackendAdapter:
    """LocalBackend-backed implementation of :class:`VoluntariosPort`."""

    __slots__ = ("_executor",)

    def __init__(self, executor: SqlExecutor) -> None:
        self._executor = executor

    # -- read -----------------------------------------------------------

    def list_voluntarios(self) -> list[Voluntario]:
        rows = self._execute(LIST_VOLUNTARIOS_SQL)
        return [row_to_voluntario(row) for row in rows]

    def get_voluntario_by_id(self, voluntario_id: str) -> Voluntario | None:
        rows = self._execute(GET_VOLUNTARIO_BY_ID_SQL, [voluntario_id])
        return row_to_voluntario(rows[0]) if rows else None

    def list_voluntario_roles(self, voluntario_id: str) -> list[str]:
        rows = self._execute(LIST_VOLUNTARIO_ROLES_SQL, [voluntario_id])
        return [str(row["tipo_rol"]) for row in rows]

    # -- write ---------------------------------------------------------

    def create_voluntario(  # noqa: N803, PLR0913
        self,
        *,
        nombre: str,
        tel1: str | None = None,
        tel2: str | None = None,
        email: str | None = None,
        dni: str | None = None,
    ) -> Voluntario:
        """Insert a new volunteer and return the persisted row."""

        def _clean(value: str | None) -> str | None:
            if value is None:
                return None
            stripped = value.strip()
            return stripped or None

        params: list[Any] = [
            nombre.strip(),
            _clean(tel1),
            _clean(tel2),
            _clean(email),
            _clean(dni),
        ]
        rows = self._execute(CREATE_VOLUNTARIO_SQL, params)
        return row_to_voluntario(rows[0])

    def deactivate_voluntario(self, voluntario_id: str) -> bool:
        """Atomically set ``activo = false``; idempotent."""
        rows = self._execute(DEACTIVATE_VOLUNTARIO_SQL, [voluntario_id])
        return bool(rows)

    def assign_voluntario_role(
        self, voluntario_id: str, rol: str
    ) -> Voluntario:
        """Insert a role assignment; raises UniqueViolationError on duplicate."""
        self._execute(ASSIGN_ROLE_SQL, [voluntario_id, rol])
        rows = self._execute(GET_VOLUNTARIO_BY_ID_SQL, [voluntario_id])
        if not rows:
            return Voluntario(id=voluntario_id, voluntario="<deleted>", activo=False)
        return row_to_voluntario(rows[0])

    def remove_voluntario_role(
        self, voluntario_id: str, rol: str
    ) -> Voluntario:
        """Remove a role assignment; idempotent (no-op if not assigned)."""
        self._execute(REMOVE_ROLE_SQL, [voluntario_id, rol])
        rows = self._execute(GET_VOLUNTARIO_BY_ID_SQL, [voluntario_id])
        if not rows:
            return Voluntario(id=voluntario_id, voluntario="<deleted>", activo=False)
        return row_to_voluntario(rows[0])

    # -- internal ------------------------------------------------------

    def _execute(
        self,
        query: str,
        params: Sequence[Any] | None = None,
    ) -> list[dict[str, Any]]:
        return self._executor.execute_sql(
            query, list(params) if params is not None else None
        )


__all__ = ["VoluntariosLocalBackendAdapter"]
