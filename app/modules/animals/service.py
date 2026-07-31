"""Animales service: unica capa que habla con ``SqlExecutor`` para animales.

Es deliberadamente framework-agnostica: toma un ``SqlExecutor`` y
un dict de campos validados, ejecuta el SQL via ``client.execute_sql``
y devuelve dataclasses. Las rutas HTTP son una capa fina encima que
maneja form parsing, auth y renderizado HTML.

Politica de validacion:

- Enums de dominio (``Especie``, ``Sexo``) y campos requeridos se
  validan ANTES de cualquier SQL. El service levanta ``ValueError``
  con mensaje accionable; la ruta traduce a 422 / 409.
- El service NO traduce ``InsForgeError`` a excepciones de dominio:
  eso acoplaria el service a HTTP. La ruta inspecciona la excepcion y
  decide la respuesta.
- El campo legacy ``Situacion`` no se persiste: es derivado del event
  log (LIFECYCLE-SCHEMA-02 / LIFECYCLE-03). El service no lo expone.

El schema se define como constante aqui (mismo patron que
``app.core.auth``) para que las queries ``INSERT`` / ``SELECT``
esten en un solo lugar.

Mapeo de campos (legacy ``TbFichaAnimal`` -> dataclass):

  NCHIP                       -> NCHIP
  TraeNChip                   -> TraeNChip
  FIMPLANTACIONCHIP           -> FIMPLANTACIONCHIP
  NombreAnimal                -> NombreAnimal
  Especie                     -> Especie
  Sexo                        -> Sexo
  Raza                        -> Raza
  Color                       -> Color
  Pelo                        -> Pelo
  Tamano (legacy: Tamanyos)   -> Tamano
  Caracter                    -> Caracter
  FNacimiento                 -> FNacimiento
  FDefuncion                  -> FDefuncion
  Terapia                     -> Terapia
  Observaciones               -> Observaciones
  NombreFoto                  -> NombreFoto
  Cartilla                    -> Cartilla
  Eutanasia                   -> Eutanasia
  RazaPPP                     -> RazaPPP
  Mestizo                     -> Mestizo
  EutanasiaOtrasCausas        -> EutanasiaOtrasCausas
  EutanasiaEnfermedad          -> EutanasiaEnfermedad
  UltimoEstadoAntesDeFallecido -> UltimoEstadoAntesDeFallecido
  ComunicacionARIAC           -> ComunicacionARIAC
  (mejora)                    -> id (UUID PK)
  (mejora)                    -> fecha_alta (created_at)
  (mejora)                    -> updated_at
  (mejora)                    -> activo (soft-delete)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, cast

from app.core.data_access import SqlExecutor
from app.core.insforge import _validate_storage_key
from app.modules.animals import queries as qry
from app.modules.animals.queries import DB_LABEL_TO_ESTADO


class Especie(StrEnum):
    CANINA = "CANINA"
    FELINA = "FELINA"


class Sexo(StrEnum):
    M = "M"
    H = "H"


@dataclass(frozen=True, slots=True)
class Animal:
    """Una fila de la tabla ``animales``, tal como la devuelve el service.

    Los nombres de los campos son los del schema en CamelCase Spanish
    (matching el legacy ``TbFichaAnimal``). El campo ``id`` es la PK
    UUID, las tres columnas de sistema (``id``, ``fecha_alta``,
    ``updated_at``, ``activo``) son las mejoras justificadas.
    """

    id: str
    NCHIP: str
    NombreAnimal: str
    Especie: Especie
    Sexo: Sexo
    FNacimiento: str  # DATE en la DB; string ISO 8601 en la API
    activo: bool = True
    TraeNChip: str | None = None
    FIMPLANTACIONCHIP: str | None = None
    Raza: str | None = None
    Color: str | None = None
    Pelo: str | None = None
    Tamano: str | None = None
    Caracter: str | None = None
    FDefuncion: str | None = None
    Terapia: str | None = None
    Observaciones: str | None = None
    NombreFoto: str | None = None
    Cartilla: str | None = None
    Eutanasia: str | None = None
    RazaPPP: str | None = None
    Mestizo: str | None = None
    EutanasiaOtrasCausas: str | None = None
    EutanasiaEnfermedad: str | None = None
    UltimoEstadoAntesDeFallecido: str | None = None
    ComunicacionARIAC: str | None = None
    fecha_alta: str | None = None
    updated_at: str | None = None


def _db_state_to_api_estado(db_state: str | None) -> str:
    """Normalize a DB ``current_state`` Spanish label to API snake_case estado.

    Single source of truth for DB→API estado mapping lives in
    ``app.modules.animals.queries.DB_LABEL_TO_ESTADO`` (AGENTS.md §4).
    """
    if db_state is None:
        return "pendiente_entrada"
    return DB_LABEL_TO_ESTADO.get(db_state, "incoherente")


@dataclass(frozen=True, slots=True)
class AnimalSearch:
    """Un animal en el resultado de búsqueda (spec response shape)."""

    id: str
    chip: str
    nombre: str
    especie: str
    sexo: str
    estado: str
    fecha_nacimiento: str
    fecha_alta: str


@dataclass(frozen=True, slots=True)
class AnimalSearchResult:
    """Respuesta paginada del search API (spec response shape)."""

    data: list[AnimalSearch]
    total: int
    limit: int
    offset: int


_INSERT_COLUMNS = (
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
)

_SELECT_COLUMNS = (
    "id",
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
    "fecha_alta",
    "updated_at",
    "activo",
)


def _row_to_animal(row: dict[str, Any]) -> Animal:
    """Mapea una fila cruda de la DB (dict) al dataclass ``Animal``."""
    return Animal(
        id=str(row["id"]),
        NCHIP=str(row["NCHIP"]),
        NombreAnimal=str(row["NombreAnimal"]),
        Especie=Especie(row["Especie"]),
        Sexo=Sexo(row["Sexo"]),
        FNacimiento=str(row["FNacimiento"]),
        activo=bool(row.get("activo", True)),
        TraeNChip=row.get("TraeNChip"),
        FIMPLANTACIONCHIP=row.get("FIMPLANTACIONCHIP"),
        Raza=row.get("Raza"),
        Color=row.get("Color"),
        Pelo=row.get("Pelo"),
        Tamano=row.get("Tamano"),
        Caracter=row.get("Caracter"),
        FDefuncion=row.get("FDefuncion"),
        Terapia=row.get("Terapia"),
        Observaciones=row.get("Observaciones"),
        NombreFoto=row.get("NombreFoto"),
        Cartilla=row.get("Cartilla"),
        Eutanasia=row.get("Eutanasia"),
        RazaPPP=row.get("RazaPPP"),
        Mestizo=row.get("Mestizo"),
        EutanasiaOtrasCausas=row.get("EutanasiaOtrasCausas"),
        EutanasiaEnfermedad=row.get("EutanasiaEnfermedad"),
        UltimoEstadoAntesDeFallecido=row.get("UltimoEstadoAntesDeFallecido"),
        ComunicacionARIAC=row.get("ComunicacionARIAC"),
        fecha_alta=str(row["fecha_alta"]) if row.get("fecha_alta") else None,
        updated_at=str(row["updated_at"]) if row.get("updated_at") else None,
    )


def _validate_required_string(params: dict[str, Any], field: str) -> str:
    """Helper: campo string requerido compartido entre create/update.

    Patron paralelo a ``_required_text`` en
    ``app/modules/entradas/service.py``: devuelve el valor normalizado
    o levanta ``ValueError`` con mensaje accionable. Usado por los
    checks de campos string required (#129: Terapia, TraeNChip,
    FIMPLANTACIONCHIP, NombreFoto).
    """
    value = str(params.get(field) or "").strip()
    if not value:
        raise ValueError(f"{field} es obligatorio y no puede estar vacio")
    return value


def _validate_required_fields(params: dict[str, Any]) -> None:
    """Valida los campos requeridos antes de cualquier SQL (compartido create/update).

    Levanta ``ValueError`` con mensaje accionable si algo falta o esta
    fuera de dominio. NO toca la DB. Reutilizado por ``create_animal``
    y ``update_animal`` para mantener una unica fuente de verdad de la
    validacion de dominio de los animales (cierra el problema #4 del
    code review externo: validacion duplicada routes<->service).

    El conjunto de campos required es la union de Access ``TbFichaAnimal.
    Required=True`` (D-05 fidelidad al legacy) y los datos requeridos
    de ficha definidos en ``docs/discovery/feature-01-animal-lifecycle.
    md`` §"Required animal data". Ver ``ANIMAL_FORM_REQUIRED_FIELDS``
    en ``app/modules/animals/forms.py`` para la lista canonica.
    """
    NCHIP = (params.get("NCHIP") or "").strip()
    if not NCHIP:
        raise ValueError("NCHIP es obligatorio y no puede estar vacio")

    nombre = (params.get("NombreAnimal") or "").strip()
    if not nombre:
        raise ValueError("NombreAnimal es obligatorio y no puede estar vacio")

    try:
        # cast: any non-member (including None) lands in the ValueError branch.
        Especie(cast("str", params.get("Especie")))
    except ValueError as exc:
        raise ValueError(
            f"Especie debe ser una de {[e.value for e in Especie]}, "
            f"recibido: {params.get('Especie')!r}"
        ) from exc

    try:
        # cast: any non-member (including None) lands in the ValueError branch.
        Sexo(cast("str", params.get("Sexo")))
    except ValueError as exc:
        raise ValueError(
            f"Sexo debe ser uno de {[s.value for s in Sexo]}, "
            f"recibido: {params.get('Sexo')!r}"
        ) from exc

    fnacimiento = (params.get("FNacimiento") or "").strip()
    if not fnacimiento:
        raise ValueError("FNacimiento es obligatorio y no puede estar vacio")

    # Issue #129: los 4 required anhadidos por la paridad Access + discovery.
    _validate_required_string(params, "Terapia")
    _validate_required_string(params, "TraeNChip")
    _validate_required_string(params, "FIMPLANTACIONCHIP")
    nombre_foto = _validate_required_string(params, "NombreFoto")

    # Issue #224: NombreFoto se usa, sin sanear, como segmento de URL en
    # las llamadas de storage de InsForge (``download_object_stream`` /
    # ``delete_object`` en ``app/core/insforge.py``). Reutiliza la misma
    # allow-list que protege ``bucket`` (``_validate_storage_key``) para
    # rechazar path traversal / separadores de ruta en el path de
    # escritura, no solo en el de lectura.
    try:
        _validate_storage_key(nombre_foto)
    except ValueError as exc:
        raise ValueError(
            f"NombreFoto contiene caracteres no permitidos ({nombre_foto!r}); "
            "no puede incluir '/', '\\\\', segmentos '..' ni empezar por '.'"
        ) from exc


_INSERT_ANIMAL_SQL = f"""
INSERT INTO animales ({", ".join(_INSERT_COLUMNS)})
VALUES ({", ".join(f"${i+1}" for i in range(len(_INSERT_COLUMNS)))})
RETURNING {", ".join(_SELECT_COLUMNS)}
"""

_LIST_ANIMALS_SQL = f"""
SELECT {", ".join(_SELECT_COLUMNS)}
FROM animales
WHERE activo = true
ORDER BY fecha_alta DESC
"""

_GET_ANIMAL_BY_ID_SQL = f"""
SELECT {", ".join(_SELECT_COLUMNS)}
FROM animales
WHERE id = $1
"""


# Columnas que se actualizan en UPDATE (excluye PK id, created_at
# fecha_alta y activo: id nunca cambia, fecha_alta es la fecha de
# creacion y activo se maneja por separado en ``delete_animal``).
_UPDATE_COLUMNS = _INSERT_COLUMNS

_UPDATE_ANIMAL_SQL = (
    "UPDATE animales SET "
    + ", ".join(f"{col} = ${i+2}" for i, col in enumerate(_UPDATE_COLUMNS))
    + ", updated_at = now() "
    + "WHERE id = $1 "
    + "RETURNING " + ", ".join(_SELECT_COLUMNS)
)

_DELETE_ANIMAL_SQL = """
UPDATE animales
SET activo = false,
    updated_at = now()
WHERE id = $1
RETURNING id, activo
"""


def _build_insert_params(params: dict[str, Any]) -> list[Any]:
    """Construye la lista de parametros en el orden de ``_INSERT_COLUMNS``."""
    return [
        params.get("NCHIP", "").strip(),
        params.get("NombreAnimal", "").strip(),
        params.get("Especie"),
        params.get("Sexo"),
        params.get("FNacimiento", "").strip(),
        params.get("TraeNChip"),
        params.get("FIMPLANTACIONCHIP"),
        params.get("Raza"),
        params.get("Color"),
        params.get("Pelo"),
        params.get("Tamano"),
        params.get("Caracter"),
        params.get("FDefuncion"),
        params.get("Terapia"),
        params.get("Observaciones"),
        params.get("NombreFoto"),
        params.get("Cartilla"),
        params.get("Eutanasia"),
        params.get("RazaPPP"),
        params.get("Mestizo"),
        params.get("EutanasiaOtrasCausas"),
        params.get("EutanasiaEnfermedad"),
        params.get("UltimoEstadoAntesDeFallecido"),
        params.get("ComunicacionARIAC"),
    ]


def _build_update_params(params: dict[str, Any]) -> list[Any]:
    """Parametros en el orden de ``_UPDATE_COLUMNS`` (id va en posicion 0)."""
    return [params.get(col) for col in _UPDATE_COLUMNS]


def create_animal(client: SqlExecutor, params: dict[str, Any]) -> Animal:
    """Inserta un animal. Levanta ``ValueError`` si los datos son invalidos.

    Un NCHIP duplicado se surface como respuesta no-2xx de InsForge;
    el ``InsForgeError`` resultante se propaga sin cambios para que la
    ruta lo traduzca a 409.
    """
    _validate_required_fields(params)

    rows = client.execute_sql(_INSERT_ANIMAL_SQL, _build_insert_params(params))
    return _row_to_animal(rows[0])


def list_animals(client: SqlExecutor) -> list[Animal]:
    """Devuelve todos los animales activos, mas recientes primero."""
    rows = client.execute_sql(_LIST_ANIMALS_SQL)
    return [_row_to_animal(row) for row in rows]


def get_animal_by_id(client: SqlExecutor, animal_id: str) -> Animal | None:
    """Devuelve el animal con este id (activo o inactivo), o ``None``."""
    rows = client.execute_sql(_GET_ANIMAL_BY_ID_SQL, [animal_id])
    return _row_to_animal(rows[0]) if rows else None


def update_animal(
    client: SqlExecutor,
    animal_id: str,
    params: dict[str, Any],
) -> Animal | None:
    """Actualiza un animal existente y devuelve la fila actualizada.

    Levanta ``ValueError`` (via :func:`_validate_required_fields`) si
    los campos requeridos son invalidos; el service NO toca la DB en
    ese caso. Devuelve ``None`` si el id no existe (``UPDATE … RETURNING``
    con 0 filas). La columna ``updated_at`` la setea la propia SQL con
    ``now()`` para no depender del reloj del cliente.
    """
    _validate_required_fields(params)

    rows = client.execute_sql(
        _UPDATE_ANIMAL_SQL,
        [animal_id, *_build_update_params(params)],
    )
    return _row_to_animal(rows[0]) if rows else None


def delete_animal(client: SqlExecutor, animal_id: str) -> bool:
    """Soft-delete: marca ``activo = false``. Devuelve True si la fila existio.

    Implementado como ``UPDATE … RETURNING id`` para que la condicion
    de existencia quede embebida en la propia SQL (no hay SELECT
    previo redundante). Devuelve ``False`` si la fila no existia (0
    filas en el RETURNING).
    """
    rows = client.execute_sql(_DELETE_ANIMAL_SQL, [animal_id])
    return bool(rows)


<<<<<<< HEAD
# --- search (issue #30 LIFECYCLE-05) ----------------------------------------


def _row_to_animal_search(row: dict[str, Any]) -> AnimalSearch:
    """Map a search result row to ``AnimalSearch``."""
    db_state = row.get("current_state")
    return AnimalSearch(
        id=str(row["id"]),
        chip=str(row["NCHIP"]),
        nombre=str(row["NombreAnimal"]),
        especie=str(row["Especie"]),
        sexo=str(row["Sexo"]),
        estado=_db_state_to_api_estado(db_state),
        fecha_nacimiento=str(row["FNacimiento"]),
        fecha_alta=str(row["fecha_alta"]) if row.get("fecha_alta") else "",
    )


def search_animals(
    client: SqlExecutor,
    *,
    q: str | None = None,
    chip: str | None = None,
    especie: str | None = None,
    sexo: str | None = None,
    estado: str | None = None,
    fecha_alta_since: str | None = None,
    fecha_alta_until: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> AnimalSearchResult:
    """Búsqueda de animales con filtros (issue #30, LIFECYCLE-05).

    Filtros (todos AND):
    - ``q``: substring match case-insensitive en ``nombre``.
      Ignorado si ``chip`` está presente.
    - ``chip``: exact match en ``NCHIP``. Toma precedencia sobre ``q``.
    - ``especie``: exact match (CANINA | FELINA).
    - ``sexo``: exact match (M | H).
    - ``estado``: filtrado por estado derivado (JOIN con
      ``animal_current_state``). Valores API: pendiente_entrada,
      pendiente_nueva_situacion, albergue, acogida, adoptado,
      entregado, fallecido, incoherente.
    - ``fecha_alta_since`` / ``fecha_alta_until``: rango inclusivo.

    Paginación: ``limit`` default 50, max 200; ``offset`` para cursor.
    ``limit=0`` devuelve solo ``total`` sin ``data`` (count sin fetch).

    Orden: ``fecha_alta DESC``.
    """
    params = qry.AnimalSearchParams(
        q=q,
        chip=chip,
        especie=especie,
        sexo=sexo,
        estado=estado,
        fecha_alta_since=fecha_alta_since,
        fecha_alta_until=fecha_alta_until,
        limit=limit,
        offset=offset,
    )
    capped = params.cap_limit()

    # limit=0: count-only path
    if capped.limit == 0:
        count_result = qry.build_animal_count(capped)
        rows = client.execute_sql(count_result.sql, count_result.params)
        total = int(rows[0]["total"]) if rows else 0
        return AnimalSearchResult(data=[], total=total, limit=0, offset=capped.offset)

    # Normal path: data + total in two queries
    search_result = qry.build_animal_search(capped)
    data_rows = client.execute_sql(search_result.sql, search_result.params)
    animals = [_row_to_animal_search(row) for row in data_rows]

    count_result = qry.build_animal_count(capped)
    count_rows = client.execute_sql(count_result.sql, count_result.params)
    total = int(count_rows[0]["total"]) if count_rows else 0

    return AnimalSearchResult(
        data=animals,
        total=total,
        limit=capped.limit,
        offset=capped.offset,
    )
=======
# --- chip change (issue #29, LIFECYCLE-04) --------------------------------


@dataclass(frozen=True, slots=True)
class ChangeChipResult:
    """Resultado del saga de cambio de chip.

    ``success=True``: todos los registros se actualizaron atomicamente.
    ``success=False``: la operacion se revirtio; ``error`` contiene la causa.
    """

    success: bool
    old_chip: str
    new_chip: str
    updated_tables: dict[str, int]
    error: str | None = None


def change_animal_chip(
    client: SqlExecutor,
    *,
    animal_id: str,
    old_chip: str,
    new_chip: str,
    reason: str,
    operador_user_id: str,
) -> ChangeChipResult:
    """Saga: cambiar el chip de un animal en cascada a 6 tablas.

    Tablas: ``animals`` (NCHIP), ``entradas``, ``acogidas``,
    ``adopciones``, ``actuaciones_sanitarias``, ``terapias``.

    Validaciones pre-transaccion:
    - ``new_chip`` no puede estar vacio ni ser igual a ``old_chip``.
    - ``reason`` no puede estar vacio.
    - ``new_chip`` no puede estar asignado a otro animal.
    - ``old_chip`` debe coincidir con el chip actual del animal.

    Si cualquier tabla falla dentro de la transaccion, se ejecuta
    ROLLBACK y se devuelve ``ChangeChipResult(success=False)``.

    Returns: :class:`ChangeChipResult`
    """
    # --- pre-flight validations -----------------------------------------
    new_chip_val = new_chip.strip()
    if not new_chip_val:
        raise ValueError("new_chip es obligatorio y no puede estar vacio")
    if new_chip_val == old_chip:
        raise ValueError("new_chip no puede ser igual a old_chip")
    reason_val = reason.strip()
    if not reason_val:
        raise ValueError("reason es obligatorio y no puede estar vacio")

    # 1. Uniqueness: new_chip no esta asignado a otro animal?
    uniq_rows = client.execute_sql(
        _CHECK_CHIP_UNIQUENESS_SQL, [new_chip_val, animal_id]
    )
    if uniq_rows:
        return ChangeChipResult(
            success=False,
            old_chip=old_chip,
            new_chip=new_chip_val,
            updated_tables={},
            error=f"El chip {new_chip_val!r} ya esta asignado a otro animal (id={uniq_rows[0]['id']})",
        )

    # 2. old_chip coincide con el chip actual del animal?
    current_rows = client.execute_sql(_GET_CURRENT_CHIP_SQL, [animal_id])
    if not current_rows:
        return ChangeChipResult(
            success=False,
            old_chip=old_chip,
            new_chip=new_chip_val,
            updated_tables={},
            error=f"Animal {animal_id!r} no encontrado",
        )
    actual_chip = str(current_rows[0].get("NCHIP", ""))
    if actual_chip != old_chip:
        return ChangeChipResult(
            success=False,
            old_chip=old_chip,
            new_chip=new_chip_val,
            updated_tables={},
            error=f"El chip actual del animal ({actual_chip!r}) no coincide con old_chip ({old_chip!r})",
        )

    # --- saga: BEGIN transaction ----------------------------------------
    _begin_tx(client)

    updated: dict[str, int] = {}

    try:
        # animals
        rows_ani = client.execute_sql(
            _UPDATE_ANIMALS_CHIP_SQL, [new_chip_val, animal_id, old_chip]
        )
        updated["animals"] = len(rows_ani)

        # entradas
        rows_ent = client.execute_sql(
            _UPDATE_ENTRADAS_CHIP_SQL, [new_chip_val, old_chip]
        )
        updated["entradas"] = len(rows_ent)

        # acogidas
        rows_aco = client.execute_sql(
            _UPDATE_ACOGIDAS_CHIP_SQL, [new_chip_val, old_chip]
        )
        updated["acogidas"] = len(rows_aco)

        # adopciones
        rows_ado = client.execute_sql(
            _UPDATE_ADOPCIONES_CHIP_SQL, [new_chip_val, old_chip]
        )
        updated["adopciones"] = len(rows_ado)

        # actuaciones_sanitarias
        rows_act = client.execute_sql(
            _UPDATE_ACTUACIONES_SANITARIAS_CHIP_SQL, [new_chip_val, old_chip]
        )
        updated["actuaciones_sanitarias"] = len(rows_act)

        # terapias
        rows_ter = client.execute_sql(
            _UPDATE_TERAPIAS_CHIP_SQL, [new_chip_val, old_chip]
        )
        updated["terapias"] = len(rows_ter)

        # lifecycle event
        metadata_json = json.dumps(
            {"old_chip": old_chip, "new_chip": new_chip_val, "reason": reason_val}
        )
        client.execute_sql(
            _INSERT_LIFECYCLE_EVENT_SQL,
            [animal_id, "CHIP_CHANGED", metadata_json, operador_user_id],
        )

        _commit_tx(client)

        return ChangeChipResult(
            success=True,
            old_chip=old_chip,
            new_chip=new_chip_val,
            updated_tables=updated,
        )

    except Exception as exc:  # noqa: BLE001
        _rollback_tx(client)
        return ChangeChipResult(
            success=False,
            old_chip=old_chip,
            new_chip=new_chip_val,
            updated_tables=updated,
            error=f"Error en la transaccion: {exc}",
        )


# --- chip change SQL constants (issue #29, LIFECYCLE-04) -------------------

_CHECK_CHIP_UNIQUENESS_SQL = """
SELECT id FROM animals WHERE NCHIP = $1 AND id != $2 LIMIT 1
"""

_GET_CURRENT_CHIP_SQL = """
SELECT NCHIP FROM animals WHERE id = $1
"""

_UPDATE_ANIMALS_CHIP_SQL = """
UPDATE animals SET NCHIP = $1, updated_at = now()
WHERE id = $2 AND NCHIP = $3
RETURNING id
"""

_UPDATE_ENTRADAS_CHIP_SQL = """
UPDATE entradas SET chip = $1, updated_at = now()
WHERE chip = $2 AND activo = true
RETURNING id
"""

_UPDATE_ACOGIDAS_CHIP_SQL = """
UPDATE acogidas SET chip = $1, updated_at = now()
WHERE chip = $2 AND activo = true
RETURNING id
"""

_UPDATE_ADOPCIONES_CHIP_SQL = """
UPDATE adopciones SET chip = $1, updated_at = now()
WHERE chip = $2 AND activo = true
RETURNING id
"""

_UPDATE_ACTUACIONES_SANITARIAS_CHIP_SQL = """
UPDATE actuaciones_sanitarias SET chip = $1, updated_at = now()
WHERE chip = $2
RETURNING id
"""

_UPDATE_TERAPIAS_CHIP_SQL = """
UPDATE terapias SET chip = $1, updated_at = now()
WHERE chip = $2
RETURNING id
"""

_INSERT_LIFECYCLE_EVENT_SQL = """
INSERT INTO animal_lifecycle_events (
    animal_id,
    event_type,
    event_timestamp,
    metadata,
    created_by
) VALUES ($1, $2, now(), $3, $4)
ON CONFLICT (animal_id, event_type, event_timestamp) DO NOTHING
"""


# --- private helpers (inline SQL for tx control) --------------------------


def _begin_tx(client: SqlExecutor) -> None:
    client.execute_sql("BEGIN", [])


def _commit_tx(client: SqlExecutor) -> None:
    client.execute_sql("COMMIT", [])


def _rollback_tx(client: SqlExecutor) -> None:
    client.execute_sql("ROLLBACK", [])

>>>>>>> ea2a149 (feat(animals): chip change with cascade -- closes #29)
