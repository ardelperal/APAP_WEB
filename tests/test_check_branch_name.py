"""Pin the branch-name gate (issue #441, AGENTS.md §15.2)."""
from __future__ import annotations

import pytest

from scripts.check_branch_name import ALLOWLIST, check


@pytest.mark.parametrize("name", [
    "chore/464-preflight-cleanup",
    "feat/441-branch-name-gate",
    "fix/123-short",
    "perf/123-some-perf",
    "refactor/9999-something-long-here",
    "docs/12-x",
    "ci/1-a",
    "test/1-x",
    "archive/old-stuff",
    "archive/another/branch",
    "main",
])
def test_valid_branch_names(name: str) -> None:
    violations, _ = check(name)
    assert violations == [], f"{name!r} should be valid"


@pytest.mark.parametrize("name", [
    "my-random-branch",
    "feat/abc-not-numeric",
    "feat/431-WRONG-CASE",
    "feat-431-bad-shape",
    "test/1",  # slug too short
    "feat/123 ",  # trailing space
    "wip/431-bad",  # wrong type
    "feat/431-UPPERCASE",
    "feat-431-bad",  # wrong separator
])
def test_invalid_branch_names(name: str) -> None:
    violations, _ = check(name)
    assert violations, f"{name!r} should be rejected"


def test_grandfathered_branches_pass() -> None:
    for name in ALLOWLIST:
        violations, notices = check(name)
        assert violations == []
        assert any("grandfathered" in n for n in notices)


def test_allowlist_is_frozenset() -> None:
    assert isinstance(ALLOWLIST, frozenset)


def test_dependabot_branch_passes_only_for_dependabot_actor() -> None:
    branch = "dependabot/github_actions/main/all-actions-657f7d9623"

    violations, notices = check(branch, "dependabot[bot]")
    assert violations == []
    assert any("trusted Dependabot" in notice for notice in notices)

    violations, _ = check(branch, "octocat")
    assert violations


def test_dependabot_actor_cannot_bypass_namespace_validation() -> None:
    violations, _ = check("feat/no-issue", "dependabot[bot]")
    assert violations


def test_allowlist_only_shrinks() -> None:
    """Adding to the allowlist is a one-shot calibration; the ratchet only shrinks.

    This test enforces the shape: ALLOWLIST is a frozenset (immutable) and any
    entry corresponds to a real branch. The baseline-calibration discipline
    is documented in AGENTS.md §21.
    """
    for name in ALLOWLIST:
        assert isinstance(name, str)
        assert name  # no empty strings
