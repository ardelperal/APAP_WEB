"""Module-size ratchet for APAP_WEB (AGENTS.md rule 21, issue #202).

Enforces the module-size budget: no Python module under ``app/`` or
``migration/`` may exceed ``MAX_LINES`` lines. Modules that already
exceeded the budget when the rule landed live in ``BASELINE`` and may
only shrink — growing a baselined module past its recorded size fails
the check, and shrinking one prints a reminder to lock the improvement
into ``BASELINE``.

Usage::

    python scripts/check_module_size.py [root]

``root`` defaults to the repository root (the parent of ``scripts/``).
Exit code 0 when clean, 1 on any violation. Stdlib-only, deterministic,
path-separator-safe (baseline keys are POSIX-style relative paths).

Run locally before pushing; CI runs it in the ``lint`` job (pinned by
``tests/test_module_size.py::test_ci_workflow_lint_job_runs_module_size_gate``).

Tests: ``tests/test_module_size.py``.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping
from pathlib import Path

# Sibling scripts in scripts/.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _quality_envelope import write_envelope  # noqa: E402 - sys.path tweak above
from _ratchet_deadline import check_deadline  # noqa: E402 - sys.path tweak above

#: Hard budget for any new module under SCAN_DIRS.
MAX_LINES = 700

#: Directories (relative to the scanned root) subject to the budget.
#: tests/ and scripts/ are intentionally exempt — the budget targets
#: product code, where god-files hide layering violations.
SCAN_DIRS = ("app", "migration")

#: Known offenders at the time rule 21 landed (2026-07-18 audit,
#: re-measured on main). Keys are POSIX-style paths relative to the
#: repo root; values are the exact line counts recorded that day.
#: RATCHET: entries may only shrink or disappear. When you reduce one
#: of these modules, update its entry to the new (smaller) count in the
#: same PR — tests/test_module_size.py::test_baseline_matches_measured_tree
#: fails on any drift between this dict and the real tree. Never add a
#: new entry: split the module instead.
BASELINE: dict[str, int] = {
    # NOTE: ``migration/apply.py`` shrunk below MAX_LINES (700) during
    # the InsForge retirement (chore(insforge) series on main) and
    # was removed from BASELINE to satisfy ``test_baseline_matches_measured_tree``.
    # The remaining offender is ``migration/reconcile.py`` at 976 lines;
    # split it (or shrink it below 700) to retire the last BASELINE entry.
    "migration/reconcile.py": 976,
}

#: Ratchet deadline (deterministic-quality-harness v1.5 Rule 12). Every
#: baselined module's goal is to shrink below MAX_LINES (target=0 entries).
#: The deadline is set to the project-wide pre-MVP finale; revisit and tighten
#: per-entry once the ratchet is retired.
TARGET: tuple[int, str] = (0, "2026-12-31")


def count_lines(path: Path) -> int:
    """Count physical lines the same way on Windows and Linux."""
    return len(path.read_text(encoding="utf-8").splitlines())


def _iter_python_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for scan_dir in SCAN_DIRS:
        base = root / scan_dir
        if not base.is_dir():
            continue
        files.extend(
            path
            for path in base.rglob("*.py")
            if "__pycache__" not in path.parts
        )
    return sorted(files)


def check_tree(
    root: Path,
    *,
    max_lines: int = MAX_LINES,
    baseline: Mapping[str, int] | None = None,
) -> tuple[list[str], list[str]]:
    """Check every module under ``root``'s SCAN_DIRS against the budget.

    Returns ``(violations, notices)``. Violations fail the check;
    notices are informational (e.g. a baselined module shrank and the
    baseline should be updated to lock in the improvement).
    """
    if baseline is None:
        baseline = BASELINE
    violations: list[str] = []
    notices: list[str] = []
    seen: set[str] = set()

    for path in _iter_python_files(root):
        rel = path.relative_to(root).as_posix()
        lines = count_lines(path)
        if rel in baseline:
            seen.add(rel)
            budget = baseline[rel]
            if lines > budget:
                violations.append(
                    f"{rel}: {lines} lines, grew beyond its baseline of {budget} "
                    f"(ratchet: baselined modules may only shrink — split it "
                    f"instead of growing it)"
                )
            elif lines < budget:
                notices.append(
                    f"{rel}: {lines} lines, below its baseline of {budget} — "
                    f"update BASELINE in scripts/check_module_size.py to lock "
                    f"in the improvement"
                    + (
                        f" (now within the {max_lines}-line budget: remove the "
                        f"entry entirely)"
                        if lines <= max_lines
                        else ""
                    )
                )
        elif lines > max_lines:
            violations.append(
                f"{rel}: {lines} lines, exceeds the {max_lines}-line budget "
                f"(AGENTS.md rule 21) — split the module; do NOT add it to "
                f"BASELINE"
            )

    for rel in sorted(set(baseline) - seen):
        violations.append(
            f"{rel}: baselined at {baseline[rel]} lines but the file does not "
            f"exist under {root} — remove the stale BASELINE entry"
        )

    return violations, notices


def _pin_output_encoding() -> None:
    """Pin stdout/stderr to UTF-8: output must not depend on the locale (issue #488)."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    _pin_output_encoding()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=None)
    parser.add_argument(
        "--emit-envelope",
        type=Path,
        default=None,
        metavar="PATH",
        help="Also write the indicator envelope (Rule 16) to PATH as UTF-8 JSON.",
    )
    args = parser.parse_args(argv)
    root = (
        args.root.resolve()
        if args.root is not None
        else Path(__file__).resolve().parents[1]
    )

    violations, notices = check_tree(root)

    for notice in notices:
        print(f"NOTE {notice}")
    for violation in violations:
        print(f"FAIL {violation}")

    # Files over budget are the "violations that aren't in BASELINE". A
    # baselined file is allowed to be over MAX_LINES (its own shrink-only
    # budget is recorded in BASELINE); a non-baselined file is a hard fail.
    files_over_budget = sum(
        1 for v in violations if not any(v.startswith(rel + ":") for rel in BASELINE)
    )

    if violations:
        print(
            f"check_module_size: {len(violations)} violation(s). "
            f"Budget: {MAX_LINES} lines per module under "
            f"{', '.join(f'{d}/' for d in SCAN_DIRS)} (AGENTS.md rule 21)."
        )
        status = "fail"
    else:
        print("check_module_size: OK")
        status = "pass"
    warning = check_deadline(TARGET, len(BASELINE), label="module_size")
    if warning:
        print(f"DEADLINE {warning}")

    if args.emit_envelope is not None:
        write_envelope(
            out_path=args.emit_envelope,
            gate="module_size",
            status=status,
            indicators={
                "files_in_baseline": len(BASELINE),
                "files_over_budget": files_over_budget,
            },
            ceilings={
                "files_in_baseline": 0,
                "files_over_budget": 0,
            },
            findings=[
                {"file": v.split(":", 1)[0], "line": 0, "detail": v}
                for v in violations
            ],
        )

    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
