"""Apply legacy ACCDB rows into the InsForge web database (issue #168).

This module is the engine behind ``python -m migration apply``: the
bidirectional sync that AGENTS.md §18 declares MANDATORY between the
Access/VBA legacy backend and the new web app. It reads legacy rows via
``migration.legacy_reader`` (the injected legacy executor seam) and writes them into the matching
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

**Source-identity snapshot (PR3/M1):** ``apply_legacy_to_web`` writes
``migration.lock_snapshot.json`` AFTER acquiring the lock and BEFORE
the first legacy read. The snapshot is the durable fingerprint of the
``.accdb`` and the photos directory; subsequent runs compare against
it and fail closed on drift (per design D8). Empty / missing sources
produce the SHA-256 of zero bytes — a valid empty source, not a
crash. See ``migration.lock_snapshot`` for the on-disk contract.

**MSACCESS pre-flight (PR3/M1):** ``check_msaccess_running()`` is
called before the lock. Any live ``MSACCESS.EXE`` process aborts the
apply with ``MsAccessRunningError`` (CLI exit code 5). The check is
no-arg and skipped in dry-run mode.

**Partial-apply evidence (PR3/M1):** SIGINT AFTER the snapshot persists
the snapshot, releases the lock, and writes
``migration.partial_apply.json``. The next apply detects the file at
entry and fails closed with ``PartialApplyInterruptedError`` until the
operator removes it. PR3 does NOT auto-delete the file (no destructive
cleanup).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from app.core import logging as logging_mod
from app.core.data_access import BackendError
from migration import (
    MigrationError,
    MsAccessPreflightUnavailableError,
    acquire_lock,  # noqa: F401 — re-exported for lazy imports in apply_helpers
    check_msaccess_running,
    release_lock,  # noqa: F401 — re-exported for lazy imports in apply_helpers
)
from migration.bootstrap import bootstrap_m0_infrastructure
from migration.dni_collision import DniCollisionCounter
from migration.legacy_reader import (
    TableSpec,
    load_legacy_snapshot_batched,
)
from migration.lock_snapshot import (  # noqa: F401 — re-exported for apply_helpers lazy imports
    compute_accdb_hash,
    compute_photos_dir_hash,
    detect_drift,
    read_partial_apply,
    read_snapshot,
    write_partial_apply,
    write_snapshot,
)
from migration.mappings import load_mapping
from migration.shadow_state import (
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


# --- PR3/M1 apply-safety exceptions --------------------------------------


class MsAccessRunningError(MigrationError):
    """``MSACCESS.EXE`` is running; refuse to apply to avoid lock contention.

    The MSACCESS pre-flight (``check_msaccess_running``) is a no-arg
    probe that returns the list of PIDs whose process name matches
    ``MSACCESS.EXE`` (case-insensitive). A non-empty list means at
    least one live Access frontend is holding the ``.accdb`` open;
    an apply against the same file would hang on the pyodbc
    ``Connection.timeout=30`` and surface as a misleading
    ``LegacyReaderError``. The CLI converts this exception to exit
    code 5 (reason ``msaccess_running``).

    When ``psutil`` is missing or ``process_iter`` raises mid-iteration,
    ``check_msaccess_running`` raises ``MsAccessPreflightUnavailableError``
    instead — see that class for the fail-closed contract. The apply
    pipeline does NOT catch iteration errors and attempt recovery
    (PR3 verification remediation, per user directive 2026-07-11):
    better to abort than to claim "no MSACCESS live" when the check
    was unable to actually look.
    """

    def __init__(self, *, pids: list[int], detail: str) -> None:
        super().__init__(detail)
        self.pids = list(pids)
        self.detail = detail


class PartialApplyInterruptedError(MigrationError):
    """A previous apply was interrupted (SIGINT) and left partial evidence.

    ``migration.partial_apply.json`` exists from a prior interrupted
    run. Per the user directive (no destructive cleanup), the operator
    MUST review the file and remove it before retrying. The CLI
    converts this exception to exit code 7 plus a runbook URL.
    """

    def __init__(self, *, detail: str, evidence: dict[str, Any]) -> None:
        super().__init__(detail)
        self.evidence = dict(evidence)
        self.detail = detail


class SqlExecutor(Protocol):
    """Structural type for the web client passed to ``apply_legacy_to_web``.

    Mirrors the surface ``LocalPostgresExecutor.execute_sql`` exposes; defined
    as a Protocol so tests can pass a ``FakeInsForge`` without
    subclassing the real client.
    """

    def execute_sql(
        self,
        query: str,
        params: list[Any] | None = None,
    ) -> list[dict[str, Any]]: ...

    def get_bucket(self, bucket_name: str) -> dict[str, Any] | None: ...

    def ensure_bucket(self, bucket_name: str, *, is_public: bool = False) -> dict[str, Any]: ...


# --- Schema bootstrap ----------------------------------------------------


# Canonical DDL for the shadow-state table. The apply path must use
# the same schema as ``reconcile``; creating an apply-only shape on a
# first run would make the two operator commands incompatible.
BOOTSTRAP_SHADOW_TABLE_SQL = SHADOW_TABLE_SQL


def _bootstrap_shadow_state(client: SqlExecutor) -> None:
    """Ensure ``web_only_feature_shadow`` exists.

    Idempotent: the repository emits ``CREATE ... IF NOT EXISTS`` DDL
    and lets InsForge/Postgres own replay safety. We don't track
    bootstrap state in code — the backend owns the contract.

    Called by ``apply_legacy_to_web`` BEFORE the lock acquisition
    (Hard Rule 8: a missed bootstrap must not lock the operator out)
    AND by ``run_reconcile`` (so the bootstrap-on-first-run contract
    holds for both subcommands).
    """
    ShadowStateRepository(client).ensure_table()


# --- Safety helpers ------------------------------------------------------


# Regex for valid PostgreSQL identifiers (table / column names). The
# apply path constructs ``INSERT INTO <table>`` and ``UPDATE <table>
# SET <col>`` SQL strings; we MUST validate the table name comes from
# a trusted source (the YAML mapping or a CLI argument validated by
# argparse choices) before embedding it. Anything else is SQLi.
def apply_legacy_to_web(
    client: SqlExecutor,
    table_name: str,
    *,
    legacy_path: str,
    since: datetime | None = None,
    batch_size: int = 100,
    dry_run: bool = False,
    lock_path: Path | None = None,
    snapshot_path: Path | None = None,
    partial_path: Path | None = None,
    photos_dir_path: Path | str | None = None,
    dni_collision_counter: DniCollisionCounter | None = None,
) -> ApplyResult:
    """Bulk-apply legacy rows for one table into the InsForge web DB.

    Pipeline (per batch of ``batch_size`` rows):

    1. Read a batch via ``legacy_reader.load_legacy_snapshot_batched``
       (legacy executor seam, injected via ``set_legacy_query_executor``
       in tests; the real runtime driver is ``migration.legacy_access_client``).
    2. Map every legacy row to its web-column shape via the YAML.
    3. For each mapped row:
       a. Compute the ``source_hash`` (SHA-256 of the canonical JSON).
       b. SELECT the existing web row by natural key.
       c. If absent → INSERT + audit log ``sync.applied``.
       d. If present and equal → skip + bump ``skipped`` counter.
       e. If present and different → record a shadow row + bump
          ``skipped`` (the operator reconciles via ``reconcile``).

    PR3/M1 apply-safety wiring (orchestrated by the public function
    only — per-row logic in ``_apply_one_row`` is untouched):

    - Bootstrap M0 infrastructure (shadow table + private bucket)
      runs FIRST, before the lock, so a missed bootstrap cannot lock
      the operator out. Skipped in dry-run.
    - Partial-apply evidence check at entry: refuses to run if a
      previous apply was interrupted. Skipped in dry-run.
    - MSACCESS pre-flight (``check_msaccess_running()``): any live
      ``MSACCESS.EXE`` aborts with ``MsAccessRunningError`` BEFORE the
      lock is acquired. Skipped in dry-run.
    - Lock acquisition via ``_LockContext``.
    - INSIDE the lock, AFTER acquisition, BEFORE first read: the
      source-identity snapshot is computed (``.accdb`` SHA-256 +
      photos manifest) and atomically written to
      ``migration.lock_snapshot.json``. Drift against the previous
      snapshot aborts with ``SourceDriftError`` BEFORE the new
      snapshot is written (the old one is preserved).
    - Read + apply loop. SIGINT (KeyboardInterrupt) here persists the
      snapshot, releases the lock, and writes
      ``migration.partial_apply.json``. SIGINT BEFORE the snapshot
      leaves no trace (lock released, no snapshot, no partial file).

    Args:
        client: InsForge-shaped client (``LocalPostgresExecutor`` in
            production, ``FakeInsForge`` in tests).
        table_name: YAML spec name (e.g. ``"animal"``,
            ``"voluntario"``). Must be in ``list_available_tables()``.
        legacy_path: absolute path to the legacy ``.accdb`` (kept
            explicit per Hard Rule 2: dependency injection; no
            ``Settings.migration_dir`` global lookup for an
            assertable side-effect input).
        since: optional ISO cursor; ``None`` → full sync.
        batch_size: legacy rows per page (defaults to 100 to
            match ``legacy_reader.BATCH_SIZE``).
        dry_run: when ``True`` the diff plan is computed and reported
            but no INSERT/UPDATE/shadow writes are issued AND the
            advisory lock is skipped AND the snapshot is not written
            AND MSACCESS and partial-apply checks are skipped.
        lock_path: optional override for the lock file path; defaults
            to the same resolution ``migration.cli._resolve_lock_path``
            uses.
        snapshot_path: optional override for the snapshot file path;
            defaults to ``<migration_dir>/migration.lock_snapshot.json``.
        partial_path: optional override for the partial-apply
            evidence path; defaults to
            ``<migration_dir>/migration.partial_apply.json``.
        photos_dir_path: optional path to the photos directory for the
            source-identity manifest. ``None`` produces an empty
            manifest (the SHA-256 of zero bytes) so a pre-PR4 apply
            can still proceed against a valid empty source.
        dni_collision_counter: optional DI seam for the DNI collision
            counter (PR5). The forward applier never invokes
            :func:`record_dni_collision` because legacy
            ``TbVoluntariosParaAutorrellenables`` has no ``DNI`` column
            (verified by pyodbc schema introspection 2026-07-11), so the
            counter stays at 0 across the entire forward run. The seam
            is wired today so the PR6 reverse applier (``web_to_legacy``)
            can pass a counter and read its value at the end of the
            run to populate
            ``MigrationReport.collisions[table_name]["preserve_advances"]``.
            Default ``None`` keeps the existing call sites untouched.

    Returns:
        :class:`ApplyResult` with the per-table counts and errors.

    Raises:
        LegacyReaderError: pyodbc I/O failed. Propagated so the CLI
            exits 5 (design §1.5); the lock is released via the
            surrounding ``try/finally``.
        MsAccessRunningError: a live ``MSACCESS.EXE`` blocked the
            pre-flight; CLI exits 5.
        SourceDriftError: the on-disk source changed since the last
            apply; CLI exits 6.
        PartialApplyInterruptedError: a previous apply was interrupted
            and left ``partial_apply.json``; CLI exits 7.
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

    # Resolve lock / snapshot / partial-apply paths up-front so the
    # SIGINT handler and the dry-run / real-apply branches all see
    # the same paths (no env-var race).
    resolved_lock_path = lock_path or _resolve_default_lock_path()
    resolved_snapshot_path = (
        Path(snapshot_path) if snapshot_path else _resolve_default_snapshot_path()
    )
    resolved_partial_path = (
        Path(partial_path) if partial_path else _resolve_default_partial_path()
    )

    # --- Bootstrap M0 infrastructure BEFORE the lock -----------------
    if not dry_run:
        bootstrap_m0_infrastructure(client)

    # --- Entry guard: partial-apply evidence from interrupted run -----
    # Per user directive: no destructive cleanup. The operator MUST
    # remove the file before retrying.
    if not dry_run:
        existing_partial = read_partial_apply(resolved_partial_path)
        if existing_partial is not None:
            raise PartialApplyInterruptedError(
                detail=(
                    f"Previous apply was interrupted; review "
                    f"{resolved_partial_path} and remove it to retry. "
                    f"Evidence: progress_applied="
                    f"{existing_partial.get('progress_applied')!r}, "
                    f"reason={existing_partial.get('reason')!r}"
                ),
                evidence=existing_partial,
            )

    # --- MSACCESS pre-flight (no-arg, before lock) -------------------
    # Fail-closed contract (PR3 verification remediation, per user
    # directive 2026-07-11): when the preflight cannot run
    # (``psutil`` missing or iteration errors) we MUST NOT silently
    # claim "no MSACCESS live". We log a categorical event with the
    # reason and re-raise so the CLI surfaces exit 5 with reason
    # ``msaccess_preflight_unavailable``. Dry-run (``--check-only``)
    # bypasses this branch entirely — preflight is read-only's
    # concern.
    if not dry_run:
        try:
            msaccess_pids = check_msaccess_running()
        except MsAccessPreflightUnavailableError as preflight_exc:
            # Categorical log: no PIDs, no error strings, only the
            # reason. The apply layer owns the audit log; the CLI
            # owns the operator-facing categorical stream.
            logging_mod.log_safe(
                "apply.preflight_unavailable",
                reason=preflight_exc.reason,
            )
            raise
        if msaccess_pids:
            raise MsAccessRunningError(
                pids=msaccess_pids,
                detail=(
                    f"Cannot run apply while MSACCESS.EXE is running "
                    f"(pids={msaccess_pids}). Close the legacy Access "
                    f"frontend and retry."
                ),
            )

    # Build the TableSpec — only the columns the YAML asks
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

    # --- Lock + snapshot + read loop -------------------------------
    lock_ctx = _LockContext(client, resolved_lock_path, dry_run=dry_run)
    snapshot_written = False
    errors: list[str] = []
    applied = 0
    skipped = 0

    # VOL-04 (#37): volontario FK index for resolution.
    # Built once per apply run for ``acogida`` / ``adopcion`` tables which
    # carry volontario free-text references that need to resolve to UUIDs.
    # The index is loaded from the DB inside the lock so it is consistent
    # with the rows migrated in this run (Level 2 resolution).
    # For ``volontarios`` itself, the index starts empty and is populated
    # row-by-row as INSERTs succeed (Level 2 for subsequent rows).
    vol_index: _VoluntariosIndex = _VoluntariosIndex()

    try:
        with lock_ctx:
            # --- Snapshot write (AFTER lock, BEFORE first read) ----
            # Per design D8: snapshot ordering is locked. Drift
            # detection compares the prospective new snapshot with
            # the existing one; on mismatch we abort WITHOUT writing
            # the new snapshot, leaving the previous one intact for
            # post-mortem.
            if not dry_run:
                _write_or_check_snapshot(
                    legacy_path=legacy_path,
                    photos_dir_path=photos_dir_path,
                    snapshot_path=resolved_snapshot_path,
                )
                snapshot_written = True

            # --- Read + apply loop --------------------------------
            # Load the volontarios index for tables that carry volontario FKs.
            # Must be inside the lock so Level 2 (in-memory snapshot) is
            # consistent with the DB state at apply time.
            if mapping.web_table in ("acogidas", "adopciones"):
                vol_index.load_from_db(client)

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
                            vol_index=vol_index,
                        )
                    except BackendError as exc:
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
    except KeyboardInterrupt:
        # SIGINT after the snapshot was written → persist partial
        # evidence so the next apply can fail closed at entry. SIGINT
        # before the snapshot leaves ``snapshot_written=False`` and
        # no partial evidence is written (the lock is released by
        # ``_LockContext.__exit__`` above).
        if snapshot_written:
            write_partial_apply(
                resolved_partial_path,
                direction="legacy-to-web",
                table_name=safe,
                progress_applied=applied,
                progress_total=None,
                reason="sigint",
            )
        raise




# Private apply-pipeline helpers (FK lookup, source-hash, value
# transforms, snapshot write, per-row apply, shadow divergence,
# lock context, default-path resolution, SourceDriftError,
# _VoluntariosIndex, _SAFE_TABLE_NAME, _safe_table) live in
# ``migration.apply_helpers`` to keep this module under the
# 700-line AGENTS.md rule 21 budget. Re-imported here so the rest
# of the apply code keeps the same name resolution.
from migration.apply_helpers import (  # noqa: E402,F401
    _SAFE_TABLE_NAME,
    SourceDriftError,
    _normalise_for_lookup,
    _resolve_fk_value,
    _safe_table,
    _strip_accents,
    _VoluntariosIndex,
)
from migration.apply_lock import (  # noqa: E402,F401
    _LockContext,
    _resolve_default_lock_path,
    _resolve_default_partial_path,
    _resolve_default_snapshot_path,
)
from migration.apply_per_row import (  # noqa: E402,F401
    _apply_one_row,
    _fetch_web_row_by_key,
    _insert_web_row,
    _record_shadow_divergence,
)
from migration.apply_row_mapping import (  # noqa: E402,F401
    _compute_source_hash,
    _legacy_to_web_row,
)
from migration.apply_snapshots import _write_or_check_snapshot  # noqa: E402,F401
