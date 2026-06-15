from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"
BRANCH_PROTECTION_PATH = REPO_ROOT / ".github" / "branch-protection.md"
DEVELOPMENT_GUIDE_PATH = REPO_ROOT / "docs" / "development.md"


def test_ci_workflow_defines_lint_test_and_build_jobs() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "name: ci" in workflow
    assert "pull_request:" in workflow
    assert "branches: [main]" in workflow
    assert "lint:" in workflow
    assert "test:" in workflow
    assert "build:" in workflow
    assert "python-version-file: pyproject.toml" in workflow
    assert "ruff check ." in workflow
    assert "python -m pytest -W error::DeprecationWarning" in workflow
    assert "python -m build" in workflow


def test_ci_workflow_keeps_e2e_hook_disabled_until_playwright_lands() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "e2e:" in workflow
    assert "if: ${{ vars.ENABLE_E2E == 'true' }}" in workflow
    assert "run: |" in workflow
    assert "TODO(E2E-01): enable when Playwright harness lands" in workflow


def test_ci_workflow_includes_diagnostic_secret_leak_scan() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "Diagnostic secret-leak scan" in workflow
    assert "grep -rE '(http://|https://|sk-|ghp_)[A-Za-z0-9]+' .github/ || true" in workflow


def test_branch_protection_note_lists_required_ci_checks() -> None:
    note = BRANCH_PROTECTION_PATH.read_text(encoding="utf-8")

    assert "ci / lint" in note
    assert "ci / test" in note
    assert "ci / build" in note
    assert "Settings → Branches → Branch protection rules" in note


def test_development_guide_documents_e2e_ci_hook() -> None:
    guide = DEVELOPMENT_GUIDE_PATH.read_text(encoding="utf-8")

    assert "TODO(E2E-01)" in guide
    assert "Playwright" in guide
