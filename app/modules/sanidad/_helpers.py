"""Sanidad module-private helpers.

Lifted out of ``app/modules/sanidad/service.py`` so the main service
module fits the 700-line AGENTS.md rule 21 budget without forcing a
class-level split on a domain already mid-migration to hexagonal.

The helpers remain underscore-prefixed to signal they are still
private to the sanidad domain and not part of any wider public
surface. ``ActuacionSanitaria`` is imported from ``service`` at the
bottom of that module, so the class is fully defined by the time
this module's functions execute (no runtime circular-import hazard).

Note on duplicate helpers (``_required_text``, ``_optional_text``):
those two are intentionally NOT defined here even though the
``_raise_validation_error`` function below calls them. They are
members of ``WATCHED_DUPLICATE_HELPERS`` (AGENTS.md rule 25,
issue #227) and the BASELINE only shrinks — adding a sixth file
would create a new violation. They will move to a shared module
together with ``_raise_validation_error`` as part of #227, not
inside this slice.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.core.data_access import SqlExecutor
from app.modules.sanidad.service import (  # noqa: I001  # see service.py
    _CHECK_TIPO_ACTUACION_SQL,
    _CHECK_VOLUNTARIO_SQL,
    ActuacionSanitaria,
    _optional_text,
    _required_text,
)

# --- row mapping ----------------------------------------------------------


def _row_to_actuacion_sanitaria(row: dict[str, Any]) -> ActuacionSanitaria:
    return ActuacionSanitaria(
        id=str(row["id"]),
        animal_id=str(row["animal_id"]),
        fecha=str(row["fecha"]),
        tipo_actuacion_id=(
            str(row["tipo_actuacion_id"])
            if row.get("tipo_actuacion_id")
            else None
        ),
        veterinario=row.get("veterinario"),
        observaciones=row.get("observaciones"),
        voluntario_id=(
            str(row["voluntario_id"]) if row.get("voluntario_id") else None
        ),
        material_utilizado=row.get("material_utilizado"),
        fecha_alta=str(row["fecha_alta"]) if row.get("fecha_alta") else None,
        updated_at=str(row["updated_at"]) if row.get("updated_at") else None,
        activo=bool(row.get("activo", True)),
    )


# --- date validation ------------------------------------------------------


def _validate_fecha_d24(fecha: str) -> str | None:
    """Pure D-24 reglas 1+2 validation: format + future-date.

    Returns ``None`` when ``fecha`` is valid; returns a Spanish error
    message (suitable for surfacing to the operator via a 422 form
    re-render) when it violates one of the rules.

    **D-24 regla 3** (fecha anterior a ``animales.fecha_alta``) is NOT
    covered by this helper — that check needs the animal row, so it
    lives in the INSERT/UPDATE CTE (``checked_animal`` filter) and the
    disambiguation path of :func:`_raise_validation_error`. Splitting
    the validation in two layers keeps the no-DB validation cheap and
    the FK + fecha_alta check atomic with the write (CRITICAL-1).

    Parameters
    ----------
    fecha:
        The ``fecha`` value from the form, after ``_required_text`` has
        stripped whitespace. Empty / None callers should run ``_required_text``
        first; this helper assumes a non-empty string.
    """
    try:
        parsed = date.fromisoformat(fecha)
    except ValueError:
        return "fecha debe tener formato YYYY-MM-DD"
    if parsed > date.today():
        return f"fecha no puede ser futura (hoy es {date.today().isoformat()})"
    return None


# --- window parsing for the proximity report (issue #652) ----------------


def parse_proximas_window(
    fecha_desde: str, fecha_hasta: str
) -> tuple[date, date]:
    """Parse and validate the proximity report window.

    Pure data validation: lifted out of the route handler so the
    HTTP boundary stays HTTP-only (AGENTS.md rule 28). Raises
    ``ValueError`` with a Spanish message on bad input; callers
    translate to ``HTTPException`` at the HTTP boundary.

    Empty strings, malformed ISO dates, and ``desde > hasta`` all
    raise. The error messages are operator-facing because the route
    handler surfaces them verbatim in a 400 response.
    """
    try:
        desde = date.fromisoformat(fecha_desde)
        hasta = date.fromisoformat(fecha_hasta)
    except ValueError as exc:
        raise ValueError(
            "fecha_desde and fecha_hasta must be ISO dates (YYYY-MM-DD): "
            f"{exc}"
        ) from exc
    if desde > hasta:
        raise ValueError("fecha_desde must be <= fecha_hasta")
    return desde, hasta


# --- CTE disambiguation ---------------------------------------------------


def _raise_validation_error(
    client: SqlExecutor, params: dict[str, Any]
) -> None:
    """Disambiguate a 0-row CTE result by re-running each check.

    Invoked ONLY after the atomic CTE returned 0 rows. The disambiguation
    SELECTs are NOT part of the success path, so the TOCTOU window for
    the success path remains closed. The disambiguation exists purely for
    operator UX: a specific error message lets the form re-render with a
    field-level hint instead of a generic "FK validation failed".

    Handles the D-24 regla 3 disambiguation too: if the animal exists,
    is active, AND has a ``fecha_alta`` that is after the form's ``fecha``,
    raise the D-24-specific message. The animal row's ``fecha_alta`` is
    formatted as ISO date for the operator-facing string.
    """
    animal_id = _required_text(params, "animal_id")
    animal_rows = client.execute_sql(
        "SELECT id, activo, fecha_alta FROM animales WHERE id = $1",
        [animal_id],
    )
    if not animal_rows:
        raise ValueError(
            f"animal_id debe apuntar a un animal activo (no encontrado: {animal_id})"
        )
    if not animal_rows[0].get("activo", False):
        raise ValueError(
            f"animal_id debe apuntar a un animal activo (inactivo: {animal_id})"
        )

    # Animal exists and is active. Now check D-24 regla 3:
    # fecha anterior a animales.fecha_alta (si fecha_alta no es NULL).
    fecha = _required_text(params, "fecha")
    fecha_alta_raw = animal_rows[0].get("fecha_alta")
    if fecha_alta_raw:
        try:
            fecha_parsed = date.fromisoformat(fecha)
        except ValueError:
            # _validate_fecha_d24 already raised on a bad format, so we
            # never reach this branch in practice. If we do (e.g. a
            # future caller bypasses _validate_fecha_d24), fall through to
            # the other checks instead of crashing with a confusing
            # date error here.
            fecha_parsed = None
        if fecha_parsed is not None:
            if isinstance(fecha_alta_raw, datetime):
                fecha_alta_date = fecha_alta_raw.date()
            else:
                fecha_alta_date = date.fromisoformat(str(fecha_alta_raw)[:10])
            if fecha_parsed < fecha_alta_date:
                raise ValueError(
                    f"fecha es anterior al alta del animal "
                    f"({fecha_alta_date.isoformat()})"
                )

    vol_id = _optional_text(params, "voluntario_id")
    if vol_id and not client.execute_sql(_CHECK_VOLUNTARIO_SQL, [vol_id]):
        raise ValueError(
            f"voluntario_id debe apuntar a un voluntario activo (inactivo: {vol_id})"
        )

    tipo_id = _optional_text(params, "tipo_actuacion_id")
    if tipo_id and not client.execute_sql(_CHECK_TIPO_ACTUACION_SQL, [tipo_id]):
        raise ValueError(
            f"tipo_actuacion_id no existe en catalogos_pruebas: {tipo_id}"
        )

    # Should not happen in practice (one of the SELECTs above would have
    # raised). Keep an explicit message so a future regression is loud,
    # not silent.
    raise ValueError(
        "FK validation failed (animal_id, voluntario_id, tipo_actuacion_id) — "
        "none matched"
    )
