"""Cyclomatic complexity (CC) ratchet for high-risk functions.

AGENTS.md rule 21 + issues #336 and #332: ``create_app`` and
``apply_web_to_legacy`` must stay at CC <= 15.
The ratchet is shrink-only: the budget may only decrease, never increase.

The check uses ``radon cc -a`` on each target file and extracts the CC of
the named function.

Usage::

    python scripts/check_complexity.py [root]

``root`` defaults to the repository root (the parent of ``scripts/``).
Exit code 0 when clean, 1 on any violation. Stdlib-only, deterministic.

Run locally before pushing; CI should run it in the ``lint`` job.

Issues: #336 (create_app), #332 (apply_web_to_legacy)
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

#: Hard CC budget per function.
MAX_CC = 15

#: (file_path_relative_to_root, function_simple_name) -> baseline CC.
#: RATCHET: may only decrease; no entry may be added.
BASELINE_CC: dict[tuple[str, str], int] = {
    ("app/main.py", "create_app"): 1,  # issue #336 refactor — extracted closures
    (
        "migration/reverse_apply/orchestrator.py",
        "apply_web_to_legacy",
    ): 3,  # issue #332 refactor — extracted helpers; CC=C (3)
}


def extract_function_cc(output: str, func_simple_name: str) -> int | None:
    """Parse ``radon cc -a`` output for a specific function.

    radon -a output format per function (one per line):
      F <line>:<col> <module>/<path>.<func> - <grade>

    e.g. "F 140:0 create_app - A"
    e.g. with closures: "F 212:4 _register_index_handler.index - A"

    The CC is encoded in the grade: A=1, B=2, C=3, D=4, E=5, F=6+
    """
    # Direct match: F <line>:<col> <func_name> - <grade>
    pattern = rf"F\s+\d+:\d+\s+{re.escape(func_simple_name)}\s+-\s+([A-F])(\d+)?"
    m = re.search(pattern, output, re.MULTILINE)
    if m:
        grade = m.group(1)
        explicit = m.group(2)
        if explicit:
            return int(explicit)
        grade_map = {"A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "F": 6}
        return grade_map.get(grade, 6)
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
        result = subprocess.run(
            [sys.executable, "-m", "radon", "cc", "-a", "--show-closures", str(target)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return [f"radon cc timed out on {target}"], []
    except FileNotFoundError:
        return ["radon not installed: pip install radon"], []

    violations: list[str] = []
    notices: list[str] = []

    key = (file_rel, func_name)
    cc = extract_function_cc(output, func_name)

    if cc is None:
        violations.append(
            f"{file_rel}::{func_name}: could not find {func_name} in radon output"
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


def main(argv: list[str] | None = None) -> int:
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
