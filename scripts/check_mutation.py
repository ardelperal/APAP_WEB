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
from pathlib import Path
from typing import Any

#: Fraction of INCOMPETENT results above which the run is not trustworthy.
#: An incompetent mutant is one whose mutated source could not execute. A few
#: are normal (a mutation can produce genuinely unrunnable code); a large share
#: means the runner, not the code, is broken.
MAX_INCOMPETENT_RATIO = 0.20

#: Default location of the committed baseline, relative to the repo root.
DEFAULT_BASELINE_PATH = "docs/quality/mutation-baseline.json"

_SURVIVED = "survived"
_KILLED = "killed"
_INCOMPETENT = "incompetent"


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
               wr.test_outcome AS test_outcome
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
            "module_path": Path(str(row["module_path"])).as_posix(),
            "test_outcome": _normalize_outcome(row["test_outcome"]),
        }
        for row in raw_rows
    ]
    return rows, []


def check_run_health(rows: list[dict[str, Any]]) -> list[str]:
    """Return violations for a degenerate run (issue #431, Finding 2).

    These checks run *before* any score comparison. A run that fails them
    carries no information, and reporting its survival rate would be worse
    than reporting nothing.
    """
    total = len(rows)
    if total == 0:
        return ["session contains no mutation jobs — nothing was measured"]

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
    for row in rows:
        module = row["module_path"]
        survivors.setdefault(module, 0)
        if row["test_outcome"] == _SURVIVED:
            survivors[module] += 1
    return dict(sorted(survivors.items()))


def load_baseline(baseline_path: Path) -> tuple[dict[str, int], list[str]]:
    """Return ``(modules, errors)`` from the committed baseline JSON."""
    if not baseline_path.exists():
        return {}, [f"{baseline_path}: baseline not found"]
    try:
        payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {}, [f"{baseline_path}: cannot read baseline ({exc})"]
    modules = payload.get("modules", {})
    if not isinstance(modules, dict):
        return {}, [f"{baseline_path}: 'modules' must be an object"]
    return {str(k): int(v) for k, v in modules.items()}, []


def check_ratchet(
    measured: Mapping[str, int],
    baseline: Mapping[str, int],
) -> tuple[list[str], list[str]]:
    """Return ``(violations, notices)`` for the shrink-only survivor ratchet."""
    violations: list[str] = []
    notices: list[str] = []

    for module, survivors in sorted(measured.items()):
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

    baseline, errors = load_baseline(baseline_path)
    if errors:
        return _fail(errors)

    violations, notices = check_ratchet(measured, baseline)
    for notice in notices:
        print(f"NOTE: {notice}")
    if violations:
        return _fail(violations, f"check_mutation: {len(violations)} violation(s).")
    print(f"check_mutation: OK ({len(measured)} module(s), run is healthy)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
