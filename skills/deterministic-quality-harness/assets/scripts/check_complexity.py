#!/usr/bin/env python3
# HARNESS-PROVENANCE: deterministic-quality-harness v1.8 — assets/scripts/check_complexity.py
"""Cyclomatic complexity gate with an absolute, global ceiling.

Hard Rule 12: this gate is deliberately NOT a ``top-N`` check. Under ``top-10``, whether a given
function passes depends on the complexity of nine unrelated functions, so the same code yields
different verdicts as its neighbours change. Every function is measured against the same fixed
ceiling, always.

This is the cheap early signal: it needs no coverage data and no test run, so it fails fast and
points at one function. ``check_crap.py`` is the binding constraint (see its docstring).

Exit codes:
    0  no function above MAX_COMPLEXITY outside BASELINE
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

ROOT_PACKAGE = "app"

#: The ceiling. Absolute, global, applied to every function without exception.
MAX_COMPLEXITY = 15

EXCLUDED_PARTS = frozenset({"__pycache__", ".venv", "venv", "build", "dist", "migrations"})


@dataclass(frozen=True)
class BaselineEntry:
    """A tolerated over-ceiling function with a mandatory exit plan (see Hard Rule 12)."""

    complexity: int
    target: int
    target_date: str  # ISO-8601, YYYY-MM-DD


#: Keyed by ``path::qualified_name``. Shrink-only.
BASELINE: dict[str, BaselineEntry] = {}

# --------------------------------------------------------------------------------------------
# MECHANISM
# --------------------------------------------------------------------------------------------

_FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)
_BRANCH_NODES = (
    ast.If,
    ast.IfExp,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.ExceptHandler,
    ast.Assert,
    ast.match_case,
)


@dataclass(frozen=True)
class Measurement:
    key: str
    name: str
    file: str
    line: int
    complexity: int


def _decision_points(node: ast.AST) -> int:
    """Count the decision points directly owned by ``node``.

    Nested functions and classes are skipped: they are measured on their own, and folding them
    into the parent would double-count and make the parent's number depend on its children.
    """
    total = 0
    stack: list[ast.AST] = list(ast.iter_child_nodes(node))
    while stack:
        current = stack.pop()
        if isinstance(current, (*_FUNCTION_NODES, ast.ClassDef)):
            continue
        if isinstance(current, _BRANCH_NODES):
            total += 1
        elif isinstance(current, ast.BoolOp):
            total += len(current.values) - 1
        elif isinstance(current, ast.comprehension):
            total += len(current.ifs)
        stack.extend(ast.iter_child_nodes(current))
    return total


def _walk_functions(node: ast.AST, prefix: str = ""):
    for child in ast.iter_child_nodes(node):
        if isinstance(child, _FUNCTION_NODES):
            qualified = f"{prefix}{child.name}"
            yield qualified, child
            yield from _walk_functions(child, prefix=f"{qualified}.")
        elif isinstance(child, ast.ClassDef):
            yield from _walk_functions(child, prefix=f"{prefix}{child.name}.")
        else:
            yield from _walk_functions(child, prefix=prefix)


def measure(root: Path) -> list[Measurement]:
    """Measure every function, not only the offenders — the indicators need the whole set."""
    measurements: list[Measurement] = []
    for path in subject_paths(root, load_policy()):
        display = str(path.relative_to(root)).replace("\\", "/")
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            measurements.append(
                Measurement(
                    key=f"{display}::<unparseable>",
                    name="<unparseable>",
                    file=display,
                    line=exc.lineno or 0,
                    complexity=MAX_COMPLEXITY + 1,
                )
            )
            continue
        for qualified, function in _walk_functions(tree):
            measurements.append(
                Measurement(
                    key=f"{display}::{qualified}",
                    name=qualified,
                    file=display,
                    line=function.lineno,
                    complexity=1 + _decision_points(function),
                )
            )
    return measurements


def offenders_of(measurements: list[Measurement]) -> list[Measurement]:
    return [item for item in measurements if item.complexity > MAX_COMPLEXITY]


def evaluate(offenders: list[Measurement], today: date) -> tuple[int, list[str]]:
    lines: list[str] = []
    failed = False
    observed = {offender.key: offender for offender in offenders}

    for key in sorted(observed):
        offender = observed[key]
        allowance = BASELINE.get(key)
        location = f"{offender.file}:{offender.line}"
        if allowance is None:
            failed = True
            lines.append(
                f"FAIL  {location}  {offender.name} has complexity {offender.complexity}, "
                f"ceiling is {MAX_COMPLEXITY}"
            )
        elif offender.complexity > allowance.complexity:
            failed = True
            lines.append(
                f"FAIL  {location}  {offender.name} grew to {offender.complexity}, "
                f"BASELINE allows {allowance.complexity}"
            )
        elif today.isoformat() > allowance.target_date and offender.complexity > allowance.target:
            failed = True
            lines.append(
                f"FAIL  {location}  {offender.name} BASELINE expired on {allowance.target_date} "
                f"at complexity {offender.complexity}, target was {allowance.target}"
            )
        elif offender.complexity < allowance.complexity:
            lines.append(
                f"NOTE  {location}  {offender.name} down to {offender.complexity}; "
                f"lower the BASELINE to lock the gain in"
            )

    for key in sorted(BASELINE):
        if key not in observed:
            lines.append(f"NOTE  {key}: now under the ceiling; remove it from BASELINE")

    if not failed:
        lines.append(f"OK    every function at or below complexity {MAX_COMPLEXITY}")
    return (1 if failed else 0), lines


def build_report(root: Path, measurements: list[Measurement], status: str, policy_date: date) -> dict:
    offenders = offenders_of(measurements)
    report = {
        "gate": "complexity",
        "policy_date": policy_date.isoformat(),
        "status": status,
        "indicators": {
            "max_complexity": max((item.complexity for item in measurements), default=0),
            "functions_over_ceiling": len(offenders),
            "functions_measured": len(measurements),
        },
        "ceilings": {"max_complexity": MAX_COMPLEXITY, "functions_over_ceiling": 0},
        "findings": [
            {
                "file": item.file,
                "line": item.line,
                "detail": f"{item.name} has complexity {item.complexity}",
            }
            for item in sorted(offenders, key=lambda entry: entry.key)
        ],
    }
    unclassified = sorted({item.file for item in measurements if item.name == "<unparseable>"})
    checked = [path for path in expected_subjects(root) if path not in unclassified]
    return bind_envelope(
        report, root, "complexity", checked=checked, unclassified=unclassified
    )


def _pin_output_encoding() -> None:
    """Pin stdout/stderr to UTF-8.

    Python picks the output encoding from the platform locale, so the same gate emits different
    bytes on a Windows workstation (cp1252) and a Linux runner (utf-8) — and a non-encodable
    character crashes the write outright. A harness that claims determinism cannot let its own
    output depend on where it ran.
    """
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
    args = parser.parse_args(argv)

    root = args.root.resolve()
    if not (root / ROOT_PACKAGE).is_dir():
        message = f"root package '{ROOT_PACKAGE}' not found under {root}"
        if args.json:
            report = build_report(root, [], "error", args.policy_date)
            report["detail"] = message
            print(json.dumps(report))
        else:
            print(f"FAIL  {message}", file=sys.stderr)
        return 1

    measurements = measure(root)
    if not measurements:
        message = f"no eligible functions found under {root / ROOT_PACKAGE}"
        if args.json:
            report = build_report(root, measurements, "error", args.policy_date)
            report["detail"] = message
            print(json.dumps(report, indent=2))
        else:
            print(f"FAIL  {message}", file=sys.stderr)
        return 1

    exit_code, lines = evaluate(offenders_of(measurements), args.policy_date)

    if args.json:
        print(json.dumps(build_report(root, measurements, "pass" if exit_code == 0 else "fail", args.policy_date), indent=2))
    else:
        for line in lines:
            print(line)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
