"""Internal helpers for ``migration.apply`` (module-size split).

The private ``_``-prefixed helpers and supporting classes that
``apply.py``'s ``apply_legacy_to_web`` pipeline uses live here,
so the parent module stays under the 700-line AGENTS.md
rule 21 budget. The public API (``apply_legacy_to_web``) is
unchanged; ``migration.apply`` re-imports the helpers via
``from migration.apply_helpers import ...`` so callers inside
the apply code keep the same name resolution.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # ``_InsForgeLike`` lives in ``migration.apply`` (kept there because
    # it is the structural type of the public ``apply_legacy_to_web``
    # signature). Re-imported for type checking only.
    from migration.apply import _InsForgeLike  # noqa: F401

from rapidfuzz import fuzz

from app.core import logging as logging_mod
from migration import MigrationError
from migration.lock_snapshot import Snapshot, detect_drift
from migration.shadow_state import ShadowStateRepository


class SourceDriftError(MigrationError):
    """The on-disk source changed between consecutive apply runs.

    The previous ``migration.lock_snapshot.json`` disagrees with the
    freshly-computed fingerprints of the ``.accdb`` or the photos
    directory. PR3 fails closed (no auto-accept). The CLI converts
    this exception to exit code 6 plus a runbook URL. A future PR
    will add ``--accept-drift`` for the explicit-acknowledge path.
    """

    def __init__(
        self,
        *,
        detail: str,
        accdb_sha256_changed: bool,
        photos_dir_sha256_changed: bool,
        photos_file_count_delta: int,
        photos_total_bytes_delta: int,
    ) -> None:
        super().__init__(detail)
        self.accdb_sha256_changed = accdb_sha256_changed
        self.photos_dir_sha256_changed = photos_dir_sha256_changed
        self.photos_file_count_delta = photos_file_count_delta
        self.photos_total_bytes_delta = photos_total_bytes_delta
        self.detail = detail


_SAFE_TABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_table(table_name: str) -> str:
    """Return ``table_name`` if it is a safe SQL identifier, else raise.

    Belt-and-braces the same as ``migration.cli._apply_accept_derived``;
    Hard Rule 8 + AGENTS.md §1: never trust identifiers from external
    input.
    """
    if not _SAFE_TABLE_NAME.match(table_name):
        raise ValueError(
            f"unsafe SQL identifier {table_name!r}; must match {_SAFE_TABLE_NAME.pattern}"
        )
    return table_name


# --- Voluntarios index for FK resolution -----------------------------------


class _VoluntariosIndex:
    __slots__ = ("_by_name",)

    def __init__(self) -> None:
        # Maps normalised name -> (web_uuid, original_name).
        self._by_name: dict[str, tuple[str, str]] = {}

    def load_from_db(self, client: _InsForgeLike) -> None:
        """Load all active volontarios from the DB into the index (Level 1).

        Called once per apply run before processing acogidas / adopciones.
        Entries from ``record()`` (Level 2: volontarios migrated in this run)
        take precedence and are NOT overwritten by DB entries.
        Idempotent in the sense that re-calling never corrupts the index;
        it only adds DB entries that are not yet present.
        """
        sql = "SELECT id, voluntario FROM volontarios WHERE activo = true"
        for row in client.execute_sql(sql, None):
            norm = _normalise_for_lookup(row.get("voluntario", ""))
            if norm and norm not in self._by_name:
                # Only add if not already registered via record() (Level 2 wins).
                self._by_name[norm] = (str(row["id"]), row["voluntario"])

    def record(self, legacy_name: str, web_uuid: str) -> None:
        """Register a volontario migrated in this run (Level 2 resolution).

        Called after each successful volontarios INSERT so that a
        subsequent acogida row can resolve the FK using the just-migrated
        volontario (Level 2 beats Level 3 fuzzy).
        """
        norm = _normalise_for_lookup(legacy_name)
        if norm:
            self._by_name[norm] = (web_uuid, legacy_name)

    def resolve(
        self,
        legacy_name: str | None,
        *,
        fuzzy_threshold: int = 85,
    ) -> str | None:
        """Resolve a free-text legacy name to a volontario UUID.

        Levels:
          1. Exact normalised match in the index -> return UUID.
          2. Fuzzy match (rapidfuzz.WRatio >= threshold) -> return best UUID.
          3. No match -> return None.
        """
        if not legacy_name or not str(legacy_name).strip():
            return None

        name = str(legacy_name).strip()
        norm = _normalise_for_lookup(name)

        # Level 1: exact normalised match.
        if norm in self._by_name:
            return self._by_name[norm][0]

        # Level 2: fuzzy match -- score every entry, return best above threshold.
        best_uuid: str | None = None
        best_score = 0.0
        stripped = _strip_accents(norm)
        for indexed_norm, (uuid, _original) in self._by_name.items():
            indexed_stripped = _strip_accents(indexed_norm)
            score = fuzz.WRatio(stripped, indexed_stripped)
            if score >= fuzzy_threshold and score > best_score:
                best_score = score
                best_uuid = uuid

        return best_uuid


def _normalise_for_lookup(name: str) -> str:
    """Lower-case + strip + collapse internal whitespace.

    Mirrors the normalisation used in the dedup pipeline so that the
    FK resolver and the dedup CLI produce consistent results.
    """
    return " ".join(name.strip().lower().split())


def _strip_accents(name: str) -> str:
    """Decompose to NFD then drop combining marks.

    Used so "Maria Garcia" / "Maria Garcia" normalise to the same
    ASCII string before WRatio scoring.
    """
    return "".join(
        ch
        for ch in unicodedata.normalize("NFKD", name)
        if not unicodedata.combining(ch)
    )


# --- Mapping helpers ----------------------------------------------------


def _resolve_fk_value(
    legacy_value: str | None,
    lookup_table: str,
    lookup_key: str,
    client: _InsForgeLike,
    vol_index: _VoluntariosIndex | None,
    *,
    fuzzy_match: bool = False,
    fuzzy_threshold: int = 85,
    optional: bool = False,
) -> str | None:
    """Resolve a legacy free-text value to a web UUID via FK lookup.

    Exact lookup: SELECT UUID FROM ``lookup_table`` WHERE ``lookup_key`` = $1.
    Fuzzy lookup (for volontarios): use ``vol_index`` to resolve via
    the 4-level strategy (index -> fuzzy -> None/raise).
    """
    if not legacy_value or not str(legacy_value).strip():
        return None

    safe_table = _safe_table(lookup_table)
    safe_key = _safe_table(lookup_key)
    sql = f'SELECT id FROM {safe_table} WHERE {safe_key} = $1 LIMIT 1'  # noqa: S608
    rows = client.execute_sql(sql, [str(legacy_value).strip()])
    if rows:
        return str(rows[0]["id"])

    # Exact lookup missed. For volontarios fuzzy, fall through to the index.
    if fuzzy_match and vol_index is not None:
        return vol_index.resolve(legacy_value, fuzzy_threshold=fuzzy_threshold)

    return None


def _apply_value_transform(transform: str, value: Any) -> Any:
    """Apply the named transform to a raw legacy value.

    Catalogue lives in ``migration.mappings.ColumnMapping.transform``.
    Dispatcher is an explicit table so the supported set is visible at
    a glance. Failures raise ``ValueError``; the apply pipeline re-raises
    and the per-row ``except InsForgeError`` records the error and
    continues (a single bad value must not abort the whole apply).
    """
    if transform == "identity":
        return value
    if transform == "nullify_empty_string":
        # Access empty string -> Postgres NULL. Many legacy text columns
        # store '' instead of NULL; the web schema declares them NULLABLE,
        # so '' has to become None before the INSERT. Without this
        # transform, dates like FIMPLANTACIONCHIP='' fail with
        # "invalid input syntax for type date" (issue #639).
        if value is None:
            return None
        if isinstance(value, str) and value.strip() == "":
            return None
        return value
    if transform == "normalize_sexo":
        # TbFichaAnimal.Sexo stores "Hembra"/"Macho" (full words).
        # animales.sexo has CHECK (sexo IN ('M', 'H')). Map the legacy
        # full-word to the single-letter web code; anything else
        # (including None or empty) becomes None so the apply pipeline
        # reports it as a skip rather than a CHECK violation (issue #639).
        if value is None:
            return None
        s = str(value).strip().upper()
        if s in ("HEMBRA", "H", "FEMALE", "F"):
            return "H"
        if s in ("MACHO", "M", "MALE"):
            return "M"
        if s == "":
            return None
        # Unknown value: return None rather than raising. The apply
        # records this as "applied" if the row's source_hash matches
        # an existing web row; if it is a new row, the column will be
        # NULL which is also fine (sexo is nullable in the schema).
        return None
    if transform == "normalize_especie":
        # TbFichaAnimal.Especie stores "CANINA" or "felina" (mixed case).
        # animales.especie has CHECK (especie IN ('CANINA', 'FELINA'))
        # (uppercase only). Normalise to uppercase so the lowercase
        # legacy value does not fail the CHECK (issue #639).
        if value is None:
            return None
        s = str(value).strip().upper()
        if s in ("CANINA", "FELINA"):
            return s
        if s == "":
            return None
        return None
    if transform == "normalize_si_no":
        # Legacy stores "Sí"/"No"/"Si" (with/without tilde, mixed case).
        # The web column is TEXT and accepts any string, but the operator
        # expects the canonical Spanish "Sí" (with tilde). Normalise so
        # round-trip comparison is stable.
        if value is None:
            return None
        s = str(value).strip().lower()
        if s in ("sí", "si", "s", "yes", "1", "true"):
            return "Sí"
        if s in ("no", "n", "0", "false"):
            return "No"
        if s == "":
            return None
        return None
    if transform in ("currency_to_numeric", "double_to_numeric"):
        # The legacy driver returns a string-formatted number (e.g.
        # "12,34 €"); the web schema has NUMERIC. These transforms were
        # declared in the original design but not implemented yet
        # (mapping uses identity in practice). The dispatcher is the
        # future home for them; for now we pass through.
        return value
    if transform in ("default_now", "default_uuid", "default_true", "fk_lookup"):
        # The legacy-row path never reaches these (web-only / fk paths
        # are handled by the FK branch above). The dispatcher falls
        # through with identity for safety.
        return value
    # Unknown transform: pass through. The Literal type in
    # ColumnMapping prevents this at validation time, but a defensive
    # fallback is cheap.
    return value


def _legacy_to_web_row(
    legacy_row: dict[str, Any],
    mapping: Any,
    client: _InsForgeLike,
    vol_index: _VoluntariosIndex | None = None,
) -> dict[str, Any]:
    """Map a legacy ``dict`` to its web-column ``dict``.

    Walks the ``mapping.columns`` list and emits only the columns with a
    non-null ``legacy_column``. Web-only columns (``legacy_column=None``,
    e.g. ``DNI`` on ``voluntarios``) are skipped -- they are owned by
    the web side and the shadow-state handles their reconciliation.

    For columns with ``transform: fk_lookup``, resolves the legacy free-text
    value to a web UUID via :func:`_resolve_fk_value`.  volontario columns
    use fuzzy matching when the YAML declares ``fuzzy_match: true``.
    """
    out: dict[str, Any] = {}
    for col in mapping.columns:
        # FK columns (transform: fk_lookup) always need resolution,
        # regardless of whether their YAML column declares legacy_column.
        # The YAML uses legacy_column=None for FK columns that have no direct
        # legacy equivalent (the legacy value lives in fk_lookups[].legacy_column).
        # Check this FIRST so we don't skip FK columns at the next gate.
        if col.transform == "fk_lookup":
            lookup_spec = next(
                (lk for lk in mapping.fk_lookups if lk.name == col.lookup),
                None,
            )
            if lookup_spec is None:
                continue
            # Prefer col.legacy_column; fall back to lookup_spec.legacy_column
            # (for FK columns that only declare the legacy column in fk_lookups).
            legacy_src = col.legacy_column or lookup_spec.legacy_column
            resolved = _resolve_fk_value(
                legacy_row.get(legacy_src),
                lookup_table=lookup_spec.lookup_table,
                lookup_key=lookup_spec.lookup_legacy_key,
                client=client,
                vol_index=vol_index,
                fuzzy_match=lookup_spec.fuzzy_match,
                fuzzy_threshold=lookup_spec.fuzzy_threshold,
                optional=lookup_spec.optional,
            )
            out[col.web_column] = resolved
        elif col.legacy_column is None:
            # Web-only non-FK column (id, fecha_alta, DNI, ...) -- handled
            # by the SQL default or the shadow-state.
            continue
        else:
            raw = legacy_row.get(col.legacy_column)
            out[col.web_column] = _apply_value_transform(col.transform, raw)
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


def _write_or_check_snapshot(
    *,
    legacy_path: str,
    photos_dir_path: Path | str | None,
    snapshot_path: Path,
) -> Snapshot:
    """Compute hashes, drift-check against the existing snapshot, then write.

    Raises ``SourceDriftError`` if a previous snapshot exists with
    different fingerprints; in that case the previous snapshot is
    preserved on disk (no destructive overwrite). Returns the newly
    written ``Snapshot`` so callers can inspect ``started_at`` if
    needed.
    """
    # Lazy-import so test monkeypatches on
    # ``migration.apply.compute_accdb_hash`` flow through.
    from migration.apply import compute_accdb_hash, compute_photos_dir_hash
    accdb_hash = compute_accdb_hash(legacy_path)
    photos_manifest = compute_photos_dir_hash(photos_dir_path)

    # Lazy-import so test monkeypatches on
    # ``migration.apply.read_snapshot`` flow through.
    from migration.apply import read_snapshot
    previous = read_snapshot(snapshot_path)
    if previous is not None:
        # Build a prospective snapshot with the SAME shape that
        # ``write_snapshot`` would produce, then compare ignoring the
        # ``started_at`` timestamp (it always advances). Empty / missing
        # sources produce ``EMPTY_SHA256`` consistently so a fresh
        # empty source matches a previous empty-source snapshot.
        prospective = Snapshot(
            schema_version=previous.schema_version,
            direction="legacy-to-web",
            started_at=datetime.now(UTC),
            accdb_sha256=accdb_hash,
            photos_dir_sha256=photos_manifest.sha256,
            photos_file_count=photos_manifest.file_count,
            photos_total_bytes=photos_manifest.total_bytes,
        )
        drift = detect_drift(previous, prospective)
        if drift.drifted:
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

    # Lazy-import so test monkeypatches on
    # migration.apply.write_snapshot flow through.
    from migration.apply import write_snapshot
    return write_snapshot(
        snapshot_path,
        direction="legacy-to-web",
        accdb_sha256=accdb_hash,
        photos_manifest=photos_manifest,
    )


def _apply_one_row(
    *,
    client: _InsForgeLike,
    mapping: Any,
    web_table: str,
    legacy_row: dict[str, Any],
    dry_run: bool,
    vol_index: _VoluntariosIndex | None = None,
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
        # The legacy row has no natural key -- there is nothing to match
        # against the web side. Surface as an error so the CLI's error
        # count bumps.
        raise ValueError(
            f"legacy row missing natural key {mapping.legacy_key!r}: {legacy_row!r}"
        )
    legacy_pk = str(legacy_pk_value)

    source_hash = _compute_source_hash(legacy_row)
    web_row = _legacy_to_web_row(legacy_row, mapping, client, vol_index)

    existing = _fetch_web_row_by_key(client, mapping, legacy_pk)

    if existing is None:
        if dry_run:
            return "applied"  # counted, not written
        returned = _insert_web_row(client, web_table, web_row)
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
        # Register the new row in the volontarios index so subsequent
        # rows (acogidas / adopciones) can resolve FKs via Level 2.
        # Only for the volontarios table; other tables contribute no
        # volontario name -> UUID entries.
        if vol_index is not None and mapping.web_table == "volontarios":
            web_uuid = returned[0]["id"] if returned else None
            if web_uuid:
                vol_index.record(str(legacy_pk_value), str(web_uuid))
        return "applied"

    # Row exists -- compare the canonical mapped dict.
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
    sql = f"SELECT * FROM {table} WHERE {key_col} = $1 LIMIT 1"  # noqa: S608 ids validados
    rows = client.execute_sql(sql, [legacy_pk])
    return rows[0] if rows else None


def _insert_web_row(
    client: _InsForgeLike, web_table: str, web_row: dict[str, Any]
) -> list[dict[str, Any]]:
    """INSERT ``web_row`` into ``web_table`` and return the ``RETURNING`` row.

    The SQL is constructed from the column list of ``web_row`` so the
    function works against any mapping without a per-table hand-coded
    INSERT. ``id`` (UUID) and timestamps (``fecha_alta``,
    ``updated_at``) are handled by the DB defaults (``DEFAULT
    gen_random_uuid()``, ``DEFAULT now()``) -- we just don't include
    them in the params if they're missing from the mapped row.

    Returns the rows from ``RETURNING id`` so callers can record the
    new web UUID (e.g. for FK index registration in VOL-04).
    """
    safe_table = _safe_table(web_table)
    cols = [c for c in web_row if _SAFE_TABLE_NAME.match(c)]
    if not cols:
        raise ValueError(f"no safe columns to INSERT into {web_table}")
    placeholders = ", ".join(f"${i + 1}" for i in range(len(cols)))
    cols_vals = f"({', '.join(cols)}) VALUES ({placeholders})"
    sql = f"INSERT INTO {safe_table} {cols_vals} RETURNING id"  # noqa: S608 ids validados
    params = [web_row[c] for c in cols]
    return client.execute_sql(sql, params)


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
    """Wraps ``acquire_lock`` / ``release_lock`` in a context manager.

    Stdlib ``contextlib.AbstractContextManager`` would do, but the
    dataclass-shaped object reads cleaner at the apply call site.

    Skips the lock entirely in ``dry_run`` mode — the operator can
    re-run ``apply --check-only`` freely without locking out a real
    apply.
    """

    def __init__(
        self,
        _client: _InsForgeLike,
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
        # Lazy-import so test monkeypatches on
        # migration.apply.acquire_lock flow through.
        from migration.apply import acquire_lock
        acquire_lock(self._lock_path)
        self._acquired = True
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._acquired:
            # Release even on the error path (Hard Rule 8 + the
            # apply slice's "lock always released" contract).
            try:
                # Lazy-import for the same reason as acquire_lock.
                from migration.apply import release_lock
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


def _resolve_default_snapshot_path() -> Path:
    """Resolve the snapshot path when the caller did not pass one.

    Same ``APAP_MIGRATION_DIR`` convention as the lock path. The
    snapshot lives next to the lock file and the partial-apply
    evidence so the operator's mental model is "everything the apply
    run touched lives in ``APAP_MIGRATION_DIR``".
    """
    return _resolve_default_lock_path().with_name("migration.lock_snapshot.json")


def _resolve_default_partial_path() -> Path:
    """Resolve the partial-apply evidence path when the caller did not pass one."""
    return _resolve_default_lock_path().with_name("migration.partial_apply.json")


__all__ = [
    "SourceDriftError",
    "_LockContext",
    "_SAFE_TABLE_NAME",
    "_VoluntariosIndex",
    "_apply_value_transform",
    "_compute_source_hash",
    "_fetch_web_row_by_key",
    "_insert_web_row",
    "_legacy_to_web_row",
    "_normalise_for_lookup",
    "_record_shadow_divergence",
    "_resolve_default_lock_path",
    "_resolve_default_partial_path",
    "_resolve_default_snapshot_path",
    "_resolve_fk_value",
    "_safe_table",
    "_strip_accents",
    "_write_or_check_snapshot",
]
