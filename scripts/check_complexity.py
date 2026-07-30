"""Cyclomatic complexity (CC) ratchet for ``app/main.py::create_app``.

AGENTS.md rule 21 + issue #336: ``create_app`` must stay at CC <= 15.
The ratchet is shrink-only: the budget may only decrease, never increase.

The check uses ``radon cc -a`` (aggregate complexity) on ``app/main.py``
and extracts the CC of the ``create_app`` function specifically.

Usage::

    python scripts/check_complexity.py [root]

``root`` defaults to the repository root (the parent of ``scripts/``).
Exit code 0 when clean, 1 on any violation. Stdlib-only, deterministic.

Run locally before pushing; CI should run it in the ``lint`` job.

Issue: #336
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

#: Hard CC budget for create_app.
MAX_CC = 15

#: Baselined CC for create_app at the time of the refactor (issue #336).
#: RATCHET: may only decrease.
BASELINE_CC: dict[str, int] = {
    "app/main.py::create_app": 1,  # issue #336 refactor — extracted closures
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


def check_complexity(root: Path) -> tuple[list[str], list[str]]:
    """Check CC of create_app against the budget.

    Returns (violations, notices).
    """
    target = root / "app" / "main.py"
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

    func_name = "app.main.py::create_app"
    cc = extract_function_cc(output, "create_app")

    if cc is None:
        # Function may have been removed or renamed — flag it
        violations.append(f"{func_name}: could not find create_app in radon output")
        return violations, notices

    baseline = BASELINE_CC.get("app/main.py::create_app", None)
    if baseline is not None and cc > baseline:
        violations.append(
            f"{func_name}: CC={cc}, exceeds baseline of {baseline} "
            f"(ratchet: CC may only decrease — split create_app further)"
        )
    elif cc > MAX_CC:
        violations.append(
            f"{func_name}: CC={cc}, exceeds hard budget of {MAX_CC} "
            f"(AGENTS.md rule 21 + issue #336)"
        )
    elif baseline is not None and cc < baseline:
        notices.append(
            f"{func_name}: CC={cc}, below baseline of {baseline} — "
            f"update BASELINE_CC in scripts/check_complexity.py to lock in the improvement"
        )
    else:
        notices.append(f"{func_name}: CC={cc} — within budget")

    return violations, notices


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
            f"create_app CC budget: {MAX_CC} (AGENTS.md rule 21 + issue #336)."
        )
        return 1
    print("check_complexity: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
