"""Unit tests for ``app.modules.sanidad.periodicity`` (HEALTH-05, #54).

Tests the pure functions in the periodicity engine:
- PeriodicidadRule.is_recurring() and next_due_date()
- codigo_to_tipo_tarea() mapping
- find_periodicity_rule() lookup (exact vs wildcard especie)
- generate_next_tarea() task creation params
- _priority_from_date() priority assignment
- _fallback_add_months() month arithmetic

No SQL mocking needed — all tests are pure unit tests.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.sanidad import periodicity as periodicity_module
from app.modules.sanidad.periodicity import (
    PeriodicidadRule,
    _fallback_add_months,
    _priority_from_date,
    codigo_to_tipo_tarea,
    find_periodicity_rule,
    generate_next_tarea,
)
from app.modules.sanidad.scheduling import schedule_periodic_task

# --- PeriodicidadRule -------------------------------------------------------

class TestPeriodicidadRuleIsRecurring:
    """is_recurring() returns True only for positive periodicidad_meses."""

    def test_null_meses_is_one_shot(self) -> None:
        rule = PeriodicidadRule(
            codigo="Esterilización",
            especie="canina",
            periodicidad_meses=None,
        )
        assert rule.is_recurring() is False

    def test_zero_meses_is_not_recurring(self) -> None:
        rule = PeriodicidadRule(
            codigo="Vacuna",
            especie="canina",
            periodicidad_meses=0,
        )
        assert rule.is_recurring() is False

    def test_positive_meses_is_recurring(self) -> None:
        rule = PeriodicidadRule(
            codigo="Vacuna Polivalente",
            especie="canina",
            periodicidad_meses=12,
        )
        assert rule.is_recurring() is True


class TestPeriodicidadRuleNextDueDate:
    """next_due_date() adds periodicidad_meses months correctly."""

    def test_simple_12_months(self) -> None:
        rule = PeriodicidadRule(
            codigo="Vacuna Polivalente",
            especie="canina",
            periodicidad_meses=12,
        )
        result = rule.next_due_date(date(2025, 3, 15))
        assert result == date(2026, 3, 15)

    def test_end_of_month_to_shorter_month(self) -> None:
        """Jan 31 + 1 month → Feb 28 (dateutil handles overflow correctly)."""
        rule = PeriodicidadRule(
            codigo="Desparasitación",
            especie="canina",
            periodicidad_meses=1,
        )
        result = rule.next_due_date(date(2025, 1, 31))
        assert result == date(2025, 2, 28)

    def test_cross_year(self) -> None:
        rule = PeriodicidadRule(
            codigo="Rabia",
            especie="felina",
            periodicidad_meses=12,
        )
        result = rule.next_due_date(date(2024, 6, 1))
        assert result == date(2025, 6, 1)

    def test_one_shot_raises(self) -> None:
        rule = PeriodicidadRule(
            codigo="Esterilización",
            especie="felina",
            periodicidad_meses=None,
        )
        with pytest.raises(ValueError, match="one-shot"):
            rule.next_due_date(date(2025, 5, 1))


# --- codigo_to_tipo_tarea --------------------------------------------------

class TestCodigoToTipoTarea:
    """codigo_to_tipo_tarea maps catalog codigos to TipoTarea values."""

    @pytest.mark.parametrize("codigo", ["Vacuna Polivalente", "vacuna polivalente", "RABIA"])
    def test_vacuna_maps_to_automatica_vacuna(self, codigo: str) -> None:
        assert codigo_to_tipo_tarea(codigo) == "automatica_vacuna"

    @pytest.mark.parametrize("codigo", ["Rabia", "rabia", "RABIA"])
    def test_rabia_maps_to_automatica_vacuna(self, codigo: str) -> None:
        assert codigo_to_tipo_tarea(codigo) == "automatica_vacuna"

    @pytest.mark.parametrize(
        "codigo", ["Desparasitación Interna", "Desparasitación Externa", "desparasitacion"]
    )
    def test_desparasitacion_maps_to_desparasitacion(self, codigo: str) -> None:
        assert codigo_to_tipo_tarea(codigo) == "automatica_desparasitacion"

    @pytest.mark.parametrize("codigo", ["Leishmaniosis", "Esterilización", "Otra prueba"])
    def test_other_maps_to_tratamiento(self, codigo: str) -> None:
        assert codigo_to_tipo_tarea(codigo) == "automatica_tratamiento"


# --- find_periodicity_rule --------------------------------------------------

CATALOG_FIXTURE: list[dict[str, Any]] = [
    {"codigo": "Vacuna Polivalente", "especie": "canina", "periodicidad_meses": 12, "nombre": "Vacuna Polivalente", "orden": 1},
    {"codigo": "Vacuna Polivalente", "especie": "felina", "periodicidad_meses": 12, "nombre": "Vacuna Polivalente", "orden": 6},
    {"codigo": "Rabia", "especie": "canina", "periodicidad_meses": 12, "nombre": "Rabia", "orden": 2},
    {"codigo": "Desparasitación Interna", "especie": "canina", "periodicidad_meses": 3, "nombre": "Desparasitación Interna", "orden": 4},
    {"codigo": "Esterilización", "especie": None, "periodicidad_meses": None, "nombre": "Esterilización", "orden": 8},
]


class TestFindPeriodicityRule:
    """find_periodicity_rule returns the most-specific matching rule."""

    def test_exact_especie_match(self) -> None:
        rule = find_periodicity_rule(CATALOG_FIXTURE, "Vacuna Polivalente", "canina")
        assert rule is not None
        assert rule.especie == "canina"
        assert rule.periodicidad_meses == 12

    def test_felino_exact_match(self) -> None:
        rule = find_periodicity_rule(CATALOG_FIXTURE, "Vacuna Polivalente", "felina")
        assert rule is not None
        assert rule.especie == "felina"
        assert rule.periodicidad_meses == 12

    def test_wildcard_fallback(self) -> None:
        """NULL especie matches any species (Esterilización applies to all)."""
        rule = find_periodicity_rule(CATALOG_FIXTURE, "Esterilización", "canina")
        assert rule is not None
        assert rule.especie is None
        assert rule.periodicidad_meses is None

    def test_unknown_codigo_returns_none(self) -> None:
        rule = find_periodicity_rule(CATALOG_FIXTURE, "Inexistente", "canina")
        assert rule is None

    def test_unknown_especie_no_wildcard(self) -> None:
        """Unknown especie does NOT fall back to wildcard unless codigo matches."""
        rule = find_periodicity_rule(CATALOG_FIXTURE, "Rabia", "ave")
        assert rule is None  # Rabia only exists for canina, no wildcard

    def test_case_insensitive_especie(self) -> None:
        rule = find_periodicity_rule(CATALOG_FIXTURE, "Vacuna Polivalente", "CANINA")
        assert rule is not None
        assert rule.especie == "canina"


# --- generate_next_tarea ---------------------------------------------------

class TestGenerateNextTarea:
    """generate_next_tarea builds the task-creation param dict."""

    def test_recurring_creates_task(self) -> None:
        rule = PeriodicidadRule(
            codigo="Vacuna Polivalente",
            especie="canina",
            periodicidad_meses=12,
        )
        params = generate_next_tarea(
            last_actuacion_date=date(2025, 6, 1),
            periodicidad_rule=rule,
            animal_id="animal-uuid",
            actuacion_id="actuacion-uuid",
        )
        assert params is not None
        assert params["tipo"] == "automatica_vacuna"
        assert params["origen"] == "regla_salud"
        assert params["vinculo_tipo"] == "actuacion_sanitaria"
        assert params["vinculo_id"] == "actuacion-uuid"
        assert params["vencimiento_at"] == "2026-06-01"
        assert params["metadata"]["codigo_prueba"] == "Vacuna Polivalente"
        assert params["metadata"]["periodicidad_meses"] == 12

    def test_one_shot_returns_none(self) -> None:
        rule = PeriodicidadRule(
            codigo="Esterilización",
            especie=None,
            periodicidad_meses=None,
        )
        params = generate_next_tarea(
            last_actuacion_date=date(2025, 6, 1),
            periodicidad_rule=rule,
            animal_id="animal-uuid",
            actuacion_id="actuacion-uuid",
        )
        assert params is None


# --- _priority_from_date ---------------------------------------------------

class TestPriorityFromDate:
    """_priority_from_date assigns urgency based on how overdue the task is."""

    def test_future_date_is_baja(self) -> None:
        future = date.today() + timedelta(days=30)
        assert _priority_from_date(future) == "baja"

    def test_same_week_is_baja(self) -> None:
        tomorrow = date.today() + timedelta(days=1)
        assert _priority_from_date(tomorrow) == "baja"

    def test_overdue_less_than_week_is_normal(self) -> None:
        yesterday = date.today() - timedelta(days=1)
        assert _priority_from_date(yesterday) == "normal"

    def test_overdue_more_than_week_is_alta(self) -> None:
        two_weeks = date.today() - timedelta(days=14)
        assert _priority_from_date(two_weeks) == "alta"

    def test_overdue_more_than_month_is_urgente(self) -> None:
        two_months = date.today() - timedelta(days=60)
        assert _priority_from_date(two_months) == "urgente"


# --- _fallback_add_months ---------------------------------------------------

class TestFallbackAddMonths:
    """_fallback_add_months is used when dateutil is unavailable."""

    def test_simple_add(self) -> None:
        result = _fallback_add_months(date(2025, 3, 15), 12)
        assert result == date(2026, 3, 15)

    def test_cross_year(self) -> None:
        result = _fallback_add_months(date(2024, 6, 1), 6)
        assert result == date(2024, 12, 1)

    def test_shorter_month_caps_at_last_day(self) -> None:
        """Fallback caps day at last day of shorter month (imperfect but safe)."""
        result = _fallback_add_months(date(2025, 1, 31), 1)
        # Fallback: month=1+1=2, day=min(31,28)=28
        assert result == date(2025, 2, 28)


# --- schedule_periodic_task error logging (issue #1069) ---------------------


class _SchedulingClient:
    """Fake executor answering the two catalog/animal SELECTs."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def execute_sql(self, query: str, params: object = None) -> list[dict[str, object]]:
        normalized = " ".join(query.split())
        self.calls.append(normalized)
        if "FROM catalogos_pruebas" in normalized:
            return [{"codigo": "VACUNA-RABIA"}]
        if "FROM animales" in normalized:
            return [{"especie": "CANINA"}]
        return []


def _actuacion(fecha: str) -> Any:
    return SimpleNamespace(
        id="act-1", animal_id="animal-1", tipo_actuacion_id="tipo-1", fecha=fecha
    )


_CATALOG = [
    {"codigo": "VACUNA-RABIA", "especie": "CANINA", "periodicidad_meses": 12}
]


class TestSchedulePeriodicTaskErrorLogging:
    """Issue #1069: the three non-fatal branches log the REAL exception
    type, never the ``"<class 'Exception'>"`` class string, and scheduling
    stays non-fatal."""

    def test_non_iso_fecha_logs_the_real_type(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.INFO, logger="app"):
            schedule_periodic_task(_SchedulingClient(), _actuacion("10/03/2026"), _CATALOG)

        records = [r for r in caplog.records if "compute_error" in r.getMessage()]
        assert records, "a bad fecha must emit sanidad.periodicity.compute_error"
        assert records[0]._caller_fields["error"] == "ValueError"
        assert "<class 'Exception'>" not in str(records[0].__dict__)

    def test_bad_rule_logs_the_real_type(self, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
        class _ExplodingRule:
            def is_recurring(self) -> bool:
                return True

            def next_due_date(self, last: date) -> date:
                raise ValueError("bad rule")

        monkeypatch.setattr(
            periodicity_module, "find_periodicity_rule", lambda *a, **k: _ExplodingRule()
        )
        with caplog.at_level(logging.INFO, logger="app"):
            schedule_periodic_task(_SchedulingClient(), _actuacion("2026-03-10"), _CATALOG)

        records = [r for r in caplog.records if "compute_error" in r.getMessage()]
        assert records, "a rule failure must emit sanidad.periodicity.compute_error"
        assert records[0]._caller_fields["error"] == "ValueError"
        assert "<class 'Exception'>" not in str(records[0].__dict__)

    def test_task_create_failure_logs_the_real_type_and_stays_non_fatal(
        self, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _explode(**kwargs: object) -> None:
            raise ValueError("forced task failure")

        monkeypatch.setattr("app.modules.tasks.crear_tarea", _explode)
        with caplog.at_level(logging.INFO, logger="app"):
            # Must NOT raise: the actuation was already committed.
            schedule_periodic_task(_SchedulingClient(), _actuacion("2026-03-10"), _CATALOG)

        records = [r for r in caplog.records if "task_create_error" in r.getMessage()]
        assert records, "a crear_tarea failure must emit task_create_error"
        assert records[0]._caller_fields["error"] == "ValueError"
        assert "<class 'Exception'>" not in str(records[0].__dict__)
