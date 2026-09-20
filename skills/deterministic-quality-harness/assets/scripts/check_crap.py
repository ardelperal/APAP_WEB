#!/usr/bin/env python3
# HARNESS-PROVENANCE: deterministic-quality-harness v1.8 — assets/scripts/check_crap.py
"""CRAP gate — Change Risk Anti-Patterns, per function.

    CRAP(f) = CC(f)^2 * (1 - coverage(f))^3 + CC(f)

The point of CRAP over raw complexity: it prices complexity by how well it is tested. A branchy
function with real tests around it is a known quantity; the same function untested is the thing
that breaks in production. One number, both axes.

Read the ceiling carefully. At 100% coverage CRAP collapses to CC, so ``MAX_CRAP = 6`` means no
function may exceed complexity 6 no matter how well tested it is. That is deliberate upstream
(`swarm-forge` `cleaner.prompt`: "reduce CRAP to 6 or below") and it DOMINATES the complexity
ceiling in ``check_complexity.py``: a function at CC 7 can never pass this gate. The complexity
gate stays because it is cheap and runs without coverage data, so it fails earlier and more
clearly — it is the smoke alarm, this is the audit.

Fails closed: no coverage data means no verdict, and no verdict means exit 1. A CRAP gate that
silently assumed full coverage would report the healthiest possible number for untested code,
which is exactly backwards.

Exit codes:
    0  every function at or below MAX_CRAP, outside BASELINE
    1  a new offender, a BASELINE entry that grew, a BASELINE entry past its target date, or
       missing/unusable coverage data
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

#: Upstream ceiling. See the module docstring before raising it — this number is what makes the
#: harness demand small functions rather than merely well-tested large ones.
MAX_CRAP = 6.0

#: Reported as an indicator, not gated here: the coverage floor belongs to pytest's
#: --cov-fail-under so that a single tool owns a single verdict.
COVERAGE_JSON = "coverage.json"

EXCLUDED_PARTS = frozenset({"__pycache__", ".venv", "venv", "build", "dist", "migrations"})


@dataclass(frozen=True)
class BaselineEntry:
    """A tolerated CRAP score with a mandatory exit plan (Hard Rule 12)."""

    crap: float
    target: float
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
    coverage: float
    crap: float


class CoverageUnavailable(RuntimeError):
    """Raised when coverage data is missing, malformed, or does not cover the package."""


def _decision_points(node: ast.AST) -> int:
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


def _own_lines(function: ast.AST) -> set[int]:
    """Lines belonging to this function but not to a nested function or class.

    Nested definitions are measured on their own, exactly as in ``check_complexity.py``. Folding
    their lines into the parent would make the parent's coverage depend on its children's.
    """
    start = getattr(function, "lineno", 0)
    end = getattr(function, "end_lineno", start)
    own = set(range(start, end + 1))
    for child in ast.iter_child_nodes(function):
        for node in ast.walk(child):
            if isinstance(node, (*_FUNCTION_NODES, ast.ClassDef)):
                nested_start = getattr(node, "lineno", 0)
                nested_end = getattr(node, "end_lineno", nested_start)
                own -= set(range(nested_start, nested_end + 1))
    return own


def load_coverage(root: Path, coverage_path: Path) -> dict[str, tuple[set[int], set[int]]]:
    """Return ``{posix_relative_path: (executed_lines, missing_lines)}``."""
    if not coverage_path.is_file():
        raise CoverageUnavailable(
            f"{coverage_path} not found — run "
            f"'pytest --cov --cov-report=json:{COVERAGE_JSON}' before this gate"
        )
    try:
        payload = json.loads(coverage_path.read_text(encoding="utf-8"))
        files = payload["files"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise CoverageUnavailable(
            f"{coverage_path} is not a usable coverage report: {exc}"
        ) from exc

    table: dict[str, tuple[set[int], set[int]]] = {}
    for raw_path, entry in files.items():
        normalised = raw_path.replace("\\", "/")
        try:
            normalised = Path(raw_path).resolve().relative_to(root).as_posix()
        except (ValueError, OSError):
            pass
        table[normalised] = (
            set(entry.get("executed_lines", [])),
            set(entry.get("missing_lines", [])),
        )
    if not table:
        raise CoverageUnavailable(f"{coverage_path} reports no files")
    return table


def _lookup(table: dict[str, tuple[set[int], set[int]]], display: str):
    if display in table:
        return table[display]
    for key, value in table.items():
        if key.endswith("/" + display) or display.endswith("/" + key):
            return value
    return None


def measure(root: Path, coverage_path: Path) -> tuple[list[Measurement], float]:
    """Measure every function plus the package-wide line coverage indicator."""
    table = load_coverage(root, coverage_path)
    measurements: list[Measurement] = []
    executed_total = 0
    statements_total = 0

    policy = load_policy()
    paths = subject_paths(root, policy)
    declared = {path.relative_to(root).as_posix() for path in paths}
    covered = set(table)
    unexpected = sorted(covered - declared)
    if unexpected:
        raise CoverageUnavailable(
            "coverage denominator contains subjects outside quality policy: " + ", ".join(unexpected)
        )
    for path in paths:
        display = str(path.relative_to(root)).replace("\\", "/")
        entry = _lookup(table, display)
        if entry is None:
            raise CoverageUnavailable(
                f"{display} is under the root package but absent from {coverage_path.name}; "
                f"either it is untestable and belongs in the declared boundary, or coverage did "
                f"not run over it"
            )
        executed, missing = entry
        executed_total += len(executed)
        statements_total += len(executed) + len(missing)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for qualified, function in _walk_functions(tree):
            own = _own_lines(function)
            hit = len(own & executed)
            total = hit + len(own & missing)
            coverage = 1.0 if total == 0 else hit / total
            complexity = 1 + _decision_points(function)
            measurements.append(
                Measurement(
                    key=f"{display}::{qualified}",
                    name=qualified,
                    file=display,
                    line=function.lineno,
                    complexity=complexity,
                    coverage=coverage,
                    crap=complexity**2 * (1 - coverage) ** 3 + complexity,
                )
            )

    if not measurements:
        raise CoverageUnavailable("no functions found to measure; refusing to report success")
    line_coverage = 100.0 * executed_total / statements_total if statements_total else 0.0
    return measurements, line_coverage


def offenders_of(measurements: list[Measurement]) -> list[Measurement]:
    return [item for item in measurements if item.crap > MAX_CRAP]


def evaluate(offenders: list[Measurement], today: date) -> tuple[int, list[str]]:
    lines: list[str] = []
    failed = False
    observed = {offender.key: offender for offender in offenders}

    for key in sorted(observed):
        offender = observed[key]
        location = f"{offender.file}:{offender.line}"
        detail = (
            f"CRAP {offender.crap:.1f} (complexity {offender.complexity}, "
            f"coverage {offender.coverage:.0%})"
        )
        allowance = BASELINE.get(key)
        if allowance is None:
            failed = True
            lines.append(f"FAIL  {location}  {offender.name}: {detail}, ceiling is {MAX_CRAP:.0f}")
            lines.append("        cover the branches, split the function, or both")
        elif offender.crap > allowance.crap:
            failed = True
            lines.append(
                f"FAIL  {location}  {offender.name}: {detail}, BASELINE allows {allowance.crap:.1f}"
            )
        elif today.isoformat() > allowance.target_date and offender.crap > allowance.target:
            failed = True
            lines.append(
                f"FAIL  {location}  {offender.name}: BASELINE expired on {allowance.target_date} "
                f"at {detail}, target was {allowance.target:.1f}"
            )
        elif offender.crap < allowance.crap:
            lines.append(
                f"NOTE  {location}  {offender.name}: down to {offender.crap:.1f}; "
                f"lower the BASELINE to lock the gain in"
            )

    for key in sorted(BASELINE):
        if key not in observed:
            lines.append(f"NOTE  {key}: now under the ceiling; remove it from BASELINE")

    if not failed:
        lines.append(f"OK    every function at or below CRAP {MAX_CRAP:.0f}")
    return (1 if failed else 0), lines


def build_report(root: Path, measurements: list[Measurement], line_coverage: float, status: str, policy_date: date) -> dict:
    offenders = offenders_of(measurements)
    report = {
        "gate": "crap",
        "policy_date": policy_date.isoformat(),
        "status": status,
        "indicators": {
            "max_crap": round(max((item.crap for item in measurements), default=0.0), 2),
            "functions_over_ceiling": len(offenders),
            "functions_measured": len(measurements),
            "line_coverage_pct": round(line_coverage, 2),
        },
        "ceilings": {"max_crap": MAX_CRAP, "functions_over_ceiling": 0},
        "findings": [
            {
                "file": item.file,
                "line": item.line,
                "detail": f"{item.name}: CRAP {item.crap:.1f} "
                f"(complexity {item.complexity}, coverage {item.coverage:.0%})",
            }
            for item in sorted(offenders, key=lambda entry: entry.key)
        ],
    }
    return bind_envelope(report, root, "crap", checked=expected_subjects(root))


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
    parser.add_argument(
        "--coverage-json",
        type=Path,
        default=None,
        help=f"coverage report path (default: <root>/{COVERAGE_JSON})",
    )
    parser.add_argument("--json", action="store_true", help="emit the indicator envelope")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    coverage_path = args.coverage_json or (root / COVERAGE_JSON)

    try:
        measurements, line_coverage = measure(root, coverage_path)
    except CoverageUnavailable as exc:
        if args.json:
            report = build_report(root, [], 0.0, "error", args.policy_date)
            report["detail"] = str(exc)
            print(json.dumps(report))
        else:
            print(f"FAIL  {exc}", file=sys.stderr)
        return 1

    exit_code, lines = evaluate(offenders_of(measurements), args.policy_date)

    if args.json:
        status = "pass" if exit_code == 0 else "fail"
        print(json.dumps(build_report(root, measurements, line_coverage, status, args.policy_date), indent=2))
    else:
        for line in lines:
            print(line)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
