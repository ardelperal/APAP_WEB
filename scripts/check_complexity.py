"""Cyclomatic complexity (CC) ceiling for every function in the codebase.

Every function under ``SCAN_DIRS`` is measured against the same absolute ceiling. The ceiling is
absolute rather than a top-N ranking: under top-N the verdict on one function depends on the
complexity of unrelated functions, so identical code passes or fails depending on its neighbours.

``BASELINE_CC`` is a shrink-only ratchet of tolerated offenders: entries may only decrease, a
function that grows past its entry fails, and a function with no entry must be under ``MAX_CC``.

Methods and closures are measured as their own entries, and their decision points are excluded
from the enclosing function — folding them in would make a parent depend on its children and
would count the same branch twice.

Until 2026-08-08 this gate iterated ``BASELINE_CC`` and so measured 2 of 901 functions; see
issue #486 for the evidence and the nine offenders that scoping it correctly surfaced.

Usage::

    python scripts/check_complexity.py [root]
    python scripts/check_complexity.py [root] --emit-baseline

``root`` defaults to the repository root (the parent of ``scripts/``).
Exit code 0 when clean, 1 on any violation. Stdlib-only, deterministic.

Issues: #336 (create_app), #332 (apply_web_to_legacy)
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

# _ratchet_deadline lives next to this script.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _ratchet_deadline import check_deadline  # noqa: E402 - sys.path tweak above

#: Hard CC budget per function. Absolute and global — never a top-N selection.
MAX_CC = 15

#: Directories walked by the gate. Mirrors ``scripts/check_mutation_sites.py``.
SCAN_DIRS = ("app", "migration")

#: Directory names skipped anywhere in a path.
EXCLUDED_PARTS = frozenset({"__pycache__", ".venv", "venv", "build", "dist", "node_modules"})

#: (file_path_relative_to_root, qualified_function_name) -> baseline CC.
#: RATCHET: entries may only decrease or disappear; never add headroom.
#: Generate additions with ``--emit-baseline`` rather than by hand.
#:
#: The nine entries below `create_app` are pre-existing debt surfaced the first time this gate
#: measured the whole codebase (2026-08-08). They are recorded, not accepted: the ratchet means
#: no NEW function may exceed the budget and none of these may grow. `derive_estado_actual_animal`
#: at CC=31 and `_diff_snapshots` at CC=29 are the two worth attacking first.
BASELINE_CC: dict[tuple[str, str], int] = {
    ("app/main.py", "create_app"): 1,  # issue #336 refactor — extracted closures
    ("app/modules/animals/routes.py", "_animal_to_form_data"): 25,
    ("app/modules/entradas/batch_routes.py", "stage_batch_view"): 17,
    ("migration/apply.py", "apply_legacy_to_web"): 20,
    ("migration/cli_apply_reverse.py", "run_apply"): 21,
    ("migration/derivation.py", "derive_estado_actual_animal"): 31,
    ("migration/diff_engine.py", "_diff_snapshots"): 29,
    ("migration/reconcile.py", "_build_derived_inputs"): 16,
    ("migration/reconcile.py", "post_apply_diff"): 18,
    ("migration/reporting.py", "MigrationReport.to_markdown"): 20,
    (
        "migration/reverse_apply/orchestrator.py",
        "apply_web_to_legacy",
    ): 13,  # issue #332 refactor — extracted helpers (was CC=57)
}

#: Ratchet deadline (deterministic-quality-harness v1.5 Rule 12). Every
#: baselined function's goal is to shrink below MAX_CC (target=0 entries).
#: The deadline is set to the project-wide pre-MVP finale; revisit and tighten
#: per-entry once the ratchet is retired.
TARGET: tuple[int, str] = (0, "2026-12-31")

_FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)


def _count_decision_points(node: ast.AST) -> int:
    """Return the number of decision points owned by ``node``.

    CC starts at 1 and we add 1 for each:
      - if/elif (each branch)
      - for/while/async for
      - except handler
      - and/or (BoolOp with >1 values adds len(values)-1)
      - ternary (IfExp)
      - comprehension (List/Dict/Set/Generator)
      - assert

    Skipping walrus (NamedExpr) on purpose: it doesn't branch. Nested functions and classes are
    skipped too — they are measured as their own entries.
    """
    count = 0
    stack: list[ast.AST] = list(ast.iter_child_nodes(node))
    while stack:
        child = stack.pop()
        if isinstance(child, (*_FUNCTION_NODES, ast.ClassDef)):
            continue
        if isinstance(child, (ast.If, ast.IfExp)):
            count += 1
        elif isinstance(child, (ast.For, ast.AsyncFor, ast.While)):
            count += 1
        elif isinstance(child, ast.ExceptHandler):
            count += 1
        elif isinstance(child, ast.BoolOp):
            # `a and b and c` has 2 decision points (b, c); `a and b` has 1.
            count += max(0, len(child.values) - 1)
        elif isinstance(child, (ast.ListComp, ast.DictComp, ast.SetComp, ast.GeneratorExp)):
            count += 1
        elif isinstance(child, ast.Assert):
            count += 1
        stack.extend(ast.iter_child_nodes(child))
    return count


def _walk_functions(node: ast.AST, prefix: str = ""):
    """Yield ``(qualified_name, node)`` for every function, including methods and closures."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, _FUNCTION_NODES):
            qualified = f"{prefix}{child.name}"
            yield qualified, child
            yield from _walk_functions(child, prefix=f"{qualified}.")
        elif isinstance(child, ast.ClassDef):
            yield from _walk_functions(child, prefix=f"{prefix}{child.name}.")
        else:
            yield from _walk_functions(child, prefix=prefix)


def iter_source_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for scan_dir in SCAN_DIRS:
        base = root / scan_dir
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if EXCLUDED_PARTS.intersection(path.parts):
                continue
            files.append(path)
    return files


def measure(root: Path) -> tuple[dict[tuple[str, str], int], list[str]]:
    """Measure every function. Returns ``({(file_rel, qualified): cc}, errors)``.

    A file that cannot be read or parsed is an error, never a silent skip: a gate that quietly
    drops what it cannot inspect reports the codebase as clean for the part nobody looked at.
    """
    measured: dict[tuple[str, str], int] = {}
    errors: list[str] = []
    for path in iter_source_files(root):
        file_rel = str(path.relative_to(root)).replace("\\", "/")
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(f"{file_rel}: cannot read ({exc})")
            continue
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            errors.append(f"{file_rel}: syntax error ({exc})")
            continue
        for qualified, node in _walk_functions(tree):
            measured[(file_rel, qualified)] = 1 + _count_decision_points(node)
    return measured, errors


def check_complexity(root: Path) -> tuple[list[str], list[str]]:
    """Check CC of every measured function against the budget.

    Returns (violations, notices).
    """
    measured, errors = measure(root)
    violations: list[str] = list(errors)
    notices: list[str] = []

    for key in sorted(measured):
        file_rel, func_name = key
        cc = measured[key]
        baseline = BASELINE_CC.get(key)
        full_name = f"{file_rel}::{func_name}"
        if baseline is not None and cc > baseline:
            violations.append(
                f"{full_name}: CC={cc}, exceeds baseline of {baseline} "
                f"(ratchet: CC may only decrease)"
            )
        elif baseline is None and cc > MAX_CC:
            violations.append(
                f"{full_name}: CC={cc}, exceeds hard budget of {MAX_CC} (AGENTS.md rule 21)"
            )
        elif baseline is not None and cc < baseline:
            notices.append(
                f"{full_name}: CC={cc}, below baseline of {baseline} — "
                f"update BASELINE_CC to lock in the improvement"
            )

    for key in sorted(BASELINE_CC):
        if key not in measured:
            violations.append(
                f"{key[0]}::{key[1]}: in BASELINE_CC but no such function was found — "
                f"remove the entry or fix the path"
            )

    return violations, notices


def render_baseline(root: Path) -> str:
    """Emit a BASELINE_CC block for the current offenders.

    A ratchet with dozens of entries never gets adopted if it has to be typed by hand.
    """
    measured, _ = measure(root)
    lines = ["BASELINE_CC: dict[tuple[str, str], int] = {"]
    for key in sorted(measured):
        cc = measured[key]
        if cc > MAX_CC or key in BASELINE_CC:
            lines.append(f'    ("{key[0]}", "{key[1]}"): {cc},')
    lines.append("}")
    return "\n".join(lines)


def _pin_output_encoding() -> None:
    """Pin stdout/stderr to UTF-8: output must not depend on the locale (issue #488)."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    _pin_output_encoding()
    args = list(sys.argv[1:] if argv is None else argv)
    emit_baseline = "--emit-baseline" in args
    if emit_baseline:
        args.remove("--emit-baseline")
    root = Path(args[0]).resolve() if args else Path(__file__).resolve().parents[1]

    if emit_baseline:
        print(render_baseline(root))
        return 0

    violations, notices = check_complexity(root)

    for notice in notices:
        print(f"NOTE {notice}")
    for violation in violations:
        print(f"FAIL {violation}")

    if violations:
        print(
            f"check_complexity: {len(violations)} violation(s). "
            f"CC budget: {MAX_CC} (AGENTS.md rule 21)."
        )
        return 1
    measured, _ = measure(root)
    print(f"check_complexity: OK ({len(measured)} function(s) measured, budget CC<={MAX_CC})")
    warning = check_deadline(TARGET, len(BASELINE_CC), label="complexity")
    if warning:
        print(f"DEADLINE {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
