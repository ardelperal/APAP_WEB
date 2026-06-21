"""Diff engine for the migration module (LIFECYCLE-03 / migration-01).

This module is the **brain of the migration**: given a legacy snapshot
(from :mod:`app.core.migration.legacy_reader`) and a web snapshot
(from :mod:`app.core.migration.web_reader`), it classifies each row
as one of:

  - ``INSERT``: the row exists in the source snapshot but not in the
    target → must be created on the target side.
  - ``UPDATE``: the row exists in both snapshots but the relevant
    fields differ → must be updated on the target side.
  - ``DELETE``: the row exists in the target snapshot but not in the
    source → must be removed from the target side (subject to
    ``--delete-orphans`` in the applier).
  - ``NOOP``: the row exists in both snapshots and the fields are
    identical → nothing to do.

It also detects **modified_both_sides** conflicts (regla #13475 v2:
active-passive estricto): if a row was modified in BOTH the legacy and
the web since ``last_sync_at``, the diff is flagged ``conflict=True``
and the applier will NOT apply it without an explicit operator
decision (``--conflict web|legacy|abort``).

**Matching strategies** (per design §5):

- **Natural key** (animales, voluntarios): both sides share a column
  with the same value (``NCHIP`` / ``Voluntario``). The diff engine
  matches on the value of ``mapping.key_field``.
- **sync_state mapping** (entradas, acogidas, adopciones): the legacy
  PK is an ``INTEGER`` (``IDEntrada``) and the web PK is a ``UUID``
  (``id``). The diff engine resolves the legacy PK to the web UUID
  via :func:`app.core.migration.sync_state.lookup_web_pk`.

The two directions (``legacy → web`` and ``web → legacy``) are
implemented as two separate functions because the *meaning* of
INSERT/DELETE inverts: in ``legacy → web``, INSERT means "create this
row on the web"; in ``web → legacy``, INSERT means "write this web
row to the legacy .accdb". The applier (PR 5/6) uses the direction
to pick the right SQL generator.

**Pure functions**: this module has NO side effects and NO I/O. It
takes snapshots in, returns diffs out. All tests are pure unit tests
with synthetic ``dict`` snapshots — no MCP, no Dysflow, no InsForge.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.core.migration.reporting import Diff
from app.core.migration.sync_state import (
    SyncState,
    lookup_web_pk,
)

if TYPE_CHECKING:
    # Solo para anotaciones; el import real se hace lazy en
    # ``diff_legacy_to_web`` / ``diff_web_to_legacy`` para evitar el
    # ciclo ``__init__`` → ``diff_engine`` → ``mappings`` → ``__init__``.
    from app.core.migration.mappings import TableMapping

#: Fields that NEVER participate in the diff comparison.
#:
#: - ``id`` — web PK (UUID v4); not a business value.
#: - ``updated_at`` — timestamp the applier rewrites on every write;
#:   comparing it always yields UPDATE, falsa señal de cambio.
#: - ``fecha_alta`` — set once at INSERT time; not a "modification"
#:   signal (it's a creation timestamp).
#: - ``activo`` — soft-delete flag managed by the applier + reconcile
#:   layer, not by the diff engine.
#:
#: The diff engine excludes these from the "did this row change?" check
#: even when they appear in the legacy snapshot (e.g. ``updated_at``
#: stamped by Dysflow in a recent dump).
DEFAULT_IGNORE_FIELDS: frozenset[str] = frozenset({"id", "updated_at", "fecha_alta", "activo"})


@dataclass(frozen=True, slots=True)
class Conflict:
    """Un desacuerdo detectado por el diff engine (regla #13475 v2).

    Se emite cuando una fila fue modificada en AMBAS apps desde
    ``last_sync_at``. El applier NO aplica el diff asociado sin
    decisión explícita del operador (``--conflict web|legacy|abort``).

    A diferencia de :class:`app.core.migration.reporting.Conflict`
    (que es el dataclass serializable dentro de ``MigrationReport``),
    esta clase es interna al diff engine — se usa como payload de la
    lista ``conflicts`` retornada por :func:`diff_legacy_to_web` /
    :func:`diff_web_to_legacy` y se convierte luego al dataclass
    serializable en la capa de reporting.
    """

    table: str
    legacy_pk: int | str | None
    web_pk: str | None
    fields: frozenset[str]
    legacy_state: dict[str, Any] | None = None
    web_state: dict[str, Any] | None = None
    last_sync_at: datetime | None = None


# --- Public API: diff computations ----------------------------------------


def diff_legacy_to_web(
    legacy_snapshot: dict[str, list[dict[str, Any]]],
    web_snapshot: dict[str, list[dict[str, Any]]],
    mapping: TableMapping,
    sync_state: SyncState,
) -> list[Diff]:
    """Compara el snapshot legacy contra el snapshot web y retorna diffs.

    "Source" es legacy, "target" es web. INSERTs son filas nuevas en
    legacy que la web no tiene; DELETEs son filas web sin contraparte
    legacy (huérfanas, requieren ``--delete-orphans`` para aplicarse).

    Args:
        legacy_snapshot: ``{web_table: [row, ...]}`` desde
            :func:`app.core.migration.legacy_reader.load_legacy_snapshot`.
        web_snapshot: ``{web_table: [row, ...]}`` desde
            :func:`app.core.migration.web_reader.load_web_snapshot`.
        mapping: spec pydantic de la tabla (de
            :func:`app.core.migration.mappings.load_mapping`).
        sync_state: estado persistente (para resolver legacy→web PK
            en tablas sin natural key, y para ``last_sync_at``).

    Returns:
        Lista de :class:`Diff` con la clasificación por fila. La lista
        puede estar vacía si ambos snapshots están vacíos.
    """
    return _diff_snapshots(
        source=legacy_snapshot,
        target=web_snapshot,
        mapping=mapping,
        sync_state=sync_state,
    )


def diff_web_to_legacy(
    web_snapshot: dict[str, list[dict[str, Any]]],
    legacy_snapshot: dict[str, list[dict[str, Any]]],
    mapping: TableMapping,
) -> list[Diff]:
    """Inverse direction: web → legacy.

    INSERTs son filas web nuevas (sin contraparte legacy); DELETEs son
    filas legacy que la web ya no tiene.

    Nota: la dirección inversa NO usa ``sync_state`` para matching
    (porque la fuente ES el web, donde la PK es siempre ``id`` UUID
    y la fila YA está en su forma canónica). Para tablas con natural
    key compartido (animales, voluntarios) el match es por valor del
    natural key.

    Args:
        web_snapshot: ``{web_table: [row, ...]}`` desde
            :func:`app.core.migration.web_reader.load_web_snapshot`.
        legacy_snapshot: ``{web_table: [row, ...]}`` desde
            :func:`app.core.migration.legacy_reader.load_legacy_snapshot`.
        mapping: spec pydantic de la tabla.

    Returns:
        Lista de :class:`Diff`. Conflict detection está deshabilitada
        en esta dirección (regla #13475 v2: el web es el active side,
        el legacy es el passive mirror; un cambio en ambos significa
        que el legacy está desincronizado pero el web manda).
    """
    # Para inverse, usamos el mismo algoritmo pero sin
    # conflict detection y sin sync_state (la PK web ya es UUID).
    return _diff_snapshots(
        source=web_snapshot,
        target=legacy_snapshot,
        mapping=mapping,
        sync_state=SyncState(),  # dummy — no se usa en inverse
        detect_conflicts=False,
        source_is_web=True,
    )


# --- Internal: core algorithm ---------------------------------------------


def _diff_snapshots(
    *,
    source: dict[str, list[dict[str, Any]]],
    target: dict[str, list[dict[str, Any]]],
    mapping: TableMapping,
    sync_state: SyncState,
    detect_conflicts: bool = True,
    source_is_web: bool = False,
) -> list[Diff]:
    """Core del algoritmo de diff.

    Para cada fila en ``source``:
      1. Resolver la PK de la fila (``source_pk``).
      2. Encontrar la fila correspondiente en ``target`` (vía natural
         key o sync_state).
      3. Si no hay match → INSERT.
      4. Si hay match:
         - Comparar campos comparables (intersección o via mapping.columns).
         - Si idénticos → NOOP.
         - Si difieren → UPDATE con ``changed_fields``; además, si
           ``detect_conflicts`` y ambos lados se modificaron desde
           ``last_sync_at``, marcar ``conflict=True``.

    Para cada fila en ``target`` que NO fue matcheada por una fila
    source → DELETE (huérfana en target).
    """
    table = mapping.web_table
    source_rows = source.get(table, [])
    target_rows = target.get(table, [])

    # Fast index del target por PK de target.
    target_by_pk = _index_target(target_rows, mapping, source_is_web=source_is_web)

    # PKs del target que fueron matcheadas por una fila source.
    matched_target_pks: set[str] = set()

    last_sync_at = sync_state.tables.get(table)
    last_sync_dt = last_sync_at.last_sync_at if last_sync_at else None

    diffs: list[Diff] = []

    # -- Phase 1: classify each source row ----------------------------
    for source_row in source_rows:
        source_pk_value = _extract_source_pk(source_row, mapping, source_is_web)
        if source_pk_value is None:
            # Sin PK en la fila source: no podemos matchear nada.
            # En producción esto sería un error de schema; en tests
            # lo skipeamos silenciosamente.
            continue

        target_row, target_pk_value = _find_target_row(
            source_pk_value=source_pk_value,
            source_row=source_row,
            target_rows=target_rows,
            target_by_pk=target_by_pk,
            mapping=mapping,
            sync_state=sync_state,
            source_is_web=source_is_web,
        )

        if target_row is None:
            diffs.append(
                Diff(
                    op="INSERT",
                    key=str(source_pk_value),
                    table=table,
                    legacy_pk=(source_pk_value if not source_is_web else None),
                    web_pk=(source_pk_value if source_is_web else None),
                    legacy_row=(source_row if not source_is_web else None),
                    web_row=(source_row if source_is_web else None),
                    reason="source_new",
                )
            )
            continue

        matched_target_pks.add(str(target_pk_value))

        changed = _compute_changed_fields(source_row, target_row, mapping)
        if not changed:
            diffs.append(
                Diff(
                    op="NOOP",
                    key=str(source_pk_value),
                    table=table,
                    legacy_pk=(source_pk_value if not source_is_web else None),
                    web_pk=(target_pk_value if target_pk_value else None),
                    legacy_row=(source_row if not source_is_web else None),
                    web_row=(target_row if not source_is_web else None),
                    reason="identical",
                )
            )
            continue

        # Hay cambios en los campos comparables.
        is_conflict = False
        if detect_conflicts and last_sync_dt is not None:
            web_for_check = target_row if not source_is_web else source_row
            legacy_for_check = source_row if not source_is_web else target_row
            is_conflict = _is_modified_both_sides(
                legacy_row=legacy_for_check,
                web_row=web_for_check,
                mapping=mapping,
                last_sync_at=last_sync_dt,
            )

        diffs.append(
            Diff(
                op="UPDATE",
                key=str(source_pk_value),
                table=table,
                legacy_pk=(source_pk_value if not source_is_web else None),
                web_pk=(target_pk_value if target_pk_value else None),
                legacy_row=(source_row if not source_is_web else None),
                web_row=(target_row if not source_is_web else None),
                changed_fields=changed,
                conflict=is_conflict,
                reason="modified_both_sides" if is_conflict else "fields_changed",
            )
        )

    # -- Phase 2: DELETE for target rows not matched -------------------
    for target_row in target_rows:
        target_pk_value = _extract_target_pk(target_row, mapping, source_is_web)
        if target_pk_value is None:
            continue
        if str(target_pk_value) in matched_target_pks:
            continue

        # Para el reporte, ``legacy_pk`` debe ser identificable incluso
        # en DELETEs (donde la fila legacy ya no existe). En el caso
        # natural-key (key_field == legacy_key), el valor del natural
        # key vive en el target row → lo usamos como legacy_pk (es la
        # "huella" que la legacy habría tenido). Para tablas sin
        # natural key, ``legacy_pk`` queda ``None`` (el operador debe
        # ver el ``legacy_row`` o el ``web_pk`` para entender).
        legacy_pk_for_diff: int | str | None = None
        web_pk_for_diff: str | None = None
        if source_is_web:
            # source = web, target = legacy. DELETEs son legacy rows
            # que la web ya no tiene.
            legacy_pk_for_diff = target_pk_value
            web_pk_for_diff = None
        else:
            # source = legacy, target = web. DELETEs son web rows
            # sin contraparte legacy.
            legacy_pk_for_diff = target_row.get(mapping.key_field)
            web_pk_for_diff = target_pk_value

        diffs.append(
            Diff(
                op="DELETE",
                key=str(target_pk_value),
                table=table,
                legacy_pk=legacy_pk_for_diff,
                web_pk=web_pk_for_diff,
                legacy_row=(target_row if source_is_web else None),
                web_row=(target_row if not source_is_web else None),
                reason="target_orphan",
            )
        )

    return diffs


# --- Internal: indexing & matching ---------------------------------------


def _index_target(
    target_rows: list[dict[str, Any]],
    mapping: TableMapping,
    source_is_web: bool = False,
) -> dict[str, dict[str, Any]]:
    """Indexa las filas target por la PK que el matching va a usar.

    Para matching por natural key (``key_field == legacy_key``, ej:
    ``NCHIP`` en animales): indexa por el valor del natural key,
    sin importar cuál lado es source y cuál es target.

    Para matching via sync_state (entradas/acogidas/adopciones),
    con source=legacy: indexa por ``id`` (UUID), porque la lookup es
    ``web_uuid → web_row`` y siempre es por ``id`` web. Con
    source=web (inverse), la sync_state no se usa (devolvemos dict
    vacío porque ``_find_target_row`` retorna ``None`` directamente
    en inverse+sync_state — la inversa solo soporta natural key v1).
    """
    index: dict[str, dict[str, Any]] = {}
    if mapping.key_field == mapping.legacy_key:
        pk_col = mapping.key_field
        for row in target_rows:
            pk_val = row.get(pk_col)
            if pk_val is not None:
                index[str(pk_val)] = row
        return index
    # key_field != legacy_key → matching via sync_state (legacy→web
    # solamente). En inverse, no matcheamos nada por esta vía.
    if source_is_web:
        return index
    for row in target_rows:
        pk_val = row.get("id")
        if pk_val is not None:
            index[str(pk_val)] = row
    return index


def _extract_source_pk(
    source_row: dict[str, Any],
    mapping: TableMapping,
    source_is_web: bool,
) -> int | str | None:
    """Extrae el valor PK de una fila source.

    - Si source es web (``source_is_web=True``) y el mapping usa
      natural key (``key_field == legacy_key``): usa el natural key
      (mismo valor que el legacy, ej: ``NCHIP="X1"``).
    - Si source es web y matching es via sync_state: usa ``id``
      (UUID) — la inversa solo aplica a tablas con natural key en v1.
    - Si source es legacy: usa ``legacy_key`` (sea natural key o no).
    """
    if source_is_web:
        if mapping.key_field == mapping.legacy_key:
            return source_row.get(mapping.key_field)
        return source_row.get("id")
    return source_row.get(mapping.legacy_key)


def _extract_target_pk(
    target_row: dict[str, Any],
    mapping: TableMapping,
    source_is_web: bool,
) -> str | None:
    """Extrae el PK de una fila target para detectar huérfanas."""
    if source_is_web:
        # target = legacy, source = web → target_pk = legacy_pk
        return target_row.get(mapping.legacy_key)
    # target = web → target_pk = id (UUID)
    return target_row.get("id")


def _find_target_row(
    *,
    source_pk_value: int | str,
    source_row: dict[str, Any],
    target_rows: list[dict[str, Any]],
    target_by_pk: dict[str, dict[str, Any]],
    mapping: TableMapping,
    sync_state: SyncState,
    source_is_web: bool,
) -> tuple[dict[str, Any] | None, str | None]:
    """Encuentra la fila target correspondiente al source_pk.

    Returns:
        ``(target_row, target_pk_value)`` o ``(None, None)`` si no
        hay match.
    """
    if source_is_web:
        # source = web (PK = id UUID); target = legacy (PK = legacy_key).
        # Matching por natural key si comparten columna, sino no match
        # (la dirección inversa solo soporta natural key matching; para
        # sync_state matching, el applier no necesita diff — vuelca
        # directamente).
        if mapping.key_field != mapping.legacy_key:
            return None, None
        # Ambos lados tienen el mismo valor en ``key_field`` (=legacy_key).
        target_row = target_by_pk.get(str(source_pk_value))
        if target_row is None:
            return None, None
        return target_row, str(source_pk_value)

    # source = legacy.
    if mapping.key_field == mapping.legacy_key:
        # Natural key: el valor de la legacy_key == valor de la key_field
        # en el target.
        target_row = target_by_pk.get(str(source_pk_value))
        if target_row is None:
            return None, None
        target_pk = target_row.get("id")
        return target_row, (str(target_pk) if target_pk is not None else None)

    # source = legacy, matching via sync_state.
    table = mapping.web_table
    web_uuid = lookup_web_pk(sync_state, table, source_pk_value)
    if web_uuid is None:
        # Legacy_pk no tiene contraparte web registrada → INSERT.
        return None, None
    target_row = target_by_pk.get(str(web_uuid))
    if target_row is None:
        # sync_state dice que existe un web_uuid pero no está en el
        # snapshot actual (probablemente un DELETE en web) → INSERT
        # de la fila legacy la recreará.
        return None, None
    return target_row, str(web_uuid)


# --- Internal: field comparison -------------------------------------------


def _compute_changed_fields(
    source_row: dict[str, Any],
    target_row: dict[str, Any],
    mapping: TableMapping,
) -> tuple[str, ...]:
    """Compara source vs target y retorna los campos que difieren.

    Estrategia:
      - Si ``mapping.columns`` tiene entries con ``legacy_column``
        no nulo: comparar columna por columna via el mapping (maneja
        renames como ``Tamanyos`` legacy ↔ ``Tamano`` web).
      - Si no: intersección de keys (excluyendo ``DEFAULT_IGNORE_FIELDS``).
        Esto cubre el caso de tests con mapping sintético ``columns=[]``
        y producción donde las columnas legacy/web tienen el mismo nombre.

    Returns:
        Tupla de nombres de campo (en el espacio del ``target``/web)
        que difieren. Vacío si son idénticos.
    """
    changed: list[str] = []

    comparable_pairs = _iter_comparable_pairs(source_row, target_row, mapping)

    for target_field, source_val, target_val in comparable_pairs:
        if not _values_equal(source_val, target_val):
            changed.append(target_field)

    return tuple(changed)


def _iter_comparable_pairs(
    source_row: dict[str, Any],
    target_row: dict[str, Any],
    mapping: TableMapping,
) -> Iterable[tuple[str, Any, Any]]:
    """Yields ``(target_field_name, source_value, target_value)``.

    Dos modos:
      - **Mapping-driven** (cuando ``mapping.columns`` está poblado):
        itera cada ``ColumnMapping`` con ``legacy_column`` no nulo;
        produce el ``web_column`` como nombre del campo target.
      - **Intersection** (fallback): itera la intersección de keys
        entre ``source_row`` y ``target_row`` (que en legacy→web es
        source=legacy, target=web), excluyendo
        :data:`DEFAULT_IGNORE_FIELDS`.
    """
    if mapping.columns:
        for cm in mapping.columns:
            if cm.legacy_column is None:
                # Web-only column — no hay valor legacy para comparar.
                continue
            source_val = source_row.get(cm.legacy_column)
            target_val = target_row.get(cm.web_column)
            if source_val is None and target_val is None:
                continue
            yield cm.web_column, source_val, target_val
        return

    # Fallback: intersección de keys.
    shared_keys = set(source_row.keys()) & set(target_row.keys())
    for key in sorted(shared_keys):
        if key in DEFAULT_IGNORE_FIELDS:
            continue
        yield key, source_row.get(key), target_row.get(key)


def _values_equal(a: Any, b: Any) -> bool:
    """Compara dos valores del snapshot.

    Trato especial para ``None`` (ambos None → iguales), ``datetime``
    (timezone-aware vs naive se comparan normalizando a UTC), y todo
    lo demás vía ``==``.

    Si los tipos difieren pero los valores son comparables (ej: int
    ``1`` vs str ``"1"``), retorna ``False`` para no generar falsos
    NOOPs — el operador puede haber editado un valor en un lado.
    """
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if isinstance(a, datetime) and isinstance(b, datetime):
        # Normalizar a UTC para comparación segura.
        a_utc = a if a.tzinfo else a.replace(tzinfo=UTC)
        b_utc = b if b.tzinfo else b.replace(tzinfo=UTC)
        return a_utc == b_utc
    if isinstance(a, datetime) or isinstance(b, datetime):
        # Tipos mixtos (uno datetime, otro string) — no iguales.
        return False
    return a == b


# --- Internal: conflict detection ----------------------------------------


def _is_modified_both_sides(
    *,
    legacy_row: dict[str, Any],
    web_row: dict[str, Any],
    mapping: TableMapping,
    last_sync_at: datetime,
) -> bool:
    """True si legacy Y web se modificaron desde ``last_sync_at``.

    Lógica (design §9):
      - ``web_updated = parse(web_row['updated_at'])``.
      - ``legacy_updated = max(parse(legacy_row[f]) for f in date_fields)``
        (algunas tablas tienen varias fechas candidatas).
      - Conflicto si AMBAS son > ``last_sync_at``.

    Se normaliza ``last_sync_at`` a UTC-aware antes de comparar para
    evitar ``TypeError: can't compare offset-naive and offset-aware
    datetime`` cuando el caller pasa un datetime naive (típico en
    tests con ``datetime(2026, 6, 15)`` sin ``tzinfo``).
    """
    last_sync_norm = _normalize_to_utc(last_sync_at)
    web_updated = _parse_datetime(web_row.get("updated_at"))
    if web_updated is None or web_updated <= last_sync_norm:
        return False

    legacy_dates: list[datetime] = []
    for field_name in mapping.date_fields:
        dt = _parse_datetime(legacy_row.get(field_name))
        if dt is not None:
            legacy_dates.append(dt)
    if not legacy_dates:
        return False
    legacy_updated = max(legacy_dates)
    return legacy_updated > last_sync_norm


def _normalize_to_utc(dt: datetime) -> datetime:
    """Normaliza un datetime a UTC-aware (naive → asume UTC, aware → convierte)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _parse_datetime(value: Any) -> datetime | None:
    """Parse robusto de un valor que puede ser datetime, ISO str, o None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    return None


__all__ = [
    "Conflict",
    "DEFAULT_IGNORE_FIELDS",
    "diff_legacy_to_web",
    "diff_web_to_legacy",
]
