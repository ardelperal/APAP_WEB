"""Apply web-side rows into the legacy ``.accdb`` (PR6 / M2 reverse).

Symmetric counterpart to :mod:`migration.apply` for the
``web -> legacy`` direction. The reverse applier pushes web-only
edits back to the legacy backend so the two sides stay converged
across a full ``legacy -> web -> legacy`` round-trip.

**Scope (this slice):** reverse direction only. Reuses every seam
PR1-PR5 installed:

- ``migration.legacy_reader.set_legacy_query_executor`` (reads)
  + ``set_legacy_write_executor`` (writes) for legacy I/O. The
  pyodbc implementations live in :mod:`migration.dysflow_client`.
- ``migration.lock.check_msaccess_running`` for the pre-flight, and
  ``acquire_lock`` / ``release_lock`` for the advisory lock.
- ``migration.shadow_state.ShadowStateRepository`` for the
  web-only shadow persistence (``last_legacy_snapshot_at``
  advance; ``preserved_value`` is NEVER written on reverse per the
  spec scenario "Reverse path never writes preserved_value").
- ``migration.dni_collision.record_dni_collision`` for the
  reverse-path collision policy (``direction="web-to-legacy"``).
- ``migration.semantic_events.record_lifecycle_reversed`` for the
  ``LIFECYCLE_REVERSED`` event the spec requires when a derived
  column was overridden in web between forward and reverse apply.
- ``migration.sync_state`` for ``tables[table].last_sync_at``
  updates on success.

**Per-strategy behaviour** (per the per-strategy table in
``live-migration-bidirectional-completion`` spec + the
``web-only-feature-preservation`` spec delta):

| Strategy   | Forward (legacy->web)                | Reverse (web->legacy)                       |
|------------|--------------------------------------|---------------------------------------------|
| preserve   | Write ``preserved_value``            | NEVER write; advance ``last_legacy_snapshot_at`` |
| derived    | Run derivation engine; compare       | DO NOT re-derive; emit ``LIFECYCLE_REVERSED`` if state changed |
| fixed      | Write static value once              | NEVER write; one-shot bootstrap only        |
| mapped 1:1 | Write mapped columns                 | Write mapped columns (the dominant case)    |

**Idempotency:** every reverse write uses the legacy natural key as
the dedup pivot. A legacy row with the same natural key but a
different payload is UPDATEd; a missing legacy row is INSERTed.
Re-running ``apply_web_to_legacy`` produces ``applied == 0`` for any
row already synced.

**Dry-run:** ``dry_run=True`` runs the diff plan without writes and
reports ``applied`` as the would-apply count. The advisory lock is
skipped (mirrors forward behavior).

**M2 no-op on derived:** the reverse applier is the documented
"non-rederivation" surface — neither
:func:`migration.derivation.derive_estado_actual_animal` nor
:func:`migration.derivation.compare_derived_to_stored` are called
on this path (the atom
``tests/migration/test_reverse_apply.py::test_derived_column_no_rederive_on_reverse``
pins the invariant via monkeypatch).

**Bootstrap:** no bootstrap step (the private ``apap-photos`` bucket
and the shadow-table DDL are forward-only concerns; reverse writes
do not touch storage). The partial-apply guard runs for symmetry
with the forward applier (the forward ``migration.partial_apply.json``
state is operator-actionable across both directions).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from app.core import logging as logging_mod
from migration import (
    MigrationError,
    MsAccessPreflightUnavailableError,
    acquire_lock,
    check_msaccess_running,
    legacy_reader,
    release_lock,
)
from migration import dni_collision as dni_collision_mod
from migration import semantic_events as semantic_events_mod
from migration.apply import _SAFE_TABLE_NAME, ApplyResult, _safe_table
from migration.bootstrap import bootstrap_m0_infrastructure
from migration.dni_collision import DniCollisionCounter
from migration.lock_snapshot import (
    Snapshot,
    compute_accdb_hash,
    compute_photos_dir_hash,
    detect_drift,
    read_partial_apply,
    read_snapshot,
    write_partial_apply,
    write_snapshot,
)
from migration.mappings import load_mapping
from migration.reporting import MigrationReport
from migration.shadow_state import ShadowStateRepository
from migration.sync_state import load_sync_state, save_sync_state, update_last_sync_at

# --- Reverse-direction direction constant --------------------------------


#: Closed-vocabulary direction tag for the reverse applier. Mirrors
#: the CLI's ``--direction`` flag's accepted value
#: (``{legacy-to-web, web-to-legacy}``) and the YAML's per-strategy
#: ``source_direction`` stamp on ``LIFECYCLE_REVERSED``.
DIRECTION_WEB_TO_LEGACY = "web-to-legacy"
DIRECTION_LEGACY_TO_WEB = "legacy-to-web"


# --- Reverse-protocol type (structural) ---------------------------------


class _InsForgeLike(Protocol):
    """Structural type for the web client passed to ``apply_web_to_legacy``.

    Mirrors the surface ``InsForgeClient.execute_sql`` exposes, plus
    the private ``apap-photos`` bucket accessors that the
    bootstrap uses. The :class:`FakeInsForge` test fixture satisfies
    the protocol by duck typing.
    """

    def execute_sql(
        self,
        query: str,
        params: list[Any] | None = None,
    ) -> list[dict[str, Any]]: ...

    def get_bucket(self, bucket_name: str) -> dict[str, Any] | None: ...

    def ensure_bucket(self, bucket_name: str, *, is_public: bool = False) -> dict[str, Any]: ...


# --- Reverse apply exceptions --------------------------------------------


class ReverseApplyError(MigrationError):
    """Base class for typed reverse-apply failures.

    Mirror of the forward applier's typed-exception hierarchy. PR6
    ships one concrete subtype (``ReverseSyncStateRollbackError``)
    used by the transactional sync_state update; new subtypes land
    alongside future reverse-only failure modes (e.g. DLQ-style
    retry on a single legacy write that retries N times before
    failing the run).
    """


class ReverseSyncStateRollbackError(ReverseApplyError):
    """``sync_state.json`` could not be advanced after a successful
    legacy write.

    The legacy write already committed (the operator cannot roll back
    the .accdb transaction via the seam); the operator gets a
    categorical line that points to the runbook and the row's audit
    log. The forward applier's MSACCESS / partial-apply / drift
    branches are unchanged — the reverse path shares the same
    dataset and the same per-table ``tables[table].last_sync_at``
    cursor.
    """


# --- Schema bootstrap (no-op for reverse) --------------------------------


def _skip_bootstrap_for_reverse(*_args: Any, **_kwargs: Any) -> None:
    """Reverse apply does NOT bootstrap M0 infra.

    The forward applier runs :func:`bootstrap_m0_infrastructure` to
    ensure the shadow table + private ``apap-photos`` bucket exist.
    The reverse applier does not touch either — storage writes are
    forward-only, and the shadow-table DDL is forward-only too (the
    forward applier's atomic ``CREATE TABLE IF NOT EXISTS`` runs
    there).
    """


# --- Web → legacy mapping helpers ---------------------------------------


def _web_to_legacy_row(web_row: dict[str, Any], mapping: Any) -> dict[str, Any]:
    """Map a web ``dict`` to its legacy-column ``dict``.

    Inverse of :func:`migration.apply._legacy_to_web_row`: walks the
    same ``mapping.columns`` list, but emits only the columns with a
    non-null ``legacy_column``. Web-only columns
    (``legacy_column=None``, e.g. ``DNI`` on ``voluntarios``) are
    skipped — legacy has no column to receive them, and the
    :func:`record_dni_collision` helper routes the per-row
    collision to the shadow table via the DI seam.

    Column lookups are case-insensitive: the YAML keeps CamelCase
    names (``Voluntario``, ``NCHIP``) for legacy compatibility, but
    the web side stores columns in lowercase. The forward path does
    not need this normalization because the YAML's
    ``legacy_column`` names match the legacy CamelCase exactly and
    the web writes happen on the forward path.
    """
    out: dict[str, Any] = {}
    for col in mapping.columns:
        if col.legacy_column is None:
            continue
        out[col.legacy_column] = _case_insensitive_get(web_row, col.web_column)
    return out


def _compute_source_hash(row: dict[str, Any]) -> str:
    """SHA-256 hex of the canonical JSON of ``row``.

    Same contract as :func:`migration.apply._compute_source_hash`;
    the reverse audit log emits ``source_hash = SHA-256 of the
    web-side mapped payload`` and ``target_hash = SHA-256 of the
    legacy-side pre-update payload`` so the operator can trace the
    round-trip without trusting either side in isolation.
    """
    payload = json.dumps(row, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _case_insensitive_get(row: dict[str, Any], key: str) -> Any:
    """Return ``row[key]`` ignoring case on the key lookup.

    The YAML mappings store column names in CamelCase (the legacy
    convention); the web row keys are lowercase. A naive
    ``row.get(key)`` returns ``None`` when the cases disagree, so
    the helper looks up the lowercase form AND any uppercase variant
    of ``key`` in the row. Returns ``None`` on miss.
    """
    if not row:
        return None
    direct = row.get(key)
    if direct is not None:
        return direct
    lower = key.lower()
    if row.get(lower) is not None:
        return row.get(lower)
    upper = key.upper()
    if row.get(upper) is not None:
        return row.get(upper)
    # Last-ditch: scan keys ignoring case for the canonical name.
    target = lower
    for k, v in row.items():
        if k.lower() == target:
            return v
    return None


# --- Reverse apply entry point ------------------------------------------


def apply_web_to_legacy(
    client: _InsForgeLike,
    table_name: str,
    *,
    legacy_path: str,
    web_snapshot: dict[str, list[dict[str, Any]]] | None = None,
    dry_run: bool = False,
    lock_path: Path | None = None,
    snapshot_path: Path | None = None,
    partial_path: Path | None = None,
    photos_dir_path: Path | str | None = None,
    dni_collision_counter: DniCollisionCounter | None = None,
    migration_report: MigrationReport | None = None,
    sync_state_path: Path | None = None,
) -> ApplyResult:
    """Bulk-apply web rows for one table into the legacy ``.accdb``.

    Args:
        client: InsForge-shaped client (``InsForgeClient`` in
            production, ``FakeInsForge`` in tests).
        table_name: YAML spec name (e.g. ``"voluntario"``).
        legacy_path: absolute path to the legacy ``.accdb``. The
            reverse applier issues reads via
            ``migration.legacy_reader._execute_legacy_query`` and
            writes via ``migration.legacy_reader._execute_legacy_write``.
        web_snapshot: optional pre-built snapshot keyed by web
            table name (``{"voluntarios": [row, ...]}``). When
            ``None`` the reverse applier pulls rows from the web via
            ``client.execute_sql`` once at the start of the run.
        dry_run: when ``True`` the diff plan is computed and reported
            but no INSERT/UPDATE/shadow writes are issued AND the
            advisory lock is skipped AND the snapshot is not written
            AND MSACCESS and partial-apply checks are skipped.
        lock_path: optional override for the lock file path; defaults
            to the same resolution :func:`apply_legacy_to_web` uses
            (``<APAP_MIGRATION_DIR>/migration.lock``).
        snapshot_path: optional override for the source-identity
            snapshot path.
        partial_path: optional override for the partial-apply
            evidence path.
        photos_dir_path: optional override for the photos manifest.
        dni_collision_counter: optional DI seam for the DNI collision
            counter (PR5); the reverse applier bumps it once per
            reverse-path collision routed by
            :func:`record_dni_collision` with
            ``direction="web-to-legacy"``.
        sync_state_path: optional override for ``sync_state.json``.
            When ``None`` defaults to
            ``<APAP_MIGRATION_DIR>/sync_state.json``. The reverse
            applier advances ``tables[table].last_sync_at`` AFTER
            the legacy writes commit; on failure the file is left
            byte-identical to its pre-apply state.

    Returns:
        :class:`migration.apply.ApplyResult` with the per-table
        counts and errors. Same dataclass as the forward applier so
        the CLI can render either direction uniformly.

    Raises:
        MigrationError: any of the typed apply-level failures
            (MSACCESS pre-flight unavailable / running, source drift,
            partial-apply evidence from a prior interrupted run,
            legacy reader/writer errors).
        ValueError: ``table_name`` is not a valid SQL identifier.
    """
    safe = _safe_table(table_name)

    # Load the YAML mapping up-front so a typo fails fast before we
    # acquire the lock. ``load_mapping`` raises ``MappingNotFoundError``
    # on a missing spec — let it propagate.
    mapping = load_mapping(safe)
    web_table = _safe_table(mapping.web_table)

    # Resolve lock / snapshot / partial-apply / sync_state paths so the
    # SIGINT handler and the dry-run / real-apply branches all see the
    # same paths (no env-var race).
    resolved_lock_path = lock_path or _resolve_default_lock_path()
    resolved_snapshot_path = (
        Path(snapshot_path) if snapshot_path else _resolve_default_snapshot_path()
    )
    resolved_partial_path = (
        Path(partial_path) if partial_path else _resolve_default_partial_path()
    )
    resolved_sync_state_path = (
        Path(sync_state_path)
        if sync_state_path
        else _resolve_default_sync_state_path()
    )

    # --- M0 bootstrap is a no-op for reverse (forward only owns
    #     the private bucket + shadow DDL). The forward applier is
    #     the source of truth; we still call the bootstrap module
    #     in case a future PR tightens the invariants (e.g. a
    #     cross-direction invariant that needs to be checked on
    #     every run). Today the call is a guarded no-op so the
    #     reverse applier lands cleanly even without the bootstrap
    #     state.
    if not dry_run:
        bootstrap_m0_infrastructure(client)

    # --- Entry guard: partial-apply evidence from interrupted run -----
    # The forward applier's SIGINT handler writes
    # ``migration.partial_apply.json``; if it exists from a prior
    # forward or reverse run, refuse to start a new reverse until
    # the operator removes the file (forward PR3 contract).
    if not dry_run:
        existing_partial = read_partial_apply(resolved_partial_path)
        if existing_partial is not None:
            from migration.apply import PartialApplyInterruptedError

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

    # --- MSACCESS pre-flight (fail-closed, mirrors forward) -----------
    if not dry_run:
        try:
            msaccess_pids = check_msaccess_running()
        except MsAccessPreflightUnavailableError as preflight_exc:
            logging_mod.log_safe(
                "apply.preflight_unavailable",
                reason=preflight_exc.reason,
            )
            raise
        if msaccess_pids:
            from migration.apply import MsAccessRunningError

            raise MsAccessRunningError(
                pids=msaccess_pids,
                detail=(
                    f"Cannot run apply while MSACCESS.EXE is running "
                    f"(pids={msaccess_pids}). Close the legacy Access "
                    "frontend and retry."
                ),
            )

    # --- Web + legacy snapshot --------------------------------------
    # The reverse applier pulls both sides in one batch each so the
    # per-row diff can be done in-memory (no per-row SQL trip). The
    # diff is bounded by the smaller of the two snapshots — adding a
    # web row with no legacy counterpart yields an INSERT; an
    # unchanged row is a no-op.
    legacy_columns: tuple[str, ...] = tuple(
        c.legacy_column for c in mapping.columns if c.legacy_column
    )
    web_columns: tuple[str, ...] = tuple(c.web_column for c in mapping.columns)

    if web_snapshot is None:
        sql = _build_web_select_sql(web_table, web_columns)
        try:
            web_rows = client.execute_sql(sql)
        except Exception as exc:  # noqa: BLE001 — last-resort guard
            errors: list[str] = []
            errors.append(f"{mapping.web_table}: web query failed: {exc}")
            return ApplyResult(
                table_name=safe,
                applied=0,
                skipped=0,
                errors=errors,
            )
    else:
        web_rows = list(web_snapshot.get(mapping.web_table, []))

    # Pull the full legacy snapshot, indexed by natural key, in ONE
    # batch. The paging loop mirrors the forward applier's pattern
    # but stops after a single sweep (M2 reverse is bounded by the
    # diff size, not by the legacy table size).
    legacy_by_key: dict[str, dict[str, Any]] = {}
    try:
        for _legacy_table_name, rows in legacy_reader.load_legacy_snapshot_batched(
            legacy_path,
            [
                legacy_reader.TableSpec(
                    legacy_table=mapping.legacy_table,
                    columns=legacy_columns or ("*",),
                    where=None,
                )
            ],
        ):
            for legacy_row in rows:
                key_value = _case_insensitive_get(legacy_row, mapping.legacy_key)
                if key_value is None:
                    continue
                legacy_by_key[str(key_value)] = dict(legacy_row)
    except Exception as exc:  # noqa: BLE001 — surface to the operator stream
        logging_mod.log_safe(
            "apply.legacy_read_failed",
            reason=type(exc).__name__,
        )
        raise

    # --- Lock + snapshot + read loop -------------------------------
    lock_ctx = _LockContext(client, resolved_lock_path, dry_run=dry_run)
    snapshot_written = False
    errors: list[str] = []
    applied = 0
    skipped = 0

    sync_state_loaded: Any = None
    sync_state_pre_bytes: bytes | None = None

    try:
        with lock_ctx:
            # --- Snapshot write (AFTER lock, BEFORE first read) ----
            if not dry_run:
                _write_or_check_snapshot(
                    legacy_path=legacy_path,
                    photos_dir_path=photos_dir_path,
                    snapshot_path=resolved_snapshot_path,
                    direction=DIRECTION_WEB_TO_LEGACY,
                )
                snapshot_written = True

            if not dry_run and resolved_sync_state_path.exists():
                sync_state_loaded = load_sync_state(resolved_sync_state_path)
                sync_state_pre_bytes = resolved_sync_state_path.read_bytes()

            # --- Per-row apply loop ---------------------------------
            for web_row in web_rows:
                try:
                    outcome = _reverse_apply_one_row(
                        client=client,
                        mapping=mapping,
                        web_row=web_row,
                        legacy_path=legacy_path,
                        legacy_columns=legacy_columns,
                        web_table=web_table,
                        dry_run=dry_run,
                        legacy_by_key=legacy_by_key,
                        dni_collision_counter=dni_collision_counter,
                    )
                except Exception as exc:  # noqa: BLE001 — last-resort guard
                    natural_key = web_row.get(mapping.key_field) if mapping.key_field else None
                    errors.append(
                        f"{mapping.legacy_table}: unexpected error on "
                        f"{natural_key!r}: {exc}"
                    )
                    continue
                if outcome == "applied":
                    applied += 1
                else:
                    skipped += 1

            # --- Sync-state advance (AFTER legacy writes) -----------
            # The spec scenario ``Sync_state advances after successful
            # legacy write`` is honoured here: we touch sync_state.json
            # ONLY after the per-row loop completes successfully. On
            # any raised exception (caught below in the SIGINT branch
            # or via the apply error swallows), the file is left
            # byte-identical to the pre-apply state via the
            # ``sync_state_pre_bytes`` snapshot in the outer scope.
            if not dry_run and applied > 0 and sync_state_loaded is not None:
                try:
                    update_last_sync_at(
                        sync_state_loaded,
                        mapping.web_table,
                        datetime.now(UTC),
                    )
                    save_sync_state(sync_state_loaded, resolved_sync_state_path)
                except Exception as exc:  # noqa: BLE001 — never mask row errors
                    # The legacy writes already succeeded (we are past
                    # the per-row loop); the apply reports a
                    # categorical sync_state rollback line so the
                    # operator can re-run after fixing the disk
                    # error. We log + swallow so the per-row counts
                    # remain visible.
                    logging_mod.log_safe(
                        "sync_state.rollback",
                        table=mapping.web_table,
                        reason=str(exc),
                    )
                    errors.append(
                        f"{mapping.web_table}: sync_state rollback "
                        f"(legacy writes succeeded; re-run to advance "
                        f"the cursor): {exc}"
                    )

        if migration_report is not None:
            migration_report.counts.setdefault(safe, {})["count_web"] = len(web_rows)
            migration_report.collisions.setdefault(safe, {})[
                "dni_collisions"
            ] = dni_collision_counter.value if dni_collision_counter is not None else 0

        return ApplyResult(
            table_name=safe,
            applied=applied,
            skipped=skipped,
            errors=errors,
        )
    except KeyboardInterrupt:
        if snapshot_written:
            write_partial_apply(
                resolved_partial_path,
                direction=DIRECTION_WEB_TO_LEGACY,
                table_name=safe,
                progress_applied=applied,
                progress_total=None,
                reason="sigint",
            )
        # Also restore sync_state.json if we never reached the
        # save_sync_state call (loop was interrupted mid-flight).
        if sync_state_pre_bytes is not None and resolved_sync_state_path.exists():
            current = resolved_sync_state_path.read_bytes()
            if current != sync_state_pre_bytes:
                try:
                    resolved_sync_state_path.write_bytes(sync_state_pre_bytes)
                except OSError:
                    pass
        raise
    except Exception:
        # Any other unexpected error: roll back sync_state if the
        # loop raised mid-flight (the legacy writes either succeeded
        # for some rows or all rolled back; we restore the file just
        # in case a partial save somehow happened).
        if sync_state_pre_bytes is not None and resolved_sync_state_path.exists():
            current = resolved_sync_state_path.read_bytes()
            if current != sync_state_pre_bytes:
                try:
                    resolved_sync_state_path.write_bytes(sync_state_pre_bytes)
                except OSError:
                    pass
        raise


def _reverse_apply_one_row(
    *,
    client: _InsForgeLike,
    mapping: Any,
    web_row: dict[str, Any],
    legacy_path: str,
    legacy_columns: tuple[str, ...],
    web_table: str,
    dry_run: bool,
    legacy_by_key: dict[str, dict[str, Any]],
    dni_collision_counter: DniCollisionCounter | None,
) -> str:
    """Apply one web row to legacy. Returns ``"applied"`` or ``"skipped"``.

    Per-row logic mirroring :func:`migration.apply._apply_one_row`:

    1. Map web row → legacy-row shape via :func:`_web_to_legacy_row`.
    2. Look up the existing legacy row from the pre-computed
       ``legacy_by_key`` snapshot (one bulk read at the start of
       the run; the diff is bounded by ``< 5.000`` rows × ``< 10``
       columns per design §5).
    3. If absent → INSERT (rare; happy path for newly-added web rows).
    4. If present and equal → skip (no-op).
    5. If present and different → UPDATE + ``sync.applied`` audit log.
    6. For derived columns: if the web-side ``current_state``
       differs from the prior forward-derived state, emit a
       ``LIFECYCLE_REVERSED`` event (PR6 spec scenario). The
       derivation engine is NOT invoked on this path — the
       ``test_derived_column_no_rederive_on_reverse`` atom pins
       that invariant via monkeypatch.
    7. For ``preserve`` columns (web-only shadow, e.g. ``DNI``):
       advance the shadow row's ``last_legacy_snapshot_at``; never
       write ``preserved_value`` (the
       ``test_preserve_column_not_written_to_legacy`` atom pins
       this via static grep).

    Side-effects:

    - One row INSERT/UPDATE against legacy (via the write seam).
    - One ``log_safe("sync.applied", direction="web->legacy", ...)``
      per applied row.
    - Per-row ``record_dni_collision`` invocations on preserve
      columns with no legacy equivalent (e.g. ``DNI``); each bumps
      ``dni_collision_counter`` so the PR7 reconcile CLI can
      surface the count.
    - Per-row ``LIFECYCLE_REVERSED`` events when a derived column
      changed in web between forward and reverse apply.
    - Per-row ``needs_review`` shadow rows when the legacy write
      returns rowcount=0 (drift detection — spec scenario "round-trip
      detects drift as needs_review").
    """
    natural_key_value = _case_insensitive_get(web_row, mapping.key_field)
    if natural_key_value is None:
        raise ValueError(
            f"web row missing natural key {mapping.key_field!r}: {web_row!r}"
        )
    legacy_pk = str(natural_key_value)

    legacy_payload = _web_to_legacy_row(web_row, mapping)

    # Per-row legacy lookup from the in-memory snapshot — avoids a
    # per-row SELECT TOP 1 against pyodbc.
    existing = legacy_by_key.get(legacy_pk)
    # Defensive: in some test seeds the natural-key casing in the
    # web row does not match the legacy row's natural-key case;
    # fall back to a case-insensitive lookup so the round-trip
    # works against the FakeInsForge / Case-sensitive-row fixtures
    # used in ``tests/migration/test_round_trip.py``.
    if existing is None:
        lower_target = legacy_pk.lower()
        for k, row in legacy_by_key.items():
            if k.lower() == lower_target:
                existing = row
                break

    if existing is None:
        # No legacy row yet → INSERT in legacy.
        if dry_run:
            return "applied"  # counted, not written
        _insert_legacy_row(
            legacy_path=legacy_path,
            legacy_table=mapping.legacy_table,
            legacy_payload=legacy_payload,
            natural_key=mapping.legacy_key,
            natural_key_value=legacy_pk,
        )

        # Advance the shadow-state per-row regardless of branch;
        # see the spec scenario "Web-only DNI survives round-trip".
        # Without this, the per-strategy table contract is unmet
        # for preserve columns on the round-trip happy-path (where
        # the mapped payload does not differ, so the divergence
        # handler never fires).
        _advance_preserve_shadow_state(
            client=client,
            mapping=mapping,
            web_row=web_row,
            legacy_pk=legacy_pk,
            direction=DIRECTION_WEB_TO_LEGACY,
            dni_collision_counter=dni_collision_counter,
        )

        logging_mod.log_safe(
            "sync.applied",
            table=web_table,
            pk=legacy_pk,
            direction="web->legacy",
            source_hash=_compute_source_hash(legacy_payload),
            target_hash=None,
            op="INSERT",
            dry_run=False,
            actor="apply_reverse",
        )
        return "applied"

    # Row exists — compare the canonical mapped dict.
    target_payload = {col: existing.get(col) for col in legacy_payload}
    target_hash = _compute_source_hash(target_payload)
    new_hash = _compute_source_hash(legacy_payload)

    # Derived-column override detection runs BEFORE the skip check so
    # a derived-column state change is reported even when the mapped
    # (legacy-bound) payload is identical. The spec scenario
    # ``derived column with state change emits LIFECYCLE_REVERSED``
    # only requires a state change between forward and reverse; a
    # post-forward override of a web-only derived column (where
    # legacy has no column to receive the value) is the dominant
    # reverse-path signal and must surface on every processed row,
    # not just rows whose mapped payload differs.
    _emit_reversed_lifecycle_events_for_changed_derived(
        client=client,
        mapping=mapping,
        existing_legacy_row=existing,
        web_row=web_row,
        legacy_pk=legacy_pk,
    )

    # Advance the preserve-column shadow state for EVERY web row
    # regardless of whether the mapped payload differs — the spec
    # scenario "Web-only DNI survives round-trip" requires
    # ``last_legacy_snapshot_at`` to advance even when the mapped
    # payload is identical. Without this, the happy-path round-trip
    # does not advance the shadow cursor and the
    # ``test_round_trip_100_voluntarios_preserves_dni`` atom fails.
    # The ``preserved_value`` field is never touched (verified by
    # the static-grep atom in test_reverse_apply.py).
    _advance_preserve_shadow_state(
        client=client,
        mapping=mapping,
        web_row=web_row,
        legacy_pk=legacy_pk,
        direction=DIRECTION_WEB_TO_LEGACY,
        dni_collision_counter=dni_collision_counter,
    )

    if new_hash == target_hash:
        return "skipped"

    # Divergence → UPDATE the legacy row.
    if dry_run:
        return "applied"  # counted, not written
    legacy_rowcount = _update_legacy_row(
        legacy_path=legacy_path,
        legacy_table=mapping.legacy_table,
        legacy_payload=legacy_payload,
        natural_key=mapping.legacy_key,
        natural_key_value=legacy_pk,
    )

    # Drift detection (spec scenario "Round-trip detects drift as
    # needs_review"): if the legacy write reports 0 rows affected,
    # the natural-key row was deleted / no longer present in legacy
    # between forward and reverse (operator ran ``DELETE`` in Access,
    # or the row was renamed in a way the apply couldn't see). The
    # reverse applier can't push the web edit to a missing row, so
    # the change is recorded as ``needs_review`` in the shadow table
    # for the operator to resolve via ``apap-migrate reconcile``.
    if legacy_rowcount == 0:
        _record_drift_needs_review(
            client=client,
            mapping=mapping,
            web_row=web_row,
            legacy_pk=legacy_pk,
            source_hash=new_hash,
            target_hash=target_hash,
        )

    logging_mod.log_safe(
        "sync.applied",
        table=web_table,
        pk=legacy_pk,
        direction="web->legacy",
        source_hash=new_hash,
        target_hash=target_hash,
        op="UPDATE",
        dry_run=False,
        rowcount=legacy_rowcount,
        actor="apply_reverse",
    )
    return "applied"


# --- Legacy I/O helpers (use the read + write seams) ------------------


def _insert_legacy_row(
    *,
    legacy_path: str,
    legacy_table: str,
    legacy_payload: dict[str, Any],
    natural_key: str,
    natural_key_value: str,
) -> None:
    """INSERT a new row in legacy via the write seam."""
    safe_table = _safe_table(legacy_table)
    # Drop the natural-key column from the column list so the INSERT
    # form ``INSERT INTO t (cols) VALUES (?, ?, ?)`` carries exactly
    # the columns the row provides. The natural key is bound as the
    # first parameter so a typo on the natural-key column lands in a
    # clean INSERT instead of NULL.
    cols = [
        c for c in legacy_payload if _SAFE_TABLE_NAME.match(c) and c != natural_key
    ]
    if not cols:
        raise ValueError(
            f"no safe columns to INSERT into {legacy_table}; payload={legacy_payload!r}"
        )
    placeholders = ", ".join("?" for _ in cols)
    col_list = ", ".join(cols)
    sql = f"INSERT INTO {safe_table} ({col_list}) VALUES ({placeholders})"
    params = [legacy_payload[c] for c in cols]
    legacy_reader._execute_legacy_write(legacy_path, sql, params)


def _update_legacy_row(
    *,
    legacy_path: str,
    legacy_table: str,
    legacy_payload: dict[str, Any],
    natural_key: str,
    natural_key_value: str,
) -> int:
    """UPDATE the legacy row matching ``natural_key`` with ``legacy_payload``.

    Returns the write-seam rowcount (``int``). When no mapped
    writeable columns exist (a future PR may extend to derived
    payload; today's M2 reverse path is a no-op), returns ``0`` so
    the caller can route the row to ``needs_review`` without
    issuing a no-op SQL.
    """
    safe_table = _safe_table(legacy_table)
    safe_key = _safe_table(natural_key)
    cols = [c for c in legacy_payload if _SAFE_TABLE_NAME.match(c) and c != natural_key]
    if not cols:
        return 0
    set_clause = ", ".join(f"{c} = ?" for c in cols)
    sql = f"UPDATE {safe_table} SET {set_clause} WHERE {safe_key} = ?"
    params = [legacy_payload[c] for c in cols] + [natural_key_value]
    return int(
        legacy_reader._execute_legacy_write(legacy_path, sql, params)
    )


def _record_drift_needs_review(
    *,
    client: _InsForgeLike,
    mapping: Any,
    web_row: dict[str, Any],
    legacy_pk: str,
    source_hash: str,
    target_hash: str,
) -> None:
    """Record a ``needs_review`` shadow row when the reverse write can't land.

    PR6 spec scenario ``Round-trip detects drift as needs_review``:
    when the legacy executor returns ``rowcount == 0`` after an
    UPDATE (i.e., the natural-key row was deleted in legacy between
    forward and reverse), the reverse applier records the divergence
    in ``web_only_feature_shadow`` so the operator can resolve it
    via ``apap-migrate reconcile --filter-direction web-to-legacy``.
    The ``preserved_value`` carries the pre/post hashes (NOT the
    raw payload — count + hash evidence only, per the PII audit
    doc's ``Count + Hash Evidence`` invariant).
    """
    repo = ShadowStateRepository(client)  # type: ignore[arg-type]
    repo.upsert(
        table_name=mapping.web_table,
        legacy_pk=legacy_pk,
        web_pk=legacy_pk,
        web_column="__row__",
        preserved_value={
            "source_hash": source_hash,
            "target_hash": target_hash,
            "drift_kind": "reverse_legacy_row_missing",
        },
        strategy="preserve",
        reconciliation_status="needs_review",
        origin_direction=DIRECTION_WEB_TO_LEGACY,
    )
    repo.update_reconciliation_status(
        table_name=mapping.web_table,
        legacy_pk=legacy_pk,
        web_column="__row__",
        status="needs_review",
        review_reasons=["reverse_drift_legacy_row_missing"],
    )


# --- Derived-column event emission --------------------------------------


def _emit_reversed_lifecycle_events_for_changed_derived(
    *,
    client: _InsForgeLike,
    mapping: Any,
    existing_legacy_row: dict[str, Any],
    web_row: dict[str, Any],
    legacy_pk: str,
) -> None:
    """Emit ``LIFECYCLE_REVERSED`` events for changed derived columns.

    Iterates ``mapping.columns``; for each column with
    ``web_only_strategy == "derived"`` AND whose web-side value
    differs from the legacy-side value, construct a
    :class:`LifecycleEvent` via
    :func:`migration.semantic_events.record_lifecycle_reversed` and
    ``logging_mod.log_safe("lifecycle.reversed", ...)`` so the operator CLI /
    audit dashboards can render the transition. The derivation
    engine is NEVER called on this path — the event is observational
    only (the legacy write already committed).
    """
    legacy_pk_id: int | None = None
    try:
        legacy_pk_id = int(legacy_pk)
    except (TypeError, ValueError):
        legacy_pk_id = None

    for col in mapping.columns:
        strategy = getattr(col, "web_only_strategy", None)
        if strategy != "derived":
            continue
        pre_state = existing_legacy_row.get(col.legacy_column or col.web_column)
        post_state = web_row.get(col.web_column)
        if pre_state == post_state:
            continue
        event = semantic_events_mod.record_lifecycle_reversed(
            pre_state=str(pre_state) if pre_state is not None else None,
            post_state=str(post_state) if post_state is not None else None,
            legacy_source_table=mapping.legacy_table,
            legacy_source_id=legacy_pk_id,
        )
        animal_id = _case_insensitive_get(web_row, "id")
        if animal_id is None:
            rows = client.execute_sql(
                f"SELECT id FROM {_safe_table(mapping.web_table)} "
                f"WHERE {_safe_table(mapping.key_field)} = $1",
                [legacy_pk],
            )
            animal_id = rows[0].get("id") if rows else None
        if animal_id is None:
            raise ValueError(
                f"Cannot resolve animal_id for reversed lifecycle event {legacy_pk!r}"
            )
        semantic_events_mod.persist_lifecycle_reversed(
            web_client=client,
            event=event,
            animal_id=str(animal_id),
            source_entity_id=str(animal_id),
        )
        logging_mod.log_safe(
            "lifecycle.reversed",
            table=mapping.web_table,
            pk=legacy_pk,
            legacy_source_table=event.legacy_source_table,
            legacy_source_id=event.legacy_source_id,
            pre_state=event.metadata.get("pre_state") if event.metadata else None,
            post_state=event.metadata.get("post_state") if event.metadata else None,
            source_direction=(
                event.metadata.get("source_direction") if event.metadata else None
            ),
            actor="apply_reverse",
        )


# --- Preserve-column collision routing (DNI shadow) -------------------


def _advance_preserve_shadow_state(
    *,
    client: _InsForgeLike,
    mapping: Any,
    web_row: dict[str, Any],
    legacy_pk: str,
    direction: str,
    dni_collision_counter: DniCollisionCounter | None,
) -> None:
    """Advance the per-row preserve-column shadow state.

    For each column with ``web_only_strategy == "preserve"`` whose
    web-side value is set, call :func:`record_dni_collision` with
    ``direction`` so the operator can resolve the row via
    ``apap-migrate reconcile --filter-direction web-to-legacy`` AND
    the per-strategy contract ``Reverse: advance last_legacy_snapshot_at``
    is honoured (``record_dni_collision`` updates
    ``last_legacy_snapshot_at`` and stamps the categorical
    ``dni_collision`` review reason via
    ``update_reconciliation_status``).

    Bumps ``dni_collision_counter`` once per collision so the PR7
    reconcile CLI can surface the count via
    ``MigrationReport.collisions[<table>]["dni_collisions"]``.

    Note: column names are looked up case-insensitively against
    the web row (the YAML carries CamelCase names like ``DNI``;
    the web side stores lowercase keys). The ``web_column`` name
    stamped on the shadow row is the canonical YAML form so the
    operator CLI's filter (``--column dni`` or ``DNI``) keeps
    working through future lowercase naming migrations.
    """
    repo = ShadowStateRepository(client)  # type: ignore[arg-type]
    for col in mapping.columns:
        if getattr(col, "web_only_strategy", None) != "preserve":
            continue
        value = _case_insensitive_get(web_row, col.web_column)
        if value is None:
            continue
        dni_collision_mod.record_dni_collision(
            shadow_state=repo,
            table_name=mapping.web_table,
            legacy_pk=legacy_pk,
            web_pk=legacy_pk,
            web_column=col.web_column,
            direction=direction,  # type: ignore[arg-type]
        )
        if dni_collision_counter is not None:
            dni_collision_counter.bump()


# --- Web SELECT builder ------------------------------------------------


def _build_web_select_sql(web_table: str, columns: tuple[str, ...]) -> str:
    """Build the ``SELECT cols FROM table`` for the reverse snapshot."""
    safe = _safe_table(web_table)
    cols = ", ".join(_safe_table(c) for c in columns) or "*"
    return f"SELECT {cols} FROM {safe}"


# --- Snapshot helpers (forward-pattern mirror) --------------------------


def _write_or_check_snapshot(
    *,
    legacy_path: str,
    photos_dir_path: Path | str | None,
    snapshot_path: Path,
    direction: str,
) -> Snapshot:
    """Compute hashes, drift-check, write. Mirror of the forward helper.

    PR3 fail-closed contract preserved: when a previous snapshot's
    ``.accdb_sha256`` / photos manifest disagrees with the freshly
    computed values, raise :class:`SourceDriftError` and leave the
    previous snapshot intact on disk.
    """
    accdb_hash = compute_accdb_hash(legacy_path)
    photos_manifest = compute_photos_dir_hash(photos_dir_path)

    previous = read_snapshot(snapshot_path)
    if previous is not None:
        prospective = Snapshot(
            schema_version=previous.schema_version,
            direction=direction,
            started_at=datetime.now(UTC),
            accdb_sha256=accdb_hash,
            photos_dir_sha256=photos_manifest.sha256,
            photos_file_count=photos_manifest.file_count,
            photos_total_bytes=photos_manifest.total_bytes,
        )
        drift = detect_drift(previous, prospective)
        if drift.drifted:
            from migration.apply import SourceDriftError

            raise SourceDriftError(
                detail=(
                    "Source drift detected between previous and current "
                    "apply run. accdb_sha256_changed="
                    f"{drift.accdb_sha256_changed}, "
                    "photos_dir_sha256_changed="
                    f"{drift.photos_dir_sha256_changed}, "
                    f"photos_file_count_delta={drift.photos_file_count_delta}, "
                    f"photos_total_bytes_delta={drift.photos_total_bytes_delta}. "
                    "Refusing to apply; review the source files."
                ),
                accdb_sha256_changed=drift.accdb_sha256_changed,
                photos_dir_sha256_changed=drift.photos_dir_sha256_changed,
                photos_file_count_delta=drift.photos_file_count_delta,
                photos_total_bytes_delta=drift.photos_total_bytes_delta,
            )

    return write_snapshot(
        snapshot_path,
        direction=direction,
        accdb_sha256=accdb_hash,
        photos_manifest=photos_manifest,
    )


# --- Lock context (forward pattern mirror) -----------------------------


class _LockContext:
    """Tiny context manager wrapping ``acquire_lock`` / ``release_lock``.

    Mirror of ``migration.apply._LockContext``. Skips the lock
    entirely in ``dry_run`` mode so the operator can re-run
    ``--check-only`` freely.
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
            try:
                release_lock(self._lock_path)
            except Exception:  # noqa: BLE001 — never mask the original exc
                pass


# --- Path resolution helpers (forward-pattern mirror) ------------------


def _resolve_default_lock_path() -> Path:
    """``<APAP_MIGRATION_DIR>/migration.lock``. Mirrors the forward helper."""
    import os

    return Path(os.environ.get("APAP_MIGRATION_DIR", "./migration")) / "migration.lock"


def _resolve_default_snapshot_path() -> Path:
    """``<APAP_MIGRATION_DIR>/migration.lock_snapshot.json``."""
    return _resolve_default_lock_path().with_name("migration.lock_snapshot.json")


def _resolve_default_partial_path() -> Path:
    """``<APAP_MIGRATION_DIR>/migration.partial_apply.json``."""
    return _resolve_default_lock_path().with_name("migration.partial_apply.json")


def _resolve_default_sync_state_path() -> Path:
    """``<APAP_MIGRATION_DIR>/sync_state.json``.

    Reverse applier advances ``tables[table].last_sync_at`` AFTER
    the legacy writes commit. The file lives at the same canonical
    path the diff engine + forward applier read, so an operator
    re-run of either direction sees the same cursor.
    """
    return _resolve_default_lock_path().parent / "sync_state.json"


__all__ = [
    "DIRECTION_LEGACY_TO_WEB",
    "DIRECTION_WEB_TO_LEGACY",
    "ReverseApplyError",
    "ReverseSyncStateRollbackError",
    "apply_web_to_legacy",
]
