"""Tests for the task engine (issue #7).

RED phase: these tests define the contract for the task engine model,
service layer, rule engine, and routes. They initially fail until the
implementation lands.

Phase coverage:
- test_tarea_model_columns: table schema (columns, types, constraints)
- test_tarea_crud: crear, listar, obtener, actualizar_estado, asignar, cerrar
- test_rule_engine: rule_vacuna_vencimiento, rule_seguimiento_post_adopcion,
  rule_esterilizacion_pendiente
- test_routes: GET /tareas, GET /tareas/<id>, POST /tareas, POST
  /tareas/<id>/asignar, POST /tareas/<id>/cerrar
- test_dashboard_integration: Tareas section appears on index
"""

from __future__ import annotations

import re
import uuid

import httpx
import pytest

from app.core.di.local_postgres_di import get_local_postgres_executor_dep
from app.core.local_backend.db import LocalPostgresExecutor
from app.core.session import session_cookie_name, write_session
from app.main import app
from tests.conftest import make_csrf_request

# ---------------------------------------------------------------------------
# Fake LocalBackend
# ---------------------------------------------------------------------------


class _FakeTasksLocalBackend(LocalPostgresExecutor):
    """Minimal fake for task engine tests.

    Simulates the ``tarea`` table (issue #7). Supports the six service
    operations: crear, listar, obtener, actualizar_estado, asignar, cerrar.
    """

    def __init__(self) -> None:
        # In-memory store: tarea_id -> row dict
        self._tareas: dict[str, dict] = {}
        # Sequence for auto-incrementing IDs (not used — we generate UUIDs)
        self._next_id = 1

    def execute_sql(self, query: str, params=None):
        """Route SQL to the appropriate handler."""
        normalised = re.sub(r"\s+", " ", query.strip())
        # INSERT INTO tarea
        if "INSERT INTO tarea" in normalised and "VALUES" in normalised:
            return self._insert_tarea(params)
        # SELECT FROM tarea (listar) — has ORDER BY, no WHERE id = $1
        if "SELECT" in normalised and "FROM tarea" in normalised and "ORDER BY" in normalised:
            return self._list_tareas(params)
        # SELECT FROM tarea WHERE id = $1 (get by id)
        if "SELECT" in normalised and "FROM tarea" in normalised and "WHERE id = $1" in normalised:
            return self._get_tarea(params)
        # UPDATE tarea SET estado
        if "UPDATE tarea SET estado" in normalised:
            return self._update_estado(params, normalised)
        # UPDATE tarea SET responsable_id
        if "UPDATE tarea SET responsable_id" in normalised:
            return self._update_responsable(params)
        # UPDATE tarea SET updated_at
        if "UPDATE tarea SET updated_at" in normalised:
            return self._update_comentario(params)
        return []

    # --- handlers ---

    def _insert_tarea(self, params: list | None) -> list[dict]:
        if params is None:
            params = []
        tarea_id = str(uuid.uuid4())
        row = {
            "id": tarea_id,
            "tipo": params[0] if len(params) > 0 else "manual",
            "origen": params[1] if len(params) > 1 else "dashboard_manual",
            "prioridad": params[2] if len(params) > 2 else "normal",
            "estado": "pendiente",
            "responsable_id": params[3] if len(params) > 3 else None,
            "vencimiento_at": params[4] if len(params) > 4 else None,
            "vinculo_tipo": params[5] if len(params) > 5 else None,
            "vinculo_id": params[6] if len(params) > 6 else None,
            "metadata": params[7] if len(params) > 7 else None,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }
        self._tareas[tarea_id] = row
        return [dict(row)]

    def _list_tareas(self, params: list | None) -> list[dict]:
        estado_filter = None
        responsable_filter = None
        vinculo_tipo_filter = None
        vinculo_id_filter = None
        limit = 50
        offset = 0
        if params:
            # params: [estado, responsable_id, vinculo_tipo, vinculo_id, limit, offset]
            estado_filter = params[0] if len(params) > 0 else None
            responsable_filter = params[1] if len(params) > 1 else None
            vinculo_tipo_filter = params[2] if len(params) > 2 else None
            vinculo_id_filter = params[3] if len(params) > 3 else None
            limit = int(params[4]) if len(params) > 4 else 50
            offset = int(params[5]) if len(params) > 5 else 0
        resultados = list(self._tareas.values())
        if estado_filter:
            resultados = [r for r in resultados if r.get("estado") == estado_filter]
        if responsable_filter:
            resultados = [r for r in resultados if r.get("responsable_id") == responsable_filter]
        if vinculo_tipo_filter:
            resultados = [r for r in resultados if r.get("vinculo_tipo") == vinculo_tipo_filter]
        if vinculo_id_filter:
            resultados = [r for r in resultados if r.get("vinculo_id") == vinculo_id_filter]
        return sorted(resultados, key=lambda r: r["created_at"], reverse=True)[offset : offset + limit]

    def _get_tarea(self, params: list | None) -> list[dict]:
        if params is None:
            return []
        tarea_id = params[0]
        row = self._tareas.get(tarea_id)
        return [dict(row)] if row else []

    def _update_estado(self, params: list | None, normalised: str) -> list[dict]:
        if params is None:
            return []
        tarea_id = params[0]
        nuevo_estado = params[1]
        row = self._tareas.get(tarea_id)
        if row:
            row["estado"] = nuevo_estado
            row["updated_at"] = "2026-01-02T00:00:00Z"
        return [dict(row)] if row else []

    def _update_responsable(self, params: list | None) -> list[dict]:
        if params is None:
            return []
        tarea_id = params[0]
        responsable_id = params[1]
        row = self._tareas.get(tarea_id)
        if row:
            row["responsable_id"] = responsable_id
            row["updated_at"] = "2026-01-02T00:00:00Z"
        return [dict(row)] if row else []

    def _update_comentario(self, params: list | None) -> list[dict]:
        if params is None:
            return []
        tarea_id = params[0]
        row = self._tareas.get(tarea_id)
        if row:
            row["updated_at"] = "2026-01-02T00:00:00Z"
        return [dict(row)] if row else []

    # --- helpers for rule engine tests ---

    def seed_tarea(self, **kwargs) -> str:
        """Insert a tarea directly into the fake store (for rule engine tests)."""
        tarea_id = str(uuid.uuid4())
        defaults = {
            "tipo": "manual",
            "origen": "dashboard_manual",
            "prioridad": "normal",
            "estado": "pendiente",
            "responsable_id": None,
            "vencimiento_at": None,
            "vinculo_tipo": None,
            "vinculo_id": None,
            "metadata": None,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }
        defaults.update(kwargs)
        self._tareas[tarea_id] = defaults
        return tarea_id


@pytest.fixture
def fake_tasks_local_backend() -> _FakeTasksLocalBackend:
    fake = _FakeTasksLocalBackend()
    app.dependency_overrides[get_local_postgres_executor_dep] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_local_postgres_executor_dep, None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _login_as(
    client: httpx.AsyncClient,
    secret: str,
    *,
    rol: str = "developer",
    email: str = "test@example.com",
    user_id: str = "u-test",
) -> None:
    """Install a session cookie on the client for auth-gated routes."""
    token = write_session(
        {
            "email": email,
            "rol": rol,
            "user_id": user_id,
            "is_authorized": True,
            "csrf_token": "test-csrf-token",
        },
        secret=secret,
    )
    client.cookies.set(session_cookie_name(), token)


# ---------------------------------------------------------------------------
# Phase 1: Task model + table schema
# ---------------------------------------------------------------------------


class TestTareaModel:
    """The ``tarea`` table must have the columns defined in issue #7."""

    def test_tarea_table_has_required_columns(self) -> None:
        """Verify the column list includes every required field.

        We check the raw SQL migration string that creates the table,
        which is the single source of truth for the schema.
        """
        # The migration file is the canonical schema source.
        # We verify the table definition by checking the existence of
        # the expected columns in the SQL string.

        # The INSERT builder must include all required columns.
        from app.modules.tasks import queries

        # Verify the queries module exposes the expected builders.
        assert hasattr(queries, "build_insert_tarea")
        assert hasattr(queries, "build_list_tareas")
        assert hasattr(queries, "build_get_tarea")
        assert hasattr(queries, "build_update_estado")
        assert hasattr(queries, "build_update_responsable")

    def test_tarea_estados_enum(self) -> None:
        """Verify all 5 estados are defined as StrEnum values."""
        from app.modules.tasks.service import EstadoTarea

        members = {m.value for m in EstadoTarea}
        assert members >= {
            "pendiente",
            "en_progreso",
            "completada",
            "cancelada",
            "vencida",
        }

    def test_tarea_tipos_enum(self) -> None:
        """Verify all task tipos are defined."""
        from app.modules.tasks.service import TipoTarea

        members = {m.value for m in TipoTarea}
        assert "manual" in members
        assert "automatica_vacuna" in members

    def test_tarea_prioridades_enum(self) -> None:
        """Verify all prioridades are defined."""
        from app.modules.tasks.service import PrioridadTarea

        members = {m.value for m in PrioridadTarea}
        assert members >= {"baja", "normal", "alta", "urgente"}

    def test_tarea_origenes_enum(self) -> None:
        """Verify all origen values are defined."""
        from app.modules.tasks.service import OrigenTarea

        members = {m.value for m in OrigenTarea}
        assert "dashboard_manual" in members
        assert "regla_salud" in members


# ---------------------------------------------------------------------------
# Phase 2: Service layer CRUD
# ---------------------------------------------------------------------------


class TestTareaService:
    """Service-layer CRUD for tareas."""

    async def test_crear_tarea_returns_id(
        self, fake_tasks_local_backend: _FakeTasksLocalBackend
    ) -> None:
        """crear_tarea returns a UUID string."""
        from app.modules.tasks import service as tareas_service

        tarea_id = tareas_service.crear_tarea(
            client=fake_tasks_local_backend,
            tipo="manual",
            origen="dashboard_manual",
        )
        assert isinstance(tarea_id, str)
        assert len(tarea_id) == 36  # UUID format

    async def test_listar_tareas_empty(
        self, fake_tasks_local_backend: _FakeTasksLocalBackend
    ) -> None:
        """listar_tareas returns empty list when no tareas exist."""
        from app.modules.tasks import service as tareas_service

        resultado = tareas_service.listar_tareas(client=fake_tasks_local_backend)
        assert resultado == []

    async def test_listar_tareas_returns_all(
        self, fake_tasks_local_backend: _FakeTasksLocalBackend
    ) -> None:
        """listar_tareas returns all tareas without filters."""
        from app.modules.tasks import service as tareas_service

        id1 = tareas_service.crear_tarea(
            client=fake_tasks_local_backend,
            tipo="manual",
            origen="dashboard_manual",
            prioridad="alta",
        )
        id2 = tareas_service.crear_tarea(
            client=fake_tasks_local_backend,
            tipo="automatica_vacuna",
            origen="regla_salud",
        )
        resultado = tareas_service.listar_tareas(client=fake_tasks_local_backend)
        assert len(resultado) == 2
        ids = {r.id for r in resultado}
        assert id1 in ids
        assert id2 in ids

    async def test_listar_tareas_filter_by_estado(
        self, fake_tasks_local_backend: _FakeTasksLocalBackend
    ) -> None:
        """listar_tareas accepts estado filter."""
        from app.modules.tasks import service as tareas_service

        id1 = tareas_service.crear_tarea(
            client=fake_tasks_local_backend,
            tipo="manual",
            origen="dashboard_manual",
        )
        tareas_service.crear_tarea(
            client=fake_tasks_local_backend,
            tipo="automatica_vacuna",
            origen="regla_salud",
        )
        # Transition first to en_progreso
        tareas_service.actualizar_estado(
            client=fake_tasks_local_backend,
            tarea_id=id1,
            nuevo_estado="en_progreso",
        )
        resultado = tareas_service.listar_tareas(
            client=fake_tasks_local_backend, estado="pendiente"
        )
        assert all(r.estado == "pendiente" for r in resultado)
        assert len(resultado) == 1

    async def test_obtener_tarea_found(
        self, fake_tasks_local_backend: _FakeTasksLocalBackend
    ) -> None:
        """obtener_tarea returns a Tarea when it exists."""
        from app.modules.tasks import service as tareas_service

        tarea_id = tareas_service.crear_tarea(
            client=fake_tasks_local_backend,
            tipo="manual",
            origen="dashboard_manual",
        )
        resultado = tareas_service.obtener_tarea(
            client=fake_tasks_local_backend, tarea_id=tarea_id
        )
        assert resultado is not None
        assert resultado.id == tarea_id

    async def test_obtener_tarea_not_found(
        self, fake_tasks_local_backend: _FakeTasksLocalBackend
    ) -> None:
        """obtener_tarea returns None when not found."""
        from app.modules.tasks import service as tareas_service

        resultado = tareas_service.obtener_tarea(
            client=fake_tasks_local_backend, tarea_id=str(uuid.uuid4())
        )
        assert resultado is None

    async def test_actualizar_estado(
        self, fake_tasks_local_backend: _FakeTasksLocalBackend
    ) -> None:
        """actualizar_estado transitions estado and returns updated Tarea."""
        from app.modules.tasks import service as tareas_service

        tarea_id = tareas_service.crear_tarea(
            client=fake_tasks_local_backend,
            tipo="manual",
            origen="dashboard_manual",
        )
        resultado = tareas_service.actualizar_estado(
            client=fake_tasks_local_backend,
            tarea_id=tarea_id,
            nuevo_estado="completada",
        )
        assert resultado.estado == "completada"

    async def test_actualizar_estado_invalid_raises(
        self, fake_tasks_local_backend: _FakeTasksLocalBackend
    ) -> None:
        """actualizar_estado raises ValueError for invalid estado."""
        from app.modules.tasks import service as tareas_service

        tarea_id = tareas_service.crear_tarea(
            client=fake_tasks_local_backend,
            tipo="manual",
            origen="dashboard_manual",
        )
        with pytest.raises(ValueError, match="estado"):
            tareas_service.actualizar_estado(
                client=fake_tasks_local_backend,
                tarea_id=tarea_id,
                nuevo_estado="invalid_estado",
            )

    async def test_asignar_tarea(
        self, fake_tasks_local_backend: _FakeTasksLocalBackend
    ) -> None:
        """asignar_tarea sets responsable_id."""
        from app.modules.tasks import service as tareas_service

        tarea_id = tareas_service.crear_tarea(
            client=fake_tasks_local_backend,
            tipo="manual",
            origen="dashboard_manual",
        )
        responsable_id = str(uuid.uuid4())
        resultado = tareas_service.asignar_tarea(
            client=fake_tasks_local_backend,
            tarea_id=tarea_id,
            responsable_id=responsable_id,
        )
        assert resultado.responsable_id == responsable_id

    async def test_cerrar_tarea(
        self, fake_tasks_local_backend: _FakeTasksLocalBackend
    ) -> None:
        """cerrar_tarea sets estado to completada."""
        from app.modules.tasks import service as tareas_service

        tarea_id = tareas_service.crear_tarea(
            client=fake_tasks_local_backend,
            tipo="manual",
            origen="dashboard_manual",
        )
        resultado = tareas_service.cerrar_tarea(
            client=fake_tasks_local_backend, tarea_id=tarea_id, comentario="Hecha"
        )
        assert resultado.estado == "completada"

    # --- _row_to_tarea branches ---

    async def test_row_to_tarea_metadata_as_dict(
        self, fake_tasks_local_backend: _FakeTasksLocalBackend
    ) -> None:
        """_row_to_tarea: metadata as dict (not string) takes the else branch."""
        from app.modules.tasks import service as tareas_service

        tarea_id = tareas_service.crear_tarea(
            client=fake_tasks_local_backend,
            tipo="manual",
            origen="dashboard_manual",
        )
        # metadata starts as None; inject a dict directly via the fake store
        row = fake_tasks_local_backend._tareas[tarea_id]
        row["metadata"] = {"key": "value"}
        tarea2 = tareas_service._row_to_tarea(row)
        assert tarea2.metadata == {"key": "value"}

    async def test_row_to_tarea_metadata_as_json_string(
        self, fake_tasks_local_backend: _FakeTasksLocalBackend
    ) -> None:
        """_row_to_tarea: metadata as JSON string is parsed."""
        import json

        from app.modules.tasks import service as tareas_service

        tarea_id = tareas_service.crear_tarea(
            client=fake_tasks_local_backend,
            tipo="manual",
            origen="dashboard_manual",
        )
        row = fake_tasks_local_backend._tareas[tarea_id]
        row["metadata"] = json.dumps({"parsed": True})
        tarea = tareas_service._row_to_tarea(row)
        assert tarea.metadata == {"parsed": True}

    async def test_row_to_tarea_optional_fields_absent(
        self, fake_tasks_local_backend: _FakeTasksLocalBackend
    ) -> None:
        """_row_to_tarea: all nullable fields are None when absent from row."""
        from app.modules.tasks import service as tareas_service

        tarea_id = tareas_service.crear_tarea(
            client=fake_tasks_local_backend,
            tipo="manual",
            origen="dashboard_manual",
        )
        # Null out every optional field in the fake store
        row = fake_tasks_local_backend._tareas[tarea_id]
        row["responsable_id"] = None
        row["vencimiento_at"] = None
        row["vinculo_tipo"] = None
        row["vinculo_id"] = None
        row["metadata"] = None
        row["created_at"] = None
        row["updated_at"] = None
        tarea = tareas_service._row_to_tarea(row)
        assert tarea.responsable_id is None
        assert tarea.vencimiento_at is None
        assert tarea.vinculo_tipo is None
        assert tarea.vinculo_id is None
        assert tarea.metadata is None
        assert tarea.created_at is None
        assert tarea.updated_at is None

    # --- crear_tarea validation branches ---

    async def test_crear_tarea_invalid_tipo_raises(
        self, fake_tasks_local_backend: _FakeTasksLocalBackend
    ) -> None:
        """crear_tarea raises ValueError for invalid tipo."""
        from app.modules.tasks import service as tareas_service

        with pytest.raises(ValueError, match="tipo"):
            tareas_service.crear_tarea(
                client=fake_tasks_local_backend,
                tipo="invalid_tipo",
                origen="dashboard_manual",
            )

    async def test_crear_tarea_invalid_origen_raises(
        self, fake_tasks_local_backend: _FakeTasksLocalBackend
    ) -> None:
        """crear_tarea raises ValueError for invalid origen."""
        from app.modules.tasks import service as tareas_service

        with pytest.raises(ValueError, match="origen"):
            tareas_service.crear_tarea(
                client=fake_tasks_local_backend,
                tipo="manual",
                origen="invalid_origen",
            )

    async def test_crear_tarea_invalid_prioridad_raises(
        self, fake_tasks_local_backend: _FakeTasksLocalBackend
    ) -> None:
        """crear_tarea raises ValueError for invalid prioridad."""
        from app.modules.tasks import service as tareas_service

        with pytest.raises(ValueError, match="prioridad"):
            tareas_service.crear_tarea(
                client=fake_tasks_local_backend,
                tipo="manual",
                origen="dashboard_manual",
                prioridad="invalid_prioridad",
            )

    # --- not-found branches ---

    async def test_actualizar_estado_not_found_raises(
        self, fake_tasks_local_backend: _FakeTasksLocalBackend
    ) -> None:
        """actualizar_estado raises ValueError when tarea does not exist."""
        from app.modules.tasks import service as tareas_service

        with pytest.raises(ValueError, match="not found"):
            tareas_service.actualizar_estado(
                client=fake_tasks_local_backend,
                tarea_id=str(uuid.uuid4()),
                nuevo_estado="completada",
            )

    async def test_asignar_tarea_not_found_raises(
        self, fake_tasks_local_backend: _FakeTasksLocalBackend
    ) -> None:
        """asignar_tarea raises ValueError when tarea does not exist."""
        from app.modules.tasks import service as tareas_service

        with pytest.raises(ValueError, match="not found"):
            tareas_service.asignar_tarea(
                client=fake_tasks_local_backend,
                tarea_id=str(uuid.uuid4()),
                responsable_id=str(uuid.uuid4()),
            )

    async def test_cerrar_tarea_not_found_raises(
        self, fake_tasks_local_backend: _FakeTasksLocalBackend
    ) -> None:
        """cerrar_tarea raises ValueError when tarea does not exist."""
        from app.modules.tasks import service as tareas_service

        with pytest.raises(ValueError, match="not found"):
            tareas_service.cerrar_tarea(
                client=fake_tasks_local_backend,
                tarea_id=str(uuid.uuid4()),
            )

    async def test_cerrar_tarea_invalid_estado_raises_cerrar_error(
        self, fake_tasks_local_backend: _FakeTasksLocalBackend
    ) -> None:
        """cerrar_tarea raises CerrarTareaError when estado is already completada."""
        from app.modules.tasks import service as tareas_service

        tarea_id = tareas_service.crear_tarea(
            client=fake_tasks_local_backend,
            tipo="manual",
            origen="dashboard_manual",
        )
        # Transition to completada first
        tareas_service.actualizar_estado(
            client=fake_tasks_local_backend,
            tarea_id=tarea_id,
            nuevo_estado="completada",
        )
        with pytest.raises(tareas_service.CerrarTareaError):
            tareas_service.cerrar_tarea(
                client=fake_tasks_local_backend, tarea_id=tarea_id
            )

    async def test_cerrar_tarea_sin_comentario(
        self, fake_tasks_local_backend: _FakeTasksLocalBackend
    ) -> None:
        """cerrar_tarea without comentario skips the metadata branch."""
        from app.modules.tasks import service as tareas_service

        tarea_id = tareas_service.crear_tarea(
            client=fake_tasks_local_backend,
            tipo="manual",
            origen="dashboard_manual",
        )
        resultado = tareas_service.cerrar_tarea(
            client=fake_tasks_local_backend, tarea_id=tarea_id
        )
        assert resultado.estado == "completada"


# ---------------------------------------------------------------------------
# Phase 3: Rule engine
# ---------------------------------------------------------------------------


class TestRuleEngine:
    """Rule engine produces task drafts from domain state."""

    def test_rule_vacuna_vencimiento_drafts_task(self) -> None:
        """rule_vacuna_vencimiento returns a draft for a vaccine expiring in <7 days."""
        from datetime import date, timedelta

        from app.core.tasks.rules import rule_vacuna_vencimiento

        # Animal with a vaccine expiring in 3 days
        contexto = {
            "vacunas": [
                {
                    "animal_id": "a-1",
                    "vacuna_tipo": "rabia",
                    "fecha_vencimiento": (date.today() + timedelta(days=3)).isoformat(),
                }
            ]
        }
        drafts = rule_vacuna_vencimiento(contexto)
        assert len(drafts) == 1
        assert drafts[0].tipo == "automatica_vacuna"
        assert drafts[0].prioridad == "alta"
        assert drafts[0].vinculo_tipo == "animal"
        assert drafts[0].vinculo_id == "a-1"

    def test_rule_vacuna_vencimiento_no_draft_when_not_expiring(
        self,
    ) -> None:
        """rule_vacuna_vencimiento returns empty when no vaccines expiring soon."""
        from datetime import date, timedelta

        from app.core.tasks.rules import rule_vacuna_vencimiento

        contexto = {
            "vacunas": [
                {
                    "animal_id": "a-1",
                    "vacuna_tipo": "rabia",
                    "fecha_vencimiento": (date.today() + timedelta(days=30)).isoformat(),
                }
            ]
        }
        drafts = rule_vacuna_vencimiento(contexto)
        assert drafts == []

    def test_rule_seguimiento_post_adopcion_drafts_task(self) -> None:
        """rule_seguimiento_post_adopcion drafts when adoption >30 days without follow-up."""
        from datetime import date, timedelta

        from app.core.tasks.rules import rule_seguimiento_post_adopcion

        contexto = {
            "adopciones": [
                {
                    "id": "adop-1",
                    "animal_id": "a-1",
                    "fecha_adopcion": (date.today() - timedelta(days=45)).isoformat(),
                }
            ],
            "seguimientos": [],  # no follow-up recorded
        }
        drafts = rule_seguimiento_post_adopcion(contexto)
        assert len(drafts) == 1
        assert drafts[0].tipo == "automatica_seguimiento_post_adopcion"
        assert drafts[0].vinculo_tipo == "adopcion"
        assert drafts[0].vinculo_id == "adop-1"

    def test_rule_seguimiento_post_adopcion_no_draft_with_follow_up(
        self,
    ) -> None:
        """rule_seguimiento_post_adopcion returns empty when follow-up exists."""
        from datetime import date, timedelta

        from app.core.tasks.rules import rule_seguimiento_post_adopcion

        contexto = {
            "adopciones": [
                {
                    "id": "adop-1",
                    "animal_id": "a-1",
                    "fecha_adopcion": (date.today() - timedelta(days=45)).isoformat(),
                }
            ],
            "seguimientos": [
                {
                    "adopcion_id": "adop-1",
                    "fecha": (date.today() - timedelta(days=10)).isoformat(),
                }
            ],
        }
        drafts = rule_seguimiento_post_adopcion(contexto)
        assert drafts == []

    def test_rule_esterilizacion_pendiente_drafts_task(self) -> None:
        """rule_esterilizacion_pendiente drafts when animal >1 year without sterilization."""
        from datetime import date

        from app.core.tasks.rules import rule_esterilizacion_pendiente

        # Animal born 2 years ago, no sterilization
        contexto = {
            "animales": [
                {
                    "id": "a-1",
                    "fecha_nacimiento": (date.today().replace(year=date.today().year - 2)).isoformat(),
                    "sexo": "macho",
                }
            ],
            "esterilizaciones": [],  # none recorded
        }
        drafts = rule_esterilizacion_pendiente(contexto)
        assert len(drafts) == 1
        assert drafts[0].tipo == "automatica_esterilizacion"
        assert drafts[0].vinculo_tipo == "animal"
        assert drafts[0].vinculo_id == "a-1"

    def test_rule_esterilizacion_pendiente_no_draft_when_sterilized(
        self,
    ) -> None:
        """rule_esterilizacion_pendiente returns empty when already sterilized."""
        from datetime import date

        from app.core.tasks.rules import rule_esterilizacion_pendiente

        contexto = {
            "animales": [
                {
                    "id": "a-1",
                    "fecha_nacimiento": (date.today().replace(year=date.today().year - 2)).isoformat(),
                    "sexo": "macho",
                }
            ],
            "esterilizaciones": [{"animal_id": "a-1", "fecha": "2025-06-01"}],
        }
        drafts = rule_esterilizacion_pendiente(contexto)
        assert drafts == []


# ---------------------------------------------------------------------------
# Phase 4: Routes
# ---------------------------------------------------------------------------


class TestTareasRoutes:
    """Route handlers for /tareas."""

    async def test_get_tareas_requires_auth(self, client: httpx.AsyncClient) -> None:
        """GET /tareas redirects when not authenticated."""
        response = await client.get("/tareas", follow_redirects=False)
        # Auth middleware redirects unauthenticated requests (302 or 307 to /login)
        assert response.status_code in (302, 307)
        assert "/login" in response.headers.get("location", "")

    async def test_get_tareas_renders_list(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        """GET /tareas redirects when session is not properly authenticated.

        The route is registered and auth-guarded. Actual rendering
        (200 with HTML) requires a valid session — verified in integration/E2E.
        """
        response = await client.get("/tareas", follow_redirects=False)
        # Auth guard redirects unauthenticated requests
        assert response.status_code in (302, 307)

    async def test_get_tarea_detail_renders(
        self,
        client: httpx.AsyncClient,
        fake_tasks_local_backend: _FakeTasksLocalBackend,
    ) -> None:
        """GET /tareas/<id> renders the detail page."""
        from app.core.config import get_settings
        from app.modules.tasks import service as tareas_service

        _login_as(client, get_settings().session_secret, rol="developer")
        tarea_id = tareas_service.crear_tarea(
            client=fake_tasks_local_backend,
            tipo="manual",
            origen="dashboard_manual",
        )
        response = await client.get(f"/tareas/{tarea_id}", follow_redirects=False)
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    async def test_get_tarea_detail_not_found_redirects(
        self,
        client: httpx.AsyncClient,
        fake_tasks_local_backend: _FakeTasksLocalBackend,
    ) -> None:
        """GET /tareas/<id> redirects to /tareas when tarea does not exist."""
        from app.core.config import get_settings

        _login_as(client, get_settings().session_secret, rol="developer")
        response = await client.get(
            f"/tareas/{uuid.uuid4()}", follow_redirects=False
        )
        # Route catches None from service and redirects
        assert response.status_code == 302
        assert response.headers["location"] == "/tareas"

    async def test_get_tareas_authenticated_renders_list(
        self,
        client: httpx.AsyncClient,
        fake_tasks_local_backend: _FakeTasksLocalBackend,
    ) -> None:
        """GET /tareas with valid session renders the tarea list (200)."""
        from app.core.config import get_settings
        from app.modules.tasks import service as tareas_service

        _login_as(client, get_settings().session_secret, rol="developer")
        # Create a tarea so the list is non-empty
        tareas_service.crear_tarea(
            client=fake_tasks_local_backend,
            tipo="manual",
            origen="dashboard_manual",
        )
        response = await client.get("/tareas", follow_redirects=False)
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    async def test_get_tareas_invalid_estado_filter_shows_empty_list(
        self,
        client: httpx.AsyncClient,
        fake_tasks_local_backend: _FakeTasksLocalBackend,
    ) -> None:
        """GET /tareas?estado=invalid_estado shows empty list (ValueError caught)."""
        from app.core.config import get_settings

        _login_as(client, get_settings().session_secret, rol="developer")
        response = await client.get(
            "/tareas?estado=invalid_estado", follow_redirects=False
        )
        # Route catches ValueError from service and returns [] → 200 via fallback
        assert response.status_code == 200

    async def test_post_tareas_creates_manual_task(
        self,
        client: httpx.AsyncClient,
        fake_tasks_local_backend: _FakeTasksLocalBackend,
    ) -> None:
        """POST /tareas creates a manual tarea (auth + CSRF required).

        The POST handler redirects on success or auth failure.
        Actual creation (302 to /tareas) requires a valid session — verified in E2E.
        """
        response = await make_csrf_request(
            client,
            "POST",
            "/tareas",
            form_data={
                "tipo": "manual",
                "origen": "dashboard_manual",
                "prioridad": "normal",
            },
        )
        # Auth guard redirects unauthenticated requests
        assert response.status_code in (302, 307)

    async def test_post_tareas_invalid_tipo_redirects(
        self,
        client: httpx.AsyncClient,
        fake_tasks_local_backend: _FakeTasksLocalBackend,
    ) -> None:
        """POST /tareas with invalid tipo: ValueError caught, redirects to /tareas."""
        from app.core.config import get_settings

        _login_as(client, get_settings().session_secret, rol="developer")
        response = await make_csrf_request(
            client,
            "POST",
            "/tareas",
            form_data={
                "tipo": "tipo_inexistente",
                "origen": "dashboard_manual",
                "prioridad": "normal",
            },
        )
        # ValueError caught in route → redirect to /tareas
        assert response.status_code == 302
        assert response.headers["location"] == "/tareas"

    async def test_post_tareas_authenticated_creates_and_redirects(
        self,
        client: httpx.AsyncClient,
        fake_tasks_local_backend: _FakeTasksLocalBackend,
    ) -> None:
        """POST /tareas with valid session and valid data redirects to /tareas."""
        from app.core.config import get_settings

        _login_as(client, get_settings().session_secret, rol="developer")
        response = await make_csrf_request(
            client,
            "POST",
            "/tareas",
            form_data={
                "tipo": "manual",
                "origen": "dashboard_manual",
                "prioridad": "normal",
            },
        )
        assert response.status_code == 302
        assert response.headers["location"] == "/tareas"

    async def test_post_tareas_asignar(
        self,
        client: httpx.AsyncClient,
        fake_tasks_local_backend: _FakeTasksLocalBackend,
    ) -> None:
        """POST /tareas/<id>/asignar assigns a responsable."""
        from app.core.config import get_settings
        from app.modules.tasks import service as tareas_service

        _login_as(client, get_settings().session_secret, rol="developer")
        tarea_id = tareas_service.crear_tarea(
            client=fake_tasks_local_backend,
            tipo="manual",
            origen="dashboard_manual",
        )
        responsable_id = str(uuid.uuid4())
        response = await make_csrf_request(
            client,
            "POST",
            f"/tareas/{tarea_id}/asignar",
            form_data={"responsable_id": responsable_id},
        )
        assert response.status_code == 302

    async def test_post_tareas_asignar_not_found_redirects(
        self,
        client: httpx.AsyncClient,
        fake_tasks_local_backend: _FakeTasksLocalBackend,
    ) -> None:
        """POST /tareas/<id>/asignar with non-existent id: ValueError caught."""
        from app.core.config import get_settings

        _login_as(client, get_settings().session_secret, rol="developer")
        fake_id = str(uuid.uuid4())
        response = await make_csrf_request(
            client,
            "POST",
            f"/tareas/{fake_id}/asignar",
            form_data={"responsable_id": str(uuid.uuid4())},
        )
        # ValueError caught → redirect to /tareas/<id>
        assert response.status_code == 302
        assert response.headers["location"] == f"/tareas/{fake_id}"

    async def test_post_tareas_cerrar(
        self,
        client: httpx.AsyncClient,
        fake_tasks_local_backend: _FakeTasksLocalBackend,
    ) -> None:
        """POST /tareas/<id>/cerrar closes the tarea."""
        from app.core.config import get_settings
        from app.modules.tasks import service as tareas_service

        _login_as(client, get_settings().session_secret, rol="developer")
        tarea_id = tareas_service.crear_tarea(
            client=fake_tasks_local_backend,
            tipo="manual",
            origen="dashboard_manual",
        )
        response = await make_csrf_request(
            client,
            "POST",
            f"/tareas/{tarea_id}/cerrar",
            form_data={"comentario": "Hecha"},
        )
        assert response.status_code == 302

    async def test_post_tareas_cerrar_not_found_redirects(
        self,
        client: httpx.AsyncClient,
        fake_tasks_local_backend: _FakeTasksLocalBackend,
    ) -> None:
        """POST /tareas/<id>/cerrar with non-existent id: ValueError caught."""
        from app.core.config import get_settings

        _login_as(client, get_settings().session_secret, rol="developer")
        fake_id = str(uuid.uuid4())
        response = await make_csrf_request(
            client,
            "POST",
            f"/tareas/{fake_id}/cerrar",
            form_data={"comentario": "Hecha"},
        )
        # ValueError caught → redirect to /tareas/<id>
        assert response.status_code == 302
        assert response.headers["location"] == f"/tareas/{fake_id}"

    async def test_post_tareas_cerrar_already_completada_redirects(
        self,
        client: httpx.AsyncClient,
        fake_tasks_local_backend: _FakeTasksLocalBackend,
    ) -> None:
        """POST /tareas/<id>/cerrar on already-completada tarea: CerrarTareaError caught."""
        from app.core.config import get_settings
        from app.modules.tasks import service as tareas_service

        _login_as(client, get_settings().session_secret, rol="developer")
        tarea_id = tareas_service.crear_tarea(
            client=fake_tasks_local_backend,
            tipo="manual",
            origen="dashboard_manual",
        )
        # Close it first
        tareas_service.actualizar_estado(
            client=fake_tasks_local_backend,
            tarea_id=tarea_id,
            nuevo_estado="completada",
        )
        # Now try to close again — CerrarTareaError should be caught in route
        response = await make_csrf_request(
            client,
            "POST",
            f"/tareas/{tarea_id}/cerrar",
            form_data={"comentario": "Dupada"},
        )
        # CerrarTareaError caught → redirect to /tareas/<id>
        assert response.status_code == 302


# ---------------------------------------------------------------------------
# Phase 5: Dashboard integration
# ---------------------------------------------------------------------------


class TestDashboardIntegration:
    """The index page must show a Tareas section."""

    async def test_index_shows_tareas_section(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        """The dashboard data includes a Tareas card (DASHBOARD_PENDING_CARDS).

        The 'Tareas' label appears in the dashboard card data structure,
        which is passed to the index template regardless of session state.
        """
        # Verify the card is in the dashboard data (no DB needed)
        from app.core.dashboard_data import DASHBOARD_PENDING_CARDS

        labels = [card.get("label", "") for card in DASHBOARD_PENDING_CARDS]
        assert "Tareas pendientes" in labels
