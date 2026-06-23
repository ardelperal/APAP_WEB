from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"
BRANCH_PROTECTION_PATH = REPO_ROOT / ".github" / "branch-protection.md"
DEVELOPMENT_GUIDE_PATH = REPO_ROOT / "docs" / "development.md"


def test_ci_workflow_defines_lint_test_and_build_jobs() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "name: ci" in workflow
    assert "pull_request:" in workflow
    # Both main and staging must trigger CI. main is gated (only the
    # user promotes there) but PRs landing on main still need to be
    # validated; staging is where every change lands first under the
    # project's stagingOnly policy.
    assert "branches: [main, staging]" in workflow
    assert "lint:" in workflow
    assert "test:" in workflow
    assert "build:" in workflow
    assert "python-version-file: pyproject.toml" in workflow
    assert "ruff check ." in workflow
    assert "python -m pytest -W error::DeprecationWarning" in workflow
    assert "python -m build" in workflow


def test_ci_workflow_runs_e2e_job_with_playwright() -> None:
    """The e2e job runs the Playwright suite unconditionally (no gate
    on ``vars.ENABLE_E2E``). The Playwright harness landed in PR #108
    and the e2e job is now always on so every PR gets the visual
    regression net.
    """
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "e2e:" in workflow
    # The e2e job must install + run the Playwright suite. There must
    # be no ``vars.ENABLE_E2E`` gate (the feature flag is gone).
    assert "vars.ENABLE_E2E" not in workflow, (
        "e2e job should always run; the ENABLE_E2E flag has been retired"
    )
    assert "playwright install" in workflow
    assert "playwright" in workflow.lower()
    # And it must actually execute the suite.
    assert "pytest tests/e2e/" in workflow


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

    # The Playwright e2e suite landed in PR #108 and the dev guide
    # now documents the actual runner and the local command, not a
    # future TODO.
    assert "Playwright" in guide
    assert "scripts/dev_server_no_lifespan.py" in guide
    assert "playwright install" in guide


def test_ci_workflow_defines_deploy_job_with_gating() -> None:
    """CD-01: deploy job exists, runs only on push to main, depends on lint+test+build."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "  deploy:" in workflow
    assert "  name: deploy" in workflow
    # needs must reference the three required jobs
    assert "needs: [lint, test, build]" in workflow
    # gating: only on push to main, never on PRs
    # (two if: lines combined with AND are also acceptable, per tasks.md 2.1)
    gating_ok = (
        "if: github.event_name == 'push' && github.ref == 'refs/heads/main' && github.event.pull_request == null" in workflow
        or (
            "if: github.event_name == 'push' && github.ref == 'refs/heads/main'" in workflow
            and "if: github.event.pull_request == null" in workflow
        )
    )
    assert gating_ok, "deploy job must gate on push to main AND exclude pull_request events"


def test_ci_workflow_deploy_job_calls_coolify_webhook() -> None:
    """CD-01: deploy job hits the Coolify webhook with curl -fsS; uses secret COOLIFY_WEBHOOK_URL."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "Trigger Coolify webhook" in workflow
    assert "curl -fsS -X POST" in workflow
    assert "secrets.COOLIFY_WEBHOOK_URL" in workflow


def test_ci_workflow_deploy_job_has_secret_leak_grep() -> None:
    """CD-01: deploy job has a second secret-leak grep step, separate from the lint one."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    # The diagnostic step name appears in the deploy job too
    assert workflow.count("Diagnostic secret-leak scan") >= 2
    # And the deploy-scoped variant targets the build outputs / source (not only .github/)
    assert "grep -rE '(http://|https://|sk-|ghp_)[A-Za-z0-9]+' . --exclude-dir=.git" in workflow
