"""PR size gate enforcing AGENTS.md §15.1 (review_budget_lines: 400).

A ``size:exception`` label on the PR overrides the budget (§15.6) — explicit,
visible, intentional. Without the label, the budget is enforced.

The budget counts additions + deletions from ``git diff --shortstat`` against
the merge-base. Lockfiles and generated assets are NOT currently exempted —
add an exemption here if a real lockfile-creating change trips it.

Usage::

    python scripts/check_pr_size.py <total-changed-lines> <has-exception-label>

Exit codes:
    0 — within budget, or ``size:exception`` label overrides the budget
    1 — over budget without an exception label
    2 — usage error (wrong argument count or non-integer total)

Tests: ``tests/test_pr_size.py``. CI wiring: ``.github/workflows/pr-size.yml``.
Pinned by ``tests/test_ci_workflow.py::test_ci_workflow_pr_size_job_is_wired``.
"""
from __future__ import annotations

import sys

BUDGET = 400
EXPECTED_ARG_COUNT = 2
EXIT_OK = 0
EXIT_OVER_BUDGET = 1
EXIT_USAGE_ERROR = 2
TRUTHY = frozenset({"true", "1", "yes"})


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != EXPECTED_ARG_COUNT:
        print("usage: check_pr_size.py <total-changed-lines> <has-exception-label>")
        return EXIT_USAGE_ERROR
    try:
        total = int(args[0])
    except ValueError:
        print(f"FAIL: total-changed-lines must be an integer, got {args[0]!r}")
        return EXIT_USAGE_ERROR
    has_exception = args[1].lower() in TRUTHY
    if has_exception:
        print(
            f"check_pr_size: OK (total={total}, "
            "size:exception label present — override applied)"
        )
        return EXIT_OK
    if total > BUDGET:
        print(
            f"FAIL check_pr_size: PR changes {total} lines (budget {BUDGET}). "
            "Apply the size:exception label to override, or slice the PR "
            "(AGENTS.md §15.1)."
        )
        return EXIT_OVER_BUDGET
    print(f"check_pr_size: OK ({total} <= {BUDGET})")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
