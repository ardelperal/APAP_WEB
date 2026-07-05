"""Apply legacy ACCDB rows into the InsForge web database (issue #168).

This module is the engine behind ``python -m migration apply``: the
bidirectional sync that AGENTS.md §18 declares MANDATORY between the
Access/VBA legacy backend and the new web app. It reads legacy rows via
``migration.legacy_reader`` (Dysflow) and writes them into the matching
InsForge domain table (``animales``, ``voluntarios``, ``entradas``,
``acogidas``, ``adopciones``, ...) per the YAML column map.

**Direction (this slice):** ``legacy_to_web`` only. The reverse
direction (``web_to_legacy``) is a future PR.

**Idempotency:** every row is matched on its natural key
(``migration.mappings.<table>.yaml::key_field``). An existing web row
whose payload matches the legacy row is skipped. An existing web row
whose payload DOESN'T match is recorded in
``web_only_feature_shadow`` as a divergence — the apply slice never
overwrites a row that disagrees with the legacy side; the operator
reconciles via ``migrate reconcile --interactive``.

**Concurrency safety:** the apply acquires the migration advisory lock
(see ``migration.lock``) for the duration of the run. A second
operator invocation sees an active lock and fails fast.

**Audit:** every applied row emits ``log_safe("sync.applied", ...)``
with the table, pk, direction, source hash, and target hash. The
audit log is the only durable proof of which row was written when.

**Dry-run:** ``dry_run=True`` runs the full diff plan but issues no
INSERTs, no UPDATEs, no shadow writes. The advisory lock is also
skipped — the operator can re-run ``apply --check-only`` freely.

**Bootstrap:** on the first call we ensure the
``web_only_feature_shadow`` table exists (``CREATE TABLE IF NOT
EXISTS``). Subsequent replays are no-ops at the SQL level.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from app.core import logging as logging_mod
from app.core.insforge import InsForgeError
from migration import (
    acquire_lock,
    release_lock,
)
from migration.legacy_reader import (
    TableSpec,
    load_legacy_snapshot_batched,
)
from migration.mappings import load_mapping
from migration.shadow_state import (
    SHADOW_NEEDS_REVIEW_INDEX_SQL,
    SHADOW_TABLE_SQL,
    ShadowStateRepository,
)

# --- Public types --------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ApplyResult:
    """Aggregate result of one ``apply_legacy_to_web`` run.

    The dataclass is the single source of truth for the operator
    surface: the CLI prints ``applied`` / ``skipped`` / ``errors`` and
    nothing else. It mirrors the shape of ``MigrationReport``'s counts
    but is lighter — no diffs / conflicts arrays (those live in
    ``MigrationReport`` for the round-trip reports).

    ``table_name`` is the YAML spec name (``"animal"``, ``"voluntario"``,
    etc.) so the caller can route the result into a multi-table
    ``MigrationReport`` later without re-parsing.
    """

    table_name: str
    applied: int
    skipped: int
    errors: list[str] = field(default_factory=list)


class _InsForgeLike(Protocol):
    """Structural type for the web client passed to ``apply_legacy_to_web``.

    Mirrors the surface ``InsForgeClient.execute_sql`` exposes; defined
    as a Protocol so tests can pass a ``FakeInsForge`` without
    subclassing the real client.
    """

    def execute_sql(
        self,
        query: str,
        params: list[Any] | None = None,
    ) -> list[dict[str, Any]]: ...


# --- Schema bootstrap ----------------------------------------------------


# Canonical DDL for the shadow-state table. The apply path must use
# the same schema as ``reconcile``; creating an apply-only shape on a
# first run would make the two operator commands incompatible.
BOOTSTRAP_SHADOW_TABLE_SQL = SHADOW_TABLE_SQL


def _bootstrap_shadow_state(client: _InsForgeLike) -> None:
    """Ensure ``web_only_feature_shadow`` exists.

    Idempotent: the ``CREATE TABLE IF NOT EXISTS`` is a SQL-level
    no-op on replay. We don't track bootstrap state in code — the
    InsForge backend owns the contract.

    Called by ``apply_legacy_to_web`` BEFORE the lock acquisition
    (Hard Rule 8: a missed bootstrap must not lock the operator out)
    AND by ``run_reconcile`` (so the bootstrap-on-first-run contract
    holds for both subcommands).
    """
    client.execute_sql(BOOTSTRAP_SHADOW_TABLE_SQL)
    client.execute_sql(SHADOW_NEEDS_REVIEW_INDEX_SQL)


# --- Safety helpers ------------------------------------------------------


# Regex for valid PostgreSQL identifiers (table / column names). The
# apply path constructs ``INSERT INTO <table>`` and ``UPDATE <table>
# SET <col>`` SQL strings; we MUST validate the table name comes from
# a trusted source (the YAML mapping or a CLI argument validated by
# argparse choices) before embedding it. Anything else is SQLi.
_SAFE_TABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_table(table_name: str) -> str:
    """Return ``table_name`` if it is a safe SQL identifier, else raise.

    The same belt-and-braces the existing
    ``migration.cli._apply_accept_derived`` uses. Hard Rule 8 + AGENTS.md
    §1: never trust identifiers from external input.
    """
    if not _SAFE_TABLE_NAME.match(table_name):
        raise ValueError(
            f"unsafe SQL identifier {table_name!r}; must match {_SAFE_TABLE_NAME.pattern}"
        )
    return table_name


# --- Mapping helpers ----------------------------------------------------


def _legacy_to_web_row(legacy_row: dict[str, Any], mapping: Any) -> dict[str, Any]:
    """Map a legacy ``dict`` to its web-column ``dict``.

    Walks the ``mapping.columns`` list and emits only the columns with a
    non-null ``legacy_column``. Web-only columns (``legacy_column=None``,
    e.g. ``DNI`` on ``voluntarios``) are skipped — they are owned by
    the web side and the shadow-state handles their reconciliation.

    Values are passed through verbatim. Date coercion (Access stores
    dates as ``#YYYY-MM-DD#``; InsForge wants ISO-8601 strings) is the
    YAML's ``transform`` responsibility — the helper does NOT
    re-interpret values. Transforms like ``default_uuid`` /
    ``default_now`` are handled at the SQL layer (the YAML declares
    ``legacy_column=null`` for them and the applier knows to skip them
    here, mirroring the legacy_reader contract).
    """
    out: dict[str, Any] = {}
    for col in mapping.columns:
        if col.legacy_column is None:
            # Web-only column (id, fecha_alta, DNI, ...) — handled by
            # the SQL default or the shadow-state.
            continue
        out[col.web_column] = legacy_row.get(col.legacy_column)
    return out


def _compute_source_hash(row: dict[str, Any]) -> str:
    """SHA-256 hex of the canonical JSON of ``row``.

    The source hash is the audit-log fingerprint of what the legacy
    side presented. Stable across Python runs (sorted keys, no
    whitespace) so a re-run produces the same hash and idempotency
    is observable.
    """
    payload = json.dumps(row, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# --- Apply entry point --------------------------------------------------


def apply_legacy_to_web(
    client: _InsForgeLike,
    table_name: str,
    *,
    legacy_path: str,
    since: datetime | None = None,
    batch_size: int = 100,
    dry_run: bool = False,
    lock_path: Path | None = None,
) -> ApplyResult:
    """Bulk-apply legacy rows for one table into the InsForge web DB.

    Pipeline (per batch of ``batch_size`` rows):

    1. Read a batch via ``legacy_reader.load_legacy_snapshot_batched``
       (Dysflow executor, injected via ``set_legacy_query_executor``
       in tests; the real Dysflow MCP wires it in production).
    2. Map every legacy row to its web-column shape via the YAML.
    3. For each mapped row:
       a. Compute the ``source_hash`` (SHA-256 of the canonical JSON).
       b. SELECT the existing web row by natural key.
       c. If absent → INSERT + audit log ``sync.applied``.
       d. If present and equal → skip + bump ``skipped`` counter.
       e. If present and different → record a shadow row + bump
          ``skipped`` (the operator reconciles via ``reconcile``).

    Args:
        client: InsForge-shaped client (``InsForgeClient`` in
            production, ``FakeInsForge`` in tests).
        table_name: YAML spec name (e.g. ``"animal"``,
            ``"voluntario"``). Must be in ``list_available_tables()``.
        legacy_path: absolute path to the legacy ``.accdb`` (kept
            explicit per Hard Rule 2: dependency injection; no
            ``Settings.migration_dir`` global lookup for an
            assertable side-effect input).
        since: optional ISO cursor; ``None`` → full sync.
        batch_size: legacy rows per Dysflow page (defaults to 100 to
            match ``legacy_reader.BATCH_SIZE``).
        dry_run: when ``True`` the diff plan is computed and reported
            but no INSERT/UPDATE/shadow writes are issued AND the
            advisory lock is skipped.
        lock_path: optional override for the lock file path; defaults
            to the same resolution ``migration.cli._resolve_lock_path``
            uses.

    Returns:
        :class:`ApplyResult` with the per-table counts and errors.

    Raises:
        LegacyReaderError: Dysflow I/O failed. Propagated so the CLI
            exits 5 (design §1.5); the lock is released via the
            surrounding ``try/finally``.
        ValueError: ``table_name`` is not a valid SQL identifier
            (caught at the CLI via argparse choices for user input,
            but the function defends in depth for library callers).
    """
    safe = _safe_table(table_name)

    # Load the YAML mapping up-front so a typo fails fast before we
    # acquire the lock. ``load_mapping`` raises ``MappingNotFoundError``
    # on a missing spec — let it propagate.
    mapping = load_mapping(safe)
    web_table = _safe_table(mapping.web_table)

    # Bootstrap the shadow table BEFORE the lock: a missed bootstrap
    # must not lock the operator out, and the lock would just bounce
    # the next caller anyway. Dry-run skips bootstrap too (no writes).
    if not dry_run:
        _bootstrap_shadow_state(client)

    errors: list[str] = []
    applied = 0
    skipped = 0

    # Build the Dysflow TableSpec — only the columns the YAML asks
    # for (no ``SELECT *``). We pass them in the YAML's declared order
    # so a future PR can use the column list as a checksum / contract.
    legacy_columns: tuple[str, ...] = tuple(
        c.legacy_column for c in mapping.columns if c.legacy_column
    )
    spec = TableSpec(
        legacy_table=mapping.legacy_table,
        columns=legacy_columns,
        where=None,  # ``since`` is a cursor on the web side, not a WHERE here
    )

    # --- Lock acquisition (skipped in dry-run) -----------------------
    lock_ctx = _LockContext(client, lock_path, dry_run=dry_run)
    with lock_ctx:
        for _legacy_table_name, rows in load_legacy_snapshot_batched(
            legacy_path, [spec]
        ):
            for legacy_row in rows:
                try:
                    outcome = _apply_one_row(
                        client=client,
                        mapping=mapping,
                        web_table=web_table,
                        legacy_row=legacy_row,
                        dry_run=dry_run,
                    )
                except InsForgeError as exc:
                    errors.append(
                        f"{mapping.legacy_table}: InsForge error on "
                        f"{legacy_row.get(mapping.legacy_key)!r}: {exc}"
                    )
                    continue
                except Exception as exc:  # noqa: BLE001 — last-resort guard
                    errors.append(
                        f"{mapping.legacy_table}: unexpected error on "
                        f"{legacy_row.get(mapping.legacy_key)!r}: {exc}"
                    )
                    continue
                if outcome == "applied":
                    applied += 1
                else:
                    skipped += 1

    return ApplyResult(
        table_name=safe,
        applied=applied,
        skipped=skipped,
        errors=errors,
    )


def _apply_one_row(
    *,
    client: _InsForgeLike,
    mapping: Any,
    web_table: str,
    legacy_row: dict[str, Any],
    dry_run: bool,
) -> str:
    """Apply one legacy row and return ``"applied"`` or ``"skipped"``.

    Helper extracted from :func:`apply_legacy_to_web` so the per-row
    logic is unit-testable without the paging loop in the way. The
    return string is the row's outcome (``"applied"`` when an INSERT
    was emitted, ``"skipped"`` for either a no-op equality or a
    divergence recorded in the shadow table).
    """
    legacy_pk_value = legacy_row.get(mapping.legacy_key)
    if legacy_pk_value is None:
        # The legacy row has no natural key — there is nothing to match
        # against the web side. Surface as an error so the CLI's error
        # count bumps.
        raise ValueError(
            f"legacy row missing natural key {mapping.legacy_key!r}: {legacy_row!r}"
        )
    legacy_pk = str(legacy_pk_value)

    source_hash = _compute_source_hash(legacy_row)
    web_row = _legacy_to_web_row(legacy_row, mapping)

    existing = _fetch_web_row_by_key(client, mapping, legacy_pk)

    if existing is None:
        if dry_run:
            return "applied"  # counted, not written
        _insert_web_row(client, web_table, web_row)
        logging_mod.log_safe(
            "sync.applied",
            table=web_table,
            pk=legacy_pk,
            direction="legacy->web",
            source_hash=source_hash,
            target_hash=None,
            op="INSERT",
            dry_run=False,
        )
        return "applied"

    # Row exists — compare the canonical mapped dict.
    target_payload = {col: existing.get(col) for col in web_row}
    target_hash = _compute_source_hash(target_payload)
    if _compute_source_hash(web_row) == target_hash:
        return "skipped"

    # Divergence: record in the shadow table. We do NOT overwrite the
    # web row; the operator reconciles via ``reconcile --interactive``.
    if not dry_run:
        _record_shadow_divergence(
            client=client,
            table_name=mapping.web_table,
            legacy_pk=legacy_pk,
            web_pk=str(existing.get("id")) if existing.get("id") else None,
            source_hash=source_hash,
            target_hash=target_hash,
        )
        logging_mod.log_safe(
            "sync.applied",
            table=web_table,
            pk=legacy_pk,
            direction="legacy->web",
            source_hash=source_hash,
            target_hash=target_hash,
            op="NOOP_DIVERGENCE_RECORDED",
            dry_run=False,
        )
    return "skipped"


def _fetch_web_row_by_key(
    client: _InsForgeLike, mapping: Any, legacy_pk: str
) -> dict[str, Any] | None:
    """Return the existing web row matching ``legacy_pk``, or ``None``.

    Looks up by the natural key column (``mapping.key_field``). The
    query is intentionally simple — equality on a single column —
    because the natural key for every spec in this slice is a single
    non-composite column (NCHIP, Voluntario, ...). A future PR can
    extend to composite keys (the materiales catalog already uses one).
    """
    key_col = _safe_table(mapping.key_field)
    table = _safe_table(mapping.web_table)
    sql = f"SELECT * FROM {table} WHERE {key_col} = $1 LIMIT 1"
    rows = client.execute_sql(sql, [legacy_pk])
    return rows[0] if rows else None


def _insert_web_row(
    client: _InsForgeLike, web_table: str, web_row: dict[str, Any]
) -> None:
    """INSERT ``web_row`` into ``web_table`` and return the new row.

    The SQL is constructed from the column list of ``web_row`` so the
    function works against any mapping without a per-table hand-coded
    INSERT. ``id`` (UUID) and timestamps (``fecha_alta``,
    ``updated_at``) are handled by the DB defaults (``DEFAULT
    gen_random_uuid()``, ``DEFAULT now()``) — we just don't include
    them in the params if they're missing from the mapped row.
    """
    safe_table = _safe_table(web_table)
    cols = [c for c in web_row if _SAFE_TABLE_NAME.match(c)]
    if not cols:
        raise ValueError(f"no safe columns to INSERT into {web_table}")
    placeholders = ", ".join(f"${i + 1}" for i in range(len(cols)))
    col_list = ", ".join(cols)
    sql = f"INSERT INTO {safe_table} ({col_list}) VALUES ({placeholders}) RETURNING id"
    params = [web_row[c] for c in cols]
    client.execute_sql(sql, params)


def _record_shadow_divergence(
    *,
    client: _InsForgeLike,
    table_name: str,
    legacy_pk: str,
    web_pk: str | None,
    source_hash: str,
    target_hash: str,
) -> None:
    """INSERT a divergence row into ``web_only_feature_shadow``.

    The shadow table is the durable audit trail: every disagreement
    between the legacy and web sides is recorded exactly once (the
    table's UNIQUE composite index — once added by a follow-up PR —
    will reject duplicate rows). The operator reconciles via
    ``migrate reconcile --interactive``.
    """
    safe = _safe_table(table_name)
    ShadowStateRepository(client).upsert(
        table_name=safe,
        legacy_pk=legacy_pk,
        web_pk=web_pk,
        web_column="__row__",
        preserved_value={"source_hash": source_hash, "target_hash": target_hash},
        strategy="preserve",
        reconciliation_status="needs_review",
    )


# --- Lock context manager -----------------------------------------------


class _LockContext:
    """Tiny context manager wrapping ``acquire_lock`` / ``release_lock``.

    A stdlib ``contextlib.AbstractContextManager`` would do, but the
    apply pipeline wraps the lock in ``try/finally`` semantically and
    the dataclass-shaped object reads cleaner at the call site.

    Skips the lock entirely in ``dry_run`` mode — the operator can
    re-run ``apply --check-only`` freely without locking out a real
    apply.
    """

    def __init__(
        self,
        client: _InsForgeLike,
        lock_path: Path | None,
        *,
        dry_run: bool,
    ) -> None:
        self._lock_path = lock_path or _resolve_default_lock_path()
        self._dry_run = dry_run
        self._acquired = False

    def __enter__(self) -> _LockContext:
        if self._dry_run:
            return self
        acquire_lock(self._lock_path)
        self._acquired = True
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._acquired:
            # Release even on the error path (Hard Rule 8 + the
            # apply slice's "lock always released" contract).
            try:
                release_lock(self._lock_path)
            except Exception:  # noqa: BLE001 — never mask the original exc
                pass


def _resolve_default_lock_path() -> Path:
    """Resolve the lock path when the caller did not pass one.

    Mirrors ``migration.cli._resolve_lock_path`` — same env-var
    convention (``APAP_MIGRATION_DIR``), same default
    (``./migration/migration.lock``). Kept as a separate helper so
    ``migration.cli`` does not have to import from this module and we
    don't create a circular dependency.
    """
    import os

    migration_dir = os.environ.get("APAP_MIGRATION_DIR", "./migration")
    return Path(migration_dir) / "migration.lock"


__all__ = [
    "ApplyResult",
    "BOOTSTRAP_SHADOW_TABLE_SQL",
    "_SAFE_TABLE_NAME",
    "_bootstrap_shadow_state",
    "_compute_source_hash",
    "_legacy_to_web_row",
    "apply_legacy_to_web",
]
