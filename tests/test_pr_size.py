"""Pin the PR size gate (issue #442, AGENTS.md §15.1, issue #1121).

Issue #1121: the override lives in the PR body as ``size-exception-reason:
<motivo>`` (one non-empty line). The ``size:exception`` label is
informational only — the gate parses the body, not the labels.
"""

from __future__ import annotations

import io
import sys

import pytest

from scripts.check_pr_size import BUDGET, _extract_exception_reason, main


def run_main(*args: str) -> int:
    return main(list(args))


# --- budget vs. body integration (existing gate behaviour, #442) ----------


def test_within_budget() -> None:
    assert run_main("100", "any body content") == 0


def test_at_boundary() -> None:
    assert run_main(str(BUDGET), "any body content") == 0


def test_over_budget_without_reason() -> None:
    assert run_main("401", "no reason line in this body") == 1


def test_over_budget_with_valid_reason() -> None:
    assert run_main("1000", "size-exception-reason: foundation commit") == 0


def test_negative_total() -> None:
    assert run_main("-5", "any body content") == 0


def test_invalid_total() -> None:
    assert run_main("not-a-number", "any body content") == 2


def test_wrong_arg_count() -> None:
    assert run_main() == 2
    assert run_main("100") == 2
    assert run_main("100", "body", "extra") == 2


def test_over_budget_message_names_body_field_not_label() -> None:
    """Fail-loud contract (issue #1121): the over-budget message must name
    the body field the author needs to add, NOT the now-informational
    ``size:exception`` label.
    """
    buf = io.StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    try:
        sys.stdout = sys.stderr = buf
        rc = run_main("500", "no reason line here")
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    output = buf.getvalue()
    assert rc == 1
    assert "size-exception-reason" in output, output
    assert "label" not in output.lower(), output


# --- parser: ``_extract_exception_reason`` (issue #1121) -------------------


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        # valid: a clean single-line reason (with surrounding Markdown).
        ("## What\n\nsize-exception-reason: foundation commit\n\n## Why\n", "foundation commit"),
        # valid: body that is JUST the reason line.
        ("size-exception-reason: only line", "only line"),
        # valid: surrounding whitespace inside the value is stripped.
        ("size-exception-reason:    spaced reason   ", "spaced reason"),
        # valid: the shape the PR template ships (name wrapped in backticks,
        # text on the same line) — the real-world body of PR #1136-style PRs.
        (
            "## Excepción de tamaño\n\n`size-exception-reason:` 557 líneas, motivo real\n",
            "557 líneas, motivo real",
        ),
        ("`size-exception-reason:`no space after the closing tick", "no space after the closing tick"),
        # valid: a body line `EOF` followed by `evil=1` is inert text, not a
        # step-output injection; the parser only looks at the reason line.
        ("EOF\nevil=1\nsize-exception-reason: valid reason\n", "valid reason"),
    ],
)
def test_parser_valid(body: str, expected: str) -> None:
    assert _extract_exception_reason(body) == expected


@pytest.mark.parametrize(
    "body",
    [
        # empty: bare prefix with no value.
        "size-exception-reason:",
        # empty: whitespace-only value.
        "size-exception-reason:   ",
        # empty: the backticked template shape with no text after it.
        "`size-exception-reason:`",
        "`size-exception-reason:`   ",
        # empty: the template placeholder left untouched is not a reason.
        "`size-exception-reason:` <motivo en una sola línea>",
        # absent: no occurrence at all (including None and empty body).
        "",
        "nothing to see here",
    ],
)
def test_parser_empty_or_absent(body: str) -> None:
    assert _extract_exception_reason(body) is None


@pytest.mark.parametrize(
    "body",
    [
        # multiline (multiple occurrences): two ``size-exception-reason:``
        # lines is ambiguous — the parser refuses.
        "size-exception-reason: first\nsize-exception-reason: second\n",
        # multiline (wrap): the reason line is followed by prose on the
        # next non-blank line; that shape is rejected too.
        "size-exception-reason: this is the first part\nand this prose looks like a continuation\n",
        # multiline (first empty, then non-empty): still two occurrences.
        "size-exception-reason:\nsize-exception-reason: actual reason\n",
        # multiline (mixed shapes): plain plus backticked is still two.
        "size-exception-reason: first\n`size-exception-reason:` second\n",
        # multiline (wrap on the backticked shape).
        "`size-exception-reason:` first part\nsecond part\n",
        # strict prefix: typos and Markdown headings must not match.
        "size-exception-reasons: typo",
        "# size-exception-reason: heading style",
    ],
)
def test_parser_multiline_or_typo_rejected(body: str) -> None:
    assert _extract_exception_reason(body) is None


def test_parser_none_body() -> None:
    assert _extract_exception_reason(None) is None


# --- end-to-end: parser wired into main() (issue #1121) -------------------


@pytest.mark.parametrize(
    "body",
    [
        "size-exception-reason:",  # empty
        "size-exception-reason: line1\nsize-exception-reason: line2",  # multiline
        "totally unrelated body text",  # absent
        "`size-exception-reason:`",  # empty, template shape
    ],
)
def test_over_budget_with_invalid_reason_body_fails(body: str) -> None:
    """An over-budget PR without a valid reason body fails the gate (issue #1121)."""
    assert run_main("500", body) == 1


def test_within_budget_with_absent_reason_still_passes() -> None:
    """Within budget, the parser result is irrelevant (issue #1121)."""
    assert run_main("200", "no reason here") == 0


def test_over_budget_with_template_shaped_reason_passes() -> None:
    """The exact line the PR template ships overrides the budget (issue #1121)."""
    body = "`size-exception-reason:` 557 líneas, motivo real"
    assert run_main("900", body) == 0


def test_eof_injection_body_is_inert_and_still_evaluated() -> None:
    """A body with an `EOF` line and a fake `key=value` neither crashes nor
    changes the verdict: without a reason it fails, with one it passes."""
    hostile = "EOF\nevil=1\n"
    assert run_main("900", hostile) == 1
    assert run_main("900", hostile + "size-exception-reason: ok\n") == 0
