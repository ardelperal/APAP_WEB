"""Voluntarios service: la unica capa que habla con InsForgeClient para el registro de voluntarios.

Es la contraparte del ``app.modules.animals.service``: framework-
agnostica, valida antes de SQL, devuelve dataclasses, propaga
``InsForgeError`` sin cambios. Las rutas HTTP son una capa fina
encima.

Politica de validacion:

- ``Voluntario`` (nombre) es obligatorio.
- ``Email`` y ``DNI`` son UNIQUE en la DB; un duplicado propaga el
  ``InsForgeError`` de InsForge tal cual para que la ruta traduzca a
  409.
- ``activo`` empieza en ``true``; ``deactivate_voluntario`` lo pone en
  ``false`` preservando las FK references (intakes, foster stays,
  adopciones, terapias). NUNCA se hace DELETE fisico.
- Los roles se gestionan en una tabla aparte (``roles_voluntario``)
  con junction pattern. La asignacion de roles valida que el
  voluntario este activo (BR2 del discovery).

El schema se define como constante aqui (mismo patron que
``app.core.auth`` y ``app.modules.animals.service``) para que las
queries ``INSERT`` / ``SELECT`` esten en un solo lugar.

Mapeo de campos (legacy ``TbVoluntariosParaAutorrellenables`` ->
dataclass):

  Voluntario   -> Voluntario
  Tel1         -> Tel1
  Tel2         -> Tel2
  Email        -> Email
  (mejora)     -> id (UUID PK)
  (mejora)     -> DNI UNIQUE (para dedup en VOL-03)
  (mejora)     -> fecha_alta (created_at)
  (mejora)     -> updated_at
  (mejora)     -> activo (soft-delete)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.core.insforge import InsForgeClient


VALID_ROL_TYPES = frozenset({"intake", "seguimiento", "acogida", "salud"})


class RolVoluntario(str, Enum):
    INTAKE = "intake"
    SEGUIMIENTO = "seguimiento"
    ACOGIDA = "acogida"
    SALUD = "salud"


@dataclass(frozen=True, slots=True)
class Voluntario:
    """Una fila de la tabla ``voluntarios``, tal como la devuelve el service.

    Los nombres de los campos son los del schema en CamelCase Spanish
    (matching el legacy ``TbVoluntariosParaAutorrellenables``). Las
    cinco columnas de sistema (``id``, ``fecha_alta``, ``updated_at``,
    ``activo`` + la mejora ``DNI``) son las que el nuevo schema anade
    sobre el legacy.
    """

    id: str
    Voluntario: str
    activo: bool = True
    Tel1: str | None = None
    Tel2: str | None = None
    Email: str | None = None
    DNI: str | None = None
    fecha_alta: str | None = None
    updated_at: str | None = None


_INSERT_COLUMNS = (
    "Voluntario",
    "Tel1",
    "Tel2",
    "Email",
    "DNI",
)


_SELECT_COLUMNS = (
    "id",
    "Voluntario",
    "Tel1",
    "Tel2",
    "Email",
    "DNI",
    "fecha_alta",
    "updated_at",
    "activo",
)


def _row_to_voluntario(row: dict[str, Any]) -> Voluntario:
    """Mapea una fila cruda de la DB (dict) al dataclass ``Voluntario``."""
    return Voluntario(
        id=str(row["id"]),
        Voluntario=str(row["Voluntario"]),
        activo=bool(row.get("activo", True)),
        Tel1=row.get("Tel1"),
        Tel2=row.get("Tel2"),
        Email=row.get("Email"),
        DNI=row.get("DNI"),
        fecha_alta=str(row["fecha_alta"]) if row.get("fecha_alta") else None,
        updated_at=str(row["updated_at"]) if row.get("updated_at") else None,
    )


def _validate_create_params(params: dict[str, Any]) -> None:
    """Valida los campos provistos antes de cualquier SQL.

    Levanta ``ValueError`` con mensaje accionable si algo falta.
    """
    Voluntario = (params.get("Voluntario") or "").strip()
    if not Voluntario:
        raise ValueError("Voluntario (nombre) es obligatorio y no puede estar vacio")

    email = (params.get("Email") or "").strip()
    if email and "@" not in email:
        raise ValueError("Email no tiene formato valido")


_INSERT_VOLUNTARIO_SQL = f"""
INSERT INTO voluntarios ({", ".join(_INSERT_COLUMNS)})
VALUES ({", ".join(f"${i+1}" for i in range(len(_INSERT_COLUMNS)))})
RETURNING {", ".join(_SELECT_COLUMNS)}
"""

_LIST_VOLUNTARIOS_SQL = f"""
SELECT {", ".join(_SELECT_COLUMNS)}
FROM voluntarios
WHERE activo = true
ORDER BY Voluntario ASC
"""

_GET_VOLUNTARIO_BY_ID_SQL = f"""
SELECT {", ".join(_SELECT_COLUMNS)}
FROM voluntarios
WHERE id = $1
"""

_LIST_ROLES_SQL = """
SELECT tipo_rol
FROM roles_voluntario
WHERE voluntario_id = $1
ORDER BY tipo_rol ASC
"""


def _build_insert_params(params: dict[str, Any]) -> list[Any]:
    """Parametros en el orden de ``_INSERT_COLUMNS``."""
    def _opt(key: str) -> str | None:
        value = params.get(key)
        if value is None:
            return None
        value = str(value).strip()
        return value or None

    return [
        params.get("Voluntario", "").strip(),
        _opt("Tel1"),
        _opt("Tel2"),
        _opt("Email"),
        _opt("DNI"),
    ]


def create_voluntario(client: InsForgeClient, params: dict[str, Any]) -> Voluntario:
    """Inserta un voluntario. ``Voluntario`` (nombre) es obligatorio.

    Un Email o DNI duplicado se surface como respuesta no-2xx de
    InsForge; el ``InsForgeError`` resultante se propaga sin cambios
    para que la ruta lo traduzca a 409.
    """
    _validate_create_params(params)
    rows = client.execute_sql(_INSERT_VOLUNTARIO_SQL, _build_insert_params(params))
    return _row_to_voluntario(rows[0])


def list_voluntarios(client: InsForgeClient) -> list[Voluntario]:
    """Devuelve todos los voluntarios activos, ordenados alfabeticamente."""
    rows = client.execute_sql(_LIST_VOLUNTARIOS_SQL)
    return [_row_to_voluntario(row) for row in rows]


def get_voluntario_by_id(client: InsForgeClient, voluntario_id: str) -> Voluntario | None:
    """Devuelve el voluntario con este id (activo o inactivo), o ``None``."""
    rows = client.execute_sql(_GET_VOLUNTARIO_BY_ID_SQL, [voluntario_id])
    return _row_to_voluntario(rows[0]) if rows else None


def list_roles(client: InsForgeClient, voluntario_id: str) -> list[str]:
    """Devuelve la lista de roles asignados al voluntario, ordenados."""
    rows = client.execute_sql(_LIST_ROLES_SQL, [voluntario_id])
    return [str(row["tipo_rol"]) for row in rows]
