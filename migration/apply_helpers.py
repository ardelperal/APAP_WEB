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

import re
import unicodedata
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # ``_LocalBackendLike`` lives in ``migration.apply`` (kept there because
    # it is the structural type of the public ``apply_legacy_to_web``
    # signature). Re-imported for type checking only.
    # stub adapter in #671 is the placeholder; see web_reader_stub.
    # migration package is being rewritten in #8.
    from migration.apply import SqlExecutor  # noqa: F401

from rapidfuzz import fuzz

from migration import MigrationError


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

    def load_from_db(self, client: SqlExecutor) -> None:
        """Load all active voluntarios from the DB into the index (Level 1).

        Called once per apply run before processing acogidas / adopciones.
        Entries from ``record()`` (Level 2: voluntarios migrated in this run)
        take precedence and are NOT overwritten by DB entries.
        Idempotent in the sense that re-calling never corrupts the index;
        it only adds DB entries that are not yet present.
        """
        sql = "SELECT id, voluntario FROM voluntarios WHERE activo = true"
        for row in client.execute_sql(sql, None):
            norm = _normalise_for_lookup(row.get("voluntario", ""))
            if norm and norm not in self._by_name:
                # Only add if not already registered via record() (Level 2 wins).
                self._by_name[norm] = (str(row["id"]), row["voluntario"])

    def record(self, legacy_name: str, web_uuid: str) -> None:
        """Register a volontario migrated in this run (Level 2 resolution).

        Called after each successful voluntarios INSERT so that a
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
    client,  # migration apply Protocol — see #8
    vol_index: _VoluntariosIndex | None,
    *,
    fuzzy_match: bool = False,
    fuzzy_threshold: int = 85,
    optional: bool = False,
) -> str | None:
    """Resolve a legacy free-text value to a web UUID via FK lookup.

    Exact lookup: SELECT UUID FROM ``lookup_table`` WHERE ``lookup_key`` = $1.
    Fuzzy lookup (for voluntarios): use ``vol_index`` to resolve via
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

    # Exact lookup missed. For voluntarios fuzzy, fall through to the index.
    if fuzzy_match and vol_index is not None:
        return vol_index.resolve(legacy_value, fuzzy_threshold=fuzzy_threshold)

    return None


def _identity_transform(value: Any) -> Any:
    """Trivial pass-through for columns that need no transformation."""
    return value


def _nullify_empty_string_transform(value: Any) -> Any:
    """Map Access's empty-string convention onto Postgres NULL.

    Many legacy text columns store ``''`` instead of ``NULL``; the web
    schema declares them NULLABLE, so ``''`` has to become ``None``
    before the INSERT. Without this transform, dates like
    ``FIMPLANTACIONCHIP=''`` fail with "invalid input syntax for type
    date" (issue #639).
    """
    if value is None:
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    return value


def _normalize_sexo_transform(value: Any) -> Any:
    """Map legacy full-word ``Sexo`` onto single-letter web code.

    ``TbFichaAnimal.Sexo`` stores "Hembra"/"Macho" (full words);
    ``animales.sexo`` has ``CHECK (sexo IN ('M', 'H'))``. Map the
    legacy full-word to the single-letter web code; anything else
    (including ``None`` or empty) becomes ``None`` so the apply
    pipeline reports the row as a skip rather than a CHECK violation
    (issue #639).
    """
    if value is None:
        return None
    s = str(value).strip().upper()
    if s in ("HEMBRA", "H", "FEMALE", "F"):
        return "H"
    if s in ("MACHO", "M", "MALE"):
        return "M"
    # Unknown value (including blank): return None rather than raising.
    # The apply records this as "applied" if the row's source_hash
    # matches an existing web row; if it is a new row, the column will
    # be NULL which is also fine (sexo is nullable in the schema).
    return None


def _normalize_especie_transform(value: Any) -> Any:
    """Upper-case the legacy ``Especie`` column onto the web CHECK.

    ``TbFichaAnimal.Especie`` stores "CANINA" or "felina" (mixed case);
    ``animales.especie`` has ``CHECK (especie IN ('CANINA', 'FELINA'))``
    (uppercase only). Normalise to uppercase so the lowercase legacy
    value does not fail the CHECK (issue #639).
    """
    if value is None:
        return None
    s = str(value).strip().upper()
    if s in ("CANINA", "FELINA"):
        return s
    # Unknown value (including blank) becomes None.
    return None


def _normalize_si_no_transform(value: Any) -> Any:
    """Map legacy ``Sí`` / ``No`` / ``Si`` onto the canonical Spanish.

    Legacy stores "Sí"/"No"/"Si" (with/without tilde, mixed case). The
    web column is TEXT and accepts any string, but the operator expects
    the canonical Spanish "Sí" (with tilde). Normalise so round-trip
    comparison is stable.
    """
    if value is None:
        return None
    s = str(value).strip().lower()
    if s in ("sí", "si", "s", "yes", "1", "true"):
        return "Sí"
    if s in ("no", "n", "0", "false"):
        return "No"
    # Unknown value (including blank) becomes None.
    return None


#: Dispatch table for ``_apply_value_transform``. Keys are the canonical
#: transform names declared in ``migration.mappings.ColumnMapping.transform``;
#: values are pure callables that take the raw legacy value and return
#: the value to be inserted into the web column. ``currency_to_numeric`` /
#: ``double_to_numeric`` and the ``default_*`` / ``fk_lookup`` group are
#: declared in the design but currently pass through (the mapping uses
#: ``identity`` in practice); they are listed explicitly so the supported
#: set is visible at a glance.
TRANSFORMS: dict[str, Any] = {
    "identity": _identity_transform,
    "nullify_empty_string": _nullify_empty_string_transform,
    "normalize_sexo": _normalize_sexo_transform,
    "normalize_especie": _normalize_especie_transform,
    "normalize_si_no": _normalize_si_no_transform,
    "currency_to_numeric": _identity_transform,
    "double_to_numeric": _identity_transform,
    "default_now": _identity_transform,
    "default_uuid": _identity_transform,
    "default_true": _identity_transform,
    "fk_lookup": _identity_transform,
}


def _apply_value_transform(transform: str, value: Any) -> Any:
    """Apply the named transform to a raw legacy value.

    Catalogue lives in :data:`TRANSFORMS`; the supported set is visible
    at a glance. Unknown transform names fall through to
    :func:`_identity_transform` for safety (the ``Literal`` type in
    ``ColumnMapping`` prevents this at validation time, but the
    defensive fallback is cheap).
    """
    return TRANSFORMS.get(transform, _identity_transform)(value)


__all__ = [
    "SourceDriftError",
    "TRANSFORMS",
    "_SAFE_TABLE_NAME",
    "_VoluntariosIndex",
    "_apply_value_transform",
    "_identity_transform",
    "_normalise_for_lookup",
    "_normalize_especie_transform",
    "_normalize_sexo_transform",
    "_normalize_si_no_transform",
    "_nullify_empty_string_transform",
    "_resolve_fk_value",
    "_safe_table",
    "_strip_accents",
]
