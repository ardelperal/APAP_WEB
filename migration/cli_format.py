"""Output formatting and PII masking for the ``apap-migrate`` CLI.

Extracted verbatim from ``migration.cli`` (issue #203, AGENTS.md rule
21 module-size budget): the operator-facing formatters, the PII
masking helpers, and the ``--since`` validator. ``migration.cli``
re-imports every name so existing ``from migration.cli import X``
callers keep working unchanged.

The helpers are pure (no I/O, no client state): they take a shadow
row ``dict`` (or a scalar) and return the string the CLI writes to
its injected ``stream``. The PII contract mirrors
``app.core.logging.log_safe``: the closed column list
(``REDACTED_FIELDS``) masks ``preserved_value`` / ``derived_value``,
and a closed regex set masks PK values that look like a DNI, email,
or phone (spec REQ-PII-Audit + PR5 scope).
"""

from __future__ import annotations

import argparse
import re
from datetime import datetime
from typing import Any

from app.core.logging import REDACTED_FIELDS, normalize_key

# --- Formatters ----------------------------------------------------------
#
# One ``key=value`` line per case for ``--check-only`` (T5.1). The
# shadow row is the single source of truth: the CLI never recomputes
# values, only projects the fields the operator needs to make a
# decision. The output is grep / ``jq``-friendly: a single line
# per case with all relevant fields. ``None`` values are rendered
# as the literal string ``"null"`` so the output is grep-safe
# (a missing field is distinguishable from an empty string).
# ``preserved_value`` and ``review_reasons`` are JSON strings
# coming from the JSONB columns; the test harness compares them
# verbatim against the value the fake server returned.
#
# PR 5 follow-up fix (P2 from PR 5 code review): the original
# ``row.get('foo') or 'null'`` pattern collapses an empty string to
# the literal ``"null"``, which makes the operator unable to
# distinguish a NULL column from an empty-string value. The formatters
# below use ``_render_value`` which is NULL-aware: ``None`` → ``null``,
# empty string → ``''`` (empty literal), anything else → ``repr(x)``.
#
# PR5 PII contract: ``preserved_value`` carries raw PII (the value the
# applier would re-write to the web column). When the shadow row's
# ``web_column`` is one of the PII columns (the closed list at
# ``app.core.logging.REDACTED_FIELDS``), the formatter masks the
# value to ``"[REDACTED]"`` so the operator stdout never carries a
# raw DNI / email / phone. Mirrors the closed-list redaction that
# ``log_safe`` performs; the CLI is a second surface that needs the
# same protection (per spec REQ-PII-Audit + PR5 scope).


def _is_pii_web_column(column: str | None) -> bool:
    """Return ``True`` when ``column`` names a PII web column.

    Mirrors the closed-list comparison in :func:`log_safe` (case
    insensitive, ``_``/``-`` normalised) so the CLI mask is consistent
    with the ``log_safe`` mask across the rest of the operator
    surface.
    """
    if not column:
        return False
    return normalize_key(column) in REDACTED_FIELDS


def _mask_pii_value(column: str | None, raw: Any) -> Any:
    """Return ``"[REDACTED]"`` when ``column`` is PII, else ``raw``.

    Used by the CLI formatters to keep the operator-facing stdout
    free of raw PII while preserving the NULL-aware rendering for
    non-PII columns (state machines, natural keys, etc.).
    """
    if _is_pii_web_column(column):
        return "[REDACTED]"
    return raw


# PR5 follow-up: ``legacy_pk`` and ``web_pk`` may carry raw PII (a
# DNI typed as the natural key, an email, a phone number). The
# formatter does not have a column context for the value (it's a
# PK, not a web column), so the column-based mask is not enough.
# The value-based mask below applies five closed regex patterns:
#
# DNI (8 digits + 1 letter):          12345678Z
# NIE (X/Y/Z + 7 digits + 1 letter):  X1234567Z, Y7654321A, Z1234567S
# NIF Especial (K/L/M + 7 + 1):       K1234567A, L1234567B, M1234567C
# Phone E.164 (9 digits ± country):    +34 612345678, +34612345678, +1 5551234567
#   Spanish mobile: leading 6/7/8/9 after country code; minimum 9 digits total.
#   The 9-digit floor excludes numeric NCHIPs (3–5 digits: 001, 1234, 12345).
#   A bare 9-digit string (612345678) is also accepted as a Spanish local-mobile.
# Email (RFC-lite):                   alice@example.org, user+tag@domain.es
#
# UUIDs, NCHIPs, and other natural keys do NOT match any pattern.
# The set is deliberately conservative — false negatives on rare PII
# formats are acceptable as long as the common shapes are caught.
#
# Phone E.164 / national formats — covered by three patterns:
#
# 1. Spanish landline:  (\+34\s?)?[89]\d{8}
#    Matches:  912345678  +34912345678  +34 912345678
# 2. Spanish mobile:    (\+34\s?)?[67]\d{8}
#    Matches:  612345678  +34612345678  +34 612345678
# 3. US international:   ^\+1\s?\d{10}$
#    Matches:  +1 5551234567  +15551234567
#    (NANP: +1 followed by 10-digit subscriber; the space is optional)
#
# NCHIP exclusion: the old pattern ``\+?\d[\d\s\-\(\)]{6,}`` matched any
# 7+ consecutive digit string, producing false positives on numeric NCHIPs
# like "0012345".  The three-pattern seam requires either a +1 prefix (US)
# or a 9-digit subscriber starting with 6-9 (Spanish), which excludes
# all numeric IDs shorter than 9 digits.
#
# Issue #219: extended from 3 to 6 patterns. Previously missed NIE
# (X/Y/Z prefix) and NIF Especial (K/L/M prefix). Phone regex replaced
# with a three-pattern seam to handle ES landline/mobile and US international
# E.164 formats while excluding numeric NCHIPs.
_PII_VALUE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\d{8}[A-Z]$"),                         # Spanish DNI
    re.compile(r"^[XYZ]\d{7}[A-Z]$"),                    # Spanish NIE
    re.compile(r"^[KLM]\d{7}[A-Z]$"),                    # Spanish NIF Especial
    re.compile(r"^(\+34\s?)?[89]\d{8}$"),                 # Spanish landline (optional +34)
    re.compile(r"^(\+34\s?)?[67]\d{8}$"),               # Spanish mobile (optional +34)
    re.compile(r"^\+1\s?\d{10}$"),                       # US international E.164
    re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$"),          # email (RFC-lite)
)


def _looks_like_pii(value: object) -> bool:
    """Return ``True`` when ``value`` matches a PII regex.

    Used by the CLI formatters to mask ``legacy_pk`` / ``web_pk``
    (which carry no ``web_column`` context) when the value matches
    a DNI / email / phone shape. UUIDs, NCHIPs, and other natural
    keys do NOT match any pattern and pass through unchanged.

    Conservative: returns ``False`` for any non-string value or any
    string that doesn't match the closed regex set. The match is
    anchor-to-anchor (``^...$``) so a substring of a UUID cannot
    accidentally match the DNI shape.
    """
    if not isinstance(value, str):
        return False
    return any(pattern.match(value) for pattern in _PII_VALUE_PATTERNS)


def _render_pk(value: Any) -> str:
    """Render a shadow-row PK for the CLI formatters.

    PR5 follow-up: when the PK matches a PII regex (DNI, email,
    phone), the value is masked to ``[REDACTED]`` so the operator
    stdout never carries a raw DNI/email/phone in the PK columns.
    UUIDs and NCHIPs do NOT match any pattern and pass through
    unchanged. Non-string values (None, numbers, dicts) fall
    through to the standard NULL-aware ``_render_value`` path.
    """
    if _looks_like_pii(value):
        return "[REDACTED]"
    return _render_value(value)


def _render_value(x: Any) -> str:
    """Render a single shadow-row value for the ``key=value`` output.

    Rules (PR 5 follow-up):

    - ``None`` → ``"null"`` (the operator can grep the literal).
    - Empty string → ``""`` (rendered as the empty literal, NOT
      collapsed to ``"null"`` — the original bug).
    - String → the string verbatim (preserves JSONB-serialised strings
      like ``'"Adoptado"'`` and bare tokens like ``"v-1"``).
    - Other value → ``str(x)`` (numbers, booleans).
    """
    if x is None:
        return "null"
    return str(x)


def _format_row_for_check_only(row: dict[str, Any]) -> str:
    """One ``key=value`` line per shadow row (T5.1 / design.md §7).

    PR5: ``preserved_value`` AND ``derived_value`` are masked to
    ``"[REDACTED]"`` when ``web_column`` is in the closed PII list
    (the same closed list that ``log_safe`` uses). The mask is
    per-row so non-PII columns (state machines, natural keys) keep
    their verbatim rendering for the operator decision surface. The
    row also carries ``origin_direction`` (PR5 spec) — every listed
    case is stamped so the operator dashboard can route by
    migration direction.

    PR5 follow-up: ``legacy_pk`` and ``web_pk`` are masked via
    :func:`_render_pk` (which matches the PII regexes) so a DNI
    typed as the natural key never reaches operator stdout as raw.
    UUIDs and NCHIPs do not match any pattern and pass through.
    """
    web_column = row.get("web_column")
    masked_preserved = _mask_pii_value(web_column, row.get("preserved_value"))
    masked_derived = _mask_pii_value(web_column, row.get("derived_value"))
    parts: list[str] = [
        f"table={_render_value(row.get('table_name'))}",
        f"legacy_pk={_render_pk(row.get('legacy_pk'))}",
        f"web_pk={_render_pk(row.get('web_pk'))}",
        f"web_column={_render_value(web_column)}",
        f"origin_direction={_render_value(row.get('origin_direction'))}",
        f"status={_render_value(row.get('reconciliation_status'))}",
        f"strategy={_render_value(row.get('strategy'))}",
        f"web_value={_render_value(masked_preserved)}",
        f"derived_value={_render_value(masked_derived)}",
        f"derived_at={_render_value(row.get('derived_at'))}",
        f"last_legacy_snapshot_at={_render_value(row.get('last_legacy_snapshot_at'))}",
        f"last_reconciled_at={_render_value(row.get('last_reconciled_at'))}",
        f"review_reasons={_render_value(row.get('review_reasons'))}",
    ]
    return " ".join(parts)


def _format_row_for_interactive(row: dict[str, Any]) -> str:
    """Multi-line block per shadow row for the interactive prompt.

    Mirrors the ``--check-only`` field set but indented so the
    prompt header reads naturally. Optional fields are only shown
    when populated (skip the noise for ``null`` rows).

    PR5: ``preserved_value`` AND ``derived_value`` are masked to
    ``"[REDACTED]"`` when ``web_column`` is in the closed PII list
    (mirrors ``_format_row_for_check_only``). The interactive flow
    does NOT bypass the redaction — the operator still sees the
    column name, the status, and the categorical review reasons;
    they only lose the raw PII bytes. Resolution prompts that need
    the raw value (e.g. ``(b) accept derived``) go through
    ``_format_value_prompt`` which renders the ``derived_value``
    (NOT the preserved PII). PR5 also stamps ``origin_direction``
    so the operator can see which migration direction produced the
    row.

    PR5 follow-up: ``legacy_pk`` and ``web_pk`` are masked via
    :func:`_render_pk` (same mask as ``_format_row_for_check_only``).
    """
    web_column = row.get("web_column")
    masked_preserved = _mask_pii_value(web_column, row.get("preserved_value"))
    masked_derived = _mask_pii_value(web_column, row.get("derived_value"))
    lines: list[str] = [
        f"  table:                   {_render_value(row.get('table_name'))}",
        f"  legacy_pk:               {_render_pk(row.get('legacy_pk'))}",
        f"  web_pk:                  {_render_pk(row.get('web_pk'))}",
        f"  web_column:              {_render_value(web_column)}",
        f"  origin_direction:        {_render_value(row.get('origin_direction'))}",
        f"  strategy:                {_render_value(row.get('strategy'))}",
        f"  web_value:               {_render_value(masked_preserved)}",
        f"  derived_value:           {_render_value(masked_derived)}",
        f"  derived_at:              {_render_value(row.get('derived_at'))}",
        f"  status:                  {_render_value(row.get('reconciliation_status'))}",
    ]
    if row.get("last_legacy_snapshot_at"):
        lines.append(f"  last_legacy_snapshot_at: {row['last_legacy_snapshot_at']}")
    if row.get("last_reconciled_at"):
        lines.append(f"  last_reconciled_at:      {row['last_reconciled_at']}")
    if row.get("review_reasons"):
        lines.append(f"  review_reasons:          {row['review_reasons']}")
    return "\n".join(lines)


def _format_value_prompt(row: dict[str, Any]) -> str:
    """Build the ``(b) accept derived`` value prompt with the stored
    ``derived_value`` as the default.

    PR 5 follow-up: the operator can press Enter to accept the
    derived value (no retyping). When ``derived_value`` is missing
    (NULL or absent), the prompt does NOT carry a default — the
    operator MUST type a value (the caller still validates the
    non-empty case; an empty input without a default is rejected).
    """
    web_column = row.get("web_column", "")
    derived_value = row.get("derived_value")
    if derived_value is None:
        return f"Enter value for {web_column}: "
    # Strip JSON quotes if the value was serialised through JSONB and
    # came back as a quoted string (e.g. ``'"Adoptado"'`` → ``Adoptado``).
    rendered = derived_value
    if (
        isinstance(derived_value, str)
        and len(derived_value) >= 2
        and derived_value[0] == derived_value[-1] == '"'
    ):
        rendered = derived_value[1:-1]
    return f"Enter value for {web_column} [default: {rendered}]: "


# --- --since validation --------------------------------------------------


def _parse_since(value: str) -> str:
    """Validate ``--since`` is a parseable ISO-8601 timestamp.

    The SQL filter (``last_legacy_snapshot_at >= %s``) compares a
    ``TIMESTAMPTZ`` column against the parameter, so the value is
    forwarded as-is to the driver. We still validate it
    client-side so a typo surfaces early as a clean argparse-style
    error instead of silently returning an empty list.
    """
    try:
        datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(
            f"--since: invalid ISO-8601 timestamp {value!r}: {exc}"
        ) from exc
    return value
