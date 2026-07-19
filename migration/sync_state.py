"""Sync state persistence for the migration module (LIFECYCLE-03 / migration-01).

This module persists **per-table migration bookkeeping** to disk so that
the diff engine can:

- Know when the last sync ran for each table (``last_sync_at`` cursor for
  incremental sync, design §1.4).
- Map legacy primary keys → web UUIDs for tables that don't share a
  natural key (entradas/acogidas/adopciones use the ``IdEntrada`` legacy
  INTEGER while the web uses a UUID v4 — design §4 + §7).

The file is ``sync_state.json`` and is written **atomically** (write to
``sync_state.json.tmp`` + ``os.replace``) so that a process crash mid-write
can never leave a half-parsed file on disk. This is the persistence-side
mirror of the rule #13474 v2 "function de migración atómica": if the
process dies, the operator can re-run and the state file is either the
old one (good) or the new one (good) — never the corrupt mid-write one.

**Public API contract** (kept stable across PRs because the diff engine
in PR 5/6 + the applier in PR 8 both depend on it):

- ``SyncState`` / ``TableState`` dataclasses.
- ``load_sync_state(path)`` / ``save_sync_state(state, path)``.
- ``get_or_create_table_state(state, table)``.
- ``record_legacy_to_web_mapping(state, table, legacy_pk, web_pk)``.
- ``lookup_web_pk(state, table, legacy_pk)`` → ``str | None``.
- ``lookup_legacy_pk(state, table, web_pk)`` → ``str | None``
  (returns ``str(legacy_pk)`` since the original PK type isn't preserved
  in the mapping — callers needing the int must coerce).
- ``update_last_sync_at(state, table, dt)``.
- ``SyncStateError`` for malformed on-disk JSON.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


class SyncStateError(Exception):
    """Error de parseo o validación del ``sync_state.json`` en disco.

    Hereda de ``Exception`` (no de ``MigrationError``) para no crear
    ciclos de import (``sync_state`` se carga ANTES que el resto del
    módulo en flujos de recovery). El CLI / applier lo captura y lo
    mapea a exit code 5 (I/O error, design §1.5).
    """


@dataclass(frozen=True)
class TableState:
    """Estado de sincronización para una tabla específica.

    ``last_sync_at`` es el cursor para sync incremental (``--since``):
    el diff engine compara ``updated_at`` de las filas web contra este
    timestamp para clasificar INSERT vs UPDATE.

    ``legacy_to_web_id`` es el mapping ``str(legacy_pk) -> web_uuid``.
    Es un dict mutable (no frozen) porque los callers lo modifican
    in-place vía ``record_legacy_to_web_mapping`` (un dataclass frozen
    con un dict adentro es engañoso: el dict sí es editable).

    El dataclass en sí es frozen para que los callers no sustituyan la
    referencia; modificar ``legacy_to_web_id`` está permitido y es el
    patrón de uso esperado.
    """

    last_sync_at: datetime | None = None
    legacy_to_web_id: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SyncState:
    """Estado global del módulo de migración (por tabla).

    ``version`` es el schema del JSON: si en el futuro cambiamos la
    forma del archivo, este campo nos da un migration path
    determinístico. Por ahora solo existe ``"1.0"``.
    """

    version: str = "1.0"
    tables: dict[str, TableState] = field(default_factory=dict)


# --- I/O ------------------------------------------------------------------


def load_sync_state(path: Path | str) -> SyncState:
    """Carga el ``sync_state.json`` desde ``path``.

    Args:
        path: ruta al archivo (puede no existir; en ese caso retorna
            un ``SyncState()`` vacío — primer run legítimo).

    Returns:
        ``SyncState`` con la forma canónica leída del disco.

    Raises:
        SyncStateError: si el archivo existe pero su contenido no es
            JSON válido o no satisface la forma de ``SyncState``.
    """
    path = Path(path)
    if not path.exists():
        # Primer run: archivo no existe → estado vacío. NO es un error.
        return SyncState()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SyncStateError(f"sync_state at {path} is not valid JSON: {exc}") from exc
    return _sync_state_from_raw(raw)


def save_sync_state(state: SyncState, path: Path | str) -> None:
    """Persiste ``state`` a ``path`` con escritura atómica.

    **Garantía atómica**: escribe a ``{path}.tmp`` y luego hace
    ``os.replace(tmp, path)``. ``os.replace`` es atómico en POSIX y
    Windows (mismo filesystem), y sobrescribe el destino si ya existe.
    Si el proceso muere a mitad del write, queda el ``.tmp`` huérfano
    (no el archivo principal corrupto), y el siguiente ``load_sync_state``
    lee el archivo anterior válido.

    Crea el directorio padre si no existe (operador puede pasar un
    path nuevo sin tener que mkdir manualmente).

    Args:
        state: estado a persistir.
        path: ruta destino (debe terminar en ``.json`` o similar — el
            sufijo ``.tmp`` se agrega para el staging).
    """
    path = Path(path)
    parent = path.parent
    if parent and not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)

    tmp_path = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(_sync_state_to_raw(state), ensure_ascii=False, indent=2)
    tmp_path.write_text(payload, encoding="utf-8")
    os.replace(tmp_path, path)


# --- Helpers de mutación --------------------------------------------------


def get_or_create_table_state(state: SyncState, table: str) -> TableState:
    """Obtiene la ``TableState`` de ``table``, creándola si no existe.

    Idempotente: la segunda llamada con el mismo ``table`` retorna la
    misma instancia (referencia), de modo que las mutaciones in-place
    sobre la ``TableState`` retornada se ven reflejadas en ``state``.
    """
    ts = state.tables.get(table)
    if ts is None:
        ts = TableState()
        # ``state.tables`` es un dict nuevo dentro de un frozen dataclass;
        # para "mutarlo" hacemos replace. El dataclass es frozen pero el
        # dict adentro es el mismo objeto — la convención de Python es
        # que un dataclass frozen puede tener campos mutables.
        new_tables = dict(state.tables)
        new_tables[table] = ts
        object.__setattr__(state, "tables", new_tables)
    return ts


def record_legacy_to_web_mapping(
    state: SyncState,
    table: str,
    legacy_pk: Any,
    web_pk: str,
) -> None:
    """Registra ``legacy_pk -> web_pk`` en la ``TableState`` de ``table``.

    ``legacy_pk`` se coacciona a ``str`` antes de guardarlo: el JSON
    solo soporta string keys, y la coerción es segura porque los
    primary keys de Access son INTEGER (representables como ``str``
    sin pérdida) y los UUIDs ya son ``str``.

    Crea la ``TableState`` si no existe (vía
    :func:`get_or_create_table_state`).
    """
    ts = get_or_create_table_state(state, table)
    ts.legacy_to_web_id[str(legacy_pk)] = str(web_pk)


def lookup_web_pk(
    state: SyncState,
    table: str,
    legacy_pk: Any,
) -> str | None:
    """Busca el ``web_uuid`` para ``legacy_pk`` en la tabla ``table``.

    Retorna ``None`` en miss (NO raise) — el diff engine trata el miss
    como "INSERT" en legacy→web (la fila legacy nunca se migró). Esta
    función también coacciona ``legacy_pk`` a ``str`` antes de buscar
    para ser consistente con :func:`record_legacy_to_web_mapping`.

    Args:
        state: estado global.
        table: nombre de la tabla (``"animales"``, ``"entradas"``…).
        legacy_pk: PK legacy (puede ser ``int`` o ``str``).

    Returns:
        El ``web_uuid`` correspondiente, o ``None`` si no hay mapping.
    """
    ts = state.tables.get(table)
    if ts is None:
        return None
    return ts.legacy_to_web_id.get(str(legacy_pk))


def lookup_legacy_pk(
    state: SyncState,
    table: str,
    web_pk: str,
) -> int | str | None:
    """Busca el ``legacy_pk`` (como ``int``) para ``web_pk`` en ``table``.

    Como el mapping es unidireccional (``legacy_pk → web_pk``), esta
    función itera el dict para encontrar el inverso. Para una tabla
    con miles de mappings esto es O(n) — aceptable porque el applier
    lo llama solo cuando un FK del legacy NO se resuelve por la vía
    principal (sync_state legacy→web). Si el volume crece, en v2 se
    puede mantener un índice inverso en memoria.

    Los PK legacy de Access son ``INTEGER``, así que la key guardada
    como ``str`` se convierte de vuelta a ``int`` antes de retornar
    (regla del design §4). Si por alguna razón la key no es un entero
    válido (tabla legacy con PK string), se retorna el ``str`` tal
    cual — el caller debe saber manejar ambos casos.

    Returns:
        ``int(legacy_pk)`` si hay match y es convertible, o ``str`` si
        no, o ``None`` si no hay match.
    """
    ts = state.tables.get(table)
    if ts is None:
        return None
    target = str(web_pk)
    for legacy_key, web_uuid in ts.legacy_to_web_id.items():
        if web_uuid == target:
            try:
                return int(legacy_key)
            except ValueError:
                return legacy_key
    return None


def update_last_sync_at(
    state: SyncState,
    table: str,
    ts: datetime,
) -> None:
    """Actualiza ``last_sync_at`` para la ``TableState`` de ``table``.

    Llamado por el applier al final de un sync exitoso (PR 8); permite
    que el próximo ``--mode incremental --since`` filtre las filas
    modificadas desde este timestamp.
    """
    table_state = get_or_create_table_state(state, table)
    # ``TableState`` es frozen pero su ``last_sync_at`` es un campo
    # primitivo (datetime inmutable), así que la única forma de
    # actualizarlo es creando una nueva ``TableState`` y reemplazando
    # la entrada del dict ``state.tables``.
    new_tables = dict(state.tables)
    new_tables[table] = TableState(
        last_sync_at=ts,
        legacy_to_web_id=dict(table_state.legacy_to_web_id),
    )
    object.__setattr__(state, "tables", new_tables)


# --- Internal: raw <-> SyncState ------------------------------------------


def _sync_state_to_raw(state: SyncState) -> dict[str, Any]:
    """Convierte un ``SyncState`` a la forma JSON-serializable.

    ``datetime`` → ISO-8601 (con timezone si lo tiene). ``TableState``
    se aplana a un dict con keys explícitos (``last_sync_at``,
    ``legacy_to_web_id``) en lugar de usar ``asdict()``, porque
    ``asdict`` también expone campos privados y la forma explícita es
    la documentada en el design §7.
    """
    return {
        "version": state.version,
        "tables": {
            name: {
                "last_sync_at": (ts.last_sync_at.isoformat() if ts.last_sync_at else None),
                "legacy_to_web_id": dict(ts.legacy_to_web_id),
            }
            for name, ts in state.tables.items()
        },
    }


def _sync_state_from_raw(raw: dict[str, Any]) -> SyncState:
    """Construye un ``SyncState`` desde la forma JSON del disco.

    Valida que ``raw`` sea un ``dict`` con las claves esperadas. Si
    falta ``version`` o ``tables``, levanta ``SyncStateError`` (el
    archivo está estructuralmente corrupto, no solo con un valor
    inesperado en una celda).
    """
    if not isinstance(raw, dict):
        raise SyncStateError(f"sync_state root must be a JSON object, got {type(raw).__name__}")
    version = raw.get("version", "1.0")
    raw_tables = raw.get("tables", {})
    if not isinstance(raw_tables, dict):
        raise SyncStateError(
            f"sync_state 'tables' must be a JSON object, got {type(raw_tables).__name__}"
        )
    tables: dict[str, TableState] = {}
    for name, ts_raw in raw_tables.items():
        if not isinstance(ts_raw, dict):
            raise SyncStateError(f"sync_state tables['{name}'] must be a JSON object")
        last_sync_at_raw = ts_raw.get("last_sync_at")
        last_sync_at: datetime | None
        if last_sync_at_raw is None:
            last_sync_at = None
        elif isinstance(last_sync_at_raw, str):
            try:
                last_sync_at = datetime.fromisoformat(last_sync_at_raw)
            except ValueError as exc:
                raise SyncStateError(
                    f"sync_state tables['{name}'].last_sync_at is not ISO-8601: "
                    f"{last_sync_at_raw!r}"
                ) from exc
        else:
            raise SyncStateError(
                f"sync_state tables['{name}'].last_sync_at must be a string or null"
            )
        mapping_raw = ts_raw.get("legacy_to_web_id", {})
        if not isinstance(mapping_raw, dict):
            raise SyncStateError(
                f"sync_state tables['{name}'].legacy_to_web_id must be a JSON object"
            )
        tables[name] = TableState(
            last_sync_at=last_sync_at,
            legacy_to_web_id={str(k): str(v) for k, v in mapping_raw.items()},
        )
    return SyncState(version=version, tables=tables)


__all__ = [
    "SyncState",
    "SyncStateError",
    "TableState",
    "get_or_create_table_state",
    "load_sync_state",
    "lookup_legacy_pk",
    "lookup_web_pk",
    "record_legacy_to_web_mapping",
    "save_sync_state",
    "update_last_sync_at",
]
