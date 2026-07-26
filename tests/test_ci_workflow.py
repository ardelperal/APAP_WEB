import shlex
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"
MAKEFILE_PATH = REPO_ROOT / "Makefile"
CHECK_RULES_SCRIPT_PATH = REPO_ROOT / "scripts" / "check_rules.py"
BRANCH_PROTECTION_PATH = REPO_ROOT / ".github" / "branch-protection.md"
DEVELOPMENT_GUIDE_PATH = REPO_ROOT / "docs" / "development.md"


def _make_target_command(target: str) -> str:
    lines = MAKEFILE_PATH.read_text(encoding="utf-8").splitlines()
    start = lines.index(f"{target}:") + 1
    recipe: list[str] = []
    for line in lines[start:]:
        if not line.startswith("\t"):
            break
        recipe.append(line.strip().removesuffix("\\").rstrip())
    return " ".join(recipe)


def _seed_detectors_5_through_8(repo_root: Path) -> None:
    module_dir = repo_root / "app" / "modules" / "demo"
    module_dir.mkdir(parents=True)
    (module_dir / "service.py").write_text(
        "import logging\n"
        "logger = logging.getLogger(__name__)\n"
        "logger.warning('unsafe')\n"
        "print('unsafe')\n",
        encoding="utf-8",
    )
    (repo_root / "app" / "main.py").write_text(
        "response.set_cookie('apap_session', 'token', samesite='lax')\n",
        encoding="utf-8",
    )


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


def test_ci_workflow_test_job_enforces_global_coverage_floor() -> None:
    """Issue #199: the CI ``test`` job must enforce ``fail_under`` from pyproject.

    ``pyproject.toml`` declares ``fail_under = 80`` under
    ``[tool.coverage.report]``, but a pytest run without ``--cov`` never
    measures coverage, so the floor was dead letter in CI. The test job
    must:

    1. run pytest with coverage over ``app/`` (``--cov=app``),
    2. write ``coverage.json`` (``--cov-report=json``) so the
       CRITICAL_HELPERS gate (``scripts/pytest_plugin/coverage_gate.py``,
       AGENTS.md rule 11) keeps working — the plugin is a no-op when
       ``coverage.json`` is absent,
    3. fail the job below the global floor via an explicit
       ``--cov-fail-under`` that matches ``fail_under`` in pyproject
       (explicit because pytest-cov only reliably enforces the flag,
       not the config-file value).

    Removing any of these from ci.yml is a blocked change (AGENTS.md
    rule 19).
    """
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
        pyproject = tomllib.load(fh)
    fail_under = pyproject["tool"]["coverage"]["report"]["fail_under"]

    # The declared floor itself must not silently drift below 80.
    assert fail_under >= 80

    # Scope to the test job's executable lines only: slice the job
    # section and drop YAML comments, so a comment that merely mentions
    # the flags (like the explanatory block above the run: step) can
    # never satisfy these assertions.
    test_job_start = workflow.index("\n  test:")
    test_job = workflow[test_job_start : workflow.index("\n  build:", test_job_start)]
    executable = "\n".join(
        line for line in test_job.splitlines() if not line.lstrip().startswith("#")
    )

    # Coverage must be measured over the app package...
    assert "--cov=app" in executable
    # ...must produce coverage.json for the CRITICAL_HELPERS gate...
    assert "--cov-report=json" in executable
    # ...and must enforce the same floor pyproject declares.
    assert f"--cov-fail-under={fail_under}" in executable


def test_ci_workflow_lint_job_runs_check_rules_gate(tmp_path: Path) -> None:
    """Issue #200: the CI ``lint`` job must gate on ``scripts/check_rules.py``.

    The APAP001/APAP003 custom rules (plus Detectors 2-8 of the AST
    linter) are documented as "the authoritative lint gate" in
    ``pyproject.toml`` and AGENTS.md, but until this test the linter
    only ran locally via ``make check-rules`` — CI never executed it,
    so a violation could land on main with a green build. The lint job
    must run the linter over the REPO ROOT (``.``), not ``app``:
    Detectors 5-8 resolve ``app/``-relative paths against the scanned
    root, so ``check_rules.py app`` silently disables the APAP003 /
    print / CSRF detectors. Default excludes (``DEFAULT_EXCLUDES`` +
    ``.check_rulesignore``) silence the known false positives.

    Removing this step from ci.yml is a blocked change (AGENTS.md
    rule 20).
    """
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    # Scope to the lint job's executable lines only (same rationale as
    # test_ci_workflow_test_job_enforces_global_coverage_floor): slice
    # the job section and drop YAML comments so a comment mentioning
    # the command can never satisfy the assertion.
    lint_job_start = workflow.index("\n  lint:")
    lint_job = workflow[lint_job_start : workflow.index("\n  test:", lint_job_start)]
    executable = "\n".join(
        line for line in lint_job.splitlines() if not line.lstrip().startswith("#")
    )

    make_command = _make_target_command("check-rules")
    command = shlex.split(make_command)
    command[0] = sys.executable
    command[1] = str(CHECK_RULES_SCRIPT_PATH)
    _seed_detectors_5_through_8(tmp_path)
    result = subprocess.run(
        command,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    expected_rule_ids = {
        "apap003_raw_logger_call",
        "print_in_app",
        "csrf_middleware_registered",
        "csrf_samesite_strict",
    }
    missing_rule_ids = {
        rule_id
        for rule_id in expected_rule_ids
        if f": {rule_id}:" not in result.stdout
    }
    assert result.returncode == 1 and not missing_rule_ids, (
        "The make check-rules recipe must activate Detectors 5-8 from the "
        f"repository root; exit={result.returncode}, missing={sorted(missing_rule_ids)}, "
        f"stdout={result.stdout!r}, stderr={result.stderr!r}"
    )

    ci_command = "python scripts/check_rules.py ."
    normalized_make_command = make_command.replace("$(PYTHON)", "python", 1)
    assert ci_command in executable, (
        "The lint job must run the AGENTS.md rule linter over the repo "
        "root (python scripts/check_rules.py .) so APAP001/APAP003 and "
        "Detectors 2-8 gate CI, not just local `make check-rules` runs."
    )
    assert normalized_make_command == ci_command, (
        "make check-rules must invoke the same repository-root command as CI; "
        f"got {normalized_make_command!r}"
    )


def test_ci_workflow_defines_typecheck_job_running_mypy() -> None:
    """Issue #201: the CI ``typecheck`` job must gate on mypy.

    The codebase is fully annotated (``from __future__ import
    annotations``, dataclasses, ``Final``) but until this test no type
    checker ever ran: annotations were documentation without
    verification. The ``typecheck`` job must run the exact same command
    as ``make typecheck`` (``python -m mypy``, scope and flags declared
    once in ``pyproject.toml`` ``[tool.mypy]``) so local and CI results
    cannot drift.

    Removing this job from ci.yml is a blocked change (AGENTS.md
    rule 24).
    """
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "\n  typecheck:" in workflow, (
        "ci.yml must define a typecheck job (issue #201, AGENTS.md rule 24)"
    )

    # Scope to the typecheck job's executable lines only (same rationale
    # as test_ci_workflow_lint_job_runs_check_rules_gate): slice the job
    # section and drop YAML comments so a comment mentioning mypy can
    # never satisfy the assertion.
    typecheck_job_start = workflow.index("\n  typecheck:")
    typecheck_job = workflow[typecheck_job_start : workflow.index("\n  test:", typecheck_job_start)]
    executable = "\n".join(
        line for line in typecheck_job.splitlines() if not line.lstrip().startswith("#")
    )

    # The job must install the dev extra like every other job (mypy is
    # a dev dependency) and run the config-driven mypy command.
    assert 'python -m pip install -e ".[dev]"' in executable
    assert "python -m mypy" in executable, (
        "The typecheck job must run `python -m mypy` (scope lives in "
        "pyproject.toml [tool.mypy]) — the same command as `make typecheck`."
    )

    # mypy itself must be a pinned dev dependency so CI actually gets it.
    with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
        pyproject = tomllib.load(fh)
    dev_deps = pyproject["project"]["optional-dependencies"]["dev"]
    assert any(dep.startswith("mypy") for dep in dev_deps), (
        "pyproject.toml [project.optional-dependencies] dev must declare mypy"
    )
    # And the scope must be declared in config, not ad-hoc CLI args:
    # app/ and migration/ are both gated (issue #201 scope decision).
    mypy_files = pyproject["tool"]["mypy"]["files"]
    assert "app" in mypy_files
    assert "migration" in mypy_files


def test_ci_workflow_defines_deploy_job_with_gating() -> None:
    """CD-01: deploy job exists, runs only on push to main, depends on lint+typecheck+test+build."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "  deploy:" in workflow
    assert "  name: deploy" in workflow
    # needs must reference the five required jobs (typecheck added by
    # issue #201; concurrency added by issue #282 — TOCTOU gate).
    assert "needs: [lint, typecheck, test, concurrency, build]" in workflow
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


# ---------------------------------------------------------------------------
# PostgreSQL TOCTOU regression gate — issue #282
# ---------------------------------------------------------------------------


def test_ci_workflow_defines_concurrency_job_with_postgres() -> None:
    """REQ-1 / REQ-3: the CI ``concurrency`` job provisions PostgreSQL and
    runs the TOCTOU regression guard without deselection.

    The ``test`` job deliberately omits PostgreSQL and deselects
    ``test_voluntarios_concurrent.py`` so the suite stays fast. The
    ``concurrency`` job exists precisely to exercise the same test with a
    real PostgreSQL service container, restoring the TOCTOU regression
    signal.

    Option A (issue #282 fix): the test exercises the SQL层面的 TOCTOU
    contract directly via asyncpg against the postgres service container.
    This avoids requiring InsForge (a separate BaaS) to be running in CI.
    Full HTTP round-trip coverage is handled by staging E2E where InsForge
    is available.

    This test asserts the contract that makes the signal real:

    (a) ``concurrency:`` job exists with a ``postgres:16-alpine`` service.
    (b) The job runs ``pytest tests/test_voluntarios_concurrent.py`` with
        no ``--deselect`` flag.
    (c) The job environment sets ``APAP_TEST_DATABASE_URL`` (database DSN).
    (d) The job does NOT set ``APAP_E2E_BASE_URL`` or ``APAP_E2E_SESSION_TOKEN``
        (Option A: the test uses asyncpg, not httpx — no HTTP endpoint needed).

    No custom pg_isready healthcheck is expected: postgres:16-alpine ships
    with a working default pg_isready. A custom --health-cmd with no --user
    flag causes pg_isready to run as root, failing with
    "FATAL: role \"root\" does not exist".
    """
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    # (a) concurrency: job with postgres:16-alpine service.
    assert "\n  concurrency:" in workflow, (
        "ci.yml must define a concurrency job (issue #282, REQ-1)"
    )
    assert "postgres:16-alpine" in workflow, (
        "concurrency job must provision postgres:16-alpine service "
        "(CVE-2024-7348 patched floor, AGENTS.md §8)"
    )

    # Slice to the concurrency job section only.
    concurrency_start = workflow.index("\n  concurrency:")
    # Find the next top-level job or end of file.
    remaining = workflow[concurrency_start + len("\n  concurrency:"):]
    next_job_match = None
    for marker in ["\n  lint:", "\n  typecheck:", "\n  test:", "\n  build:", "\n  e2e:", "\n  deploy:"]:
        idx = remaining.index(marker) if marker in remaining else None
        if idx is not None:
            if next_job_match is None or idx < next_job_match:
                next_job_match = idx
    concurrency_section = remaining[:next_job_match] if next_job_match is not None else remaining

    # (b) No --deselect for test_voluntarios_concurrent.py in the concurrency job.
    # The test job deselects it (expected); the concurrency job must NOT.
    has_concurrent_pytest = "pytest tests/test_voluntarios_concurrent.py" in concurrency_section
    has_deselect = "--deselect tests/test_voluntarios_concurrent.py" in concurrency_section
    assert has_concurrent_pytest, (
        "concurrency job must run pytest tests/test_voluntarios_concurrent.py"
    )
    assert not has_deselect, (
        "concurrency job must NOT deselect test_voluntarios_concurrent.py; "
        "the whole point of this job is to run it with a real PostgreSQL instance"
    )

    # (c) APAP_TEST_DATABASE_URL env var set in the job.
    assert "APAP_TEST_DATABASE_URL" in concurrency_section, (
        "concurrency job must set APAP_TEST_DATABASE_URL environment variable "
        "(Option A: asyncpg direct SQL test, no HTTP endpoint needed)"
    )

    # (d) No APAP_E2E_BASE_URL or APAP_E2E_SESSION_TOKEN in the concurrency job
    # (Option A uses asyncpg, not httpx — these env vars are no longer needed).
    assert "APAP_E2E_BASE_URL" not in concurrency_section, (
        "concurrency job must NOT set APAP_E2E_BASE_URL; "
        "Option A test uses asyncpg directly, not httpx against an HTTP endpoint"
    )
    assert "APAP_E2E_SESSION_TOKEN" not in concurrency_section, (
        "concurrency job must NOT set APAP_E2E_SESSION_TOKEN; "
        "Option A test uses asyncpg directly, not httpx with session cookies"
    )
