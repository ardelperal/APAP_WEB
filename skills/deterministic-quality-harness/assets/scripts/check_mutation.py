#!/usr/bin/env python3
# HARNESS-PROVENANCE: deterministic-quality-harness v1.8 — assets/scripts/check_mutation.py
"""Mutation-survivor ratchet with a degenerate-run guard.

Mutation testing is the only mechanical answer to "do these tests assert anything". Coverage
says a line executed; mutation changes the line and asks whether any test noticed. Everything
else in this harness — complexity, CRAP, duplication — measures the shape of the code. This
measures the value of the suite.

Three things this gate does that a plain threshold on the survival rate does not:

1. **Degenerate-run guard.** A mutation run where nothing executed reports the same perfect
   survival rate as a run that killed every mutant. Ask `cosmic-ray` for the rate after a run
   where every mutant came back INCOMPETENT and it will happily report 0.00 — a threshold gate
   goes green on a run that measured nothing. So an INCOMPETENT share above
   ``MAX_INCOMPETENT_RATIO`` fails the build. A measurement that could not run must never score
   as a perfect one (Hard Rule 18).
2. **Completeness.** Every queued job must have produced a result. A truncated run is a
   degenerate run wearing a smaller hat.
3. **Acquisition grace period.** A module newly added to the target set has no real survivor
   count yet, so it carries an ``AwaitingAcquisition`` marker with the date it landed. The marker
   must be replaced by a real number within ``GRACE_PERIOD_DAYS``, or the gate fails closed —
   otherwise "we haven't measured that one yet" becomes permanent.

Stdlib only, on purpose: the session is read through ``sqlite3`` rather than through the mutation
tool's own API, so this gate and its tests run everywhere — including the platforms where the
mutation runner itself cannot execute mutants.

Exit codes:
    0  run healthy and no module above its BASELINE
    1  missing/unreadable session, incomplete run, degenerate run, a module that grew, an
       expired target date, or an overdue acquisition marker
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from policy_time import add_policy_date_argument
from quality_policy import bind_envelope, expected_subjects
from typing import Any

# --------------------------------------------------------------------------------------------
# CONFIGURATION
# --------------------------------------------------------------------------------------------

#: Share of INCOMPETENT results above which the run is not trustworthy. An incompetent mutant is
#: one whose mutated source could not execute. A few are normal — a mutation can produce
#: genuinely unrunnable code. A large share means the runner is broken, not the code.
MAX_INCOMPETENT_RATIO = 0.20

#: How long an AwaitingAcquisition marker may sit before the gate fails. Long enough for a
#: weekly scheduled mutation run to acquire the real number, short enough that a forgotten entry
#: surfaces inside one sprint.
GRACE_PERIOD_DAYS = 14


@dataclass(frozen=True)
class BaselineEntry:
    """A tolerated survivor count with a mandatory exit plan (Hard Rule 12)."""

    survivors: int
    target: int
    target_date: str  # ISO-8601, YYYY-MM-DD


@dataclass(frozen=True)
class AwaitingAcquisition:
    """A module in the target set whose real survivor count has not been measured yet."""

    since: str  # ISO-8601, the date it landed on the default branch


#: Survivor entries are keyed by ``module-path|operator-name|occurrence``. Module-only keys are
#: reserved for AwaitingAcquisition; migrate aggregate survivor counts with ``--emit-baseline``.
BASELINE: dict[str, BaselineEntry | AwaitingAcquisition] = {}

# --------------------------------------------------------------------------------------------
# MECHANISM
# --------------------------------------------------------------------------------------------

_SURVIVED = "survived"
_KILLED = "killed"
_INCOMPETENT = "incompetent"
_SKIPPED = "skipped"
_KNOWN_TEST_OUTCOMES = frozenset({_SURVIVED, _KILLED, _INCOMPETENT})

#: Cosmic-ray session layout. Read-only, and never through the tool's own API.
_QUERY = """
    SELECT ms.module_path AS module_path,
           ms.operator_name AS operator_name,
           ms.occurrence AS occurrence,
           wr.test_outcome AS test_outcome,
           wr.worker_outcome AS worker_outcome
    FROM work_items AS wi
    JOIN mutation_specs AS ms ON ms.job_id = wi.job_id
    LEFT JOIN work_results AS wr ON wr.job_id = wi.job_id
"""


def _normalise(raw: object) -> str:
    if raw is None:
        return ""
    text = str(raw).strip().lower()
    return text.rsplit(".", 1)[-1] if "." in text else text


def read_session(session_path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    if not session_path.is_file():
        return [], [f"{session_path}: session file not found"]
    try:
        connection = sqlite3.connect(f"file:{session_path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        return [], [f"{session_path}: cannot open session ({exc})"]
    try:
        connection.row_factory = sqlite3.Row
        raw = connection.execute(_QUERY).fetchall()
    except sqlite3.Error as exc:
        return [], [f"{session_path}: cannot read session ({exc})"]
    finally:
        connection.close()
    return [
        {
            "module_path": str(row["module_path"]).replace("\\", "/"),
            "operator_name": str(row["operator_name"]),
            "occurrence": int(row["occurrence"]),
            "test_outcome": _normalise(row["test_outcome"]),
            "worker_outcome": _normalise(row["worker_outcome"]),
        }
        for row in raw
    ], []


def active_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if row["worker_outcome"] != _SKIPPED]


def check_run_health(rows: list[dict[str, Any]]) -> tuple[list[str], dict[str, float]]:
    """Reject a run that did not actually measure anything."""
    violations: list[str] = []
    if not rows:
        return ["session contains no mutation jobs; refusing to report success"], {}

    pending = sum(1 for row in rows if not row["test_outcome"])
    if pending:
        violations.append(f"run incomplete: {pending} of {len(rows)} job(s) produced no result")

    unknown = sorted(
        {
            row["test_outcome"]
            for row in rows
            if row["test_outcome"] and row["test_outcome"] not in _KNOWN_TEST_OUTCOMES
        }
    )
    if unknown:
        violations.append(f"run contains unknown test outcome(s): {', '.join(unknown)}")

    incompetent = sum(1 for row in rows if row["test_outcome"] == _INCOMPETENT)
    killed = sum(1 for row in rows if row["test_outcome"] == _KILLED)
    survived = sum(1 for row in rows if row["test_outcome"] == _SURVIVED)
    ratio = incompetent / len(rows)

    if ratio > MAX_INCOMPETENT_RATIO:
        violations.append(
            f"degenerate run: {ratio:.0%} of mutants were INCOMPETENT "
            f"(limit {MAX_INCOMPETENT_RATIO:.0%}); the runner is broken, not the code"
        )
    if killed == 0 and survived == 0:
        violations.append("degenerate run: no mutant was killed or survived; nothing was measured")

    scored = killed + survived
    metrics = {
        "mutation_score_pct": round(100 * killed / scored, 2) if scored else 0.0,
        "incompetent_ratio_pct": round(100 * ratio, 2),
        "survivors_total": float(survived),
        "mutants_measured": float(len(rows)),
    }
    return violations, metrics


def mutant_identity(row: dict[str, Any]) -> str:
    """Identify the mutation itself, not its module's aggregate survivor count."""
    return f"{row['module_path']}|{row['operator_name']}|{row['occurrence']}"


def measure_survivors(rows: list[dict[str, Any]]) -> dict[str, str]:
    survivors: dict[str, str] = {}
    for row in rows:
        if row["test_outcome"] == _SURVIVED:
            survivors[mutant_identity(row)] = row["module_path"]
    return dict(sorted(survivors.items()))


def check_ratchet(survivors: dict[str, str], today: date) -> tuple[list[str], list[str]]:
    violations: list[str] = []
    notices: list[str] = []
    for identity, module in sorted(survivors.items()):
        allowance = BASELINE.get(identity)
        if allowance is None:
            module_allowance = BASELINE.get(module)
            if isinstance(module_allowance, AwaitingAcquisition):
                notices.append(f"{identity}: acquired surviving mutant; record it now")
            elif isinstance(module_allowance, BaselineEntry):
                violations.append(
                    f"{module}: legacy aggregate BASELINE cannot identify survivors; "
                    f"regenerate it with --emit-baseline (new finding: {identity})"
                )
            else:
                violations.append(f"{identity}: surviving mutant not in BASELINE")
        elif isinstance(allowance, AwaitingAcquisition):
            violations.append(f"{identity}: AwaitingAcquisition must be keyed by module")
        elif allowance.survivors != 1:
            violations.append(
                f"{identity}: stable survivor BASELINE must record survivors=1; "
                "regenerate it with --emit-baseline"
            )
        elif today.isoformat() > allowance.target_date and allowance.target < 1:
            violations.append(
                f"{identity}: BASELINE expired on {allowance.target_date}; "
                f"target was {allowance.target}"
            )
    for identity, allowance in sorted(BASELINE.items()):
        if identity not in survivors and isinstance(allowance, BaselineEntry):
            notices.append(f"{identity}: survivor was killed; remove it from BASELINE")
    return violations, notices


def check_pending_overdue(today: date) -> list[str]:
    """An 'we have not measured this yet' marker must not become permanent."""
    violations: list[str] = []
    for module, allowance in sorted(BASELINE.items()):
        if not isinstance(allowance, AwaitingAcquisition):
            continue
        try:
            since = date.fromisoformat(allowance.since)
        except ValueError:
            violations.append(f"{module}: AwaitingAcquisition has an unparseable date")
            continue
        age = today.toordinal() - since.toordinal()
        if age > GRACE_PERIOD_DAYS:
            violations.append(
                f"{module}: awaiting acquisition for {age} days "
                f"(grace period is {GRACE_PERIOD_DAYS}); the measurement never landed"
            )
    return violations


def render_baseline(survivors: dict[str, str], today: date, horizon_days: int = 90) -> str:
    target_date = date.fromordinal(today.toordinal() + horizon_days).isoformat()
    lines = ["BASELINE: dict[str, BaselineEntry | AwaitingAcquisition] = {"]
    for identity in sorted(survivors):
        lines.append(
            f'    "{identity}": BaselineEntry(survivors=1, '
            f'target=0, target_date="{target_date}"),'
        )
    lines.append("}")
    return "\n".join(lines)


def write_baseline(path: Path, payload: str) -> None:
    """Atomically replace a baseline only after the session has passed health checks."""
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(payload + "\n", encoding="utf-8", newline="\n")
    temporary.replace(path)


def build_report(
    root: Path,
    metrics: dict[str, float],
    violations: list[str],
    status: str,
    policy_date: date,
    observed_subjects: list[str],
) -> dict:
    expected = expected_subjects(root)
    expected_set = set(expected)
    observed_set = set(observed_subjects)
    unclassified = sorted(observed_set - expected_set)
    report = {
        "gate": "mutation",
        "policy_date": policy_date.isoformat(),
        "status": status,
        "indicators": {
            "mutation_score_pct": metrics.get("mutation_score_pct", 0.0),
            "survivors_total": int(metrics.get("survivors_total", 0)),
            "incompetent_ratio_pct": metrics.get("incompetent_ratio_pct", 0.0),
            "mutants_measured": int(metrics.get("mutants_measured", 0)),
        },
        "ceilings": {"incompetent_ratio_pct": MAX_INCOMPETENT_RATIO * 100},
        "findings": [{"file": "<session>", "line": 0, "detail": item} for item in violations],
    }
    return bind_envelope(
        report,
        root,
        "mutation",
        checked=sorted(observed_set & expected_set),
        skipped=[
            {"path": path, "reason": "no mutation specification in session"}
            for path in sorted(expected_set - observed_set)
        ],
        unclassified=unclassified,
    )


def _pin_output_encoding() -> None:
    """Pin stdout/stderr to UTF-8 so output bytes do not depend on the platform locale."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    _pin_output_encoding()
    parser = argparse.ArgumentParser(description=__doc__)
    add_policy_date_argument(parser)
    parser.add_argument("session", type=Path, help="cosmic-ray session database")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository root")
    parser.add_argument("--json", action="store_true", help="emit the indicator envelope")
    parser.add_argument(
        "--emit-baseline",
        action="store_true",
        help="print a BASELINE block for the measured survivors instead of judging them",
    )
    parser.add_argument(
        "--baseline-output",
        type=Path,
        help="atomically write an emitted baseline to this path instead of stdout",
    )
    args = parser.parse_args(argv)
    if args.baseline_output is not None and not args.emit_baseline:
        parser.error("--baseline-output requires --emit-baseline")

    root = args.root.resolve()
    rows, errors = read_session(args.session)
    if errors:
        if args.json:
            report = build_report(root, {}, errors, "error", args.policy_date, [])
            report["detail"] = errors[0]
            print(json.dumps(report))
        else:
            for message in errors:
                print(f"FAIL  {message}", file=sys.stderr)
        return 1

    rows = active_rows(rows)
    observed_subjects = sorted({str(row["module_path"]).replace("\\", "/") for row in rows})
    unexpected_subjects = sorted(set(observed_subjects) - set(expected_subjects(root)))
    today = args.policy_date
    health, metrics = check_run_health(rows)
    survivors = measure_survivors(rows)

    if args.emit_baseline and health:
        for message in health:
            print(f"FAIL  {message}", file=sys.stderr)
        return 1

    if args.emit_baseline:
        payload = render_baseline(survivors, today)
        if args.baseline_output is None:
            print(payload)
        else:
            write_baseline(args.baseline_output, payload)
        return 0

    ratchet, notices = check_ratchet(survivors, today)
    overdue = check_pending_overdue(today)
    violations = health + ratchet + overdue
    if unexpected_subjects:
        violations.append(
            "mutation session contains subjects outside quality policy: "
            + ", ".join(unexpected_subjects)
        )

    if args.json:
        status = "pass" if not violations else "fail"
        print(json.dumps(build_report(root, metrics, violations, status, args.policy_date, observed_subjects), indent=2))
        return 0 if not violations else 1

    for message in violations:
        print(f"FAIL  {message}")
    for message in notices:
        print(f"NOTE  {message}")
    if not violations:
        print(
            f"OK    mutation score {metrics.get('mutation_score_pct', 0.0):.1f}%, "
            f"{int(metrics.get('survivors_total', 0))} survivor(s), run healthy"
        )
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
