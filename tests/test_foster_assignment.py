"""Service-layer tests for FOSTER-03 foster assignment gate.

The ``foster.assignment`` module owns:

- :func:`evaluate_assignment`: gate de especie (hard block) + capacity
  advisory. Decision in {admit, block, admit_with_warning}.
- :func:`record_override`: graba override con motivo obligatorio
  (raise ``ValueError`` si motivo vacío). Audit log via ``log_safe``.
- :func:`list_overrides_for_casa`: lista overrides de una casa
  ordenadas ``created_at DESC``.

Mirror of the ``tests/test_foster.py`` and ``tests/test_acogidas.py``
patterns: real InsForgeClient + httpx.MockTransport for SQL shape
assertion. Each test records the SQL queries captured and asserts
the shape; the assertions fail loudly if a future refactor breaks
the contract.

Coverage (24 atoms):

1.  evaluate_assignment happy path admit (especie OK + capacidad OK)
2.  evaluate_assignment species mismatch (CANINA animal, FELINA casa) -> block
3.  evaluate_assignment casa sin especie_preferente acepta cualquier especie -> admit
4.  evaluate_assignment capacidad OK (count < capacidad) -> admit
5.  evaluate_assignment capacidad al límite (count == capacidad) -> admit_with_warning
6.  evaluate_assignment capacidad excedida (count > capacidad) -> admit_with_warning
7.  evaluate_assignment animal no existe -> raise ValueError
8.  evaluate_assignment animal inactivo -> raise ValueError
9.  evaluate_assignment casa no existe -> raise ValueError
10. evaluate_assignment casa inactiva -> raise ValueError
11. evaluate_assignment count solo estancias de la especie preferida (no mezcla)
12. evaluate_assignment casa cualquier-especie cuenta TODAS las estancias
13. evaluate_assignment no cuenta estancia cerrada (fecha_final populated)
14. evaluate_assignment no cuenta estancia soft-deleted (activo = false)
15. evaluate_assignment no cuenta estancias de OTRAS casas
16. evaluate_assignment block_reason incluye especie_preferente y animal.especie
17. record_override happy -> INSERT + retorna dataclass
18. record_override motivo vacío -> raise ValueError, NO INSERT
19. record_override motivo whitespace -> raise ValueError, NO INSERT
20. record_override emite log_safe con operador
21. record_override log_safe NO incluye motivo (PII)
22. list_overrides_for_casa ordena por created_at DESC
23. list_overrides_for_casa sin overrides -> lista vacía
24. list_overrides_for_casa no incluye overrides de otras casas
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.core.insforge import InsForgeClient
from app.modules.foster import assignment as assignment_service


def _json_response(status_code: int, body: Any) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        content=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json"},
    )


def _client_recording(
    handler: Callable[[httpx.Request, dict[str, Any]], httpx.Response],
) -> tuple[InsForgeClient, list[dict[str, Any]]]:
    captured: list[dict[str, Any]] = []

    def _recording_handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization", "").startswith("Bearer ")
        body = json.loads(request.content.decode("utf-8")) if request.content else {}
        captured.append(body)
        return handler(request, body)

    client = InsForgeClient(
        base_url="https://example.insforge.app",
        service_key="ik_test",
        transport=httpx.MockTransport(_recording_handler),
    )
    return client, captured


# --- fixtures: animal + casa + estancia -----------------------------------


ANIMAL_ID = "11111111-1111-1111-1111-111111111111"
CASA_ID = "22222222-2222-2222-2222-222222222222"


def _animal_row(especie: str = "CANINA", activo: bool = True) -> dict[str, Any]:
    return {
        "id": ANIMAL_ID,
        "NCHIP": "985112004409871",
        "NombreAnimal": "Luna",
        "Especie": especie,
        "Sexo": "H",
        "FNacimiento": "2023-04-12",
        "Terapia": "",
        "activo": activo,
        "TraeNChip": None,
        "FIMPLANTACIONCHIP": None,
        "Raza": None,
        "Color": None,
        "Pelo": None,
        "Tamano": None,
        "Caracter": None,
        "FDefuncion": None,
        "Observaciones": None,
        "NombreFoto": None,
        "Cartilla": None,
        "Eutanasia": None,
        "RazaPPP": None,
        "Mestizo": None,
        "EutanasiaOtrasCausas": None,
        "EutanasiaEnfermedad": None,
        "UltimoEstadoAntesDeFallecido": None,
        "ComunicacionARIAC": None,
        "fecha_alta": "2026-07-04T10:00:00Z",
        "updated_at": "2026-07-04T10:00:00Z",
    }


def _casa_row(
    especie_preferente: str | None = "CANINA",
    capacidad: int = 2,
    activo: bool = True,
) -> dict[str, Any]:
    return {
        "id": CASA_ID,
        "nombre": "María",
        "apellidos": "García",
        "calle": "Calle Mayor",
        "telefono": "600123456",
        "coche": "Sí",
        "capacidad": capacidad,
        "especie_preferente": especie_preferente,
        "activo": activo,
        # Other CasaAcogida columns — not relevant for these tests.
        "dni_acogedor": None,
        "numero": None,
        "piso": None,
        "letra": None,
        "localidad": None,
        "provincia": None,
        "cp": None,
        "telefono2": None,
        "email": None,
        "vinculacion": None,
        "caracteristicas": None,
        "observaciones": None,
        "fecha_alta": "2026-07-04T10:00:00Z",
        "fecha_baja": None,
        "updated_at": "2026-07-04T10:00:00Z",
    }


def _make_handler(
    *,
    animal: dict[str, Any] | None = None,
    casa: dict[str, Any] | None = None,
    active_count: int = 0,
) -> Callable[[httpx.Request, dict[str, Any]], httpx.Response]:
    """Build a handler that responds to the SQL shapes evaluate_assignment emits.

    Order in evaluate_assignment:
      1. SELECT FROM animales WHERE id = $1  (animals_service.get_animal_by_id)
      2. SELECT FROM casas_acogida WHERE id = $1  (foster_service.get_casa_acogida_by_id)
      3. SELECT COUNT(*) JOIN acogidas JOIN animales WHERE casa_acogida_id = $1 ...

    NB: the COUNT query contains ``FROM animales`` (via JOIN) so the
    pattern matching has to discriminate by ``SELECT COUNT(*)`` first.
    """
    animal_row = animal if animal is not None else _animal_row()

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        q = body["query"]
        # 3. Active count for capacity check (MUST come before the
        # animal check because the COUNT query also references
        # ``animales`` via the JOIN).
        if "SELECT COUNT(*) AS active_count" in q:
            return _json_response(200, [{"active_count": active_count}])
        # 1. Animal lookup
        if "FROM animales" in q and "WHERE id = $1" in q:
            return _json_response(200, [animal_row])
        # 2. Casa lookup
        if "FROM casas_acogida" in q and "WHERE id = $1" in q:
            return _json_response(200, [casa] if casa is not None else [])
        # INSERT override
        if "INSERT INTO foster_capacity_overrides" in q:
            return _json_response(
                200,
                [
                    {
                        "id": "99999999-9999-9999-9999-999999999999",
                        "casa_acogida_id": body["params"][0],
                        "animal_id": body["params"][1],
                        "operador_user_id": body["params"][2],
                        "motivo": body["params"][3],
                        "created_at": "2026-07-04T11:00:00Z",
                    }
                ],
            )
        # LIST overrides
        if "FROM foster_capacity_overrides" in q:
            return _json_response(200, [])
        raise AssertionError(f"unexpected SQL: {q!r}")

    return _handler


# --- 1. evaluate_assignment: happy path admit ------------------------------


def test_evaluate_assignment_admit_when_especie_matches_and_capacity_ok() -> None:
    """Animal CANINA + casa FELINA-cap 2 + 0 estancias activas -> admit."""
    client, captured = _client_recording(
        _make_handler(animal=_animal_row("FELINA"), casa=_casa_row("FELINA", 2), active_count=0)
    )

    decision = assignment_service.evaluate_assignment(client, ANIMAL_ID, CASA_ID)
    client.close()

    assert decision.decision == "admit"
    assert decision.reason is None
    assert decision.warnings == ()


# --- 2. evaluate_assignment: species mismatch block ------------------------


def test_evaluate_assignment_species_mismatch_returns_block() -> None:
    """Animal CANINA + casa FELINA -> block con reason claro."""
    client, captured = _client_recording(
        _make_handler(animal=_animal_row("CANINA"), casa=_casa_row("FELINA", 2), active_count=0)
    )

    decision = assignment_service.evaluate_assignment(client, ANIMAL_ID, CASA_ID)
    client.close()

    assert decision.decision == "block"
    assert decision.reason is not None
    assert "FELINA" in decision.reason
    assert "CANINA" in decision.reason
    assert decision.warnings == ()


# --- 3. evaluate_assignment: casa sin especie_preferente admite cualquier -


def test_evaluate_assignment_casa_cualquier_especie_admite_cualquier_animal() -> None:
    """Casa con especie_preferente NULL acepta cualquier especie."""
    client, captured = _client_recording(
        _make_handler(
            animal=_animal_row("FELINA"),
            casa=_casa_row(especie_preferente=None, capacidad=2),
            active_count=0,
        )
    )

    decision = assignment_service.evaluate_assignment(client, ANIMAL_ID, CASA_ID)
    client.close()

    assert decision.decision == "admit"


# --- 4. evaluate_assignment: capacidad OK ----------------------------------


def test_evaluate_assignment_admit_when_capacity_under_limit() -> None:
    """Capacidad 3 + 1 estancia activa -> admit (count < cap)."""
    client, captured = _client_recording(
        _make_handler(
            animal=_animal_row("FELINA"),
            casa=_casa_row("FELINA", 3),
            active_count=1,
        )
    )

    decision = assignment_service.evaluate_assignment(client, ANIMAL_ID, CASA_ID)
    client.close()

    assert decision.decision == "admit"


# --- 5. evaluate_assignment: capacidad al límite ---------------------------


def test_evaluate_assignment_admit_with_warning_when_capacity_at_limit() -> None:
    """Capacidad 2 + 2 estancias activas -> admit_with_warning."""
    client, captured = _client_recording(
        _make_handler(
            animal=_animal_row("FELINA"),
            casa=_casa_row("FELINA", 2),
            active_count=2,
        )
    )

    decision = assignment_service.evaluate_assignment(client, ANIMAL_ID, CASA_ID)
    client.close()

    assert decision.decision == "admit_with_warning"
    assert decision.reason is None
    assert len(decision.warnings) == 1
    assert "capacidad excedida: 2/2" in decision.warnings[0]


# --- 6. evaluate_assignment: capacidad excedida ---------------------------


def test_evaluate_assignment_admit_with_warning_when_capacity_exceeded() -> None:
    """Capacidad 2 + 3 estancias activas -> admit_with_warning con 3/2."""
    client, captured = _client_recording(
        _make_handler(
            animal=_animal_row("FELINA"),
            casa=_casa_row("FELINA", 2),
            active_count=3,
        )
    )

    decision = assignment_service.evaluate_assignment(client, ANIMAL_ID, CASA_ID)
    client.close()

    assert decision.decision == "admit_with_warning"
    assert "3/2" in decision.warnings[0]


# --- 7. evaluate_assignment: animal no existe ------------------------------


def test_evaluate_assignment_animal_not_found_raises_value_error() -> None:
    """get_animal_by_id returns None -> raise ValueError."""

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        if "FROM animales" in body["query"] and "WHERE id = $1" in body["query"]:
            return _json_response(200, [])  # empty = no row
        raise AssertionError(f"unexpected SQL: {body['query']!r}")

    client, captured = _client_recording(_handler)

    with pytest.raises(ValueError, match="animal"):
        assignment_service.evaluate_assignment(client, ANIMAL_ID, CASA_ID)
    client.close()


# --- 8. evaluate_assignment: animal inactivo -------------------------------


def test_evaluate_assignment_animal_inactive_raises_value_error() -> None:
    """get_animal_by_id returns animal with activo=false -> raise."""
    client, captured = _client_recording(
        _make_handler(animal=_animal_row("CANINA", activo=False))
    )

    with pytest.raises(ValueError, match="animal"):
        assignment_service.evaluate_assignment(client, ANIMAL_ID, CASA_ID)
    client.close()


# --- 9. evaluate_assignment: casa no existe --------------------------------


def test_evaluate_assignment_casa_not_found_raises_value_error() -> None:
    """get_casa_acogida_by_id returns None -> raise ValueError."""
    client, captured = _client_recording(_make_handler(casa=None))

    with pytest.raises(ValueError, match="casa"):
        assignment_service.evaluate_assignment(client, ANIMAL_ID, CASA_ID)
    client.close()


# --- 10. evaluate_assignment: casa inactiva -------------------------------


def test_evaluate_assignment_casa_inactive_raises_value_error() -> None:
    """casa con activo=false -> raise con mensaje 'dada de baja'."""
    client, captured = _client_recording(
        _make_handler(casa=_casa_row("CANINA", 2, activo=False))
    )

    with pytest.raises(ValueError, match="dada de baja"):
        assignment_service.evaluate_assignment(client, ANIMAL_ID, CASA_ID)
    client.close()


# --- 11. evaluate_assignment: count solo especie preferida ----------------


def test_evaluate_assignment_count_only_preferred_species() -> None:
    """El SQL filtra por especie preferida — el mock devuelve 0 porque la
    consulta ya filtra. La verificación clave: el servicio pasa el
    ``casa_id`` al SELECT y compara contra la ``capacidad`` retornada
    por el mock, sin importar qué más haya en la DB.
    """
    client, captured = _client_recording(
        _make_handler(
            animal=_animal_row("FELINA"),
            casa=_casa_row("FELINA", 5),
            active_count=0,  # count=0 porque JOIN filtra por especie
        )
    )

    decision = assignment_service.evaluate_assignment(client, ANIMAL_ID, CASA_ID)
    client.close()

    assert decision.decision == "admit"
    # El SELECT COUNT lleva el casa_id como parametro.
    count_query = next(
        c for c in captured if "SELECT COUNT(*) AS active_count" in c["query"]
    )
    assert count_query["params"] == [CASA_ID]


# --- 12. evaluate_assignment: casa cualquier-especie cuenta todas ---------


def test_evaluate_assignment_cualquier_especie_counts_all() -> None:
    """Casa con especie_preferente NULL — el JOIN no filtra por especie."""
    client, captured = _client_recording(
        _make_handler(
            animal=_animal_row("FELINA"),
            casa=_casa_row(especie_preferente=None, capacidad=1),
            active_count=1,  # count=1: cualquier especie cuenta
        )
    )

    decision = assignment_service.evaluate_assignment(client, ANIMAL_ID, CASA_ID)
    client.close()

    assert decision.decision == "admit_with_warning"
    assert "1/1" in decision.warnings[0]


# --- 13. evaluate_assignment: no cuenta estancia cerrada ------------------


def test_evaluate_assignment_no_cuenta_estancia_cerrada_es_filtro_sql() -> None:
    """El filtro ``fecha_final IS NULL AND activo = true`` vive en el SQL.
    El mock no necesita devolver filas: si la consulta retorna count=0,
    la verificación es que el WHERE del SQL incluye ambos predicados.
    """
    client, captured = _client_recording(
        _make_handler(
            animal=_animal_row("FELINA"),
            casa=_casa_row("FELINA", 3),
            active_count=0,
        )
    )

    assignment_service.evaluate_assignment(client, ANIMAL_ID, CASA_ID)
    client.close()

    count_query = next(
        c for c in captured if "SELECT COUNT(*) AS active_count" in c["query"]
    )
    assert "fecha_final IS NULL" in count_query["query"]
    assert "a.activo = true" in count_query["query"]


# --- 14. evaluate_assignment: no cuenta estancia soft-deleted -------------


def test_evaluate_assignment_no_cuenta_estancia_soft_deleted_es_filtro_sql() -> None:
    """Mismo WHERE que test 13 — verifica el predicado activo=true."""
    client, captured = _client_recording(
        _make_handler(
            animal=_animal_row("FELINA"),
            casa=_casa_row("FELINA", 3),
            active_count=0,
        )
    )

    assignment_service.evaluate_assignment(client, ANIMAL_ID, CASA_ID)
    client.close()

    count_query = next(
        c for c in captured if "SELECT COUNT(*) AS active_count" in c["query"]
    )
    assert "a.activo = true" in count_query["query"]


# --- 15. evaluate_assignment: no cuenta estancias de otras casas ---------


def test_evaluate_assignment_no_cuenta_estancias_de_otras_casas_es_filtro_sql() -> None:
    """El WHERE filtra por ``casa_acogida_id = $1``."""
    client, captured = _client_recording(
        _make_handler(
            animal=_animal_row("FELINA"),
            casa=_casa_row("FELINA", 3),
            active_count=0,
        )
    )

    assignment_service.evaluate_assignment(client, ANIMAL_ID, CASA_ID)
    client.close()

    count_query = next(
        c for c in captured if "SELECT COUNT(*) AS active_count" in c["query"]
    )
    assert "a.casa_acogida_id = $1" in count_query["query"]


# --- 16. evaluate_assignment: block reason incluye especie y animal -------


def test_evaluate_assignment_block_reason_includes_both_especies() -> None:
    """El reason del block DEBE mencionar ambas especies para diagnóstico."""
    client, captured = _client_recording(
        _make_handler(
            animal=_animal_row("CANINA"), casa=_casa_row("FELINA", 2), active_count=0
        )
    )

    decision = assignment_service.evaluate_assignment(client, ANIMAL_ID, CASA_ID)
    client.close()

    assert decision.decision == "block"
    assert decision.reason is not None
    # Formato esperado: "la casa solo admite FELINA, no CANINA"
    assert "FELINA" in decision.reason
    assert "CANINA" in decision.reason
    assert "la casa" in decision.reason.lower()


# --- 17. record_override: happy path --------------------------------------


def test_record_override_happy_inserts_and_returns_dataclass() -> None:
    """Override con motivo válido -> INSERT + retorna FosterCapacityOverride."""
    client, captured = _client_recording(_make_handler())

    override = assignment_service.record_override(
        client,
        casa_id=CASA_ID,
        animal_id=ANIMAL_ID,
        operador_user_id="op-1",
        motivo="emergencia",
    )
    client.close()

    assert isinstance(override, assignment_service.FosterCapacityOverride)
    assert override.id == "99999999-9999-9999-9999-999999999999"
    assert override.casa_acogida_id == CASA_ID
    assert override.animal_id == ANIMAL_ID
    assert override.operador_user_id == "op-1"
    assert override.motivo == "emergencia"
    assert override.created_at == "2026-07-04T11:00:00Z"

    insert = next(c for c in captured if "INSERT INTO foster_capacity_overrides" in c["query"])
    assert insert["params"] == [CASA_ID, ANIMAL_ID, "op-1", "emergencia"]


# --- 18. record_override: motivo vacío raise -----------------------------


def test_record_override_motivo_vacio_raises_value_error_no_sql() -> None:
    """motivo='' -> raise ValueError, NO INSERT (defensa SQL)."""
    client, captured = _client_recording(_make_handler())

    with pytest.raises(ValueError, match="motivo"):
        assignment_service.record_override(
            client,
            casa_id=CASA_ID,
            animal_id=ANIMAL_ID,
            operador_user_id="op-1",
            motivo="",
        )
    client.close()

    insert_calls = [c for c in captured if "INSERT INTO foster_capacity_overrides" in c["query"]]
    assert insert_calls == [], "INSERT must not run when motivo is empty"


# --- 19. record_override: motivo whitespace raise -------------------------


def test_record_override_motivo_whitespace_raises_value_error_no_sql() -> None:
    """motivo='   ' -> raise ValueError, NO INSERT."""
    client, captured = _client_recording(_make_handler())

    with pytest.raises(ValueError, match="motivo"):
        assignment_service.record_override(
            client,
            casa_id=CASA_ID,
            animal_id=ANIMAL_ID,
            operador_user_id="op-1",
            motivo="   ",
        )
    client.close()

    insert_calls = [c for c in captured if "INSERT INTO foster_capacity_overrides" in c["query"]]
    assert insert_calls == [], "INSERT must not run when motivo is only whitespace"


# --- 20. record_override: emite log_safe con operador ---------------------


def test_record_override_emits_log_safe_with_operador(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """log_safe('foster.capacity_override.recorded', ...) se emite."""
    captured_log: list[dict[str, Any]] = []

    def _capture(event: str, **fields: Any) -> None:
        captured_log.append({"event": event, **fields})

    monkeypatch.setattr("app.modules.foster.assignment.log_safe", _capture)

    client, _captured = _client_recording(_make_handler())
    assignment_service.record_override(
        client,
        casa_id=CASA_ID,
        animal_id=ANIMAL_ID,
        operador_user_id="op-1",
        motivo="emergencia",
    )
    client.close()

    assert len(captured_log) == 1
    entry = captured_log[0]
    assert entry["event"] == "foster.capacity_override.recorded"
    assert entry["casa_acogida_id"] == CASA_ID
    assert entry["animal_id"] == ANIMAL_ID
    assert entry["operador"] == "op-1"


# --- 21. record_override: log NO incluye motivo (PII) --------------------


def test_record_override_log_does_not_include_motivo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El motivo es texto libre del operador (puede llevar PII) — no se loguea."""
    captured_log: list[dict[str, Any]] = []

    def _capture(event: str, **fields: Any) -> None:
        captured_log.append({"event": event, **fields})

    monkeypatch.setattr("app.modules.foster.assignment.log_safe", _capture)

    client, _captured = _client_recording(_make_handler())
    assignment_service.record_override(
        client,
        casa_id=CASA_ID,
        animal_id=ANIMAL_ID,
        operador_user_id="op-1",
        motivo="Juan me llamó por teléfono 600000000",
    )
    client.close()

    entry = captured_log[0]
    assert "motivo" not in entry, (
        f"motivo must NOT be logged (PII risk); got log entry: {entry}"
    )


# --- 22. list_overrides_for_casa: ordenado DESC --------------------------


def _override_row(
    id_: str,
    created_at: str,
    motivo: str = "caso urgente",
) -> dict[str, Any]:
    return {
        "id": id_,
        "casa_acogida_id": CASA_ID,
        "animal_id": ANIMAL_ID,
        "operador_user_id": "op-1",
        "motivo": motivo,
        "created_at": created_at,
    }


def test_list_overrides_for_casa_ordenados_por_created_at_desc() -> None:
    """3 overrides con timestamps distintos -> lista ordenada DESC."""
    rows = [
        _override_row("a", "2026-07-04T11:00:00Z"),
        _override_row("b", "2026-07-04T10:00:00Z"),
        _override_row("c", "2026-07-04T12:00:00Z"),
    ]

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        if "FROM foster_capacity_overrides" in body["query"]:
            return _json_response(200, rows)
        raise AssertionError(f"unexpected SQL: {body['query']!r}")

    client, captured = _client_recording(_handler)
    overrides = assignment_service.list_overrides_for_casa(client, CASA_ID)
    client.close()

    assert [o.id for o in overrides] == ["a", "b", "c"]
    # El SQL debe pedir ORDER BY created_at DESC (no asume el caller).
    list_query = next(
        c for c in captured if "FROM foster_capacity_overrides" in c["query"]
    )
    assert "ORDER BY created_at DESC" in list_query["query"]


# --- 23. list_overrides_for_casa: lista vacía ----------------------------


def test_list_overrides_for_casa_sin_overrides_retorna_lista_vacia() -> None:
    """Sin overrides -> [] (PostgreSQL retorna [], no error)."""

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        if "FROM foster_capacity_overrides" in body["query"]:
            return _json_response(200, [])
        raise AssertionError(f"unexpected SQL: {body['query']!r}")

    client, _captured = _client_recording(_handler)
    overrides = assignment_service.list_overrides_for_casa(client, CASA_ID)
    client.close()

    assert overrides == []


# --- 24. list_overrides_for_casa: no incluye otras casas -----------------


def test_list_overrides_for_casa_filtra_por_casa_id() -> None:
    """El SQL filtra por ``casa_acogida_id = $1`` — el caller no lo hace."""
    captured_calls: list[list[Any]] = []

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        if "FROM foster_capacity_overrides" in body["query"]:
            captured_calls.append(body["params"])
            return _json_response(200, [])
        raise AssertionError(f"unexpected SQL: {body['query']!r}")

    client, _captured = _client_recording(_handler)
    assignment_service.list_overrides_for_casa(client, CASA_ID)
    client.close()

    assert captured_calls == [[CASA_ID]]
