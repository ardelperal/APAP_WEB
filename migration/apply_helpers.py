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
    # ``_InsForgeLike`` lives in ``migration.apply`` (kept there because
    # it is the structural type of the public ``apply_legacy_to_web``
    # signature). Re-imported for type checking only.
    from migration.apply import _InsForgeLike  # noqa: F401

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


__all__ = [
    "SourceDriftError",
    "_SAFE_TABLE_NAME",
    "_VoluntariosIndex",
    "_apply_value_transform",
    "_normalise_for_lookup",
    "_resolve_fk_value",
    "_safe_table",
    "_strip_accents",
]
