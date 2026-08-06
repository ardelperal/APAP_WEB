"""Mutation-score ratchet with a degenerate-run guard (issue #431).

Reads a cosmic-ray session database and enforces, in order:

1. **Completeness** — every queued job produced a result.
2. **Non-degeneracy** — the run actually exercised the suite. This is the
   reason the script exists. ``cr-rate`` only looks at the survival rate, so
   it reports ``0.00`` both for a run that killed every mutant and for a run
   where nothing executed at all. Measured on 2026-08-06: cosmic-ray 8.4.6 on
   native Windows returns ``INCOMPETENT`` for 100% of mutants (27/27 on a
   12-line control module, 233/233 on ``migration/derivation.py``) and
   ``cr-rate`` still reports ``0.00`` — a threshold gate would pass green on a
   run that measured nothing. The same control module on WSL returns 27/27
   ``KILLED``. See issue #431, Findings 1 and 2.
3. **Shrink-only survivor ratchet** — per-module surviving-mutant counts may
   only decrease, mirroring ``scripts/check_module_size.py``,
   ``scripts/check_route_size.py`` and ``scripts/check_mutation_sites.py``.
4. **Acquisition grace period** — modules newly added to the target set carry
   an ``awaiting_acquisition`` marker (issue #434) with the ISO date they
   landed on ``main``. The marker must be replaced with a real survivor count
   by the next scheduled CI mutation run. The ratchet fails closed if the
   marker persists past ``GRACE_PERIOD_DAYS`` days, so a broken measurement
   cannot stay silent (§32.P3). See issue #434.

Stdlib-only on purpose: the session is read through ``sqlite3`` rather than
through cosmic-ray's own API, so this gate and its tests run on any platform,
including the ones where cosmic-ray itself cannot execute mutants.

Usage::

    python scripts/check_mutation.py <session.sqlite>
    python scripts/check_mutation.py <session.sqlite> --emit-baseline

Exit code 0 when clean, 1 on any violation.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

#: Fraction of INCOMPETENT results above which the run is not trustworthy.
#: An incompetent mutant is one whose mutated source could not execute. A few
#: are normal (a mutation can produce genuinely unrunnable code); a large share
#: means the runner, not the code, is broken.
MAX_INCOMPETENT_RATIO = 0.20

#: Default location of the committed baseline, relative to the repo root.
DEFAULT_BASELINE_PATH = "docs/quality/mutation-baseline.json"

#: How long an ``awaiting_acquisition`` entry may sit before the ratchet
#: fails the build. Long enough for the weekly scheduled CI ``mutation`` job
#: to acquire the real number, short enough that a forgotten entry surfaces
#: within a sprint (issue #434). 14 days = two weekly cron windows.
GRACE_PERIOD_DAYS = 14

_SURVIVED = "survived"
_KILLED = "killed"
_INCOMPETENT = "incompetent"
_SKIPPED = "skipped"


def _normalize_outcome(raw: object) -> str:
    """Map a stored ``TestOutcome`` to its lowercase value.

    SQLAlchemy persists ``Enum(TestOutcome)`` by member *name* (``KILLED``),
    while ``TestOutcome`` is a ``StrEnum`` whose *value* is ``killed``. Accept
    either so the gate does not depend on that storage detail.
    """
    if raw is None:
        return ""
    return str(raw).strip().lower()


def read_session(session_path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Return ``(rows, errors)`` for one cosmic-ray session database.

    Each row carries ``module_path`` and the normalized ``test_outcome``.
    A queued job with no result row yields ``test_outcome = ""``.
    """
    if not session_path.exists():
        return [], [f"{session_path}: session file not found"]

    query = """
        SELECT ms.module_path AS module_path,
               wr.test_outcome AS test_outcome,
               wr.worker_outcome AS worker_outcome
        FROM work_items AS wi
        JOIN mutation_specs AS ms ON ms.job_id = wi.job_id
        LEFT JOIN work_results AS wr ON wr.job_id = wi.job_id
    """
    try:
        connection = sqlite3.connect(f"file:{session_path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        return [], [f"{session_path}: cannot open session ({exc})"]

    try:
        connection.row_factory = sqlite3.Row
        raw_rows = connection.execute(query).fetchall()
    except sqlite3.Error as exc:
        return [], [f"{session_path}: cannot read session ({exc})"]
    finally:
        connection.close()

    rows = [
        {
            # cosmic-ray on Windows records backslash-separated module paths
            # (e.g. ``app\\modules\\m.py``); the committed baseline is POSIX.
            # Normalising to forward slashes before constructing ``Path``
            # makes the conversion OS-independent — on Linux, ``Path``
            # treats backslashes as ordinary filename characters and would
            # otherwise leave them in place.
            "module_path": str(row["module_path"]).replace("\\", "/"),
            "test_outcome": _normalize_outcome(row["test_outcome"]),
            "worker_outcome": _normalize_outcome(row["worker_outcome"]),
        }
        for row in raw_rows
    ]
    return rows, []


def active_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop jobs deliberately excluded before execution.

    ``cr-filter-operators`` records a filtered mutant as
    ``worker_outcome = SKIPPED`` with a NULL ``test_outcome``. Those are not
    pending work and they are not results — they were never meant to run, so
    they must not count toward completeness, the INCOMPETENT ratio, or the
    survivor totals. Without this, enabling the filter would make every
    session look incomplete.
    """
    return [row for row in rows if row["worker_outcome"] != _SKIPPED]


def check_run_health(rows: list[dict[str, Any]]) -> list[str]:
    """Return violations for a degenerate run (issue #431, Finding 2).

    These checks run *before* any score comparison. A run that fails them
    carries no information, and reporting its survival rate would be worse
    than reporting nothing.
    """
    if not rows:
        return ["session contains no mutation jobs — nothing was measured"]

    rows = active_rows(rows)
    total = len(rows)
    if total == 0:
        return [
            "every mutant in the session was filtered out — the "
            "exclude-operators list is too broad to measure anything"
        ]

    pending = sum(1 for row in rows if not row["test_outcome"])
    if pending:
        return [
            f"session is incomplete: {pending}/{total} job(s) have no result "
            "— re-run `cosmic-ray exec` to completion before gating"
        ]

    incompetent = sum(1 for row in rows if row["test_outcome"] == _INCOMPETENT)
    killed = sum(1 for row in rows if row["test_outcome"] == _KILLED)
    ratio = incompetent / total

    violations: list[str] = []
    if ratio > MAX_INCOMPETENT_RATIO:
        violations.append(
            f"{incompetent}/{total} mutants ({ratio:.1%}) came back INCOMPETENT, "
            f"above the {MAX_INCOMPETENT_RATIO:.0%} ceiling — the runner is broken, "
            "not the code. cosmic-ray does not execute mutants on native Windows; "
            "run the mutation job on Linux (issue #431, Finding 1)"
        )
    if killed == 0:
        violations.append(
            f"0/{total} mutants were killed — the test suite did not run against "
            "the mutated code. A survival rate computed from this session is "
            "meaningless (issue #431, Finding 2)"
        )
    return violations


def measure_survivors(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Return POSIX-style module path to surviving-mutant count."""
    survivors: dict[str, int] = {}
    for row in active_rows(rows):
        module = row["module_path"]
        survivors.setdefault(module, 0)
        if row["test_outcome"] == _SURVIVED:
            survivors[module] += 1
    return dict(sorted(survivors.items()))


def load_baseline(
    baseline_path: Path,
) -> tuple[dict[str, int], dict[str, str], list[str]]:
    """Return ``(modules, awaiting_acquisition, errors)`` from the baseline JSON.

    ``modules`` is the shrink-only map of path -> surviving-mutant count.
    ``awaiting_acquisition`` is the map of path -> ISO date the entry landed
    on ``main`` (issue #434). Both must be JSON objects; otherwise the
    baseline is rejected up front so a malformed file cannot pass the ratchet
    silently.
    """
    if not baseline_path.exists():
        return {}, {}, [f"{baseline_path}: baseline not found"]
    try:
        payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {}, {}, [f"{baseline_path}: cannot read baseline ({exc})"]

    modules_raw = payload.get("modules", {})
    if not isinstance(modules_raw, dict):
        return {}, {}, [f"{baseline_path}: 'modules' must be an object"]
    try:
        modules = {str(k): int(v) for k, v in modules_raw.items()}
    except (TypeError, ValueError) as exc:
        return {}, {}, [f"{baseline_path}: 'modules' contains non-int values ({exc})"]

    awaiting_raw = payload.get("awaiting_acquisition", {})
    if not isinstance(awaiting_raw, dict):
        return (
            {},
            {},
            [f"{baseline_path}: 'awaiting_acquisition' must be an object"],
        )
    awaiting_acquisition = {str(k): str(v) for k, v in awaiting_raw.items()}

    return modules, awaiting_acquisition, []


def check_ratchet(
    measured: Mapping[str, int],
    baseline: Mapping[str, int],
    awaiting_acquisition: Mapping[str, str] = {},
) -> tuple[list[str], list[str]]:
    """Return ``(violations, notices)`` for the shrink-only survivor ratchet.

    Modules in ``awaiting_acquisition`` are excluded from the
    "no baseline entry" violation: they are intentionally pending and are
    enforced separately by ``check_pending_overdue``. Every other measured
    module must have a baseline entry, and every baseline entry must show
    up in the session or be marked stale.
    """
    violations: list[str] = []
    notices: list[str] = []

    for module, survivors in sorted(measured.items()):
        if module in awaiting_acquisition:
            continue
        if module not in baseline:
            violations.append(
                f"{module}: {survivors} surviving mutant(s) but no baseline entry — "
                "add it in this PR (`--emit-baseline`) so the count is pinned"
            )
        elif survivors > baseline[module]:
            violations.append(
                f"{module}: {survivors} surviving mutant(s), grew beyond its "
                f"baseline of {baseline[module]} (ratchet: kill the new survivors "
                "or strengthen the tests)"
            )
        elif survivors < baseline[module]:
            notices.append(
                f"{module}: {survivors} surviving mutant(s), below baseline "
                f"{baseline[module]} — lower the entry in the same PR"
            )

    for module in sorted(set(baseline) - set(measured)):
        violations.append(
            f"{module}: stale baseline entry — the session covered no such module"
        )
    return violations, notices


def check_pending_overdue(
    awaiting_acquisition: Mapping[str, str],
    today: date,
    grace_period_days: int = GRACE_PERIOD_DAYS,
) -> list[str]:
    """Return violation messages for ``awaiting_acquisition`` entries past their grace period.

    A pending entry is overdue when ``today - since > grace_period_days``.
    Long-enough grace gives the scheduled CI ``mutation`` job time to acquire
    the real number; short-enough that a forgotten entry surfaces within a
    sprint. See issue #434 and AGENTS.md §32.P3.

    ``today`` is injected to keep the function pure and testable across
    platforms; callers should pass ``date.today()`` (the production path)
    or a fixed date (the test path).
    """
    violations: list[str] = []
    for module, since_str in sorted(awaiting_acquisition.items()):
        try:
            since = date.fromisoformat(since_str)
        except ValueError:
            violations.append(
                f"{module}: awaiting_acquisition date {since_str!r} is not a valid "
                "ISO date (expected YYYY-MM-DD)"
            )
            continue
        age_days = (today - since).days
        if age_days > grace_period_days:
            violations.append(
                f"{module}: awaiting_acquisition marker is {age_days} days old, "
                f"past the {grace_period_days}-day grace period. The next scheduled "
                "CI mutation job should have replaced this entry with the real "
                "survivor count acquired on Linux. See issue #434."
            )
    return violations


def _fail(messages: list[str], summary: str | None = None) -> int:
    """Print each message as a FAIL line plus an optional summary; return 1."""
    for message in messages:
        print(f"FAIL: {message}")
    if summary is not None:
        print(summary)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", type=Path, help="cosmic-ray session database")
    parser.add_argument("--baseline", type=Path, default=None)
    parser.add_argument("--emit-baseline", action="store_true")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    baseline_path = args.baseline or (root / DEFAULT_BASELINE_PATH)

    rows, errors = read_session(args.session.resolve())
    if errors:
        return _fail(errors)

    health = check_run_health(rows)
    if health:
        return _fail(
            health,
            f"check_mutation: {len(health)} violation(s) — run not trustworthy.",
        )

    measured = measure_survivors(rows)
    if args.emit_baseline:
        print(json.dumps({"modules": measured}, indent=2, sort_keys=True))
        return 0

    baseline, awaiting_acquisition, errors = load_baseline(baseline_path)
    if errors:
        return _fail(errors)

    pending_violations = check_pending_overdue(
        awaiting_acquisition, date.today(), GRACE_PERIOD_DAYS
    )
    violations, notices = check_ratchet(measured, baseline, awaiting_acquisition)
    for notice in notices:
        print(f"NOTE: {notice}")
    if violations or pending_violations:
        all_violations = pending_violations + violations
        return _fail(
            all_violations, f"check_mutation: {len(all_violations)} violation(s)."
        )
    pending_count = len(awaiting_acquisition)
    if pending_count:
        print(
            f"check_mutation: OK ({len(measured)} module(s), "
            f"{pending_count} awaiting acquisition)"
        )
    else:
        print(f"check_mutation: OK ({len(measured)} module(s), run is healthy)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
