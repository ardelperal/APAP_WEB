"""Branch-complete unit tests for the CRAP-reduction helper seams."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException, status

from app.modules.animals.adapters.insforge.animals_insforge_adapter import (
    _search_total,
)
from app.modules.animals.adapters.insforge.animals_insforge_chip_cascade import (
    COMMIT_TX_SQL,
    ROLLBACK_TX_SQL,
    AnimalsInsforgeChipCascade,
    _require_different,
    _require_nonblank,
)
from app.modules.animals.adapters.insforge.animals_insforge_lifecycle import (
    _event_timestamp_value,
    _event_type_values,
    _require_event_row,
)
from app.modules.animals.adapters.insforge.animals_insforge_queries import (
    _append_search_filter,
    _exact_search_filter,
    _name_search_filter,
)
from app.modules.animals.adapters.insforge.animals_insforge_write_queries import (
    _update_pairs,
)
from app.modules.animals.domain.animal import Animal, Especie, Sexo
from app.modules.animals.domain.change_chip_result import ChangeChipResult
from app.modules.animals.domain.lifecycle_event import LifecycleEventType
from app.modules.animals.route_helpers import (
    _animal_update_kwargs,
    _chip_change_error_status,
    _chip_change_response,
    _chip_change_user_id,
    _execute_chip_change,
    _optional_animal_fields,
    _optional_domain_value,
    _require_animal,
)


class _SequencedClient:
    def __init__(self, responses: list[list[dict[str, object]] | Exception]) -> None:
        self._responses = iter(responses)
        self.calls: list[tuple[str, list[object] | None]] = []

    def execute_sql(
        self, query: str, params: list[object] | None = None
    ) -> list[dict[str, object]]:
        self.calls.append((query, params))
        response = next(self._responses)
        if isinstance(response, Exception):
            raise response
        return response


class _RoutePort:
    def __init__(self, animal: Animal | None) -> None:
        self.animal = animal
        self.change_calls: list[dict[str, str]] = []

    def get_animal_by_id(self, _animal_id: str) -> Animal | None:
        return self.animal

    def change_animal_chip(self, **kwargs: str) -> ChangeChipResult:
        self.change_calls.append(kwargs)
        return ChangeChipResult(
            success=True,
            old_chip=kwargs["old_chip"],
            new_chip=kwargs["new_chip"],
            updated_tables={"animals": 1},
        )


def _animal() -> Animal:
    return Animal(
        id="animal-1",
        NCHIP="old-chip",
        NombreAnimal="Luna",
        Especie=Especie.CANINA,
        Sexo=Sexo.H,
        FNacimiento="2024-01-01",
    )


@pytest.mark.parametrize(("rows", "expected"), [([], 0), ([{"total": "7"}], 7)])
def test_search_total_covers_empty_and_present_rows(
    rows: list[dict[str, object]], expected: int
) -> None:
    assert _search_total(rows) == expected


@pytest.mark.parametrize(("value", "name"), [("value", "field"), ("  ", "field")])
def test_require_nonblank_accepts_content_and_rejects_whitespace(
    value: str, name: str
) -> None:
    if value.strip():
        assert _require_nonblank(value, name) == value.strip()
    else:
        with pytest.raises(ValueError, match=name):
            _require_nonblank(value, name)


def test_require_different_accepts_distinct_and_rejects_equal_values() -> None:
    _require_different("new", "old", "new_chip")
    with pytest.raises(ValueError, match="new_chip"):
        _require_different("same", "same", "new_chip")


def test_chip_preflight_helpers_cover_duplicate_missing_mismatch_and_success() -> None:
    duplicate = AnimalsInsforgeChipCascade(_SequencedClient([[{"id": "other"}]]))
    result = duplicate._duplicate_chip_failure("animal-1", "old", "new")
    assert result is not None and result.success is False

    missing = AnimalsInsforgeChipCascade(_SequencedClient([[]]))
    result = missing._current_chip_failure("animal-1", "old", "new")
    assert result is not None and "no existe" in (result.error or "")

    mismatch = AnimalsInsforgeChipCascade(_SequencedClient([[{"NCHIP": "other"}]]))
    result = mismatch._current_chip_failure("animal-1", "old", "new")
    assert result is not None and "no coincide" in (result.error or "")

    matching = AnimalsInsforgeChipCascade(_SequencedClient([[{"NCHIP": "old"}]]))
    assert matching._current_chip_failure("animal-1", "old", "new") is None


def test_chip_preflight_stops_on_duplicate_and_continues_to_current_chip() -> None:
    duplicate_client = _SequencedClient([[{"id": "other"}]])
    duplicate = AnimalsInsforgeChipCascade(duplicate_client)
    assert duplicate._preflight("animal-1", "old", "new") is not None
    assert len(duplicate_client.calls) == 1

    valid = AnimalsInsforgeChipCascade(_SequencedClient([[], [{"NCHIP": "old"}]]))
    assert valid._preflight("animal-1", "old", "new") is None


def test_execute_updates_records_every_table_count() -> None:
    client = _SequencedClient(
        [[{"id": "a"}], [], [{"id": "c"}], [], [{"id": "s"}], []]
    )
    cascade = AnimalsInsforgeChipCascade(client)
    updated: dict[str, int] = {}
    assert cascade._execute_updates("animal-1", "old", "new", updated) == {
        "animals": 1,
        "entradas": 0,
        "acogidas": 1,
        "adopciones": 0,
        "actuaciones_sanitarias": 1,
        "terapias": 0,
    }


def test_rollback_error_covers_success_and_failure() -> None:
    success = AnimalsInsforgeChipCascade(_SequencedClient([[]]))
    assert success._rollback_error() is None

    failure = AnimalsInsforgeChipCascade(_SequencedClient([RuntimeError("offline")]))
    assert "offline" in (failure._rollback_error() or "")


def test_transaction_failure_formats_with_and_without_rollback_error() -> None:
    cascade = AnimalsInsforgeChipCascade(_SequencedClient([]))
    plain = cascade._build_failure(
        "old", "new", {}, RuntimeError("write failed"), None
    )
    rollback = cascade._build_failure(
        "old", "new", {}, RuntimeError("write failed"), "offline"
    )
    assert plain.error == "Error en la transaccion: write failed"
    assert rollback.error == (
        "Error en la transaccion: write failed; rollback fallo: offline"
    )


def test_execute_cascade_covers_commit_and_rollback_results() -> None:
    success_client = _SequencedClient(
        [[], [], [], [], [], [], [], [], []]
    )
    success = AnimalsInsforgeChipCascade(success_client)._execute_cascade(
        "animal-1", "old", "new", "reason", "operator"
    )
    assert success.success is True
    assert success_client.calls[-1][0] == COMMIT_TX_SQL

    failure_client = _SequencedClient([[], RuntimeError("write failed"), []])
    failure = AnimalsInsforgeChipCascade(failure_client)._execute_cascade(
        "animal-1", "old", "new", "reason", "operator"
    )
    assert failure.success is False
    assert failure_client.calls[-1][0] == ROLLBACK_TX_SQL


def test_event_type_values_covers_absent_and_present_filters() -> None:
    assert _event_type_values(None) is None
    assert _event_type_values([]) is None
    assert _event_type_values([LifecycleEventType.CHIP_CHANGED]) == ["CHIP_CHANGED"]


def test_event_timestamp_value_covers_datetime_and_string() -> None:
    timestamp = datetime(2026, 8, 28, 10, 30, tzinfo=UTC)
    assert _event_timestamp_value(timestamp) == timestamp.isoformat()
    assert _event_timestamp_value("2026-08-28T10:30:00Z") == "2026-08-28T10:30:00Z"


def test_require_event_row_returns_first_row_and_rejects_empty_result() -> None:
    row = {"id": "event-1"}
    assert _require_event_row([row]) is row
    with pytest.raises(RuntimeError, match="RETURNING produced no rows"):
        _require_event_row([])


def test_exact_search_filter_covers_absent_and_present_values() -> None:
    assert _exact_search_filter('a."Sexo" =', None) is None
    assert _exact_search_filter('a."Sexo" =', "H") == ('a."Sexo" =', "H")


def test_name_search_filter_covers_absent_and_present_values() -> None:
    assert _name_search_filter(None) is None
    assert _name_search_filter("Luna") == ('a."NombreAnimal" ILIKE', "%Luna%")


def test_append_search_filter_covers_absent_and_present_filters() -> None:
    conditions = ["a.activo = TRUE"]
    params: list[object] = []
    _append_search_filter(conditions, params, None)
    _append_search_filter(conditions, params, ('a."Especie" =', "CANINA"))
    assert conditions == ["a.activo = TRUE", 'a."Especie" = $1']
    assert params == ["CANINA"]


def test_update_pairs_omits_none_and_preserves_canonical_order() -> None:
    assert _update_pairs(
        {"Sexo": "H", "NombreAnimal": "Luna", "Especie": None}
    ) == [("NombreAnimal", "Luna"), ("Sexo", "H")]


def test_optional_animal_fields_excludes_core_fields() -> None:
    assert _optional_animal_fields({"NombreAnimal": "Luna", "Raza": "Mestiza"}) == {
        "Raza": "Mestiza"
    }


def test_optional_domain_value_covers_absent_and_present_values() -> None:
    assert _optional_domain_value({}, "Especie", Especie) is None
    assert _optional_domain_value({"Especie": "FELINA"}, "Especie", Especie) is Especie.FELINA


def test_animal_update_kwargs_builds_typed_core_and_optional_fields() -> None:
    kwargs = _animal_update_kwargs(
        {
            "NombreAnimal": "Luna",
            "Especie": "CANINA",
            "Sexo": "H",
            "FNacimiento": "2024-01-01",
            "Raza": "Mestiza",
        }
    )
    assert kwargs == {
        "nombre": "Luna",
        "especie": Especie.CANINA,
        "sexo": Sexo.H,
        "fnacimiento": "2024-01-01",
        "Raza": "Mestiza",
    }


def test_chip_change_user_id_covers_dict_and_response_shapes() -> None:
    assert _chip_change_user_id({"user_id": "operator"}) == "operator"
    assert _chip_change_user_id(object()) == ""


def test_require_animal_returns_row_and_raises_for_missing_id() -> None:
    animal = _animal()
    assert _require_animal(_RoutePort(animal), "animal-1") is animal  # type: ignore[arg-type]
    with pytest.raises(HTTPException) as exc_info:
        _require_animal(_RoutePort(None), "missing")  # type: ignore[arg-type]
    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


def test_execute_chip_change_builds_complete_port_command() -> None:
    port = _RoutePort(_animal())
    result = _execute_chip_change(
        port,  # type: ignore[arg-type]
        "animal-1",
        "new-chip",
        "replacement",
        {"user_id": "operator"},
    )
    assert result.success is True
    assert port.change_calls == [{
        "animal_id": "animal-1",
        "old_chip": "old-chip",
        "new_chip": "new-chip",
        "reason": "replacement",
        "operador_user_id": "operator",
    }]


def test_chip_change_response_covers_success_conflict_and_validation_error() -> None:
    success = ChangeChipResult(
        success=True,
        old_chip="old",
        new_chip="new",
        updated_tables={"animals": 1},
    )
    assert _chip_change_response(success) == {
        "success": True,
        "old_chip": "old",
        "new_chip": "new",
        "updated_tables": {"animals": 1},
    }

    with pytest.raises(HTTPException) as conflict:
        _chip_change_response(ChangeChipResult(False, "old", "new", error="ya está asignado"))
    assert conflict.value.status_code == status.HTTP_409_CONFLICT

    with pytest.raises(HTTPException) as invalid:
        _chip_change_response(ChangeChipResult(False, "old", "new", error="invalid"))
    assert invalid.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_chip_change_error_status_covers_conflict_and_validation_messages() -> None:
    assert _chip_change_error_status("ya esta asignado") == status.HTTP_409_CONFLICT
    assert _chip_change_error_status("ya está asignado") == status.HTTP_409_CONFLICT
    assert _chip_change_error_status(None) == status.HTTP_422_UNPROCESSABLE_CONTENT
