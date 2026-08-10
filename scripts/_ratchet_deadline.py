"""Shared deadline-check helper for shrink-only ratchets.

Per ``deterministic-quality-harness`` v1.5 Rule 12: "every BASELINE records
its target value and target date." This module provides the shared
``check_deadline`` function used by every ratchet script
(``check_ruff_ratchet``, ``check_module_size``, ``check_route_size``,
``check_complexity``, ``check_crap``, ``check_mutation_sites``,
``check_docstring_coverage``, ``check_jscpd``, ``check_vulture_guard``).

The check is **informational**: a deadline warning never changes the
script's exit code. A ratchet still fails when a measured value grows
above its baseline; a deadline approaching does not break the build.
That split is deliberate — Rule 12 calls the deadline the "target value
and target date" of the ratchet, not a new failure condition.

Rationale: deadline lines that break the build turn into noise the
moment a project starts a multi-quarter migration and the only way
to silence them is to retire the rule. Warnings let a project ship
progress while still surfacing the schedule.

Each ratchet script uses one ``check_deadline`` call. All entries in
a given ratchet share the same ``(target_value, target_date)`` tuple
because every ratchet has one uniform goal (target=0 to retire,
target=100% for coverage, target=ceiling for CRAP). Per-entry target
overrides are out of scope for this slice — when needed, callers can
filter the BASELINE before computing their own deadline per entry.
"""

from __future__ import annotations

from datetime import date

#: Threshold below which a deadline warning is emitted. The skill is silent on
#: the exact value; 30 days is the convention chosen by APAP_WEB and matches
#: the typical sprint cadence.
WARN_DAYS_AHEAD: int = 30


def check_deadline(
    target: tuple,
    baseline_value,
    measured_value=None,
    *,
    label: str = "ratchet",
    today: date | None = None,
) -> str | None:
    """Return a DEADLINE warning string, or None if no warning is needed.

    Args:
        target: ``(target_value, target_date_str)``. The target_date_str
            must be ISO 8601 (``YYYY-MM-DD``) or empty (in which case this
            function always returns ``None``).
        baseline_value: the ratchet's BASELINE entry for this label.
            Used for the off-track / on-track indicator when measured is
            provided.
        measured_value: optional current measured value. When provided,
            the warning distinguishes OFF-TRACK (measured > baseline) from
            the steady-state report.
        label: short name printed in the warning (e.g. ``"ruff"``,
            ``"module_size"``). Defaults to ``"ratchet"``.
        today: override for the current date. Tests use this; production
            uses ``date.today()``.

    Returns:
        A single warning string if the target date is within
        ``WARN_DAYS_AHEAD`` (or past). Otherwise ``None``.
    """
    if not isinstance(target, tuple) or len(target) != 2:
        return None
    target_value, target_date_str = target
    if not target_date_str:
        return None
    try:
        target_date = date.fromisoformat(target_date_str)
    except ValueError:
        return None

    today = today or date.today()
    days_left = (target_date - today).days
    if days_left >= WARN_DAYS_AHEAD:
        return None

    measured_str = ""
    if measured_value is not None:
        if measured_value > baseline_value:
            measured_str = (
                f" — OFF-TRACK (current: {measured_value} > baseline {baseline_value})"
            )
        else:
            measured_str = f" (current: {measured_value})"

    if days_left < 0:
        return (
            f"[{label}] target {target_value} due {target_date_str} "
            f"OVERDUE by {-days_left} day(s){measured_str}"
        )
    return (
        f"[{label}] target {target_value} due {target_date_str} "
        f"({days_left} day(s) left{measured_str})"
    )


def parse_target_date(date_str: str) -> date | None:
    """Parse an ISO date string. Returns None on bad input.

    Centralised so each ratchet script can read its TARGETS date without
    re-implementing the parsing. Empty string also returns None.
    """
    if not date_str:
        return None
    try:
        return date.fromisoformat(date_str)
    except ValueError:
        return None


__all__ = ["WARN_DAYS_AHEAD", "check_deadline", "parse_target_date"]
