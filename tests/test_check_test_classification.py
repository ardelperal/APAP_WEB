"""Tests for the test-classification ratchet (AGENTS.md §apap-testing-strategy).

``scripts/check_test_classification.py`` enforces that every domain in
``IN_SCOPE_DOMAINS`` has a matching integration atom under
``tests/integration/`` when the flow involves behaviour that
``httpx.MockTransport`` cannot verify (FK enforcement, triggers, CTE
rollback, ON CONFLICT, soft-delete cascade).

The ratchet is shrink-only: BASELINE entries may only be removed when
the matching integration file lands. Adding a unit test for an in-scope
domain without the matching integration test is a regression and fails
the gate.

Per ``docs/quality/test-audit.md`` (2026-08-31), the audit listed five
P0 gaps: ``cesiones``, ``entradas``, ``auth``, ``chip_cascade``, and
``animal_lifecycle_events``. After issues #632 and #633, the
``entradas`` and ``cesiones`` gaps are closed (integration atoms
landed; ratchet baseline shrunk). One module gap remains: ``auth``
(#634). ``chip_cascade`` and ``lifecycle_events`` are cross-cutting
concerns that the audit itself owns (the ratchet stays narrow).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKER_PATH = REPO_ROOT / "scripts" / "check_test_classification.py"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"
AUDIT_PATH = REPO_ROOT / "docs" / "quality" / "test-audit.md"
SKILL_PATH = REPO_ROOT / "skills" / "apap-testing-strategy" / "SKILL.md"


def _load_checker():
    spec = importlib.util.spec_from_file_location(
        "check_test_classification", CHECKER_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(root: Path, rel_posix: str, source: str = "") -> Path:
    path = root / Path(rel_posix)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def _tree(root: Path, files: dict[str, str]) -> None:
    for rel, source in files.items():
        _write(root, rel, source)


# ---------------------------------------------------------------------------
# The real tree
# ---------------------------------------------------------------------------


def test_current_tree_passes_with_baseline() -> None:
    """The checker exits 0 on the repository as it stands.

    Every gap that predates the rule must be in BASELINE — otherwise the
    gate would be born red and get deleted within a week.
    """
    checker = _load_checker()
    assert checker.main([str(REPO_ROOT)]) == 0


def test_baseline_entries_are_real_gaps() -> None:
    """BASELINE may not accumulate stale entries.

    Each BASELINE entry must still correspond to a module with no
    integration file. If the integration file lands, the BASELINE entry
    is no longer a gap and must be removed.
    """
    checker = _load_checker()
    integration_dir = REPO_ROOT / "tests" / "integration"
    for module in checker.BASELINE:
        integration_file = integration_dir / f"test_{module}_queries_integration.py"
        assert not integration_file.exists(), (
            f"BASELINE entry '{module}' has a matching integration file "
            f"({integration_file.relative_to(REPO_ROOT)}). Remove the entry "
            f"from scripts/check_test_classification.py to lock in the improvement."
        )


def test_baseline_rationale_cites_audit() -> None:
    """Every BASELINE entry must cite the audit document.

    The rationale is the contract that ties a baselined gap to its source
    of truth. Without a citation, the BASELINE drifts into undocumented
    debt.
    """
    checker = _load_checker()
    for module, reason in checker.BASELINE.items():
        assert "docs/quality/test-audit.md" in reason, (
            f"BASELINE entry '{module}' does not cite docs/quality/test-audit.md. "
            f"Add the citation so the gap is traceable to its source of truth."
        )


def test_in_scope_domains_are_a_superset_of_baseline() -> None:
    """A module in BASELINE must be in IN_SCOPE_DOMAINS, otherwise the
    baseline entry is meaningless noise."""
    checker = _load_checker()
    assert set(checker.BASELINE).issubset(checker.IN_SCOPE_DOMAINS), (
        f"BASELINE has entries not in IN_SCOPE_DOMAINS: "
        f"{set(checker.BASELINE) - checker.IN_SCOPE_DOMAINS}. "
        f"Either add the domain to IN_SCOPE_DOMAINS or remove the BASELINE entry."
    )


def test_in_scope_domains_cite_audit_or_skill() -> None:
    """The IN_SCOPE_DOMAINS list must trace back to the audit or the skill."""
    content = CHECKER_PATH.read_text(encoding="utf-8")
    assert "docs/quality/test-audit.md" in content, (
        "check_test_classification.py must cite docs/quality/test-audit.md "
        "so the IN_SCOPE_DOMAINS list is traceable to its source of truth."
    )
    assert "apap-testing-strategy" in content, (
        "check_test_classification.py must cite the apap-testing-strategy "
        "skill so the gate is enforced under the same norm."
    )


# ---------------------------------------------------------------------------
# Synthetic trees
# ---------------------------------------------------------------------------


def test_passes_when_in_scope_domain_has_integration_file(tmp_path: Path) -> None:
    """A full integration tree (every in-scope module covered) is clean."""
    files = {
        "tests/__init__.py": "",
        "tests/integration/__init__.py": "",
    }
    for module in _load_checker().IN_SCOPE_DOMAINS:
        files[f"tests/integration/test_{module}_queries_integration.py"] = (
            f"# integration atom for {module}\n"
        )
    _tree(tmp_path, files)
    checker = _load_checker()
    violations, notices = checker.check_tree(tmp_path)
    assert violations == []
    # BASELINE entries still produce notices — they are visible until the
    # ratchet itself is shrunk by a future PR.
    assert all("baselined" in n for n in notices)


def test_fails_when_in_scope_domain_has_no_integration_file(tmp_path: Path) -> None:
    """Empty tree: every in-scope domain without an integration file fails."""
    _tree(
        tmp_path,
        {
            "tests/__init__.py": "",
        },
    )
    checker = _load_checker()
    violations, _ = checker.check_tree(tmp_path)
    # Every in-scope domain not in BASELINE must produce a violation.
    expected = sorted(checker.IN_SCOPE_DOMAINS - set(checker.BASELINE))
    assert len(violations) == len(expected)
    for module, violation in zip(expected, violations, strict=True):
        assert violation.startswith(f"{module}:")


def test_baselined_domain_is_a_notice_not_a_violation(tmp_path: Path) -> None:
    """Every baselined module produces a notice, never a violation."""
    # Provide integration files for every non-baselined in-scope module.
    files = {
        "tests/__init__.py": "",
        "tests/integration/__init__.py": "",
    }
    in_scope = _load_checker().IN_SCOPE_DOMAINS
    baselined = _load_checker().BASELINE
    for module in sorted(in_scope - set(baselined)):
        files[f"tests/integration/test_{module}_queries_integration.py"] = (
            f"# integration atom for {module}\n"
        )
    _tree(tmp_path, files)
    checker = _load_checker()
    violations, notices = checker.check_tree(tmp_path)
    assert violations == []
    for module in baselined:
        assert any(module in n for n in notices), (
            f"BASELINE module {module} should appear as a notice."
        )


def test_baselined_entry_disappears_once_integration_lands(tmp_path: Path) -> None:
    """When the integration file lands, the BASELINE entry is silent.

    The ratchet is shrink-only: a BASELINE entry produces a notice as
    long as the integration file is missing. Once the integration file
    lands, the notice for that module disappears — the gate signals the
    developer to remove the BASELINE entry in a follow-up PR.

    As of the #633 / cesiones integration atom, the BASELINE is
    ``{auth}``. Covering auth integration and asserting no notice
    appears exercises the shrink-only contract.
    """
    files = {
        "tests/__init__.py": "",
        "tests/integration/__init__.py": "",
        # Provide coverage for everything EXCEPT the baselined modules.
    }
    in_scope = _load_checker().IN_SCOPE_DOMAINS
    baselined = _load_checker().BASELINE
    for module in sorted(in_scope - set(baselined)):
        files[f"tests/integration/test_{module}_queries_integration.py"] = (
            f"# integration atom for {module}\n"
        )
    # Now also provide auth integration. After this, no baselined
    # module remains.
    files["tests/integration/test_auth_queries_integration.py"] = (
        "# integration atom for auth\n"
    )
    _tree(tmp_path, files)
    checker = _load_checker()
    violations, notices = checker.check_tree(tmp_path)
    assert violations == []
    # No baselined module remains.
    for module in baselined:
        assert all(module not in n for n in notices), (
            f"BASELINE module {module} should not appear in notices once its "
            f"integration file exists."
        )


# ---------------------------------------------------------------------------
# CLI contract
# ---------------------------------------------------------------------------


def test_main_returns_zero_on_clean_tree() -> None:
    checker = _load_checker()
    assert checker.main([str(REPO_ROOT)]) == 0


def test_main_returns_one_on_violation(tmp_path: Path) -> None:
    _tree(
        tmp_path,
        {
            "tests/__init__.py": "",
        },
    )
    checker = _load_checker()
    # tmp_path has zero integration files — every non-baselined in-scope
    # domain violates.
    assert checker.main([str(tmp_path)]) == 1


def test_main_prints_fail_prefix_on_violation(tmp_path: Path, capsys) -> None:
    _tree(
        tmp_path,
        {
            "tests/__init__.py": "",
        },
    )
    checker = _load_checker()
    checker.main([str(tmp_path)])
    captured = capsys.readouterr()
    assert "FAIL" in captured.out
    assert "check_test_classification: " in captured.out
    assert "violation(s)" in captured.out


def test_main_prints_baseline_notices_on_clean_tree(capsys) -> None:
    """Even when the real tree is green, BASELINE entries print as notices."""
    checker = _load_checker()
    checker.main([str(REPO_ROOT)])
    captured = capsys.readouterr()
    for module in checker.BASELINE:
        assert f"NOTE {module}:" in captured.out


# ---------------------------------------------------------------------------
# CI wiring
# ---------------------------------------------------------------------------


def test_ci_workflow_lint_job_runs_check_test_classification() -> None:
    """The CI workflow must invoke the checker.

    Without this wiring, the gate is dead code.
    """
    assert WORKFLOW_PATH.exists(), (
        f"CI workflow not found at {WORKFLOW_PATH.relative_to(REPO_ROOT)}"
    )
    content = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "check_test_classification" in content, (
        "CI workflow does not invoke scripts/check_test_classification.py. "
        "Add a step to the lint job."
    )


def test_audit_and_skill_exist() -> None:
    """The audit document and the skill must exist alongside the ratchet."""
    assert AUDIT_PATH.exists(), (
        f"Audit not found at {AUDIT_PATH.relative_to(REPO_ROOT)}"
    )
    assert SKILL_PATH.exists(), (
        f"Skill not found at {SKILL_PATH.relative_to(REPO_ROOT)}"
    )
