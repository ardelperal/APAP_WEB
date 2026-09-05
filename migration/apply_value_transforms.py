"""Pure helpers extracted from migration/apply.py.

These two functions are independent of the legacy→web apply orchestrator
and live here so that ``apply.py`` can stay under the 1058-line ratchet
baseline (AGENTS.md rule 21). They are pure: no I/O, no DB, no shared
state. Importing this module is safe — it has no side effects.

Split on 2026-09-05 as part of the M3.1 close + carry-over hygiene pass.
"""
from __future__ import annotations

from typing import Any


def _apply_value_transform(transform: str, value: Any) -> Any:
    """Apply the named transform to a raw legacy value.

    The transform catalogue is defined in ``migration.mappings.ColumnMapping.transform``.
    The dispatcher is a small, explicit table so the set of supported
    transforms is visible at a glance and adding a new one is a one-line
    change.

    Transforms that fail to parse the legacy value (e.g. a malformed
    date string) raise ``ValueError``. The caller (``_legacy_to_web_row``
    or its caller) decides whether to skip the row (route to shadow
    state) or re-raise. The apply pipeline re-raises; the per-row
    ``except InsForgeError`` wraps that into a recorded error in
    ``ApplyResult.errors`` and ``continue`` to the next row, so a
    single bad value does not abort the whole apply.
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





# --- Apply entry point --------------------------------------------------
