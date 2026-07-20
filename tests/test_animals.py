"""Tests del service layer de animales (TDD estricto).

El service es la unica capa que habla con ``InsForgeClient`` para
animales. Lo ejercitamos con un ``InsForgeClient`` real conectado a
``httpx.MockTransport`` para capturar SQL y params sin red.

El contrato es: ``create_animal`` valida campos antes de SQL y devuelve
``Animal``; ``list_animals`` devuelve activos ordenados por fecha_alta
DESC; ``get_animal_by_id`` devuelve el animal o ``None``; ``update_animal``
hace ``UPDATE … WHERE id = $1 RETURNING …`` con la misma validacion
que create y ``delete_animal`` hace soft-delete (``activo = false``).
NCHIP duplicado propaga el ``InsForgeError`` de InsForge sin cambios.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.core.insforge import InsForgeClient, InsForgeError
from app.modules.animals.forms import ANIMAL_FORM_REQUIRED_FIELDS
from app.modules.animals.service import (
    Especie,
    Sexo,
    create_animal,
    delete_animal,
    get_animal_by_id,
    list_animals,
    update_animal,
)

# --- helpers --------------------------------------------------------------


def _json_response(status_code: int, body: Any) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        content=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json"},
    )


def _client_recording(handler) -> tuple[InsForgeClient, list[dict[str, Any]]]:
    """Cliente cuyo MockTransport registra cada body JSON enviado."""
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


def _params_minimal() -> dict[str, Any]:
    """Parametros validos para el happy path.

    Tras #129 (paridad Access + discovery), son 9 obligatorios: los 5
    originales (Access ``TbFichaAnimal.Required=True`` NCHIP/NombreAnimal/
    Especie/Sexo/FNacimiento) + los 4 de discovery (Terapia, TraeNChip,
    FIMPLANTACIONCHIP, NombreFoto). Ver ``ANIMAL_FORM_REQUIRED_FIELDS``
    en ``app/modules/animals/forms.py``.
    """
    return {
        # Access TbFichaAnimal.Required=True
        "NCHIP": "985112004409871",
        "NombreAnimal": "Luna",
        "Especie": "CANINA",
        "Sexo": "H",
        "FNacimiento": "2023-04-12",
        # Discovery feature-01-animal-lifecycle.md
        "Terapia": "No",
        "TraeNChip": "Si",
        "FIMPLANTACIONCHIP": "2023-04-15",
        "NombreFoto": "luna-2023.jpg",
    }


# --- create_animal --------------------------------------------------------


def test_create_animal_ejecuta_insert_con_parametros_esperados() -> None:
    """El INSERT contiene los 5 campos obligatorios en el orden correcto."""
    returned = {
        "id": "11111111-1111-1111-1111-111111111111",
        "NCHIP": "985112004409871",
        "NombreAnimal": "Luna",
        "Especie": "CANINA",
        "Sexo": "H",
        "FNacimiento": "2023-04-12",
        "activo": True,
    }

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        return _json_response(200, [returned])

    client, captured = _client_recording(_handler)
    result = create_animal(client, _params_minimal())
    client.close()

    assert result.id == returned["id"]
    assert result.NCHIP == "985112004409871"
    assert result.NombreAnimal == "Luna"
    assert result.Especie is Especie.CANINA
    assert result.Sexo is Sexo.H

    assert len(captured) == 1
    query = captured[0]["query"]
    assert "INSERT INTO animales" in query
    assert "RETURNING" in query
    params = captured[0]["params"]
    assert params[0] == "985112004409871"
    assert params[1] == "Luna"
    assert params[2] == "CANINA"
    assert params[3] == "H"
    assert params[4] == "2023-04-12"


def test_create_animal_rechaza_Especie_invalida_antes_de_sql() -> None:
    client, captured = _client_recording(lambda req, body: _json_response(200, []))

    with pytest.raises(ValueError, match="Especie"):
        create_animal(client, {**_params_minimal(), "Especie": "REPTIL"})
    client.close()

    assert captured == [], "no se debe emitir SQL si la validacion falla"


def test_create_animal_rechaza_Sexo_invalido_antes_de_sql() -> None:
    client, captured = _client_recording(lambda req, body: _json_response(200, []))

    with pytest.raises(ValueError, match="Sexo"):
        create_animal(client, {**_params_minimal(), "Sexo": "X"})
    client.close()

    assert captured == []


def test_create_animal_rechaza_NCHIP_vacio() -> None:
    client, captured = _client_recording(lambda req, body: _json_response(200, []))

    with pytest.raises(ValueError, match="NCHIP"):
        create_animal(client, {**_params_minimal(), "NCHIP": "   "})
    client.close()

    assert captured == []


def test_create_animal_rechaza_NombreAnimal_vacio() -> None:
    client, captured = _client_recording(lambda req, body: _json_response(200, []))

    with pytest.raises(ValueError, match="NombreAnimal"):
        create_animal(client, {**_params_minimal(), "NombreAnimal": ""})
    client.close()

    assert captured == []


def test_create_animal_rechaza_FNacimiento_vacio() -> None:
    client, captured = _client_recording(lambda req, body: _json_response(200, []))

    with pytest.raises(ValueError, match="FNacimiento"):
        create_animal(client, {**_params_minimal(), "FNacimiento": ""})
    client.close()

    assert captured == []


def test_create_animal_propag_InsForgeError_en_NCHIP_duplicado() -> None:
    """Un 409 de InsForge (NCHIP duplicado) propaga el InsForgeError tal cual."""

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        return _json_response(
            409, {"error": "duplicate key value violates unique constraint"}
        )

    client, _ = _client_recording(_handler)

    with pytest.raises(InsForgeError) as exc:
        create_animal(client, _params_minimal())
    client.close()

    assert exc.value.status_code == 409


def test_create_animal_acepta_todos_los_campos_opcionales() -> None:
    """El INSERT incluye los 9 obligatorios + 15 opcionales, con NULL
    para los no provistos.

    Tras #129, los 9 obligatorios (5 Access + 4 discovery) deben
    proveerse siempre; los 15 restantes son opcionales y admiten
    ``None`` (NULL).
    """
    returned = {
        "id": "22222222-2222-2222-2222-222222222222",
        "NCHIP": "985112004409999",
        "NombreAnimal": "Mishi",
        "Especie": "FELINA",
        "Sexo": "M",
        "FNacimiento": "2024-01-15",
        "activo": True,
    }

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        return _json_response(200, [returned])

    client, captured = _client_recording(_handler)
    create_animal(
        client,
        {
            **_params_minimal(),
            "NCHIP": "985112004409999",
            "NombreAnimal": "Mishi",
            "Especie": "FELINA",
            "Sexo": "M",
            "FNacimiento": "2024-01-15",
            "TraeNChip": "Si",
            "FIMPLANTACIONCHIP": "2024-01-20",
            "Raza": "Comun europeo",
            "Color": "Negro",
            "Pelo": "Corto",
            "Tamano": "Mediano",
            "Caracter": "Tranquilo",
            "FDefuncion": None,
            "Terapia": "No",  # #129: ahora obligatorio; antes era None
            "Observaciones": "Sin observaciones",
            "NombreFoto": "mishi.jpg",  # #129: ahora obligatorio
            "Cartilla": "Si",
            "Eutanasia": "No",
            "RazaPPP": "No",
            "Mestizo": "Si",
            "EutanasiaOtrasCausas": None,
            "EutanasiaEnfermedad": None,
            "UltimoEstadoAntesDeFallecido": None,
            "ComunicacionARIAC": "No",
        },
    )
    client.close()

    assert len(captured) == 1
    query = captured[0]["query"]
    # El INSERT debe listar los 24 campos de insercion (9 obligatorios + 15 opcionales)
    for col in (
        "NCHIP",
        "NombreAnimal",
        "Especie",
        "Sexo",
        "FNacimiento",
        "TraeNChip",
        "FIMPLANTACIONCHIP",
        "Raza",
        "Color",
        "Pelo",
        "Tamano",
        "Caracter",
        "FDefuncion",
        "Terapia",
        "Observaciones",
        "NombreFoto",
        "Cartilla",
        "Eutanasia",
        "RazaPPP",
        "Mestizo",
        "EutanasiaOtrasCausas",
        "EutanasiaEnfermedad",
        "UltimoEstadoAntesDeFallecido",
        "ComunicacionARIAC",
    ):
        assert col in query, f"falta columna {col} en el INSERT"
    params = captured[0]["params"]
    assert params[0] == "985112004409999"  # NCHIP
    assert params[5] == "Si"               # TraeNChip
    assert params[6] == "2024-01-20"       # FIMPLANTACIONCHIP
    assert params[7] == "Comun europeo"   # Raza


# --- list_animals ---------------------------------------------------------


def test_list_animals_ejecuta_select_y_devuelve_filas() -> None:
    rows = [
        {
            "id": "aaa",
            "NCHIP": "1",
            "NombreAnimal": "Luna",
            "Especie": "CANINA",
            "Sexo": "H",
            "FNacimiento": "2023-04-12",
            "activo": True,
        },
        {
            "id": "bbb",
            "NCHIP": "2",
            "NombreAnimal": "Mishi",
            "Especie": "FELINA",
            "Sexo": "M",
            "FNacimiento": "2024-01-15",
            "activo": True,
        },
    ]

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        return _json_response(200, rows)

    client, captured = _client_recording(_handler)
    result = list_animals(client)
    client.close()

    assert [r.id for r in result] == ["aaa", "bbb"]
    assert [r.NombreAnimal for r in result] == ["Luna", "Mishi"]

    assert len(captured) == 1
    query = captured[0]["query"]
    assert "SELECT" in query
    assert "FROM animales" in query
    assert "ORDER BY fecha_alta DESC" in query
    assert "WHERE activo = true" in query


def test_list_animals_devuelve_lista_vacia_sin_filas() -> None:
    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        return _json_response(200, [])

    client, _ = _client_recording(_handler)
    result = list_animals(client)
    client.close()

    assert result == []


# --- get_animal_by_id -----------------------------------------------------


def test_get_animal_by_id_devuelve_fila_cuando_existe() -> None:
    row = {
        "id": "abc-123",
        "NCHIP": "1",
        "NombreAnimal": "Luna",
        "Especie": "CANINA",
        "Sexo": "H",
        "FNacimiento": "2023-04-12",
        "activo": True,
    }

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        return _json_response(200, [row])

    client, captured = _client_recording(_handler)
    result = get_animal_by_id(client, "abc-123")
    client.close()

    assert result is not None
    assert result.id == "abc-123"
    assert result.NCHIP == "1"
    assert captured[0]["params"] == ["abc-123"]
    assert "WHERE id = $1" in captured[0]["query"]


def test_get_animal_by_id_devuelve_None_si_no_existe() -> None:
    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        return _json_response(200, [])

    client, _ = _client_recording(_handler)
    result = get_animal_by_id(client, "no-such-id")
    client.close()

    assert result is None


# --- update_animal (code-quality-fixes T3.1) ------------------------------
#
# El handler de update delega en ``update_animal`` con la misma
# validacion que ``create_animal`` (reutilizando
# ``_validate_required_fields``), ejecuta un UPDATE con RETURNING para
# traer la fila actualizada y toca ``updated_at = now()``. El id es
# el primer parametro del WHERE; el resto de los params siguen el orden
# de ``_UPDATE_COLUMNS``.


def test_update_animal_ejecuta_update_con_returning_y_devuelve_fila() -> None:
    """``update_animal`` ejecuta UPDATE … WHERE id = $1 RETURNING … y devuelve ``Animal``."""
    returned = {
        "id": "abc-123",
        "NCHIP": "985112004409871",
        "NombreAnimal": "Luna Editada",
        "Especie": "CANINA",
        "Sexo": "H",
        "FNacimiento": "2023-04-12",
        "activo": True,
        "updated_at": "2026-06-23T12:00:00Z",
    }

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        return _json_response(200, [returned])

    client, captured = _client_recording(_handler)
    result = update_animal(client, "abc-123", _params_minimal())
    client.close()

    assert result is not None
    assert result.id == "abc-123"
    assert result.NombreAnimal == "Luna Editada"
    assert result.updated_at == "2026-06-23T12:00:00Z"

    assert len(captured) == 1
    query = captured[0]["query"]
    assert "UPDATE animales SET" in query
    assert "updated_at = now()" in query
    assert "WHERE id = $1" in query
    assert "RETURNING" in query

    params = captured[0]["params"]
    assert params[0] == "abc-123", "id debe ser el primer parametro (WHERE)"
    assert params[1] == "985112004409871", "NCHIP es el segundo parametro"
    assert params[2] == "Luna"


def test_update_animal_incluye_todas_las_columnas_en_el_set_clause() -> None:
    """El SET incluye los 24 campos del form + updated_at = now()."""
    returned = {
        "id": "abc",
        "NCHIP": "1",
        "NombreAnimal": "X",
        "Especie": "CANINA",
        "Sexo": "M",
        "FNacimiento": "2020-01-01",
        "activo": True,
    }

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        return _json_response(200, [returned])

    client, captured = _client_recording(_handler)
    update_animal(
        client,
        "abc",
        {
            **_params_minimal(),
            "Raza": "Mestizo",
            "Color": "Negro",
            "Terapia": "Si",
        },
    )
    client.close()

    query = captured[0]["query"]
    for col in (
        "NCHIP", "NombreAnimal", "Especie", "Sexo", "FNacimiento",
        "TraeNChip", "FIMPLANTACIONCHIP", "Raza", "Color", "Pelo", "Tamano",
        "Caracter", "FDefuncion", "Terapia", "Observaciones", "NombreFoto",
        "Cartilla", "Eutanasia", "RazaPPP", "Mestizo", "EutanasiaOtrasCausas",
        "EutanasiaEnfermedad", "UltimoEstadoAntesDeFallecido", "ComunicacionARIAC",
    ):
        assert col in query, f"falta columna {col} en el SET"
    # updated_at es la columna derivada (se setea con now() en SQL).
    assert "updated_at = now()" in query


def test_update_animal_rechaza_NCHIP_vacio_sin_tocar_sql() -> None:
    """Misma validacion que create: NCHIP vacio levanta ValueError y no emite SQL."""
    client, captured = _client_recording(lambda req, body: _json_response(200, []))

    with pytest.raises(ValueError, match="NCHIP"):
        update_animal(client, "abc-123", {**_params_minimal(), "NCHIP": "   "})
    client.close()

    assert captured == [], "no se debe emitir SQL si la validacion falla"


def test_update_animal_rechaza_Especie_invalida_sin_tocar_sql() -> None:
    client, captured = _client_recording(lambda req, body: _json_response(200, []))

    with pytest.raises(ValueError, match="Especie"):
        update_animal(client, "abc-123", {**_params_minimal(), "Especie": "REPTIL"})
    client.close()

    assert captured == []


def test_update_animal_devuelve_None_si_el_id_no_existe() -> None:
    """``UPDATE … RETURNING`` con 0 filas: el service devuelve ``None``."""

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        return _json_response(200, [])

    client, captured = _client_recording(_handler)
    result = update_animal(client, "no-such-id", _params_minimal())
    client.close()

    assert result is None
    assert len(captured) == 1
    assert captured[0]["params"][0] == "no-such-id"


# --- delete_animal (code-quality-fixes T3.2) ------------------------------


def test_delete_animal_soft_delete_con_id_existente_devuelve_True() -> None:
    """``delete_animal`` ejecuta UPDATE … activo=false y devuelve True si la fila existio."""
    returned = {
        "id": "abc-123",
        "NCHIP": "1",
        "NombreAnimal": "Luna",
        "Especie": "CANINA",
        "Sexo": "H",
        "FNacimiento": "2023-04-12",
        "activo": False,
    }

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        return _json_response(200, [returned])

    client, captured = _client_recording(_handler)
    result = delete_animal(client, "abc-123")
    client.close()

    assert result is True
    assert len(captured) == 1
    query = captured[0]["query"]
    assert "UPDATE animales" in query
    assert "SET activo = false" in query
    assert "updated_at = now()" in query
    assert "WHERE id = $1" in query
    assert captured[0]["params"] == ["abc-123"]


def test_delete_animal_devuelve_False_si_el_id_no_existe() -> None:
    """``delete_animal`` con 0 filas afectadas devuelve False (no propaga error)."""

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        return _json_response(200, [])

    client, captured = _client_recording(_handler)
    result = delete_animal(client, "no-such-id")
    client.close()

    assert result is False
    assert len(captured) == 1
    assert captured[0]["params"] == ["no-such-id"]


def test_delete_animal_no_emite_sql_extra_cuando_es_True() -> None:
    """Triangulacion: el happy path emite exactamente UN UPDATE y devuelve True."""

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        return _json_response(200, [{"id": "abc", "activo": False}])

    client, captured = _client_recording(_handler)
    result = delete_animal(client, "abc")
    client.close()

    assert result is True
    assert len(captured) == 1, (
        "delete_animal debe emitir exactamente UN UPDATE; "
        f"se emitio {len(captured)} (probable look-up previo redundante)"
    )


# --- #129 parity: campos requeridos segun Access + discovery -----------------
#
# P1 del playbook (`docs/proceso.md`): la webapp es superset del legacy. Los
# campos ``Required=True`` en Access ``TbFichaAnimal`` + los documentados
# como "datos requeridos de ficha" en ``docs/discovery/feature-01-animal-
# lifecycle.md`` §"Required animal data" deben ser requeridos en la web.
#
# Access Required (TbFichaAnimal):  NCHIP, NombreAnimal, Especie, Sexo,
#                                    FNacimiento, Terapia
# Discovery §"Required animal data": anhadidos TraeNChip, FImplantacionChip
#                                    (=FIMPLANTACIONCHIP en la web) y Foto
#                                    (=NombreFoto en la web; el legacy
#                                    TbFichaAnimal.NombreFoto es el campo
#                                    que guarda el nombre del archivo de
#                                    foto del animal).


def test_animal_form_required_fields_incluyen_los_de_access_y_discovery() -> None:
    """P1 fidelidad al legacy: el conjunto de campos requeridos es la
    union exacta de ``TbFichaAnimal.Required=True`` (Access) y los datos
    requeridos de ficha definidos en discovery.

    Verifica ademas que el nombre del campo web ``NombreFoto`` esta
    declarado como requerido (es la representacion web de la foto del
    animal del legacy; el discovery lo lista como ``Foto``).
    """
    expected = {
        # Access TbFichaAnimal.Required=True
        "NCHIP",
        "NombreAnimal",
        "Especie",
        "Sexo",
        "FNacimiento",
        "Terapia",
        # Discovery feature-01 §"Required animal data"
        "TraeNChip",
        "FIMPLANTACIONCHIP",
        "NombreFoto",
    }
    assert set(ANIMAL_FORM_REQUIRED_FIELDS) == expected, (
        f"required set drifted from Access + discovery: "
        f"extras got={sorted(set(ANIMAL_FORM_REQUIRED_FIELDS) - expected)}, "
        f"missing expected={sorted(expected - set(ANIMAL_FORM_REQUIRED_FIELDS))}"
    )


@pytest.mark.parametrize(
    "missing_field",
    ["Terapia", "TraeNChip", "FIMPLANTACIONCHIP", "NombreFoto"],
)
def test_create_animal_rechaza_campos_requeridos_de_access_o_discovery(
    missing_field: str,
) -> None:
    """Issue #129: Terapia (Access) + TraeNChip/FIMPLANTACIONCHIP/NombreFoto
    (discovery) son requeridos. Missing cada uno rechaza con ValueError y
    sin emitir SQL (regla P1: el servicio NO toca la DB si la validacion
    falla, ver `app/modules/animals/service.py` docstring de
    ``_validate_required_fields``).
    """
    client, captured = _client_recording(lambda req, body: _json_response(200, []))
    params = {**_params_minimal(), missing_field: ""}

    with pytest.raises(ValueError, match=missing_field):
        create_animal(client, params)
    client.close()

    assert captured == [], (
        "no se debe emitir SQL si la validacion falla; "
        f"se capturaron {len(captured)} queries: {captured!r}"
    )


@pytest.mark.parametrize(
    "missing_field",
    ["Terapia", "TraeNChip", "FIMPLANTACIONCHIP", "NombreFoto"],
)
def test_update_animal_rechaza_campos_requeridos_de_access_o_discovery(
    missing_field: str,
) -> None:
    """Simetrico a ``create_animal``: ``update_animal`` reusa
    ``_validate_required_fields`` (mismo helper para create/update
    per `app/modules/animals/service.py` docstring), por lo que la
    validacion cubre ambos paths. Missing un required rechaza sin
    emitir SQL.
    """
    client, captured = _client_recording(lambda req, body: _json_response(200, []))
    params = {**_params_minimal(), missing_field: ""}

    with pytest.raises(ValueError, match=missing_field):
        update_animal(client, "abc-123", params)
    client.close()

    assert captured == [], (
        "no se debe emitir SQL si la validacion falla en update; "
        f"se capturaron {len(captured)} queries: {captured!r}"
    )


# --- Issue #224: NombreFoto is used, unsanitized, as a storage `key` URL --
# path segment (`InsForgeClient.download_object_stream` /
# `delete_object`). It must be rejected at the write path (create/update)
# before any SQL is issued, same fail-fast contract as the other required
# field checks above.


@pytest.mark.parametrize(
    "payload",
    [
        "../../etc/passwd",
        "..\\..\\windows\\system32",
        "/etc/passwd",
        "sub/dir/foto.jpg",
        "..oculto.jpg",
        ".oculto.jpg",
    ],
)
def test_create_animal_rechaza_NombreFoto_con_path_traversal(payload: str) -> None:
    client, captured = _client_recording(lambda req, body: _json_response(200, []))

    with pytest.raises(ValueError, match="NombreFoto"):
        create_animal(client, {**_params_minimal(), "NombreFoto": payload})
    client.close()

    assert captured == [], (
        "no se debe emitir SQL si NombreFoto es inseguro; "
        f"se capturaron {len(captured)} queries: {captured!r}"
    )


@pytest.mark.parametrize(
    "payload",
    [
        "../../etc/passwd",
        "..\\..\\windows\\system32",
        "/etc/passwd",
        "sub/dir/foto.jpg",
    ],
)
def test_update_animal_rechaza_NombreFoto_con_path_traversal(payload: str) -> None:
    client, captured = _client_recording(lambda req, body: _json_response(200, []))

    with pytest.raises(ValueError, match="NombreFoto"):
        update_animal(client, "abc-123", {**_params_minimal(), "NombreFoto": payload})
    client.close()

    assert captured == []


def test_create_animal_acepta_NombreFoto_con_nombre_de_archivo_normal() -> None:
    """Un nombre de archivo normal (sin separadores ni traversal) sigue funcionando."""
    returned = {
        "id": "33333333-3333-3333-3333-333333333333",
        "NCHIP": "985112004409871",
        "NombreAnimal": "Luna",
        "Especie": "CANINA",
        "Sexo": "H",
        "FNacimiento": "2023-04-12",
        "activo": True,
    }

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        return _json_response(200, [returned])

    client, captured = _client_recording(_handler)
    create_animal(client, {**_params_minimal(), "NombreFoto": "foto123.jpg"})
    client.close()

    assert len(captured) == 1
