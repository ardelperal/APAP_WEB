"""Service layer for the owner-surrender (Cesión por Propietario) workflow.

Issue #41 (INTAKE-03). Mirrors the pattern in ``app.modules.entradas.service``:
routes handle form parsing, auth guards and HTML rendering; this module
owns all SQL and the domain validation. The service is what the routes
and the future API endpoints will both call.

## Workflow

A cesión por propietario is the variant of intake where the owner formally
hands over the animal. The web app models it as TWO linked rows created
in a single ``create_cesion`` call:

1. ``cesiones_propietario`` — the surrender record itself (legacy
   ``TbCesionPorPropietario``, 19 columns preserved 1:1 per the P1
   fidelity invariant of ``docs/proceso.md`` §0). Linked 1-a-1 to
   ``entradas`` via FK UNIQUE on ``entrada_id``; one entrada can have
   at most one cesión.
2. ``contratos`` — the contract metadata row, ``tipo_contrato_id``
   pointing at the ``'Cesión'`` row in ``catalogos_tipos_contrato``
   (CATALOG-01, codigo='Cesión', iniciales='CP') and ``cesion_id``
   pointing at the newly-created cesión. The legacy stored scanned
   images via ``TbContratosAnexos`` (NombreArchivo, blob); the web
   generates PDFs later (Fase 7).

## P1 traceability chain

- Legacy table ``TbCesionPorPropietario`` (Access backend
  ``Registro_APAP_Alcala_datos_18.accdb``) -> new table
  ``cesiones_propietario`` in InsForge.
- Legacy relationship ``TbEntradasTbCesionPorPropietario`` (1-a-1 by
  IDEntrada) -> web FK ``entrada_id UUID NOT NULL UNIQUE REFERENCES
  entradas(id)``.
- Legacy relationship ``TbEntradasTbContratosAnexos`` (1-a-N) -> web
  polymorphic FK on ``contratos.entrada_id|acogida_id|adopcion_id
  |cesion_id`` with the ``contratos_exactly_one_entity`` CHECK
  enforcing exactly one.
- Catalog link: legacy contract numbering used the prefix ``CP``
  (e.g. ``CP0671`` -> 11 production rows as of 2026-07-03); CATALOG-01
  records this in ``catalogos_tipos_contrato`` as codigo='Cesión',
  iniciales='CP', tabla_legacy='TbCesionPorPropietario',
  campo_legacy='NCONTRATOCESION'. The service resolves the contract
  type FK by codigo at create time so the operation is self-contained.

## Deviations from legacy (recorded in decisions-proyecto)

- ``nombre_representante`` is ``NOT NULL`` here even though the legacy
  DDL marks it as ``required=False``. Operators cannot surrender
  without identifying the owner; the web narrows the legacy surface
  to keep the workflow usable. Documented gap-of-fidelity #41.
- ``cartilla_sanitaria`` etc. remain ``TEXT`` rather than ``BOOLEAN`` so
  the legacy ``'Sí'`` (with tilde) round-trips and operators see the
  same vocabulary in the UI.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.data_access import SqlExecutor
from app.core.data_access import BackendError


class CesionConflictError(ValueError):
    """Raised when an attempt to create a cesión collides with the
    1-a-1 UNIQUE FK on ``cesiones_propietario.entrada_id``. Mirrors
    ``EntradaConflictError`` in the entradas module — both translate
    InsForge's 409 envelope into a domain-meaningful exception that
    routes can render as a 409 form error without depending on the
    InsForge envelope shape.
    """


@dataclass(frozen=True, slots=True)
class Cesion:
    """A public service-row representation for ``cesiones_propietario``.

    Field names follow the Access legacy CamelCase Spanish spelling
    (see ``docs/discovery/feature-02-intake-foster-adoption.md`` §"Owner
    surrender"). ``entrada_id`` is the FK to ``entradas.id``.
    """

    id: str
    entrada_id: str
    numero_contrato: str
    nombre_representante: str
    cartilla_sanitaria: str | None = None
    certificado_veterinario: str | None = None
    autorizacion_recogida: str | None = None
    fecha_vacuna_rabia: str | None = None
    numero_colegiado: str | None = None
    numero_colaborador: str | None = None
    dni_representante: str | None = None
    calle_representante: str | None = None
    numero_calle_representante: str | None = None
    piso_representante: str | None = None
    letra_representante: str | None = None
    localidad_representante: str | None = None
    provincia_representante: str | None = None
    cp_representante: str | None = None
    telefono_representante: str | None = None
    email_representante: str | None = None
    hora_cesion: str | None = None
    fecha_alta: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True, slots=True)
class Contrato:
    """A public service-row representation for ``contratos``.

    Just enough to keep the (Cesion, Contrato) return type explicit.
    Only the columns populated by the cesion workflow carry values; the
    other entity FKs (entrada, acogida, adopcion) are ``None`` per the
    ``contratos_exactly_one_entity`` CHECK constraint.
    """

    id: str
    tipo_contrato_id: str
    numero_contrato: str
    fecha: str
    cesion_id: str | None = None
    fecha_alta: str | None = None


# --- SQL constants --------------------------------------------------------

_CHECK_ENTRADA_SQL = "SELECT id FROM entradas WHERE id = $1"

_CHECK_TIPO_CONTRATO_CESION_SQL = (
    "SELECT id FROM catalogos_tipos_contrato WHERE codigo = $1"
)

_INSERT_CESION_COLUMNS = (
    "entrada_id",
    "numero_contrato",
    "nombre_representante",
    "cartilla_sanitaria",
    "certificado_veterinario",
    "autorizacion_recogida",
    "fecha_vacuna_rabia",
    "numero_colegiado",
    "numero_colaborador",
    "dni_representante",
    "calle_representante",
    "numero_calle_representante",
    "piso_representante",
    "letra_representante",
    "localidad_representante",
    "provincia_representante",
    "cp_representante",
    "telefono_representante",
    "email_representante",
    "hora_cesion",
)
_CESION_RETURNING_COLUMNS = (
    "id",
    "entrada_id",
    "numero_contrato",
    "nombre_representante",
    "cartilla_sanitaria",
    "certificado_veterinario",
    "autorizacion_recogida",
    "fecha_vacuna_rabia",
    "numero_colegiado",
    "numero_colaborador",
    "dni_representante",
    "calle_representante",
    "numero_calle_representante",
    "piso_representante",
    "letra_representante",
    "localidad_representante",
    "provincia_representante",
    "cp_representante",
    "telefono_representante",
    "email_representante",
    "hora_cesion",
    "fecha_alta",
    "updated_at",
)
_INSERT_CESION_SQL = (
    "INSERT INTO cesiones_propietario ("  # noqa: S608 constant identifiers; values are $N binds
    + ", ".join(_INSERT_CESION_COLUMNS)
    + ") VALUES ("
    + ", ".join(f"${i+1}" for i in range(len(_INSERT_CESION_COLUMNS)))
    + ") RETURNING "
    + ", ".join(_CESION_RETURNING_COLUMNS)
)

_INSERT_CONTRATO_SQL = (
    "INSERT INTO contratos ("
    "tipo_contrato_id, numero_contrato, fecha, cesion_id"
    ") VALUES ($1, $2, $3, $4) RETURNING "
    "id, tipo_contrato_id, numero_contrato, fecha, cesion_id, fecha_alta"
)

_SELECT_CESION_BY_ENTRADA_SQL = (
    "SELECT "  # noqa: S608 constant identifiers; values are $N binds
    + ", ".join(_CESION_RETURNING_COLUMNS)
    + " FROM cesiones_propietario WHERE entrada_id = $1"
)

_SELECT_CESIONES_SQL = (
    "SELECT "  # noqa: S608 constant identifiers; values are $N binds
    + ", ".join(_CESION_RETURNING_COLUMNS)
    + " FROM cesiones_propietario ORDER BY fecha_alta DESC NULLS LAST"
)

CONTRATO_TIPO_CESION = "Cesión"


# --- helpers --------------------------------------------------------------


def _required_text(params: dict[str, Any], field: str) -> str:
    """Read a required string param or raise ValueError.

    Mirrors the helper in ``app.modules.entradas.service`` so the route
    layer can ``except ValueError`` uniformly across modules.
    """
    value = str(params.get(field) or "").strip()
    if not value:
        raise ValueError(f"{field} is required and cannot be empty")
    return value


def _optional_text(params: dict[str, Any], field: str) -> str | None:
    value = params.get(field)
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def _row_to_cesion(row: dict[str, Any]) -> Cesion:
    """Map a raw DB row dict to the public ``Cesion`` dataclass."""
    return Cesion(
        id=str(row["id"]),
        entrada_id=str(row["entrada_id"]),
        numero_contrato=str(row["numero_contrato"]),
        nombre_representante=str(row["nombre_representante"]),
        cartilla_sanitaria=row.get("cartilla_sanitaria"),
        certificado_veterinario=row.get("certificado_veterinario"),
        autorizacion_recogida=row.get("autorizacion_recogida"),
        fecha_vacuna_rabia=(
            str(row["fecha_vacuna_rabia"])
            if row.get("fecha_vacuna_rabia")
            else None
        ),
        numero_colegiado=row.get("numero_colegiado"),
        numero_colaborador=row.get("numero_colaborador"),
        dni_representante=row.get("dni_representante"),
        calle_representante=row.get("calle_representante"),
        numero_calle_representante=row.get("numero_calle_representante"),
        piso_representante=row.get("piso_representante"),
        letra_representante=row.get("letra_representante"),
        localidad_representante=row.get("localidad_representante"),
        provincia_representante=row.get("provincia_representante"),
        cp_representante=row.get("cp_representante"),
        telefono_representante=row.get("telefono_representante"),
        email_representante=row.get("email_representante"),
        hora_cesion=(
            str(row["hora_cesion"]) if row.get("hora_cesion") else None
        ),
        fecha_alta=str(row["fecha_alta"]) if row.get("fecha_alta") else None,
        updated_at=str(row["updated_at"]) if row.get("updated_at") else None,
    )


def _row_to_contrato(row: dict[str, Any]) -> Contrato:
    return Contrato(
        id=str(row["id"]),
        tipo_contrato_id=str(row["tipo_contrato_id"]),
        numero_contrato=str(row["numero_contrato"]),
        fecha=str(row["fecha"]),
        cesion_id=(
            str(row["cesion_id"]) if row.get("cesion_id") else None
        ),
        fecha_alta=str(row["fecha_alta"]) if row.get("fecha_alta") else None,
    )


def _build_cesion_insert_params(params: dict[str, Any]) -> list[Any]:
    """Positional params for ``_INSERT_CESION_SQL`` (20 columns)."""
    return [
        _required_text(params, "entrada_id"),
        _required_text(params, "numero_contrato"),
        _required_text(params, "nombre_representante"),
        _optional_text(params, "cartilla_sanitaria"),
        _optional_text(params, "certificado_veterinario"),
        _optional_text(params, "autorizacion_recogida"),
        _optional_text(params, "fecha_vacuna_rabia"),
        _optional_text(params, "numero_colegiado"),
        _optional_text(params, "numero_colaborador"),
        _optional_text(params, "dni_representante"),
        _optional_text(params, "calle_representante"),
        _optional_text(params, "numero_calle_representante"),
        _optional_text(params, "piso_representante"),
        _optional_text(params, "letra_representante"),
        _optional_text(params, "localidad_representante"),
        _optional_text(params, "provincia_representante"),
        _optional_text(params, "cp_representante"),
        _optional_text(params, "telefono_representante"),
        _optional_text(params, "email_representante"),
        _optional_text(params, "hora_cesion"),
    ]


def _is_unique_conflict(exc: BackendError) -> bool:
    """Detect the 1-a-1 UNIQUE conflict on ``cesiones_propietario.entrada_id``.

    Same heuristic as ``_is_duplicate_error`` in ``entradas.service``
    but operating on the cesiones table name so a future addition of an
    entrada-level duplicate scenario does not falsely fire here.
    """
    body = str(exc.body).lower()
    return exc.status_code == 409 and (
        "cesiones_propietario" in body
        or "duplicate" in body
        or "unique" in body
    )


# --- public API -----------------------------------------------------------


def create_cesion(
    client: SqlExecutor,
    params: dict[str, Any],
) -> tuple[Cesion, Contrato]:
    """Create an owner-surrender record + its linked contrato.

    Validates first, then emits TWO INSERTs in this order:
    1. ``INSERT INTO cesiones_propietario`` (satisfied alone; the FK
       UNIQUE on ``entrada_id`` is the natural idempotence guard).
    2. ``INSERT INTO contratos`` with ``cesion_id`` pointing at the row
       just created and ``tipo_contrato_id`` resolved from
       ``catalogos_tipos_contrato.codigo = 'Cesión'``.

    Returns the persisted ``Cesion`` and its generated ``Contrato``.

    Raises:
        ValueError: when required fields are blank, the ``entrada_id``
            does not reference an existing entrada, or the type catalog
            is missing the ``'Cesión'`` row (lifecycle configuration
            drift; should never happen in a well-seeded env).
        CesionConflictError: when the entrada already has a cesión
            (UNIQUE FK on ``entrada_id`` violated).
    """
    # 1. Required-field validation — fail fast before any DB call.
    _build_cesion_insert_params(params)

    # 2. Validate the entrada FK — the FK UNIQUE on entrada_id belongs to
    #    cesiones_propietario, so a missing parent would 409 on insert
    #    anyway, but explicit pre-validation gives a friendlier error.
    entrada_id = _required_text(params, "entrada_id")
    if not client.execute_sql(_CHECK_ENTRADA_SQL, [entrada_id]):
        raise ValueError(
            f"entrada_id does not reference an existing entrada: {entrada_id!r}"
        )

    # 3. Resolve the contrato type FK (catalogos_tipos_contrato.codigo).
    tipo_rows = client.execute_sql(
        _CHECK_TIPO_CONTRATO_CESION_SQL, [CONTRATO_TIPO_CESION]
    )
    if not tipo_rows:
        raise ValueError(
            "catalogos_tipos_contrato is missing the 'Cesión' row; "
            "re-run ensure_catalogs() or seed CATALOG-01"
        )
    tipo_contrato_id = str(tipo_rows[0]["id"])

    # 4. INSERT the cesion. UNIQUE conflicts become CesionConflictError.
    try:
        cesion_rows = client.execute_sql(
            _INSERT_CESION_SQL, _build_cesion_insert_params(params)
        )
    except BackendError as exc:
        if _is_unique_conflict(exc):
            raise CesionConflictError(
                "ya existe una cesión para esta entrada"
            ) from exc
        raise
    cesion = _row_to_cesion(cesion_rows[0])

    # 5. INSERT the contrato linked to the cesion. fecha defaults to the
    #    cesion day; the legacy contract number (CPxxxx) carries over
    #    verbatim from ``numero_contrato``.
    fecha_param = (
        _optional_text(params, "fecha_cesion")
        or (cesion.fecha_alta or "")[:10]
    )
    contrato_rows = client.execute_sql(
        _INSERT_CONTRATO_SQL,
        [tipo_contrato_id, cesion.numero_contrato, fecha_param, cesion.id],
    )
    contrato = _row_to_contrato(contrato_rows[0])

    return cesion, contrato


def get_cesion_by_entrada_id(
    client: SqlExecutor,
    entrada_id: str,
) -> Cesion | None:
    """Return the cesión linked to an entrada, or ``None`` when missing.

    The relationship is 1-a-1 (FK UNIQUE on ``entrada_id`` in
    ``cesiones_propietario``) so at most one row can exist per entrada.
    """
    rows = client.execute_sql(_SELECT_CESION_BY_ENTRADA_SQL, [entrada_id])
    return _row_to_cesion(rows[0]) if rows else None


def list_cesiones(client: SqlExecutor) -> list[Cesion]:
    """Return all cesiones, newest first."""
    rows = client.execute_sql(_SELECT_CESIONES_SQL)
    return [_row_to_cesion(row) for row in rows]


__all__ = [
    "Cesion",
    "CesionConflictError",
    "Contrato",
    "CONTRATO_TIPO_CESION",
    "create_cesion",
    "get_cesion_by_entrada_id",
    "list_cesiones",
]
