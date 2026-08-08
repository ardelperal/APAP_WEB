"""Cyclomatic complexity (CC) ratchet for high-risk functions.

AGENTS.md rule 21 + issues #336 and #332: ``create_app`` and
``apply_web_to_legacy`` must stay at CC <= 15.
The ratchet is shrink-only: the budget may only decrease, never increase.

CC is computed via a stdlib-only AST walker (no external dependency on
radon). The walker counts decision points: if/elif/while/for/except/and/or/
ternary/comprehension/assert.

Usage::

    python scripts/check_complexity.py [root]

``root`` defaults to the repository root (the parent of ``scripts/``).
Exit code 0 when clean, 1 on any violation. Stdlib-only, deterministic.

Run locally before pushing; CI should run it in the ``lint`` job.

Issues: #336 (create_app), #332 (apply_web_to_legacy)
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

#: Hard CC budget per function.
MAX_CC = 15

#: (file_path_relative_to_root, function_simple_name) -> baseline CC.
#: RATCHET: may only decrease; no entry may be added.
#: Values are the measured CC AFTER the refactor (issue #336 for create_app,
#: issue #332 for apply_web_to_legacy). radon's explicit `-s` score for the
#: post-refactor apply_web_to_legacy is 14 (was 57 pre-refactor); the AST
#: walker reports 13 — the ratchet compares AST counts so the value is the
#: AST measurement.
BASELINE_CC: dict[tuple[str, str], int] = {
    ("app/main.py", "create_app"): 1,  # issue #336 refactor — extracted closures
    (
        "migration/reverse_apply/orchestrator.py",
        "apply_web_to_legacy",
    ): 13,  # issue #332 refactor — extracted helpers (was CC=57)
}


def _count_decision_points(node: ast.AST) -> int:
    """Return the number of decision points under ``node``.

    CC starts at 1 and we add 1 for each:
      - if/elif (each branch)
      - for/while/async for
      - except handler
      - and/or (BoolOp with >1 values adds len(values)-1)
      - ternary (IfExp)
      - comprehension (List/Dict/Set/Generator)
      - assert

    Skipping walrus (NamedExpr) on purpose: it doesn't branch.
    """
    count = 0
    for child in ast.walk(node):
        if isinstance(child, (ast.If, ast.IfExp)):
            count += 1
        elif isinstance(child, (ast.For, ast.AsyncFor, ast.While)):
            count += 1
        elif isinstance(child, ast.ExceptHandler):
            count += 1
        elif isinstance(child, ast.BoolOp):
            # `a and b and c` has 2 decision points (b, c); single operand
            # like `a and b` has 1.
            count += max(0, len(child.values) - 1)
        elif isinstance(child, (ast.ListComp, ast.DictComp, ast.SetComp, ast.GeneratorExp)):
            count += 1
        elif isinstance(child, ast.Assert):
            count += 1
    return count


def _function_cc(tree: ast.AST, func_name: str) -> int | None:
    """Find the top-level function ``func_name`` in ``tree`` and return its CC.

    Only top-level (module-level) functions are considered. Returns ``None``
    if the function is not defined at the top level.
    """
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            return 1 + _count_decision_points(node)
    return None


def check_one_function(
    root: Path,
    file_rel: str,
    func_name: str,
) -> tuple[list[str], list[str]]:
    """Check CC of one function against the budget.

    Returns (violations, notices).
    """
    target = root / file_rel
    if not target.exists():
        return [f"{target}: file not found"], []

    try:
        source = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [f"{file_rel}: cannot read ({exc})"], []

    try:
        tree = ast.parse(source, filename=str(target))
    except SyntaxError as exc:
        return [f"{file_rel}: syntax error ({exc})"], []

    key = (file_rel, func_name)
    cc = _function_cc(tree, func_name)

    violations: list[str] = []
    notices: list[str] = []

    if cc is None:
        violations.append(
            f"{file_rel}::{func_name}: could not find top-level function"
        )
        return violations, notices

    baseline = BASELINE_CC.get(key, None)
    full_name = f"{file_rel}::{func_name}"
    if baseline is not None and cc > baseline:
        violations.append(
            f"{full_name}: CC={cc}, exceeds baseline of {baseline} "
            f"(ratchet: CC may only decrease)"
        )
    elif cc > MAX_CC:
        violations.append(
            f"{full_name}: CC={cc}, exceeds hard budget of {MAX_CC} "
            f"(AGENTS.md rule 21 + issues #336, #332)"
        )
    elif baseline is not None and cc < baseline:
        notices.append(
            f"{full_name}: CC={cc}, below baseline of {baseline} — "
            f"update BASELINE_CC to lock in the improvement"
        )
    else:
        notices.append(f"{full_name}: CC={cc} — within budget")

    return violations, notices


def check_complexity(root: Path) -> tuple[list[str], list[str]]:
    """Check CC of all tracked functions against the budget.

    Returns (violations, notices).
    """
    all_violations: list[str] = []
    all_notices: list[str] = []

    for (file_rel, func_name) in BASELINE_CC:
        viol, notices = check_one_function(root, file_rel, func_name)
        all_violations.extend(viol)
        all_notices.extend(notices)

    return all_violations, all_notices


def _pin_output_encoding() -> None:
    """Pin stdout/stderr to UTF-8: output must not depend on the locale (issue #488)."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    _pin_output_encoding()
    args = sys.argv[1:] if argv is None else argv
    root = Path(args[0]).resolve() if args else Path(__file__).resolve().parents[1]

    violations, notices = check_complexity(root)

    for notice in notices:
        print(f"NOTE {notice}")
    for violation in violations:
        print(f"FAIL {violation}")

    if violations:
        print(
            f"check_complexity: {len(violations)} violation(s). "
            f"CC budget: {MAX_CC} (AGENTS.md rule 21 + issues #336, #332)."
        )
        return 1
    print("check_complexity: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
