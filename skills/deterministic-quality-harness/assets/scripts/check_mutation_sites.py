#!/usr/bin/env python3
# HARNESS-PROVENANCE: deterministic-quality-harness v1.8 — assets/scripts/check_mutation_sites.py
"""Static mutation-site density gate.

Counts AST-level mutation targets per file without running a single mutant. It is the cheap
proxy for "how much surface would a mutation run have to cover here", and it answers a question
the complexity ceiling cannot: a file can be full of small, simple functions and still be an
enormous mutation surface, because surface is a property of the file, not of any one function.

Upstream (`swarm-forge` `cleaner.prompt`) makes the consequence mandatory rather than advisory:
a changed file above the ceiling is SPLIT before handoff. The ceiling here is upstream's 100.
A mature codebase will need a ratchet to get there — that is what BASELINE is for.

Use ``--emit-baseline`` to generate the BASELINE block rather than hand-writing it; a ratchet you
have to type by hand is a ratchet nobody adopts.

Exit codes:
    0  no file above MAX_MUTATION_SITES outside BASELINE
    1  a new offender, a BASELINE entry that grew, or a BASELINE entry past its target date
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from policy_time import add_policy_date_argument
from quality_policy import bind_envelope, expected_subjects, load_policy, subject_paths

# --------------------------------------------------------------------------------------------
# CONFIGURATION
# --------------------------------------------------------------------------------------------

SCAN_DIRS = ("app",)

#: Upstream's number. Above this, upstream splits the file before handoff rather than
#: negotiating. A legacy codebase ratchets down to it; it does not raise the ceiling to meet
#: the codebase.
MAX_MUTATION_SITES = 100

EXCLUDED_PARTS = frozenset({"__pycache__", ".venv", "venv", "build", "dist", "migrations"})


@dataclass(frozen=True)
class BaselineEntry:
    """A tolerated over-ceiling file with a mandatory exit plan (Hard Rule 12)."""

    sites: int
    target: int
    target_date: str  # ISO-8601, YYYY-MM-DD


BASELINE: dict[str, BaselineEntry] = {}

# --------------------------------------------------------------------------------------------
# MECHANISM
# --------------------------------------------------------------------------------------------

#: Nodes a mutation tool would rewrite. Kept deliberately close to what real mutation operators
#: target, so the static number tracks the real cost of a mutation run.
_MUTABLE_NODES = (
    ast.BinOp,
    ast.BoolOp,
    ast.UnaryOp,
    ast.Compare,
    ast.If,
    ast.IfExp,
    ast.While,
    ast.For,
    ast.Assert,
    ast.Raise,
    ast.Return,
    ast.AugAssign,
)


@dataclass(frozen=True)
class Measurement:
    file: str
    sites: int


def _count_sites(tree: ast.AST) -> int:
    total = 0
    for node in ast.walk(tree):
        if isinstance(node, _MUTABLE_NODES):
            total += 1
        elif isinstance(node, ast.Constant) and isinstance(node.value, (int, float, str, bool)):
            total += 1
        elif isinstance(node, ast.Call):
            total += len(node.args) + len(node.keywords)
    return total


def measure(root: Path) -> list[Measurement]:
    measurements: list[Measurement] = []
    for path in subject_paths(root, load_policy()):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue  # check_layers.py owns the unparseable-file failure
        display = str(path.relative_to(root)).replace("\\", "/")
        measurements.append(Measurement(file=display, sites=_count_sites(tree)))
    return sorted(measurements, key=lambda item: item.file)


def offenders_of(measurements: list[Measurement]) -> list[Measurement]:
    return [item for item in measurements if item.sites > MAX_MUTATION_SITES]


def evaluate(offenders: list[Measurement], today: date) -> tuple[int, list[str]]:
    lines: list[str] = []
    failed = False
    observed = {item.file: item for item in offenders}

    for key in sorted(observed):
        item = observed[key]
        allowance = BASELINE.get(key)
        if allowance is None:
            failed = True
            lines.append(
                f"FAIL  {item.file}: {item.sites} mutation sites, ceiling is {MAX_MUTATION_SITES}"
            )
            lines.append("        split the file before handoff, or ratchet it with a target date")
        elif item.sites > allowance.sites:
            failed = True
            lines.append(
                f"FAIL  {item.file}: grew to {item.sites} sites, BASELINE allows {allowance.sites}"
            )
        elif today.isoformat() > allowance.target_date and item.sites > allowance.target:
            failed = True
            lines.append(
                f"FAIL  {item.file}: BASELINE expired on {allowance.target_date} at "
                f"{item.sites} sites, target was {allowance.target}"
            )
        elif item.sites < allowance.sites:
            lines.append(
                f"NOTE  {item.file}: down to {item.sites} sites; lower the BASELINE to lock it in"
            )

    for key in sorted(BASELINE):
        if key not in observed:
            lines.append(f"NOTE  {key}: now under the ceiling; remove it from BASELINE")

    if not failed:
        lines.append(f"OK    every file at or below {MAX_MUTATION_SITES} mutation sites")
    return (1 if failed else 0), lines


def render_baseline(offenders: list[Measurement], today: date, horizon_days: int = 90) -> str:
    """Emit a BASELINE block. Every entry carries a target and a date; there is no other shape."""
    target_date = date.fromordinal(today.toordinal() + horizon_days).isoformat()
    lines = ["BASELINE: dict[str, BaselineEntry] = {"]
    for item in sorted(offenders, key=lambda entry: entry.file):
        lines.append(
            f'    "{item.file}": BaselineEntry(sites={item.sites}, '
            f'target={MAX_MUTATION_SITES}, target_date="{target_date}"),'
        )
    lines.append("}")
    return "\n".join(lines)


def build_report(root: Path, measurements: list[Measurement], status: str, policy_date: date) -> dict:
    offenders = offenders_of(measurements)
    report = {
        "gate": "mutation_sites",
        "policy_date": policy_date.isoformat(),
        "status": status,
        "indicators": {
            "max_mutation_sites": max((item.sites for item in measurements), default=0),
            "files_over_ceiling": len(offenders),
            "total_mutation_sites": sum(item.sites for item in measurements),
            "files_measured": len(measurements),
        },
        "ceilings": {"max_mutation_sites": MAX_MUTATION_SITES, "files_over_ceiling": 0},
        "findings": [
            {"file": item.file, "line": 0, "detail": f"{item.sites} mutation sites"}
            for item in sorted(offenders, key=lambda entry: entry.file)
        ],
    }
    checked = [item.file for item in measurements]
    unclassified = sorted(set(expected_subjects(root)) - set(checked))
    return bind_envelope(
        report,
        root,
        "mutation_sites",
        checked=checked,
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
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository root")
    parser.add_argument("--json", action="store_true", help="emit the indicator envelope")
    parser.add_argument(
        "--emit-baseline",
        action="store_true",
        help="print a BASELINE block for the current offenders instead of judging them",
    )
    args = parser.parse_args(argv)

    root = args.root.resolve()
    if not any((root / scan_dir).is_dir() for scan_dir in SCAN_DIRS):
        message = f"none of {SCAN_DIRS} found under {root}"
        if args.json:
            report = build_report(root, [], "error", args.policy_date)
            report["detail"] = message
            print(json.dumps(report))
        else:
            print(f"FAIL  {message}", file=sys.stderr)
        return 1

    measurements = measure(root)
    if not measurements:
        message = f"no eligible Python files found under {root}"
        if args.json:
            report = build_report(root, measurements, "error", args.policy_date)
            report["detail"] = message
            print(json.dumps(report, indent=2))
        else:
            print(f"FAIL  {message}", file=sys.stderr)
        return 1

    if args.emit_baseline:
        print(render_baseline(offenders_of(measurements), args.policy_date))
        return 0

    exit_code, lines = evaluate(offenders_of(measurements), args.policy_date)
    if args.json:
        print(json.dumps(build_report(root, measurements, "pass" if exit_code == 0 else "fail", args.policy_date), indent=2))
    else:
        for line in lines:
            print(line)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
