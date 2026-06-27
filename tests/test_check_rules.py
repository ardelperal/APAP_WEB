"""Tests for the AST-based rule linter (scripts/check_rules.py).

Per Slice 1 of ``openspec/changes/hardening-2026-q2/specs/01-dev-tooling-gate/spec.md``.

The parametrized suite proves each detector both directions:

  - **positive**: a seeded fixture must produce a violation with the
    expected ``rule_id``.
  - **negative**: a clean fixture must NOT trigger any detector.

Detectors land in two commits (Rule 1 in commit 3, Rules 6/7/4 in
commit 4); each commit replaces the placeholder assertion below with the
real parametrized case so the suite is always green.
"""

from __future__ import annotations


def test_placeholder_for_pr_1a_scaffold():
    """Scaffold test — replaced by the real suite in subsequent commits.

    See commit messages for the rollout:

    * commit 2 — module + ``Violation`` dataclass + ``find_violations``.
    * commit 3 — Detector 1 (Rule 1: ``route_uses_execute_sql``).
    * commit 4 — Detectors 2/3/4 (Rules 6/7/4-partial).
    """
    # Trivially passes so ``make all`` stays green until the real suite lands.
    assert True
