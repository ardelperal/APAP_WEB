"""PR size gate enforcing AGENTS.md §15.1 (review_budget_lines: 400).

Issue #1121: the override lives in the PR body as ``size-exception-reason:
<motivo>`` — a deterministic, single-line, non-empty field. The
``size:exception`` label is informational only; the gate parses the body,
not the labels (epic #935 rule: gates read structured data, not gestures).

The budget counts additions + deletions from ``git diff --shortstat`` against
the merge-base. The workflow excludes deterministic lockfiles while retaining
their source manifests in the budget.

Usage::

    python scripts/check_pr_size.py <total-changed-lines> <pr-body>

Exit codes:
    0 — within budget, or ``size-exception-reason:`` line overrides the budget
    1 — over budget without a valid ``size-exception-reason:`` line
    2 — usage error (wrong argument count or non-integer total)

Tests: ``tests/test_pr_size.py``. CI wiring: ``.github/workflows/pr-size.yml``.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, cast

BUDGET = 400
EXPECTED_ARG_COUNT = 2
EXIT_OK = 0
EXIT_OVER_BUDGET = 1
EXIT_USAGE_ERROR = 2

EXCEPTION_REASON_PREFIX = "size-exception-reason:"


if TYPE_CHECKING:  # pragma: no cover - typing aid only
    from typing import Protocol

    class _ReconfigurableTextIO(Protocol):
        # ``typing.TextIO`` does not declare ``reconfigure`` even though it
        # exists at runtime on Python 3.7+. The Protocol narrows the type
        # for the cast in ``_pin_output_encoding``; the ``hasattr`` guard
        # there is the actual runtime gate.
        def reconfigure(self, *, encoding: str) -> object: ...


def _pin_output_encoding() -> None:
    """Pin stdout/stderr to UTF-8: output must not depend on the locale (issue #488)."""
    if hasattr(sys.stdout, "reconfigure"):
        cast("_ReconfigurableTextIO", sys.stdout).reconfigure(encoding="utf-8")
        cast("_ReconfigurableTextIO", sys.stderr).reconfigure(encoding="utf-8")


def _extract_exception_reason(body: str | None) -> str | None:
    """Return the override reason from the PR body, or ``None`` when absent.

    A valid reason is a single line ``size-exception-reason: <text>``
    where ``<text>`` is non-empty after stripping. Rules:

    1. Exactly one line starts with the prefix. Two or more occurrences
       (even if one is empty) are ambiguous and rejected (multiline).
    2. Empty / whitespace-only value → absent.
    3. The line right after the reason must be blank (or end of body).
       Prose on the next line is a wrap attempt — rejected as multiline.
    """
    if not body:
        return None
    lines = body.splitlines()
    # ``candidate`` stays None until we see exactly one occurrence with a
    # non-empty value. An empty occurrence or a second occurrence clears
    # it back to None; the tuple keeps the index and value linked so the
    # wrap guard below does not need a separate narrowing trick.
    candidate: tuple[int, str] | None = None
    occurrence_count = 0
    for index, line in enumerate(lines):
        if not line.startswith(EXCEPTION_REASON_PREFIX):
            continue
        occurrence_count += 1
        if occurrence_count > 1:
            return None
        value = line[len(EXCEPTION_REASON_PREFIX) :].strip()
        if value:
            candidate = (index, value)
        # Empty-value occurrence still counts as the unique one — we
        # just don't update ``candidate`` because the parser treats it
        # as absent. A second occurrence short-circuits to None above.
    if candidate is None:
        return None
    candidate_index, candidate_value = candidate
    # Multiline wrap guard: the line right after the reason must be blank
    # or absent. Anything else means the reason spilled over.
    next_line = lines[candidate_index + 1] if candidate_index + 1 < len(lines) else ""
    if next_line.strip():
        return None
    return candidate_value


def main(argv: list[str] | None = None) -> int:
    _pin_output_encoding()
    args = sys.argv[1:] if argv is None else argv
    if len(args) != EXPECTED_ARG_COUNT:
        print(
            "usage: check_pr_size.py <total-changed-lines> <pr-body> "
            "(PR body is parsed for `size-exception-reason: <motivo>`)"
        )
        return EXIT_USAGE_ERROR
    try:
        total = int(args[0])
    except ValueError:
        print(f"FAIL: total-changed-lines must be an integer, got {args[0]!r}")
        return EXIT_USAGE_ERROR
    reason = _extract_exception_reason(args[1])
    if reason:
        print(
            f"check_pr_size: OK (total={total}, "
            f"size-exception-reason present — override applied: {reason})"
        )
        return EXIT_OK
    if total > BUDGET:
        print(
            f"FAIL check_pr_size: PR changes {total} lines (budget {BUDGET}). "
            "Add `size-exception-reason: <motivo>` to the PR body to override, "
            "or slice the PR (AGENTS.md §15.1)."
        )
        return EXIT_OVER_BUDGET
    print(f"check_pr_size: OK ({total} <= {BUDGET})")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
