"""Pin the PR size gate (issue #442, AGENTS.md §15.1)."""
from __future__ import annotations

from scripts.check_pr_size import main


def run_main(*args: str) -> int:
    return main(list(args))


def test_within_budget() -> None:
    assert run_main("100", "false") == 0


def test_at_boundary() -> None:
    assert run_main("400", "false") == 0


def test_over_budget() -> None:
    assert run_main("401", "false") == 1


def test_over_budget_with_exception_label() -> None:
    assert run_main("1000", "true") == 0


def test_negative_total() -> None:
    assert run_main("-5", "false") == 0


def test_invalid_total() -> None:
    assert run_main("not-a-number", "false") == 2


def test_wrong_arg_count() -> None:
    assert run_main() == 2
    assert run_main("100") == 2
    assert run_main("100", "false", "extra") == 2
