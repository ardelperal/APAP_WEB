"""Branch-name gate for the <type>/<issue>-<slug> convention (AGENTS.md §15.2, #441).

A frozen ALLOWLIST covers branches that pre-date the rename. New branches
MUST match the pattern or start with archive/.
"""
from __future__ import annotations

import re
import sys

ALLOWLIST: frozenset[str] = frozenset({
    # Grandfathered branches that pre-date the rename convention.
    "feat/quality-gates-mutation",
    "feat/architecture-layers-gate",
    # Add more here as the user renames legacy branches.
})

_PATTERN = re.compile(
    r"^(?:(chore|feat|fix|perf|refactor|docs|ci|test)/[0-9]+-[a-z0-9-]+|archive/.+|main)$"
)


def check(head_ref: str) -> tuple[list[str], list[str]]:
    """Return (violations, notices) for the given head ref name."""
    if head_ref in ALLOWLIST:
        return [], [f"{head_ref}: grandfathered via ALLOWLIST"]
    if _PATTERN.match(head_ref):
        return [], []
    example = "feat/441-branch-name-gate"
    return [
        f"{head_ref}: branch name must match the pattern (AGENTS.md §15.2, #441). "
        f"Expected shape: <type>/<issue>-<slug> where <type> ∈ {{chore|feat|fix|perf|refactor|docs|ci|test}}. "
        f"Example: {example}"
    ], []


def _pin_output_encoding() -> None:
    """Pin stdout/stderr to UTF-8: output must not depend on the locale (issue #488)."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    _pin_output_encoding()
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: check_branch_name.py <head-ref>")
        return 2
    violations, notices = check(args[0])
    for n in notices:
        print(f"NOTE {n}")
    for v in violations:
        print(f"FAIL {v}")
    if violations:
        return 1
    print(f"check_branch_name: OK ({args[0]} matches the pattern)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
