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
    """CD-01: deploy job hits the Coolify manual github webhook.

    Coolify v4 manual webhook endpoint verifies the raw JSON body against
    X-Hub-Signature-256 using the application's manual_webhook_secret_github,
    so the step must use both COOLIFY_WEBHOOK_URL and COOLIFY_WEBHOOK_SECRET
    and POST a real JSON body (no bare curl).

    The signing + POST logic lives in ``scripts/coolify_webhook.py`` (so
    the prod and test paths share the same code). The workflow just
    sets the env vars and shells out to that module.
    """
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "Trigger Coolify webhook" in workflow
    assert "secrets.COOLIFY_WEBHOOK_URL" in workflow
    assert "secrets.COOLIFY_WEBHOOK_SECRET" in workflow
    # The workflow MUST delegate to the unit-tested signing module,
    # NOT inline the HMAC + urllib code in a heredoc. Pinned by
    # tests/test_coolify_webhook.py.
    assert "python scripts/coolify_webhook.py" in workflow
    # The inline heredoc + urllib path is forbidden.
    assert "python - <<'PY'" not in workflow
    assert "urllib.request.urlopen" not in workflow
    # A bare unsigned curl is no longer acceptable.
    assert "curl -fsS -X POST \"$COOLIFY_WEBHOOK_URL\"" not in workflow


def test_ci_workflow_missing_webhook_secret_is_a_failure() -> None:
    """Missing COOLIFY_WEBHOOK_SECRET MUST fail the deploy step.

    Pinned by spec (ci-cd-pipeline/spec.md, Scenario "Missing webhook
    secret blocks production deploy"). Without the secret, the HMAC
    signature would be computed over an empty key, and Coolify v4
    would reject every payload. Loud fail at CI beats silent fail at
    the healthcheck-driven rollback.
    """
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    # The deploy step must check the secret specifically (not just the
    # URL) and emit a ``::error::`` annotation with a clear message,
    # then exit 1.
    assert "COOLIFY_WEBHOOK_SECRET" in workflow
    assert "::error::COOLIFY_WEBHOOK_SECRET" in workflow
    assert "exit 1" in workflow


def test_ci_workflow_payload_shape_matches_coolify_expectation() -> None:
    """The workflow MUST pass the keys Coolify's manualWebhookApplications reads.

    Pinned by spec (ci-cd-pipeline/spec.md, Requirement "Coolify Webhook
    Signing Contract" > Scenario "Payload shape"). The signing logic
    lives in ``scripts/coolify_webhook.py::build_push_payload`` and is
    pinned by tests/test_coolify_webhook.py::test_build_push_payload_includes_required_keys.
    The workflow just sets the env vars that the module reads.
    """
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    # The workflow must forward the env vars the module needs to build
    # the payload (ref, sha, repository, commit message).
    assert "GITHUB_REF:" in workflow
    assert "GITHUB_SHA:" in workflow
    assert "GITHUB_REPOSITORY:" in workflow
    assert "COMMIT_MESSAGE:" in workflow


def test_ci_workflow_deploy_job_has_secret_leak_grep() -> None:
    """CD-01: deploy job has a second secret-leak grep step, separate from the lint one."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    # The diagnostic step name appears in the deploy job too
    assert workflow.count("Diagnostic secret-leak scan") >= 2
    # And the deploy-scoped variant targets the build outputs / source (not only .github/)
    assert "grep -rE '(http://|https://|sk-|ghp_)[A-Za-z0-9]+' . --exclude-dir=.git" in workflow
