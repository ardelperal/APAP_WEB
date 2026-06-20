"""Animales service: unica capa que habla con ``InsForgeClient`` para animales.

Es deliberadamente framework-agnostica: toma un ``InsForgeClient`` y
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

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.core.insforge import InsForgeClient


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


def _validate_create_params(params: dict[str, Any]) -> None:
    """Valida los campos provistos antes de cualquier SQL.

    Levanta ``ValueError`` con mensaje accionable si algo falta o esta
    fuera de dominio. NO toca la DB.
    """
    NCHIP = (params.get("NCHIP") or "").strip()
    if not NCHIP:
        raise ValueError("NCHIP es obligatorio y no puede estar vacio")

    nombre = (params.get("NombreAnimal") or "").strip()
    if not nombre:
        raise ValueError("NombreAnimal es obligatorio y no puede estar vacio")

    try:
        Especie(params.get("Especie"))
    except ValueError as exc:
        raise ValueError(
            f"Especie debe ser una de {[e.value for e in Especie]}, "
            f"recibido: {params.get('Especie')!r}"
        ) from exc

    try:
        Sexo(params.get("Sexo"))
    except ValueError as exc:
        raise ValueError(
            f"Sexo debe ser uno de {[s.value for s in Sexo]}, "
            f"recibido: {params.get('Sexo')!r}"
        ) from exc

    fnacimiento = (params.get("FNacimiento") or "").strip()
    if not fnacimiento:
        raise ValueError("FNacimiento es obligatorio y no puede estar vacio")


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


def create_animal(client: InsForgeClient, params: dict[str, Any]) -> Animal:
    """Inserta un animal. Levanta ``ValueError`` si los datos son invalidos.

    Un NCHIP duplicado se surface como respuesta no-2xx de InsForge;
    el ``InsForgeError`` resultante se propaga sin cambios para que la
    ruta lo traduzca a 409.
    """
    _validate_create_params(params)

    rows = client.execute_sql(_INSERT_ANIMAL_SQL, _build_insert_params(params))
    return _row_to_animal(rows[0])


def list_animals(client: InsForgeClient) -> list[Animal]:
    """Devuelve todos los animales activos, mas recientes primero."""
    rows = client.execute_sql(_LIST_ANIMALS_SQL)
    return [_row_to_animal(row) for row in rows]


def get_animal_by_id(client: InsForgeClient, animal_id: str) -> Animal | None:
    """Devuelve el animal con este id (activo o inactivo), o ``None``."""
    rows = client.execute_sql(_GET_ANIMAL_BY_ID_SQL, [animal_id])
    return _row_to_animal(rows[0]) if rows else None
